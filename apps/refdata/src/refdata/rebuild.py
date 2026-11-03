"""Rebuild: an event log → the source tables, through `specs/build.sql` (DuckDB).

The log is decoded into one DuckDB view per event type and entity (`order_placed`,
`customers`, ...; see `refdata.logviews`), and nothing but the log is read. Each `-- table: <name>` block yields one source table with exactly the
source's columns; the result is written to a SQLite file created with the source's own DDL.
DuckDB runs in UTC, so `ts - INTERVAL` never crosses the host's daylight-saving shifts.
"""

from __future__ import annotations

import sqlite3
from decimal import Decimal
from pathlib import Path

import duckdb

from refdata.blocks import parse_blocks
from refdata.logviews import attach_log
from refdata.source import load_source


def _value(v):
    return float(v) if isinstance(v, Decimal) else v


def build_tables(log_root: Path, project: Path) -> tuple[duckdb.DuckDBPyConnection,
                                                         dict[str, str]]:
    """A UTC DuckDB connection with the log attached, and each table's `build.sql` block."""
    duck = duckdb.connect()
    duck.execute("SET TimeZone = 'UTC'")           # interval arithmetic never in host time
    attach_log(duck, Path(log_root))
    blocks = parse_blocks((Path(project) / "specs" / "build.sql").read_text(), {"table"})
    return duck, {b.name: b.sql for b in blocks}


def rebuild(log_root: Path, project: Path, src_db: Path, out: Path, *,
            force: bool = False) -> Path:
    log_root, project, src_db, out = Path(log_root), Path(project), Path(src_db), Path(out)
    if not src_db.exists():
        raise FileNotFoundError(f"{src_db} not found; run: uv run refdata fetch")
    if out.exists():
        if not force:
            raise FileExistsError(f"{out} exists; pass --force to overwrite")
        out.unlink()
    src = load_source(project)
    duck, blocks = build_tables(log_root, project)
    if set(blocks) != set(src.tables):
        raise ValueError(f"build.sql blocks differ from source.toml: missing "
                         f"{sorted(set(src.tables) - set(blocks))}, extra "
                         f"{sorted(set(blocks) - set(src.tables))}")

    con = sqlite3.connect(f"file:{src_db}?mode=ro", uri=True)
    ddl = {n: s for n, s in con.execute(
        "SELECT name, sql FROM sqlite_master WHERE type = 'table' ORDER BY rowid")
        if n in src.tables}
    cols = {n: [r[1] for r in con.execute(f'PRAGMA table_info("{n}")')] for n in ddl}
    con.close()
    if set(ddl) != set(src.tables):
        raise ValueError(f"tables not in {src_db.name}: {sorted(set(src.tables) - set(ddl))}")

    out.parent.mkdir(parents=True, exist_ok=True)
    dst = sqlite3.connect(out)
    try:
        fill_sqlite(duck, blocks, ddl, cols, dst)
    except BaseException:
        dst.close()
        out.unlink(missing_ok=True)
        raise
    dst.close()
    return out


def fill_sqlite(duck: duckdb.DuckDBPyConnection, blocks: dict[str, str], ddl: dict[str, str],
                cols: dict[str, list[str]], dst: sqlite3.Connection) -> None:
    """Create each table from its source DDL (so column affinity applies, as in the source)
    and fill it from its `build.sql` block, in the source's column order."""
    for name, sql in ddl.items():
        fill_table(duck, name, blocks[name], sql, cols[name], dst)


def fill_table(duck: duckdb.DuckDBPyConnection, name: str, block: str, ddl: str,
               want: list[str], dst: sqlite3.Connection) -> None:
    rel = duck.sql(block)
    got = rel.columns
    if sorted(got) != sorted(want):
        raise ValueError(f"view {name!r}: missing columns "
                         f"{sorted(set(want) - set(got))}, unexpected "
                         f"{sorted(set(got) - set(want))}")
    dst.execute(ddl)
    ph = ", ".join("?" * len(want))
    sel = ", ".join(f'"{c}"' for c in want)
    rows = duck.sql(f"SELECT {sel} FROM ({block.rstrip().rstrip(';')})")
    with dst:
        while batch := rows.fetchmany(50_000):
            dst.executemany(f'INSERT INTO "{name}" VALUES ({ph})',
                            [tuple(_value(v) for v in r) for r in batch])
