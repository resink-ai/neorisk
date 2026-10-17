"""`run_to_dataset`: validate, simulate, stream sealed steps to the writer, write the manifest."""

from __future__ import annotations

import dataclasses
import hashlib
import os
import shutil
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow as pa

from neorisk_simkit.engine.run import Simulation
from neorisk_simkit.io.entities import EntityWriter
from neorisk_simkit.io.manifest import write_manifest
from neorisk_simkit.io.schema.schema_json import write_schema
from neorisk_simkit.io.stats import machine, peak_rss_bytes, write_run_stats
from neorisk_simkit.io.step_index import INDEX_PATH, step_index_row, write_step_index
from neorisk_simkit.io.writer import FileEntry, plan_columns, write_step, writer_options
from neorisk_simkit.spec.project import load_project, resolve_run
from neorisk_simkit.spec.validate import ValidationReport, validate

_ENGINE_COUNTERS = ("rejects", "retries", "late_messages", "continuations")


class ValidationFailed(Exception):
    """The run failed validation; `report` holds every error."""

    def __init__(self, report: ValidationReport):
        super().__init__("; ".join(report.errors))
        self.report = report


@dataclass(frozen=True)
class RunResult:
    out_dir: Path
    manifest: dict[str, Any]
    stats: dict[str, Any]


def _file_entry(run_dir: Path, rel: str, rows: int) -> FileEntry:
    return FileEntry(rel, rows, hashlib.sha256((run_dir / rel).read_bytes()).hexdigest())


def _simulate(run: Any, project_dir: Path, work: Path, threads: int, checked: bool):
    t_start = time.perf_counter()
    sim = Simulation(run, threads=threads, checked=checked)
    t_built = time.perf_counter()
    plan = run.plan
    files: list[FileEntry] = []
    index_rows: list[dict] = []
    entities = EntityWriter(work, run.writer, plan)
    counts = {e.name: 0 for e in plan.events}
    history_counts = {g.name: 0 for g in plan.change_groups}
    checks: dict[str, int] = {}
    write_s = 0.0
    try:
        w0 = time.perf_counter()
        entities.add(sim.static_entities())
        write_s += time.perf_counter() - w0
        for sealed in sim.steps():
            w0 = time.perf_counter()
            files.extend(write_step(work, sealed, run.writer, plan))
            entities.add(sealed.entities)
            write_s += time.perf_counter() - w0
            index_rows.append(step_index_row(sealed, plan))
            for name, t in sealed.events.items():
                counts[name] += t.num_rows
            for name, t in sealed.history.items():
                history_counts[name] += t.num_rows
            for name, n in sealed.stats.get("checks", {}).items():
                checks[name] = checks.get(name, 0) + n
    except BaseException:
        entities.abort()
        raise
    w0 = time.perf_counter()
    files.extend(entities.close())
    write_step_index(work, index_rows, writer_options(run.writer, *plan_columns(plan)))
    files.append(_file_entry(work, INDEX_PATH, len(index_rows)))
    write_schema(work, plan)
    files.append(_file_entry(work, "schema/schema.json", 0))
    write_s += time.perf_counter() - w0
    manifest = write_manifest(
        work, run, files, counts, checks, sim.stats["late_messages"],
        history_counts=history_counts, entity_counts=entities.counts(), project_dir=project_dir)
    t_done = time.perf_counter()
    return sim, manifest, {"build_s": t_built - t_start, "write_s": write_s,
                           "total_s": t_done - t_start, "manifest_at": t_done}


def run_to_dataset(project_dir: str | Path, profile: str = "sample",
                   overrides: Iterable[str] = (), *, seed: int | None = None,
                   out_dir: Path | None = None, threads: int | None = None,
                   checked: bool = False, force: bool = False,
                   engine_overrides: dict[str, Any] | None = None) -> RunResult:
    """Run one profile of a project into `out_dir` (default `<project>/<paths.out>/<run name>`).

    Raises `ValidationFailed` before creating any folder, `FileExistsError` if `out_dir` exists
    and `force` is false. The dataset is written to `<out_dir>.partial` and renamed when done."""
    t_entry = time.perf_counter()
    project = load_project(project_dir)
    run = resolve_run(project, profile, overrides, seed=seed)
    if engine_overrides:
        run = dataclasses.replace(run, engine=dataclasses.replace(run.engine,
                                                                  **engine_overrides))
    threads = int(threads if threads is not None else run.budget.threads)
    report = validate(run, threads)               # caps for the workers actually allocated
    if not report.ok:
        raise ValidationFailed(report)
    if out_dir is None:
        out_dir = project.dir / project.toml.get("paths", {}).get("out", "out") / run.name
    out_dir = Path(out_dir)
    if out_dir.exists() and not force:
        raise FileExistsError(f"{out_dir} already exists (use force to overwrite)")

    pa.set_cpu_count(threads)
    os.environ.setdefault("POLARS_MAX_THREADS", str(threads))

    work = out_dir.with_name(out_dir.name + ".partial")
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    try:
        sim, manifest, timing = _simulate(run, project.dir, work, threads, checked)
        timing["engine_s"] = timing.pop("manifest_at") - t_entry
        stats = _run_stats(sim, manifest, timing, threads)
        write_run_stats(work, stats)
        _install(work, out_dir)
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise
    return RunResult(out_dir, manifest, stats)


def _install(work: Path, out_dir: Path) -> None:
    """Move `work` to `out_dir`; an existing `out_dir` is set aside first and deleted only
    after the new folder is in place (restored if the final rename fails)."""
    if not out_dir.exists():
        work.rename(out_dir)
        return
    old = out_dir.with_name(out_dir.name + ".old")
    if old.exists():
        shutil.rmtree(old)
    out_dir.rename(old)
    try:
        work.rename(out_dir)
    except BaseException:
        old.rename(out_dir)
        raise
    shutil.rmtree(old)


def _run_stats(sim: Simulation, manifest: dict[str, Any], timing: dict[str, float],
               threads: int) -> dict[str, Any]:
    st = sim.stats
    rows = sum(manifest["counts"].values()) + sum(manifest["history_counts"].values())
    total = timing["total_s"]
    exported = sum(manifest["counts"].values())
    engine_s = timing["engine_s"]
    out = {
        "engine_seconds": engine_s,
        "exported_events": exported,
        "events_per_second": exported / engine_s if engine_s > 0 else 0.0,
        "proposals": st["proposals"],
        "requests_by_boundary": dict(st["requests_by_boundary"]),
        "timings": {"total_s": total, "build_s": timing["build_s"],
                    "generate_s": st["generate_s"], "seal_s": st["seal_s"],
                    "write_s": timing["write_s"]},
        "stage_seconds": {"build": timing["build_s"], "generate": st["generate_s"],
                          "seal": st["seal_s"], "write": timing["write_s"]},
        "rows": rows,
        "rows_per_s": rows / total if total > 0 else 0.0,
        "steps": st["steps"],
        "peak_rss_bytes": peak_rss_bytes(),
        "rounds_per_step": list(st["rounds_per_step"]),
        "round_detail": list(st["round_detail"]),
        "threads": threads,
        "machine": machine(),
    }
    for k in _ENGINE_COUNTERS:
        out[k] = dict(st[k]) if isinstance(st[k], dict) else st[k]
    return out
