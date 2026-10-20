"""Write a run as a dataset directory: one Parquet file per table, plus manifest and schema.

    manifest.json   schema version, provenance, seed, config, counts, stats, files + sha256
    run_stats.json  timings and peak RSS (not part of replay identity)
    schema/schema.json
    events/<type>.parquet  entities/<table>.parquet  labels/labels.parquet
    cases/cases.parquet    snapshots/<kind>.parquet (opening state, with a warm-up)

Writer settings are fixed and recorded, so the same run gives byte-identical files.
"""

from __future__ import annotations

import hashlib
import json
import resource
import shutil
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

import polars as pl

from neorisk_simkit.engine.output import Output
from neorisk_simkit.schema import schema_json

WRITER = {"compression": "zstd", "compression_level": 3, "row_group_size": 131_072,
          "statistics": True, "polars": pl.__version__}


class DatasetExists(FileExistsError):
    pass


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _jsonable(x: Any) -> Any:
    if is_dataclass(x) and not isinstance(x, type):
        return {k: _jsonable(v) for k, v in asdict(x).items()}
    if isinstance(x, dict):
        return {str(k): _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if isinstance(x, (str, int, float, bool)) or x is None:
        return x
    return str(x)


def peak_rss_mb() -> float:
    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return r / (1024 * 1024) if sys.platform == "darwin" else r / 1024


def _write(df: pl.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path, compression="zstd", compression_level=3, statistics=True,
                     row_group_size=WRITER["row_group_size"])


def write(out: Output, out_dir: str | Path, *, provenance: dict | None = None,
          force: bool = False) -> Path:
    d = Path(out_dir)
    if d.exists() and any(d.iterdir()):
        if not force:
            raise DatasetExists(f"{d} exists; runs are deterministic, pass --force to overwrite")
        shutil.rmtree(d)
    d.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    for group, frames in (("events", out.events), ("entities", out.entities),
                          ("snapshots", out.snapshots)):
        for name, df in frames.items():
            p = d / group / f"{name}.parquet"
            _write(df, p)
            files.append(p)
    for p, df in ((d / "labels" / "labels.parquet", out.labels),
                  (d / "cases" / "cases.parquet", out.cases)):
        _write(df, p)
        files.append(p)
    schema = schema_json.build(out.plan)
    sp = d / "schema" / "schema.json"
    sp.parent.mkdir(exist_ok=True)
    sp.write_text(schema_json.dumps(schema))
    files.append(sp)
    st = out.stats
    manifest = {
        "pack": out.plan.name,
        "schema_version": out.plan.pack.schema_version,
        "overlays": {o.name: _jsonable(o.params) for o in out.plan.overlays},
        "provenance": _jsonable(provenance or {}),
        "seed": out.run.seed,
        "config": _jsonable(out.cfg),
        "run": _jsonable(out.run),
        "writer": WRITER,
        "counts": {**{f"events/{k}": v.height for k, v in out.events.items()},
                   **{f"entities/{k}": v.height for k, v in out.entities.items()},
                   "labels": out.labels.height, "cases": out.cases.height},
        "stats": {"late_messages": st.late_messages, "late_replies": st.late_replies,
                  "commands": st.commands,
                  "rejections": [{"kind": k, "action": a, "reason": r, "n": n}
                                 for (k, a, r), n in sorted(st.rejections.items())],
                  "censored_cases": int(out.cases["censored"].sum())},
        "files": {str(p.relative_to(d)): _sha(p) for p in sorted(files)},
    }
    (d / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (d / "run_stats.json").write_text(json.dumps(
        {**out.timings, "peak_rss_mb": round(peak_rss_mb(), 1),
         "events": sum(df.height for df in out.events.values())}, indent=2) + "\n")
    return d
