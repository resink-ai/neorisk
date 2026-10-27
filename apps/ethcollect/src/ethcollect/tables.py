"""The three shared tables: their columns, the label vocabulary, and how they are stored.

Every connector writes one Parquet file per (table, source), replacing that source's previous
file, so a connector rerun never duplicates rows and never touches another source's rows.
`load` unions all sources of a table and de-duplicates on the table's key, keeping the
first source in name order.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import duckdb
import polars as pl

TRANSFERS = {
    "tx_hash": pl.String,
    "log_index": pl.Int64,  # -1 for the transaction itself; log or trace index otherwise
    "block_number": pl.Int64,
    "ts": pl.Datetime("us", "UTC"),
    "from_address": pl.String,
    "to_address": pl.String,
    "kind": pl.String,  # external | internal | erc20
    "asset": pl.String,  # "ETH" or the token contract
    "asset_symbol": pl.String,
    "amount": pl.Float64,  # in whole units when decimals are known, raw units otherwise
    "decimals": pl.Int64,
    "usd_approx": pl.Float64,  # stablecoins only for now
    "method_id": pl.String,
    "status": pl.Int64,  # 1 ok, 0 failed
    "source": pl.String,
}

ADDRESSES = {
    "address": pl.String,
    "is_contract": pl.Boolean,
    "first_seen": pl.Datetime("us", "UTC"),
    "sample_reason": pl.String,  # seed | random | counterparty | given
    "source": pl.String,
}

LABELS = {
    "address": pl.String,
    "label_kind": pl.String,
    "is_risk": pl.Boolean,
    "source": pl.String,
    "source_ref": pl.String,  # tag, comment or URL the claim came from
    "trust": pl.Float64,
    "observed_at": pl.Date,
    "date_known": pl.Boolean,  # False: observed_at is the fetch date
}

SCHEMAS = {"transfers": TRANSFERS, "addresses": ADDRESSES, "labels": LABELS}
KEYS = {
    # block_number because aws-public token rows have no tx_hash; (block, log_index) is unique
    "transfers": ["tx_hash", "block_number", "log_index", "kind"],
    "addresses": ["address"],
    "labels": ["address", "label_kind", "source"],
}

TRUST = {"high": 0.9, "medium": 0.6, "low": 0.3}
RISK_KINDS = {"sanctioned", "scam", "phishing", "hack", "laundering", "frozen"}
SERVICE_KINDS = {"exchange", "bridge", "mixer", "dex", "service"}
LABEL_KINDS = RISK_KINDS | SERVICE_KINDS

STABLECOINS = {
    "0xdac17f958d2ee523a2206206994597c13d831ec7": "USDT",
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": "USDC",
    "0x6b175474e89094c44da98b954eedeac495271d0f": "DAI",
}


def norm(address: str | None) -> str | None:
    """Lower-case 0x addresses; anything that is not a 20-byte hex address becomes None."""
    if not address:
        return None
    a = address.strip().lower()
    if len(a) != 42 or not a.startswith("0x"):
        return None
    try:
        int(a, 16)
    except ValueError:
        return None
    return a


def frame(table: str, rows: list[dict]) -> pl.DataFrame:
    schema = SCHEMAS[table]
    df = pl.DataFrame(rows, schema=schema, orient="row") if rows else pl.DataFrame(schema=schema)
    return df.unique(subset=KEYS[table], keep="first", maintain_order=True)


def label_rows(
    addresses,
    *,
    kind: str,
    source: str,
    trust: str,
    ref: str | None = None,
    observed_at=None,
) -> list[dict]:
    """Label rows for many addresses that share one claim; bad addresses are skipped."""
    if kind not in LABEL_KINDS:
        raise ValueError(f"unknown label kind {kind!r}")
    today = datetime.now(UTC).date()
    out = []
    for a in addresses:
        a = norm(a)
        if a:
            out.append({
                "address": a, "label_kind": kind, "is_risk": kind in RISK_KINDS,
                "source": source, "source_ref": ref, "trust": TRUST[trust],
                "observed_at": observed_at or today, "date_known": observed_at is not None,
            })
    return out


def path(root: Path, table: str, source: str) -> Path:
    return Path(root) / table / f"{source}.parquet"


def write(root: Path, table: str, source: str, df: pl.DataFrame) -> Path:
    """Replace this source's rows of `table`."""
    p = path(root, table, source)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.select(list(SCHEMAS[table])).write_parquet(p)
    return p


def append(root: Path, table: str, source: str, df: pl.DataFrame) -> Path:
    """Add rows to this source's file, de-duplicated on the table key (new rows win)."""
    p = path(root, table, source)
    if p.exists():
        df = pl.concat([df.select(list(SCHEMAS[table])), pl.read_parquet(p)], how="vertical")
        df = df.unique(subset=KEYS[table], keep="first", maintain_order=True)
    return write(root, table, source, df)


def db() -> duckdb.DuckDBPyConnection:
    """A DuckDB connection that hands timestamps back in UTC, not the machine's zone."""
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    return con


def load(root: Path, table: str) -> pl.DataFrame:
    files = sorted((Path(root) / table).glob("*.parquet"))
    if not files:
        return pl.DataFrame(schema=SCHEMAS[table])
    names = ", ".join(f"'{f}'" for f in files)
    if table == "addresses":  # merge what each source knows about an address
        sql = (
            "select address, bool_or(is_contract) is_contract, min(first_seen) first_seen, "
            "arg_min(sample_reason, case sample_reason when 'seed' then 0 when 'random' then 1 "
            "when 'given' then 2 when 'counterparty' then 3 end) sample_reason, "
            "array_to_string(list_sort(list(distinct source)), ',') as \"source\" "
            f"from read_parquet([{names}], union_by_name = true) group by address"
        )
        return pl.from_arrow(db().sql(sql).arrow()).select(list(ADDRESSES))
    keys = ", ".join(KEYS[table])
    sql = (
        f"select * exclude (rn) from (select *, row_number() over (partition by {keys} "
        f"order by source) rn from read_parquet([{names}], union_by_name = true)) where rn = 1"
    )
    return pl.from_arrow(db().sql(sql).arrow()).select(list(SCHEMAS[table]))
