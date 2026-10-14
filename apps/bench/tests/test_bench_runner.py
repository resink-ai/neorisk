import numpy as np
import polars as pl
import pytest

from bench.runner import evaluate, load_events, raw_features, run, time_split
from datagen.cli import main as datagen_main


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory):
    out = tmp_path_factory.mktemp("fraud")
    datagen_main(
        [
            "generate",
            "--scenario",
            "fraud",
            "--n-events",
            "20000",
            "--seed",
            "11",
            "--span-days",
            "60",
            "--out",
            str(out),
        ]
    )
    return out


def test_time_split_is_ordered_and_disjoint(data_dir):
    ev, _ = load_events(data_dir)
    tr, va, te = time_split(ev)
    assert tr.height + va.height + te.height == ev.height
    assert tr["event_time"].max() <= va["event_time"].min()
    assert va["event_time"].max() <= te["event_time"].min()


def test_raw_features_numeric_only_no_ids_no_label(data_dir):
    ev, _ = load_events(data_dir)
    x = raw_features(ev)
    assert "label" not in x.columns and not any(c.endswith("_id") for c in x.columns)
    assert all(t.is_numeric() for t in x.schema.values())
    assert x.null_count().sum_horizontal().item() == 0


def test_load_events_rejects_leaked_golden(data_dir, tmp_path):
    ev = pl.read_parquet(data_dir / "events.parquet").with_columns(u_amt_sum_7d=pl.lit(0.0))
    ev.write_parquet(tmp_path / "events.parquet")
    (tmp_path / "meta.json").write_text((data_dir / "meta.json").read_text())
    with pytest.raises(ValueError, match="golden"):
        load_events(tmp_path)


def test_evaluate_single_class_is_nan():
    m = evaluate(np.zeros(10, dtype=int), np.linspace(0, 1, 10))
    assert np.isnan(m["auc"]) and np.isnan(m["pr_auc"])


def test_evaluate_perfect_ranking():
    y = np.array([0, 0, 0, 1, 1])
    m = evaluate(y, np.array([0.1, 0.2, 0.3, 0.8, 0.9]))
    assert m["auc"] == 1.0 and m["recall_at_precision"] == 1.0


def test_oracle_beats_raw_beats_chance(data_dir):
    rows = run(data_dir, oracle=True)
    test = {r["model"]: r for r in rows if r["split"] == "test"}
    raw = max(test["logreg_raw"]["auc"], test["xgb_raw"]["auc"])
    assert test["xgb_oracle"]["auc"] > raw > 0.5
