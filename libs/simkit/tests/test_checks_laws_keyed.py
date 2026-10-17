"""D47: keyed laws carried across steps; open keys at the end are censored, not violations."""

import dataclasses
from itertools import pairwise
from types import SimpleNamespace

import pyarrow as pa
import pytest
from conftest import make_run

from neorisk_simkit.checks.laws import LawBook
from neorisk_simkit.engine import CapExceeded
from neorisk_simkit.engine.errors import LawViolation
from neorisk_simkit.spec import law
from neorisk_simkit.spec.plan import CheckDef

TS = pa.timestamp("us", tz="UTC")
S = 1_000_000


def _plan(*checks):
    run = make_run("ledger")
    return dataclasses.replace(run.plan, checks=tuple(CheckDef(i, lw, req)
                                                      for i, lw, req in checks))


def _table(rows):
    n = len(rows)
    cols = {"event_id": pa.array(range(1, n + 1), pa.int64()),
            "event_type": pa.array(["x"] * n, pa.string()),
            "event_time": pa.array([r["t"] for r in rows], pa.int64()).cast(TS),
            "lamport": pa.array([r.get("lamport", 1) for r in rows], pa.int64()),
            "partition_id": pa.array([r.get("pid", 1) for r in rows], pa.int64()),
            "seq": pa.array([r.get("seq", i) for i, r in enumerate(rows)], pa.int32()),
            "cause_id": pa.nulls(n, pa.int64()),
            "action_id": pa.array([0] * n, pa.int16())}
    for k in ("acct_id", "amount"):
        cols[k] = pa.array([r[k] for r in rows], pa.int64())
    return pa.table(cols)


def _sealed(t0, t1, opened=None, entry=None):
    """`opened` is an event of the ledger fixture, `entry` its posting table."""
    return SimpleNamespace(step=0, t_start=t0, t_end=t1, exported=True,
                           events={} if opened is None else {"opened": opened},
                           postings={} if entry is None else {"entry": entry},
                           history={}, entities={}, stats={}, warmup_rows={})


def _warm(t0, t1, opened=None, entry=None):
    """A warm-up step (F-01): the law tables' rows ride in `warmup_rows`."""
    rows = {k: v for k, v in (("opened", opened), ("entry", entry)) if v is not None}
    return SimpleNamespace(step=0, t_start=t0, t_end=t1, exported=False, events={},
                           postings={}, history={}, entities={}, stats={}, warmup_rows=rows)


def _book(*checks):
    return LawBook(_plan(*checks), max_keys=100)


LE = ("chk.le", law.sum_le("opened.amount", "entry.amount", by="acct_id"), True)


def test_sum_le_runs_per_key_in_canonical_order():
    book = _book(LE)
    book.step(_sealed(0, 10, opened=_table([{"t": 2, "acct_id": 2, "amount": 3}]),
                      entry=_table([{"t": 1, "acct_id": 2, "amount": 5}])), None)
    with pytest.raises(LawViolation, match=r"acct_id 2: opened.amount total 7 exceeds "
                                           r"entry.amount total 5"):
        book.step(_sealed(10, 20, opened=_table([{"t": 13, "acct_id": 2, "amount": 4}])), None)


def test_sum_le_lhs_before_rhs_is_a_violation():
    book = _book(LE)
    with pytest.raises(LawViolation, match="acct_id 4: opened.amount total 1 exceeds "
                                           "entry.amount total 0"):
        book.step(_sealed(0, 10, opened=_table([{"t": 1, "acct_id": 4, "amount": 1}]),
                          entry=_table([{"t": 2, "acct_id": 4, "amount": 9}])), None)


def test_sum_le_carries_sums_across_steps():
    book = _book(LE)
    book.step(_sealed(0, 10, opened=_table([{"t": 2, "acct_id": 5, "amount": 3}]),
                      entry=_table([{"t": 1, "acct_id": 5, "amount": 10}])), None)
    book.step(_sealed(10, 20, opened=_table([{"t": 11, "acct_id": 5, "amount": 6}])), None)
    with pytest.raises(LawViolation, match="acct_id 5: opened.amount total 11 exceeds "
                                           "entry.amount total 10"):
        book.step(_sealed(20, 30, opened=_table([{"t": 21, "acct_id": 5, "amount": 2}])), None)


def test_sum_le_counts_the_right_side_seen_in_warmup():
    """F-01: a capture in warm-up and its refund after `start` (here: an opening in warm-up and
    a matching posting after `start`) pass; without the warm-up sums the posting would exceed 0."""
    book = _book(("chk.le2", law.sum_le("entry.amount", "opened.amount", by="acct_id"), True))
    book.step(_warm(0, 10, opened=_table([{"t": 1, "acct_id": 3, "amount": 5}])), None,
              exported=False)
    assert book.step(_sealed(10, 20, entry=_table([{"t": 11, "acct_id": 3, "amount": 5}])),
                     None) == {"chk.le2": 1}
    with pytest.raises(LawViolation, match="acct_id 3: entry.amount total 6 exceeds "
                                           "opened.amount total 5"):
        book.step(_sealed(20, 30, entry=_table([{"t": 21, "acct_id": 3, "amount": 1}])), None)


def test_a_close_of_a_warmup_opening_is_matched_not_judged():
    book = _book(RES)
    book.step(_warm(0, 10 * S, opened=_table([{"t": 1 * S, "acct_id": 9, "amount": 0},
                                              {"t": 8 * S, "acct_id": 8, "amount": 0}])),
              None, exported=False)          # key 9 misses its 6 s deadline in warm-up: dropped
    book.step(_sealed(10 * S, 20 * S, entry=_table([{"t": 12 * S, "acct_id": 8, "amount": 0}])),
              None)                          # key 8 (deadline 13 s) closes after `start`
    book.finish(20 * S)
    r = book.report()["chk.res"]
    assert (r["violations"], r["censored"], r["unmatched"], r["checked"]) == (0, 0, 0, 0)


RES = ("chk.res", law.resolved("opened", by=("entry",), key="acct_id", within="5s"), True)


def test_resolved_within_a_deadline():
    book = _book(RES)
    book.step(_sealed(0, 10 * S, opened=_table([{"t": 1 * S, "acct_id": 1, "amount": 0},
                                                {"t": 8 * S, "acct_id": 2, "amount": 0}]),
                      entry=_table([{"t": 3 * S, "acct_id": 1, "amount": 0}])), None)
    # key 2's deadline (13 s) lies after this step's end (10 s): not judged yet
    assert book.report()["chk.res"]["violations"] == 0
    with pytest.raises(LawViolation, match=r"acct_id 2 opened at 8000000 not resolved "
                                           r"within 5s"):
        book.step(_sealed(10 * S, 20 * S), None)          # 13 s < 20 s and still open


def test_a_close_before_the_deadline_resolves():
    book = _book(RES)
    book.step(_sealed(0, 10 * S, opened=_table([{"t": 8 * S, "acct_id": 6, "amount": 0}])),
              None)
    book.step(_sealed(10 * S, 20 * S, entry=_table([{"t": 12 * S, "acct_id": 6, "amount": 0}])),
              None)
    book.finish(20 * S)
    r = book.report()["chk.res"]
    assert (r["violations"], r["censored"], r["checked"]) == (0, 0, 1)


def test_open_keys_at_the_end_are_censored():
    book = _book(RES)
    book.step(_sealed(0, 10 * S, opened=_table([{"t": 8 * S, "acct_id": 7, "amount": 0}]),
                      entry=_table([{"t": 9 * S, "acct_id": 99, "amount": 0}])), None)
    book.finish(10 * S)                          # deadline 13 s >= end: censored
    r = book.report()["chk.res"]
    assert (r["violations"], r["censored"], r["unmatched"]) == (0, 1, 1)


def test_resolved_without_deadline_censors_at_the_end():
    book = _book(("chk.res", law.resolved("opened", by=("entry",), key="acct_id"), True))
    book.step(_sealed(0, 10, opened=_table([{"t": 1, "acct_id": 3, "amount": 0}])), None)
    book.finish(10)
    assert book.report()["chk.res"]["censored"] == 1


def _table_nullable(rows):
    """`_table` whose `acct_id` may hold None."""
    t = _table([{**r, "acct_id": r["acct_id"] or 0} for r in rows])
    keys = pa.array([r["acct_id"] for r in rows], pa.int64())
    return t.set_column(t.schema.get_field_index("acct_id"), "acct_id", keys)


def test_null_keys_are_skipped():
    book = _book(LE, RES)
    out = book.step(_sealed(0, 10 * S,
                            opened=_table_nullable([{"t": 1, "acct_id": None, "amount": 9}]),
                            entry=_table_nullable([{"t": 2, "acct_id": None, "amount": 0}])),
                    None)
    book.finish(10 * S)
    assert out == {"chk.le": 0, "chk.res": 0} and book.keys == 0
    assert book.report()["chk.res"]["unmatched"] == 0


def _late_report(cuts):
    """A non-required `resolved` fed the same rows split into steps at `cuts`."""
    book = _book(("chk.res", law.resolved("opened", by=("entry",), key="acct_id",
                                          within="5s"), False))
    opened = [{"t": 1 * S, "acct_id": 1, "amount": 0}, {"t": 2 * S, "acct_id": 2, "amount": 0},
              {"t": 3 * S, "acct_id": 3, "amount": 0}, {"t": 17 * S, "acct_id": 4, "amount": 0}]
    entry = [{"t": 4 * S, "acct_id": 1, "amount": 0}, {"t": 9 * S, "acct_id": 2, "amount": 0},
             {"t": 9 * S, "acct_id": 2, "amount": 0}]
    bounds = [0, *cuts, 20 * S]
    for t0, t1 in pairwise(bounds):
        o = [r for r in opened if t0 <= r["t"] < t1]
        e = [r for r in entry if t0 <= r["t"] < t1]
        book.step(_sealed(t0, t1, opened=_table(o) if o else None,
                          entry=_table(e) if e else None), None)
    book.finish(20 * S)
    return book.report()["chk.res"]


def test_late_and_expired_keys_are_counted_alike_for_any_step_length():
    """Key 1 resolves; key 2 is closed too late (9 s > 7 s), so both its closes are unmatched;
    key 3 expires unclosed; key 4 (deadline 22 s) is censored."""
    reports = [_late_report(c) for c in ([], [5 * S], [3 * S, 8 * S, 15 * S])]
    for r in reports:
        assert (r["checked"], r["violations"], r["censored"], r["unmatched"]) == (3, 2, 1, 2)
        assert r["first"]["detail"] == "acct_id 2 opened at 2000000 not resolved within 5s"
    assert reports[0] == reports[1] == reports[2]


def test_carried_keys_are_capped():
    book = LawBook(_plan(LE), max_keys=2)
    with pytest.raises(CapExceeded, match="checker_state"):
        book.step(_sealed(0, 10, entry=_table([{"t": 1, "acct_id": a, "amount": 1}
                                               for a in (1, 2, 3)])), None)
