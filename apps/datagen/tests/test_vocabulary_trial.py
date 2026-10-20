"""P5 vocabulary trial: an order book, an L1 envelope and a social cascade fit the five
primitives; their laws hold, reference implementations agree, mutations are caught, and
time grows about linearly."""

import dataclasses
import time
from dataclasses import replace
from pathlib import Path

import polars as pl
import pytest

from neorisk_simkit.checks import Data, failed, run_check, run_checks
from neorisk_simkit.checks.reference import l1_envelope, order_book
from neorisk_simkit.engine import simulate
from neorisk_simkit.project import load_project
from neorisk_simkit.spec import validate

EX = Path(__file__).resolve().parents[3] / "examples"


def _run(project, *sets, debug=False):
    pr = load_project(EX / project)
    s = pr.settings("sample", list(sets))
    plan = pr.plan()
    assert validate(plan) == [] and pr.lint() == []
    run = dataclasses.replace(s.run, debug=True) if debug else s.run
    return plan, simulate(plan, s.config, run)


@pytest.fixture(scope="module", params=["crypto_exchange", "layer1", "social"])
def pack(request):
    plan, out = _run(request.param)
    return request.param, plan, out


def test_laws_hold(pack):
    _name, plan, out = pack
    res = run_checks(out, plan.checks)
    assert failed(res) == [], [r.as_dict() for r in failed(res)]
    assert sum(df.height for df in out.events.values()) > 5000


def test_debug_mode_changes_nothing(pack):
    name, _plan, out = pack
    _, dbg = _run(name, debug=True)
    assert all(out.events[k].equals(dbg.events[k]) for k in out.events)


def _mut(out, table, fn):
    d = Data.of(out)
    ev = dict(d.events)
    ev[table] = fn(ev[table])
    return replace(d, events=ev)


def test_order_book_matches_the_reference_and_catches_a_wrong_trade():
    _, out = _run("crypto_exchange")
    d = Data.of(out)
    assert d.ev("trade").height > 500
    assert order_book(d, "BTC-USD") == [] and order_book(d, "ETH-USD") == []
    shifted = _mut(out, "trade", lambda df: df.with_columns(
        price=pl.when(pl.col("trade_id") == df["trade_id"][10]).then(pl.col("price") + 1)
        .otherwise(pl.col("price"))))
    sym = out.events["trade"]["symbol"][10]
    assert order_book(shifted, sym)
    kinds = set(out.events["order_accepted"]["type"])
    assert kinds == {"gtc", "ioc", "fok"}
    assert (out.events["order_rejected"]["reason"] == "fok_unfillable").any()
    assert (out.events["order_cancelled"]["reason"] == "user").any()


def test_l1_matches_the_reference_envelope_and_catches_a_wrong_fee():
    plan, out = _run("layer1")
    d = Data.of(out)
    assert l1_envelope(d, 20) == []
    inc = out.events["tx_included"]
    assert set(inc["status"]) == {"success", "reverted"}
    assert set(out.events["tx_dropped"]["reason"]) >= {"bad_nonce"}
    bad = _mut(out, "tx_included", lambda df: df.with_columns(fee=pl.col("fee") + 1))
    assert l1_envelope(bad, 20)
    logged = _mut(out, "transfer_log", lambda df: pl.concat([df, df.head(1).with_columns(
        tx_id=pl.lit(inc.filter(pl.col("status") == "reverted")["tx_id"][0], pl.Int64))]))
    law = next(c.fn for c in plan.checks if c.name == "reverts_have_no_logs")
    assert run_check(logged, "x", law).status == "fail"


def test_cascades_respect_the_graph_and_dedup():
    plan, out = _run("social")
    rep = out.events["post_reposted"]
    assert rep["depth"].max() >= 3                     # cascades go several levels deep
    assert out.stats.rejections[("cascade", "view", "already_seen")] > 0
    law = next(c.fn for c in plan.checks if c.name == "viewers_follow_who_exposed_them")
    bad = _mut(out, "post_viewed", lambda df: df.with_columns(
        user_id=pl.when(pl.int_range(pl.len()) == 0).then(pl.col("user_id").max() + 0)
        .otherwise(pl.col("user_id"))).with_columns(
        via_post=pl.when(pl.int_range(pl.len()) == 0).then(-1).otherwise(pl.col("via_post"))))
    assert run_check(bad, "x", law).status == "fail"


def _cost(project, key, n):
    t = time.perf_counter()
    _, out = _run(project, f"{key}={n}")
    return time.perf_counter() - t, sum(df.height for df in out.events.values())


@pytest.mark.parametrize(("project", "key", "n"), [("layer1", "wallets", 50),
                                                   ("social", "users", 200)])
def test_time_scales_about_linearly(project, key, n):
    _cost(project, key, n)
    t1, r1 = _cost(project, key, n)
    t4, r4 = _cost(project, key, 4 * n)
    # rows can grow faster than users (a bigger graph has more popular accounts, so cascades
    # reach further); the requirement is on the algorithm: time per event must not grow
    assert r4 / r1 > 3.0
    assert (t4 / r4) / (t1 / r1) < 1.5
