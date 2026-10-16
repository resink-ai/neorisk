import argparse
import os
from collections.abc import Sequence

from datagen.config import FraudConfig
from datagen.scenarios import SCENARIOS
from neorisk_simkit import export


def _project_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("project")
    p.add_argument("--profile", default="sample")
    p.add_argument("--set", action="append", default=[], metavar="K=V")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="datagen")
    sub = parser.add_subparsers(dest="cmd", required=True)
    gen = sub.add_parser("generate", help="generate a synthetic dataset")
    gen.add_argument("--scenario", required=True, choices=sorted(SCENARIOS))
    gen.add_argument("--n-events", type=int, default=FraudConfig.n_events)
    gen.add_argument("--seed", type=int, default=0)
    gen.add_argument("--span-days", type=int, default=FraudConfig.span_days)
    gen.add_argument("--bad-rate", type=float, default=FraudConfig.target_bad_rate)
    gen.add_argument("--out", required=True)
    val = sub.add_parser("validate", help="validate a project folder and print memory caps")
    _project_args(val)
    run = sub.add_parser("run", help="run a project profile into a dataset folder")
    _project_args(run)
    run.add_argument("--seed", type=int, default=None)
    run.add_argument("--threads", type=int, default=None)
    run.add_argument("--out", default=None, help="run folder (default <project>/out/<name>)")
    run.add_argument("--force", action="store_true", help="overwrite an existing run folder")
    run.add_argument("--checked", action="store_true", help="bounds-checked debug run")
    sch = sub.add_parser("schema", help="print DDL or JSON schema of a project or dataset")
    sch.add_argument("target", help="project folder or dataset folder")
    sch.add_argument("--profile", default="sample")
    sch.add_argument("--set", action="append", default=[], metavar="K=V")
    sch.add_argument("--format", default="sql", help="sql (default) or json")
    sch.add_argument("--dialect", default="postgres", help="postgres (default) or duckdb")
    sch.add_argument("--tables", default=None, help="comma-separated table names")
    sch.add_argument("--with-fks", action="store_true", help="emit REFERENCES clauses")
    sch.add_argument("--out", default=None, help="write <table>.sql files into DIR")
    args = parser.parse_args(argv)

    if args.cmd == "schema":
        os.environ["NUMBA_NUM_THREADS"] = "1"
        from datagen import schema_cmd

        return schema_cmd.cmd_schema(args)

    if args.cmd in ("validate", "run"):
        os.environ["NUMBA_NUM_THREADS"] = "1"
        from datagen import run_cmds

        return run_cmds.cmd_validate(args) if args.cmd == "validate" else run_cmds.cmd_run(args)

    cfg = FraudConfig(
        n_events=args.n_events,
        seed=args.seed,
        span_days=args.span_days,
        target_bad_rate=args.bad_rate,
    )
    ds = SCENARIOS[args.scenario](cfg)
    export(ds, args.out)
    print(
        f"wrote {ds.events.height} events to {args.out} (bad rate {ds.events['label'].mean():.4f})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
