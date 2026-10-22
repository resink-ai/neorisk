"""The e-commerce pack: deterministic, linear, causal, and the legacy export bench reads."""

import time
import tracemalloc
from pathlib import Path

import polars as pl
import pytest

from neorisk_simkit.engine import simulate
from neorisk_simkit.io.legacy import legacy_fraud
from neorisk_simkit.project import load_project
from neorisk_simkit.spec import validate

ECOM = Path(__file__).resolve().parents[3] / "examples" / "ecommerce"


def _run(users=800, days=30, overlays=("bounty_hunters",), **sets):
    pr = load_project(ECOM)
    s = pr.settings(None, [f"users={users}", f"run.days={days}",
                           *(f"{k}={v}" for k, v in sets.items())], list(overlays))
    return simulate(pr.plan(s.overlays), s.config, s.run)


def test_pack_and_overlay_validate_clean():
    pr = load_project(ECOM)
    assert validate(pr.plan({"bounty_hunters": {}})) == []
    assert pr.lint() == []


def test_events_follow_their_causes():
    out = _run()
    signup = out.events["user_signed_up"].select("user_id", pl.col("event_time").alias("t0"))
    orders = out.events["order_placed"].join(signup, on="user_id")
    assert orders.height == out.events["order_placed"].height > 0
    assert (orders["event_time"] >= orders["t0"]).all()
    paid = out.events["referral_bonus_paid"]
    assert paid.height > 0 and paid["invitee_id"].is_unique().all()
    assert (paid["user_id"] != paid["invitee_id"]).all()
    # every bonus is caused by a claim request whose invitee ordered at least a day earlier
    first = (out.events["order_placed"].filter(pl.col("amount") >= 3000)
             .group_by("user_id").agg(pl.col("event_time").min().alias("t_order")))
    j = paid.join(first, left_on="invitee_id", right_on="user_id")
    assert j.height == paid.height
    assert ((j["event_time"] - j["t_order"]).dt.total_seconds() >= 86_400).all()


def test_monthly_budget_is_never_exceeded():
    out = _run(users=1500, monthly_budget_cents=30_000)
    paid = out.events["referral_bonus_paid"].with_columns(
        month=(pl.col("event_time") - pl.datetime(2026, 1, 1, time_zone="UTC"))
        .dt.total_days() // 30)
    assert out.events["referral_bonus_rejected"].height > 0
    assert paid.group_by("month").agg(pl.col("amount").sum())["amount"].max() <= 30_000


def _cost(users: int) -> tuple[float, int]:
    t = time.perf_counter()
    out = _run(users=users, days=20)
    return time.perf_counter() - t, sum(df.height for df in out.events.values())


def test_time_and_rows_scale_linearly_with_users():
    _cost(300)                                            # warm imports
    t1, r1 = _cost(1000)
    t4, r4 = _cost(4000)
    assert 3.0 < r4 / r1 < 5.0                            # output grows ~4x
    assert t4 / t1 < 6.0                                  # time grows ~linearly (§10)


def _peak(users: int) -> int:
    tracemalloc.start()
    _run(users=users, days=20)
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    return peak


def test_peak_memory_scales_linearly_with_users():
    m1, m4 = _peak(500), _peak(2000)
    assert m4 < 4 * m1 + 8 * 2**20                        # ~4x plus a constant


def test_legacy_export_has_labels_and_a_planted_signature():
    ds = legacy_fraud(_run(users=3000, days=40))
    assert ds.golden["event_id"].equals(ds.events["event_id"])
    assert 0.003 < ds.events["label"].mean() < 0.08
    g = ds.golden.join(ds.events.select("event_id", "event_type"), on="event_id")
    inv = g.filter(pl.col("event_type") == 1)
    z, n = inv.filter(pl.col("invitee_is_zombie") == 1), inv.filter(pl.col("invitee_is_zombie") == 0)
    assert z.height > 0 and n.height > 0
    assert z["inv_bonus_count_30d"].mean() > 2 * n["inv_bonus_count_30d"].mean()


@pytest.mark.parametrize("overlays", [(), ("bounty_hunters",)])
def test_same_seed_same_output(overlays):
    a, b = _run(500, 20, overlays), _run(500, 20, overlays)
    assert all(a.events[k].equals(b.events[k]) for k in a.events)
    assert all(a.entities[k].equals(b.entities[k]) for k in a.entities)
    assert a.labels.equals(b.labels)


def _signup_device_owner(out):
    devices = out.entities["devices"].select("device_id", pl.col("user_id").alias("owner"))
    users = out.entities["users"].select("user_id", "invited_by")
    return (out.events["user_signed_up"].select("user_id", "device_id")
            .join(devices, on="device_id").join(users, on="user_id"))


def test_stealth_and_promoters_blur_the_ring():
    def labeled(out):
        return set(out.labels.filter(pl.col("target_table") == "users")["target_id"])

    plain = _run(users=2000)
    s = _signup_device_owner(plain).filter(pl.col("user_id").is_in(labeled(plain))
                                           & pl.col("invited_by").is_not_null())
    assert s.height > 0 and (s["owner"] == s["invited_by"]).all()      # zombies: hunter's device
    shared = _signup_device_owner(plain).filter(pl.col("owner") == pl.col("invited_by"))
    assert set(shared["user_id"]) <= labeled(plain)                    # only the ring shares

    out = _run(users=2000, **{"bounty_hunters.stealth_p": 1.0,
                              "bounty_hunters.promoters_share": 0.01})
    ring = labeled(out)
    z = _signup_device_owner(out).filter(pl.col("user_id").is_in(ring)
                                         & pl.col("invited_by").is_not_null())
    assert z.height > 0 and (z["owner"] == z["user_id"]).all()         # stealth: own devices
    friends = _signup_device_owner(out).filter(pl.col("owner") == pl.col("invited_by"))
    assert friends.height > 0 and not set(friends["user_id"]) & ring   # look-alikes, unlabeled
    paid = out.events["referral_bonus_paid"]
    assert paid.filter(~pl.col("user_id").is_in(ring))["user_id"].value_counts()["count"].max() >= 3


def test_stealth_ring_members_carry_the_stealth_variant():
    plain = _run(users=2000)
    assert plain.labels["variant"].is_null().all()
    out = _run(users=2000, **{"bounty_hunters.stealth_p": 0.5})
    v = out.labels.filter(pl.col("target_table") == "users")["variant"]
    n = (v == "stealth").sum()
    assert 0 < n < v.len() and set(v.drop_nulls()) == {"stealth"}


def test_probing_is_off_by_default():
    out = _run(users=800)
    assert out.events["verification_failed"].height == 0


def test_probing_ring_members_fail_verification_and_test_the_threshold():
    out = _run(users=3000, **{"verify_fail_p": 0.03, "bounty_hunters.probe_p": 1.0})
    ring = out.labels.filter(pl.col("target_table") == "users")
    ring_ids = set(ring["target_id"])
    failed = set(out.events["verification_failed"]["user_id"])
    base = set(out.entities["users"]["user_id"]) - ring_ids
    assert len(failed & ring_ids) / len(ring_ids) > 0.9
    assert 0 < len(failed & base) / len(base) < 0.06                   # genuine retries: rare
    o = out.events["order_placed"].filter(pl.col("user_id").is_in(ring_ids))
    lo = 3000
    below = set(o.filter(pl.col("amount") < lo)["user_id"])
    zombies = set(ring.filter(pl.col("role") == "zombie")["target_id"])
    assert len(below & zombies) / len(zombies) > 0.8                   # tried under the minimum


def test_stealth_members_probe_less():
    out = _run(users=3000, **{"bounty_hunters.stealth_p": 0.5, "bounty_hunters.probe_p": 1.0,
                              "bounty_hunters.stealth_probe_p": 0.2})
    lab = out.labels.filter(pl.col("target_table") == "users").unique("target_id")
    failed = set(out.events["verification_failed"]["user_id"])
    rate = (lambda ids: len(set(ids) & failed) / max(len(ids), 1))
    st = lab.filter(pl.col("variant") == "stealth")["target_id"].to_list()
    vis = lab.filter(pl.col("variant").is_null())["target_id"].to_list()
    assert rate(vis) > 0.9 and 0.05 < rate(st) < 0.4
