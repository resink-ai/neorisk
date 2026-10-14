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
            "--bad-rate",
            "0.05",
            "--out",
            str(out),
        ]
    )
    assert rc == 0
    ev = pl.read_parquet(out / "events.parquet")
    meta = json.loads((out / "meta.json").read_text())
    assert ev.height == 3000 and meta["scenario"] == "fraud" and meta["seed"] == 3
    assert not set(meta["golden_columns"]) & set(ev.columns)
    assert (out / "golden.parquet").exists()
    golden = pl.read_parquet(out / "golden.parquet")
    assert golden.height == 3000 and "invr_bonus_sum_30d" in golden.columns
    assert meta["config"]["target_bad_rate"] == 0.05
    assert 0.03 < meta["bad_rate"] < 0.07


def test_unknown_scenario_exits_nonzero(tmp_path):
    with pytest.raises(SystemExit) as e:
        main(["generate", "--scenario", "nope", "--out", str(tmp_path)])
    assert e.value.code != 0
