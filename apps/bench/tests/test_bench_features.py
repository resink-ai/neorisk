from datetime import timedelta

import numpy as np
import polars as pl
import pytest

from bench.features import IDENTIFIER_LIKE, build_features, feature_names
from datagen.config import FraudConfig
from datagen.scenarios.fraud import generate


@pytest.fixture(scope="module")
def events():
    return generate(FraudConfig(n_events=5000, seed=5, span_days=40)).events


@pytest.fixture(scope="module")
def feats(events):
    return build_features(events)


def test_rows_align_with_events_and_no_nulls(events, feats):
    assert feats["event_id"].equals(events["event_id"])
    names = feature_names(feats)
    assert names and all(feats.schema[c].is_numeric() for c in names)
    assert feats.select(pl.col(names).is_null().sum()).row(0) == (0,) * len(names)
    floats = [c for c in names if feats.schema[c].is_float()]
    assert feats.select(pl.col(floats).is_nan().sum()).row(0) == (0,) * len(floats)


def test_no_label_golden_or_id_columns(events, feats):
    names = set(feature_names(feats))
    assert "label" not in names and "event_time" not in names
    assert not any(c.endswith("_id") for c in names)
    assert not names & set(IDENTIFIER_LIKE)
    for banned in ("score", "invitee_is_zombie", "amt_ratio_30d"):
        assert banned not in names


def test_features_do_not_depend_on_labels(events, feats):
    shuffled = events.with_columns(
        label=pl.Series(np.random.default_rng(0).permutation(events["label"].to_numpy()))
    )
    assert build_features(shuffled).equals(feats)


def test_velocity_matches_bruteforce(events, feats):
    txn = events.filter(pl.col("event_type") == 0).select("user_id", "event_time", "amount")
    rows = txn.to_dicts()
    by_user: dict[str, list] = {}
    for r in rows:
        by_user.setdefault(r["user_id"], []).append(r)
    joined = events.select("event_id", "user_id", "event_time", "event_type").join(
        feats.select("event_id", "obs_u_amt_count_30d", "obs_u_amt_sum_30d"), on="event_id"
    )
    sample = joined.filter(pl.col("event_type") == 0).head(300).to_dicts()

    for r in sample:
        lo = r["event_time"] - timedelta(days=30)
        prior = [x for x in by_user[r["user_id"]] if lo <= x["event_time"] < r["event_time"]]
        assert r["obs_u_amt_count_30d"] == len(prior)
        assert r["obs_u_amt_sum_30d"] == pytest.approx(sum(x["amount"] for x in prior))


def test_inviter_side_counts_invites_before_event(events, feats):
    inv = events.filter(pl.col("event_type") == 1).drop_nulls("inviter_id")
    hunter = inv.group_by("inviter_id").len().sort("len", descending=True)["inviter_id"][0]
    mine = events.filter(pl.col("user_id") == hunter).select("event_id", "event_time")
    got = mine.join(feats.select("event_id", "obs_invr_bonus_count_30d"), on="event_id")
    assert got["obs_invr_bonus_count_30d"].max() > 0


def test_missing_required_column_raises(events):
    with pytest.raises(ValueError, match="inviter_id"):
        build_features(events.drop("inviter_id"))
