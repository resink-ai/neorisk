"""Per-address extras from Etherscan V2: current ETH balance, first funder, NFT transfers.

Parts run one after another and each writes its table when it ends, so a run stopped by the
daily call limit keeps what it finished; a rerun replays answers from the cache, except
balances, which are always fetched fresh.
"""

from datetime import UTC, datetime

from ethcollect import tables
from ethcollect.connectors import history
from ethcollect.connectors.explorer import DailyLimit, pick
from ethcollect.context import FetchError

KIND = "chain"
SUMMARY = "ETH balance, first funder and NFT transfers per address from Etherscan V2"
DEFAULT_RATE = 3.0  # free tier: 3 calls/s, 100k/day
PARTS = ("balance", "funder", "nft")
BATCH = 20  # balancemulti takes at most 20 addresses


def add_arguments(p) -> None:
    history.add_arguments(p)
    p.add_argument("--parts", default=",".join(PARTS),
                   help=f"comma-separated, in order (default {','.join(PARTS)})")
    p.add_argument("--funder-look", type=int, default=10,
                   help="oldest N normal and internal transfers searched for the funder")


def _each(ctx, what: str, items: list, fn) -> tuple[list, DailyLimit | None]:
    """fn(item) for each item with progress lines. A failing item is noted and skipped; the
    daily limit stops the loop and is handed back."""
    out, failed = [], []
    for i, item in enumerate(items, 1):
        try:
            out.append(fn(item))
        except DailyLimit as e:
            ctx.note(f"{what}_failed", failed)
            return out, e
        except FetchError as e:
            failed.append(item if isinstance(item, str) else item[0])
            ctx.warn(f"{what} {failed[-1]}: {e}")
        if i % 500 == 0 or i == len(items):
            print(f"  {what}: {i}/{len(items)} at {datetime.now():%H:%M}", flush=True)
    ctx.note(f"{what}_failed", failed)
    return out, None


def _balance(ctx, args, ex, addresses):
    batches = [addresses[i:i + BATCH] for i in range(0, len(addresses), BATCH)]
    got, stopped = _each(ctx, "balance", batches, ex.balances)
    now = datetime.now(UTC)
    rows = [{"address": a, "balance_eth": b, "as_of": now, "source": ctx.source}
            for batch in got for a, b in batch]
    tables.append(ctx.out, "balances", ctx.source, tables.frame("balances", rows))
    ctx.note("balances", len(rows))
    return stopped


def _funder(ctx, args, ex, addresses):
    got, stopped = _each(ctx, "funder", addresses,
                         lambda a: (a, *ex.first_funding(a, args.funder_look)))
    rows = [{"address": a, "funder": f and f["from_address"], "tx_hash": f and f["tx_hash"],
             "ts": f and f["ts"], "amount_eth": f and f["amount"], "via": f and f["kind"],
             "source": ctx.source} for a, f, _ in got]
    tables.append(ctx.out, "funders", ctx.source, tables.frame("funders", rows))
    # the oldest transfers read on the way are history too
    seen = [{**r, "source": ctx.source} for _, _, read in got for r in read]
    tables.append(ctx.out, "transfers", ctx.source, tables.frame("transfers", seen))
    ctx.note("funders", sum(r["funder"] is not None for r in rows))
    ctx.note("transfers", len(seen))
    return stopped


def _nft(ctx, args, ex, addresses):
    start, end = ex.block_at(ctx.since, "after"), ex.block_at(ctx.until, "before")
    ctx.note("blocks", [start, end])
    got, stopped = _each(ctx, "nft", addresses,
                         lambda a: ex.nft_history(a, start, end, args.per_kind))
    rows = [{**r, "source": ctx.source} for found in got for r in found]
    df = tables.frame("nft_transfers", rows)
    tables.append(ctx.out, "nft_transfers", ctx.source, df)
    ctx.note("nft_transfers", df.height)
    return stopped


RUN = {"balance": _balance, "funder": _funder, "nft": _nft}


def run(ctx, args) -> None:
    parts = [p.strip() for p in args.parts.split(",") if p.strip()]
    if unknown := set(parts) - set(PARTS):
        raise SystemExit(f"unknown --parts {sorted(unknown)}; choose from {PARTS}")
    addresses = history.read_addresses(args)
    if not addresses:
        raise SystemExit("give --address or --addresses")
    ctx.note("addresses", len(addresses))
    ex = pick(ctx, "etherscan")
    for part in parts:
        print(f"  part {part}", flush=True)
        if stopped := RUN[part](ctx, args, ex, addresses):
            raise FetchError(f"{part} stopped at the daily call limit ({stopped}); finished "
                             f"parts are saved, rerun tomorrow to continue from the cache")
