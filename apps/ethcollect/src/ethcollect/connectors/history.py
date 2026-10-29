"""Shared by the explorer connectors: pull the history of a list of addresses into `transfers`."""

from __future__ import annotations

import argparse
from pathlib import Path

from ethcollect import tables
from ethcollect.connectors.explorer import DailyLimit, Explorer
from ethcollect.context import Context, FetchError


def add_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("--address", action="append", default=[], help="an address; repeatable")
    p.add_argument("--addresses", type=Path,
                   help="file with one address per line, or a .parquet with an address column")
    p.add_argument("--per-kind", type=int, default=50,
                   help="latest N normal, internal and ERC-20 transfers per address (default 50)")


def read_addresses(args) -> list[str]:
    found = list(args.address)
    if args.addresses:
        if args.addresses.suffix == ".parquet":
            import polars as pl

            found += pl.read_parquet(args.addresses)["address"].to_list()
        else:
            found += [ln.split(",")[0] for ln in args.addresses.read_text().splitlines()]
    seen, out = set(), []
    for a in map(tables.norm, found):
        if a and a not in seen:
            seen.add(a)
            out.append(a)
    if args.limit:
        out = out[: args.limit]
    return out


def run(ctx: Context, args, explorer: Explorer) -> None:
    addresses = read_addresses(args)
    if not addresses:
        raise SystemExit("give --address or --addresses")
    start, end = explorer.block_at(ctx.since, "after"), explorer.block_at(ctx.until, "before")
    ctx.note("blocks", [start, end])
    rows, failed, stopped = [], [], None
    for i, a in enumerate(addresses, 1):
        try:
            rows += explorer.history(a, start, end, args.per_kind)
        except DailyLimit as e:
            stopped = e
            break
        except FetchError as e:
            failed.append(a)
            ctx.warn(f"{a}: {e}")
        if i % 50 == 0:
            print(f"  {i}/{len(addresses)} addresses, {len(rows)} transfers", flush=True)
    df = tables.frame("transfers", [{**r, "source": ctx.source} for r in rows])
    tables.append(ctx.out, "transfers", ctx.source, df)
    ctx.note("addresses", len(addresses))
    ctx.note("failed_addresses", failed)
    ctx.note("transfers", df.height)
    if stopped:  # rows so far are saved; a rerun replays them from the cache
        raise FetchError(f"stopped at the daily call limit: {stopped}")
