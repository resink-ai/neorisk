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
