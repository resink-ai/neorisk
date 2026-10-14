import json

import polars as pl
import pytest

from datagen.cli import main


def test_generate_writes_dataset(tmp_path):
    out = tmp_path / "fraud"
    rc = main(
        [
            "generate",
            "--scenario",
            "fraud",
            "--n-events",
            "3000",
            "--seed",
            "3",
            "--span-days",
            "30",
            "--out",
            str(out),
        ]
    )
    assert rc == 0
    ev = pl.read_parquet(out / "events.parquet")
    meta = json.loads((out / "meta.json").read_text())
    assert ev.height == 3000 and meta["scenario"] == "fraud" and meta["seed"] == 3
    assert not set(meta["golden_columns"]) & set(ev.columns)


def test_unknown_scenario_exits_nonzero(tmp_path):
    with pytest.raises(SystemExit) as e:
        main(["generate", "--scenario", "nope", "--out", str(tmp_path)])
    assert e.value.code != 0
