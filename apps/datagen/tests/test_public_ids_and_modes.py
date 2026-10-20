"""Optional public ids at export, and the population run mode."""

import dataclasses
import shutil
from pathlib import Path

import numpy as np
import polars as pl

from datagen.cli import main
from neorisk_simkit.checks import failed, run_checks
from neorisk_simkit.engine import simulate
from neorisk_simkit.io import read
from neorisk_simkit.io.public_ids import feistel
from neorisk_simkit.project import load_project

EX = Path(__file__).resolve().parents[3] / "examples"


def test_feistel_is_a_bijection():
    x = np.arange(0, 200_000, dtype=np.int64)
    y = feistel(x, "users", 7)
    assert len(np.unique(y)) == len(x) and (y >= 0).all() and (y < 2**62).all()
    assert (feistel(x, "users", 7) == y).all() and not (feistel(x, "orders", 7) == y).all()


def test_public_ids_export_keeps_every_reference(tmp_path):
    proj = tmp_path / "ecommerce"
    shutil.copytree(EX / "ecommerce", proj, ignore=shutil.ignore_patterns("out", "reports"))
    assert main(["run", str(proj), "--overlay", "bounty_hunters", "--set", "users=300",
                 "--set", "run.days=10", "--out", str(tmp_path / "run")]) == 0
    assert main(["export", str(tmp_path / "run"), "--public-ids", "--out",
                 str(tmp_path / "pub")]) == 0
    a, b = read(tmp_path / "run"), read(tmp_path / "pub")
    assert not a.entities["users"]["user_id"].equals(b.entities["users"]["user_id"])
    assert b.entities["users"]["user_id"].min() > 2**40          # looks random
    res = run_checks(b, [], structural=True)
    assert failed(res) == [], [r.as_dict() for r in failed(res)]
    assert a.events["order_placed"]["seq"].equals(b.events["order_placed"]["seq"])
    users = set(b.entities["users"]["user_id"])
    assert set(b.labels["target_id"]) <= users


def test_population_mode_runs_cases_out_without_a_horizon():
    pr = load_project(EX / "payments_subscriptions")
    s = pr.settings("sample", ["subscribers=60", "renewal_churn_p=0.5"])
    run = dataclasses.replace(s.run, mode="population", days=30, max_case_steps=200)
    out = simulate(pr.plan(), s.config, run)
    subs = out.cases.filter(pl.col("kind") == "subscriber")
    # every subscription reaches its natural end: cancelled or still paying at the step cap
    ended = out.events["subscription_cancelled"]["subscriber_id"].n_unique()
    assert ended + subs["censored"].sum() >= subs.height
    from datetime import UTC, datetime
    assert out.events["invoice_paid"]["event_time"].max() > datetime(2026, 2, 15, tzinfo=UTC)
