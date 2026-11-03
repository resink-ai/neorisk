"""Build and verify a Spider2 dataset: the event log in, the source tables out.

`build_spider2` ingests the source into a simkit dataset (an internal stage), writes the log,
writes every source table to `results/` and every saved query's answer to
`expected/queries/`, then the manifest. `verify` reads only the built version and the specs:
it decodes the log, runs `build.sql`, loads the tables into SQLite with the source's DDL (so
affinity applies as in the source) and compares them, and the query answers, exactly.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
from pathlib import Path

import pyarrow.parquet as pq

from dataset.config import DatasetConfig
from dataset.manifest import files_of, lock_diff, lock_of, recipe_sha256, sha256, write_json
from dataset.names import resolve
from dataset.tables import TableResult, answer_table, compare_tables, detect_mixed, sqlite_table
from neorisk_simkit.io import read
from neorisk_simkit.io.log import LogError, write_log
from neorisk_simkit.io.writer import WRITER
from refdata.compare import _ordered, open_indexed
from refdata.ingest import IngestError, ingest, owners
from refdata.rebuild import build_tables, fill_sqlite
from refdata.source import load_source


class BuildError(ValueError):
    pass


def _write_parquet(table, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path, compression="zstd", compression_level=3,
                   row_group_size=WRITER["row_group_size"])


def _queries(cfg: DatasetConfig) -> list[Path]:
    return sorted((cfg.dir / "specs" / "queries").glob("*.sql"))


def _index(con: sqlite3.Connection, keys: dict[str, list[str]]) -> None:
    for t, cols in keys.items():
        if cols:
            con.execute(f'CREATE INDEX "dataset_{t}" ON "{t}" ('
                        + ", ".join(f'"{c}"' for c in cols) + ")")


def _results(cfg: DatasetConfig, db: Path, out: Path) -> dict:
    src = load_source(cfg.dir)
    unknown = set(cfg.mixed) - set(src.tables)
    if unknown:
        raise BuildError(f"{cfg.name}: [results.mixed] names tables not in source.toml: "
                         f"{sorted(unknown)}")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    meta: dict = {"tables": {}, "queries": {}}
    try:
        ddl = dict(con.execute("SELECT name, sql FROM sqlite_master WHERE type = 'table'"))
        for t, key in src.tables.items():
            if t not in ddl:
                raise BuildError(f"{cfg.name}: table {t!r} is not in {db.name}")
            mixed, want = detect_mixed(con, t), set(cfg.mixed.get(t, []))
            if mixed != want:
                raise BuildError(f"{cfg.name}: table {t!r} has mixed columns {sorted(mixed)}, "
                                 f"but dataset.toml declares {sorted(want)}")
            tbl = sqlite_table(con, t, mixed)
            _write_parquet(tbl, out / "results" / f"{t}.parquet")
            meta["tables"][t] = {"ddl": ddl[t], "key": key, "mixed": sorted(mixed),
                                 "columns": [{"name": f.name, "type": str(f.type)}
                                             for f in tbl.schema]}
    finally:
        con.close()
    qfiles = _queries(cfg)
    if qfiles:
        mem = open_indexed(db, src.tables)
        try:
            for f in qfiles:
                sql = f.read_text()
                _write_parquet(answer_table(mem, sql), out / "expected" / "queries" /
                               f"{f.stem}.parquet")
                meta["queries"][f.stem] = {"ordered": _ordered(sql)}
        finally:
            mem.close()
    write_json(out / "schema" / "results.json", meta)
    return meta


def build_spider2(cfg: DatasetConfig, db: Path, *, record: bool = False) -> dict:
    db = Path(db)
    if not db.exists():
        raise FileNotFoundError(f"{db} not found; run: uv run refdata fetch")
    final = resolve(f"{cfg.name}/{cfg.version}")
    tmp = final.parent / f".{cfg.version}.tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        with tempfile.TemporaryDirectory() as work:
            try:
                ds = ingest(cfg.dir, db, Path(work) / "ds")
                write_log(read(ds), tmp, owners=owners(cfg.dir))
            except (IngestError, LogError) as e:
                raise BuildError(f"{cfg.name}: {e}") from e
        meta = _results(cfg, db, tmp)
        files = files_of(tmp)
        log_rows = sum(v["rows"] for k, v in files.items() if k.startswith("log/"))
        manifest = {"name": cfg.name, "version": cfg.version, "kind": cfg.kind,
                    "recipe_sha256": recipe_sha256(cfg.dir), "source_sha256": sha256(db),
                    "counts": {"log": log_rows,
                               **{f"results/{t}": files[f"results/{t}.parquet"]["rows"]
                                  for t in meta["tables"]},
                               "queries": len(meta["queries"])},
                    "files": files}
        lock_path = cfg.dir / f"{cfg.version}.lock.json"
        if lock_path.exists():
            diff = lock_diff(json.loads(lock_path.read_text()), manifest)
            if diff:
                raise BuildError(f"{cfg.name} {cfg.version}: the build differs from "
                                 f"{lock_path.name} in {diff[:10]}; changed output needs a "
                                 f"new version")
        elif record:
            write_json(lock_path, lock_of(manifest))
        write_json(tmp / "manifest.json", manifest)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    shutil.rmtree(final, ignore_errors=True)
    tmp.rename(final)
    return manifest


def _failed(name: str, detail: str, rows: int = 0) -> TableResult:
    return TableResult(name, False, rows, 0, detail=detail)


def verify(cfg: DatasetConfig) -> dict:
    root = resolve(f"{cfg.name}/{cfg.version}")
    if not (root / "manifest.json").exists():
        raise FileNotFoundError(f"{cfg.name} {cfg.version} is not built under {root.parent}; "
                                f"run: uv run dataset build {cfg.name}")
    meta = json.loads((root / "schema" / "results.json").read_text())
    duck, blocks = build_tables(root, cfg.dir)
    if set(blocks) != set(meta["tables"]):
        raise ValueError(f"build.sql blocks differ from the results: missing "
                         f"{sorted(set(meta['tables']) - set(blocks))}, extra "
                         f"{sorted(set(blocks) - set(meta['tables']))}")
    mem = sqlite3.connect(":memory:")
    try:
        cols = {t: [c["name"] for c in m["columns"]] for t, m in meta["tables"].items()}
        fill_sqlite(duck, blocks, {t: m["ddl"] for t, m in meta["tables"].items()}, cols, mem)
        tables = [compare_tables(t, pq.read_table(root / "results" / f"{t}.parquet"),
                                 sqlite_table(mem, t, set(m["mixed"])))
                  for t, m in meta["tables"].items()]
        _index(mem, {t: m["key"] for t, m in meta["tables"].items()})
        queries = []
        for f in _queries(cfg):
            if f.stem not in meta["queries"]:
                queries.append(_failed(f.stem, "no expected answer; rebuild the dataset"))
                continue
            want = pq.read_table(root / "expected" / "queries" / f"{f.stem}.parquet")
            try:
                got = answer_table(mem, f.read_text())
            except sqlite3.Error as e:
                queries.append(_failed(f.stem, f"fails on the rebuilt tables: {e}",
                                       want.num_rows))
                continue
            queries.append(compare_tables(f.stem, want, got,
                                          ordered=meta["queries"][f.stem]["ordered"]))
    finally:
        mem.close()
    return {"ok": all(r.ok for r in tables + queries), "tables": tables, "queries": queries}
