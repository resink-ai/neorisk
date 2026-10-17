"""`manifest.json`: everything that identifies a run, deterministic under a fixed writer config
(no timings; those live in `run_stats.json`)."""

from __future__ import annotations

import dataclasses
import hashlib
import importlib.metadata
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa

import neorisk_simkit
from neorisk_simkit.io.writer import FileEntry, plan_columns, writer_options

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_REVISION_DIRS = ("spec", "engine", "std", "io", "checks")   # checks: counts are in the manifest


def engine_revision() -> str:
    """D22: package version + `@` + first 7 hex of sha256 over
    `{spec,engine,std,io,checks}/**/*.py` (`checks/` too: its counts go into the manifest)."""
    root = Path(neorisk_simkit.__file__).parent
    h = hashlib.sha256()
    for sub in _REVISION_DIRS:
        for p in sorted((root / sub).rglob("*.py"), key=lambda p: p.relative_to(root).as_posix()):
            h.update(p.relative_to(root).as_posix().encode() + b"\0" + p.read_bytes() + b"\0")
    return f"{importlib.metadata.version('neorisk-simkit')}@{h.hexdigest()[:7]}"


def uv_lock_sha256(project_dir: Path) -> str | None:
    """sha256 of the nearest `uv.lock` above (or in) the project folder, else None."""
    d = Path(project_dir).resolve()
    for folder in (d, *d.parents):
        lock = folder / "uv.lock"
        if lock.is_file():
            return hashlib.sha256(lock.read_bytes()).hexdigest()
    return None


def jsonable(v: Any) -> Any:
    """A JSON-safe copy of config values (dataclasses, mappings, tuples, numpy scalars)."""
    if dataclasses.is_dataclass(v) and not isinstance(v, type):
        return {f.name: jsonable(getattr(v, f.name)) for f in dataclasses.fields(v)}
    if isinstance(v, Mapping):
        return {str(k): jsonable(x) for k, x in v.items()}
    if isinstance(v, list | tuple):
        return [jsonable(x) for x in v]
    if isinstance(v, np.generic):
        return v.item()
    if isinstance(v, str | int | float | bool) or v is None:
        return v
    return repr(v)


def _rfc3339(us: int) -> str:
    return (_EPOCH + timedelta(microseconds=us)).isoformat().replace("+00:00", "Z")


def merged_config(run: Any) -> dict[str, Any]:
    return {"pack": jsonable(run.cfg), "budget": jsonable(run.budget),
            "engine": jsonable(run.engine),
            "run": {"mode": run.mode, "start": _rfc3339(run.start_us),
                    "span_us": run.span_us, "warmup_us": run.warmup_us}}


def write_manifest(run_dir: Path, run: Any, files: list[FileEntry], counts: dict[str, Any],
                   checks: dict[str, int], late_messages: int, *,
                   history_counts: dict[str, int] | None = None,
                   entity_counts: dict[str, int] | None = None,
                   project_dir: Path | None = None,
                   pairing: dict[str, dict[str, int]] | None = None,
                   posting_counts: dict[str, int] | None = None) -> dict[str, Any]:
    """Build and write `manifest.json`.

    `counts` is rows per event type; posting tables (D45), history groups and entity tables are
    counted apart in `posting_counts`, `history_counts` and `entity_counts`.
    `pairing` is `{request boundary: {"requests": delivered, "responses": routed}}` (D40)."""
    plan = run.plan
    options = writer_options(run.writer, *plan_columns(plan))
    writer = {k: (sorted(v) if isinstance(v, list) else v) for k, v in options.items()}
    writer["pyarrow"] = pa.__version__
    manifest = {
        "schema_version": plan.schema_version,
        "pack": plan.pack,
        "pack_revision": plan.revision,
        "engine_revision": engine_revision(),
        "uv_lock_sha256": uv_lock_sha256(project_dir) if project_dir is not None else None,
        "seed": int(run.seed),
        "profile": run.profile,
        "overrides": list(run.overrides),
        "config": merged_config(run),
        "writer": writer,
        "counts": dict(sorted(counts.items())),
        "history_counts": dict(sorted((history_counts or {}).items())),
        "posting_counts": dict(sorted((posting_counts or {}).items())),
        "entity_counts": dict(sorted((entity_counts or {}).items())),
        "checks": dict(checks),
        "late_messages": int(late_messages),
        "pairing": dict(sorted((pairing or {}).items())),
        "files": [{"path": f.path, "rows": f.rows, "sha256": f.sha256}
                  for f in sorted(files, key=lambda f: f.path)],
    }
    (Path(run_dir) / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    return manifest
