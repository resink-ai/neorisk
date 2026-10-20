"""datagen: run the e-commerce event simulation and export it for bench.

    datagen run --out DIR [--users N] [--days D] [--seed S]
    datagen export RUN_DIR --legacy-fraud --out DIR
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="datagen")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="simulate the e-commerce scenario into parquet tables")
    run.add_argument("--out", required=True)
    run.add_argument("--users", type=int, default=2000)
    run.add_argument("--days", type=float, default=30.0)
    run.add_argument("--seed", type=int, default=7)
    exp = sub.add_parser("export", help="export a run in the legacy fraud format for bench")
    exp.add_argument("run_dir")
    exp.add_argument("--legacy-fraud", action="store_true")
    exp.add_argument("--out", required=True)
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return int(e.code or 0)

    if args.cmd == "run":
        from neorisk_simkit.ecommerce import Config, simulate, write

        cfg = Config(users=args.users, days=args.days, seed=args.seed)
        tables = simulate(cfg)
        write(tables, args.out, cfg)
        print(json.dumps({k: v.height for k, v in tables.items()}))
        return 0

    if not args.legacy_fraud:
        print("datagen export: pass --legacy-fraud (the only export format)", file=sys.stderr)
        return 2
    from neorisk_simkit.export import export
    from neorisk_simkit.legacy import legacy_fraud

    run_dir = Path(args.run_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text())
    cfg = manifest["config"]
    meta = {"seed": cfg["seed"],
            "source": {"pack": "ecommerce", "overlays": {"bounty_hunters": {}},
                       "run": run_dir.name, "config": cfg}}
    export(legacy_fraud(run_dir, meta), args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
