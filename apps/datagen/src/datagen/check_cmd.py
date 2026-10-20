"""datagen check RUN_DIR [--project DIR] [--expectations FILE] [--baseline RUN] [--seeds N]
                       [--out DIR]

Runs the structural checks, the pack's and overlays' laws, the expectations and (with an
overlay) the regression rule against a finished dataset. Writes checks.json and report.html
to PROJECT/reports/<run>/ (or --out). Exits 1 when a required check fails, errors, is
inconclusive or is unanchored (the pack changed since the run).
"""

from __future__ import annotations

import json
from pathlib import Path


def add_parser(sub) -> None:
    c = sub.add_parser("check", help="check a dataset; write checks.json and report.html")
    c.add_argument("run_dir")
    c.add_argument("--project", default=None,
                   help="the project that made the run (default: RUN_DIR/../..)")
    c.add_argument("--expectations", default=None,
                   help="default: PROJECT/specs/expectations.yaml if present")
    c.add_argument("--baseline", default=None,
                   help="the same run without overlays (default: rerun it in memory)")
    c.add_argument("--skip-stats", action="store_true",
                   help="laws and structure only (expectations are calibrated per profile)")
    c.add_argument("--seeds", type=int, default=0,
                   help="held-out seeds to rerun in memory for 95%% intervals on expectations")
    c.add_argument("--out", default=None, help="report folder (default: PROJECT/reports/<run>)")


def _project_dir(args) -> Path:
    if args.project:
        return Path(args.project)
    guess = Path(args.run_dir).resolve().parents[1]
    if not (guess / "specs" / "pack.py").exists():
        from neorisk_simkit.spec import PackError
        raise PackError(f"cannot find the project of {args.run_dir}; pass --project")
    return guess


def run(args) -> int:
    from neorisk_simkit.checks import Result, failed, run_checks
    from neorisk_simkit.io import read
    from neorisk_simkit.project import load_project

    data = read(args.run_dir)
    m = data.manifest
    pr = load_project(_project_dir(args))
    plan = pr.plan(m["overlays"])
    results = run_checks(data, plan.checks)
    rev, ran = pr.revision(), m["provenance"].get("pack_revision")
    results.insert(0, Result("s.anchored", "structural", True, "pass" if rev == ran else "fail",
                             1, 0 if rev == ran else 1,
                             detail="" if rev == ran else
                             f"specs changed since the run: {ran} -> {rev}; rerun it"))
    exp = Path(args.expectations) if args.expectations else pr.specs / "expectations.yaml"
    if exp.exists() and not args.skip_stats:
        from neorisk_simkit.checks.stats import check_expectations
        held = [pr.rerun(m, seed=m["seed"] + 1000 + i) for i in range(args.seeds)]
        results += check_expectations(data, exp, held)
    if m["overlays"]:
        from neorisk_simkit.checks.interference import regression
        results += regression(pr, data, baseline=args.baseline)
    out = Path(args.out) if args.out else pr.root / "reports" / data.root.name
    out.mkdir(parents=True, exist_ok=True)
    bad = failed(results)
    summary = {"run": str(data.root), "pack": m["pack"], "overlays": list(m["overlays"]),
               "checks": len(results), "failed": [r.name for r in bad]}
    (out / "checks.json").write_text(json.dumps(
        {**summary, "results": [r.as_dict() for r in results]}, indent=2, default=str) + "\n")
    try:
        from neorisk_simkit.report.html import render
        (out / "report.html").write_text(render(data, results))
    except ImportError:
        pass
    print(json.dumps({**summary, "report": str(out)}))
    return 1 if bad else 0
