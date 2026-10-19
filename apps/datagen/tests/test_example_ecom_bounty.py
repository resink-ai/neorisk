"""The bounty_hunters overlay: members are user rows executed by a campaign owner, emitting
only base events; zombies hug the minimum order, share the hunter's devices and claim from the
base pool; labels are hidden (§08 contract)."""

import json
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
SMALL = ["users=3000", "skus=1200", "sku_groups=8", "run.span=21d", "run.warmup=0s", *POOLS,
         "bounty_hunters.size=8", "bounty_hunters.arrive_day=1.0",
         "bounty_hunters.arrive_span_days=3.0", "bounty_hunters.qualify_timeout=7d"]
# a zombie claim timeout below the claim latency's 300 ms minimum: every grant arrives late
LATE = [*SMALL, "bounty_hunters.claim_timeout=100ms"]


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    return run_to_dataset(EX, "sample", SMALL, overlays=["bounty_hunters"],
                          out_dir=tmp_path_factory.mktemp("bh") / "run", threads=4)


@pytest.fixture(scope="module")
def ev(run):
    return read_events(run.out_dir)


@pytest.fixture(scope="module")
def members(run):
    u = pl.read_parquet(run.out_dir / "entities" / "user")
    return u.filter(pl.col("origin") == "member")


@pytest.fixture(scope="module")
def stats(run):
    return json.loads((run.out_dir / "run_stats.json").read_text())["machines"]


def _signups(ev, members):
    su = ev["user_signed_up"].join(members.select(pl.col("id").alias("user_id")), on="user_id")
    return (su.filter(pl.col("invited_by").is_null()),
            su.filter(pl.col("invited_by").is_not_null()))


def test_overlay_profiles_validate_and_keep_the_schema():
    base = resolve_run(load_project(EX), "sample", []).plan
    for profile in ("legacy", "abuse"):
        run = resolve_run(load_project(EX), profile, [])
        assert validate(run).ok, (profile, validate(run).errors)
        ev = [(e.name, e.cols) for e in run.plan.events if e.group == "events"]
        assert ev == [(e.name, e.cols) for e in base.events if e.group == "events"]


def test_overlay_parameters_never_change_the_source():
    a = resolve_run(load_project(EX), "sample", [], overlays=["bounty_hunters"]).plan
    b = resolve_run(load_project(EX), "sample", ["referral.min_order=1000",
                                                 "bounty_hunters.size=5",
                                                 "bounty_hunters.order_above_min=0.1",
                                                 "bounty_hunters.claim_timeout=100ms"],
                    overlays=["bounty_hunters"]).plan
    assert a.machine_sources == b.machine_sources        # D77, F-10: std.near bases are params


def test_members_are_hunters_and_their_zombies(ev, members):
    hunters, zombies = _signups(ev, members)
    assert hunters.height == 8 and zombies.height >= 8 * 3
    assert set(zombies["invited_by"]) <= set(hunters["user_id"])
    # members are never admitted as base owners, so no base process runs for them (suppress=
    # has no runtime effect, D74/F-22): every row naming a member comes from a campaign owner
    # (or from an order it created)
    plan = resolve_run(load_project(EX), "sample", SMALL, overlays=["bounty_hunters"]).plan
    code = {p.name: p.ptype_code for p in plan.partitions}
    rows = pl.concat([t.select("user_id", "partition_id") for t in ev.values()
                      if "user_id" in t.columns])
    mrows = rows.join(members.select(pl.col("id").alias("user_id")), on="user_id")
    assert mrows.height > 0 and (mrows["partition_id"] // (1 << 56) != code["user"]).all()
    # the acting-for user travels as the row's user_id, the campaign executes it (D74, Task 8)
    own = pl.concat([ev[n].select("user_id", "partition_id")
                     for n in ("user_signed_up", "order_placed", "referral_bonus_paid")])
    own = own.join(members.select(pl.col("id").alias("user_id")), on="user_id")
    assert own.height > 0 and (own["partition_id"] // (1 << 56) == code["campaign"]).all()


def test_zombies_hug_the_minimum_and_share_devices(ev, members):
    hunters, zombies = _signups(ev, members)
    orders = ev["order_placed"].join(zombies.select("user_id"), on="user_id")
    assert orders.height > 0
    assert orders["amount"].min() >= 3000 and orders["amount"].max() <= 3150
    dev = zombies.join(hunters.select(pl.col("user_id").alias("invited_by"),
                                      pl.col("device_id").alias("hunter_device")),
                       on="invited_by")
    assert dev.height == zombies.height
    assert (dev["device_id"] == dev["hunter_device"]).mean() >= 0.5


def test_labels_are_hidden_and_final_per_target(run, members):
    d = run.out_dir
    assert not (d / "events" / "labels_campaign").exists()
    labels = pl.read_parquet(sorted((d / "labels" / "labels_campaign").rglob("*.parquet")))
    last = labels.sort("event_time", "lamport").group_by("target_id").last()
    assert set(last["target_id"]) == set(members["id"])
    assert set(last["role"]) == {"hunter", "zombie"}
    assert (last["label_available_at"] > last["event_time"]).all()
    assert json.loads((d / "manifest.json").read_text())["label_counts"]["labels_campaign"] \
        == labels.height


def test_zombie_claims_reach_the_base_pool(ev, members):
    paid = ev["referral_bonus_paid"].join(members.select(pl.col("id").alias("invitee_id")),
                                          on="invitee_id")
    assert set(paid["role"]) == {"invitee", "inviter"}
    assert ev["bonus_granted"].height > paid.height // 2


def test_machine_stats_count_campaign_machines(ev, members, stats):
    # machines on several partitions (base fulfillment, cohort hunter/zombie): per-machine
    # counters land in their own entries (872fa42)
    hunters, zombies = _signups(ev, members)
    h, z = stats["hunter"], stats["zombie"]
    assert h["entries"]["new"] == h["entries"]["inviting"] == hunters.height == 8
    assert h["spawned"] == z["entries"]["invited"] == zombies.height
    paid = ev["referral_bonus_paid"].join(members.select(pl.col("id").alias("invitee_id")),
                                          on="invitee_id")
    assert z["entries"]["paid"] == paid.filter(pl.col("role") == "invitee").height > 0
    assert z["entries"]["ordered"] == ev["order_placed"].join(
        zombies.select("user_id"), on="user_id").height
    assert z["late_grants"] == 0 and h["late_grants"] == 0
    assert stats["fulfillment"]["entries"]["placed"] == ev["order_placed"].height


def test_hunters_cash_out_once_per_zombie_paid_in_time(ev, members, stats):
    # `jn` is a lifetime counter of the instance (Task 7); the hunter joins exactly once, so
    # it equals the zombies whose zombie_paid reached the join before it was left, and the
    # collecting state's max_repeats=std.field("jn") places one cash-out order per such zombie.
    # Payouts after the join was left are late (late="count"), never cashed out.
    hunters, zombies = _signups(ev, members)
    h = stats["hunter"]
    assert h["entries"]["collecting"] == h["entries"]["done"] == h["entries"]["gone"] == 8
    hunter_orders = ev["order_placed"].join(hunters.select("user_id"), on="user_id")
    assert hunter_orders["amount"].min() >= 9000 and hunter_orders["amount"].max() <= 18000
    payouts = ev["referral_bonus_paid"].filter(pl.col("role") == "invitee").join(
        zombies.select(pl.col("user_id").alias("invitee_id"), "invited_by"), on="invitee_id")
    assert hunter_orders.height == payouts.height - h["late"] > 0
    # per ring: a hunter never cashes out more than its own zombies were paid
    per = payouts.group_by("invited_by").len().rename({"invited_by": "user_id", "len": "paid"})
    cash = hunter_orders.group_by("user_id").len()
    j = cash.join(per, on="user_id", how="left")
    assert (j["len"] <= j["paid"]).all(ignore_nulls=False)


@pytest.fixture(scope="module")
def late(run, tmp_path_factory):
    # same plan source as `run` (the timeout is an op parameter, D77): no recompile
    return run_to_dataset(EX, "sample", LATE, overlays=["bounty_hunters"],
                          out_dir=tmp_path_factory.mktemp("bh_late") / "run", threads=4)


def test_late_grants_are_released_to_the_pool(late):
    # F-35, D67: a grant that arrives after the request timeout is stored, released with a
    # claim_refund message and counted in late_grants; the pool books it back
    ev = read_events(late.out_dir)
    st = json.loads((late.out_dir / "run_stats.json").read_text())["machines"]["zombie"]
    refunded = ev["bonus_refunded"]
    assert refunded.height == st["late_grants"] > 0
    assert set(refunded["claim_id"]) <= set(ev["bonus_granted"]["claim_id"])
    assert refunded["claim_id"].n_unique() == refunded.height
    granted = ev["bonus_granted"].select("claim_id", pl.col("amount").alias("granted"))
    j = refunded.join(granted, on="claim_id")
    assert j.height == refunded.height and (j["amount"] == j["granted"]).all()
    assert st["entries"]["paid"] == 0                   # a timed-out zombie is never paid
    assert late.manifest["laws"]["chk.referral_budget"]["violations"] == 0
