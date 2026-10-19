"""Session fixtures with legacy fraud exports (D87) shared by the bench tests.

Registered from each bench test module that uses them with `pytest_plugins = ["legacy_fixture"]`
(no second conftest.py, F-39). Building one compiles the ecommerce + bounty_hunters module
(45-90 min cold, seconds warm; `users` and `run.span` are runtime config, so both sizes share
one cached module), so every test that requests one is marked `large`.
"""

from pathlib import Path

import pytest

EX = Path(__file__).resolve().parents[3] / "examples" / "ecommerce"


def _export(tmp: Path, overrides: list[str]) -> Path:
    from datagen.cli import main
    from neorisk_simkit.io.dataset import run_to_dataset

    res = run_to_dataset(EX, "legacy", overrides, out_dir=tmp / "run", threads=4)
    out = tmp / "fraud"
    assert main(["export", str(res.out_dir), "--legacy-fraud", "--out", str(out)]) == 0
    return out


@pytest.fixture(scope="session")
def legacy_dir(tmp_path_factory):
    return _export(tmp_path_factory.mktemp("legacy"), ["users=2000", "run.span=30d"])


@pytest.fixture(scope="session")
def legacy_compare_dir(tmp_path_factory):
    """A larger export for `bench compare` (about 2x the rows): on `legacy_dir` the ANNs get
    2-3 mini-batches per epoch and their test AUC is seed noise."""
    return _export(tmp_path_factory.mktemp("legacy_cmp"), ["users=4000", "run.span=45d"])
