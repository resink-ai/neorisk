"""Public ids (§12, optional, off by default): `datagen export RUN --public-ids --out DIR`
copies a dataset with every id replaced by a seeded Feistel permutation of (table, id) into
62 bits, so ids look random but stay unique, positive int64 and consistent: a `ref` column
maps through its target table's key, `event_id` and `cause_id` through the event space, and
label targets through their table. `seq` and `partition_id` (ordering and provenance) stay.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import polars as pl

from neorisk_simkit.engine.rng import key as stable_key
from neorisk_simkit.io.read import RunData
from neorisk_simkit.io.writer import _sha, _write

HALF = 31
MASK = np.uint64((1 << HALF) - 1)


def feistel(ids: np.ndarray, space: str, seed: int, rounds: int = 4) -> np.ndarray:
    """A keyed bijection on [0, 2^62): equal inputs give equal outputs, distinct give distinct."""
    x = ids.astype(np.uint64)
    left, right = (x >> np.uint64(HALF)) & MASK, x & MASK
    for r in range(rounds):
        k = np.uint64(stable_key(seed, space, r) & ((1 << HALF) - 1))
        f = ((right * np.uint64(0x9E3779B1) + k) ^ (right >> np.uint64(13))) & MASK
        left, right = right, left ^ f
    return ((left << np.uint64(HALF)) | right).astype(np.int64)


def _map(s: pl.Series, space: str, seed: int) -> pl.Series:
    vals = s.to_numpy(allow_copy=True)
    nulls = s.is_null().to_numpy()
    out = feistel(np.where(nulls, 0, vals).astype(np.int64), space, seed)
    return pl.Series(s.name, out, dtype=pl.Int64).scatter(np.flatnonzero(nulls), None)


def export_public(run: RunData, out_dir: str | Path, seed: int | None = None) -> Path:
    seed = run.manifest["seed"] if seed is None else seed
    d = Path(out_dir)
    if d.exists():
        shutil.rmtree(d)
    tables = {t["name"]: t for t in run.schema["tables"]}

    def convert(df: pl.DataFrame, t: dict) -> pl.DataFrame:
        cols = []
        for c in t["columns"]:
            name = c["name"]
            if name not in df.columns:
                continue
            if c["type"] == "ref":
                cols.append(_map(df[name], c["ref"], seed))
            elif name in ("event_id", "cause_id"):
                cols.append(_map(df[name], "event", seed))
            elif t["group"] == "entity" and name == t.get("key"):
                cols.append(_map(df[name], t["name"], seed))
        return df.with_columns(cols) if cols else df

    files = []
    for group, frames in (("events", run.events), ("entities", run.entities)):
        for name, df in frames.items():
            p = d / group / f"{name}.parquet"
            _write(convert(df, tables[name]), p)
            files.append(p)
    lab = run.labels
    if lab.height:
        parts = [g.with_columns(_map(g["target_id"], g["target_table"][0], seed))
                 for g in lab.partition_by("target_table", maintain_order=True)]
        lab = pl.concat(parts).sort("labeled_at", maintain_order=True)
    for p, df in ((d / "labels" / "labels.parquet", lab),
                  (d / "cases" / "cases.parquet", run.cases)):
        _write(df, p)
        files.append(p)
    (d / "schema").mkdir(parents=True, exist_ok=True)
    shutil.copy(run.root / "schema" / "schema.json", d / "schema" / "schema.json")
    files.append(d / "schema" / "schema.json")
    m = {**run.manifest, "public_ids": {"method": "feistel-62", "seed": seed},
         "files": {str(p.relative_to(d)): _sha(p) for p in sorted(files)}}
    (d / "manifest.json").write_text(json.dumps(m, indent=2) + "\n")
    return d
