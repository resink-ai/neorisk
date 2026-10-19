import numpy as np
import polars as pl
import pytest

from bench.runner import evaluate, load_events, oracle_frame, raw_features, run, time_split

pytest_plugins = ["legacy_fixture"]


@pytest.mark.large
def test_time_split_is_ordered_and_disjoint(legacy_dir):
    ev, _ = load_events(legacy_dir)
    tr, va, te = time_split(ev)
    assert tr.height + va.height + te.height == ev.height
    assert tr["event_time"].max() <= va["event_time"].min()
    assert va["event_time"].max() <= te["event_time"].min()


@pytest.mark.large
def test_raw_features_numeric_only_no_ids_no_label(legacy_dir):
    ev, _ = load_events(legacy_dir)
    x = raw_features(ev)
    assert "label" not in x.columns and not any(c.endswith("_id") for c in x.columns)
    assert all(t.is_numeric() for t in x.schema.values())
    assert x.null_count().sum_horizontal().item() == 0


@pytest.mark.large
def test_load_events_rejects_leaked_golden(legacy_dir, tmp_path):
    ev = pl.read_parquet(legacy_dir / "events.parquet").with_columns(
        u_amt_sum_7d=pl.lit(0.0))
    ev.write_parquet(tmp_path / "events.parquet")
    (tmp_path / "meta.json").write_text((legacy_dir / "meta.json").read_text())
    with pytest.raises(ValueError, match="golden"):
        load_events(tmp_path)


def test_evaluate_single_class_is_nan():
    m = evaluate(np.zeros(10, dtype=int), np.linspace(0, 1, 10))
    assert np.isnan(m["auc"]) and np.isnan(m["pr_auc"])


def test_evaluate_perfect_ranking():
    y = np.array([0, 0, 0, 1, 1])
    m = evaluate(y, np.array([0.1, 0.2, 0.3, 0.8, 0.9]))
    assert m["auc"] == 1.0 and m["recall_at_precision"] == 1.0


@pytest.mark.large
def test_oracle_beats_raw_beats_chance(legacy_dir):
    rows = run(legacy_dir, oracle=True)
    test = {r["model"]: r for r in rows if r["split"] == "test"}
    raw = max(test["logreg_raw"]["auc"], test["xgb_raw"]["auc"])
    assert test["xgb_oracle"]["auc"] > raw > 0.5


@pytest.mark.large
def test_oracle_features_exclude_score_but_include_golden(legacy_dir):
    ev, _ = load_events(legacy_dir)
    golden = pl.read_parquet(legacy_dir / "golden.parquet")
    assert "score" in golden.columns
    cols = raw_features(oracle_frame(ev, golden)).columns
    assert "score" not in cols
    assert "u_amt_count_7d" in cols


@pytest.mark.large
def test_load_events_requires_golden_columns_key(legacy_dir, tmp_path):
    import json

    (tmp_path / "events.parquet").write_bytes((legacy_dir / "events.parquet").read_bytes())
    meta = json.loads((legacy_dir / "meta.json").read_text())
    meta.pop("golden_columns")
    (tmp_path / "meta.json").write_text(json.dumps(meta))
    with pytest.raises(ValueError, match="golden_columns"):
        load_events(tmp_path)


@pytest.mark.large
def test_single_class_train_emits_nan_rows(legacy_dir, tmp_path):
    ev = pl.read_parquet(legacy_dir / "events.parquet")
    cut = ev["event_time"].sort()[int(ev.height * 0.7)]
    ev = ev.with_columns(
        label=pl.when(pl.col("event_time") < cut).then(0).otherwise(pl.col("label"))
    )
    ev.write_parquet(tmp_path / "events.parquet")
    (tmp_path / "meta.json").write_text((legacy_dir / "meta.json").read_text())
    rows = run(tmp_path)
    got = {(r["model"], r["split"]) for r in rows}
    assert got == {(m, s) for m in ("logreg_raw", "xgb_raw") for s in ("valid", "test")}
    for r in rows:
        assert np.isnan(r["auc"]) and np.isnan(r["pr_auc"]) and np.isnan(r["recall_at_precision"])


def test_raw_features_fill_nan_and_null():
    df = pl.DataFrame(
        {
            "a": [1.0, float("nan"), None],
            "b": pl.Series([1, None, 3], dtype=pl.Int64),
            "label": [0, 1, 0],
        }
    )
    x = raw_features(df)
    assert x["a"].to_list() == [1.0, -1.0, -1.0]
    assert x["b"].to_list() == [1, -1, 3]
    assert not np.isnan(x.to_numpy().astype("float64")).any()


def test_time_split_is_stable_under_input_order():
    t = np.datetime64("2026-01-01T00:00:00", "us") + np.repeat(np.arange(10), 10).astype(
        "timedelta64[h]"
    ).astype("timedelta64[us]")
    df = pl.DataFrame({"event_id": [f"e{i:03d}" for i in range(100)], "event_time": t})
    shuffled = df.sample(fraction=1.0, shuffle=True, seed=3)
    for a, b in zip(time_split(df), time_split(shuffled)):
        assert a["event_id"].equals(b["event_id"])
    tr, va, te = time_split(shuffled)
    joined = pl.concat([tr, va, te])
    assert joined.equals(df.sort("event_time", "event_id"))


@pytest.mark.large
def test_graph_golden_features_hidden_from_raw(legacy_dir):
    ev, meta = load_events(legacy_dir)
    # invr_zombie_mean_30d (latent zombie ratio) is not in the legacy export (ruling, D87)
    for c in ("invr_bonus_count_30d", "invr_bonus_mean_30d", "inv_bonus_sum_30d"):
        assert c in meta["golden_columns"]
        assert c not in ev.columns and c not in raw_features(ev).columns
    golden = pl.read_parquet(legacy_dir / "golden.parquet")
    assert "invr_bonus_sum_30d" in raw_features(oracle_frame(ev, golden)).columns
