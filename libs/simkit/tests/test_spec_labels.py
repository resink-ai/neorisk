"""D76: label records live in labels/, are counted apart and are never replayed."""

import json

import polars as pl
from conftest import FIXTURES

from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events


def test_labels_are_written_apart_and_counted(tmp_path):
    res = run_to_dataset(FIXTURES / "tagged", "sample", [], out_dir=tmp_path / "r", threads=1)
    d = res.out_dir
    m = json.loads((d / "manifest.json").read_text())
    assert m["label_counts"] == {"tags": 3}
    assert "tags" not in m["counts"] and m["counts"]["seen"] == 3
    tags = pl.read_parquet(sorted((d / "labels" / "tags").rglob("*.parquet")))
    assert tags.height == 3 and set(tags["role"]) == {"bad"}
    assert "tags" not in read_events(d)
    assert not (d / "events" / "tags").exists()
    schema = json.loads((d / "schema" / "schema.json").read_text())
    entry = next(t for t in schema["tables"] if t["name"] == "tags")
    assert "label" in entry.values()
    # labels are not replayable rows: not in the step index, nor in the run's row totals
    steps = pl.read_parquet(sorted((d / "_index").rglob("*.parquet")))
    assert "rows__tags" not in steps.columns and "rows__seen" in steps.columns
    assert steps["rows"].sum() == 3
    st = json.loads((d / "run_stats.json").read_text())
    assert st["rows"] == st["exported_events"] == 3


def test_laws_cannot_name_label_tables():
    import dataclasses

    from conftest import make_run

    from neorisk_simkit.spec import law
    from neorisk_simkit.spec.plan import CheckDef
    from neorisk_simkit.spec.validate import validate

    run = make_run("tagged")
    bad = dataclasses.replace(run, plan=dataclasses.replace(run.plan, checks=(
        CheckDef("chk.tags", law.at_most_once("tags", key="target_id"), True),)))
    assert "label table tags cannot be checked by a law" in " ".join(validate(bad).errors)


def test_law_paths_cannot_name_label_tables():
    import dataclasses

    from conftest import make_run

    from neorisk_simkit.spec import law
    from neorisk_simkit.spec.plan import CheckDef
    from neorisk_simkit.spec.validate import validate

    run = make_run("tagged")
    for lw in (law.never_negative("tags.label_available_at"),
               law.total_le("tags.label_available_at", 10)):
        bad = dataclasses.replace(run, plan=dataclasses.replace(run.plan, checks=(
            CheckDef("chk.tags", lw, True),)))
        assert "label table tags cannot be checked by a law" in " ".join(validate(bad).errors)
