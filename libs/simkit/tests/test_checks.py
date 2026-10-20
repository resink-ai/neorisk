"""Checks: structural and law checks pass on real output and catch mutated output."""

from dataclasses import replace
from pathlib import Path

import polars as pl
import pytest

from neorisk_simkit.checks import Data, failed, laws, run_check, run_checks
from neorisk_simkit.engine import simulate
from neorisk_simkit.io import read, write
from neorisk_simkit.project import load_project

ECOM = Path(__file__).resolve().parents[3] / "examples" / "ecommerce"


@pytest.fixture(scope="module")
def run():
    pr = load_project(ECOM)
    s = pr.settings(None, ["users=600", "run.days=20", "monthly_budget_cents=40000"],
                    ["bounty_hunters"])
    plan = pr.plan(s.overlays)
    return plan, simulate(plan, s.config, s.run)


def _mutate(d: Data, table: str, fn) -> Data:
    ev = dict(d.events)
    ev[table] = fn(ev[table])
    return replace(d, events=ev)


def _check(plan, name):
    return next(c for c in plan.checks if c.name == name)


def test_everything_passes_on_real_output(run, tmp_path):
    plan, out = run
    res = run_checks(out, plan.checks)
    assert {r.name for r in res} >= {"s.types", "s.references", "s.ordering",
                                     "monthly_budget", "reservations_resolved_by_ttl"}
    assert failed(res) == [], [r.as_dict() for r in failed(res)]
    assert all(r.checked > 0 for r in res)
    back = run_checks(read(write(out, tmp_path / "r")), plan.checks)   # same from disk
    assert [(r.name, r.status, r.checked) for r in back] == [
        (r.name, r.status, r.checked) for r in res]


def test_structural_mutations_fail(run):
    _plan, out = run
    d = Data.of(out)
    cases = {
        "s.ordering": _mutate(d, "order_placed", lambda df: df.reverse()),
        "s.unique_ids": _mutate(d, "order_placed",
                                lambda df: pl.concat([df, df.head(1)])),
        "s.references": _mutate(d, "order_placed",
                                lambda df: df.with_columns(sku_id=pl.col("sku_id") + 10**6)),
        "s.types": _mutate(d, "order_placed", lambda df: df.drop("quantity")),
        "s.leakage": _mutate(d, "order_placed", lambda df: df.with_columns(label=1)),
    }
    from neorisk_simkit.checks import structural as st
    for name, md in cases.items():
        r = run_check(md, name, st.CHECKS[name], group="structural")
        assert r.status == "fail", name


def test_law_mutations_fail_and_cite_the_row(run):
    plan, out = run
    d = Data.of(out)
    budget = _mutate(d, "referral_bonus_paid", lambda df: df.with_columns(amount=pl.lit(10**7)))
    r = run_check(budget, "monthly_budget", _check(plan, "monthly_budget").fn)
    assert r.status == "fail" and r.cited[0]["action"] == "referral_pool.claim"
    assert {"partition_id", "seq", "detail"} <= set(r.cited[0])

    stock = _mutate(d, "reservation_granted", lambda df: df.with_columns(qty=pl.lit(1000)))
    assert run_check(stock, "x", _check(plan, "stock_never_negative").fn).status == "fail"

    late = _mutate(d, "reservation_granted", lambda df: df.with_columns(expires_in=pl.lit(0)))
    assert run_check(late, "x", _check(plan, "reservations_resolved_by_ttl").fn).status == "fail"

    first = out.events["order_returned"].height
    assert first > 0
    ret = _mutate(d, "order_returned", lambda df: df.with_columns(amount=pl.col("amount") * 2))
    assert run_check(ret, "x", _check(plan, "returns_le_order").fn).status == "fail"

    twice = _mutate(d, "order_returned", lambda df: pl.concat([df, df.head(1).with_columns(
        seq=pl.col("seq") + 10**9)]).sort("seq"))
    assert run_check(twice, "x", _check(plan, "order_lifecycle").fn).status == "fail"


def test_a_raising_check_is_an_error_not_a_pass(run):
    _plan, out = run
    r = run_check(Data.of(out), "boom", lambda d: 1 / 0)
    assert r.status == "error" and "ZeroDivisionError" in r.detail
    assert failed([r]) == [r]


def test_generic_laws_on_a_small_frame(run):
    _plan, out = run
    d = Data.of(out)
    n, bad = laws.consecutive("session_started", "user_id", "session_id")(d)
    assert n > 0 and bad.height > 0                      # session ids are global, not per user
    n, bad = laws.pairing(("order_placed", "order_id"), ("order_returned", "order_id"))(d)
    assert bad.height > 0                                # most orders are never returned
    n, bad = laws.not_while_open("order_returned", "order_placed", [], "order_id")(d)
    assert bad.height == out.events["order_returned"].height
