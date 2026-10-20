"""`datagen export --single-file`: every event in one canonically ordered Parquet file.

The unified schema is the common columns plus every type's columns, nullable; categoricals
become strings, since different types declare different category sets.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from neorisk_simkit.io.read import RunData


def unified(run: RunData) -> pl.DataFrame:
    frames = [df.with_columns(pl.col(pl.Enum).cast(pl.String))
              for df in run.events.values() if df.height]
    return pl.concat(frames, how="diagonal_relaxed").sort("seq")


def single_file(run: RunData, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    unified(run).write_parquet(p, compression="zstd", compression_level=3)
    return p
