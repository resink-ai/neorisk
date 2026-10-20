"""The event simulator: deterministic, linear in entities, and the legacy export bench reads."""

import time

import polars as pl

from neorisk_simkit.ecommerce import Config, simulate
from neorisk_simkit.legacy import legacy_fraud


def test_same_seed_same_output():
    a, b = simulate(Config(users=500, days=20)), simulate(Config(users=500, days=20))
    assert a.keys() == b.keys() and all(a[k].equals(b[k]) for k in a)


def _cost(users: int) -> tuple[float, int]:
    t = time.perf_counter()
    out = simulate(Config(users=users, days=20))
    return time.perf_counter() - t, sum(df.height for df in out.values())


def test_time_and_rows_scale_linearly_with_users():
    _cost(500)                                            # warm imports
    t1, r1 = _cost(2000)
    t4, r4 = _cost(8000)
    assert 3.0 < r4 / r1 < 5.0                            # output grows ~4x
    assert t4 / t1 < 4 * 1.6                              # time grows ~linearly, not worse


def test_events_follow_their_causes():
    out = simulate(Config(users=800, days=30))
    signup = out["user_signed_up"].select("user_id", pl.col("event_time").alias("t0"))
    orders = out["order_placed"].join(signup, on="user_id")
    assert orders.height > 0 and (orders["event_time"] >= orders["t0"]).all()
    paid = out["referral_bonus_paid"]
    assert paid.height > 0 and paid["invitee_id"].is_unique().all()
    assert (paid["user_id"] != paid["invitee_id"]).all() and paid.null_count().sum_horizontal()[0] == 0


def test_legacy_export_has_labels_and_a_planted_signature():
    ds = legacy_fraud(simulate(Config(users=3000, days=40)))
    assert ds.golden["event_id"].equals(ds.events["event_id"])
    assert 0.003 < ds.events["label"].mean() < 0.08
    g = ds.golden.join(ds.events.select("event_id", "event_type"), on="event_id")
    inv = g.filter(pl.col("event_type") == 1)
    z, n = inv.filter(pl.col("invitee_is_zombie") == 1), inv.filter(pl.col("invitee_is_zombie") == 0)
    assert z.height > 0 and n.height > 0
    assert z["inv_bonus_count_30d"].mean() > 2 * n["inv_bonus_count_30d"].mean()
