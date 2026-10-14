import json

import polars as pl
import pytest

from neorisk_simkit import Dataset, export


def _ds(**overrides):
    events = pl.DataFrame({"event_id": ["a", "b"], "amount": [1.0, 2.0], "label": [0, 1]})
    golden = pl.DataFrame({"event_id": ["a", "b"], "vel_7d": [0.0, 3.0], "score": [0.1, 0.9]})
    ds = Dataset(events, golden, {"scenario": "t", "seed": 1})
    for k, v in overrides.items():
        setattr(ds, k, v)
    return ds


def test_export_writes_files_and_meta(tmp_path):
    export(_ds(), tmp_path)
    ev = pl.read_parquet(tmp_path / "events.parquet")
    gd = pl.read_parquet(tmp_path / "golden.parquet")
    meta = json.loads((tmp_path / "meta.json").read_text())
    assert ev.columns == ["event_id", "amount", "label"]
    assert gd.columns == ["event_id", "vel_7d", "score"]
    assert meta["golden_columns"] == ["vel_7d", "score"]
    assert meta["n_events"] == 2 and meta["bad_rate"] == 0.5 and meta["seed"] == 1


def test_export_refuses_golden_column_in_events(tmp_path):
    leaky = _ds().events.with_columns(vel_7d=pl.lit(0.0))
    with pytest.raises(ValueError, match="vel_7d"):
        export(_ds(events=leaky), tmp_path)


def test_export_requires_label_and_matching_ids(tmp_path):
    with pytest.raises(ValueError, match="label"):
        export(_ds(events=_ds().events.drop("label")), tmp_path)
    with pytest.raises(ValueError, match="event_id"):
        export(_ds(golden=_ds().golden.head(1)), tmp_path)
