"""A built version's manifest, and the lock file that records it in git.

The manifest lists every file of `<root>/<name>/<version>/` with its sha256 and (for
Parquet) its rows, plus a sha256 of the recipe and of the source. The lock,
`datasets/<name>/<version>.lock.json`, is the manifest without `counts`: once committed, a
build that does not reproduce it exactly fails, and changed output needs a new version.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pyarrow.parquet as pq

LOCK_KEYS = ("name", "version", "kind", "writer", "recipe_sha256", "source_sha256", "files")


def writer() -> dict:
    """The libraries whose versions decide the files' bytes (Parquet footers name them)."""
    import polars as pl
    import pyarrow as pa
    return {"polars": pl.__version__, "pyarrow": pa.__version__}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def recipe_sha256(d: Path) -> str:
    """Over the sorted (path, sha256) of `specs/**`, `dataset.toml` and `datagen.toml`; never
    CONTEXT.md or the lock files, so editing the prose does not change the version."""
    files = [p for p in sorted((d / "specs").rglob("*"))
             if p.is_file() and "__pycache__" not in p.parts]
    files += [d / n for n in ("dataset.toml", "datagen.toml") if (d / n).exists()]
    h = hashlib.sha256()
    for p in sorted(files, key=lambda p: p.relative_to(d).as_posix()):
        h.update(f"{p.relative_to(d).as_posix()}\0{sha256(p)}\n".encode())
    return h.hexdigest()


def files_of(root: Path) -> dict[str, dict]:
    out = {}
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        if not p.is_file() or rel == "manifest.json":
            continue
        entry = {"sha256": sha256(p)}
        if p.suffix == ".parquet":
            entry["rows"] = pq.ParquetFile(p).metadata.num_rows
        out[rel] = entry
    return out


def lock_of(manifest: dict) -> dict:
    return {k: manifest[k] for k in LOCK_KEYS}


def lock_diff(lock: dict, manifest: dict) -> list[str]:
    """What differs between a recorded lock and a new build: field names and file paths."""
    diff = [k for k in LOCK_KEYS if k != "files" and lock.get(k) != manifest.get(k)]
    a, b = lock.get("files", {}), manifest["files"]
    diff += sorted(p for p in set(a) | set(b) if a.get(p) != b.get(p))
    return diff


def write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=False) + "\n")
