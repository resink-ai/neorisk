"""Reading a dataset back: every step file of an event or posting type, in canonical order."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pyarrow as pa

from neorisk_simkit.io.schema.schema_json import load_schema
from neorisk_simkit.spec.types import LType, arrow_type


def _empty(table: dict) -> pl.DataFrame:
    schema = pa.schema([pa.field(c["name"], arrow_type(LType(c["type"])), c["nullable"])
                        for c in table["columns"]])
    return pl.from_arrow(schema.empty_table())


def _read(dataset_dir: Path, kind: str, folder: str,
          names_wanted: list[str] | None) -> dict[str, pl.DataFrame]:
    d = Path(dataset_dir)
    doc = load_schema(d)
    names = {t["name"]: t for t in doc["tables"] if t["kind"] == kind}
    wanted = list(names) if names_wanted is None else list(names_wanted)
    out: dict[str, pl.DataFrame] = {}
    for name in wanted:
        if name not in names:
            raise KeyError(f"unknown {kind} type {name!r}")
        files = sorted((d / folder / name).glob("date=*/step-*.parquet"),
                       key=lambda p: (p.name, p.parent.name))
        out[name] = (pl.concat([pl.read_parquet(f) for f in files]) if files
                     else _empty(names[name]))
    return out


def read_events(dataset_dir: Path, types: list[str] | None = None) -> dict[str, pl.DataFrame]:
    """`{event type: rows}` for the requested types (default: every event type of the schema);
    steps are in increasing order and every step file is canonical, so rows are canonical.
    A type without files yields an empty frame with its schema."""
    return _read(dataset_dir, "event", "events", types)


def read_postings(dataset_dir: Path,
                  names: list[str] | None = None) -> dict[str, pl.DataFrame]:
    """`{posting table: rows}` (D45; default: every posting table of the schema), read from
    `postings/` like `read_events`."""
    return _read(dataset_dir, "posting", "postings", names)
