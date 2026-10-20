"""§08 regression rule, both ways, and the interference report; label outcomes."""

from pathlib import Path

import polars as pl
import pytest

from neorisk_simkit.checks import failed, run_checks
from neorisk_simkit.checks.interference import compare_outputs
from neorisk_simkit.engine import simulate
from neorisk_simkit.project import load_project

ECOM = Path(__file__).resolve().parents[3] / "examples" / "ecommerce"
SETS = ["users=500", "run.days=30"]


def _pair(overlay, *sets):
    pr = load_project(ECOM)
    s0 = pr.settings(None, [*SETS, *(x for x in sets if not x.startswith(overlay))], [])
    s1 = pr.settings(None, [*SETS, *sets], [overlay])
    base = simulate(pr.plan({}), s0.config, s0.run)
    plan = pr.plan(s1.overlays)
    over = simulate(plan, s1.config, s1.run)
    return base, over, plan


def test_an_overlay_sharing_nothing_leaves_every_base_row_identical():
    base, over, plan = _pair("window_shoppers")
    assert over.stats.contacts == {}
    reg, inter = compare_outputs(base, over)
    assert reg.status == "pass" and reg.checked > 1000, reg.as_dict()
    assert inter.detail == "no shared state"
    assert all(v["only_with_overlay"] == 0 for v in inter.metric["by_event"].values())
    assert over.events["session_started"].height > base.events["session_started"].height
    assert failed(run_checks(over, plan.checks)) == []


def test_an_overlay_sharing_the_pool_keeps_arrivals_and_shows_interference():
    base, over, plan = _pair("bounty_hunters", "monthly_budget_cents=60000",
                             "bounty_hunters.share=0.01")
    assert {k for _, k in over.stats.contacts} >= {"referral_pool", "inventory"}
    reg, inter = compare_outputs(base, over)
    assert reg.status == "pass", reg.as_dict()
    assert inter.metric["shared"] == ["inventory", "referral_pool"]
    rej = inter.metric["by_event"]["referral_bonus_rejected"]
    assert rej["only_with_overlay"] > 0          # base claims rejected: hunters drained the pool
    assert failed(run_checks(over, plan.checks)) == []


def test_a_base_change_breaks_the_rule():
    base, over, _ = _pair("window_shoppers")
    over.events["user_signed_up"] = over.events["user_signed_up"].with_columns(
        acquisition=pl.lit("ads").cast(over.events["user_signed_up"]["acquisition"].dtype))
    reg, _ = compare_outputs(base, over)
    assert reg.status == "fail" and reg.cited


def test_zombie_label_outcomes_progress():
    _, over, _ = _pair("bounty_hunters", "bounty_hunters.share=0.01")
    lab = over.labels
    z = lab.filter(pl.col("role") == "zombie")
    assert set(z["outcome"]) <= {"attempted", "qualified", "paid", "rejected"}
    assert (z["outcome"] == "paid").sum() > 0
    assert (lab["label_available_at"] > lab["labeled_at"]).all()
    assert lab["target_id"].min() > 1_000_000_000            # overlay namespace ids


@pytest.mark.parametrize("overlay", ["bounty_hunters", "window_shoppers"])
def test_datagen_check_runs_the_rule(tmp_path, overlay):
    import json
    import shutil

    from datagen.cli import main
    proj = tmp_path / "ecommerce"
    shutil.copytree(ECOM, proj, ignore=shutil.ignore_patterns("out", "reports", "__pycache__"))
    assert main(["run", str(proj), "--overlay", overlay, "--set", "users=300",
                 "--set", "run.days=15"]) == 0
    run = proj / "out" / f"default-s7+{overlay}"
    assert main(["check", str(run), "--skip-stats"]) == 0
    rep = json.loads((proj / "reports" / run.name / "checks.json").read_text())
    names = {r["name"]: r for r in rep["results"]}
    assert names["overlay.regression"]["status"] == "pass"
    assert "overlay.interference" in names
