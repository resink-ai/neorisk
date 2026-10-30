"""Compare a source SQLite file with a rebuilt one.

Tables: each source table (from source.toml) must equal the rebuilt one as a multiset of
rows. INTEGER and REAL compare by numeric value; text, blobs and NULL compare exactly (so
NULL, '' and '\\N' are three values). No tolerance.

Queries: every `specs/queries/*.sql` runs on both files. Results compare as lists when the
query has a top-level ORDER BY, else as multisets; float cells compare with relative
tolerance 1e-9, since a different row order may change a float sum in its last bits.
"""

from __future__ import annotations

import math
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from refdata.source import load_source

SAMPLE = 5
REL_TOL = 1e-9


@dataclass
class TableDiff:
    name: str
    rows_source: int
    rows_rebuilt: int
    missing: list[tuple] = field(default_factory=list)
    extra: list[tuple] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.missing and not self.extra


@dataclass
class QueryDiff:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class Report:
    tables: list[TableDiff]
    queries: list[QueryDiff]

    @property
    def ok(self) -> bool:
        return all(t.ok for t in self.tables) and all(q.ok for q in self.queries)

    def to_json(self) -> dict:
        return {"ok": self.ok,
                "tables": [{"name": t.name, "rows_source": t.rows_source,
                            "rows_rebuilt": t.rows_rebuilt, "ok": t.ok,
                            "missing": [list(map(repr, r)) for r in t.missing],
                            "extra": [list(map(repr, r)) for r in t.extra]}
                           for t in self.tables],
                "queries": [{"name": q.name, "ok": q.ok, "detail": q.detail}
                            for q in self.queries]}


def norm(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return float(v)
    return v


def _sample(c: Counter, key_idx: list[int]) -> list[tuple]:
    rows = list(c.elements())
    rows.sort(key=lambda r: tuple(repr(r[i]) for i in key_idx) if key_idx else ())
    return rows[:SAMPLE]


def _table(name: str, key: list[str], a: sqlite3.Connection,
           b: sqlite3.Connection) -> TableDiff:
    cols = [r[1] for r in a.execute(f'PRAGMA table_info("{name}")')]
    sel = ", ".join(f'"{c}"' for c in cols)
    ca = Counter(tuple(norm(v) for v in r) for r in a.execute(f'SELECT {sel} FROM "{name}"'))
    try:
        cb = Counter(tuple(norm(v) for v in r)
                     for r in b.execute(f'SELECT {sel} FROM "{name}"'))
    except sqlite3.Error as e:
        return TableDiff(name, ca.total(), 0, [(f"rebuilt table unreadable: {e}",)])
    key_idx = [cols.index(k) for k in key if k in cols]
    return TableDiff(name, ca.total(), cb.total(), _sample(ca - cb, key_idx),
                     _sample(cb - ca, key_idx))


def _ordered(sql: str) -> bool:
    tail = sql[sql.rfind(")") + 1:] if ")" in sql else sql
    return re.search(r"\border\s+by\b", tail, re.IGNORECASE) is not None


def _cell_eq(x, y) -> bool:
    if isinstance(x, float) and isinstance(y, float):
        return math.isclose(x, y, rel_tol=REL_TOL) or (math.isnan(x) and math.isnan(y))
    return x == y


def _rows_eq(ra: list[tuple], rb: list[tuple], ordered: bool) -> bool:
    if len(ra) != len(rb):
        return False
    if not ordered:
        key = lambda r: tuple((v is None, type(v).__name__, v if not isinstance(v, float)
                               else round(v, 6)) for v in r)
        ra, rb = sorted(ra, key=key), sorted(rb, key=key)
    return all(len(x) == len(y) and all(_cell_eq(u, v) for u, v in zip(x, y, strict=True))
               for x, y in zip(ra, rb, strict=True))


def _query(name: str, sql: str, a: sqlite3.Connection, b: sqlite3.Connection) -> QueryDiff:
    try:
        ra = [tuple(norm(v) for v in r) for r in a.execute(sql)]
    except sqlite3.Error as e:
        return QueryDiff(name, False, f"fails on the source: {e}")
    try:
        rb = [tuple(norm(v) for v in r) for r in b.execute(sql)]
    except sqlite3.Error as e:
        return QueryDiff(name, False, f"fails on the rebuilt file: {e}")
    if _rows_eq(ra, rb, _ordered(sql)):
        return QueryDiff(name, True, f"{len(ra)} rows")
    return QueryDiff(name, False, f"source {ra[:3]} ({len(ra)} rows) != rebuilt {rb[:3]} "
                                  f"({len(rb)} rows)")


def compare(src_db: Path, rebuilt_db: Path, project: Path) -> Report:
    src = load_source(Path(project))
    a = sqlite3.connect(f"file:{src_db}?mode=ro", uri=True)
    b = sqlite3.connect(f"file:{rebuilt_db}?mode=ro", uri=True)
    try:
        tables = [_table(n, k, a, b) for n, k in src.tables.items()]
        qdir = Path(project) / "specs" / "queries"
        queries = [_query(f.stem, f.read_text(), a, b) for f in sorted(qdir.glob("*.sql"))]
    finally:
        a.close()
        b.close()
    return Report(tables, queries)
