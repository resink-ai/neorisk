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


# ---------------------------------------------------------------- final fix: C1, C2, C3, I2
I64_MAX, I64_MIN = 2**63 - 1, -(2**63)
X = 6238072747940578789                    # (0, 0) and (1, X) share the `rng.mix` hash 0


def test_composite_keys_compare_whole_tuples():
    """Codex C1: a hash only indexes composite keys; colliding tuples stay distinct."""
    import numpy as np

    from neorisk_simkit.checks.laws import key_hash

    assert list(key_hash(np.array([[0, 0], [1, X]], np.int64))) == [0, 0]
    book = _book(("chk.once", law.at_most_once("opened", key=("acct_id", "amount")), False))
    book.step(_sealed(0, 10, opened=_table([{"t": 1, "acct_id": 0, "amount": 0},
                                            {"t": 2, "acct_id": 1, "amount": X}])), None)
    assert book.report()["chk.once"]["violations"] == 0 and book.keys == 2
    book.step(_sealed(10, 20, opened=_table([{"t": 11, "acct_id": 2, "amount": 2},
                                             {"t": 12, "acct_id": 1, "amount": X},
                                             {"t": 13, "acct_id": 0, "amount": 0},
                                             {"t": 14, "acct_id": 2, "amount": 2}])), None)
    r = book.report()["chk.once"]
    assert (r["checked"], r["violations"], book.keys) == (6, 3, 3)
    assert r["first"]["detail"] == "acct_id 1 seen before"


def test_at_most_once_merges_like_union1d():
    """Final I2: new keys are merged into the sorted set, which equals `np.union1d` of
    everything seen (one column and composite keys, warm-up and exported steps alike)."""
    import numpy as np

    rng = np.random.default_rng(7)
    one = _book(("a", law.at_most_once("opened", key="acct_id"), False))
    two = _book(("b", law.at_most_once("opened", key=("acct_id", "amount")), False))
    for b in (one, two):
        b.max_keys = 10**6
        b.cap_bytes = 24 * 10**6
    seen1, seen2 = np.zeros(0, np.int64), set()
    for step in range(12):
        a = rng.integers(-50, 50, 40)
        m = rng.integers(0, 3, 40)
        rows = [{"t": step * 10 + 1, "acct_id": int(x), "amount": int(y)} for x, y in zip(a, m)]
        mk = _warm if step < 3 else _sealed
        for b in (one, two):
            b.step(mk(step * 10, step * 10 + 10, opened=_table(rows)), None,
                   exported=step >= 3)
        seen1 = np.union1d(seen1, a)
        seen2 |= set(zip(a.tolist(), m.tolist()))
    assert np.array_equal(one._laws[0].seen, seen1)
    law2 = two._laws[0]
    assert sorted(map(tuple, law2.cols.tolist())) == sorted(seen2)
    assert np.all(np.diff(law2.seen) >= 0)


def test_total_le_never_wraps():
    """Codex C2: a total past int64 exceeds the limit, within a step and across steps; a total
    below int64 is not a violation."""
    cap = ("chk.cap", law.total_le("opened.amount", I64_MAX), True)
    with pytest.raises(LawViolation, match=f"total {I64_MAX + 1} exceeds {I64_MAX}"):
        _book(cap).step(_sealed(0, 10, opened=_table([{"t": 1, "acct_id": 1, "amount": I64_MAX},
                                                      {"t": 2, "acct_id": 1, "amount": 1}])),
                        None)
    book = _book(cap)
    book.step(_sealed(0, 10, opened=_table([{"t": 1, "acct_id": 1, "amount": I64_MAX}])), None)
    with pytest.raises(LawViolation, match=f"total {I64_MAX + 1} exceeds"):
        book.step(_sealed(10, 20, opened=_table([{"t": 11, "acct_id": 1, "amount": 1}])), None)
    low = _book(("chk.low", law.total_le("opened.amount", 0), True))
    low.step(_sealed(0, 10, opened=_table([{"t": 1, "acct_id": 1, "amount": I64_MIN}])), None)
    low.step(_sealed(10, 20, opened=_table([{"t": 11, "acct_id": 1, "amount": -1}])), None)
    assert low.report()["chk.low"]["violations"] == 0


def test_sum_le_stops_when_a_sum_leaves_int64():
    """Codex C2: a per-key sum past int64 is a loud error, never a wrapped pass."""
    from neorisk_simkit.engine.errors import EngineError

    entry = _table([{"t": 1, "acct_id": 2, "amount": I64_MAX}])
    with pytest.raises(EngineError, match=f"opened.amount for acct_id 2 reaches {I64_MAX + 1}"):
        _book(LE).step(_sealed(0, 10, entry=entry, opened=_table([
            {"t": 2, "acct_id": 2, "amount": I64_MAX}, {"t": 3, "acct_id": 2, "amount": 1}])),
            None)
    book = _book(LE)
    book.step(_sealed(0, 10, entry=entry,
                      opened=_table([{"t": 2, "acct_id": 2, "amount": I64_MAX}])), None)
    with pytest.raises(EngineError, match="outside int64"):
        book.step(_sealed(10, 20, opened=_table([{"t": 11, "acct_id": 2, "amount": 1}])), None)


@pytest.mark.parametrize("side", ["entry", "opened"])
def test_sum_le_stops_when_a_carried_sum_at_int64_min_goes_lower(side):
    """Codex fix-confirm CX1: a per-key sum carried at exactly INT64_MIN (where an int64 abs
    wraps) followed by -1 in a later step is a loud error, never a wrap to INT64_MAX; on
    either side of the law."""
    from neorisk_simkit.engine.errors import EngineError

    book = _book(("chk.le", law.sum_le("opened.amount", "entry.amount", by="acct_id"), False))
    first = _table([{"t": 1, "acct_id": 3, "amount": I64_MIN}])
    book.step(_sealed(0, 10, **{side: first}), None)
    law_ = book._laws[0]
    assert (law_.rsum if side == "entry" else law_.lsum).tolist() == [I64_MIN]
    with pytest.raises(EngineError, match=f"for acct_id 3 reaches {I64_MIN - 1}, outside int64"):
        book.step(_sealed(10, 20, **{side: _table([{"t": 11, "acct_id": 3, "amount": -1}])}),
                  None)


def test_total_le_at_int64_min():
    """CX1: a carried total at INT64_MIN goes lower exactly (no violation, no wrap), and is
    still judged exactly when it climbs back past the limit (balanced at INT64_MIN:
    test_checks_laws.py)."""
    low = _book(("chk.low", law.total_le("opened.amount", 0), True))
    low.step(_sealed(0, 10, opened=_table([{"t": 1, "acct_id": 1, "amount": I64_MIN}])), None)
    low.step(_sealed(10, 20, opened=_table([{"t": 11, "acct_id": 1, "amount": -1}])), None)
    assert low._laws[0].total == I64_MIN - 1 and low.report()["chk.low"]["violations"] == 0
    with pytest.raises(LawViolation, match=f"total {I64_MIN - 1 + 2 * I64_MAX} exceeds 0"):
        low.step(_sealed(20, 30, opened=_table([{"t": 21, "acct_id": 1, "amount": I64_MAX},
                                                {"t": 22, "acct_id": 1, "amount": I64_MAX}])),
                 None)


def test_checker_state_charges_each_reducers_layout():
    """Codex C3: each keyed law carries its real bytes per key; the laws share `checker_state`."""
    once = ("chk.once", law.at_most_once("opened", key=("acct_id", "amount")), False)
    book = _book(once, LE, RES)
    rows = [{"t": i, "acct_id": i, "amount": i} for i in range(1, 4)]
    book.step(_sealed(0, 10, opened=_table(rows), entry=_table(rows)), None)
    a, le, res = book._laws
    assert (a.key_bytes, le.key_bytes, res.key_bytes) == (24, 24, 56)
    assert a.keys() * 24 == a.seen.nbytes + a.cols.nbytes
    assert le.keys() * 24 == le.skeys.nbytes + le.lsum.nbytes + le.rsum.nbytes
    assert res.keys() * 56 == sum(v.nbytes for v in res.open.values())
    assert book.state_bytes == sum(x.keys() * x.key_bytes for x in book._laws) > 0
    assert book.cap_bytes == 66 * 100 + 64 * 100                # resolved's peak, 100 keys


def _measured_peak(lw, n0, both):
    """(bytes the law's update to n0 + 10 keys held at its peak: state before plus the peak of
    new allocations, traced from the start; keys after)."""
    import tracemalloc

    tracemalloc.start()
    try:
        book = LawBook(_plan(("x", lw, False)), max_keys=10**8)
        t = _table([{"t": 1, "acct_id": i, "amount": i} for i in range(n0)])
        book.step(_sealed(0, 10 * S, opened=t, entry=t if both else None), None)
        nt = _table([{"t": 10 * S + 1, "acct_id": n0 + i, "amount": 1} for i in range(10)])
        before = book.state_bytes
        tracemalloc.reset_peak()
        base = tracemalloc.get_traced_memory()[0]
        book.step(_sealed(10 * S, 20 * S, opened=nt, entry=nt if both else None), None)
        return before + tracemalloc.get_traced_memory()[1] - base, n0 + 10
    finally:
        tracemalloc.stop()


@pytest.mark.parametrize("lw,both", [
    (law.at_most_once("opened", key="acct_id"), False),
    (law.at_most_once("opened", key=("acct_id", "amount")), False),
    (law.sum_le("opened.amount", "entry.amount", by="acct_id"), True),
    (law.resolved("opened", by=("entry",), key="acct_id", within="100d"), False),
    (law.resolved("opened", by=("entry",), key="acct_id", within="100d"), True)])
def test_an_update_stays_within_its_reserved_peak(lw, both):
    """Codex fix-confirm CX2: the bytes an update really holds at once (old and new arrays,
    merge masks, matching chunk; numpy allocations traced) stay within `law_peak_bytes`, which
    the reservation charges before allocating. Slack: the step's own few rows."""
    from neorisk_simkit.spec.caps import law_peak_bytes

    peak, n = _measured_peak(lw, 200_000, both)
    assert peak <= law_peak_bytes(lw, n) + 16_384, (peak, law_peak_bytes(lw, n))
    assert peak >= 0.9 * law_peak_bytes(lw, n) - 64 * 65_536    # the bound is not loose


def test_a_reservation_near_the_cap_raises_before_allocating():
    """CX2: `checker_state` covers an update's peak beside the other laws' state; the update
    that would pass it raises `CapExceeded` with the state untouched."""
    import numpy as np

    one = LawBook(_plan(RES), max_keys=1)                  # cap: one key's peak, 66 + 64 B
    one.step(_sealed(0, S, opened=_table([{"t": 1, "acct_id": 1, "amount": 0}])), None)
    assert one.state_bytes == 56 and one.cap_bytes == 130
    with pytest.raises(CapExceeded, match=r"limit 130, attempted 260"):
        one.step(_sealed(S, 2 * S, opened=_table([{"t": S + 1, "acct_id": 2, "amount": 0}])),
                 None)
    assert one.keys == 1 and np.array_equal(one._laws[0].open["key"], [1])

    book = LawBook(_plan(LE, ("chk.once", law.at_most_once("opened", key="acct_id"), False)),
                   max_keys=4)                              # cap 4 x 33 = 132
    rows = [{"t": i, "acct_id": i, "amount": 0} for i in range(1, 4)]
    book.step(_sealed(0, 10, opened=_table(rows), entry=_table(rows)), None)
    le, once = book._laws
    assert book.cap_bytes == 132 and (le.keys(), once.keys()) == (3, 3)
    # sum_le grows to 4 keys: 4 x 33 + once's 3 x 8 = 156 > 132, so the step raises first
    with pytest.raises(CapExceeded, match=r"limit 132, attempted 156"):
        book.step(_sealed(10, 20, entry=_table([{"t": 11, "acct_id": 9, "amount": 0}])), None)
    assert le.keys() == 3 and np.array_equal(le.skeys, [1, 2, 3])
