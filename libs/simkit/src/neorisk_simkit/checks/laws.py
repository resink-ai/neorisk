"""Declared laws evaluated on sealed steps (spec section 11; D47, F-01).

`LawBook(plan, max_keys=...)` holds one evaluator per `CheckDef`, in declaration order. Every
sealed step is fed to `LawBook.step`:

- an exported step judges its event and posting tables (they arrive in canonical order) and,
  for state laws, the live partitions' state at the seal. A required law raises `LawViolation`
  at its first offending row; a non-required one counts `violations` and keeps the first
  citation. Failures cite `(partition_id, seq)` and the action ID.
- a warm-up step (`exported=False`) reads `sealed.warmup_rows` and only updates carried state
  (`total_le` running totals, `at_most_once` key sets, `sum_le` per-key sums, open `resolved`
  keys): §11 reducers start from the opening snapshot. Nothing is counted, judged or cited;
  state laws and `balanced` skip it.

Within a step, checks run in declaration order and the first required check with a violation
raises. `finish(end_us)` censors `resolved` keys still open whose deadline is at or after the
end (reported in `censored`, never a violation).

Carried state is capped at `checker_state` = the largest peak a declared keyed law reaches while
it updates `max_keys` keys (`spec.caps.law_peak_bytes`: old and new arrays plus the update's
workspace). The laws share that cap: before allocating, a law reserves its update's peak beside
the state the others carry (`spec.caps.law_key_bytes`, each reducer's real layout), and
`CapExceeded` is raised instead when it does not fit. Running
totals are exact: a total that leaves int64 is judged exactly (`total_le`, `balanced`) or stops the
run with an `EngineError` (`sum_le`, whose per-key sums are carried as int64). Evaluation reads
only the sealed tables and the world state, so it is identical across thread counts.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from neorisk_simkit.engine.errors import CapExceeded, EngineError, LawViolation
from neorisk_simkit.io.consts import NULL
from neorisk_simkit.spec.caps import (
    RESOLVED_CHUNK,
    checker_state_bytes,
    law_key_bytes,
    law_peak_bytes,
)

_NONE = np.zeros(0, np.int64)
_M1 = np.uint64(0xBF58476D1CE4E5B9)
_M2 = np.uint64(0x94D049BB133111EB)
_I64_MIN, _I64_MAX = int(np.iinfo(np.int64).min), int(np.iinfo(np.int64).max)
_SAFE = 2.0 ** 62                  # a float bound below this proves an int64 sum cannot wrap


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


def key_columns(t: pa.Table, cols: tuple[str, ...]) -> tuple[np.ndarray, np.ndarray]:
    """(int64 key columns, shape (rows, len(cols)); indices of the rows whose key columns are all
    non-null)."""
    keep = np.ones(t.num_rows, bool)
    out = np.empty((t.num_rows, len(cols)), np.int64)
    for j, c in enumerate(cols):
        v, valid = _column(t, c)
        if valid is not None:
            keep &= valid
        out[:, j] = v
    return out, np.flatnonzero(keep)


def key_hash(cols: np.ndarray) -> np.ndarray:
    """`rng.mix` of each row of a (rows, k) key array, as int64. It only indexes keys: two
    different tuples may share a hash."""
    h = np.zeros(len(cols), np.uint64)
    for j in range(cols.shape[1]):
        h = _mix64(h ^ np.ascontiguousarray(cols[:, j]).view(np.uint64))
    return h.view(np.int64)


def row_keys(t: pa.Table, col: str) -> tuple[np.ndarray, np.ndarray]:
    """(int64 key per row, indices of the rows whose key column is non-null)."""
    k, keyed = key_columns(t, (col,))
    return k[:, 0], keyed


def exact_cumsum(v: np.ndarray, base: int = 0) -> np.ndarray:
    """`base + cumsum(v)` without wrapping: int64 when no partial sum can leave int64, else
    exact Python integers (an object array)."""
    if abs(int(base)) + float(np.abs(v.astype(np.float64)).sum()) < _SAFE:
        return np.cumsum(v) + np.int64(base)
    return np.cumsum(np.concatenate([np.array([base], object), v.astype(object)]))[1:]


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
        self.t_end = 0                                   # end of the step being fed
        self.lw = cdef.law
        self.key_bytes = law_key_bytes(cdef.law)         # carried bytes per key

    def keys(self) -> int:
        return 0

    def reserve(self, keys: int) -> None:
        """Called before an update that leaves `keys` keys allocates anything; `LawBook` raises
        `CapExceeded` when the update's peak (`law_peak_bytes`) beside the other laws' state
        would pass `checker_state`."""

    def finish(self, end_us: int) -> None:
        """The run ended at `end_us`."""

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
    """Running total over the run (warm-up rows included). Every judged row that leaves the
    total above the limit is one violation (a non-required law keeps counting each such row,
    zero or negative amounts included, until the total drops back to the limit)."""

    def __init__(self, cdef: Any, table: str, col: str, limit: int):
        super().__init__(cdef)
        self.table, self.col, self.limit = table, col, int(limit)
        self.tables = (table,)
        self.total = 0

    def _running(self, t: pa.Table) -> tuple[np.ndarray, np.ndarray | None]:
        """Exact running totals: a total past int64 is held as a Python integer, so it exceeds
        any int64 limit instead of wrapping."""
        v, valid = _column(t, self.col)
        v = np.asarray(v, np.int64)
        if valid is not None:
            v = np.where(valid, v, 0)
        return exact_cumsum(v, self.total), valid

    def warm(self, rows):
        t = rows.get(self.table)
        if t is not None and t.num_rows:
            self.total = int(self._running(t)[0][-1])

    def judge(self, rows, world, retired):
        t = rows.get(self.table)
        if t is None or not t.num_rows:
            return 0
        run, valid = self._running(t)
        bad = np.asarray(run > self.limit, bool)
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
    """Keys seen across the run. One key column: its sorted values. Several: the complete key
    tuples (`cols`), kept in the order of their `rng.mix` hash (`seen`), which only indexes them:
    tuples with equal hashes are told apart by comparing every column. A row with a null key
    column has no key: it is neither judged nor remembered. New keys are merged into the sorted
    set at their search positions (the set is never re-sorted)."""

    def __init__(self, cdef: Any, table: str, key: tuple[str, ...]):
        super().__init__(cdef)
        self.table, self.key = table, tuple(key)
        self.tables = (table,)
        self.seen = np.zeros(0, np.int64)                # sorted: the value, or the tuple's hash
        self.cols = np.zeros((0, len(self.key)), np.int64) if len(self.key) > 1 else None

    def keys(self) -> int:
        return len(self.seen)

    def _repeats(self, t: pa.Table) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """(keyed rows, their index values, their key tuples, which of them repeat a key seen
        before or earlier in this step: every occurrence after the first)."""
        cols, keyed = key_columns(t, self.key)
        cols = cols[keyed]
        h = cols[:, 0] if self.cols is None else key_hash(cols)
        lo = np.searchsorted(self.seen, h, side="left")
        hi = np.searchsorted(self.seen, h, side="right")
        if self.cols is None:
            bad = hi > lo
        else:
            bad = np.zeros(len(h), bool)
            one = np.flatnonzero(hi - lo == 1)
            bad[one] = (self.cols[lo[one]] == cols[one]).all(axis=1)
            for i in np.flatnonzero(hi - lo > 1):       # a hash shared by stored tuples
                bad[i] = (self.cols[lo[i]:hi[i]] == cols[i]).all(axis=1).any()
        order = np.lexsort((*cols.T[::-1], h))           # by hash, then every column; stable
        hs, cs = h[order], cols[order]
        again = (hs[1:] == hs[:-1]) & (cs[1:] == cs[:-1]).all(axis=1)
        bad[order[1:][again]] = True
        return keyed, h, cols, bad

    def _remember(self, h: np.ndarray, cols: np.ndarray, new: np.ndarray) -> None:
        """Insert the keys of rows `new` (distinct, none seen before) into the sorted set."""
        new = new[np.argsort(h[new], kind="stable")]
        self.reserve(len(self.seen) + len(new))
        pos = np.searchsorted(self.seen, h[new], side="right")
        self.seen = np.insert(self.seen, pos, h[new])      # the old array is freed here
        if self.cols is not None:
            self.cols = np.insert(self.cols, pos, cols[new], axis=0)

    def warm(self, rows):
        t = rows.get(self.table)
        if t is not None and t.num_rows:
            _, h, cols, bad = self._repeats(t)
            self._remember(h, cols, np.flatnonzero(~bad))

    def judge(self, rows, world, retired):
        t = rows.get(self.table)
        if t is None or not t.num_rows:
            return 0
        keyed, h, cols, bad = self._repeats(t)
        n_bad = int(bad.sum())
        if n_bad:
            j = int(np.argmax(bad))
            self._fail(self.table, _cite(t, int(keyed[j])),
                       f"{self.key[0]} {int(cols[j, 0])} seen before", n_bad)
        self._remember(h, cols, np.flatnonzero(~bad))
        return len(keyed)


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
        if float(np.abs(amt.astype(np.float64)).sum()) >= _SAFE:   # sums may leave int64:
            deb, cre = deb.astype(object), cre.astype(object)        # add them exactly
        d = np.add.reduceat(deb[order], starts)
        c = np.add.reduceat(cre[order], starts)
        first_row = np.minimum.reduceat(order, starts)
        bad = np.asarray(d != c, bool)
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


_CANON = ("event_time", "lamport", "partition_id", "seq")
_I64_MAX = np.iinfo(np.int64).max


def _ints(t: pa.Table, name: str, idx: np.ndarray) -> np.ndarray:
    return np.asarray(_column(t, name)[0], np.int64)[idx]


def _first_canonical(c: dict[str, np.ndarray], among: np.ndarray, tag: str) -> int:
    """The entry of `among` that comes first in canonical order (`tag` breaks exact ties)."""
    sub = np.lexsort(tuple(c[k][among] for k in (tag, *_CANON[::-1])))
    return int(among[sub[0]])


def _concat(parts: list[dict[str, np.ndarray]], names: tuple[str, ...]) -> dict[str, np.ndarray]:
    return {k: (np.concatenate([p[k] for p in parts]) if parts else np.zeros(0, np.int64))
            for k in names}


class _SumLe(_Law):
    """Per `by` key, over the merged stream of both tables in canonical order (a right-side
    row runs first at an exact tie of the canonical key), the running Σ lhs stays ≤ the running
    Σ rhs at every lhs row. Sums are carried across steps as sorted key arrays; warm-up rows feed
    them unjudged. Rows with a null key are skipped; a null amount adds 0 and an lhs row with a
    null amount is not judged."""

    _COLS = ("key", "amt", "side", "judged", "row", *_CANON)

    def __init__(self, cdef: Any, lhs: tuple[str, str], rhs: tuple[str, str], by: str):
        super().__init__(cdef)
        self.lhs, self.rhs, self.by = lhs, rhs, by
        self.tables = (lhs[0], rhs[0])
        self.skeys = np.zeros(0, np.int64)
        self.lsum = np.zeros(0, np.int64)
        self.rsum = np.zeros(0, np.int64)

    def keys(self) -> int:
        return len(self.skeys)

    def _stream(self, rows: dict[str, pa.Table]) -> dict[str, np.ndarray]:
        parts = []
        for side, (table, col) in ((0, self.rhs), (1, self.lhs)):
            t = rows.get(table)
            if t is None or not t.num_rows:
                continue
            k, keyed = row_keys(t, self.by)
            v, valid = _column(t, col)
            v = np.asarray(v, np.int64)
            ok = np.ones(t.num_rows, bool) if valid is None else valid
            n = len(keyed)
            parts.append({"key": k[keyed], "amt": np.where(ok, v, 0)[keyed],
                          "side": np.full(n, side, np.int64),
                          "judged": ok[keyed].astype(np.int64) * side, "row": keyed,
                          **{c: _ints(t, c, keyed) for c in _CANON}})
        s = _concat(parts, self._COLS)
        order = np.lexsort((s["side"], *(s[c] for c in _CANON[::-1]), s["key"]))
        return {k: v[order] for k, v in s.items()}

    def _run(self, rows: dict[str, pa.Table]):
        """The step's stream sorted by (key, canonical order), the running sums at each entry
        (carried bases included); the carried sums are advanced past the step."""
        s = self._stream(rows)
        n = len(s["key"])
        if not n:
            return s, s["amt"], s["amt"]
        ks = s["key"]
        change = np.ones(n, bool)
        change[1:] = ks[1:] != ks[:-1]
        gid = np.cumsum(change) - 1
        starts = np.flatnonzero(change)
        ends = np.append(starts[1:], n) - 1
        uniq = ks[starts]
        pos = np.minimum(np.searchsorted(self.skeys, uniq), max(len(self.skeys) - 1, 0))
        hit = self.skeys[pos] == uniq if len(self.skeys) else np.zeros(len(uniq), bool)
        self.reserve(len(self.skeys) + int((~hit).sum()))
        running = []
        for sums, side in ((self.lsum, 1), (self.rsum, 0)):
            a = np.where(s["side"] == side, s["amt"], 0)
            base = np.where(hit, sums[pos] if len(sums) else 0, 0)
            exact = (float(np.abs(base.astype(np.float64)).max(initial=0))   # no abs(INT64_MIN)
                     + float(np.abs(a.astype(np.float64)).sum()))
            if exact >= _SAFE:                           # a per-key sum may leave int64
                a, base = a.astype(object), base.astype(object)
            c = np.cumsum(a)                             # a wrap of this global sum cancels
            r = c - (c - a)[starts][gid] + base[gid]     # out of the per-key differences
            if exact >= _SAFE:
                r = self._fit(r, ks, side)
            running.append(r)
        run_l, run_r = running
        lend, rend = run_l[ends], run_r[ends]
        if hit.any():                                    # carried keys: updated in place
            self.lsum[pos[hit]] = lend[hit]
            self.rsum[pos[hit]] = rend[hit]
        fresh = ~hit
        if fresh.any():                                  # new keys, sorted and absent:
            at = np.searchsorted(self.skeys, uniq[fresh])    # inserted, never re-sorted
            self.skeys = np.insert(self.skeys, at, uniq[fresh])
            self.lsum = np.insert(self.lsum, at, lend[fresh])
            self.rsum = np.insert(self.rsum, at, rend[fresh])
        return s, run_l, run_r

    def _fit(self, r: np.ndarray, ks: np.ndarray, side: int) -> np.ndarray:
        """Exact per-key running sums back to int64; `EngineError` when one leaves int64 (the
        sums are carried as int64, so the law cannot judge past that)."""
        out = (r > _I64_MAX) | (r < _I64_MIN)
        if out.any():
            i = int(np.argmax(out))
            col = ".".join(self.lhs if side == 1 else self.rhs)
            raise EngineError(f"law {self.id}: the running total of {col} for {self.by} "
                              f"{int(ks[i])} reaches {int(r[i])}, outside int64")
        return r.astype(np.int64)

    def warm(self, rows):
        self._run(rows)

    def judge(self, rows, world, retired):
        s, run_l, run_r = self._run(rows)
        bad = np.flatnonzero((s["judged"] == 1) & (run_l > run_r))
        if len(bad):
            i = _first_canonical(s, bad, "side")
            table = self.lhs[0]
            self._fail(table, _cite(rows[table], int(s["row"][i])),
                       f"{self.by} {int(s['key'][i])}: {'.'.join(self.lhs)} total "
                       f"{int(run_l[i])} exceeds {'.'.join(self.rhs)} total {int(run_r[i])}",
                       len(bad))
        return int(s["judged"].sum())


class _Resolved(_Law):
    """Every `event` row opens its key; the first later row (canonical order) of a `by` table
    with the same key closes it, if it comes at or before the deadline `opened_at + within`.
    An exported opening is judged once: resolved when closed, a violation (cited, then dropped)
    when the step whose end passes the deadline seals with it still open. Openings still open
    at `finish` are censored (deadline ≥ end) or violations. A warm-up opening is never judged,
    censored or cited: it is dropped when closed or at its deadline. An exported closing row
    that closes nothing open (a key never opened, already closed, or open no longer: past its
    deadline) is counted in `unmatched`; judging a close against the deadline, not against the
    step that holds it, keeps every count independent of step length. Rows with a null key
    are skipped."""

    _OPEN = ("key", "t", "deadline", "pid", "seq", "action", "warm")

    def __init__(self, cdef: Any, event: str, by: tuple[str, ...], key: str, within: str | None):
        from neorisk_simkit.spec.project import parse_duration

        super().__init__(cdef)
        self.event, self.by, self.key, self.within = event, tuple(dict.fromkeys(by)), key, within
        self.within_us = None if within is None else parse_duration(within)
        self.tables = (event, *self.by)
        self.unmatched = 0
        self.open = {k: np.zeros(0, np.int64) for k in self._OPEN}

    def keys(self) -> int:
        return len(self.open["key"])

    def _entries(self, t: pa.Table | None, tag: int) -> dict[str, np.ndarray] | None:
        if t is None or not t.num_rows:
            return None
        k, keyed = row_keys(t, self.key)
        e = {"key": k[keyed], "tag": np.full(len(keyed), tag, np.int64),
             "action": _ints(t, "action_id", keyed), **{c: _ints(t, c, keyed) for c in _CANON}}
        return e

    def _advance(self, rows: dict[str, pa.Table], t_end: int, exported: bool) -> int:
        """Open, close and expire this step's keys; returns the openings judged."""
        names = ("key", "tag", "action", *_CANON)
        new = _concat([e for e in [self._entries(rows.get(self.event), 1)] if e], names)
        closes = _concat([e for b in self.by if (e := self._entries(rows.get(b), 0))], names)
        n_new, n_cl = len(new["key"]), len(closes["key"])
        allr = {k: np.concatenate([new[k], closes[k]]) for k in names}
        order = np.lexsort((allr["tag"], *(allr[c] for c in _CANON[::-1])))
        rank = np.empty(len(order), np.int64)          # canonical position in this step; a row
        rank[order] = np.arange(len(order))            # closes before it opens (no self-close)
        new_order = np.argsort(rank[:n_new], kind="stable")
        dl = (new["event_time"] + self.within_us if self.within_us is not None
              else np.full(n_new, _I64_MAX, np.int64))
        o = self.open
        n_old = len(o["key"])
        n_op = n_old + n_new
        self.reserve(n_op)
        fresh = {"key": new["key"], "t": new["event_time"], "deadline": dl,
                 "pid": new["partition_id"], "seq": new["seq"], "action": new["action"]}
        fresh = {k: v[new_order] for k, v in fresh.items()}
        fresh["warm"] = np.full(n_new, 0 if exported else 1, np.int64)
        op = {}
        for k in self._OPEN:                             # one column at a time: the old one
            op[k] = np.concatenate([o[k], fresh[k]])     # is freed before the next grows
            o[k] = None
        nrank = rank[:n_new][new_order]                  # an old opening ranks -1
        match = np.zeros(n_op, bool)
        used = 0
        if n_cl and n_op:
            crank = rank[n_new:]
            corder = np.lexsort((crank, closes["key"]))
            ck, cr, ct = closes["key"][corder], crank[corder], closes["event_time"][corder]
            uniq, gid = np.unique(ck, return_inverse=True)
            m = np.int64(len(order) + 2)
            comp = gid.astype(np.int64) * m + (cr + 1)
            closed = np.zeros(n_cl, bool)
            for lo in range(0, n_op, RESOLVED_CHUNK):    # bounded matching workspace
                hi = min(lo + RESOLVED_CHUNK, n_op)
                key = op["key"][lo:hi]
                orank = np.full(hi - lo, -1, np.int64)
                if hi > n_old:
                    s0 = max(lo, n_old)
                    orank[s0 - lo:] = nrank[s0 - n_old:hi - n_old]
                g = np.minimum(np.searchsorted(uniq, key), len(uniq) - 1)
                j = np.searchsorted(comp, g * m + (orank + 1), side="right")
                jj = np.minimum(j, n_cl - 1)
                mc = ((uniq[g] == key) & (j < n_cl) & (gid[jj] == g)
                      & (ct[jj] <= op["deadline"][lo:hi]))   # a close past the deadline is late
                match[lo:hi] = mc
                closed[jj[mc]] = True
            used = int(closed.sum())
        expired = ~match
        expired &= op["deadline"] < t_end
        live = op["warm"] == 0
        n_judged = int((live & (match | expired)).sum())
        live &= expired                                  # exported openings that expired
        n_bad = int(live.sum())
        first = int(np.argmax(live)) if n_bad else -1    # openings are kept in canonical order
        cite = None if first < 0 else {k: int(op[k][first]) for k in ("key", "t", "pid", "seq",
                                                                        "action")}
        del live
        match |= expired                                 # resolved or expired: dropped
        np.logical_not(match, out=match)
        del expired
        for k in self._OPEN:                             # filtered one column at a time
            op[k] = op[k][match]
        self.open = op
        if not exported:
            return 0
        self.unmatched += n_cl - used
        if n_bad:
            self._fail_open(cite, n_bad)
        return n_judged

    def _fail_open(self, cite: dict[str, int], n: int) -> None:
        self._fail(self.event, (cite["pid"], cite["seq"], cite["action"]),
                   f"{self.key} {cite['key']} opened at {cite['t']} not resolved "
                   f"within {self.within}", n)

    def warm(self, rows):
        self._advance(rows, self.t_end, exported=False)

    def judge(self, rows, world, retired):
        return self._advance(rows, self.t_end, exported=True)

    def finish(self, end_us: int) -> None:
        op = self.open
        live = op["warm"] == 0
        bad = np.flatnonzero(live & (op["deadline"] < end_us))
        self.censored += int((live & (op["deadline"] >= end_us)).sum())
        self.checked += len(bad)
        self.open = {k: v[:0] for k, v in op.items()}
        if len(bad):
            i = int(bad[0])
            self._fail_open({k: int(op[k][i]) for k in ("key", "t", "pid", "seq", "action")},
                            len(bad))

    def report(self) -> dict[str, Any]:
        return {**super().report(), "unmatched": self.unmatched}


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
        lhs, rhs, by = _event_table(plan, lw.arg("lhs")), _event_table(plan, lw.arg("rhs")), \
            lw.arg("by")
        for table, _ in (lhs, rhs):
            if not any(c.name == by for e in plan.events if e.name == table for c in e.cols):
                raise ValueError(f"check {cdef.id}: {table} has no column {by}")
        return _SumLe(cdef, lhs, rhs, by)
    if kind == "resolved":
        return _Resolved(cdef, lw.arg("event"), lw.arg("by"), lw.arg("key"), lw.arg("within"))
    raise ValueError(f"check {cdef.id}: unknown law {kind!r}")


# ---------------------------------------------------------------------------- the book
class LawBook:
    """Every declared check of `plan`, evaluated step by step (see the module docstring)."""

    def __init__(self, plan: Any, *, max_keys: int):
        self.max_keys = int(max_keys)
        self.cap_bytes = checker_state_bytes(plan, self.max_keys)   # `checker_state`
        self._laws = [_build(plan, c) for c in plan.checks]
        for law in self._laws:
            law.reserve = lambda keys, law=law: self._reserve(law, keys)
        self.end_us: int | None = None

    def _reserve(self, law: _Law, keys: int) -> None:
        need = law_peak_bytes(law.lw, keys) + sum(o.keys() * o.key_bytes for o in self._laws
                                                  if o is not law)
        if need > self.cap_bytes:
            raise CapExceeded("checker_state", self.cap_bytes, need)

    @property
    def tables(self) -> frozenset[str]:
        """The event and posting tables any check reads."""
        return frozenset(t for law in self._laws for t in law.tables)

    @property
    def keys(self) -> int:
        """Keys carried across steps by every check."""
        return sum(law.keys() for law in self._laws)

    @property
    def state_bytes(self) -> int:
        """Bytes of carried state, charged against `checker_state`."""
        return sum(law.keys() * law.key_bytes for law in self._laws)

    def step(self, sealed: Any, world: Any, *, exported: bool = True) -> dict[str, int]:
        """Feed one sealed step; returns the values checked per check this step."""
        out: dict[str, int] = {}
        for law in self._laws:
            law.t_end = int(sealed.t_end)
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
        return out

    def finish(self, end_us: int) -> None:
        """The run ended at `end_us`: `resolved` openings still open are censored (deadline at
        or after the end) or violations, in declaration order."""
        self.end_us = int(end_us)
        for law in self._laws:
            law.finish(self.end_us)

    def report(self) -> dict[str, dict]:
        return {law.id: law.report() for law in self._laws}
