"""A small `bench`-profile run (blurred ring) shared by the label-discovery tests.

Registered from each test module that uses it with `pytest_plugins = ["discover_fixture"]`.
"""

from pathlib import Path

import pytest

ECOM = Path(__file__).resolve().parents[3] / "examples" / "ecommerce"


@pytest.fixture(scope="session")
def discover_run(tmp_path_factory):
    from datagen.cli import main

    run = tmp_path_factory.mktemp("discover") / "run"
    assert main(["run", str(ECOM), "--profile", "bench", "--overlay", "bounty_hunters",
                 "--set", "users=4000", "--set", "run.days=40", "--seed", "3",
                 "--out", str(run)]) == 0
    return run


@pytest.fixture(scope="session")
def world_truth(discover_run):
    from bench.discover.world import load

    return load(discover_run, seed=3)
