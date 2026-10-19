"""Referral program: first qualifying orders claim once; the pool budget resets per period;
inviters are credited one day later by an owner-to-owner message (D73); extension points."""

from datetime import timedelta
from pathlib import Path

import polars as pl
import pytest

from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events
from neorisk_simkit.spec.project import load_project, resolve_run

pytestmark = pytest.mark.large          # runs the ecommerce-sized module (Global Constraints)

EX = Path(__file__).resolve().parents[3] / "examples" / "ecommerce"
POOLS = ["engine.timer_nodes=600_000", "engine.payload_slots=100_000",
         "engine.max_messages_per_step=300_000", "budget.max_admissions_per_step=50_000",
         "budget.max_checker_keys=1_000_000"]
REF = ["users=3000", "skus=1200", "sku_groups=8", "run.span=21d", "run.warmup=0s",
       "referral.referred_share=0.3", "referral.inviter_share=0.1", "referral.min_order=1000",
       *POOLS]


def _run(tmp, extra=(), threads=4):
    res = run_to_dataset(EX, "sample", [*REF, *extra], out_dir=tmp / "run", threads=threads)
    return res, read_events(res.out_dir), pl.read_parquet(res.out_dir / "entities" / "user")


@pytest.fixture(scope="module")
def data(tmp_path_factory):
    return _run(tmp_path_factory.mktemp("ref"))


def test_qualifying_first_orders_claim_once(data):
    _res, ev, users = data
    referred = set(users.filter(pl.col("referred"))["id"])
    first = ev["order_placed"].sort("event_time", "lamport").group_by("user_id").first()
    want = set(first.filter((pl.col("amount") >= 1000)
                            & pl.col("user_id").is_in(list(referred)))["user_id"])
    paid = set(ev["referral_bonus_paid"].filter(pl.col("role") == "invitee")["user_id"])
    rejected = set(ev["referral_bonus_rejected"]["user_id"])
    assert paid | rejected <= want and len(paid | rejected) >= len(want) - 2
    assert not paid & rejected and len(paid) > 10


def test_inviters_are_credited_a_day_later_by_message(data):
    res, ev, _users = data
    assert res.manifest["late_messages"] == 0          # inviters never retire (D73 amendment)
    rb = ev["referral_bonus_paid"]
    inv = rb.filter(pl.col("role") == "invitee").select(
        pl.col("user_id").alias("invitee_id"), pl.col("event_time").alias("t0"))
    cr = rb.filter(pl.col("role") == "inviter").select("invitee_id", "user_id", "event_time")
    j = cr.join(inv, on="invitee_id")
    assert j.height == cr.height > 0
    assert (j["event_time"] - j["t0"] >= timedelta(days=1)).all(ignore_nulls=False)
    # invites come from the signup event: `entities/user.invited_by` is filled for everyone
    inviter_of = ev["user_signed_up"].select(pl.col("user_id").alias("invitee_id"),
                                             pl.col("invited_by").alias("expected"))
    invited = inviter_of.drop_nulls()
    assert invited.height > 0                                  # not vacuous (Task 15 M-2)
    assert (invited["invitee_id"] != invited["expected"]).all()
    k = j.join(inviter_of, on="invitee_id")
    assert k.height == j.height and k["expected"].null_count() == 0
    assert (k["user_id"] == k["expected"]).all(ignore_nulls=False)


def test_the_budget_resets_each_period(tmp_path):
    _res, ev, _u = _run(tmp_path, ["referral.monthly_budget=4000", "referral.period=2d"])
    g = ev["bonus_granted"].with_columns(
        (pl.col("event_time").cast(pl.Int64) // (2 * 86_400_000_000)).alias("w"))
    per = g.group_by("w").agg(pl.col("amount").sum())
    assert per["amount"].max() <= 4000 and per.height >= 2
    assert ev["bonus_rejected"].height > 0


def test_extension_points_are_exposed():
    plan = resolve_run(load_project(EX), "sample", []).plan
    assert set(plan.exposed) == {"signup", "signup_invited", "quick_order", "pay_referral",
                                 "claim_bonus"}
    assert tuple(plan.exposed_owners) == ("user",)


# ---------------------------------------------------------------- cause through the O2O buffer
# Task 12: the first real non-null cause carried by an owner-to-owner message. The engine keeps
# the sender's cause in the carried buffer's ceid column (route.py, D80) and stamps it on the
# delivered command, so the credit's cause is the invitee's payout in every step length and
# thread count.
SHAPES = {"1d-t4": ("1d", 4), "6h-t4": ("6h", 4), "1d-t1": ("1d", 1), "6h-t1": ("6h", 1)}
PAYOUT = ("event_time", "lamport", "user_id", "invitee_id", "role", "amount")


@pytest.fixture(scope="module")
def shaped(tmp_path_factory):
    out = {}
    for name, (step, threads) in SHAPES.items():
        res, ev, _u = _run(tmp_path_factory.mktemp(name),
                           [f"engine.step={step!r}", "engine.adapt=false"], threads=threads)
        out[name] = (res, ev)
    return out


def _credits_with_causes(res, ev) -> pl.DataFrame:
    """Every inviter credit with the payout row its `cause_id` names. Raw event ids depend on
    step boundaries (D13), so the cause is canonicalized (F-01) to the content of the event it
    names: population ids, times and lamports, none of which move with the step length."""
    assert res.manifest["late_messages"] == 0
    paid = ev["referral_bonus_paid"]
    credit = paid.filter(pl.col("role") == "inviter")
    assert credit.height > 0 and credit["cause_id"].null_count() == 0
    payout = paid.filter(pl.col("role") == "invitee").select(
        pl.col("event_id").alias("cause_id"),
        *[pl.col(c).alias(f"cause_{c}") for c in PAYOUT])
    j = credit.join(payout, on="cause_id", how="left")
    assert j.height == credit.height
    assert j.select(pl.col(f"cause_{c}" for c in PAYOUT).null_count()).sum_horizontal()[0] == 0
    assert (j["cause_invitee_id"] == j["invitee_id"]).all(ignore_nulls=False)
    assert (j["cause_role"] == "invitee").all(ignore_nulls=False)
    # the content key names one credit, so the sorted comparison below is exact (Task 15 M-1)
    assert credit.height == credit.select(PAYOUT).n_unique()
    return j.select(*[c for c in PAYOUT], *[f"cause_{c}" for c in PAYOUT]).sort(pl.all())


def test_credit_causes_cross_the_o2o_buffer_in_every_shape(shaped):
    canon = {name: _credits_with_causes(*shaped[name]) for name in SHAPES}
    ref = canon["1d-t4"]
    for name, df in canon.items():
        assert df.equals(ref), name
