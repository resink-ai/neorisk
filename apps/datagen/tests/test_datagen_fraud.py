import numpy as np
import polars as pl
import pytest
from sklearn.metrics import roc_auc_score

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
    g = ds.golden.filter(pl.col("event_id").is_in(first["event_id"].implode()))
    assert (g["u_amt_count_30d"] == 0).all()


def test_tiny_dataset_does_not_crash():
    out = generate(FraudConfig(n_events=300, seed=1, span_days=10))
    assert out.events.height == 300 and np.isfinite(out.golden["score"].to_numpy()).all()


def test_golden_rows_align_with_events_and_labels_follow_score(ds):
    # labels are attached by position from golden's score: row order must be identical
    assert ds.golden["event_id"].equals(ds.events["event_id"])
    j = ds.events.select("event_id", "label").join(
        ds.golden.select("event_id", "score"), on="event_id"
    )
    bad = j.filter(pl.col("label") == 1)["score"].mean()
    good = j.filter(pl.col("label") == 0)["score"].mean()
    assert bad > 2 * good


def _joined(ds):
    return ds.events.select("event_id", "event_time", "event_type", "user_id", "inviter_id").join(
        ds.golden, on="event_id", maintain_order="left"
    )


def _hunters(ds, min_degree=3):
    inv = ds.events.filter(pl.col("event_type") == 1).drop_nulls("inviter_id")
    deg = inv.group_by("inviter_id").len()
    return deg.filter(pl.col("len") >= min_degree)["inviter_id"]


def test_inviter_side_features_have_no_future_leakage(ds):
    j = _joined(ds)
    inv = j.filter(pl.col("event_type") == 1).drop_nulls("inviter_id")
    by_inviter = {
        k: list(zip(g["event_time"].to_list(), g["referral_bonus"].to_list()))
        for (k,), g in inv.join(
            ds.events.select("event_id", "referral_bonus"), on="event_id"
        ).group_by("inviter_id")
    }
    # oversample users who did invite, so the check is not dominated by trivial zeros
    inviters = j.filter(pl.col("user_id").is_in(_hunters(ds, 1).implode()))
    sample = pl.concat([inviters.sample(300, seed=0), j.sample(200, seed=1)])
    w = np.timedelta64(30, "D").astype("timedelta64[us]").item()
    nonzero = 0
    for r in sample.iter_rows(named=True):
        t = r["event_time"]
        vals = [b for ti, b in by_inviter.get(r["user_id"], []) if t - w <= ti < t]
        assert r["invr_bonus_count_30d"] == len(vals), r["event_id"]
        assert r["invr_bonus_sum_30d"] == pytest.approx(sum(vals)), r["event_id"]
        nonzero += bool(vals)
    assert nonzero > 50


def test_invitee_side_graph_features_are_point_in_time(ds):
    # on an invite row, inv_* aggregate the same inviter's earlier invites only
    j = _joined(ds)
    inv = j.filter(pl.col("event_type") == 1).drop_nulls("inviter_id")
    rows = inv.select("event_time", "inviter_id").to_dicts()
    w = np.timedelta64(30, "D").astype("timedelta64[us]").item()
    for r in inv.iter_rows(named=True):
        t = r["event_time"]
        n = sum(
            1 for x in rows if x["inviter_id"] == r["inviter_id"] and t - w <= x["event_time"] < t
        )
        assert r["inv_bonus_count_30d"] == n
    # later events of an invitee carry the values frozen at their invite
    frozen = inv.select("user_id", pl.col("inv_bonus_sum_30d").alias("at_invite"))
    later = j.filter(pl.col("event_type") == 0).join(frozen, on="user_id")
    assert later.height > 0
    assert (later["inv_bonus_sum_30d"] == later["at_invite"]).all()


def test_hunters_own_transactions_carry_inviter_side_features(ds):
    j = _joined(ds).filter(pl.col("event_type") == 0)
    is_h = pl.col("user_id").is_in(_hunters(ds).implode())
    hunter_txn = j.filter(is_h)
    assert hunter_txn.height > 0
    assert (hunter_txn["invr_bonus_count_30d"] > 0).mean() > 0.3
    assert hunter_txn["invr_zombie_mean_30d"].max() > 0.5
    others = j.filter(~is_h)
    assert others["invr_bonus_sum_30d"].mean() < 0.1 * hunter_txn["invr_bonus_sum_30d"].mean()


def test_zombie_invitees_transact_after_their_invite(ds):
    j = _joined(ds)
    zombies = j.filter((pl.col("event_type") == 1) & (pl.col("invitee_is_zombie") == 1))
    assert zombies.height > 0
    txn = j.filter(pl.col("event_type") == 0)
    first = txn.group_by("user_id").agg(pl.col("event_time").min().alias("first_txn"))
    z = zombies.select("user_id", "event_time").join(first, on="user_id", how="left")
    assert z["first_txn"].null_count() == 0
    assert (z["first_txn"] > z["event_time"]).all()


def test_graph_signal_drives_labels(ds):
    j = _joined(ds).join(ds.events.select("event_id", "label"), on="event_id")
    hunters = _hunters(ds)
    invited = ds.events.filter(
        (pl.col("event_type") == 1) & pl.col("inviter_id").is_in(hunters.implode())
    )["user_id"]
    linked = pl.col("user_id").is_in(pl.concat([hunters, invited]).implode())
    pos = j.filter(pl.col("label") == 1)
    assert pos.filter(linked).height / pos.height > 0.08
    assert j.filter(linked)["label"].mean() > 3 * j.filter(~linked)["label"].mean()


def test_new_golden_columns_present():
    for c in (
        "invr_bonus_count_30d",
        "invr_bonus_sum_7d",
        "invr_bonus_max_14d",
        "invr_zombie_mean_30d",
    ):
        assert c in generate(FraudConfig(n_events=500, seed=2, span_days=20)).golden.columns


def test_inviter_side_features_are_predictive(ds):
    j = _joined(ds).join(ds.events.select("event_id", "label"), on="event_id")
    is_h = pl.col("user_id").is_in(_hunters(ds).implode())
    hunters, others = j.filter(is_h), j.filter(~is_h)
    assert hunters.height > 0
    assert hunters["label"].mean() > 5 * others["label"].mean()
    assert roc_auc_score(j["label"], j["invr_bonus_sum_30d"]) > 0.57


def test_invites_and_inviter_features_exist_in_tail_of_span():
    cfg = FraudConfig(n_events=20000, seed=3, span_days=60)
    out = generate(cfg)
    t = out.events["event_time"]
    cut = t.min() + (t.max() - t.min()) * 0.8
    tail = out.events.filter(pl.col("event_time") >= cut)
    assert tail.filter(pl.col("event_type") == 1).height > 0
    g = tail.select("event_id").join(out.golden, on="event_id")
    assert (g["invr_bonus_count_30d"] > 0).sum() > 0


def test_zombie_bursts_do_not_pile_up_at_span_end():
    out = generate(FraudConfig(n_events=2000, seed=5, span_days=10))
    mult = out.events.group_by("event_time").len()["len"].max()
    assert mult <= 3
