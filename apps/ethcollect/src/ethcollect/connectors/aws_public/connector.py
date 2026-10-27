"""AWS Public Blockchain Data: daily Ethereum Parquet in s3://aws-public-blockchain/v1.0/eth/.

Anonymous S3, region us-east-2. A day of `transactions` is one ~800 MB file of about 2M rows
in ~7 row groups, so this connector never reads a whole day: it reads one random row group,
and only the columns it needs (a few seconds per day from a laptop). Full-day scans, such as
filtering `logs` by contract, take far too long remotely; use an explorer's getLogs instead.

Modes:
  addresses  sample distinct addresses from random days -> `addresses` (sample_reason=random)
  transfers  rows from one random row group of given days -> `transfers`
  scan       whole days, cheap columns only: every row touching a risk-labeled address or a
             hash-picked random address, capped per address -> `transfers` + `addresses`.
             This is how history is gathered without an explorer (see references/aws-public.md).
"""

from __future__ import annotations

import hashlib
import io
import random
import zlib
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from itertools import pairwise

import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq
from pyarrow import fs as pafs

from ethcollect import tables

KIND = "chain"
SUMMARY = "AWS public Ethereum Parquet (no account): random addresses or transfers by day"
DEFAULT_RATE = 5.0
BUCKET, PREFIX, REGION = "aws-public-blockchain", "v1.0/eth", "us-east-2"
# `input` (calldata) is left out: it is most of a row group's bytes, and reading it made one
# day take ~5 minutes instead of seconds. Hence method_id is null for this source.
TX_COLS = ["hash", "block_number", "block_timestamp", "from_address", "to_address", "value",
           "receipt_status"]
TOKEN_COLS = ["transaction_hash", "log_index", "block_number", "block_timestamp",
              "from_address", "to_address", "value", "token_address"]
# Scan mode leaves out the hash columns too (hash and transaction_hash are ~400 MB of a day's
# ~850 MB). External transactions get their hash back over RPC after capping; token transfers
# keep tx_hash null and are identified by (block_number, log_index).
SCAN_TX_COLS = ["block_number", "transaction_index", "block_timestamp", "from_address",
                "to_address", "value", "receipt_status"]
SCAN_TOKEN_COLS = ["log_index", "block_number", "block_timestamp", "from_address",
                   "to_address", "value", "token_address"]


def add_arguments(p) -> None:
    p.add_argument("--mode", choices=["addresses", "transfers", "scan"], default="addresses")
    p.add_argument("--date", action="append", default=[], type=date.fromisoformat,
                   help="a day to read (repeatable); default: --days days in the window")
    p.add_argument("--days", type=int, default=12,
                   help="days to pick: random (addresses, transfers) or one per equal slice of "
                        "the window (scan); default 12")
    p.add_argument("--per-day", type=int, default=60,
                   help="addresses per day in addresses mode; rows per day in transfers mode")
    p.add_argument("--random-rate", type=float, default=1 / 5000,
                   help="scan: share of all addresses picked as random background (default "
                        "1/5000, about 100-150 a day)")
    p.add_argument("--cap", type=int, default=5,
                   help="scan: latest transfers kept per watched or random address")
    p.add_argument("--workers", type=int, default=2, help="scan: days read at once")
    p.add_argument("--seed", type=int, default=7)


def _fs() -> pafs.S3FileSystem:
    return pafs.S3FileSystem(anonymous=True, region=REGION)


def pick_days(since: date, until: date, n: int, rng: random.Random) -> list[date]:
    span = (until - since).days
    days = sorted(rng.sample(range(span), min(n, span)))
    return [since + timedelta(days=d) for d in days]


def read_group(ctx, table: str, day: date, columns: list[str], rng: random.Random) -> pa.Table:
    """One random row group of one day's file, cached as Parquet under raw/aws-public/."""
    s3 = _fs()
    folder = f"{BUCKET}/{PREFIX}/{table}/date={day.isoformat()}/"
    found = s3.get_file_info(pafs.FileSelector(folder))
    files = sorted(f.path for f in found if f.path.endswith(".parquet"))
    if not files:
        raise FileNotFoundError(f"no parquet under s3://{folder}")
    path = rng.choice(files)
    meta = pq.ParquetFile(path, filesystem=s3)
    group = rng.randrange(meta.metadata.num_row_groups)
    key = f"s3://{path}#rg={group}&cols={','.join(columns)}"

    def fetch() -> bytes:
        buf = io.BytesIO()
        pq.write_table(meta.read_row_group(group, columns=columns), buf)
        return buf.getvalue()

    return pq.read_table(io.BytesIO(ctx.cached(key, fetch, ".parquet")))


def spread_days(since: date, until: date, n: int, rng: random.Random) -> list[date]:
    """One random day in each of n equal slices of the window."""
    span = (until - since).days
    n = min(n, span)
    edges = [since + timedelta(days=span * i // n) for i in range(n + 1)]
    return [lo + timedelta(days=rng.randrange(max((hi - lo).days, 1)))
            for lo, hi in pairwise(edges)]


def picked(address: str, seed: int, rate: float) -> bool:
    """Hash-based random pick: the same address is picked (or not) on every day it appears."""
    return zlib.crc32(f"{seed}:{address}".encode()) < rate * 2**32


def _addr(col: str, padded: bool) -> pl.Expr:
    c = pl.col(col).str.to_lowercase()
    if padded:
        c = pl.when(c.str.len_chars() == 66).then(pl.lit("0x") + c.str.slice(26)).otherwise(c)
    return c.alias(col)


def match_rows(df: pl.DataFrame, watch: set[str], seed: int, rate: float, cap: int,
               padded: bool, order: list[str]) -> tuple[pl.DataFrame, set[str]]:
    """Rows of one day touching a watched or randomly picked address, latest `cap` per address.
    Returns the rows and the random picks seen."""
    df = df.with_columns(_addr("from_address", padded), _addr("to_address", padded))
    pool = set(df["from_address"].drop_nulls()) | set(df["to_address"].drop_nulls())
    randoms = {a for a in pool - watch if picked(a, seed, rate)}
    owners = watch | randoms
    parts = [df.filter(pl.col(side).is_in(owners)).with_columns(pl.col(side).alias("_owner"))
             for side in ("from_address", "to_address")]
    both = pl.concat(parts).sort(["_owner", *order], descending=True)
    top = both.group_by("_owner", maintain_order=True).head(cap).drop("_owner").unique(
        subset=order, maintain_order=True)
    return top, randoms & owners_of(top)


def owners_of(df: pl.DataFrame) -> set[str]:
    return set(df["from_address"].drop_nulls()) | set(df["to_address"].drop_nulls())


def scan_day(ctx, day: date, table: str, watch: set[str], args) -> pl.DataFrame:
    """One day of one table, read a row group at a time, reduced to matched rows (cached)."""
    padded = table == "token_transfers"
    cols, order = ((SCAN_TOKEN_COLS, ["block_number", "log_index"]) if padded
                   else (SCAN_TX_COLS, ["block_number", "transaction_index"]))
    fp = hashlib.sha1("\n".join(sorted(watch)).encode()).hexdigest()[:12]
    key = (f"scan:{table}:{day}:watch={fp}:rate={args.random_rate}:seed={args.seed}"
           f":cap={args.cap}")

    def fetch() -> bytes:
        s3 = _fs()
        folder = f"{BUCKET}/{PREFIX}/{table}/date={day.isoformat()}/"
        files = sorted(f.path for f in s3.get_file_info(pafs.FileSelector(folder))
                       if f.path.endswith(".parquet"))
        if not files:
            raise FileNotFoundError(f"no parquet under s3://{folder}")
        # whole files at once: pyarrow fetches all row groups' columns in parallel, ~2.5x
        # faster than a row group at a time (~1-1.5 GB of memory for a day of token rows)
        parts = [pl.from_arrow(pq.read_table(p, filesystem=s3, columns=cols, pre_buffer=True))
                 for p in files]
        day_rows, _ = match_rows(pl.concat(parts), watch, args.seed, args.random_rate,
                                 args.cap, padded, order)
        buf = io.BytesIO()
        day_rows.write_parquet(buf)
        return buf.getvalue()

    return pl.read_parquet(io.BytesIO(ctx.cached(key, fetch, ".parquet")))


def fill_tx_hashes(ctx, tx: pl.DataFrame) -> pl.DataFrame:
    """Hashes of external transactions by (block, index), 50 per JSON-RPC batch, cached."""
    from ethcollect.connectors.rpc.connector import ENDPOINT, Rpc
    from ethcollect.context import env

    rpc = Rpc(ctx, env("ETH_RPC_URL") or ENDPOINT)
    keys = tx.select("block_number", "transaction_index").rows()
    hashes = []
    for i in range(0, len(keys), 50):
        chunk = keys[i:i + 50]
        got = rpc.batch([("eth_getTransactionByBlockNumberAndIndex", [hex(b), hex(t)])
                         for b, t in chunk], cache=True)
        hashes += [g["hash"] if g else None for g in got]
    return tx.with_columns(pl.Series("hash", hashes, dtype=pl.String))


def scan(ctx, args, days: list[date]) -> None:
    labels = tables.load(ctx.out, "labels")
    watch = set(labels.filter(pl.col("is_risk"))["address"].to_list())
    print(f"  watching {len(watch)} risk-labeled addresses on {len(days)} days")

    def one(d: date) -> tuple[pl.DataFrame, pl.DataFrame]:
        tx = scan_day(ctx, d, "transactions", watch, args)
        tok = scan_day(ctx, d, "token_transfers", watch, args)
        print(f"  {d}: {tx.height} transactions, {tok.height} token transfers kept", flush=True)
        return tx, tok

    with ThreadPoolExecutor(max(args.workers, 1)) as pool:
        got = list(pool.map(one, days))
    order_tx, order_tok = ["block_number", "transaction_index"], ["block_number", "log_index"]
    tx, rand_tx = match_rows(pl.concat([g[0] for g in got]), watch, args.seed,
                             args.random_rate, args.cap, False, order_tx)
    tok, rand_tok = match_rows(pl.concat([g[1] for g in got]), watch, args.seed,
                               args.random_rate, args.cap, False, order_tok)
    # an address keeps its latest `cap` overall, counting ETH and token rows together
    rows = transfers_from(fill_tx_hashes(ctx, tx),
                          tok.with_columns(pl.lit(None, pl.String).alias("transaction_hash")))
    missing = sum(1 for r in rows if r["kind"] == "external" and not r["tx_hash"])
    if missing:
        ctx.warn(f"{missing} external transactions got no hash from RPC and were dropped")
        rows = [r for r in rows if r["kind"] != "external" or r["tx_hash"]]
    df = tables.frame("transfers", rows)
    owned = []
    for side in ("from_address", "to_address"):
        owned.append(df.filter(pl.col(side).is_in(watch | rand_tx | rand_tok))
                     .with_columns(pl.col(side).alias("_owner")))
    df = (pl.concat(owned).sort(["_owner", "ts"], descending=[False, True])
          .group_by("_owner", maintain_order=True).head(args.cap).drop("_owner")
          .unique(subset=tables.KEYS["transfers"], maintain_order=True))
    tables.write(ctx.out, "transfers", ctx.source, df)
    randoms = sorted((rand_tx | rand_tok) & owners_of(df))
    tables.write(ctx.out, "addresses", ctx.source, tables.frame("addresses", [
        {"address": a, "is_contract": None, "first_seen": None, "sample_reason": "random",
         "source": "aws-public"} for a in randoms]))
    ctx.note("transfers", df.height)
    ctx.note("risk_addresses_active", len(watch & owners_of(df)))
    ctx.note("random_addresses", len(randoms))


def sample_addresses(df: pl.DataFrame, n: int, rng: random.Random) -> list[str]:
    pool = sorted({a for col in ("from_address", "to_address") for a in df[col].to_list() if a})
    return rng.sample(pool, min(n, len(pool)))


def unpad(topic: str | None) -> str | None:
    """token_transfers stores from/to as 32-byte log topics (0x + 24 zeros + the address)."""
    if topic and len(topic) == 66 and topic[2:26].strip("0") == "":
        return tables.norm("0x" + topic[26:])
    return tables.norm(topic)


def transfers_from(tx: pl.DataFrame, tok: pl.DataFrame) -> list[dict]:
    rows = []
    for r in tx.iter_rows(named=True):
        rows.append({
            "tx_hash": r["hash"], "log_index": -1, "block_number": r["block_number"],
            "ts": r["block_timestamp"].replace(tzinfo=UTC),
            "from_address": tables.norm(r["from_address"]),
            "to_address": tables.norm(r["to_address"]), "kind": "external", "asset": "ETH",
            "asset_symbol": "ETH", "amount": (r["value"] or 0) / 1e18, "decimals": 18,
            "usd_approx": None, "method_id": None, "status": r["receipt_status"],
            "source": "aws-public"})
    for r in tok.iter_rows(named=True):
        token = tables.norm(r["token_address"])
        dec = 6 if tables.STABLECOINS.get(token) in {"USDT", "USDC"} else None
        amount = (r["value"] or 0) / 10**dec if dec else r["value"]
        rows.append({
            "tx_hash": r["transaction_hash"], "log_index": r["log_index"],
            "block_number": r["block_number"], "ts": r["block_timestamp"].replace(tzinfo=UTC),
            "from_address": unpad(r["from_address"]),
            "to_address": unpad(r["to_address"]), "kind": "erc20", "asset": token,
            "asset_symbol": tables.STABLECOINS.get(token), "amount": amount, "decimals": dec,
            "usd_approx": amount if dec else None, "method_id": None, "status": 1,
            "source": "aws-public"})
    return rows


def run(ctx, args) -> None:
    rng = random.Random(args.seed)
    choose = spread_days if args.mode == "scan" else pick_days
    days = args.date or choose(ctx.since, ctx.until, args.days, rng)
    if args.limit:
        days = days[: args.limit]
    ctx.note("days", [d.isoformat() for d in days])
    if args.mode == "scan":
        scan(ctx, args, days)
        return
    if args.mode == "addresses":
        now = datetime.now(UTC)
        rows = []
        for d in days:
            df = pl.from_arrow(read_group(ctx, "transactions", d,
                                          ["from_address", "to_address"], rng))
            picked = sample_addresses(df, args.per_day, rng)
            print(f"  {d}: {len(picked)} addresses from {df.height} rows")
            rows += [{"address": tables.norm(a), "is_contract": None, "first_seen": None,
                      "sample_reason": "random", "source": "aws-public"} for a in picked]
        df = tables.frame("addresses", rows)
        tables.write(ctx.out, "addresses", ctx.source, df)
        ctx.note("addresses", df.height)
        ctx.note("fetched_at", now.isoformat())
        return
    rows = []
    for d in days:
        tx = pl.from_arrow(read_group(ctx, "transactions", d, TX_COLS, rng)).head(args.per_day)
        tok = pl.from_arrow(read_group(ctx, "token_transfers", d, TOKEN_COLS, rng))
        rows += transfers_from(tx, tok.head(args.per_day))
        print(f"  {d}: {tx.height} transactions, {min(tok.height, args.per_day)} token rows")
    df = tables.frame("transfers", rows)
    tables.append(ctx.out, "transfers", ctx.source, df)
    ctx.note("transfers", df.height)
