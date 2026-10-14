import numpy as np
import polars as pl
import pytest

from datagen.config import FraudConfig
from datagen.scenarios.fraud import generate

CFG = FraudConfig(n_events=6000, seed=7, span_days=60)


@pytest.fixture(scope="module")
def ds():
    return generate(CFG)


def test_config_validation():
    for bad in (
        {"n_events": 0},
        {"target_bad_rate": 0.0},
        {"target_bad_rate": 1.0},
        {"span_days": 0},
        {"invite_frac": 1.5},
    ):
        with pytest.raises(ValueError):
            FraudConfig(**bad).validate()


def test_deterministic():
    a, b = generate(CFG), generate(CFG)
    assert a.events.equals(b.events) and a.golden.equals(b.golden)


def test_shape_and_no_golden_in_events(ds):
    assert ds.events.height == CFG.n_events
    golden_cols = set(ds.golden.columns) - {"event_id"}
    assert not golden_cols & set(ds.events.columns)
    assert set(ds.events["event_id"]) == set(ds.golden["event_id"])
    for c in ("event_time", "user_id", "device_id", "amount", "label", "inviter_id"):
        assert c in ds.events.columns


def test_bad_rate_near_target(ds):
    assert 0.01 < ds.events["label"].mean() < 0.04


def test_attributes_are_stable_within_short_window(ds):
    ev = ds.events.filter(pl.col("event_type") == 0).sort("event_time")
    # static attribute: constant per device
    assert (
        ev.group_by("device_id").agg(pl.col("device_os").n_unique()).get_column("device_os").max()
        == 1
    )
    # slow attribute: few changes per user over the span
    chg = ev.group_by("user_id").agg(
        (pl.col("user_state").diff().fill_null(0) != 0).sum().alias("c"), pl.len().alias("n")
    )
    assert chg.filter(pl.col("n") > 5)["c"].mean() < 3


def test_invites_reference_other_users(ds):
    inv = ds.events.filter(pl.col("event_type") == 1)
    assert inv.height > 0
    ok = inv.drop_nulls("inviter_id")
    assert (ok["inviter_id"] != ok["user_id"]).all()
    txn = ds.events.filter(pl.col("event_type") == 0)
    assert txn["inviter_id"].null_count() == txn.height


def test_bounty_hunter_signature_is_planted(ds):
    g = ds.golden.join(ds.events.select("event_id", "event_type"), on="event_id")
    inv = g.filter(pl.col("event_type") == 1)
    zombie = inv.filter(pl.col("invitee_is_zombie") == 1)
    normal = inv.filter(pl.col("invitee_is_zombie") == 0)
    assert zombie.height > 0
    assert zombie["inv_bonus_sum_30d"].mean() > 2 * normal["inv_bonus_sum_30d"].mean()
    assert zombie["score"].mean() > normal["score"].mean()


def test_rolling_features_have_no_future_leakage(ds):
    first = (
        ds.events.filter(pl.col("event_type") == 0).sort("event_time").group_by("user_id").first()
    )
    g = ds.golden.filter(pl.col("event_id").is_in(first["event_id"]))
    assert (g["u_amt_count_30d"] == 0).all()


def test_tiny_dataset_does_not_crash():
    out = generate(FraudConfig(n_events=300, seed=1, span_days=10))
    assert out.events.height == 300 and np.isfinite(out.golden["score"].to_numpy()).all()
