"""Reference implementations: plain-Python replays that re-derive what a std recipe must have
done, independently of the recipe and of the Polars laws. Tests run them against real packs
on forced-path fixtures.
"""

from __future__ import annotations

import polars as pl

from neorisk_simkit.checks import Data


def holds_ledger(d: Data) -> list[str]:
    """Replay hold rows in seq order: each hold is placed once, then resolved at most once,
    by the same partition, for the same amount and purpose, never before it was placed."""
    rows = pl.concat([d.ev(e).select("seq", "event_type", "partition_id", "hold_id", "amount",
                                     "purpose")
                      for e in ("hold_placed", "hold_committed", "hold_released")]).sort("seq")
    open_: dict[int, tuple[int, int, str]] = {}
    seen: set[int] = set()
    errs = []
    for seq, kind, part, hid, amt, purpose in rows.iter_rows():
        if kind == "hold_placed":
            if hid in seen:
                errs.append(f"seq {seq}: hold {hid} placed twice")
            seen.add(hid)
            open_[hid] = (part, amt, purpose)
            continue
        if hid not in open_:
            errs.append(f"seq {seq}: {kind} of hold {hid}, which is not open")
            continue
        p0, a0, u0 = open_.pop(hid)
        if (p0, a0, u0) != (part, amt, purpose):
            errs.append(f"seq {seq}: {kind} of hold {hid} as {(part, amt, purpose)}, "
                        f"placed as {(p0, a0, u0)}")
    return errs
