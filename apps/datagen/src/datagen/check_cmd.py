"""`datagen check`: judge a run's laws and expectations, write `report.html` and `checks.json`
(spec §02, §16, D86).

Exit 0 when every required check passes, 5 when a required check fails or is missing,
inconclusive or unanchored, 2 on usage errors (unknown profile or overlay, no such run, a run
made with other overlay parameters or another pack config, a bad `expectations.yaml`)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

EXPECTATIONS = "expectations.yaml"


class _Usage(Exception):
    """A usage error (exit 2)."""


def _manifest(run_dir: Path, what: str) -> dict[str, Any]:
    path = run_dir / "manifest.json"
    if not path.is_file():
        raise _Usage(f"{what} {run_dir} is not a run folder (no manifest.json); "
                     f"run `datagen run` first")
    try:
        doc = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        raise _Usage(f"{what} {run_dir}: unreadable manifest.json ({e})") from None
    if not isinstance(doc, dict):
        raise _Usage(f"{what} {run_dir}: manifest.json is not an object")
    return doc


def _check_same_run(manifest: dict[str, Any], run: Any, run_dir: Path) -> None:
    """The run in `run_dir` must be the run the command resolved: its name carries profile,
    seed and overlay names, but not overlay parameters or `--set` values, which the manifest
    records (D77). Placeholders of `expectations.yaml` read them, so a mismatch is refused."""
    from neorisk_simkit.io.manifest import jsonable

    want = jsonable({name: params for name, params in run.overlays})
    if manifest.get("overlays", {}) != want:
        raise _Usage(f"{run_dir} was run with overlays {manifest.get('overlays')}, the command "
                     f"resolves {want}: pass the run's --overlay/--set values")
    _check_same_config(manifest, run, run_dir)


def _check_same_config(manifest: dict[str, Any], run: Any, run_dir: Path) -> None:
    """Same seed and merged pack config (`--set` values) as the resolved run."""
    from neorisk_simkit.io.manifest import jsonable

    if manifest.get("seed") != run.seed:
        raise _Usage(f"{run_dir} was run with seed {manifest.get('seed')}, the command "
                     f"resolves {run.seed}")
    have_cfg = (manifest.get("config") or {}).get("pack")
    if have_cfg != jsonable(run.cfg):
        raise _Usage(f"{run_dir} was run with another pack config (overrides "
                     f"{manifest.get('overrides')}): pass the run's --set values")


def _baseline(args: argparse.Namespace, project: Any, run: Any) -> Path | None:
    """`--baseline`, else `<paths.out>/<profile>-s<seed>` when overlays are enabled and that
    run exists, else None."""
    if not run.overlays:
        if args.baseline is not None:
            print("warning: --baseline is ignored: no overlay is enabled", file=sys.stderr)
        return None
    if args.baseline is not None:
        base = Path(args.baseline)
    else:
        out = project.dir / project.toml.get("paths", {}).get("out", "out")
        base = out / f"{run.profile}-s{run.seed}"
        if not (base / "manifest.json").is_file():
            return None
    m = _manifest(base, "baseline")
    if m.get("overlays"):
        raise _Usage(f"baseline {base} has overlays {sorted(m['overlays'])}; the baseline is "
                     f"the same run without overlays")
    _check_same_config(m, run, base)               # same seed and --set values (M-2)
    return base


def _interference(results: list[dict], baseline: Path | None, run_dir: Path,
                  run: Any) -> dict | None:
    """The compare report (D79) when overlays are enabled and a baseline exists: reused from an
    `interference` expectation when one was evaluated (the report depends only on the two runs
    and the plan, so every such row holds the same one), else computed."""
    if not run.overlays or baseline is None:
        return None
    for r in results:
        v = r.get("value")
        if r.get("metric", "").startswith("stat.interference(") and isinstance(v, dict):
            return v
    from neorisk_simkit.checks.interference import compare

    return compare(baseline, run_dir, run.plan)


def _resolve(args: argparse.Namespace):
    from datagen.run_cmds import overlay_list
    from neorisk_simkit.spec.project import ProjectError, load_project, resolve_run

    try:
        project = load_project(args.project)
        run = resolve_run(project, args.profile, args.set, seed=args.seed,
                          overlays=overlay_list(project, args.profile, args))
    except ProjectError as e:
        raise _Usage(str(e)) from None
    return project, run


def cmd_check(args: argparse.Namespace) -> int:
    from neorisk_simkit.checks.stats import evaluate
    from neorisk_simkit.io.manifest import jsonable
    from neorisk_simkit.report import render
    from neorisk_simkit.spec.expectations import ExpectationError, load

    try:
        project, run = _resolve(args)
        paths = project.toml.get("paths", {})
        run_dir = (Path(args.run_dir) if args.run_dir is not None
                   else project.dir / paths.get("out", "out") / run.name)
        manifest = _manifest(run_dir, "run")
        _check_same_run(manifest, run, run_dir)
        baseline = _baseline(args, project, run)
        exp_path = project.pack_path.parent / EXPECTATIONS
        if not exp_path.is_file():
            raise _Usage(f"no {exp_path}: nothing to check")
        try:
            exp = load(exp_path, overlays={n: dict(p) for n, p in run.overlays}, cfg=run.cfg)
        except ExpectationError as e:
            raise _Usage(f"{exp_path}: {e}") from None
    except _Usage as e:
        print(e, file=sys.stderr)
        return 2
    if manifest.get("pack_revision") != run.plan.revision:
        print(f"warning: {run_dir} was made from pack revision {manifest.get('pack_revision')}, "
              f"the specs are now at {run.plan.revision}", file=sys.stderr)

    results = evaluate(exp, run_dir, run.plan, baseline=baseline)
    interference = _interference(results, baseline, run_dir, run)
    failing = [r for r in results if r["required"] and r["status"] != "pass"]
    ok = not failing
    out = (Path(args.out) if args.out is not None
           else project.dir / paths.get("reports", "reports") / run.name)
    out.mkdir(parents=True, exist_ok=True)
    doc = {"run": run.name, "pack": manifest.get("pack"),
           "revision": manifest.get("pack_revision"), "overlays": manifest.get("overlays", {}),
           "ok": ok, "results": results, "interference": interference}
    (out / "checks.json").write_text(json.dumps(jsonable(doc), indent=2, sort_keys=True) + "\n")
    (out / "report.html").write_text(render(run_dir, results, interference=interference,
                                            plan=run.plan))
    print(f"wrote {out / 'report.html'}")
    print(f"wrote {out / 'checks.json'}")
    for r in results:
        mark = "required" if r["required"] else "optional"
        note = f" ({r['note']})" if r.get("note") else ""
        print(f"  {r['status']:<12} {mark:<9} {r['id']}{note}")
    if ok:
        print(f"OK: {sum(r['required'] for r in results)} required checks pass")
        return 0
    print(f"FAILED: {len(failing)} required check(s) not passing: "
          + ", ".join(r["id"] for r in failing), file=sys.stderr)
    return 5
