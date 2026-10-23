"""datagen: validate, run, check, export, schema and replay simulation projects.

    datagen validate PROJECT [--overlay NAME]...
    datagen run PROJECT [--profile P] [--overlay NAME]... [--set K=V]... [--seed S]
                        [--out DIR] [--force] [--debug]
    datagen export RUN_DIR (--legacy-fraud [--labels roles|xgb|mlp] --out DIR | --single-file FILE | --public-ids --out DIR)

Exit codes: 0 success, 1 the run or a required check failed, 2 usage error or refusal.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path


def _err(msg: str, code: int = 2) -> int:
    print(f"datagen: {msg}", file=sys.stderr)
    return code


def _project_args(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("project", help="project folder (with specs/pack.py)")
    sp.add_argument("--overlay", action="append", default=[], help="overlay name (repeatable)")
    sp.add_argument("--profile", default=None)
    sp.add_argument("--set", action="append", default=[], metavar="K=V",
                    help="override: users=500 | run.days=10 | <overlay>.<param>=v")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="datagen")
    sub = parser.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate", help="report structural contradictions in a pack")
    _project_args(v)
    r = sub.add_parser("run", help="simulate a project into a dataset directory")
    _project_args(r)
    r.add_argument("--seed", type=int, default=None)
    r.add_argument("--out", default=None, help="default: PROJECT/out/<profile>-s<seed>[+ovl]")
    r.add_argument("--force", action="store_true", help="overwrite an existing run folder")
    r.add_argument("--debug", action="store_true",
                   help="check emits at emit time and snapshot state around rejections")
    e = sub.add_parser("export", help="export a dataset in another layout")
    e.add_argument("run_dir")
    e.add_argument("--legacy-fraud", action="store_true", help="the fraud dataset bench reads")
    e.add_argument("--single-file", default=None, metavar="FILE",
                   help="every event in one canonically ordered parquet file")
    e.add_argument("--public-ids", action="store_true",
                   help="a copy whose ids are a seeded Feistel permutation (refs consistent)")
    e.add_argument("--labels", choices=("roles", "xgb", "mlp"), default="roles",
                   help="--legacy-fraud labels: ring roles, or sampled from a scorer")
    e.add_argument("--bad-rate", type=float, default=0.02,
                   help="target bad rate for scorer labels (default 0.02)")
    e.add_argument("--out", default=None)
    from datagen import check_cmd, replay_cmd, schema_cmd
    check_cmd.add_parser(sub)
    schema_cmd.add_parser(sub)
    replay_cmd.add_parser(sub)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return int(e.code or 0)
    from neorisk_simkit.engine import SimError
    from neorisk_simkit.spec import PackError
    try:
        return COMMANDS[args.cmd](args)
    except PackError as e:
        return _err(str(e))
    except FileNotFoundError as e:                   # not a project or not a dataset
        return _err(str(e))
    except SimError as e:
        return _err(f"run failed: {e}", 1)


def cmd_validate(args) -> int:
    from neorisk_simkit.project import load_project
    from neorisk_simkit.spec import validate
    pr = load_project(args.project)
    s = pr.settings(args.profile, args.set, args.overlay)
    errs = validate(pr.plan(s.overlays)) + pr.lint()
    for e in errs:
        print(e)
    print(json.dumps({"project": pr.name, "overlays": args.overlay, "problems": len(errs)}))
    return 1 if errs else 0


def cmd_run(args) -> int:
    import dataclasses

    from neorisk_simkit.engine import simulate
    from neorisk_simkit.io import DatasetExists, write
    from neorisk_simkit.project import load_project
    from neorisk_simkit.spec import validate
    pr = load_project(args.project)
    s = pr.settings(args.profile, args.set, args.overlay)
    if args.seed is not None:
        s.run = dataclasses.replace(s.run, seed=args.seed)
    if args.debug:
        s.run = dataclasses.replace(s.run, debug=True)
    plan = pr.plan(s.overlays)
    errs = validate(plan)
    if errs:
        return _err("invalid pack:\n  " + "\n  ".join(errs), 1)
    out_dir = Path(args.out) if args.out else pr.root / "out" / pr.run_name(s, args.overlay)
    if out_dir.exists() and any(out_dir.iterdir()) and not args.force:
        return _err(f"{out_dir} exists; runs are deterministic, pass --force to overwrite")
    out = simulate(plan, s.config, s.run)
    try:
        write(out, out_dir, force=args.force,
              provenance={**pr.provenance(), "profile": s.profile, "sets": args.set})
    except DatasetExists as e:
        return _err(str(e))
    print(json.dumps({"out": str(out_dir),
                      "events": {k: v.height for k, v in out.events.items()},
                      "late_messages": out.stats.late_messages}))
    return 0


def cmd_export(args) -> int:
    from neorisk_simkit.io import read
    if sum(map(bool, (args.legacy_fraud, args.single_file, args.public_ids))) != 1:
        return _err("export: pass exactly one of --legacy-fraud, --single-file, --public-ids")
    if args.public_ids:
        if not args.out:
            return _err("export --public-ids needs --out")
        from neorisk_simkit.io.public_ids import export_public
        export_public(read(args.run_dir), args.out)
        return 0
    if args.single_file:
        from neorisk_simkit.io.single import single_file
        single_file(read(args.run_dir), args.single_file)
        return 0
    if not args.out:
        return _err("export --legacy-fraud needs --out")
    from neorisk_simkit.export import export
    from neorisk_simkit.io.legacy import legacy_fraud, rescore
    if args.labels != "roles" and not 0 < args.bad_rate < 1:
        return _err("export: --bad-rate must be in (0, 1)")
    run = read(args.run_dir)
    m = run.manifest
    meta = {"seed": m["seed"],
            "source": {"pack": m["pack"], "run": run.root.name,
                       "profile": m["provenance"].get("profile"),
                       "pack_revision": m["provenance"].get("pack_revision"),
                       "overlays": m["overlays"], "config": m["config"]}}
    ds = legacy_fraud(run, meta)
    if args.labels != "roles":
        ds = rescore(ds, args.labels, args.bad_rate, seed=m["seed"])
    export(ds, args.out)
    return 0


def _late(name: str):
    def go(args) -> int:
        from datagen import check_cmd, replay_cmd, schema_cmd
        return {"check": check_cmd, "schema": schema_cmd, "replay": replay_cmd}[name].run(args)
    return go


COMMANDS = {"validate": cmd_validate, "run": cmd_run, "export": cmd_export,
            "check": _late("check"), "schema": _late("schema"), "replay": _late("replay")}


if __name__ == "__main__":
    raise SystemExit(main())
