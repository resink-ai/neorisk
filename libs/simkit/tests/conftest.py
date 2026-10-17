import dataclasses
from pathlib import Path

import numpy as np
import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_project():
    def get(name: str) -> Path:
        path = FIXTURES / name
        assert (path / "datagen.toml").exists(), path
        return path
    return get


def make_run(name, overrides=(), **engine):
    from neorisk_simkit.spec.project import load_project, resolve_run  # lazy: conftest loads first

    run = resolve_run(load_project(FIXTURES / name), "sample", list(overrides))
    if engine:
        run = dataclasses.replace(run, engine=dataclasses.replace(run.engine, **engine))
    return run


def dataset_tree(d: Path) -> dict[str, bytes]:
    """Every file of a dataset except run_stats.json (not part of replay identity), by path."""
    return {p.relative_to(d).as_posix(): p.read_bytes() for p in sorted(d.rglob("*"))
            if p.is_file() and p.name != "run_stats.json"}


def records_of(world, table):
    """All records of one event table held by a World, in canonical order (flushes slabs)."""
    world.flush_all()
    parts = [c.records[table] for chunks in world.chunks for c in chunks
             if table in c.records and len(c.records[table]["time"])]
    if not parts:
        return {"time": np.array([], np.int64)}
    cols = {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}
    order = np.lexsort((cols["seq"], cols["pid"], cols["lamport"], cols["time"]))
    return {k: v[order] for k, v in cols.items()}


def event_dicts(d: Path) -> dict[str, list[dict]]:
    """Every event table of a dataset as row dicts, keyed by type, in canonical order."""
    from neorisk_simkit.io.read import read_events  # lazy: conftest loads before io exists

    return {k: v.to_dicts() for k, v in sorted(read_events(d).items())}


KEY = ["event_time", "lamport", "partition_id", "seq"]


def _plan_of(project: Path, overrides: list[str]):
    from neorisk_simkit.spec.project import load_project, resolve_run  # lazy: conftest loads first
    return resolve_run(load_project(project), "sample", list(overrides)).plan


def created_namespaces(project: Path, overrides: list[str]) -> frozenset[str]:
    """The ID namespaces the engine hands out at seal (creatable tables and `ids`): only their
    dense indices legitimately depend on step boundaries (D13)."""
    return frozenset(_plan_of(project, overrides).namespaces)


def created_owner_codes(project: Path, overrides: list[str],
                        created: frozenset[str]) -> frozenset[int]:
    """`ptype_code`s of owner types whose table is created: their `partition_id`s are renamed."""
    return frozenset(p.ptype_code for p in _plan_of(project, overrides).partitions
                     if p.kind == "owner" and p.table in created)


def canonicalize_ids(d: Path, created: frozenset[str],
                     owner_codes: frozenset[int] = frozenset()) -> dict[str, list[dict]]:
    """Rename every created ID namespace by first appearance in global canonical order and
    number events by their canonical position (D13); every other column is kept as is.

    With `owner_codes` (the `ptype_code`s of created owner types), the `partition_id` of a
    created owner is renamed too, and "canonical order" is replaced by an order that does not
    use `partition_id`: `(event_time, lamport, type, every other non-ID column)`. Spec §12 gives
    a created owner the dense index (hence `partition_id`, the canonical tiebreak) of its rank
    by creator `partition_id` in its creation step, so rows of different created owners that
    tie on `(event_time, lamport)` may change relative order with the step length; "identical
    logical records" then means equal records under this partition-free order. Each table's
    rows are returned in that order (`event_id` = position)."""
    import polars as pl

    from neorisk_simkit.io.read import read_events  # lazy: conftest loads before io exists
    from neorisk_simkit.io.schema.schema_json import load_schema

    schema, events = load_schema(d), read_events(d)
    refs = {t["name"]: {c["name"]: c["ref"] for c in t["columns"]
                        if c.get("ref") in created}
            for t in schema["tables"] if t["kind"] == "event"}
    out = {name: e.to_dicts() for name, e in events.items()}
    if owner_codes:
        ids = {"event_id", "partition_id"}

        def key(name: str, row: dict) -> tuple:
            rest = tuple((v is None, v) for c, v in sorted(row.items())
                         if c not in ids and c not in refs[name])
            return (row["event_time"], row["lamport"], name, rest)

        flat = sorted(((key(name, r), name, r) for name, rows in out.items() for r in rows),
                      key=lambda x: x[0])
        keys = [k for k, _, _ in flat]
        assert len(set(keys)) == len(keys), "partition-free order is ambiguous"
    else:
        merged = pl.concat([
            e.select(*KEY, pl.lit(name).alias("_t"), pl.int_range(pl.len()).alias("_i"))
            for name, e in events.items() if e.height], how="vertical").sort(KEY)
        order = {(t, i): n for n, (t, i) in enumerate(zip(merged["_t"], merged["_i"]))}
        flat = sorted(((order[(name, i)], name, r) for name, rows in out.items()
                       for i, r in enumerate(rows)), key=lambda x: x[0])
    rename: dict[str, dict[int, int]] = {}
    for pos, (_, name, row) in enumerate(flat):
        for col, ns in refs[name].items():
            v = row[col]
            if v is not None:
                row[col] = rename.setdefault(ns, {}).setdefault(v, len(rename[ns]))
        if row["partition_id"] >> 56 in owner_codes:
            p = rename.setdefault("partition", {})
            row["partition_id"] = p.setdefault(row["partition_id"], len(p))
        row["event_id"] = pos
    return {name: sorted(rows, key=lambda r: r["event_id"]) for name, rows in out.items()}
