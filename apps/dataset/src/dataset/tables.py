"""Results tables from SQLite, and the exact comparator every engine is graded with.

A results column has one Parquet type, from the storage classes it holds: only text is
string, only integers int64 (float64 under REAL affinity), any real float64. A column that
holds text together with numbers (`''` among integers, say) is *mixed*: it is stored as
SQLite's own `CAST(x AS TEXT)`.

Tables compare as multisets of rows (lists for an ordered query answer). Integers and floats
compare by value (62 == 62.0), text byte for byte, NULL only with NULL; float64 columns of
the expected table allow a relative tolerance of 1e-9.
"""

from __future__ import annotations

import math
import sqlite3
from collections import Counter
from dataclasses import dataclass, field

import pyarrow as pa

from refdata.compare import norm

REL_TOL = 1e-9
SAMPLE = 5
ARROW = {"int64": pa.int64(), "float64": pa.float64(), "string": pa.string()}


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def affinity(decl: str) -> str:
    """SQLite's column affinity rules (§3.1 of the datatype docs), in their order."""
    d = decl.upper()
    if "INT" in d:
        return "INTEGER"
    if any(s in d for s in ("CHAR", "CLOB", "TEXT")):
        return "TEXT"
    if "BLOB" in d or not d.strip():
        return "BLOB"
    if any(s in d for s in ("REAL", "FLOA", "DOUB")):
        return "REAL"
    return "NUMERIC"


def _decls(con: sqlite3.Connection, table: str) -> dict[str, str]:
    return {r[1]: r[2] or "" for r in con.execute(f"PRAGMA table_info({_q(table)})")}


def _classes(con: sqlite3.Connection, table: str, col: str) -> set[str]:
    return {r[0] for r in con.execute(f"SELECT DISTINCT typeof({_q(col)}) FROM {_q(table)}")}


def column_types(con: sqlite3.Connection, table: str) -> dict[str, str]:
    """Each column's results type, from the storage classes it holds (and REAL affinity):
    only text → string; any real, or REAL affinity → float64; only integers → int64; text
    together with numbers → string (a mixed column); nothing but NULL → by affinity."""
    out = {}
    for col, decl in _decls(con, table).items():
        aff, cls = affinity(decl), _classes(con, table, col) - {"null"}
        if "text" in cls or (not cls and aff in ("TEXT", "BLOB")):
            out[col] = "string"
        elif aff == "REAL" or "real" in cls:
            out[col] = "float64"
        else:
            out[col] = "int64"
    return out


def detect_mixed(con: sqlite3.Connection, table: str) -> set[str]:
    """Columns holding text together with numbers: they are stored as SQLite's own text."""
    mixed = set()
    for col in _decls(con, table):
        cls = _classes(con, table, col)
        if "blob" in cls:
            raise ValueError(f"{table}.{col} holds blob values; the contract has no blob type")
        if "text" in cls and cls & {"integer", "real"}:
            mixed.add(col)
    return mixed


def sqlite_table(con: sqlite3.Connection, table: str, mixed: set[str]) -> pa.Table:
    types = column_types(con, table)
    cols = list(types)
    sel = ", ".join(f"CAST({_q(c)} AS TEXT)" if c in mixed else _q(c) for c in cols)
    rows = con.execute(f"SELECT {sel} FROM {_q(table)} ORDER BY rowid").fetchall()
    arrays = []
    for i, c in enumerate(cols):
        t = "string" if c in mixed else types[c]
        vals = [r[i] for r in rows]
        if t == "float64":
            vals = [float(v) if v is not None else None for v in vals]
        arrays.append(pa.array(vals, ARROW[t]))
    return pa.Table.from_arrays(arrays, names=cols)


def _unique(names: list[str]) -> list[str]:
    seen: Counter = Counter()
    out = []
    for n in names:
        seen[n] += 1
        out.append(n if seen[n] == 1 else f"{n}__{seen[n]}")
    return out


def answer_table(con: sqlite3.Connection, sql: str) -> pa.Table:
    """A saved query's answer, each column typed by its values (see the module doc)."""
    cur = con.execute(sql)
    names = _unique([d[0] for d in cur.description])
    rows = cur.fetchall()
    arrays = []
    for i in range(len(names)):
        vals = [r[i] for r in rows]
        kinds = {type(v) for v in vals if v is not None}
        if bytes in kinds:
            raise ValueError(f"answer column {names[i]!r} holds blob values")
        if not kinds or str in kinds:
            text = [v if v is None or isinstance(v, str)
                    else con.execute("SELECT CAST(? AS TEXT)", (v,)).fetchone()[0] for v in vals]
            arrays.append(pa.array(text, pa.string()))
        elif float in kinds:
            arrays.append(pa.array([None if v is None else float(v) for v in vals], pa.float64()))
        else:
            arrays.append(pa.array(vals, pa.int64()))
    return pa.Table.from_arrays(arrays, names=names)


@dataclass
class TableResult:
    name: str
    ok: bool
    rows_expected: int
    rows_got: int
    missing: list[tuple] = field(default_factory=list)
    extra: list[tuple] = field(default_factory=list)
    detail: str = ""

    def to_json(self) -> dict:
        return {"name": self.name, "ok": self.ok, "rows_expected": self.rows_expected,
                "rows_got": self.rows_got, "detail": self.detail,
                "missing": [list(map(repr, r)) for r in self.missing],
                "extra": [list(map(repr, r)) for r in self.extra]}


def _rows(t: pa.Table) -> list[tuple]:
    cols = [t.column(i).to_pylist() for i in range(t.num_columns)]
    return [tuple(norm(v) for v in r) for r in zip(*cols, strict=True)] if cols else []


def _cell_eq(x, y, is_float: bool) -> bool:
    if (is_float and isinstance(x, (int, float)) and isinstance(y, (int, float))
            and not isinstance(x, bool) and not isinstance(y, bool)):
        if isinstance(x, float) and isinstance(y, float) and math.isnan(x) and math.isnan(y):
            return True
        return math.isclose(x, y, rel_tol=REL_TOL)
    return x == y


def _row_eq(a: tuple, b: tuple, floats: list[bool]) -> bool:
    return all(_cell_eq(x, y, f) for x, y, f in zip(a, b, floats, strict=True))


def _key(r: tuple, floats: list[bool]):
    return tuple((v is None, type(v).__name__,
                  round(v, 6) if f and isinstance(v, float) else v) for v, f in zip(r, floats,
                                                                                  strict=True))


def _sample(rows: list[tuple]) -> list[tuple]:
    return sorted(rows, key=repr)[:SAMPLE]


def compare_tables(name: str, expected: pa.Table, got: pa.Table, *,
                   ordered: bool = False) -> TableResult:
    want, have = expected.column_names, got.column_names
    ne, ng = expected.num_rows, got.num_rows
    if sorted(want) != sorted(have):
        return TableResult(name, False, ne, ng, detail=(
            f"columns differ: missing {sorted(set(want) - set(have))}, "
            f"extra {sorted(set(have) - set(want))}"))
    bad = [f"{f.name}: {f.type}" for f in got.schema
           if not (pa.types.is_integer(f.type) or pa.types.is_floating(f.type)
                   or pa.types.is_string(f.type) or pa.types.is_large_string(f.type)
                   or pa.types.is_null(f.type))]
    if bad:
        return TableResult(name, False, ne, ng, detail=(
            f"column types outside the contract (int, float, string): {bad}"))
    got = got.select(want)
    floats = [pa.types.is_floating(f.type) for f in expected.schema]
    a, b = _rows(expected), _rows(got)
    if ordered:
        ok = len(a) == len(b) and all(_row_eq(x, y, floats) for x, y in zip(a, b, strict=False))
        bad = [i for i, (x, y) in enumerate(zip(a, b, strict=False))
               if not _row_eq(x, y, floats)]
        return TableResult(name, ok, ne, ng, [a[i] for i in bad[:SAMPLE]],
                           [b[i] for i in bad[:SAMPLE]],
                           "" if ok else f"first difference at row {bad[0] if bad else len(a)}")
    ca, cb = Counter(a), Counter(b)
    missing, extra = list((ca - cb).elements()), list((cb - ca).elements())
    if missing and len(missing) == len(extra) and any(floats):
        ms, es = sorted(missing, key=lambda r: _key(r, floats)), sorted(
            extra, key=lambda r: _key(r, floats))
        if all(_row_eq(x, y, floats) for x, y in zip(ms, es, strict=True)):
            missing, extra = [], []
    ok = not missing and not extra
    return TableResult(name, ok, ne, ng, _sample(missing), _sample(extra),
                       "" if ok else f"{len(missing)} rows missing, {len(extra)} extra")
