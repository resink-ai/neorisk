"""Owner-side holds (§06 joint constraints): set aside part of a limited quantity in your own
state (a spending limit, a balance, the refundable amount) while another partition decides,
then commit or release it. No decision ever reads another partition's mutable state.

    holds.declare(p)                                   # hold_placed / _committed / _released
    hid = holds.place(ctx, s.holds, 80, free=s.limit - s.spent, purpose="checkout")
    if hid is None: return ctx.reject("over_limit")    # nothing written yet
    ...later...
    s.spent += holds.commit(ctx, s.holds, hid)         # or holds.release(ctx, s.holds, hid, why)

Law: every hold is committed or released (`checks.laws.holds_resolved`), unless its case is
censored at the horizon.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from neorisk_simkit.spec.pack import Pack
from neorisk_simkit.spec.types import LType, amount, i64, text


@dataclass
class Holds:
    open: dict[int, int] = field(default_factory=dict)     # hold id -> amount
    purpose: dict[int, str] = field(default_factory=dict)  # hold id -> purpose

    @property
    def total(self) -> int:
        return sum(self.open.values())


def declare(p: Pack, *, asset: str = "USD", cols: dict[str, LType] | None = None) -> None:
    """`cols`: extra columns every hold row carries (pass them to place/commit/release)."""
    cols = {"hold_id": i64(), "amount": amount(asset), "purpose": text(), **(cols or {})}
    p.event("hold_placed", cols=cols,
            doc="An owner sets part of a limited quantity aside")
    p.event("hold_committed", cols=cols, doc="The held amount is spent")
    p.event("hold_released", cols={**cols, "reason": text()}, doc="The hold is given back")


def place(ctx, h: Holds, amt: int, *, free: int, purpose: str, **cols) -> int | None:
    """Hold `amt` if `free` minus the open holds covers it; None (nothing written) otherwise."""
    if amt <= 0 or amt > free - h.total:
        return None
    hid = ctx.new_id("hold")
    h.open[hid], h.purpose[hid] = amt, purpose
    ctx.emit("hold_placed", hold_id=hid, amount=amt, purpose=purpose, **cols)
    return hid


def commit(ctx, h: Holds, hid: int, **cols) -> int:
    amt = h.open.pop(hid)
    ctx.emit("hold_committed", hold_id=hid, amount=amt, purpose=h.purpose.pop(hid), **cols)
    return amt


def release(ctx, h: Holds, hid: int, reason: str, **cols) -> int:
    amt = h.open.pop(hid)
    ctx.emit("hold_released", hold_id=hid, amount=amt, purpose=h.purpose.pop(hid),
             reason=reason, **cols)
    return amt
