"""sakila on every engine (see conftest.engine_run for what each one needs)."""

import pytest


@pytest.mark.parametrize("engine", ["duckdb", "spark", "flink", "flink-stream"])
def test_engine(engine_run, engine):
    rep = engine_run("sakila", engine)
    assert len(rep["tables"]) == 16
