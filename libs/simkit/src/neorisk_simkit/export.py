import json
from dataclasses import dataclass, field
from pathlib import Path

import polars as pl


@dataclass
class Dataset:
    events: pl.DataFrame  # raw benchmark input incl. label
    golden: pl.DataFrame  # event_id + hidden golden columns
    meta: dict = field(default_factory=dict)


def export(ds: Dataset, out_dir: str | Path) -> None:
    """Validate ``ds`` and write events.parquet, golden.parquet and meta.json.

    All checks run before anything is written, so a refused export leaves no files.
    """
    for col in ("event_id", "label"):
        if col not in ds.events.columns:
            raise ValueError(f"events is missing required column {col!r}")
    if "event_id" not in ds.golden.columns:
        raise ValueError("golden is missing required column 'event_id'")
    if ds.events.height == 0:
        raise ValueError("events is empty")
    if ds.events["label"].null_count() == ds.events.height:
        raise ValueError("events 'label' is all null")
    for name, frame in (("events", ds.events), ("golden", ds.golden)):
        if frame["event_id"].is_duplicated().any():
            raise ValueError(f"{name} has duplicate event_id values")
    golden_cols = [c for c in ds.golden.columns if c != "event_id"]
    leaked = [c for c in golden_cols if c in ds.events.columns]
    if leaked:
        raise ValueError(f"golden columns present in events: {leaked}")
    if set(ds.golden["event_id"]) != set(ds.events["event_id"]):
        raise ValueError("event_id sets differ between events and golden")

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    ds.events.write_parquet(out / "events.parquet")
    ds.golden.write_parquet(out / "golden.parquet")
    meta = {
        **ds.meta,
        "golden_columns": golden_cols,
        "n_events": ds.events.height,
        "bad_rate": float(ds.events["label"].mean()),
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2, default=str))
