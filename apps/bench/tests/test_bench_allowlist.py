import json

import polars as pl
import pytest

from bench.allowlist import ENGINE_COLUMNS, resolve_allowlist
from bench.features import build_features
from bench.runner import load_events, raw_features

pytest_plugins = ["legacy_fixture"]


def _events():
    return pl.DataFrame({
        "event_id": [1, 2], "event_time": [1, 2], "user_id": [5, 6], "amount": [1.0, 2.0],
        "lamport": [1, 2], "partition_id": [7, 7], "seq": [0, 1], "action_id": [0, 0],
        "label": [0, 1]})


def test_engine_columns_are_never_features():
    allowed = resolve_allowlist({}, _events())
    assert allowed == ["amount"] and not set(allowed) & ENGINE_COLUMNS
    assert raw_features(_events(), allowed).columns == ["amount"]


def test_meta_allowlist_restricts_and_is_validated():
    ev = _events().with_columns(pl.col("amount").alias("amount2"))
    assert resolve_allowlist({"feature_allowlist": ["amount2"]}, ev) == ["amount2"]
    with pytest.raises(ValueError, match="missing columns"):
        resolve_allowlist({"feature_allowlist": ["nope"]}, ev)
    with pytest.raises(ValueError, match="forbidden columns"):
        resolve_allowlist({"feature_allowlist": ["lamport"]}, ev)
    with pytest.raises(ValueError, match="forbidden columns"):
        resolve_allowlist({"feature_allowlist": ["label"]}, ev)
    with pytest.raises(ValueError, match="forbidden columns"):
        resolve_allowlist({"feature_allowlist": ["g1"], "golden_columns": ["g1"]},
                          ev.with_columns(pl.lit(0).alias("g1")))


@pytest.mark.large
def test_legacy_dataset_carries_an_allowlist_equal_to_todays_raw_set(legacy_dir):
    meta = json.loads((legacy_dir / "meta.json").read_text())
    events, loaded = load_events(legacy_dir)
    assert meta["feature_allowlist"] == loaded["_allowlist"]
    assert raw_features(events, loaded["_allowlist"]).columns == raw_features(events).columns
    a = build_features(events, loaded["_allowlist"])
    b = build_features(events)
    assert a.columns == b.columns
