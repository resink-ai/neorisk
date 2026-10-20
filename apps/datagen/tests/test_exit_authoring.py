"""Exit: a payments variant (payments_subscriptions, as state machines) and a new overlay
(card_testing on payments), written from a brief with the public API only; both validate,
their laws and expectations hold, and the overlay obeys the regression rule."""

import dataclasses
import json
import shutil
from pathlib import Path

import polars as pl

from datagen.cli import main
from neorisk_simkit.checks import failed, run_checks
from neorisk_simkit.checks.interference import compare_outputs
from neorisk_simkit.engine import simulate
from neorisk_simkit.project import load_project
from neorisk_simkit.spec import validate

EX = Path(__file__).resolve().parents[3] / "examples"


def test_subscriptions_variant_end_to_end(tmp_path):
    proj = tmp_path / "subs"
    shutil.copytree(EX / "payments_subscriptions", proj,
                    ignore=shutil.ignore_patterns("out", "reports", "__pycache__"))
    assert main(["validate", str(proj)]) == 0
    assert main(["run", str(proj)]) == 0
    assert main(["check", str(proj / "out" / "default-s7")]) == 0
    rep = json.loads((proj / "reports" / "default-s7" / "checks.json").read_text())
    assert {r["name"] for r in rep["results"] if r["group"] == "stat"} >= {
        "exp.trial_conversion", "exp.first_attempt_declines"}


def test_subscription_paths_and_debug_identity():
    pr = load_project(EX / "payments_subscriptions")
    s = pr.settings("sample", ["card_health_alpha=3.0"])        # sick cards: force dunning
    plan = pr.plan()
    out = simulate(plan, s.config, s.run)
    dbg = simulate(pr.plan(), s.config, dataclasses.replace(s.run, debug=True))
    assert all(out.events[k].equals(dbg.events[k]) for k in out.events)
    assert failed(run_checks(out, plan.checks)) == []
    reasons = set(out.events["subscription_cancelled"]["reason"])
    assert reasons == {"trial_cancel", "voluntary", "involuntary"}
    assert (out.events["invoice_paid"]["attempt"] > 1).any()        # dunning recovers some


def test_card_testing_overlay():
    pr = load_project(EX / "payments")
    s0 = pr.settings(None, ["customers=300", "run.days=40"], [])
    s1 = pr.settings(None, ["customers=300", "run.days=40"], ["card_testing"])
    plan = pr.plan(s1.overlays)
    assert validate(plan) == [] and pr.lint() == []
    base = simulate(pr.plan({}), s0.config, s0.run)
    over = simulate(plan, s1.config, s1.run)
    assert failed(run_checks(over, plan.checks)) == []
    reg, inter = compare_outputs(base, over)
    assert reg.status == "pass", reg.as_dict()
    assert "issuer" in inter.metric["shared"]
    testers = over.labels.filter(pl.col("role") == "card_tester")["target_id"]
    fraud = over.labels.filter(pl.col("role") == "fraud")
    assert set(fraud["target_table"]) == {"payments"}       # ids collide across tables
    assert testers.len() == 6 and (testers >= 1_000_000_000).all()
    auth = over.events["payment_authorized"].filter(pl.col("customer_id").is_in(testers.implode()))
    small = auth.filter(pl.col("amount") < 300)
    big = auth.filter(pl.col("amount") >= 90_000)
    assert small.height > 100 and big.height > 0
    assert set(big["card_id"]) <= set(small["card_id"])            # only cards that passed
    dec = over.events["payment_declined"].filter(pl.col("customer_id").is_in(testers.implode()))
    assert dec.height / (dec.height + auth.height) > 0.05          # stolen cards decline more
