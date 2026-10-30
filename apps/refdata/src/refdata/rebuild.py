"""Rebuild: a dataset → the source tables, through `specs/views.sql` (DuckDB).

Every Parquet file of the dataset is a DuckDB view named after its file (`order_placed`,
`customers`, ...). Each `-- table: <name>` block yields one source table with exactly the
source's columns; the result is written to a SQLite file created with the source's own DDL.
DuckDB runs in UTC, so `ts - INTERVAL` never crosses the host's daylight-saving shifts.
"""

from __future__ import annotations

import sqlite3
from decimal import Decimal
from pathlib import Path

import duckdb

from refdata.blocks import parse_blocks
from refdata.source import load_source


def _value(v):
    return float(v) if isinstance(v, Decimal) else v


def rebuild(dataset: Path, project: Path, src_db: Path, out: Path, *,
            force: bool = False) -> Path:
    dataset, project, src_db, out = Path(dataset), Path(project), Path(src_db), Path(out)
    if not src_db.exists():
        raise FileNotFoundError(f"{src_db} not found; run: uv run refdata fetch")
    if out.exists():
        if not force:
            raise FileExistsError(f"{out} exists; pass --force to overwrite")
        out.unlink()
    src = load_source(project)
    blocks = {b.name: b for b in parse_blocks((project / "specs" / "views.sql").read_text(),
                                              {"table"})}
    if set(blocks) != set(src.tables):
        raise ValueError(f"views.sql blocks differ from source.toml: missing "
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

    duck = duckdb.connect()
    duck.execute("SET TimeZone = 'UTC'")           # interval arithmetic never in host time
    for group in ("events", "entities"):
        for f in sorted((dataset / group).glob("*.parquet")):
            duck.execute(f"CREATE VIEW \"{f.stem}\" AS SELECT * FROM read_parquet('{f}')")

    out.parent.mkdir(parents=True, exist_ok=True)
    dst = sqlite3.connect(out)
    try:
        for name, sql in ddl.items():
            rel = duck.sql(blocks[name].sql)
            got, want = rel.columns, cols[name]
            if sorted(got) != sorted(want):
                raise ValueError(f"view {name!r}: missing columns "
                                 f"{sorted(set(want) - set(got))}, unexpected "
                                 f"{sorted(set(got) - set(want))}")
            dst.execute(sql)
            ph = ", ".join("?" * len(want))
            sel = ", ".join(f'"{c}"' for c in want)
            rows = duck.sql(f"SELECT {sel} FROM ({blocks[name].sql.rstrip().rstrip(';')})")
            with dst:
                while batch := rows.fetchmany(50_000):
                    dst.executemany(f'INSERT INTO "{name}" VALUES ({ph})',
                                    [tuple(_value(v) for v in r) for r in batch])
    except BaseException:
        dst.close()
        out.unlink(missing_ok=True)
        raise
    dst.close()
    return out
