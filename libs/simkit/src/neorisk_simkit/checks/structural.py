"""Structural checks on a sealed step: canonical order, required columns, category codes,
partition ids free of provisional handles, and event times inside the step."""

from __future__ import annotations

from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from neorisk_simkit.engine.errors import EngineError
from neorisk_simkit.engine.identity import FLAG
from neorisk_simkit.io.consts import NULL
from neorisk_simkit.spec.types import COMMON_COLUMNS

CHECKS = ("canonical_order", "required_not_null", "cat_codes", "no_provisional", "time_in_step",
          "ref_in_range")


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


Bound = int | tuple[int, int, int]


def ref_bounds(world: Any, id_bases: dict[str, int]) -> dict[str, Bound]:
    """Rows known per ref target (D48): population tables count the owners admitted so far
    (`pop.next`, not `n`, F-05), static / recipe tables their rows, created namespaces
    `id_bases[ns]` (after this step's assignment). Each is an int `b` = `[0, b)`, except a
    member table (D75): `(a, b, c)` = `[0, a) ∪ [b, c)` - admitted population owners, then the
    member rows from `n` on."""
    bounds: dict[str, Bound] = {name: len(next(iter(cols.values()))) if cols else 0
                                for name, cols in world.tables.items()}
    members = set(world.plan.member_tables)
    pops = {}
    for pop in world.populations:
        pops[pop.table] = pop
        bounds[pop.table] = max(bounds.get(pop.table, 0), int(pop.next))
    for ns in world.plan.namespaces:
        if ns in members and ns in pops:
            n = len(pops[ns].times)
            bounds[ns] = (int(pops[ns].next), n, max(n, int(id_bases.get(ns, n))))
        elif ns in id_bases:
            bounds[ns] = max(bounds.get(ns, 0), int(id_bases[ns]))
    return bounds


def check_ref_range(where: str, values: np.ndarray, target: str, bound: Bound,
                    cite: tuple[np.ndarray, ...] | None = None) -> int:
    """Check that every non-`NULL` dense ref lies in `[0, bound)` (an int) or in
    `[0, a) ∪ [b, c)` (`bound = (a, b, c)`, a member table, D75); returns the values checked.

    `cite` = `(partition_id, seq, action_id)` arrays parallel to `values`; the first offending
    row is named in the error (§11: failures cite (partition_id, seq) and action ID)."""
    v = np.asarray(values, np.int64)
    keep = v != NULL
    v = v[keep]
    if isinstance(bound, tuple):
        a, b, c = bound
        bad = np.flatnonzero((v < 0) | ((v >= a) & (v < b)) | (v >= c))
        rng = f"[0, {a}) ∪ [{b}, {c})"
    else:
        bad = np.flatnonzero((v < 0) | (v >= bound))
        rng = f"[0, {bound})"
    if len(bad):
        msg = f"{where}: ref {int(v[bad[0]])} outside {rng} of {target}"
        if cite is not None:
            pid, seq, action = (int(np.asarray(c)[keep][bad[0]]) for c in cite)
            msg += f" at (partition_id {pid}, seq {seq}), action {action}"
        raise EngineError(msg)
    return len(v)


def check_refs(plan: Any, records: dict[str, dict[str, np.ndarray]],
               creates: dict[str, dict[str, np.ndarray]], bounds: dict[str, Bound]) -> int:
    """Range-check every ref column of the step's events, postings, history and created rows
    (dense values, after the remap and before public IDs are drawn)."""
    n = 0

    def one(where: str, rows: dict[str, np.ndarray], c: Any) -> int:
        lt = c.ltype
        v = rows[c.name]
        cite = ((rows["pid"], rows["seq"], rows["action"])
                if "seq" in rows and "action" in rows else (rows["pid"],) * 3)
        if lt.nullable:
            ok = np.asarray(rows[f"valid_{c.name}"], bool)
            v, cite = v[ok], tuple(x[ok] for x in cite)
        # a target with no rows at all (orphan table) has bound 0: every ref to it dangles
        return check_ref_range(f"{where}.{c.name}", v, lt.target, bounds.get(lt.target, 0),
                               cite)

    for e in plan.events:
        for c in e.cols[len(COMMON_COLUMNS):]:
            if c.ltype.kind == "ref":
                what = {"postings": "posting", "labels": "label"}.get(e.group, "event")
                n += one(f"{what} {e.name}", records[e.name], c)
    for g in plan.change_groups:
        for c in g.cols:
            if c.ltype.kind == "ref":
                n += one(f"history {g.name}", records[g.name], c)
    tables = {t.name: t for t in plan.tables}
    for ns in plan.namespaces:
        for c in (tables[ns].cols if ns in tables else ()):
            if c.ltype.kind == "ref":
                n += one(f"created {ns}", creates[ns], c)
    return n


def check_step(sealed: Any, plan: Any) -> dict[str, int]:
    """Run every structural check on `sealed`; counts per check, `EngineError` on a violation.

    Refs are public IDs here, so unresolved handles in ref columns are caught by the seal's
    remap (it fails on any provisional value it cannot resolve); this check covers the raw
    `partition_id` column, where a provisional handle would still be visible.
    """
    from neorisk_simkit.spec.plan import Column

    counts = dict.fromkeys(CHECKS, 0)
    groups = {"events": ("event", sealed.events), "postings": ("postings", sealed.postings),
              "labels": ("labels", sealed.labels)}
    for e in plan.events:                          # events, postings (D45), labels (D76) alike
        what, tables = groups[e.group]
        t = tables.get(e.name)
        if t is not None:
            _check_table(f"{what} {e.name}", t, "event_time", e.cols, sealed, counts)
    head = [Column(n, lt) for n, lt in COMMON_COLUMNS if n in ("lamport", "seq")]
    for g in plan.change_groups:
        t = sealed.history.get(g.name)
        if t is not None:
            _check_table(f"history {g.name}", t, "valid_from", [*head, *g.cols], sealed,
                         counts)
    return counts
