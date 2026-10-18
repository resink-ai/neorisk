"""`datagen validate` and `datagen run`: project-folder commands (engine imported lazily, D33)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_MIB = 1024 * 1024


def _mib(n: int) -> str:
    return f"{n / _MIB:,.1f}"


def cmd_validate(args: argparse.Namespace) -> int:
    from neorisk_simkit.spec.project import ProjectError, load_project, resolve_run
    from neorisk_simkit.spec.validate import validate

    try:
        run = resolve_run(load_project(args.project), args.profile, args.set)
    except ProjectError as e:
        print(e, file=sys.stderr)
        return 2
    report = validate(run)
    plan = run.plan
    print(f"pack {plan.pack} @ {plan.revision} · schema_version {plan.schema_version}")
    print("partitions: " + ", ".join(p.name for p in plan.partitions))
    print("events: " + ", ".join(e.name for e in plan.events))
    print("processes: " + ", ".join(p.name for p in plan.processes))
    for w in report.warnings:
        print(f"warning: {w}")
    print(f"{'item':<24}{'hard MiB':>14}{'estimate MiB':>16}")
    for c in report.caps:
        print(f"{c.name:<24}{_mib(c.hard_bytes):>14}{_mib(c.estimate_bytes):>16}")
    if report.ok:
        print("OK")
        return 0
    for e in report.errors:
        print(f"error: {e}")
    return 2


def cmd_run(args: argparse.Namespace) -> int:
    from neorisk_simkit.engine.errors import CapExceeded, LawViolation
    from neorisk_simkit.io.dataset import ValidationFailed, run_to_dataset
    from neorisk_simkit.spec.caps import BudgetError
    from neorisk_simkit.spec.project import ProjectError

    try:
        res = run_to_dataset(
            args.project, args.profile, args.set, seed=args.seed, threads=args.threads,
            out_dir=Path(args.out) if args.out else None, checked=args.checked,
            force=args.force)
    except (ValidationFailed, BudgetError, ProjectError, FileExistsError) as e:
        print(e, file=sys.stderr)
        return 2
    except CapExceeded as e:
        print(e, file=sys.stderr)
        return 3
    except LawViolation as e:                       # D58
        print(e, file=sys.stderr)
        return 4
    m, st = res.manifest, res.stats
    print(f"wrote {res.out_dir}")
    for key, label in (("counts", "event"), ("posting_counts", "posting"),
                       ("history_counts", "history"), ("entity_counts", "entity")):
        for name, n in sorted(m.get(key, {}).items()):
            print(f"  {label} {name}: {n} rows")
    print(f"rounds {sum(st['rounds_per_step'])} · {st['timings']['total_s']:.2f} s")
    return 0
