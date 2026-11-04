"""Ingest: a source SQLite database → a simkit dataset, through `specs/ingest.sql`.

Rules (the dataset contract `rebuild` and `datagen check` rely on):

1. Blocks run in file order on the read-only source, which has `iso_time(text, fmt)`
   (`strptime(text, fmt)` as ISO text, NULL for NULL). Each block ends in an ORDER BY, so its
   row order is deterministic.
2. An entity block yields the pack's columns except the key, including `ext_id` (the source
   id, unique), and optionally `created_at`; without it, `created_at` is the dataset's first
   event time. The key is the 1-based row number in `ext_id` order.
3. An event block yields `event_time`, the event's pack columns and, with `ord=<col>`, that
   column; `owner=<col>` is required. A `ref(T)` column yields the source id, mapped through
   `T.ext_id` to T's key (entity blocks too); an unmatched id is an error.
4. `ts` columns are ISO text `YYYY-MM-DD HH:MM:SS[.ffffff]`, read as UTC; `amount`, `i64` and
   `i32` columns are integers (minor units for money); a null in a non-`opt` column is an error.
5. Events sort stably by (event_time, ord or 0, block position, owner, block row). `seq` is the
   1-based position, `event_id = seq`, `partition_id` the dense rank of (owner column, owner
   value), `cause_id` null and `action_id` 0.
6. The dataset holds events/, entities/, empty labels/ and cases/, schema/schema.json and a
   manifest whose provenance is {"source": "ingest", "file", "sha256", "project",
   "pack_revision"} (so `datagen check` can tell the specs changed since).
7. Every pack table has exactly one block, and every block a pack table.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from neorisk_simkit.io.writer import WRITER, _sha, _write
from neorisk_simkit.project import load_project
from neorisk_simkit.schema import schema_json
from neorisk_simkit.spec.types import COMMON, LType, polars_type
from refdata.blocks import Block, parse_blocks
from refdata.source import load_source

ORDER_BY = re.compile(r"\border\s+by\b[^()]*;?\s*$", re.IGNORECASE | re.DOTALL)
TS_FORMAT = "%Y-%m-%d %H:%M:%S%.f"
CASES = {"partition_id": pl.Int64, "kind": pl.String, "cohort": pl.String, "depth": pl.Int32,
         "created_at": pl.Datetime("us", "UTC"), "retired_at": pl.Datetime("us", "UTC"),
         "steps": pl.Int64, "censored": pl.Boolean}


class IngestError(Exception):
    pass


def _iso_time(text: str | None, fmt: str) -> str | None:
    return None if text is None else datetime.strptime(text, fmt).isoformat(" ")


def connect_ro(db: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.create_function("iso_time", 2, _iso_time, deterministic=True)
    return con


def _query(con: sqlite3.Connection, b: Block) -> tuple[list[str], list[tuple]]:
    if not ORDER_BY.search(b.sql):
        raise IngestError(f"block {b.name!r}: must end in an ORDER BY (deterministic order)")
    try:
        cur = con.execute(b.sql)
    except sqlite3.Error as e:
        raise IngestError(f"block {b.name!r}: {e}") from e
    return [d[0] for d in cur.description], cur.fetchall()


def _series(block: str, name: str, t: LType, values: list) -> pl.Series:
    try:
        if t.kind == "ts":
            s = (pl.Series(name, values, dtype=pl.String)
                 .str.strptime(pl.Datetime("us"), TS_FORMAT).dt.replace_time_zone("UTC"))
        elif t.kind == "f64":
            s = pl.Series(name, values, dtype=pl.Float64, strict=False)
        elif t.kind == "cat":
            s = pl.Series(name, values, dtype=pl.String).cast(polars_type(t))
        else:
            s = pl.Series(name, values, dtype=polars_type(t))
    except Exception as e:                           # polars raises several kinds
        raise IngestError(f"block {block!r}, column {name!r} ({t.kind}): {e}") from e
    if not t.nullable and s.null_count():
        raise IngestError(f"block {block!r}, column {name!r}: {s.null_count()} nulls "
                          f"in a non-opt column")
    return s


def _columns(b: Block, got: list[str], want: list[str], optional: set[str]) -> None:
    missing, extra = set(want) - set(got), set(got) - set(want) - optional
    if missing or extra:
        raise IngestError(f"block {b.name!r}: missing columns {sorted(missing)}, "
                          f"unexpected {sorted(extra)}")


def _map_refs(b: Block, name: str, values: list, keys: dict[str, int]) -> list:
    out, bad = [], []
    for v in values:
        if v is None:
            out.append(None)
            continue
        k = keys.get(str(v))
        if k is None:
            bad.append(str(v))
        out.append(k)
    if bad:
        raise IngestError(f"block {b.name!r}, column {name!r}: {len(bad)} values with no "
                          f"entity, e.g. {sorted(set(bad))[:3]}")
    return out


def _empty(schema: dict[str, pl.DataType]) -> pl.DataFrame:
    return pl.DataFrame(schema=schema)


def owners(project: Path) -> dict[str, str]:
    """Each event block's `owner=` column, from `specs/ingest.sql`: the log's entity key."""
    blocks = parse_blocks((Path(project) / "specs" / "ingest.sql").read_text(),
                          {"event", "entity"})
    return {b.name: b.opts["owner"] for b in blocks if b.kind == "event" and "owner" in b.opts}


def ingest(project: Path, db: Path, out: Path, *, force: bool = False) -> Path:
    project, db, out = Path(project), Path(db), Path(out)
    if not db.exists():
        raise FileNotFoundError(f"{db} not found; run: uv run refdata fetch")
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        if not force:
            raise FileExistsError(f"{out} exists; pass --force to overwrite")
        if not _is_ingested(out):
            raise FileExistsError(f"{out} is not a refdata dataset; refusing to delete it")
    src = load_source(project)
    pr = load_project(project)
    plan = pr.plan(pr.settings(None, [], []).overlays)
    blocks = parse_blocks((project / "specs" / "ingest.sql").read_text(), {"event", "entity"})
    want = {("event", n) for n in plan.events} | {("entity", n) for n in plan.entities}
    have = {(b.kind, b.name) for b in blocks}
    if want != have:
        raise IngestError(f"ingest.sql blocks differ from the pack: missing "
                          f"{sorted(n for _, n in want - have)}, extra "
                          f"{sorted(n for _, n in have - want)}")

    con = connect_ro(db)
    raw_ent: dict[str, tuple[Block, list[str], list[tuple]]] = {}
    raw_ev: list[tuple[Block, list[str], list[tuple]]] = []
    for b in blocks:
        cols, rows = _query(con, b)
        (raw_ev.append((b, cols, rows)) if b.kind == "event" else
         raw_ent.__setitem__(b.name, (b, cols, rows)))
    con.close()

    # entities: key = row number in ext_id order
    keymaps: dict[str, dict[str, int]] = {}
    ent_cols: dict[str, dict[str, list]] = {}
    for name, (b, cols, rows) in raw_ent.items():
        t = plan.entities[name]
        _columns(b, cols, list(t.cols), {"created_at"})
        data = {c: [r[i] for r in rows] for i, c in enumerate(cols)}
        if "ext_id" not in t.cols:
            raise IngestError(f"entity {name!r} has no ext_id column in the pack")
        ext = [None if v is None else str(v) for v in data["ext_id"]]
        if len(set(ext)) != len(ext) or None in ext:
            raise IngestError(f"block {name!r}: ext_id is not unique and non-null")
        order = sorted(range(len(ext)), key=ext.__getitem__)
        keymaps[name] = {ext[i]: k for k, i in enumerate(order, 1)}
        ent_cols[name] = {c: [data[c][i] for i in order] for c in data}
        ent_cols[name]["ext_id"] = [ext[i] for i in order]
    for name, data in ent_cols.items():              # refs between entities, once keys exist
        for c, lt in plan.entities[name].cols.items():
            if lt.kind == "ref":
                data[c] = _map_refs(raw_ent[name][0], c, data[c], keymaps[lt.target])

    # events
    frames: dict[str, pl.DataFrame] = {}
    sort_parts = []
    for pos, (b, cols, rows) in enumerate(raw_ev):
        t = plan.events[b.name]
        owner, ord_ = b.opts.get("owner"), b.opts.get("ord")
        if not owner or owner not in t.cols:
            raise IngestError(f"block {b.name!r}: owner= must name one of its columns")
        _columns(b, cols, ["event_time", *t.cols], {ord_} if ord_ else set())
        data = {c: [r[i] for r in rows] for i, c in enumerate(cols)}
        for c, lt in t.cols.items():
            if lt.kind == "ref":
                data[c] = _map_refs(b, c, data[c], keymaps[lt.target])
        df = pl.DataFrame([_series(b.name, "event_time", COMMON["event_time"],
                                   data["event_time"])]
                          + [_series(b.name, c, lt, data[c]) for c, lt in t.cols.items()])
        frames[b.name] = df
        sort_parts.append(pl.DataFrame({
            "event_time": df["event_time"],
            "ord": pl.Series(data[ord_] if ord_ else [0] * len(rows), dtype=pl.Int64,
                             strict=False).fill_null(0),
            "blk": pl.Series([pos] * len(rows), dtype=pl.Int64),
            "owner": pl.Series([f"{owner}={v}" for v in df[owner].to_list()], dtype=pl.String),
            "row": pl.Series(range(len(rows)), dtype=pl.Int64),
        }))
    order = (pl.concat(sort_parts).sort(["event_time", "ord", "blk", "owner", "row"],
                                        maintain_order=True)
             .with_row_index("seq", offset=1)
             .with_columns(pl.col("seq").cast(pl.Int64),
                           partition_id=pl.col("owner").rank("dense").cast(pl.Int64)))
    first = order["event_time"].min() if order.height else datetime(2000, 1, 1, tzinfo=UTC)
    last = order["event_time"].max() if order.height else first

    events = {}
    for pos, (b, _, _) in enumerate(raw_ev):
        o = order.filter(pl.col("blk") == pos).sort("row")
        df = frames[b.name].with_columns(
            event_id=o["seq"], event_type=pl.lit(b.name), seq=o["seq"],
            partition_id=o["partition_id"], cause_id=pl.lit(None, pl.Int64),
            action_id=pl.lit(0, pl.Int32))
        cols = plan.events[b.name].columns()
        events[b.name] = (df.select([pl.col(c).cast(polars_type(lt)) for c, lt in cols.items()])
                          .sort("seq"))

    entities = {}
    for name, data in ent_cols.items():
        t = plan.entities[name]
        n = len(data["ext_id"])
        created = (_series(name, "created_at", COMMON["event_time"], data["created_at"])
                   if "created_at" in data else pl.Series("created_at", [first] * n,
                                                          dtype=pl.Datetime("us", "UTC")))
        df = pl.DataFrame([pl.Series(t.key, range(1, n + 1), dtype=pl.Int64), created]
                          + [_series(name, c, lt, data[c]) for c, lt in t.cols.items()])
        entities[name] = df
    # the run window spans every time in the dataset, entity creations included
    times = [t for df in entities.values() for t in (df["created_at"].min(),
                                                     df["created_at"].max()) if t is not None]
    first, last = min([first, *times]), max([last, *times])

    # write
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    files = []
    for group, frs in (("events", events), ("entities", entities)):
        for name, df in frs.items():
            p = out / group / f"{name}.parquet"
            _write(df, p)
            files.append(p)
    schema = schema_json.build(plan)
    lab = {c: polars_type(lt) for c, lt in schema_json.LABELS.items()}
    for p, sch in ((out / "labels" / "labels.parquet", lab), (out / "cases" / "cases.parquet",
                                                               CASES)):
        _write(_empty(sch), p)
        files.append(p)
    sp = out / "schema" / "schema.json"
    sp.parent.mkdir()
    sp.write_text(schema_json.dumps(schema))
    files.append(sp)
    days = max((last - first).total_seconds() / 86400, 1e-6)
    manifest = {
        "pack": plan.name, "schema_version": plan.pack.schema_version, "overlays": {},
        "provenance": {"source": "ingest", "file": src.file, "sha256": _file_sha(db),
                       "project": pr.name, "pack_revision": pr.revision()},
        "seed": 0, "config": {},
        "run": {"start": first.isoformat(), "days": days, "seed": 0},
        "writer": WRITER,
        "counts": {**{f"events/{k}": v.height for k, v in events.items()},
                   **{f"entities/{k}": v.height for k, v in entities.items()},
                   "labels": 0, "cases": 0},
        "checks": [], "files": {str(p.relative_to(out)): _sha(p) for p in sorted(files)},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return out


def _is_ingested(out: Path) -> bool:
    try:
        m = json.loads((out / "manifest.json").read_text())
    except (OSError, ValueError):
        return False
    return m.get("provenance", {}).get("source") == "ingest"


def _file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
