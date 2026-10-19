"""`datagen export <run_dir> --legacy-fraud --out DIR` (D87): write a run as today's fraud
dataset (`events.parquet`, `golden.parquet`, `meta.json`) for bench. Single-file export of a
run is M4; without `--legacy-fraud` the command exits 2."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ONLY_LEGACY = "datagen export: only --legacy-fraud exists in M3 (single-file export is M4)"


def cmd_export(args: argparse.Namespace) -> int:
    if not args.legacy_fraud:
        print(ONLY_LEGACY, file=sys.stderr)
        return 2
    if args.out is None:
        print("datagen export: --out DIR is required", file=sys.stderr)
        return 2
    run_dir = Path(args.run_dir)
    if not (run_dir / "manifest.json").is_file():
        print(f"datagen export: {run_dir} is not a run folder (no manifest.json); "
              f"run `datagen run` first", file=sys.stderr)
        return 2
    from neorisk_simkit.export import export
    from neorisk_simkit.io.legacy import legacy_fraud

    ds = legacy_fraud(run_dir)
    export(ds, args.out)
    print(f"wrote {ds.events.height} events to {args.out} "
          f"(bad rate {ds.events['label'].mean():.4f})")
    return 0
