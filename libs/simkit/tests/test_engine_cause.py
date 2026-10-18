"""D80: cause_id = event_id of the first record of the nearest record-emitting commit in a
command's causal chain."""

import polars as pl
from conftest import FIXTURES

from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events


def _ev(tmp_path, overrides=(), **eng):
    res = run_to_dataset(FIXTURES / "causes", "sample", list(overrides), out_dir=tmp_path / "r",
                         threads=2, engine_overrides=eng or None)
    return read_events(res.out_dir)


def _links(ev):
    opened = ev["opened"].select("acct_id", pl.col("event_id").alias("opened_id"))
    asked = ev["asked"].select(pl.col("who").alias("acct_id"), pl.col("event_id").alias("asked_id"),
                               pl.col("cause_id").alias("asked_cause"))
    j = opened.join(asked, on="acct_id")
    j = j.join(ev["answered"].select("acct_id", pl.col("cause_id").alias("answered_cause")),
               on="acct_id")
    j = j.join(ev["ticked"].select("acct_id", pl.col("cause_id").alias("ticked_cause")),
               on="acct_id")
    assert j.drop_nulls().height == j.height                    # a null never compares equal
    return j


def test_causes_follow_requests_responses_and_silent_commits(tmp_path):
    ev = _ev(tmp_path)
    assert ev["opened"]["cause_id"].null_count() == 2          # population starts: no cause
    j = _links(ev)
    assert j.height == 2
    assert (j["asked_cause"] == j["opened_id"]).all()          # request -> shard record
    assert (j["answered_cause"] == j["asked_id"]).all()         # response -> owner record
    assert (j["ticked_cause"] == j["opened_id"]).all()          # through C_TICK, 2 steps later


def test_label_rows_get_a_cause_but_are_never_one(tmp_path):
    res = run_to_dataset(FIXTURES / "causes", "sample", [], out_dir=tmp_path / "r", threads=2)
    marks = pl.read_parquet(sorted((res.out_dir / "labels" / "marks").rglob("*.parquet")))
    ev = read_events(res.out_dir)
    opened = set(ev["opened"]["event_id"])
    assert set(marks["cause_id"]) <= opened                     # F-17: a label has a cause
    causes = set(pl.concat([t.select("cause_id") for t in ev.values()])["cause_id"].drop_nulls())
    assert not causes & set(marks["event_id"])                  # ... and is never a cause


def test_causal_links_do_not_depend_on_step_length(tmp_path):
    for i, step in enumerate((3_600_000_000, 6 * 3_600_000_000)):
        j = _links(_ev(tmp_path / str(i), step_us=step))
        assert (j["asked_cause"] == j["opened_id"]).all()
        assert (j["ticked_cause"] == j["opened_id"]).all()


def test_a_cause_in_warm_up_is_null(tmp_path):
    ev = _ev(tmp_path, ["run.warmup=1h"])                       # opened/asked/answered in warm-up
    assert ev["opened"].height == 0
    assert ev["ticked"]["cause_id"].null_count() == ev["ticked"].height == 2
