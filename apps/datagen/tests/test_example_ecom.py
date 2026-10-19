"""examples/ecommerce: the real pack runs; carts, holds, orders, fulfillment and laws (D91)."""

import json
from datetime import timedelta
from pathlib import Path

import polars as pl
import pytest

from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events
from neorisk_simkit.spec.project import load_project, resolve_run
from neorisk_simkit.spec.validate import validate

pytestmark = pytest.mark.large

EX = Path(__file__).resolve().parents[3] / "examples" / "ecommerce"
POOLS = ["engine.timer_nodes=600_000", "engine.payload_slots=100_000",
         "engine.max_messages_per_step=300_000", "budget.max_admissions_per_step=50_000",
         "budget.max_checker_keys=1_000_000"]
SMALL = ["users=3000", "skus=1200", "sku_groups=8", "run.span=14d", "run.warmup=0s", *POOLS]
# warm-up 0 (F-13): entities keep warm-up orders while their events are dropped (D20), and
# machine entries count every step; warm-up runs are covered by Task 23 and the S1/S2 suites


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    return run_to_dataset(EX, "sample", SMALL, out_dir=tmp_path_factory.mktemp("ecom") / "run",
                          threads=4)


@pytest.fixture(scope="module")
def ev(run):
    return read_events(run.out_dir)


def test_base_profiles_validate():
    # F-41: before writing this test run `datagen validate examples/ecommerce --profile full`;
    # if the caps exceed the profile's budget, raise `[profiles.full.set] "budget.memory"` (never
    # shrink the workload) and note in datagen.toml when the total exceeds this machine's
    # ~30 GiB ("full: not measured on the 36 GiB machine")
    for profile in ("sample", "full"):
        rep = validate(resolve_run(load_project(EX), profile, []))
        assert rep.ok, (profile, rep.errors)


def test_refund_law_reads_the_one_order_partition():
    # state-side sum_le reads the first owner partition of its right-hand table (Task 13 M-3):
    # `order` has exactly one in every profile, and overlays cannot add one (a cohort owns a new
    # table named after it and acts only for an exposed owner, which `order` is not);
    # `legacy` and `abuse` run the bounty_hunters overlay (Task 16)
    for profile in ("sample", "full", "legacy", "abuse"):
        run = resolve_run(load_project(EX), profile, [])
        assert validate(run).ok, (profile, validate(run).errors)
        plan = run.plan
        orders = [p.name for p in plan.partitions if p.kind == "owner" and p.table == "order"]
        assert orders == ["order"] and tuple(plan.exposed_owners) == ("user",), profile
        cohorts = [p.name for p in plan.partitions if p.acts_for is not None]
        assert cohorts == (["campaign"] if profile in ("legacy", "abuse") else []), profile


def test_hold_window_follows_the_hold_ttl():
    plan = resolve_run(load_project(EX), "sample", ["desk.hold_ttl_s=900"]).plan
    law = next(c.law for c in plan.checks if c.id == "chk.holds_resolved")
    assert law.arg("within") == "1200s"                 # TTL + HOLD_SLACK_S, never a literal


def test_carts_have_several_lines_and_every_line_is_decided(ev):
    started = ev["checkout_started"]
    assert started["lines"].max() >= 3 and started.height > 100
    decided = pl.concat([ev["stock_reserved"].select("checkout_id"),
                         ev["stock_rejected"].select("checkout_id")]).group_by("checkout_id").len()
    j = started.select("checkout_id", "lines").join(decided, on="checkout_id")
    assert j.height == started.height and (j["len"] == j["lines"].cast(pl.UInt32)).all()


def test_orders_commit_every_hold_and_failures_release_them(ev):
    holds = ev["stock_reserved"].select("checkout_id", "hold_id")
    fate = pl.concat([ev[n].select("hold_id", pl.lit(n).alias("fate"))
                      for n in ("stock_committed", "stock_released", "stock_expired")])
    j = holds.join(fate, on="hold_id")
    placed = set(ev["order_placed"]["checkout_id"])
    ok = j.filter(pl.col("checkout_id").is_in(list(placed)))
    assert ok.height > 0 and (ok["fate"] == "stock_committed").all()
    bad = j.filter(~pl.col("checkout_id").is_in(list(placed)))
    assert (bad["fate"] != "stock_committed").all()


def test_each_order_is_a_created_owner_running_fulfillment(run, ev):
    orders = pl.read_parquet(run.out_dir / "entities" / "order")
    assert orders.height == ev["order_placed"].height > 50
    shipped = set(ev["order_shipped"]["order_id"]) | set(ev["order_lost"]["order_id"])
    assert shipped <= set(orders["id"])
    st = json.loads((run.out_dir / "run_stats.json").read_text())["machines"]["fulfillment"]
    assert st["entries"]["placed"] == orders.height
    assert st["entries"]["shipped"] == ev["order_shipped"].height


def test_required_laws_were_checked(run):
    laws = run.manifest["laws"]
    for cid in ("chk.order_lifecycle", "chk.refund_le_paid", "chk.holds_resolved",
                "chk.credit_never_negative"):
        assert laws[cid]["checked"] > 0 and laws[cid]["violations"] == 0, cid


LAWS = ("chk.stock_never_negative", "chk.reserved_never_negative", "chk.holds_resolved",
        "chk.refund_le_paid", "chk.order_lifecycle", "chk.referral_once_per_invitee",
        "chk.referral_budget", "chk.credit_never_negative", "chk.hold_never_negative",
        "chk.pool_never_negative")


def test_every_law_is_checked_and_holds(run):
    laws = run.manifest["laws"]
    assert sorted(laws) == sorted(LAWS)
    for cid in LAWS:
        assert laws[cid]["checked"] > 0 and laws[cid]["violations"] == 0, (cid, laws[cid])


def test_inviter_credits_land_a_day_later_with_their_cause(run, ev):
    # owner-to-owner `inviter_credit` (D73): the inviter is a population user present from the
    # start that always keeps its own timers (sessions, moves), so no credit is late
    paid = ev["referral_bonus_paid"]
    credit = paid.filter(pl.col("role") == "inviter")
    assert credit.height > 0 and run.manifest["late_messages"] == 0
    payout = paid.filter(pl.col("role") == "invitee").select(
        "invitee_id", pl.col("event_time").alias("t_paid"), pl.col("event_id").alias("cause"))
    invited = ev["user_signed_up"].select(pl.col("user_id").alias("invitee_id"), "invited_by")
    j = credit.join(payout, on="invitee_id").join(invited, on="invitee_id")
    assert j.height == credit.height > 0
    # a null comparison is null and `.all()` skips nulls by default: count nulls explicitly
    assert j.select(pl.col("cause_id", "invited_by", "t_paid").null_count()).row(0) == (0, 0, 0)
    assert (j["user_id"] == j["invited_by"]).all(ignore_nulls=False)
    assert (j["user_id"] != j["invitee_id"]).all(ignore_nulls=False)
    assert ((j["event_time"] - j["t_paid"]) >= timedelta(days=1)).all(ignore_nulls=False)
    assert (j["cause_id"] == j["cause"]).all(ignore_nulls=False)    # the invitee's payout


def test_addresses_change_slowly(run):
    hist = pl.read_parquet(sorted((run.out_dir / "history" / "address").rglob("*.parquet")))
    assert hist.height > 0
    users = pl.read_parquet(run.out_dir / "entities" / "user").height
    assert 0.15 <= hist.height / users <= 0.5           # ~14/45 = 0.31 moves per user (F-37)
