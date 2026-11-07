"""`dataset bench`: every requested engine on every requested dataset, one at a time, then
one report, `$NEORISK_DATA_ROOT/_runs/bench/<run-id>/report.json` and `report.html`.

A dataset without a port for an engine is "not ported" (not a failure); an engine that is
not ready here is "not run", with the reason, and fails the bench. Where a table fails on
some engine, the report also says which engines' outputs of it agree with each other.
"""

from __future__ import annotations

import html
import json
import subprocess
import sys
import tempfile
from itertools import combinations
from pathlib import Path

from dataset import engines
from dataset.config import load
from dataset.engines import grade
from dataset.engines.flink import JOB_TIMEOUT
from dataset.names import data_root


def _entry(name: str, engine: str, status: str, **kw) -> dict:
    return {"name": name, "engine": engine, "status": status, **kw}


def _agreement(cfg, reps: dict[str, dict]) -> dict[str, dict[str, list[str]]]:
    """For each table some engine failed: each engine with output -> the engines whose
    output equals its own."""
    failing = sorted({t["name"] for r in reps.values() for t in r["tables"] if not t["ok"]})
    out: dict[str, dict[str, list[str]]] = {}
    for table in failing:
        dirs = {e: engines.runs_dir(cfg, e) / r["run_id"] / "tables" / table
                for e, r in reps.items()}
        dirs = {e: d for e, d in dirs.items() if d.is_dir()}
        same: dict[str, list[str]] = {e: [] for e in dirs}
        for a, b in combinations(dirs, 2):
            try:
                ok = grade.typed(table, grade.read_output(dirs[a]), dirs[b]).ok
            except (FileNotFoundError, OSError, ValueError):
                ok = False
            if ok:
                same[a].append(b)
                same[b].append(a)
        if same:
            out[table] = same
    return out


# longer than a Flink job may run, so the run itself cancels its job before it is killed
RUN_TIMEOUT = JOB_TIMEOUT + 600


def _isolated(cfg, engine: str) -> dict:
    """One `dataset run` in its own process, so its peak memory is its own."""
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "run.json"
        p = subprocess.run([sys.executable, "-m", "dataset.cli", "run", str(cfg.dir),
                            "--engine", engine, "--json", str(out)],
                           capture_output=True, text=True, timeout=RUN_TIMEOUT, check=False)
        if p.returncode == 2 or not out.exists():
            raise engines.EngineNotReady(p.stderr.strip().removeprefix("dataset: ")
                                         or f"dataset run exited {p.returncode}")
        return json.loads(out.read_text())


def bench(names: list[str], engine_names: list[str], *, isolate: bool = True) -> Path:
    """`isolate` runs each engine run as a subprocess (the CLI does); False runs them here."""
    run_id = engines._run_id()
    out = data_root() / "_runs" / "bench" / run_id
    out.mkdir(parents=True, exist_ok=True)
    ready: dict[str, str | None] = {}
    runs, agreement = [], {}
    for name in names:
        cfg = load(name)
        reps = {}
        for e in engine_names:
            if e != "duckdb" and not engines.is_ported(cfg, e):
                runs.append(_entry(name, e, "not ported"))
                continue
            if e not in ready:
                ready[e] = engines.engine(e).check()
            if ready[e]:
                runs.append(_entry(name, e, "not run", reason=ready[e]))
                continue
            try:
                rep = _isolated(cfg, e) if isolate else engines.run(cfg, e)
            except (FileNotFoundError, engines.EngineNotReady,
                    subprocess.TimeoutExpired) as err:
                runs.append(_entry(name, e, "not run", reason=str(err)))
                continue
            reps[e] = rep
            runs.append(_entry(
                name, e, "pass" if rep["ok"] else "fail", run_id=rep["run_id"],
                events=rep["events"], wall_s=rep["wall_s"], timings=rep["timings"],
                peak_rss_mb=rep["peak_rss_mb"], events_per_s=rep["events_per_s"],
                tables=len(rep["tables"]),
                failed=[{"name": t["name"], "detail": t["detail"], "rows_expected":
                         t["rows_expected"], "rows_got": t["rows_got"],
                         "missing": t["missing"][:3], "extra": t["extra"][:3]}
                        for t in rep["tables"] if not t["ok"]]))
        if any(not r["ok"] for r in reps.values()):
            agreement[name] = _agreement(cfg, reps)
    report = {"run_id": run_id, "datasets": names, "engines": engine_names,
              "ok": all(r["status"] in ("pass", "not ported") for r in runs),
              "runs": runs, "agreement": agreement}
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    (out / "report.html").write_text(render_html(report))
    return out


CSS = """
:root { --bg: #fbfbfa; --fg: #1d1d1b; --muted: #6b6b66; --line: #e4e3df;
        --pass: #1f7a4d; --fail: #b4322e; --skip: #8a7a2e; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #161614; --fg: #ecebe7; --muted: #a09f99; --line: #34332f;
          --pass: #5fc48f; --fail: #f07a72; --skip: #d8c26a; } }
body { background: var(--bg); color: var(--fg); margin: 0 auto; max-width: 1100px;
       padding: 24px 16px; font: 14px/1.5 system-ui, sans-serif; }
h1 { font-size: 22px; margin: 0 0 4px; } h2 { font-size: 16px; margin: 28px 0 8px; }
p.meta { color: var(--muted); margin: 0 0 16px; }
.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; }
th, td { border-bottom: 1px solid var(--line); padding: 6px 10px; text-align: left;
         vertical-align: top; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
.pass { color: var(--pass); font-weight: 600; } .fail { color: var(--fail); font-weight: 600; }
.skip { color: var(--skip); } .muted { color: var(--muted); }
code { font: 12px ui-monospace, monospace; word-break: break-word; }
"""

CLASS = {"pass": "pass", "fail": "fail", "not run": "fail", "not ported": "muted"}


def _num(v, fmt: str = "{:,.1f}") -> str:
    return "" if v is None else fmt.format(v)


def render_html(rep: dict) -> str:
    e = html.escape
    engs, names = rep["engines"], rep["datasets"]
    by = {(r["name"], r["engine"]): r for r in rep["runs"]}
    head = "".join(f"<th>{e(x)}</th>" for x in engs)
    matrix = []
    for n in names:
        cells = []
        for x in engs:
            r = by.get((n, x))
            if r is None:
                cells.append("<td></td>")
                continue
            label = r["status"]
            if r["status"] == "fail":
                label += f" ({len(r['failed'])}/{r['tables']})"
            cells.append(f'<td class="{CLASS[r["status"]]}">{e(label)}</td>')
        matrix.append(f"<tr><th>{e(n)}</th>{''.join(cells)}</tr>")
    metrics = []
    for r in rep["runs"]:
        if r["status"] not in ("pass", "fail"):
            continue
        t = r["timings"]
        metrics.append(
            f"<tr><td>{e(r['name'])}</td><td>{e(r['engine'])}</td>"
            f'<td class="{CLASS[r["status"]]}">{e(r["status"])}</td>'
            f'<td class="num">{r["events"]:,}</td><td class="num">{_num(r["wall_s"], "{:.2f}")}</td>'
            f'<td class="num">{_num(t["load"], "{:.2f}")}</td>'
            f'<td class="num">{_num(t.get("plan"), "{:.2f}")}</td>'
            f'<td class="num">{_num(t["build"], "{:.2f}")}</td>'
            f'<td class="num">{_num(t["write"], "{:.2f}")}</td>'
            f'<td class="num">{_num(r["peak_rss_mb"], "{:,.0f}")}</td>'
            f'<td class="num">{_num(r["events_per_s"], "{:,.0f}")}</td></tr>')
    notes = [f"<li><b>{e(r['name'])}</b> on {e(r['engine'])}: {e(r['reason'])}</li>"
             for r in rep["runs"] if r["status"] == "not run"]
    fails = []
    for r in rep["runs"]:
        for f in r.get("failed", []):
            agree = rep["agreement"].get(r["name"], {}).get(f["name"], {}).get(r["engine"], [])
            fails.append(
                f"<tr><td>{e(r['name'])}</td><td>{e(r['engine'])}</td><td>{e(f['name'])}</td>"
                f"<td><code>{e(f['detail'])}</code></td>"
                f'<td class="num">{f["rows_expected"]:,}</td><td class="num">{f["rows_got"]:,}</td>'
                f"<td>{e(', '.join(agree)) or '<span class=\"muted\">none</span>'}</td>"
                f"<td><code>{e('; '.join(map(str, f['missing'][:2])))}</code></td>"
                f"<td><code>{e('; '.join(map(str, f['extra'][:2])))}</code></td></tr>")
    verdict = ('<span class="pass">all runs pass</span>' if rep["ok"]
               else '<span class="fail">some runs fail or did not run</span>')
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Engine Benchmark</title><style>{CSS}</style></head><body>
<h1>Engine benchmark</h1>
<p class="meta">run {e(rep['run_id'])} · {len(names)} datasets · {len(engs)} engines · {verdict}</p>
<h2>Results</h2><div class="scroll"><table><tr><th>dataset</th>{head}</tr>
{''.join(matrix)}</table></div>
{f"<h2>Not run</h2><ul>{''.join(notes)}</ul>" if notes else ""}
<h2>Metrics</h2><p class="meta">Seconds. Load: making the log readable (the replay into
Redpanda); plan: declaring and planning the blocks; build: the queries or the job; write: the
fold or the Parquet writes. Peak memory in MB: the run's own process tree plus the engine's
containers (an idle Flink cluster holds about 2.5 GB). Events per second over the whole run.</p>
<div class="scroll"><table><tr><th>dataset</th><th>engine</th><th>status</th><th>events</th>
<th>wall</th><th>load</th><th>plan</th><th>build</th><th>write</th><th>peak MB</th><th>events/s</th></tr>
{''.join(metrics)}</table></div>
{f'''<h2>Failing tables</h2><p class="meta">"agrees with" lists the engines whose output
of the table equals this engine's.</p><div class="scroll"><table><tr><th>dataset</th>
<th>engine</th><th>table</th><th>why</th><th>rows expected</th><th>rows got</th>
<th>agrees with</th><th>missing (sample)</th><th>extra (sample)</th></tr>{''.join(fails)}
</table></div>''' if fails else ""}
</body></html>
"""
