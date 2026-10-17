"""Structural checks on a sealed step: canonical order, required columns, category codes,
partition ids free of provisional handles, and event times inside the step."""

from __future__ import annotations

from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from neorisk_simkit.engine.errors import EngineError
from neorisk_simkit.engine.identity import FLAG
from neorisk_simkit.spec.types import COMMON_COLUMNS

CHECKS = ("canonical_order", "required_not_null", "cat_codes", "no_provisional", "time_in_step")


def _i64(col: pa.ChunkedArray) -> np.ndarray:
    if pa.types.is_timestamp(col.type):
        col = col.cast(pa.int64())
    return col.to_numpy()


def _strictly_increasing(keys: list[np.ndarray]) -> int:
    """Index of the first row whose key is not above the previous row's key, or -1."""
    if len(keys[0]) < 2:
        return -1
    above = np.zeros(len(keys[0]) - 1, bool)
    equal = np.ones(len(keys[0]) - 1, bool)
    for k in keys:
        a, b = k[:-1], k[1:]
        above |= equal & (b > a)
        equal &= b == a
    bad = np.flatnonzero(~above)
    return int(bad[0]) + 1 if len(bad) else -1


def _check_table(where: str, t: pa.Table, time_col: str, cols, sealed: Any,
                 counts: dict[str, int]) -> None:
    if t.num_rows == 0:
        return
    time = _i64(t[time_col])
    keys = [time, _i64(t["lamport"]), _i64(t["partition_id"]), _i64(t["seq"])]
    i = _strictly_increasing(keys)
    if i >= 0:
        raise EngineError(f"{where}: canonical key does not increase at row {i}")
    counts["canonical_order"] += t.num_rows
    for c in cols:
        if not c.ltype.nullable and t[c.name].null_count:
            raise EngineError(f"{where}: null in required column {c.name}")
        counts["required_not_null"] += 0 if c.ltype.nullable else 1
        if c.ltype.kind == "cat":
            col = t[c.name].combine_chunks()
            idx = col.indices if isinstance(col, pa.DictionaryArray) else col
            mm = pc.min_max(idx).as_py()
            if mm["min"] is not None and (mm["min"] < 0 or mm["max"] >= len(c.ltype.values)):
                raise EngineError(f"{where}: category code of {c.name} out of range "
                                  f"[0, {len(c.ltype.values)})")
            counts["cat_codes"] += 1
    pid = _i64(t["partition_id"])
    if ((pid >= 0) & ((pid & FLAG) != 0)).any():
        raise EngineError(f"{where}: provisional handle left in partition_id after remap")
    counts["no_provisional"] += t.num_rows
    if time.min() < sealed.t_start or time.max() >= sealed.t_end:
        raise EngineError(f"{where}: {time_col} outside the step [{sealed.t_start}, "
                          f"{sealed.t_end})")
    counts["time_in_step"] += t.num_rows


def check_step(sealed: Any, plan: Any) -> dict[str, int]:
    """Run every structural check on `sealed`; counts per check, `EngineError` on a violation.

    Refs are public IDs here, so unresolved handles in ref columns are caught by the seal's
    remap (it fails on any provisional value it cannot resolve); this check covers the raw
    `partition_id` column, where a provisional handle would still be visible.
    """
    from neorisk_simkit.spec.plan import Column

    counts = dict.fromkeys(CHECKS, 0)
    for e in plan.events:                          # events and postings (D45) alike
        posting = e.group == "postings"
        t = (sealed.postings if posting else sealed.events).get(e.name)
        if t is not None:
            _check_table(f"{'postings' if posting else 'event'} {e.name}", t, "event_time",
                         e.cols, sealed, counts)
    head = [Column(n, lt) for n, lt in COMMON_COLUMNS if n in ("lamport", "seq")]
    for g in plan.change_groups:
        t = sealed.history.get(g.name)
        if t is not None:
            _check_table(f"history {g.name}", t, "valid_from", [*head, *g.cols], sealed,
                         counts)
    return counts
