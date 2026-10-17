"""Declared laws evaluated on sealed steps (spec section 11; D47, F-01).

`LawBook(plan, max_keys=...)` holds one evaluator per `CheckDef`, in declaration order. Every
sealed step is fed to `LawBook.step`:

- an exported step judges its event and posting tables (they arrive in canonical order) and,
  for state laws, the live partitions' state at the seal. A required law raises `LawViolation`
  at its first offending row; a non-required one counts `violations` and keeps the first
  citation. Failures cite `(partition_id, seq)` and the action ID.
- a warm-up step (`exported=False`) reads `sealed.warmup_rows` and only updates carried state
  (`total_le` running totals, `at_most_once` key sets): §11 reducers start from the opening
  snapshot. Nothing is counted, judged or cited; state laws and `balanced` skip it.

Carried keys are capped at `max_keys` (`checker_state`, 24 B per key). Evaluation reads only
the sealed tables and the world state, so it is identical across thread counts.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from neorisk_simkit.engine.errors import CapExceeded, LawViolation
from neorisk_simkit.io.consts import NULL
from neorisk_simkit.spec.caps import CHECKER_KEY_BYTES

_NONE = np.zeros(0, np.int64)
_M1 = np.uint64(0xBF58476D1CE4E5B9)
_M2 = np.uint64(0x94D049BB133111EB)


# ---------------------------------------------------------------------------- paths
def resolve_path(plan: Any, path: str) -> tuple[str, str, str]:
    """`("event", table, column)` for an event or posting column, `("owner", partition,
    column)` for an owner table column, `("shard", partition, field)` for a shard state
    field; `ValueError` otherwise."""
    name, _, col = path.partition(".")
    if col:
        for e in plan.events:
            if e.name == name and any(c.name == col for c in e.cols):
                return ("event", name, col)
        for p in plan.partitions:
            if p.kind == "owner" and p.table == name and any(
                    c.name == col for c in plan.table(name).cols):
                return ("owner", p.name, col)
        for p in plan.partitions:
            if p.kind == "shard" and p.name == name and col in p.state:
                return ("shard", name, col)
    raise ValueError(f"unknown path {path!r}")


def _event_table(plan: Any, path: str) -> tuple[str, str]:
    kind, table, col = resolve_path(plan, path)
    if kind != "event":
        raise ValueError(f"{path!r} is not an event or posting column")
    return table, col


# ---------------------------------------------------------------------------- columns
def _column(t: pa.Table, name: str) -> tuple[np.ndarray, np.ndarray | None]:
    """A column as numpy (dictionary codes, µs for timestamps, 0/1 for bools; nulls read 0)
    and its validity mask (`None` when no value is null)."""
    c = t.column(name).combine_chunks()
    valid = np.asarray(c.is_valid().to_numpy(zero_copy_only=False), bool) if c.null_count \
        else None
    if pa.types.is_dictionary(c.type):
        c = c.indices
    elif pa.types.is_timestamp(c.type):
        c = c.cast(pa.int64())
    elif pa.types.is_boolean(c.type):
        c = c.cast(pa.int8())
    if c.null_count:
        c = c.fill_null(0)
    return c.to_numpy(zero_copy_only=False), valid


def _mix64(x: np.ndarray) -> np.ndarray:
    x = (x ^ (x >> np.uint64(30))) * _M1
    x = (x ^ (x >> np.uint64(27))) * _M2
    return x ^ (x >> np.uint64(31))


def row_keys(t: pa.Table, cols: tuple[str, ...]) -> np.ndarray:
    """int64 key per row: the column itself for one column, else `rng.mix` of the columns."""
    if len(cols) == 1:
        return np.asarray(_column(t, cols[0])[0], np.int64)
    h = np.zeros(t.num_rows, np.uint64)
    for c in cols:
        h = _mix64(h ^ np.asarray(_column(t, c)[0], np.int64).view(np.uint64))
    return h.view(np.int64)


def _cite(t: pa.Table, i: int) -> tuple[int, int, int]:
    return (int(t.column("partition_id")[i].as_py()), int(t.column("seq")[i].as_py()),
            int(t.column("action_id")[i].as_py()))


# ---------------------------------------------------------------------------- evaluators
class _Law:
    """One check: counters, the first citation, and its carried state."""

    tables: tuple[str, ...] = ()

    def __init__(self, cdef: Any):
        self.id = cdef.id
        self.kind = cdef.law.kind
        self.required = bool(cdef.required)
        self.checked = 0
        self.violations = 0
        self.censored = 0
        self.first: dict[str, Any] | None = None

    def keys(self) -> int:
        return 0

    def warm(self, rows: dict[str, pa.Table]) -> None:
        """Feed a warm-up step's rows into carried state (nothing judged)."""

    def judge(self, rows: dict[str, pa.Table], world: Any, retired: np.ndarray) -> int:
        """Judge an exported step (`retired`: owner slots freed at its seal); returns the
        values checked."""
        return 0

    def _fail(self, table: str, cite: tuple[int, int, int], detail: str, n: int) -> None:
        """Record `n` violations whose first is `cite`; raise if the law is required."""
        self.violations += n
        pid, seq, action = cite
        if self.first is None:
            self.first = {"table": table, "partition_id": pid, "seq": seq, "action_id": action,
                          "detail": detail}
        if self.required:
            raise LawViolation(self.id, table, pid, seq, action, detail)

    def report(self) -> dict[str, Any]:
        return {"law": self.kind, "required": self.required, "checked": self.checked,
                "violations": self.violations, "censored": self.censored, "first": self.first}


class _NeverNegativeRows(_Law):
    def __init__(self, cdef: Any, table: str, col: str):
        super().__init__(cdef)
        self.table, self.col = table, col
        self.tables = (table,)

    def judge(self, rows, world, retired):
        t = rows.get(self.table)
        if t is None or not t.num_rows:
            return 0
        v, valid = _column(t, self.col)
        bad = v < 0
        if valid is not None:
            bad &= valid
        n_bad = int(bad.sum())
        if n_bad:
            i = int(np.argmax(bad))
            self._fail(self.table, _cite(t, i), f"{self.col} = {v[i].item()}", n_bad)
        return t.num_rows if valid is None else int(valid.sum())


class _TotalLe(_Law):
    """Running total over the run (warm-up rows included); every row that leaves the total
    above the limit is a violation."""

    def __init__(self, cdef: Any, table: str, col: str, limit: int):
        super().__init__(cdef)
        self.table, self.col, self.limit = table, col, int(limit)
        self.tables = (table,)
        self.total = 0

    def _running(self, t: pa.Table) -> tuple[np.ndarray, np.ndarray | None]:
        v, valid = _column(t, self.col)
        v = np.asarray(v, np.int64)
        if valid is not None:
            v = np.where(valid, v, 0)
        return self.total + np.cumsum(v), valid

    def warm(self, rows):
        t = rows.get(self.table)
        if t is not None and t.num_rows:
            self.total = int(self._running(t)[0][-1])

    def judge(self, rows, world, retired):
        t = rows.get(self.table)
        if t is None or not t.num_rows:
            return 0
        run, valid = self._running(t)
        bad = run > self.limit
        if valid is not None:
            bad &= valid
        n_bad = int(bad.sum())
        if n_bad:
            i = int(np.argmax(bad))
            self._fail(self.table, _cite(t, i), f"total {int(run[i])} exceeds {self.limit}",
                       n_bad)
        self.total = int(run[-1])
        return t.num_rows if valid is None else int(valid.sum())


class _AtMostOnce(_Law):
    """Keys seen across the run, carried as a sorted int64 array."""

    def __init__(self, cdef: Any, table: str, key: tuple[str, ...]):
        super().__init__(cdef)
        self.table, self.key = table, tuple(key)
        self.tables = (table,)
        self.seen = np.zeros(0, np.int64)

    def keys(self) -> int:
        return len(self.seen)

    def warm(self, rows):
        t = rows.get(self.table)
        if t is not None and t.num_rows:
            self.seen = np.union1d(self.seen, row_keys(t, self.key))

    def judge(self, rows, world, retired):
        t = rows.get(self.table)
        if t is None or not t.num_rows:
            return 0
        k = row_keys(t, self.key)
        pos = np.searchsorted(self.seen, k)
        bad = (pos < len(self.seen)) & (self.seen[np.minimum(pos, len(self.seen) - 1)] == k) \
            if len(self.seen) else np.zeros(len(k), bool)
        order = np.argsort(k, kind="stable")             # a repeat within the step: every
        ks = k[order]                                    # occurrence after the first
        bad[order[1:][ks[1:] == ks[:-1]]] = True
        n_bad = int(bad.sum())
        if n_bad:
            i = int(np.argmax(bad))
            first = int(_column(t, self.key[0])[0][i])
            self._fail(self.table, _cite(t, i), f"{self.key[0]} {first} seen before", n_bad)
        self.seen = np.union1d(self.seen, k)
        return t.num_rows


class _Balanced(_Law):
    """Per step, Σ debit − Σ credit = 0 in every `by` group; the group's first row is cited."""

    def __init__(self, cdef: Any, table: str, amount: str, side: str, by: tuple[str, ...]):
        super().__init__(cdef)
        self.table, self.amount, self.side, self.by = table, amount, side, tuple(by)
        self.tables = (table,)

    def judge(self, rows, world, retired):
        t = rows.get(self.table)
        if t is None or not t.num_rows:
            return 0
        amt, valid = _column(t, self.amount)
        amt = np.asarray(amt, np.int64)
        if valid is not None:
            amt = np.where(valid, amt, 0)
        side = t.column(self.side)
        deb = np.where(np.asarray(pc.fill_null(pc.equal(side, "debit"), False)), amt, 0)
        cre = np.where(np.asarray(pc.fill_null(pc.equal(side, "credit"), False)), amt, 0)
        keys = [np.asarray(_column(t, b)[0]) for b in self.by]
        order = np.lexsort(keys[::-1])                   # by[0] is the primary key
        change = np.zeros(len(order), bool)
        change[0] = True
        for k in keys:
            ks = k[order]
            change[1:] |= ks[1:] != ks[:-1]
        starts = np.flatnonzero(change)
        d = np.add.reduceat(deb[order], starts)
        c = np.add.reduceat(cre[order], starts)
        first_row = np.minimum.reduceat(order, starts)
        bad = d != c
        n_bad = int(bad.sum())
        if n_bad:
            g = int(np.argmin(np.where(bad, first_row, len(order))))
            self._fail(self.table, _cite(t, int(first_row[g])),
                       f"debits {int(d[g])} != credits {int(c[g])}", n_bad)
        return t.num_rows


class _NeverNegativeState(_Law):
    """Every live owner's (or every shard's) value at each exported seal; NULLs are skipped.
    The offending value with the smallest `partition_id` is cited."""

    def __init__(self, cdef: Any, plan: Any, path: str, kind: str, part: str, col: str):
        super().__init__(cdef)
        self.where = f"state {path}"
        self.kind_, self.part, self.col = kind, plan.partition(part), col
        if kind == "owner":
            cols = plan.table(self.part.table).cols
            self.j = next(i for i, c in enumerate(cols) if c.name == col)
            lt = cols[self.j].ltype
            self.nullable = lt.nullable or lt.kind == "ref"
            self.per_item = False
        else:
            from neorisk_simkit.engine.layout import _STATE_RE

            self.j = list(self.part.state).index(col)
            m = _STATE_RE.match(self.part.state[col])
            self.nullable = m.group(1) == "ref"
            self.per_item = m.group(2) is not None

    def _values(self, world: Any, retired: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """(values, partition_id of each value): live owners and the owners that retired at
        this seal (their final state), or every shard."""
        hid, part = world.hidden, self.part
        arr = world.state[part.name][self.j]
        if self.kind_ == "owner":
            base = world.slot_base[part.name]
            gs = np.arange(base, base + part.max_live, dtype=np.int64)
            gs = gs[hid.alive[gs] == 1]
            gone = retired[(retired >= base) & (retired < base + part.max_live)]
            gs = np.concatenate([gs, gone])
            return arr[hid.lslot[gs]], hid.pid[gs]
        if self.per_item:
            offs = world.offs[part.name]
            shard = np.repeat(np.arange(part.n, dtype=np.int64), np.diff(offs))
        else:
            shard = np.arange(part.n, dtype=np.int64)
        return arr, (np.int64(part.ptype_code) << np.int64(56)) | shard

    def judge(self, rows, world, retired):
        v, pid = self._values(world, retired)
        if v.dtype.kind == "f":
            valid = ~np.isnan(v)
        elif self.nullable:
            fill = NULL if v.dtype == np.int64 else np.iinfo(v.dtype).min
            valid = v != fill
        else:
            valid = np.ones(len(v), bool)
        bad = valid & (v < 0)
        n_bad = int(bad.sum())
        if n_bad:
            i = int(np.flatnonzero(bad)[np.argmin(pid[bad])])
            self._fail(self.where, (int(pid[i]), -1, -1), f"{self.col} = {v[i].item()}", n_bad)
        return int(valid.sum())


class _Later(_Law):
    """`sum_le` and `resolved`: evaluated from Task 10 on; until then nothing is checked."""

    def __init__(self, cdef: Any, tables: tuple[str, ...]):
        super().__init__(cdef)
        self.tables = tables


def _build(plan: Any, cdef: Any) -> _Law:
    lw = cdef.law
    kind = lw.kind
    if kind == "never_negative":
        path = lw.arg("path")
        where, name, col = resolve_path(plan, path)
        if where == "event":
            return _NeverNegativeRows(cdef, name, col)
        return _NeverNegativeState(cdef, plan, path, where, name, col)
    if kind == "total_le":
        return _TotalLe(cdef, *_event_table(plan, lw.arg("lhs")), lw.arg("limit"))
    if kind == "at_most_once":
        return _AtMostOnce(cdef, lw.arg("event"), lw.arg("key"))
    if kind == "balanced":
        return _Balanced(cdef, lw.arg("table"), lw.arg("amount"), lw.arg("side"), lw.arg("by"))
    if kind == "sum_le":
        return _Later(cdef, (_event_table(plan, lw.arg("lhs"))[0],
                             _event_table(plan, lw.arg("rhs"))[0]))
    if kind == "resolved":
        return _Later(cdef, (lw.arg("event"), *lw.arg("by")))
    raise ValueError(f"check {cdef.id}: unknown law {kind!r}")


# ---------------------------------------------------------------------------- the book
class LawBook:
    """Every declared check of `plan`, evaluated step by step (see the module docstring)."""

    def __init__(self, plan: Any, *, max_keys: int):
        self.max_keys = int(max_keys)
        self._laws = [_build(plan, c) for c in plan.checks]
        self.end_us: int | None = None

    @property
    def tables(self) -> frozenset[str]:
        """The event and posting tables any check reads."""
        return frozenset(t for law in self._laws for t in law.tables)

    @property
    def keys(self) -> int:
        """Keys carried across steps by every check."""
        return sum(law.keys() for law in self._laws)

    def step(self, sealed: Any, world: Any, *, exported: bool = True) -> dict[str, int]:
        """Feed one sealed step; returns the values checked per check this step."""
        out: dict[str, int] = {}
        if exported:
            rows = {**sealed.events, **sealed.postings}
            retired = getattr(sealed, "retired", _NONE)
            for law in self._laws:
                n = law.judge(rows, world, retired)
                law.checked += n
                out[law.id] = n
        else:
            for law in self._laws:
                law.warm(sealed.warmup_rows)
                out[law.id] = 0
        keys = self.keys
        if keys > self.max_keys:
            raise CapExceeded("checker_state", CHECKER_KEY_BYTES * self.max_keys,
                              CHECKER_KEY_BYTES * keys)
        return out

    def finish(self, end_us: int) -> None:
        """The run ended at `end_us` (Task 10 censors `resolved` keys open past it)."""
        self.end_us = int(end_us)

    def report(self) -> dict[str, dict]:
        return {law.id: law.report() for law in self._laws}
