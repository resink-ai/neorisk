"""The grader every engine shares: an engine's tables against the dataset's `results/`.

Spider2 tables go through SQLite with the source's DDL, exactly as `dataset verify` does, so
affinity treats every engine alike. Synthetic tables are typed: each column is read as its
expected type when that keeps its value (int widths, decimals, float32, a naive timestamp
taken as UTC), and fails when it would change kind (text into a number, a fraction into an
integer). Then `compare_tables` decides, with the one rule for every engine.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from dataset.tables import TableResult, compare_tables, sqlite_table
from refdata.rebuild import fill_table


def _failed(name: str, detail: str, rows: int = 0) -> TableResult:
    return TableResult(name, False, rows, 0, detail=detail)


def _kind(t: pa.DataType) -> str:
    if pa.types.is_integer(t) or pa.types.is_floating(t) or pa.types.is_decimal(t):
        return "number"
    if pa.types.is_string(t) or pa.types.is_large_string(t):
        return "string"
    if pa.types.is_boolean(t):
        return "bool"
    if pa.types.is_date(t):
        return "date"
    if pa.types.is_timestamp(t):
        return "timestamp"
    if pa.types.is_null(t):
        return "null"
    return str(t)


def data_files(d: Path) -> list[str]:
    """The data files under an engine's table folder (engines leave `.staging`, `_SUCCESS`
    and `.crc` files beside them)."""
    files = sorted(str(p) for p in d.rglob("*") if p.is_file()
                   and not any(part.startswith((".", "_")) for part in p.relative_to(d).parts)
                   and not p.name.endswith(".crc")) if d.is_dir() else []
    if not files:
        raise FileNotFoundError("the engine wrote no output")
    return files


def read_output(d: Path) -> pa.Table:
    return pa.concat_tables([pq.read_table(f) for f in data_files(d)], promote_options="default")


def _conform(col: pa.ChunkedArray, want: pa.DataType) -> pa.ChunkedArray:
    have = col.type
    if have == want:
        return col
    k, kw = _kind(have), _kind(want)
    if k != kw and k != "null":
        raise TypeError(f"is {have}, expected {want}")
    if pa.types.is_timestamp(have) and pa.types.is_timestamp(want) and have.tz is None:
        col = col.cast(pa.timestamp(have.unit, "UTC"))   # a naive time is UTC wall time
    try:
        return col.cast(want, safe=True)
    except (pa.ArrowInvalid, pa.ArrowNotImplementedError) as e:
        raise TypeError(f"is {have} and cannot be read as {want}: {e}") from None


def typed(name: str, expected: pa.Table, out: Path) -> TableResult:
    """A synthetic table: the engine's output conformed to the expected types, compared."""
    try:
        got = read_output(out)
    except (FileNotFoundError, pa.ArrowException) as e:
        return _failed(name, str(e), expected.num_rows)
    have = set(got.column_names)
    cols, names = [], []
    for f in expected.schema:
        if f.name not in have:
            continue
        try:
            cols.append(_conform(got.column(f.name), f.type))
        except TypeError as e:
            return _failed(name, f"column {f.name} {e}", expected.num_rows)
        names.append(f.name)
    extra = [c for c in got.column_names if c not in set(expected.column_names)]
    for c in extra:
        cols.append(got.column(c))
        names.append(c)
    return compare_tables(name, expected, pa.Table.from_arrays(cols, names=names),
                          extended=True)


def sqlite_graded(name: str, expected: pa.Table, out: Path, m: dict, exact: set[str],
                  mem: sqlite3.Connection, duck: duckdb.DuckDBPyConnection) -> TableResult:
    """A Spider2 table: the engine's output loaded with the source DDL, then compared."""
    try:
        files = data_files(out)
    except FileNotFoundError as e:
        return _failed(name, str(e), expected.num_rows)
    gen = set(m.get("generated", []))
    block = f"SELECT * FROM read_parquet({files!r})"
    try:
        fill_table(duck, name, block, m["ddl"],
                   [c["name"] for c in m["columns"] if c["name"] not in gen], mem)
        got = sqlite_table(mem, name, set(m["mixed"]))
    except (sqlite3.Error, duckdb.Error, pa.ArrowException, ValueError, TypeError) as e:
        return _failed(name, f"cannot be loaded: {type(e).__name__}: {e}", expected.num_rows)
    return compare_tables(name, expected, got, exact=exact)


def grade(job, meta: dict, errors: dict[str, str], engine_name: str) -> list[TableResult]:
    from dataset.engines import port_file
    cfg = job.cfg
    owner = {t: (m.get("design") or "build") for t, m in meta["tables"].items()}
    results: list[TableResult] = []
    mem = sqlite3.connect(":memory:")
    duck = duckdb.connect()
    try:
        for t, m in meta["tables"].items():
            want = pq.read_table(job.root / "results" / f"{t}.parquet")
            stem = owner[t]
            if t not in job.blocks.get(stem, {}):
                f = port_file(cfg, engine_name, stem)
                results.append(_failed(t, f"no port block in {f.relative_to(cfg.dir)}",
                                       want.num_rows))
            elif t in errors:
                results.append(_failed(t, errors[t], want.num_rows))
            elif cfg.kind == "synthetic":
                results.append(typed(t, want, job.table_dir(t)))
            else:
                results.append(sqlite_graded(t, want, job.table_dir(t), m,
                                             set(cfg.exact.get(t, [])), mem, duck))
        for stem, blocks in job.blocks.items():
            extra = sorted(set(blocks) - {t for t in meta["tables"] if owner[t] == stem})
            if extra:
                results.append(_failed(stem, f"blocks for tables not in the results: {extra}"))
    finally:
        mem.close()
        duck.close()
    return results
