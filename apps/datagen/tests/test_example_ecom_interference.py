"""Hunters drain the referral budget: base claims are rejected more often with the overlay
(§08 regression rule, interference report)."""

from pathlib import Path

import pytest

from neorisk_simkit.checks.interference import compare, shared_partitions
from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.spec.project import load_project, resolve_run

pytestmark = pytest.mark.large

EX = Path(__file__).resolve().parents[3] / "examples" / "ecommerce"
POOLS = ["engine.timer_nodes=600_000", "engine.payload_slots=100_000",
         "engine.max_messages_per_step=300_000", "budget.max_admissions_per_step=50_000",
         "budget.max_checker_keys=1_000_000"]
BASE = ["users=3000", "skus=1200", "sku_groups=8", "run.span=21d", "run.warmup=0s", *POOLS,
        "referral.referred_share=0.3", "referral.inviter_share=0.1", "referral.min_order=1000",
        "referral.monthly_budget=60000"]
# The referral period is a 30-day window aligned to the epoch: 2026-01-07 (day 6) opens one.
# Base claims alone exhaust this budget minutes after each window opens (day 0: 30 grants by
# 00:24), so rings arriving on day 1 are all rejected and change nothing; arriving with the
# day-6 reset, they take grants base shoppers would have had.
OVL = ["bounty_hunters.size=10", "bounty_hunters.arrive_day=6.0",
       "bounty_hunters.arrive_span_days=1.0", "bounty_hunters.qualify_timeout=7d"]


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("intf")
    a = run_to_dataset(EX, "sample", BASE, out_dir=tmp / "base", threads=4).out_dir
    b = run_to_dataset(EX, "sample", [*BASE, *OVL], overlays=["bounty_hunters"],
                       out_dir=tmp / "with", threads=4).out_dir
    plan = resolve_run(load_project(EX), "sample", [*BASE, *OVL],
                       overlays=["bounty_hunters"]).plan
    return compare(a, b, plan)


def test_the_overlay_shares_only_the_pool():
    plan = resolve_run(load_project(EX), "sample", [], overlays=["bounty_hunters"]).plan
    assert shared_partitions(plan) == ("referral_pool",)


def test_exogenous_draws_and_laws_hold(report):
    assert report["exogenous_identical"] is True
    assert report["laws_ok"] == {"base": True, "with": True}


def test_base_claims_are_crowded_out(report):
    rej = report["events"]["referral_bonus_rejected"]
    assert rej["with"] > rej["base"]
    assert report["changed_owners"]["referral_bonus_paid"] > 0
