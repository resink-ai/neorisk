"""Session fixture `legacy_dir`: one legacy fraud export (D87) shared by the bench tests.

Registered from each bench test module that uses it with `pytest_plugins = ["legacy_fixture"]`
(no second conftest.py, F-39). Building it compiles the ecommerce + bounty_hunters module
(45-90 min cold, seconds warm), so every test that requests it is marked `large`.
"""

from pathlib import Path

import pytest

EX = Path(__file__).resolve().parents[3] / "examples" / "ecommerce"


@pytest.fixture(scope="session")
def legacy_dir(tmp_path_factory):
    from datagen.cli import main
    from neorisk_simkit.io.dataset import run_to_dataset

    tmp = tmp_path_factory.mktemp("legacy")
    res = run_to_dataset(EX, "legacy", ["users=2000", "run.span=30d"], out_dir=tmp / "run",
                         threads=4)
    out = tmp / "fraud"
    assert main(["export", str(res.out_dir), "--legacy-fraud", "--out", str(out)]) == 0
    return out
