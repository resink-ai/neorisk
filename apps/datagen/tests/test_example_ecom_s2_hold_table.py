"""D49 hold-table rules of the ecommerce_s2 inventory desk, pinned on the kernel helpers.

The helpers run as plain Python against stub ctx / state / Local / out objects: slot choice and
the free-once paths are invisible in events (the slot only travels in the response payload).
"""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from neorisk_simkit import std
from neorisk_simkit.engine import COMMIT, reject

pytestmark = pytest.mark.large

KERNELS = (Path(__file__).resolve().parents[3] / "examples" / "ecommerce_s2" / "specs"
           / "kernels.py")
_spec = importlib.util.spec_from_file_location("ecom_s2_kernels", KERNELS)
k = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(k)

T0 = 1_000_000_000
TTL_S = 600
FIRST_HOLD = 9_000


class Out:
    """Records every write the helper makes; reserves always succeed."""

    def __init__(self):
        self.calls = []
        self._next = FIRST_HOLD

    def reserve(self, **_):
        return True

    def new_id(self, ns):
        assert ns == "hold"
        self._next += 1
        return self._next

    def respond(self, cmd, name, **pay):
        self.calls.append(("respond", name, pay))

    def timer(self, t, kind, prio, tag):
        self.calls.append(("timer", t, kind, tag))

    def __getattr__(self, name):
        if not name.startswith("emit_"):
            raise AttributeError(name)
        return lambda t, **cols: self.calls.append((name[5:], cols))

    def names(self):
        return [c[0] if c[0] != "respond" else f"respond:{c[1]}" for c in self.calls]


def _desk(n_items=4, on_hand=10):
    ctx = SimpleNamespace(t=T0, self_id=3, cfg=SimpleNamespace(hold_ttl_s=TTL_S),
                          reads=SimpleNamespace(sku=SimpleNamespace(
                              local_index={100 + i: i for i in range(n_items)})))
    s = SimpleNamespace(on_hand=[on_hand] * n_items, reserved=[0] * n_items,
                        sku=[100 + i for i in range(n_items)])
    loc = SimpleNamespace(res_hold=[std.NULL] * k.HOLD_SLOTS, res_item=[0] * k.HOLD_SLOTS,
                          res_qty=[0] * k.HOLD_SLOTS, res_ckt=[std.NULL] * k.HOLD_SLOTS)
    return ctx, s, loc


def _fill(loc, holes=()):
    for j in range(k.HOLD_SLOTS):
        if j not in holes:
            loc.res_hold[j], loc.res_item[j], loc.res_qty[j], loc.res_ckt[j] = 500 + j, 0, 0, 7


def _reserve_cmd(sku=101, qty=2, tag=77):
    return SimpleNamespace(kind=k.C_RESERVE, sku_id=sku, quantity=qty, tag=tag, line=1)


def _hold_cmd(kind, hold_id, slot, sku=101, qty=2, tag=77):
    return SimpleNamespace(kind=kind, sku_id=sku, quantity=qty, tag=tag, hold_id=hold_id,
                           slot=slot)


def _snapshot(s, loc):
    return (list(s.on_hand), list(s.reserved), list(loc.res_hold), list(loc.res_item),
            list(loc.res_qty), list(loc.res_ckt))


def test_a_reserve_takes_the_lowest_free_slot():
    ctx, s, loc = _desk()
    _fill(loc, holes=(5, 9))
    out = Out()
    assert k._reserve(ctx, s, loc, _reserve_cmd(), out) == COMMIT
    hold = FIRST_HOLD + 1
    assert out.calls[-1] == ("respond", "granted", {"hold_id": hold, "slot": 5, "line": 1})
    assert loc.res_hold[5] == hold and loc.res_hold[9] == std.NULL
    assert (loc.res_item[5], loc.res_qty[5], loc.res_ckt[5]) == (1, 2, 77)
    assert s.reserved[1] == 2
    assert ("timer", T0 + TTL_S * 1_000_000, k.C_HOLD_EXPIRE, hold) in out.calls


def test_a_full_table_rejects_busy_and_out_of_stock_takes_precedence():
    ctx, s, loc = _desk()
    _fill(loc)
    before = _snapshot(s, loc)
    out = Out()
    assert k._reserve(ctx, s, loc, _reserve_cmd(qty=2), out) == COMMIT
    assert out.calls[0] == ("stock_rejected", {"sku_group": 3, "sku_id": 101, "checkout_id": 77,
                                               "quantity": 2, "reason": k.WHY_BUSY})
    assert out.calls[1] == ("respond", "rejected", {"hold_id": std.NULL, "slot": -1, "line": 1})
    assert _snapshot(s, loc) == before
    out = Out()                                            # both apply: out_of_stock wins
    assert k._reserve(ctx, s, loc, _reserve_cmd(qty=11), out) == COMMIT
    assert out.calls[0][1]["reason"] == k.WHY_STOCK
    assert _snapshot(s, loc) == before


def test_a_commit_after_expiry_is_late_and_touches_nothing():
    ctx, s, loc = _desk()
    out = Out()
    k._reserve(ctx, s, loc, _reserve_cmd(), out)
    hold = FIRST_HOLD + 1
    assert k._expire(ctx, s, loc, SimpleNamespace(kind=k.C_HOLD_EXPIRE, tag=hold), out) == COMMIT
    assert out.names()[-1] == "stock_expired" and loc.res_hold[0] == std.NULL
    k._reserve(ctx, s, loc, _reserve_cmd(sku=102, qty=3, tag=78), out)  # reuses slot 0
    before = _snapshot(s, loc)
    out = Out()
    assert k._settle_hold(ctx, s, loc, _hold_cmd(k.C_COMMIT, hold, 0), out) == COMMIT
    assert out.calls == [("stock_commit_late", {"sku_group": 3, "sku_id": 101, "checkout_id": 77,
                                                "hold_id": hold, "quantity": 2})]
    assert _snapshot(s, loc) == before


@pytest.mark.parametrize("first", ["expire", "commit", "release"])
def test_each_slot_is_freed_exactly_once(first):
    ctx, s, loc = _desk()
    k._reserve(ctx, s, loc, _reserve_cmd(), Out())
    hold = FIRST_HOLD + 1
    expire = SimpleNamespace(kind=k.C_HOLD_EXPIRE, tag=hold)
    out = Out()
    if first == "expire":
        assert k._expire(ctx, s, loc, expire, out) == COMMIT
    else:
        kind = k.C_COMMIT if first == "commit" else k.C_RELEASE
        assert k._settle_hold(ctx, s, loc, _hold_cmd(kind, hold, 0), out) == COMMIT
    assert out.names() == [{"expire": "stock_expired", "commit": "stock_committed",
                            "release": "stock_released"}[first]]
    assert loc.res_hold[0] == std.NULL and s.reserved[1] == 0
    assert s.on_hand[1] == (8 if first == "commit" else 10)
    after = _snapshot(s, loc)
    out = Out()
    if first == "expire":                                  # a late release is a stale reject
        assert k._settle_hold(ctx, s, loc, _hold_cmd(k.C_RELEASE, hold, 0), out) == \
            reject(k.REJ_STALE)
    else:                                                  # the TTL finds nothing to free
        assert k._expire(ctx, s, loc, expire, out) == reject(k.REJ_STALE)
    assert out.calls == [] and _snapshot(s, loc) == after
