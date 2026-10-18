"""D47: laws evaluated on sealed steps in canonical order; failures cite (partition_id, seq)
and action ID."""

import dataclasses
import json
from types import SimpleNamespace

import pyarrow as pa
import pytest
from conftest import FIXTURES, make_run

from neorisk_simkit.checks.laws import LawBook, resolve_path
from neorisk_simkit.engine import CapExceeded
from neorisk_simkit.engine.errors import LawViolation
from neorisk_simkit.engine.world import World
from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.spec import law
from neorisk_simkit.spec.plan import CheckDef

TS = pa.timestamp("us", tz="UTC")


def _plan(*checks):
    run = make_run("ledger")
    return dataclasses.replace(run.plan, checks=tuple(CheckDef(i, lw, req)
                                                      for i, lw, req in checks))


def _table(rows, cats=()):
    """Rows as an event/posting table: common columns first, then the given ones."""
    n = len(rows)
    cols = {"event_id": pa.array(range(1, n + 1), pa.int64()),
            "event_type": pa.array(["x"] * n, pa.string()),
            "event_time": pa.array([r["t"] for r in rows], pa.int64()).cast(TS),
            "lamport": pa.array([r.get("lamport", i + 1) for i, r in enumerate(rows)], pa.int64()),
            "partition_id": pa.array([r.get("pid", 1) for r in rows], pa.int64()),
            "seq": pa.array([r.get("seq", i) for i, r in enumerate(rows)], pa.int32()),
            "cause_id": pa.nulls(n, pa.int64()),
            "action_id": pa.array([r.get("action", 0) for r in rows], pa.int16())}
    for k in rows[0]:
        if k in ("t", "lamport", "pid", "seq", "action"):
            continue
        if k in cats:
            cols[k] = pa.array([r[k] for r in rows], pa.string()).dictionary_encode()
        else:
            cols[k] = pa.array([r[k] for r in rows], pa.int64())
    return pa.table(cols)


def _sealed(t0, t1, events=None, postings=None):
    return SimpleNamespace(step=0, t_start=t0, t_end=t1, exported=True,
                           events=events or {}, postings=postings or {}, history={},
                           entities={}, stats={}, warmup_rows={})


def _warm(t0, t1, rows):
    """A warm-up step: nothing exported; the law tables' rows ride in `warmup_rows` (F-01)."""
    return SimpleNamespace(step=0, t_start=t0, t_end=t1, exported=False, events={},
                           postings={}, history={}, entities={}, stats={}, warmup_rows=rows)


def test_paths_resolve():
    plan = make_run("ledger").plan
    assert resolve_path(plan, "opened.amount") == ("event", "opened", "amount")
    assert resolve_path(plan, "entry.amount") == ("event", "entry", "amount")
    assert resolve_path(plan, "acct.bal") == ("owner", "acct", "bal")
    with pytest.raises(ValueError, match="unknown path 'acct.nope'"):
        resolve_path(plan, "acct.nope")


def test_never_negative_cites_the_row():
    book = LawBook(_plan(("chk.pos", law.never_negative("opened.amount"), True)), max_keys=10)
    ok = _table([{"t": 1, "acct_id": 1, "amount": 5}])
    assert book.step(_sealed(0, 10, {"opened": ok}), None) == {"chk.pos": 1}
    bad = _table([{"t": 11, "acct_id": 1, "amount": 5},
                  {"t": 12, "acct_id": 2, "amount": -3, "pid": 7, "seq": 3, "action": 0}])
    with pytest.raises(LawViolation, match=r"law chk.pos violated in opened at "
                                           r"\(partition_id 7, seq 3\), action 0: amount = -3"):
        book.step(_sealed(10, 20, {"opened": bad}), None)


def test_non_required_violations_are_counted():
    book = LawBook(_plan(("chk.soft", law.never_negative("opened.amount"), False)), max_keys=10)
    t = _table([{"t": 1, "acct_id": 1, "amount": -1}, {"t": 2, "acct_id": 2, "amount": -2}])
    book.step(_sealed(0, 10, {"opened": t}), None)
    r = book.report()["chk.soft"]
    assert (r["checked"], r["violations"], r["required"]) == (2, 2, False)
    assert r["first"]["detail"] == "amount = -1"


def test_total_le_carries_across_steps():
    book = LawBook(_plan(("chk.cap", law.total_le("opened.amount", 10), True)), max_keys=10)
    book.step(_sealed(0, 10, {"opened": _table([{"t": 1, "acct_id": 1, "amount": 6}])}), None)
    with pytest.raises(LawViolation, match="total 11 exceeds 10"):
        book.step(_sealed(10, 20, {"opened": _table([{"t": 11, "acct_id": 1, "amount": 5}])}),
                  None)


def test_at_most_once_within_and_across_steps():
    book = LawBook(_plan(("chk.once", law.at_most_once("opened", key="acct_id"), True)),
                   max_keys=10)
    book.step(_sealed(0, 10, {"opened": _table([{"t": 1, "acct_id": 4, "amount": 1},
                                                {"t": 2, "acct_id": 5, "amount": 1}])}), None)
    assert book.keys == 2
    with pytest.raises(LawViolation, match="acct_id 4 seen before"):
        book.step(_sealed(10, 20, {"opened": _table([{"t": 11, "acct_id": 4, "amount": 1}])}),
                  None)


def test_warmup_rows_build_state_without_judging():
    """F-01 (§11: reducers start from the opening snapshot): warm-up rows feed running totals
    and key sets but are never counted, cited or judged."""
    book = LawBook(_plan(("chk.cap", law.total_le("opened.amount", 10), True),
                         ("chk.once", law.at_most_once("opened", key="acct_id"), True)),
                   max_keys=10)
    warm = _table([{"t": 1, "acct_id": 4, "amount": 6}, {"t": 2, "acct_id": 4, "amount": 1}])
    assert book.step(_warm(0, 10, {"opened": warm}), None, exported=False) == \
        {"chk.cap": 0, "chk.once": 0}               # the warm-up duplicate of 4 is not judged
    assert book.report()["chk.cap"]["checked"] == book.report()["chk.once"]["checked"] == 0
    with pytest.raises(LawViolation, match="total 11 exceeds 10"):   # 7 from warm-up + 4
        book.step(_sealed(10, 20, {"opened": _table([{"t": 11, "acct_id": 5, "amount": 4}])}),
                  None)


def test_a_key_seen_in_warmup_is_seen_before():
    book = LawBook(_plan(("chk.once", law.at_most_once("opened", key="acct_id"), True)),
                   max_keys=10)
    book.step(_warm(0, 10, {"opened": _table([{"t": 1, "acct_id": 4, "amount": 1}])}), None,
              exported=False)
    with pytest.raises(LawViolation, match="acct_id 4 seen before"):
        book.step(_sealed(10, 20, {"opened": _table([{"t": 11, "acct_id": 4, "amount": 1}])}),
                  None)


def test_balanced_postings_per_commit():
    book = LawBook(_plan(("chk.bal", law.balanced("entry"), True)), max_keys=10)
    good = _table([{"t": 1, "lamport": 3, "pid": 9, "acct_id": 1, "account": "cash",
                    "side": "debit", "amount": 7},
                   {"t": 1, "lamport": 3, "pid": 9, "acct_id": 1, "account": "revenue",
                    "side": "credit", "amount": 7}], cats=("account", "side"))
    assert book.step(_sealed(0, 10, postings={"entry": good}), None) == {"chk.bal": 2}
    bad = _table([{"t": 11, "lamport": 4, "pid": 9, "seq": 5, "acct_id": 1, "account": "cash",
                   "side": "debit", "amount": 7}], cats=("account", "side"))
    with pytest.raises(LawViolation, match=r"\(partition_id 9, seq 5\).*debits 7 != credits 0"):
        book.step(_sealed(10, 20, postings={"entry": bad}), None)


def test_state_law_checks_live_owners():
    run = make_run("ledger")
    run = dataclasses.replace(run, plan=_plan(("chk.bal", law.never_negative("acct.bal"), True)))
    w = World.build(run, threads=1)
    g = w.admit_population(run.start_us - run.warmup_us, run.start_us)
    book = LawBook(run.plan, max_keys=10)
    assert book.step(_sealed(0, 10), w)["chk.bal"] == len(g)
    w.state["acct"][0][w.hidden.lslot[g[0]]] = -4
    with pytest.raises(LawViolation, match=r"in state acct.bal at \(partition_id \d+, seq -1\)"):
        book.step(_sealed(10, 20), w)


def test_checker_keys_are_capped():
    book = LawBook(_plan(("chk.once", law.at_most_once("opened", key="acct_id"), True)),
                   max_keys=1)
    with pytest.raises(CapExceeded, match="checker_state"):
        book.step(_sealed(0, 10, {"opened": _table([{"t": 1, "acct_id": 4, "amount": 1},
                                                    {"t": 2, "acct_id": 5, "amount": 1}])}),
                  None)


def test_a_run_reports_its_laws(tmp_path):
    r = run_to_dataset(FIXTURES / "ledger", "sample", out_dir=tmp_path / "ok", threads=1)
    laws = json.loads((r.out_dir / "manifest.json").read_text())["laws"]
    assert set(laws) == {"chk.opened_positive", "chk.entries_balance", "chk.bal_positive"}
    assert all(v["violations"] == 0 and v["checked"] > 0 for v in laws.values())
    stats = json.loads((r.out_dir / "run_stats.json").read_text())
    assert "check" in stats["stage_seconds"]


def test_a_required_violation_fails_the_run(tmp_path):
    out = tmp_path / "bad"
    with pytest.raises(LawViolation, match="chk.opened_positive"):
        run_to_dataset(FIXTURES / "ledger", "sample", ["bad=1"], out_dir=out, threads=1)
    assert not out.exists() and not out.with_suffix(".partial").exists()


def test_an_empty_run_checks_nothing(tmp_path):
    """Review Focus #5: the single account opens in warm-up (Task 7's `accts=1` run): the row
    laws pass vacuously with `checked = 0`, even though `bad=1` makes the warm-up row negative
    (warm-up rows are never judged, F-01)."""
    r = run_to_dataset(FIXTURES / "ledger", "sample", ["accts=1", "bad=1"],
                       out_dir=tmp_path / "empty", threads=1)
    laws = json.loads((r.out_dir / "manifest.json").read_text())["laws"]
    for k in ("chk.opened_positive", "chk.entries_balance"):
        assert (laws[k]["checked"], laws[k]["violations"]) == (0, 0), k


def test_null_keys_are_skipped():
    """Review M5: a row with a null key column has no key; it is neither judged nor kept."""
    book = LawBook(_plan(("chk.once", law.at_most_once("opened", key="acct_id"), True),
                         ("chk.pair", law.at_most_once("opened", key=("acct_id", "amount")),
                          True)), max_keys=10)
    t = _table([{"t": 1, "acct_id": None, "amount": 1}, {"t": 2, "acct_id": None, "amount": 1},
                {"t": 3, "acct_id": 4, "amount": 1}])
    assert book.step(_sealed(0, 10, {"opened": t}), None) == {"chk.once": 1, "chk.pair": 1}
    assert book.keys == 2
    with pytest.raises(LawViolation, match=r"\(partition_id 1, seq 1\).*acct_id 4 seen before"):
        book.step(_sealed(10, 20, {"opened": _table([
            {"t": 11, "acct_id": None, "amount": 1}, {"t": 12, "acct_id": 4, "amount": 1}])}),
            None)


def test_an_owner_retired_in_its_step_is_judged_on_its_final_state():
    """Review M2: every ledger account opens (bal < 0 with `bad=1`) and retires idle in the
    same step, so it is never live at a seal; state laws still judge the slots freed at the
    seal and cite the account's partition_id."""
    from neorisk_simkit.engine.run import Simulation

    run = make_run("ledger", ["bad=1"])
    run = dataclasses.replace(run, plan=dataclasses.replace(run.plan, checks=tuple(
        c for c in run.plan.checks if c.id == "chk.bal_positive")))
    sim = Simulation(run, threads=1)
    opened = []
    for s in sim.steps():
        if s.exported:
            assert not sim.world.hidden.alive[s.retired].any()
            assert s.stats["laws"]["chk.bal_positive"] == len(s.retired)
            opened += s.events["opened"].column("partition_id").to_pylist()
    r = sim.stats["laws"]["chk.bal_positive"]
    assert opened and r["checked"] == r["violations"] == len(opened)
    assert r["first"]["partition_id"] == opened[0] and r["first"]["seq"] == -1
    assert r["first"]["table"] == "state acct.bal" and r["first"]["detail"].startswith("bal = -")


def test_balanced_sums_never_wrap():
    """Codex C2: debits of 2**63 against credits of -2**63 differ, though they wrap equal."""
    book = LawBook(_plan(("chk.bal", law.balanced("entry"), True)), max_keys=10)
    rows = [{"t": 1, "lamport": 3, "pid": 9, "seq": i, "acct_id": 1, "account": "cash",
             "side": side, "amount": a}
            for i, (side, a) in enumerate((("debit", 2**63 - 1), ("debit", 1),
                                           ("credit", -(2**63))))]
    with pytest.raises(LawViolation, match=f"debits {2**63} != credits {-(2**63)}"):
        book.step(_sealed(0, 10, postings={"entry": _table(rows, cats=("account", "side"))}),
                  None)
