"""M3 laws: sum_le against owner state (D81), periodic total_le, lifecycle."""

import dataclasses
from types import SimpleNamespace

import numpy as np
import pyarrow as pa
import pytest
from conftest import FIXTURES, make_run

from neorisk_simkit.checks.laws import LawBook
from neorisk_simkit.engine import CapExceeded
from neorisk_simkit.engine.errors import EngineError, LawViolation
from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.spec import law
from neorisk_simkit.spec.plan import CheckDef

TS = pa.timestamp("us", tz="UTC")
I64_MAX, I64_MIN = 2**63 - 1, -(2**63)


def test_refunds_up_to_the_order_amount_pass(tmp_path):
    res = run_to_dataset(FIXTURES / "refunds", "sample", [], out_dir=tmp_path / "a", threads=1)
    assert res.manifest["laws"]["chk.refund_le_paid"]["checked"] == 6


def test_a_refund_beyond_the_order_amount_violates(tmp_path):
    with pytest.raises(LawViolation, match="order_id .*refund_issued.amount total .* exceeds "
                                           "order.amount"):
        run_to_dataset(FIXTURES / "refunds", "sample", ["extra=1"], out_dir=tmp_path / "b",
                       threads=1)


def _table(rows, cols=("acct_id", "amount")):
    n = len(rows)
    out = {"event_id": pa.array(range(1, n + 1), pa.int64()),
           "event_type": pa.array(["x"] * n, pa.string()),
           "event_time": pa.array([r["t"] for r in rows], pa.int64()).cast(TS),
           "lamport": pa.array([r.get("lamport", i + 1) for i, r in enumerate(rows)], pa.int64()),
           "partition_id": pa.array([r.get("pid", 1) for r in rows], pa.int64()),
           "seq": pa.array([r.get("seq", i) for i, r in enumerate(rows)], pa.int32()),
           "cause_id": pa.nulls(n, pa.int64()),
           "action_id": pa.array([0] * n, pa.int16())}
    for c in cols:
        out[c] = pa.array([r[c] for r in rows], pa.int64())
    return pa.table(out)


def _book(cid, lw, max_keys=100):
    run = make_run("ledger")
    plan = dataclasses.replace(run.plan, checks=(CheckDef(cid, lw, True),))
    return LawBook(plan, max_keys=max_keys)


def _sealed(events=None, postings=None):
    return SimpleNamespace(step=0, t_start=0, t_end=10**12, exported=True, events=events or {},
                           postings=postings or {}, history={}, entities={}, stats={},
                           warmup_rows={})


def test_total_le_per_period_resets_each_window():
    book = _book("chk.t", law.total_le("opened.amount", 5, per="10us"))
    book.step(_sealed({"opened": _table([{"t": 1, "acct_id": 1, "amount": 5},
                                         {"t": 11, "acct_id": 1, "amount": 5}])}), None)
    with pytest.raises(LawViolation, match="window"):
        book.step(_sealed({"opened": _table([{"t": 12, "acct_id": 1, "amount": 1}])}), None)


def test_lifecycle_follows_its_edges():
    lw = law.lifecycle("acct_id", edges={"opened": ("entry",)})
    book = _book("chk.l", lw)
    book.step(_sealed({"opened": _table([{"t": 1, "acct_id": 1, "amount": 0}])},
                      {"entry": _table([{"t": 2, "acct_id": 1, "amount": 0}])}), None)
    with pytest.raises(LawViolation, match="entry after entry"):
        book.step(_sealed(postings={"entry": _table([{"t": 3, "acct_id": 1, "amount": 0}])}),
                  None)
    book2 = _book("chk.l2", lw)
    with pytest.raises(LawViolation, match="entry cannot start"):
        book2.step(_sealed(postings={"entry": _table([{"t": 3, "acct_id": 2, "amount": 0}])}),
                   None)


def test_lifecycle_update_stays_within_its_reserved_peak():
    """CX2 (F-11): the bytes a lifecycle update holds at once stay within law_peak_bytes."""
    import tracemalloc

    from neorisk_simkit.spec.caps import law_peak_bytes

    lw = law.lifecycle("acct_id", edges={"opened": ("entry",)})
    tracemalloc.start()
    try:
        book = _book("chk.l", lw, max_keys=10**8)
        n0 = 200_000
        book.step(_sealed({"opened": _table([{"t": 1, "acct_id": i, "amount": 0}
                                             for i in range(n0)])}), None)
        before = book.state_bytes
        tracemalloc.reset_peak()
        base = tracemalloc.get_traced_memory()[0]
        book.step(_sealed({"opened": _table([{"t": 2, "acct_id": n0 + i, "amount": 0}
                                             for i in range(10)])}), None)
        peak = before + tracemalloc.get_traced_memory()[1] - base
    finally:
        tracemalloc.stop()
    assert peak <= law_peak_bytes(lw, n0 + 10) + 16_384


# ---------------------------------------------------------------- sum_le against owner state
SEED = 7
REFUND = law.sum_le("refund_issued.amount", "order.amount", by="order_id")


def _refunds_plan(max_live=3, checks=(("chk.r", REFUND, True),)):
    plan = make_run("refunds").plan
    parts = tuple(dataclasses.replace(p, max_live=max_live) if p.name == "order" else p
                  for p in plan.partitions)
    return dataclasses.replace(plan, partitions=parts,
                               checks=tuple(CheckDef(i, lw, r) for i, lw, r in checks))


def _pub(dense):
    from neorisk_simkit.io.seal import public_ids

    return public_ids(SEED, "order", np.asarray(dense, np.int64))


def _world(max_live, owners, alive=None):
    """A stub world: `owners` maps a slot to (dense self_id, amount); `alive` (default: every
    listed slot) the slots alive at the seal."""
    hid = SimpleNamespace(alive=np.zeros(max_live, np.uint8),
                          lslot=np.arange(max_live, dtype=np.int32),
                          self_id=np.zeros(max_live, np.int64))
    amount = np.zeros(max_live, np.int64)
    for slot, (dense, amt) in owners.items():
        hid.self_id[slot], amount[slot] = dense, amt
    for slot in (owners if alive is None else alive):
        hid.alive[slot] = 1
    return SimpleNamespace(hidden=hid, state={"order": [amount]}, slot_base={"order": 0},
                           seed=SEED)


def _refunds(rows):
    return _table(rows, cols=("order_id", "amount"))


def _rsealed(rows=None, retired=(), exported=True):
    t = {} if rows is None else {"refund_issued": _refunds(rows)}
    return SimpleNamespace(step=0, t_start=0, t_end=10**12, exported=exported,
                           events=t if exported else {}, postings={}, history={}, entities={},
                           stats={}, warmup_rows={} if exported else t,
                           retired=np.asarray(retired, np.int64))


def test_sum_le_state_judges_the_running_sum_against_the_last_state_value():
    a, b = _pub([0, 1])
    book = LawBook(_refunds_plan(), max_keys=100)
    w = _world(3, {0: (0, 100), 1: (1, 50)})
    assert book.step(_rsealed([{"t": 1, "order_id": a, "amount": 60},
                               {"t": 2, "order_id": b, "amount": 50}]), w) == {"chk.r": 2}
    w2 = _world(3, {0: (0, 100), 1: (1, 50)}, alive=[1])   # order 0 gone: its value is kept
    with pytest.raises(LawViolation, match=f"order_id {a}: refund_issued.amount total 110 "
                                           f"exceeds order.amount 100"):
        book.step(_rsealed([{"t": 3, "order_id": a, "amount": 50}]), w2)


def test_sum_le_state_reads_retired_owners_and_judges_unknown_keys_against_zero():
    a, b = _pub([4, 5])
    book = LawBook(_refunds_plan(), max_keys=100)
    w = _world(3, {2: (4, 70)}, alive=[])                   # retired at this seal
    book.step(_rsealed([{"t": 1, "order_id": a, "amount": 70}], retired=[2]), w)
    with pytest.raises(LawViolation, match=f"order_id {b}: refund_issued.amount total 1 "
                                           f"exceeds order.amount 0"):
        book.step(_rsealed([{"t": 2, "order_id": b, "amount": 1}]), _world(3, {}))


def test_sum_le_state_follows_the_value_at_each_seal_warmup_included():
    """D81: the right side is refreshed at every seal (warm-up too); warm-up refunds count."""
    a = int(_pub([0])[0])
    book = LawBook(_refunds_plan(), max_keys=100)
    book.step(_rsealed([{"t": 1, "order_id": a, "amount": 40}], exported=False),
              _world(3, {0: (0, 50)}), exported=False)
    book.step(_rsealed([{"t": 2, "order_id": a, "amount": 20}]), _world(3, {0: (0, 60)}))
    with pytest.raises(LawViolation, match="total 61 exceeds order.amount 60"):
        book.step(_rsealed([{"t": 3, "order_id": a, "amount": 1}]), _world(3, {0: (0, 60)}))


def test_sum_le_state_keeps_extreme_keys_apart():
    """Keys are whole int64 values (no hash): neighbours and extremes never merge."""
    book = LawBook(_refunds_plan(), max_keys=100)
    keys = [I64_MIN, -1, 0, 1, I64_MAX]
    book.step(_rsealed([{"t": i, "order_id": k, "amount": -1} for i, k in enumerate(keys)]),
              _world(3, {}))
    lw = book._laws[0]
    assert lw.skeys.tolist() == keys and lw.lsum.tolist() == [-1] * 5


def test_sum_le_state_stops_when_a_sum_leaves_int64():
    """S2 C2/CX1: within a step, across steps, and from a carried INT64_MIN."""
    a = int(_pub([0])[0])
    w = _world(3, {0: (0, I64_MAX)})
    with pytest.raises(EngineError, match=f"for order_id {a} reaches {I64_MAX + 1}"):
        LawBook(_refunds_plan(), max_keys=10).step(
            _rsealed([{"t": 1, "order_id": a, "amount": I64_MAX},
                      {"t": 2, "order_id": a, "amount": 1}]), w)
    book = LawBook(_refunds_plan(), max_keys=10)
    book.step(_rsealed([{"t": 1, "order_id": a, "amount": I64_MAX}]), w)
    with pytest.raises(EngineError, match="outside int64"):
        book.step(_rsealed([{"t": 2, "order_id": a, "amount": 1}]), w)
    low = LawBook(_refunds_plan(), max_keys=10)
    low.step(_rsealed([{"t": 1, "order_id": a, "amount": I64_MIN}]), w)
    assert low._laws[0].lsum.tolist() == [I64_MIN]
    with pytest.raises(EngineError, match=f"reaches {I64_MIN - 1}, outside int64"):
        low.step(_rsealed([{"t": 2, "order_id": a, "amount": -1}]), w)


def test_sum_le_state_cap_at_its_boundary():
    """CX2: `max_keys` keys fit exactly; one more raises before the state changes."""
    from neorisk_simkit.spec.caps import law_key_bytes, law_peak_bytes

    plan = _refunds_plan(max_live=4)
    assert law_key_bytes(REFUND, plan) == 24
    book = LawBook(plan, max_keys=3)
    assert book.cap_bytes == law_peak_bytes(REFUND, 3, plan)
    book.step(_rsealed(), _world(4, {0: (0, 1), 1: (1, 1), 2: (2, 1)}))
    assert book.keys == 3 and book.state_bytes == 72
    lw = book._laws[0]
    assert lw.skeys.nbytes + lw.lsum.nbytes + lw.rlast.nbytes == book.state_bytes
    keys = lw.skeys.copy()
    with pytest.raises(CapExceeded, match="checker_state"):
        book.step(_rsealed(), _world(4, {0: (0, 1), 1: (1, 1), 2: (2, 1), 3: (3, 1)}))
    assert np.array_equal(lw.skeys, keys)
    with pytest.raises(CapExceeded, match="checker_state"):      # a left key beyond the cap
        book.step(_rsealed([{"t": 1, "order_id": 12345, "amount": 0}]),
                  _world(4, {0: (0, 1)}))
    assert np.array_equal(lw.skeys, keys)


def test_sum_le_state_update_stays_within_its_reserved_peak():
    """CX2 (F-11): a seal with 200,000 live orders (public IDs, sort, merge) and a step of
    refunds stays within `law_peak_bytes`, which the reservation charges before allocating."""
    import tracemalloc

    from neorisk_simkit.spec.caps import law_peak_bytes

    n0 = 200_000
    plan = _refunds_plan(max_live=n0 + 10)
    w0 = _world(n0 + 10, {i: (i, 100) for i in range(n0)})
    w1 = _world(n0 + 10, {i: (i, 100) for i in range(n0 + 10)})
    pubs = _pub(range(n0, n0 + 10))
    tracemalloc.start()
    try:
        book = LawBook(plan, max_keys=10**8)
        book.step(_rsealed([{"t": 1, "order_id": int(p), "amount": 1} for p in _pub([0, 1])]),
                  w0)
        before = book.state_bytes
        tracemalloc.reset_peak()
        base = tracemalloc.get_traced_memory()[0]
        book.step(_rsealed([{"t": 2, "order_id": int(p), "amount": 1} for p in pubs]), w1)
        peak = before + tracemalloc.get_traced_memory()[1] - base
    finally:
        tracemalloc.stop()
    bound = law_peak_bytes(REFUND, n0 + 10, plan)
    assert book.keys == n0 + 10
    assert peak <= bound + 16_384, (peak, bound)
    assert peak >= 0.9 * bound, (peak, bound)                  # the bound is not loose


# ---------------------------------------------------------------- periodic total_le
def test_total_le_per_window_is_epoch_aligned_and_cites_the_window():
    book = _book("chk.t", law.total_le("opened.amount", 5, per="10us"))
    book.step(_sealed({"opened": _table([{"t": 9, "acct_id": 1, "amount": 5}])}), None)
    with pytest.raises(LawViolation, match="opened.amount total 7 exceeds 5 in window 1"):
        book.step(_sealed({"opened": _table([{"t": 10, "acct_id": 1, "amount": 5},
                                             {"t": 19, "acct_id": 1, "amount": 2}])}), None)


def test_total_le_per_counts_warmup_rows_in_their_window():
    book = _book("chk.t", law.total_le("opened.amount", 5, per="10us"))
    warm = SimpleNamespace(step=0, t_start=0, t_end=5, exported=False, events={}, postings={},
                           history={}, entities={}, stats={},
                           warmup_rows={"opened": _table([{"t": 1, "acct_id": 1, "amount": 4}])})
    book.step(warm, None, exported=False)
    with pytest.raises(LawViolation, match="total 6 exceeds 5 in window 0"):
        book.step(_sealed({"opened": _table([{"t": 6, "acct_id": 1, "amount": 2}])}), None)


def test_total_le_per_never_wraps():
    """S2 C2/CX1 for windows: within a step, across steps and from INT64_MIN."""
    cap = law.total_le("opened.amount", I64_MAX, per="10us")
    with pytest.raises(LawViolation, match=f"total {I64_MAX + 1} exceeds {I64_MAX} in window 0"):
        _book("c", cap).step(_sealed({"opened": _table([
            {"t": 1, "acct_id": 1, "amount": I64_MAX},
            {"t": 2, "acct_id": 1, "amount": 1}])}), None)
    book = _book("c", cap)
    book.step(_sealed({"opened": _table([{"t": 1, "acct_id": 1, "amount": I64_MAX}])}), None)
    with pytest.raises(LawViolation, match=f"total {I64_MAX + 1} exceeds"):
        book.step(_sealed({"opened": _table([{"t": 2, "acct_id": 1, "amount": 1}])}), None)
    low = _book("c", law.total_le("opened.amount", 0, per="10us"))
    low.step(_sealed({"opened": _table([{"t": 1, "acct_id": 1, "amount": I64_MIN}])}), None)
    low.step(_sealed({"opened": _table([{"t": 2, "acct_id": 1, "amount": -1}])}), None)
    assert low._laws[0].total == I64_MIN - 1 and low.report()["c"]["violations"] == 0
    with pytest.raises(LawViolation, match=f"total {I64_MIN - 1 + 2 * I64_MAX} exceeds 0 in "
                                           f"window 0"):
        low.step(_sealed({"opened": _table([{"t": 3, "acct_id": 1, "amount": I64_MAX},
                                            {"t": 4, "acct_id": 1, "amount": I64_MAX}])}), None)
    fresh = _book("c", law.total_le("opened.amount", 0, per="10us"))
    fresh.step(_sealed({"opened": _table([{"t": 1, "acct_id": 1, "amount": I64_MIN},
                                          {"t": 12, "acct_id": 1, "amount": -5}])}), None)
    assert fresh._laws[0].total == -5                        # window 1 starts from 0


def test_total_le_without_per_keeps_the_run_total():
    book = _book("chk.t", law.total_le("opened.amount", 5))
    book.step(_sealed({"opened": _table([{"t": 1, "acct_id": 1, "amount": 5}])}), None)
    with pytest.raises(LawViolation, match=r"total 6 exceeds 5") as e:
        book.step(_sealed({"opened": _table([{"t": 10**9, "acct_id": 1, "amount": 1}])}), None)
    assert e.value.detail == "total 6 exceeds 5"
    assert law.total_le("opened.amount", 5).args == (("lhs", "opened.amount"), ("limit", 5))


# ---------------------------------------------------------------- lifecycle
LIFE = law.lifecycle("acct_id", edges={"opened": ("entry",)})


def test_lifecycle_orders_rows_canonically_across_tables_and_counts_each_violation():
    book = LawBook(dataclasses.replace(make_run("ledger").plan,
                                       checks=(CheckDef("l", LIFE, False),)), max_keys=10)
    book.step(_sealed({"opened": _table([{"t": 1, "acct_id": 1, "amount": 0},
                                         {"t": 4, "acct_id": 2, "amount": 0}])},
                      {"entry": _table([{"t": 2, "acct_id": 1, "amount": 0},
                                        {"t": 5, "acct_id": 2, "amount": 0},
                                        {"t": 6, "acct_id": 2, "amount": 0}])}), None)
    r = book.report()["l"]
    assert (r["checked"], r["violations"]) == (5, 1)
    assert r["first"]["detail"] == "acct_id 2: entry after entry"
    assert book._laws[0].skeys.tolist() == [1, 2]


def test_lifecycle_warmup_rows_only_set_the_state():
    book = _book("chk.l", law.lifecycle("acct_id", edges={"opened": ("entry",)}))
    warm = SimpleNamespace(step=0, t_start=0, t_end=5, exported=False, events={}, postings={},
                           history={}, entities={}, stats={},
                           warmup_rows={"entry": _table([{"t": 1, "acct_id": 1, "amount": 0}])})
    assert book.step(warm, None, exported=False) == {"chk.l": 0}       # not judged
    with pytest.raises(LawViolation, match="acct_id 1: entry after entry"):
        book.step(_sealed(postings={"entry": _table([{"t": 6, "acct_id": 1, "amount": 0}])}),
                  None)


def test_lifecycle_keeps_extreme_keys_apart_and_merges_like_a_sorted_set():
    book = LawBook(dataclasses.replace(make_run("ledger").plan,
                                       checks=(CheckDef("l", LIFE, False),)), max_keys=10**4)
    rng = np.random.default_rng(3)
    seen = np.zeros(0, np.int64)
    for step in range(8):
        ks = rng.integers(-40, 40, 30)
        if step == 0:
            ks[:3] = (I64_MIN, I64_MAX, 0)
        book.step(_sealed({"opened": _table([{"t": step * 10 + 1, "acct_id": int(k),
                                              "amount": 0} for k in ks])}), None)
        seen = np.union1d(seen, ks)
    assert np.array_equal(book._laws[0].skeys, seen)


def test_lifecycle_cap_at_its_boundary():
    from neorisk_simkit.spec.caps import law_key_bytes, law_peak_bytes

    lw = law.lifecycle("acct_id", edges={"opened": ("entry",)})
    assert law_key_bytes(lw) == 16 and law_peak_bytes(lw, 3) == 99
    book = _book("chk.l", lw, max_keys=3)
    book.step(_sealed({"opened": _table([{"t": 1, "acct_id": a, "amount": 0}
                                         for a in (1, 2, 3)])}), None)
    assert book.state_bytes == 48 == book._laws[0].skeys.nbytes + book._laws[0].last.nbytes
    with pytest.raises(CapExceeded, match=r"limit 99, attempted 132"):
        book.step(_sealed({"opened": _table([{"t": 2, "acct_id": 4, "amount": 0}])}), None)
    assert book._laws[0].skeys.tolist() == [1, 2, 3]


# ---------------------------------------------------------------- validate
def _reasons(plan, lw):
    from neorisk_simkit.spec.validate import _law_reason

    return _law_reason(plan, lw)


def test_validate_accepts_the_new_forms_and_refuses_bad_ones():
    refunds, ledger = make_run("refunds").plan, make_run("ledger").plan
    assert _reasons(refunds, REFUND) is None
    assert "key order_id" in _reasons(
        refunds, law.sum_le("refund_issued.amount", "order.amount", by="amount"))
    assert _reasons(ledger, law.total_le("opened.amount", 5, per="30d")) is None
    assert "per" in _reasons(ledger, law.total_le("opened.amount", 5, per="0s"))
    assert _reasons(ledger, LIFE) is None
    assert "unknown event or posting table 'nope'" in _reasons(
        ledger, law.lifecycle("acct_id", edges={"opened": ("nope",)}))
    assert "has no column side" in _reasons(
        ledger, law.lifecycle("side", edges={"opened": ("entry",)}))
    assert "at least one edge" in _reasons(ledger, law.lifecycle("acct_id", edges={}))
