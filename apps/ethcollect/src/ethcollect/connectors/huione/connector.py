"""Huione Group addresses, curated by hand from public reports (no bulk list exists).

Rows live in `seeds.csv` next to this file: address, chain, claim, source_url, observed_at.
Only chain=ethereum rows are loaded, and a row without a source_url is rejected: every claim
must point at the page it came from. The file starts empty; see README.md for how to add rows.
"""

import csv
import io
from datetime import date
from pathlib import Path

from ethcollect import tables

KIND = "label"
SUMMARY = "Huione Group (FinCEN 311), hand-curated seeds.csv with a source URL per row"
DEFAULT_RATE = 1.0
SEEDS = Path(__file__).with_name("seeds.csv")


def add_arguments(p) -> None:
    p.add_argument("--seeds", type=Path, default=SEEDS, help="curated CSV (default: seeds.csv)")


def parse(body: bytes) -> tuple[list[dict], list[str]]:
    rows, rejected = [], []
    for r in csv.DictReader(io.StringIO(body.decode())):
        if (r.get("chain") or "").strip().lower() != "ethereum":
            continue
        url = (r.get("source_url") or "").strip()
        if not url or not tables.norm(r.get("address")):
            rejected.append(r.get("address") or "?")
            continue
        try:
            seen = date.fromisoformat((r.get("observed_at") or "").strip())
        except ValueError:
            seen = None
        rows += tables.label_rows([r["address"]], kind="sanctioned", source="huione",
                                  trust="high", ref=f"{r.get('claim')} <{url}>", observed_at=seen)
    return rows, rejected


def run(ctx, args) -> None:
    rows, rejected = parse(args.seeds.read_bytes())
    for a in rejected:
        ctx.warn(f"rejected {a}: needs a valid address and a source_url")
    df = tables.frame("labels", rows)
    tables.write(ctx.out, "labels", ctx.source, df)
    ctx.note("labels", df.height)
    if not rows:
        ctx.warn("seeds.csv has no ethereum rows yet; see connectors/huione/README.md")
