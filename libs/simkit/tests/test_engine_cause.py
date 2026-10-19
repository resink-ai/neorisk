"""D80: cause_id = event_id of the first record of the nearest record-emitting commit in a
command's causal chain."""

from collections import Counter

import polars as pl
from conftest import FIXTURES, event_dicts

from neorisk_simkit.engine.codegen import NEED_SWAP
from neorisk_simkit.engine.slabs import buffer_specs
from neorisk_simkit.engine.world import World
from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events
from neorisk_simkit.spec.project import load_project, resolve_run


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
    assert marks.height == 2                                    # not vacuous (review M3)
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


def test_a_full_commit_log_is_flushed_and_changes_nothing(tmp_path, monkeypatch):
    # Task 12 review M1: with every record, create and outbox buffer forced large and a 1 KB
    # slab, the 64-row commit log is what fills, so every swap is a commit-log flush
    # (codegen: `clog_n >= clog rows` -> NEED_SWAP; World._flush keeps a commit-only chunk)
    sets = ["users=2000"]
    plan = resolve_run(load_project(FIXTURES / "mini"), "sample", sets).plan
    big = {s.resource: 1_000_000 for s in buffer_specs(plan)} | {"requests": 1_000_000}
    swaps = Counter()
    real = World.handle_status

    def spy(self, worker, status):
        swaps[status] += 1
        return real(self, worker, status)

    monkeypatch.setattr(World, "handle_status", spy)
    a = event_dicts(run_to_dataset(FIXTURES / "mini", "sample", sets, out_dir=tmp_path / "a",
                                   threads=3).out_dir)
    n_plain = swaps[NEED_SWAP]
    swaps.clear()
    b = event_dicts(run_to_dataset(FIXTURES / "mini", "sample", sets, out_dir=tmp_path / "b",
                                   threads=3, engine_overrides={"slab_bytes": 1024,
                                                                "force_capacity": big}).out_dir)
    assert swaps[NEED_SWAP] > 100 * max(n_plain, 1)             # the log filled, again and again
    causes = [r["cause_id"] for rows in b.values() for r in rows]
    assert sum(c is not None for c in causes) > 10_000          # causes resolved through them
    assert b == a
