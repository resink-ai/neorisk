"""`datagen benchmark`: run a workload file and judge it against its gate (spec §10, §18).

A workload (`benchmarks/*.toml`) is an ordinary run of a project and profile. The benchmark:

1. times a compile run in a subprocess on the same plan shape (`users=1000`, one day, no warm-up)
   as `cold_compile_seconds` (with `--cold`, in fresh `NEORISK_JIT_CACHE`/`NUMBA_CACHE_DIR`);
2. runs the measured (warm) run in a second subprocess (`python -m datagen.benchmark --child`)
   with the same cache dirs, so its `engine_seconds` and peak RSS are its own;
3. reads that run's `run_stats.json`, evaluates the gate and the expectations, and writes the
   JSON report (`--out`, default `benchmarks/results/<name>-<utc>.json`).

`--scale X` sets `users = round(shape.users * X)` and nothing else; the generated engine module
must not change with it (the child asserts it), and the verdict is then `skipped`.

Expectations are `{around, tolerance}`: for a count (`around > 1`) the tolerance is relative
(10⁷ ± 5%), for a share (`around <= 1`) it is absolute (8% ± 2 points). `{at_least = x}` and
`{at_most = x}` are one-sided (D56); their checks report `limit` as `[x, null]` / `[null, x]`.

Gate keys: `warm_seconds` and `peak_rss_gb` (upper limits), `min_events_per_second` (exported
events ÷ warm `engine_seconds`) and `min_shard_events_per_second` (shard events ÷ shard-phase
seconds, D55); the two rate gates are lower limits and report `limit` as `[x, null]`.

Memory is reported in GiB (2³⁰ bytes): the gate's `peak_rss_gb` limit is read as GiB and the
report's check is named `peak_rss_gib`. A failing child keeps its exit code (D35: 2 validation,
3 `CapExceeded`; D58: 4 `LawViolation`); any other failure is 1.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import tomllib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_GIB = 1024**3
_REF_CPUS, _REF_RAM_GB = 16, 64
_COMPILE_SHAPE = ("users=1000", "run.span=1d", "run.warmup=0s")
_REPORT_DROP = ("round_detail",)            # per-round lists: large and in run_stats.json anyway


@dataclass(frozen=True)
class Workload:
    name: str
    project: Path
    profile: str
    seed: int
    overrides: list[str]
    expect: dict[str, Any]
    gate: dict[str, Any]
    shape: dict[str, Any] = field(default_factory=dict)
    path: Path | None = None


class ChildFailed(RuntimeError):
    """A benchmark subprocess exited non-zero; `code` is its exit code."""

    def __init__(self, code: int, cmd: list[str]):
        super().__init__(f"benchmark child failed with exit code {code}: " + " ".join(cmd))
        self.code = code


def load_workload(path: str | Path) -> Workload:
    path = Path(path).resolve()
    doc = tomllib.loads(path.read_text())
    wl = doc["workload"]
    for name, spec in doc.get("expect", {}).items():     # refuse a bad form before the run
        _expect_form(name, spec)
    return Workload(
        name=str(wl["name"]), project=(path.parent / wl["project"]).resolve(),
        profile=str(wl.get("profile", "sample")), seed=int(wl.get("seed", 0)),
        overrides=[str(s) for s in wl.get("set", [])], expect=dict(doc.get("expect", {})),
        gate=dict(doc.get("gate", {})), shape=dict(wl.get("shape", {})), path=path)


def _expect_form(name: str, spec: Any) -> str:
    """The form of one expectation: `around` (with `tolerance`), `at_least` or `at_most`."""
    keys = set(spec) if isinstance(spec, dict) else set()
    for form, want in (("around", {"around", "tolerance"}), ("at_least", {"at_least"}),
                       ("at_most", {"at_most"})):
        if keys == want:
            return form
    raise ValueError(f"expectation {name!r} must be {{around, tolerance}}, {{at_least}} or "
                     f"{{at_most}}, got {spec!r}")


# ---------------------------------------------------------------- evaluation
def _ratio(num: float, den: float) -> float:
    return num / den if den else 0.0


def derived(stats: dict[str, Any]) -> dict[str, Any]:
    """Quantities computed from `run_stats.json` that expectations may name (D56). Each is
    computed only when its inputs exist, so S1 reports are unchanged. Windows (F-25): exported
    steps for `payments`, `postings_per_payment_event` and `hot_share_of_checkouts`; the whole
    run for `hot_share_of_reserves`, `shard_command_share` and `campaign_member_share`."""
    proposals = stats.get("proposals") or 0
    reserve = stats.get("requests_by_boundary", {}).get("reserve", 0)
    out: dict[str, Any] = {"inventory_share_of_proposals": _ratio(reserve, proposals)}
    counts = stats.get("counts", {})
    if "payment_authorized" in counts and "payment_declined" in counts:
        out["payments"] = counts["payment_authorized"] + counts["payment_declined"]
    ledger = stats.get("posting_counts", {}).get("ledger")
    pay_events = stats.get("events_by_partition", {}).get("payment")
    if ledger is not None and pay_events is not None:
        out["postings_per_payment_event"] = _ratio(ledger, pay_events)
    hot = stats.get("accumulators", {}).get("hot_checkouts")
    if hot is not None and "checkout_started" in counts:
        out["hot_share_of_checkouts"] = _ratio(hot, counts["checkout_started"])
    inv = stats.get("shard_load", {}).get("inventory")
    if hot is not None and inv is not None and inv.get("requests"):   # shard 0 is the hot group
        out["hot_share_of_reserves"] = _ratio(inv["requests"][0], sum(inv["requests"]))
    if "shard_command_share" in stats:
        out["shard_command_share"] = stats["shard_command_share"]
    pops = stats.get("populations", {})
    members = stats.get("ids_allocated", {}).get("member")
    if "campaign" in pops and "user" in pops and members is not None:
        out["campaign_member_share"] = _ratio(pops["campaign"] + members, pops["user"])
    return out


def _within(value: float, around: float, tolerance: float) -> tuple[bool, float]:
    width = tolerance * around if abs(around) > 1 else tolerance
    return abs(value - around) <= width, width


def reference_hardware(machine: dict[str, Any]) -> bool:
    return (int(machine.get("cpus") or 0) >= _REF_CPUS
            and int(machine.get("ram_bytes") or 0) >= _REF_RAM_GB * _GIB)


def evaluate(stats: dict[str, Any], wl: Workload, *, scale: float) -> dict[str, Any]:
    """Gate and expectation checks; `verdict` is `skipped` unless the run is at scale 1."""
    checks: list[dict[str, Any]] = []
    gate = wl.gate
    if "warm_seconds" in gate:
        v, lim = float(stats["engine_seconds"]), float(gate["warm_seconds"])
        checks.append({"name": "warm_seconds", "value": v, "limit": lim, "ok": v <= lim})
    if "peak_rss_gb" in gate:
        v, lim = stats["peak_rss_bytes"] / _GIB, float(gate["peak_rss_gb"])     # GiB
        checks.append({"name": "peak_rss_gib", "value": v, "limit": lim, "ok": v <= lim})
    for key, name in (("min_events_per_second", "events_per_second"),
                      ("min_shard_events_per_second", "shard_events_per_second")):
        if key in gate:
            v, lim = float(stats[name]), float(gate[key])
            checks.append({"name": name, "value": v, "limit": [lim, None], "ok": v >= lim})
    values = stats | derived(stats)
    for name, spec in wl.expect.items():
        v = float(values[name])
        form = _expect_form(name, spec)
        if form == "around":
            around, tol = float(spec["around"]), float(spec["tolerance"])
            ok, width = _within(v, around, tol)
            limit: list[float | None] = [around - width, around + width]
        elif form == "at_least":
            x = float(spec["at_least"])
            ok, limit = v >= x, [x, None]
        else:
            x = float(spec["at_most"])
            ok, limit = v <= x, [None, x]
        checks.append({"name": name, "value": v, "limit": limit, "ok": ok})
    if scale != 1:
        verdict = "skipped"
    else:
        verdict = "pass" if all(c["ok"] for c in checks) else "fail"
    return {"verdict": verdict, "checks": checks,
            "reference_hardware": reference_hardware(stats.get("machine", {}))}


# ---------------------------------------------------------------- subprocess runs
def _child_cmd(wl: Workload, overrides: list[str], threads: int, out: Path, result: Path,
               expect_module: str | None) -> list[str]:
    cmd = [sys.executable, "-m", "datagen.benchmark", "--child", "--project", str(wl.project),
           "--profile", wl.profile, "--seed", str(wl.seed), "--threads", str(threads),
           "--out", str(out), "--result", str(result)]
    for o in overrides:
        cmd += ["--set", o]
    if expect_module:
        cmd += ["--expect-module", expect_module]
    return cmd


def _run_child(cmd: list[str], env: dict[str, str]) -> float:
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, env=env, check=False)
    elapsed = time.perf_counter() - t0
    if proc.returncode != 0:
        raise ChildFailed(proc.returncode, cmd)
    return elapsed


def _child_main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="datagen.benchmark --child")
    ap.add_argument("--child", action="store_true", required=True)
    ap.add_argument("--project", required=True)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--threads", type=int, required=True)
    ap.add_argument("--set", action="append", default=[])
    ap.add_argument("--out", required=True)
    ap.add_argument("--result", required=True)
    ap.add_argument("--expect-module", default=None)
    a = ap.parse_args(argv)
    os.environ["NUMBA_NUM_THREADS"] = "1"
    os.environ["POLARS_MAX_THREADS"] = str(a.threads)

    from neorisk_simkit.engine.build import build_engine
    from neorisk_simkit.engine.errors import CapExceeded, LawViolation
    from neorisk_simkit.io.dataset import ValidationFailed, run_to_dataset
    from neorisk_simkit.spec.caps import BudgetError
    from neorisk_simkit.spec.project import ProjectError, load_project, resolve_run

    try:
        run_to_dataset(a.project, a.profile, a.set, seed=a.seed, threads=a.threads,
                       out_dir=Path(a.out), force=True)
    except (ValidationFailed, BudgetError, ProjectError) as e:       # D35, as `datagen run`
        print(e, file=sys.stderr)
        return 2
    except CapExceeded as e:
        print(e, file=sys.stderr)
        return 3
    except LawViolation as e:                                         # D58
        print(e, file=sys.stderr)
        return 4
    plan = resolve_run(load_project(a.project), a.profile, a.set, seed=a.seed).plan
    module = build_engine(plan).__file__
    if a.expect_module is not None and module != a.expect_module:
        print(f"engine module {module} differs from the compile run's {a.expect_module}: "
              "codegen inlined a population-dependent value", file=sys.stderr)
        return 1
    Path(a.result).write_text(json.dumps({"module": module}))
    return 0


# ---------------------------------------------------------------- benchmark
def run_benchmark(path: str | Path, *, scale: float = 1.0, cold: bool = False,
                  threads: int | None = None, out_json: str | Path | None = None,
                  echo: bool = True) -> dict[str, Any]:
    wl = load_workload(path)
    if threads is None:
        threads = min(int(wl.gate.get("threads", 16)), os.cpu_count() or 1)
    overrides = list(wl.overrides)
    if scale != 1:
        overrides.append(f"users={round(int(wl.shape['users']) * scale)}")
    env = os.environ | {"NUMBA_NUM_THREADS": "1", "POLARS_MAX_THREADS": str(threads)}
    with tempfile.TemporaryDirectory(prefix=f"bench-{wl.name}-") as tmp:
        tmpd = Path(tmp)
        if cold:
            env |= {"NEORISK_JIT_CACHE": str(tmpd / "jit"), "NUMBA_CACHE_DIR": str(tmpd / "nb")}
        res_c = tmpd / "compile.json"
        cold_s = _run_child(_child_cmd(wl, [*overrides, *_COMPILE_SHAPE], threads,
                                       tmpd / "compile_run", res_c, None), env)
        module = json.loads(res_c.read_text())["module"]
        res_w = tmpd / "warm.json"
        _run_child(_child_cmd(wl, overrides, threads, tmpd / "warm_run", res_w, module), env)
        stats = json.loads((tmpd / "warm_run" / "run_stats.json").read_text())
    ev = evaluate(stats, wl, scale=scale)
    report = {k: v for k, v in stats.items() if k not in _REPORT_DROP}
    report |= derived(stats) | ev
    report |= {"workload": wl.name, "workload_file": str(wl.path), "scale": scale,
               "overrides": overrides, "cold": cold, "cold_compile_seconds": cold_s,
               "engine_module": Path(module).name,
               "utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}
    if out_json is None:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        out_json = Path(wl.path).parent / "results" / f"{wl.name}-{stamp}.json"
    out_json = Path(out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    report["report_path"] = str(out_json)
    if echo:
        print(summary(report))
    return report


def summary(rep: dict[str, Any]) -> str:
    m = rep.get("machine", {})
    st = rep.get("stage_seconds", {})
    rows = [
        ("workload", f"{rep['workload']} (scale {rep['scale']})"),
        ("machine", f"{m.get('arch')} · {m.get('cpus')} cores · "
                    f"{(m.get('ram_bytes') or 0) / _GIB:.0f} GiB"
                    + ("" if rep["reference_hardware"] else " (not reference hardware)")),
        ("threads", rep.get("threads")),
        ("exported events", f"{rep['exported_events']:,}"),
        ("events/s", f"{rep.get('events_per_second', 0):,.0f}"),
        ("shard-phase ev/s", (f"{rep.get('shard_events_per_second', 0):,.0f} "
                              f"({rep.get('shard_events', 0):,} shard events in "
                              f"{rep.get('shard_phase_seconds', 0):.2f} s)")),
        ("engine s (warm)", f"{rep['engine_seconds']:.2f}"),
        ("cold compile s", f"{rep['cold_compile_seconds']:.2f}"
                           + (" (cold cache)" if rep["cold"] else " (cache as found)")),
        ("stages s", " · ".join(f"{k} {v:.2f}" for k, v in st.items())),
        ("peak RSS GiB", f"{rep['peak_rss_bytes'] / _GIB:.2f}"),
        ("rounds/step max", max(rep.get("rounds_per_step") or [0])),
    ]
    rows += [(k, f"{v:,}" if isinstance(v, int) else f"{v:.4f}")
             for k, v in derived(rep).items()]
    rows += [(f"shard max share {name}", f"{load['max_share']:.4f} of {load['shards']} shards")
             for name, load in rep.get("shard_load", {}).items()]
    lines = [f"{k:<18}{v}" if len(k) < 18 else f"{k} {v}" for k, v in rows]
    for c in rep["checks"]:
        lines.append(f"check {c['name']:<32}{c['value']:>16,.4f}  limit {c['limit']}  "
                     f"{'ok' if c['ok'] else 'FAIL'}")
    lines.append(f"verdict           {rep['verdict']}  → {rep['report_path']}")
    return "\n".join(lines)


def cmd_benchmark(args: argparse.Namespace) -> int:
    try:
        rep = run_benchmark(args.workload, scale=args.scale, cold=args.cold,
                            threads=args.threads, out_json=args.out)
    except ChildFailed as e:
        print(e, file=sys.stderr)
        return e.code if e.code in (2, 3, 4) else 1
    except (OSError, KeyError, ValueError, RuntimeError, tomllib.TOMLDecodeError) as e:
        print(e, file=sys.stderr)
        return 1
    if rep["verdict"] == "fail" and not args.no_gate:
        return 1
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--child" not in args:
        print("usage: datagen benchmark WORKLOAD.toml (this entry point is the --child runner)",
              file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(_child_main(args))
