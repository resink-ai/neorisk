"""Reading a dataset back: every step file of an event type, in canonical order."""

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


def read_events(dataset_dir: Path, types: list[str] | None = None) -> dict[str, pl.DataFrame]:
    """`{event type: rows}` for the requested types (default: every event type of the schema);
    steps are in increasing order and every step file is canonical, so rows are canonical.
    A type without files yields an empty frame with its schema."""
    d = Path(dataset_dir)
    doc = load_schema(d)
    names = {t["name"]: t for t in doc["tables"] if t["kind"] == "event"}
    wanted = list(names) if types is None else list(types)
    out: dict[str, pl.DataFrame] = {}
    for name in wanted:
        if name not in names:
            raise KeyError(f"unknown event type {name!r}")
        files = sorted((d / "events" / name).glob("date=*/step-*.parquet"),
                       key=lambda p: (p.name, p.parent.name))
        out[name] = (pl.concat([pl.read_parquet(f) for f in files]) if files
                     else _empty(names[name]))
    return out
