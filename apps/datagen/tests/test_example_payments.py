"""The payments pack: laws hold on ordinary and forced-path runs; mutations are caught."""

from dataclasses import replace
from pathlib import Path

import polars as pl
import pytest

from neorisk_simkit.checks import Data, failed, run_check, run_checks
from neorisk_simkit.checks.reference import holds_ledger
from neorisk_simkit.engine import simulate
from neorisk_simkit.project import load_project
from neorisk_simkit.spec import validate

PAY = Path(__file__).resolve().parents[3] / "examples" / "payments"


def _run(*sets, customers=300, days=60):
    pr = load_project(PAY)
    s = pr.settings(None, [f"customers={customers}", f"run.days={days}", *sets])
    plan = pr.plan()
    assert validate(plan) == [] and pr.lint() == []
    out = simulate(plan, s.config, s.run)
    res = run_checks(out, plan.checks)
    assert failed(res) == [], [r.as_dict() for r in failed(res)]
    assert holds_ledger(Data.of(out)) == []
    return plan, out


@pytest.fixture(scope="module")
def base():
    return _run()


def test_ordinary_run_has_every_path(base):
    _, out = base
    for e in ("payment_authorized", "payment_captured", "payment_expired", "capture_replayed",
              "refund_issued", "payment_declined", "settlement_posted", "hold_released"):
        assert out.events[e].height > 0, e


def test_forced_disputes_refuse_refunds_while_open():
    _, out = _run("dispute_p=1.0", "refund_p=0.3", "dispute_mean_days=2.0",
                  "resolve_mean_days=20.0", customers=120)
    refused = out.events["refund_refused"]
    assert (refused["reason"] == "dispute_open").sum() > 0
    assert out.events["dispute_resolved"].filter(pl.col("outcome") == "lost").height > 0


def test_forced_capture_retries_replay_the_first_result():
    _, out = _run("capture_retry_p=1.0", customers=120)
    cap, rep = out.events["payment_captured"], out.events["capture_replayed"]
    assert rep.height > 0.9 * cap.height
    assert set(rep["idempotency_key"]) <= set(cap["idempotency_key"])


def test_forced_paths_expiry_declines_and_over_limit():
    _, out = _run("capture_p=0.0", customers=100)
    assert out.events["payment_captured"].height == 0
    assert out.events["payment_expired"].height > 0
    _, out = _run("risk_decline_p=1.0", customers=100)
    assert out.events["payment_authorized"].height == 0
    _, out = _run("limit_median_cents=3000", customers=100)
    assert (out.events["payment_declined"]["reason"] == "over_limit").sum() > 0


def _mut(d, table, fn):
    ev = dict(d.events)
    ev[table] = fn(ev[table])
    return replace(d, events=ev)


def _law(plan, name):
    return next(c.fn for c in plan.checks if c.name == name)


def test_mutations_are_caught(base):
    plan, out = base
    d = Data.of(out)
    cases = {
        "refunds_le_captured": ("refund_issued", lambda df: df.with_columns(
            amount=pl.col("amount") * 100)),
        "one_capture_per_payment": ("payment_captured", lambda df: pl.concat(
            [df, df.head(1).with_columns(seq=pl.col("seq") + 10**9)])),
        "credit_limit_respected": ("hold_placed", lambda df: df.with_columns(
            amount=pl.col("amount") * 1000)),
        "settlement_arithmetic": ("settlement_posted", lambda df: df.with_columns(
            net=pl.col("net") + 1)),
        "payment_lifecycle": ("payment_expired", lambda df: df.with_columns(
            seq=pl.col("seq") - pl.col("seq") + 1)),
        "holds_resolved": ("hold_committed", lambda df: df.head(0)),
    }
    for name, (table, fn) in cases.items():
        r = run_check(_mut(d, table, fn), name, _law(plan, name))
        assert r.status == "fail", name
    assert holds_ledger(_mut(d, "hold_committed",
                             lambda df: df.with_columns(amount=pl.col("amount") + 1)))
