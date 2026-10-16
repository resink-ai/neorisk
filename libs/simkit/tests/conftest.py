import dataclasses
from pathlib import Path

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
