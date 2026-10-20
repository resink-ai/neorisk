"""§07 trace: a bounty-hunter campaign against a capped bonus pool.

Zombies' first orders above the minimum make claims; the pool shard processes every claim,
from rings and normal shoppers alike, in canonical order, so the cap is exact: each month it
grants exactly the cap (the demand exceeds it), never a grant after the first rejection, and
a rejected zombie's label outcome is "rejected" while a paid one's is "paid".
"""

from datetime import timedelta
from pathlib import Path

import polars as pl
import pytest

from neorisk_simkit.checks import failed, run_checks
from neorisk_simkit.engine import simulate
from neorisk_simkit.project import load_project

ECOM = Path(__file__).resolve().parents[3] / "examples" / "ecommerce"
CAP = 15_000                                   # 15 bonuses of $10 a month


@pytest.fixture(scope="module")
def out():
    pr = load_project(ECOM)
    s = pr.settings(None, ["users=1500", "run.days=60", f"monthly_budget_cents={CAP}"],
                    ["bounty_hunters"])
    s.overlays["bounty_hunters"]["share"] = 0.01
    plan = pr.plan(s.overlays)
    o = simulate(plan, s.config, s.run)
    assert failed(run_checks(o, plan.checks)) == []
    return o


def _decisions(out):
    month = ((pl.col("event_time") - pl.datetime(2026, 1, 1, time_zone="UTC")).dt.total_days()
             // 30).alias("month")
    paid = out.events["referral_bonus_paid"].select("seq", month, pl.lit("paid").alias("d"),
                                                    "invitee_id")
    rej = out.events["referral_bonus_rejected"].select("seq", month,
                                                       pl.lit("rejected").alias("d"),
                                                       "invitee_id")
    return pl.concat([paid, rej]).sort("seq")


def test_the_cap_is_exact_and_rejections_follow_exhaustion(out):
    d = _decisions(out)
    for _, g in d.group_by("month"):
        g = g.sort("seq")
        n_paid = (g["d"] == "paid").sum()
        assert n_paid * 1000 <= CAP
        if (g["d"] == "rejected").any():
            assert n_paid * 1000 == CAP                   # demand exceeded the cap: exact
            first_rej = g.filter(pl.col("d") == "rejected")["seq"].min()
            assert g.filter(pl.col("seq") > first_rej)["d"].eq("rejected").all()
    assert (d["d"] == "rejected").sum() > 0


def test_both_rings_and_shoppers_are_rejected_and_labels_say_so(out):
    d = _decisions(out).filter(pl.col("d") == "rejected")
    ns = d["invitee_id"] >= 1_000_000_000
    assert ns.any() and (~ns).any()                       # zombies and normal invitees
    z = out.labels.filter(pl.col("role") == "zombie")
    assert {"paid", "rejected"} <= set(z["outcome"])
    paid = set(out.events["referral_bonus_paid"]["invitee_id"])
    assert set(z.filter(pl.col("outcome") == "paid")["target_id"]) <= paid


def test_the_pool_decides_at_claim_time_and_the_zombie_hears_later(out):
    # decision rows carry the claim time; the zombie learns the outcome after the pool latency
    lab = out.labels.filter(pl.col("outcome").is_in(["paid", "rejected"]))
    dec = pl.concat([out.events["referral_bonus_paid"].select("invitee_id", "event_time"),
                     out.events["referral_bonus_rejected"].select("invitee_id", "event_time")])
    j = lab.join(dec, left_on="target_id", right_on="invitee_id")
    lag = j["labeled_at"] - j["event_time"]
    assert j.height > 0
    assert (lag >= timedelta(seconds=0.2)).all() and (lag <= timedelta(seconds=0.8)).all()
