"""The toy recipe: labeled seeds + random background -> a small, self-contained sample.

Steps (each one a normal connector run, so each leaves its own run record):
  1. every label connector                      -> labels/<source>.parquet
  2. seeds: risk labels, newest-known first, one kind at a time; their history is pulled in
     batches until enough of them show activity in the window
  3. background: random addresses from random days of `aws-public`
  4. their history from the explorer, then contract flags over `rpc`
     (--history aws-scan, the default without an Etherscan key, replaces 2-4 with one
     `aws-public --mode scan` pass over --days whole days)
  5. cap each sampled address to its latest N transfers and write
     samples/toy/{addresses,transfers,labels}.parquet + manifest.json
"""

from __future__ import annotations

import argparse
import json
import math
import random
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from ethcollect import connectors, tables


def _ns(source: str, base, **opts) -> argparse.Namespace:
    from ethcollect.cli import namespace_for

    return namespace_for(source, base, limit=None, **opts)


def seed_candidates(labels: pl.DataFrame, rng: random.Random, prefer=None) -> list[str]:
    """Risk-labeled addresses, interleaved across label kinds, dated labels first.
    `prefer(address)`, if given, re-ranks within each kind (stable, so ties stay dated-first)."""
    risk = labels.filter(pl.col("is_risk")).sort("observed_at", descending=True)
    by_kind: dict[str, list[str]] = {}
    for kind, part in risk.group_by("label_kind", maintain_order=True):
        dated = part.filter(pl.col("date_known"))["address"].unique(maintain_order=True)
        rest = part.filter(~pl.col("date_known"))["address"].unique().to_list()
        rng.shuffle(rest)
        by_kind[kind[0]] = dated.to_list() + rest
        if prefer:
            by_kind[kind[0]].sort(key=prefer)
    out, seen = [], set()
    for i in range(max((len(v) for v in by_kind.values()), default=0)):
        for kind in sorted(by_kind):
            if i < len(by_kind[kind]) and by_kind[kind][i] not in seen:
                seen.add(by_kind[kind][i])
                out.append(by_kind[kind][i])
    return out


def _pull(run, base, source: str, addresses: list[str], work: Path, cap: int) -> bool:
    work.mkdir(parents=True, exist_ok=True)
    f = work / "batch.txt"
    f.write_text("\n".join(addresses))
    return run(source, _ns(source, base, addresses=f, per_kind=cap))


def active(root: Path, source: str, addresses: list[str], since, until) -> set[str]:
    p = tables.path(root, "transfers", source)
    if not p.exists():
        return set()
    lo = datetime(since.year, since.month, since.day, tzinfo=UTC)
    hi = datetime(until.year, until.month, until.day, tzinfo=UTC)
    tr = pl.read_parquet(p).filter(pl.col("ts").is_between(lo, hi))
    hit = set(tr["from_address"].to_list()) | set(tr["to_address"].to_list())
    return hit & set(addresses)


def row_counts(root: Path, source: str) -> dict[str, int]:
    """Transfers per address (either side) in one source's transfers table."""
    tr = pl.read_parquet(tables.path(root, "transfers", source))
    ends = pl.concat([tr.select(pl.col(c).alias("a")) for c in ("from_address", "to_address")])
    return dict(ends.drop_nulls().group_by("a").len().iter_rows())


def cap_transfers(tr: pl.DataFrame, sampled: list[str], cap: int) -> pl.DataFrame:
    """Each sampled address keeps its latest `cap` transfers (in or out)."""
    keep = []
    for side in ("from_address", "to_address"):
        keep.append(tr.filter(pl.col(side).is_in(sampled)).with_columns(
            pl.col(side).alias("_owner")))
    both = pl.concat(keep).sort(["_owner", "ts"], descending=[False, True])
    top = both.group_by("_owner", maintain_order=True).head(cap)
    return top.drop("_owner").unique(subset=tables.KEYS["transfers"], maintain_order=True)


def history_choice(choice: str) -> str:
    """`auto`: etherscan when ETHERSCAN_API_KEY is set, else the AWS day scan."""
    from ethcollect.context import env

    if choice != "auto":
        return choice
    return "etherscan" if env("ETHERSCAN_API_KEY") else "aws-scan"


def toy(args, run) -> int:
    args.history = history_choice(args.history)
    rng = random.Random(args.seed)
    root: Path = args.out
    work = root / "samples" / "toy"
    if not args.skip_labels:
        for s in connectors.label_sources():
            run(s, _ns(s, args))
    labels = tables.load(root, "labels")
    ctx_since, ctx_until = _window(args)
    candidates = seed_candidates(labels, rng)

    if args.history == "aws-scan":
        # 2-4. one pass over whole days: risk-labeled rows and random background together
        run("aws-public", _ns("aws-public", args, mode="scan", days=args.days, cap=args.cap,
                              seed=args.seed))
        # day snapshots leave many addresses with 1-2 rows; within each label kind prefer
        # those with a full `cap`. Kinds still take turns: busy addresses are mostly frozen
        # ones, and ranking by activity alone made 94% of seeds `frozen`.
        rows = row_counts(root, "aws-public")
        hit = active(root, "aws-public", candidates, ctx_since, ctx_until)
        seeds = seed_candidates(labels.filter(pl.col("address").is_in(list(hit))), rng,
                                prefer=lambda a: rows.get(a, 0) < args.cap)[: args.seeds]
        tried = len(candidates)
        pool = sorted(a for a in tables.load(root, "addresses").filter(
            (pl.col("sample_reason") == "random") & pl.col("source").str.contains("aws-public")
        )["address"].to_list() if a not in hit)
        full = [a for a in pool if rows.get(a, 0) >= args.cap]
        background = rng.sample(full, min(args.background, len(full)))
        rest = [a for a in pool if rows.get(a, 0) < args.cap]
        background += rng.sample(rest, min(args.background - len(background), len(rest)))
    else:
        seeds, tried, background = _explorer_seeds_and_background(args, run, rng, candidates,
                                                                  work, ctx_since, ctx_until)
    _finish(args, run, root, work, labels, seeds, tried, background, ctx_since, ctx_until)
    return 0


def _explorer_seeds_and_background(args, run, rng, candidates, work, ctx_since, ctx_until):
    root: Path = args.out
    # 2. seeds, pulled in batches of 50 until enough are active in the window
    seeds, tried = [], 0
    budget = args.seeds * 4
    while len(seeds) < args.seeds and tried < min(budget, len(candidates)):
        batch = candidates[tried:tried + 50]
        tried += len(batch)
        _pull(run, args, args.history, batch, work, args.cap)
        seeds += sorted(active(root, args.history, batch, ctx_since, ctx_until))
        print(f"[sample] seeds active {len(seeds)}/{args.seeds} after {tried} candidates")
    seeds = seeds[: args.seeds]

    # 3-4. background addresses and their history
    per_day = math.ceil(args.background / 12)
    run("aws-public", _ns("aws-public", args, mode="addresses", days=12, per_day=per_day,
                          seed=args.seed))
    background = [a for a in tables.load(root, "addresses").filter(
        pl.col("sample_reason") == "random")["address"].to_list() if a not in set(seeds)]
    background = rng.sample(sorted(background), min(args.background, len(background)))
    for i in range(0, len(background), 100):
        _pull(run, args, args.history, background[i:i + 100], work, args.cap)
    return seeds, tried, background


def _finish(args, run, root, work, labels, seeds, tried, background, ctx_since, ctx_until):
    work.mkdir(parents=True, exist_ok=True)

    # 5. cap, contract flags, write the sample
    sampled = seeds + background
    tr = cap_transfers(tables.load(root, "transfers"), sampled, args.cap)
    others = (set(tr["from_address"].drop_nulls()) | set(tr["to_address"].drop_nulls()))
    others -= set(sampled)
    flags_file = work / "flag.txt"
    flags_file.write_text("\n".join(sampled + sorted(others)))
    run("rpc", _ns("rpc", args, mode="codes", addresses=flags_file))
    flags = dict(tables.load(root, "addresses").select("address", "is_contract").iter_rows())
    ends = pl.concat([tr.select(pl.col(c).alias("address"), "ts")
                      for c in ("from_address", "to_address")])
    first_seen = dict(ends.group_by("address").agg(pl.col("ts").min()).iter_rows())
    reasons = {a: "counterparty" for a in others}
    reasons.update({a: "random" for a in background})
    reasons.update({a: "seed" for a in seeds})
    addresses = tables.frame("addresses", [
        {"address": a, "is_contract": flags.get(a), "first_seen": first_seen.get(a),
         "sample_reason": r, "source": "sample"} for a, r in sorted(reasons.items())])
    sample_labels = labels.filter(pl.col("address").is_in(addresses["address"].to_list()))
    work.mkdir(parents=True, exist_ok=True)
    addresses.write_parquet(work / "addresses.parquet")
    tr.write_parquet(work / "transfers.parquet")
    sample_labels.write_parquet(work / "labels.parquet")
    manifest = {
        "recipe": "toy", "seed": args.seed, "window": [str(ctx_since), str(ctx_until)],
        "history_source": args.history, "cap": args.cap,
        "scan_days": args.days if args.history == "aws-scan" else None,
        "seeds": len(seeds), "seed_candidates_tried": tried, "background": len(background),
        "counterparties": len(others), "transfers": tr.height,
        "labeled_addresses": sample_labels["address"].n_unique(),
        "built_at": datetime.now(UTC).isoformat(),
    }
    (work / "manifest.json").write_text(json.dumps(manifest, indent=2))
    for f in ("batch.txt", "flag.txt"):
        (work / f).unlink(missing_ok=True)
    print(json.dumps(manifest, indent=2))


def _window(args):
    from ethcollect.cli import make_context

    ctx = make_context("ofac", args)
    return ctx.since, ctx.until
