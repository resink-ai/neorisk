import json
from pathlib import Path

import polars as pl
import pytest

from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events

pytestmark = pytest.mark.large

EX = Path(__file__).resolve().parents[3] / "examples" / "ecommerce_s2"
POOLS = ["engine.timer_nodes=600_000", "engine.payload_slots=100_000",
         "engine.max_messages_per_step=300_000", "budget.max_admissions_per_step=50_000",
         "budget.max_checker_keys=2_000_000"]
CAP = 60_000
DRAIN = ["users=3000", "skus=1200", "sku_groups=8", "run.span=10d", "run.warmup=0s",
         "referred_share=0.5", f"pool_cap={CAP}", "hunt.share=0.05", *POOLS]


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    return run_to_dataset(EX, "sample", DRAIN, out_dir=tmp_path_factory.mktemp("pool") / "run",
                          threads=4)


@pytest.fixture(scope="module")
def ev(run):
    return read_events(run.out_dir)


def _decisions(ev):
    return pl.concat([ev["bonus_granted"].select("event_time", "lamport", "claim_id", "source",
                                                 "amount", pl.lit(True).alias("ok")),
                      ev["bonus_rejected"].select("event_time", "lamport", "claim_id", "source",
                                                  "amount", pl.lit(False).alias("ok"))]
                     ).sort("event_time", "lamport")


def test_the_cap_is_exact(ev):
    g = ev["bonus_granted"]
    assert g["amount"].sum() == CAP                     # drained to the cent
    assert g.sort("event_time", "lamport")["remaining_after"].to_list()[-1] == 0
    d = _decisions(ev)
    last_grant = d.with_row_index().filter(pl.col("ok"))["index"].max()
    assert not d[: last_grant + 1].filter(~pl.col("ok")).height   # no rejection before drained


def test_each_claim_is_decided_once(ev):
    d = _decisions(ev)
    assert d["claim_id"].n_unique() == d.height > 0


def test_both_sources_draw_and_users_are_rejected(ev):
    """Both claim sources reach the pool and normal users are rejected once it runs dry. In
    this drain workload users alone would exhaust it, so this is not a crowd-out measurement
    (that is the `pool` profile's interference table in benchmarks/README.md)."""
    d = _decisions(ev)
    assert set(d.filter(pl.col("ok"))["source"]) == {"user", "campaign"}
    assert d.filter(~pl.col("ok") & (pl.col("source") == "user")).height > 0


def test_owners_learn_their_decision(ev):
    paid = pl.concat([ev["referral_bonus_paid"].select("claim_id"),
                      ev["member_bonus_paid"].select("claim_id")])
    granted = ev["bonus_granted"].select("claim_id")
    assert set(paid["claim_id"]) <= set(granted["claim_id"])
    assert paid.height >= 0.95 * granted.height


def test_campaigns_finish_with_their_members(ev):
    fin = ev["campaign_finished"]
    assert fin.height > 0
    orders = ev["member_ordered"].group_by("campaign_id").len()
    j = fin.join(orders, on="campaign_id", how="left").with_columns(pl.col("len").fill_null(0))
    assert j.height == fin.height                  # a campaign with no order is kept, as 0
    assert ((j["paid"].cast(pl.UInt32) + j["denied"].cast(pl.UInt32)) == j["len"]).all()


def test_pool_laws_hold(run):
    laws = json.loads((run.out_dir / "manifest.json").read_text())["laws"]
    for k in ("chk.one_grant_per_claim", "chk.pool_cap", "chk.pool_never_negative"):
        assert laws[k]["violations"] == 0 and laws[k]["checked"] > 0, k
