"""Session fixtures with legacy fraud exports shared by the bench tests.

Registered from each bench test module that uses them with `pytest_plugins = ["legacy_fixture"]`.
"""

from pathlib import Path

import pytest

ECOM = Path(__file__).resolve().parents[3] / "examples" / "ecommerce"


def _export(tmp: Path, users: int, days: int) -> Path:
    from datagen.cli import main

    run, out = tmp / "run", tmp / "fraud"
    assert main(["run", str(ECOM), "--profile", "legacy", "--overlay", "bounty_hunters",
                 "--set", f"users={users}", "--set", f"run.days={days}", "--out", str(run)]) == 0
    assert main(["export", str(run), "--legacy-fraud", "--out", str(out)]) == 0
    return out


@pytest.fixture(scope="session")
def legacy_dir(tmp_path_factory):
    return _export(tmp_path_factory.mktemp("legacy"), 2000, 30)


@pytest.fixture(scope="session")
def legacy_compare_dir(tmp_path_factory):
    """A larger export for `bench compare`, so the ANNs get enough mini-batches."""
    return _export(tmp_path_factory.mktemp("legacy_cmp"), 4000, 45)
