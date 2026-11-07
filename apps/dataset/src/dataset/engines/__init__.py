"""Engine runs: one engine builds a dataset's results tables from its log, and the shared
grader compares them with `results/`.

An engine decodes the log into the views `refdata.logviews` makes, runs the dataset's port
(`-- table:` blocks, like `build.sql`) and writes `<run>/tables/<table>/*.parquet`. The
reference engine `duckdb` runs `specs/`; the others run `engines/spark/` or `engines/flink/`
(one Flink port serves both `flink` and `flink-stream`). A run folder is
`$NEORISK_DATA_ROOT/_runs/<name>/<version>/<engine>/<run-id>/`; its `run.json` is written
last, so a folder without one is an interrupted run, never a result.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from dataset.config import DatasetConfig
from dataset.names import data_root, resolve
from refdata.blocks import parse_blocks

ENGINES = ("duckdb", "spark", "flink", "flink-stream")
PORT_DIR = {"spark": "spark", "flink": "flink", "flink-stream": "flink"}


class EngineNotReady(RuntimeError):
    """The engine cannot run here; the message says how to make it ready."""


@dataclass
class Timings:
    build: float
    load: float | None = None
    write: float | None = None


@dataclass
class Built:
    timings: Timings
    errors: dict[str, str] = field(default_factory=dict)   # table -> why it was not written


@dataclass
class Job:
    cfg: DatasetConfig
    root: Path                                  # the built version: log/, schema/, results/
    out: Path                                   # the run folder; tables go in out/tables/
    blocks: dict[str, dict[str, str]]           # file stem -> table -> SQL, in block order
    columns: dict[str, list[tuple[str, pa.DataType]]]   # expected results columns
    events: int

    def table_dir(self, table: str) -> Path:
        return self.out / "tables" / table


def engine(name: str):
    if name == "duckdb":
        from dataset.engines.duck import DuckDB
        return DuckDB()
    if name == "spark":
        from dataset.engines.spark import Spark
        return Spark()
    if name == "flink":
        from dataset.engines.flink import Flink
        return Flink()
    if name == "flink-stream":
        from dataset.engines.stream import FlinkStream
        return FlinkStream()
    raise ValueError(f"unknown engine {name!r}; one of {', '.join(ENGINES)}")


def port_file(cfg: DatasetConfig, engine_name: str, stem: str) -> Path:
    base = cfg.dir / "specs" if engine_name == "duckdb" else (
        cfg.dir / "engines" / PORT_DIR[engine_name])
    return base / f"{stem}.sql"


def stems(cfg: DatasetConfig) -> list[str]:
    return list(cfg.designs) if cfg.kind == "synthetic" else ["build"]


def port_blocks(cfg: DatasetConfig, engine_name: str) -> dict[str, dict[str, str]]:
    """Each port file's blocks; a missing file has none."""
    out = {}
    for s in stems(cfg):
        f = port_file(cfg, engine_name, s)
        out[s] = ({b.name: b.sql for b in parse_blocks(f.read_text(), {"table"})}
                  if f.exists() else {})
    return out


def is_ported(cfg: DatasetConfig, engine_name: str) -> bool:
    return any(port_file(cfg, engine_name, s).exists() for s in stems(cfg))


def runs_dir(cfg: DatasetConfig, engine_name: str) -> Path:
    resolve(f"{cfg.name}/{cfg.version}")                 # the name rules
    return data_root() / "_runs" / cfg.name / cfg.version / engine_name


def _meta(root: Path) -> dict:
    f = root / "schema" / "results.json"
    if not f.exists():
        raise FileNotFoundError(f"{root.parent.name} {root.name} is not built under "
                                f"{root.parent.parent}; run: uv run dataset build "
                                f"{root.parent.name}")
    return json.loads(f.read_text())


def _events(root: Path) -> int:
    mf = root / "manifest.json"
    if mf.exists():
        return json.loads(mf.read_text())["counts"]["log"]
    return sum(pq.read_metadata(f).num_rows for f in (root / "log").glob("*.parquet"))


def _run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def run(cfg: DatasetConfig, engine_name: str, *, root: Path | None = None) -> dict:
    """One engine run, graded; returns (and writes) its `run.json`. Raises EngineNotReady
    before creating anything when the engine cannot run."""
    from dataset.engines import grade
    from dataset.engines.metrics import Sampler

    root = Path(root) if root else resolve(f"{cfg.name}/{cfg.version}")
    meta = _meta(root)
    eng = engine(engine_name)
    why = eng.check()
    if why:
        raise EngineNotReady(f"{engine_name}: {why}")
    base = runs_dir(cfg, engine_name)
    rid = _run_id()
    out = base / rid
    n = 1
    while out.exists():
        n += 1
        out = base / f"{rid}-{n}"
    out.mkdir(parents=True)
    columns = {t: [(f.name, f.type) for f in pq.read_schema(root / "results" / f"{t}.parquet")]
               for t in meta["tables"]}
    blocks = port_blocks(cfg, engine_name)
    job = Job(cfg, root, out, blocks, columns, _events(root))
    with Sampler(getattr(eng, "containers", ())) as sampler:
        t0 = time.perf_counter()
        built = eng.build(job)
        wall = time.perf_counter() - t0
    tables = grade.grade(job, meta, built.errors, engine_name)
    ok = all(t.ok for t in tables)
    rep = {"name": cfg.name, "version": cfg.version, "engine": engine_name,
           "run_id": out.name, "ok": ok, "events": job.events, "wall_s": round(wall, 3),
           "timings": {k: (None if v is None else round(v, 3))
                       for k, v in vars(built.timings).items()},
           "peak_rss_mb": sampler.peak_mb,
           "events_per_s": round(job.events / wall, 1) if wall > 0 else None,
           "tables": [t.to_json() for t in tables]}
    tmp = out / "run.json.tmp"
    tmp.write_text(json.dumps(rep, indent=2) + "\n")
    os.replace(tmp, out / "run.json")
    return rep


def latest_runs(cfg: DatasetConfig) -> dict[str, dict]:
    """Each engine's most recent completed run."""
    out = {}
    for e in ENGINES:
        d = runs_dir(cfg, e)
        done = sorted((p for p in d.glob("*/run.json")), key=lambda p: p.parent.name)
        if done:
            out[e] = json.loads(done[-1].read_text())
    return out

