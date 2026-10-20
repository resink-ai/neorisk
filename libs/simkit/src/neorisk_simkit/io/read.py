"""Read a dataset directory back into frames (the same shape checks and replay use)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import polars as pl


@dataclass
class RunData:
    root: Path
    manifest: dict
    schema: dict
    events: dict[str, pl.DataFrame] = field(default_factory=dict)
    entities: dict[str, pl.DataFrame] = field(default_factory=dict)
    labels: pl.DataFrame | None = None
    cases: pl.DataFrame | None = None

    def all_events(self, cols: list[str] | None = None) -> pl.DataFrame:
        from neorisk_simkit.spec.types import COMMON
        keep = cols or list(COMMON)
        return pl.concat([df.select(keep) for df in self.events.values() if df.height]
                         ).sort("seq")


def _dir(root: Path, sub: str) -> dict[str, pl.DataFrame]:
    return {f.stem: pl.read_parquet(f) for f in sorted((root / sub).glob("*.parquet"))}


def read(run_dir: str | Path) -> RunData:
    root = Path(run_dir)
    mf = root / "manifest.json"
    if not mf.exists():
        raise FileNotFoundError(f"{root} is not a dataset (no manifest.json)")
    return RunData(root, json.loads(mf.read_text()),
                   json.loads((root / "schema" / "schema.json").read_text()),
                   _dir(root, "events"), _dir(root, "entities"),
                   pl.read_parquet(root / "labels" / "labels.parquet"),
                   pl.read_parquet(root / "cases" / "cases.parquet"))
