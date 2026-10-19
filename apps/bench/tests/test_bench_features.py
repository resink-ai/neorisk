from datetime import timedelta

import numpy as np
import polars as pl
import pytest

from bench.features import IDENTIFIER_LIKE, build_features, feature_names

pytest_plugins = ["legacy_fixture"]


@pytest.fixture(scope="module")
def events(legacy_dir):
    return pl.read_parquet(legacy_dir / "events.parquet")


@pytest.fixture(scope="module")
def feats(events):
    return build_features(events)


@pytest.mark.large
def test_rows_align_with_events_and_no_nulls(events, feats):
    assert feats["event_id"].equals(events["event_id"])
    names = feature_names(feats)
    assert names and all(feats.schema[c].is_numeric() for c in names)
    assert feats.select(pl.col(names).is_null().sum()).row(0) == (0,) * len(names)
    floats = [c for c in names if feats.schema[c].is_float()]
    assert feats.select(pl.col(floats).is_nan().sum()).row(0) == (0,) * len(floats)


@pytest.mark.large
def test_no_label_golden_or_id_columns(events, feats):
    names = set(feature_names(feats))
    assert "label" not in names and "event_time" not in names
    assert not any(c.endswith("_id") for c in names)
    assert not names & set(IDENTIFIER_LIKE)
    for banned in ("score", "invitee_is_zombie", "amt_ratio_30d"):
        assert banned not in names


@pytest.mark.large
def test_features_do_not_depend_on_labels(events, feats):
    shuffled = events.with_columns(
        label=pl.Series(np.random.default_rng(0).permutation(events["label"].to_numpy()))
    )
    assert build_features(shuffled).equals(feats)


@pytest.mark.large
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


@pytest.mark.large
def test_inviter_side_counts_invites_before_event(events, feats):
    inv = events.filter(pl.col("event_type") == 1).drop_nulls("inviter_id")
    # the busiest inviter that has rows of its own: a hunter cashes out only after its join,
    # which can fall past the end of the run (the old generator's top inviter always had rows)
    acting = inv.filter(pl.col("inviter_id").is_in(events["user_id"].implode()))
    hunter = acting.group_by("inviter_id").len().sort("len", descending=True)["inviter_id"][0]
    mine = events.filter(pl.col("user_id") == hunter).select("event_id", "event_time")
    got = mine.join(feats.select("event_id", "obs_invr_bonus_count_30d"), on="event_id")
    assert got.height > 0 and got["obs_invr_bonus_count_30d"].null_count() == 0
    assert got["obs_invr_bonus_count_30d"].max() > 0


@pytest.mark.large
def test_missing_required_column_raises(events):
    with pytest.raises(ValueError, match="inviter_id"):
        build_features(events.drop("inviter_id"))


@pytest.mark.large
def test_invitee_side_inviter_activity_is_point_in_time(events, feats):
    inv = events.filter((pl.col("event_type") == 1) & pl.col("inviter_id").is_not_null())
    inv_rows = inv.to_dicts()
    by_inviter: dict[str, list] = {}
    for r in inv_rows:
        by_inviter.setdefault(r["inviter_id"], []).append(r)
    got = events.select("event_id", "user_id", "event_time").join(
        feats.select("event_id", "obs_inv_bonus_count_30d", "obs_inv_bonus_sum_30d"),
        on="event_id",
    )
    by_user = {k: v for (k,), v in got.partition_by("user_id", as_dict=True).items()}
    checked_before = checked_after = nonzero = 0
    for r in inv_rows:
        t_inv = r["event_time"]
        lo = t_inv - timedelta(days=30)
        others = [
            x
            for x in by_inviter[r["inviter_id"]]
            if x["event_id"] != r["event_id"] and lo <= x["event_time"] < t_inv
        ]
        exp_count = len(others)
        exp_sum = sum(x["referral_bonus"] for x in others)
        for e in by_user.get(r["user_id"], got.clear()).to_dicts():
            if e["event_time"] < t_inv:
                assert e["obs_inv_bonus_count_30d"] == 0
                assert e["obs_inv_bonus_sum_30d"] == 0
                checked_before += 1
            elif e["event_time"] > t_inv:
                assert e["obs_inv_bonus_count_30d"] == exp_count
                assert e["obs_inv_bonus_sum_30d"] == pytest.approx(exp_sum)
                checked_after += 1
                nonzero += exp_count > 0
    # the old generator's "an invitee's invite is its first event" no longer holds: the bonus
    # (the invite row) is paid after the invitee's qualifying order, so both sides are checked
    assert checked_before > 0 and checked_after > 0 and nonzero > 0


def test_window_semantics_on_hand_built_frame():
    from datetime import datetime

    t0 = datetime(2026, 1, 1)
    d = timedelta(days=1)
    times = [t0, t0 + 7 * d, t0 + 7 * d, t0 + 14 * d, t0 + 3 * d]
    n = len(times)
    frame = pl.DataFrame(
        {
            "event_id": [f"e{i}" for i in range(n)],
            "event_time": pl.Series(times, dtype=pl.Datetime("us")),
            "event_type": [0] * n,
            "user_id": ["a"] * 4 + ["b"],
            "device_id": ["d"] * n,
            "inviter_id": pl.Series([None] * n, dtype=pl.String),
            "amount": [1.0, 2.0, 4.0, 8.0, 16.0],
            "referral_bonus": pl.Series([None] * n, dtype=pl.Int64),
            "user_state": [1] * n,
        }
    )
    out = build_features(frame).sort("event_id")
    cnt = out["obs_u_amt_count_7d"].to_list()
    sm = out["obs_u_amt_sum_7d"].to_list()
    # e0: nothing before; e1/e2: t-w boundary (e0) included, identical-timestamp twin excluded;
    # e3: window [t0+7d, t0+14d) holds both ties, e0 (t0+14d-7d > t0) is out; b is separate.
    assert cnt == [0, 1, 1, 2, 0]
    assert sm == [0.0, 1.0, 1.0, 6.0, 0.0]


def test_invitee_lookup_is_backward_and_per_user_on_hand_built_frame():
    from datetime import datetime

    t0 = datetime(2026, 1, 1)
    d = timedelta(days=1)
    # (id, time, type, user, inviter, amount, bonus)
    rows = [
        ("x_inv", t0 + 1 * d, 1, "x", "a", None, 3),  # a invites x
        ("c_txn0", t0 + 2 * d, 0, "c", None, 5.0, None),  # c before being invited
        ("c_inv", t0 + 5 * d, 1, "c", "a", None, 4),  # a invites c; a's prior invite: x (3)
        ("c_txn1", t0 + 6 * d, 0, "c", None, 5.0, None),
        ("z_txn", t0 + 6 * d, 0, "z", None, 5.0, None),  # uninvited user stays 0
        ("y_inv", t0 + 40 * d, 1, "y", "a", None, 9),  # later invite; must not leak backward
    ]
    frame = pl.DataFrame(
        {
            "event_id": [r[0] for r in rows],
            "event_time": pl.Series([r[1] for r in rows], dtype=pl.Datetime("us")),
            "event_type": [r[2] for r in rows],
            "user_id": [r[3] for r in rows],
            "device_id": ["d"] * len(rows),
            "inviter_id": pl.Series([r[4] for r in rows], dtype=pl.String),
            "amount": pl.Series([r[5] for r in rows], dtype=pl.Float64),
            "referral_bonus": pl.Series([r[6] for r in rows], dtype=pl.Int64),
            "user_state": [1] * len(rows),
        }
    )
    out = build_features(frame).select(
        "event_id", "obs_inv_bonus_count_30d", "obs_inv_bonus_sum_30d"
    )
    got = {
        r["event_id"]: (r["obs_inv_bonus_count_30d"], r["obs_inv_bonus_sum_30d"])
        for r in out.to_dicts()
    }
    assert got["c_txn0"] == (0, 0)
    assert got["c_inv"] == (1, 3)
    assert got["c_txn1"] == (1, 3)
    assert got["z_txn"] == (0, 0)
    assert got["x_inv"] == (0, 0)
    assert got["y_inv"] == (0, 0)  # a's invites at day 1 and 5 are >30d old
