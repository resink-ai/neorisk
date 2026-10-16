import json
import re

import polars as pl
import pyarrow as pa
import pyarrow.compute as pc
import pytest
from conftest import FIXTURES

from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events
from neorisk_simkit.io.replay.encode import row_dicts, to_jsonl
from neorisk_simkit.io.replay.planner import ReplayError, ReplayRequest, plan_replay
from neorisk_simkit.io.replay.reader import iter_batches

KEY = ["event_time", "lamport", "partition_id", "seq"]
TS = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z$")


@pytest.fixture(scope="module")
def ds(tmp_path_factory):
    r = run_to_dataset(FIXTURES / "mini", "sample", ["behavior.take_p=0.4", "engine.step='3h'"],
                       out_dir=tmp_path_factory.mktemp("rp") / "ds")
    return r.out_dir


def _keys(batches):
    """Canonical keys with event_time as int µs (ReplayRequest.t_from/t_to are int µs)."""
    out = []
    for b in batches:
        t = pc.cast(b.column("event_time"), pa.int64()).to_pylist()
        out.extend(zip(t, *(b.column(k).to_pylist() for k in KEY[1:])))
    return out


@pytest.fixture(scope="module")
def everything(ds):
    ev = read_events(ds)
    allk = pl.concat([v.select(pl.col("event_time").dt.epoch("us"), *KEY[1:])
                      for v in ev.values()]).sort(KEY)
    return [tuple(r) for r in allk.iter_rows()]


def test_full_replay_is_the_canonical_order(ds, everything):
    got = _keys(iter_batches(plan_replay(ds, ReplayRequest())))
    assert got == everything and got == sorted(got)


def test_first_and_last(ds, everything):
    p = plan_replay(ds, ReplayRequest(first=100))
    assert _keys(iter_batches(p)) == everything[:100]
    full = plan_replay(ds, ReplayRequest())
    list(iter_batches(full))
    assert p.files_opened < full.files_opened
    assert _keys(iter_batches(plan_replay(ds, ReplayRequest(last=100)))) == everything[-100:]


def test_time_window_and_types(ds, everything):
    lo, hi = everything[200][0], everything[400][0]
    got = _keys(iter_batches(plan_replay(ds, ReplayRequest(t_from=lo, t_to=hi))))
    assert got == [k for k in everything if lo <= k[0] < hi]
    p = plan_replay(ds, ReplayRequest(types=("took",)))
    rows = [r for b in iter_batches(p) for r in b.to_pylist()]
    assert rows and {r["event_type"] for r in rows} == {"took"}


def test_batches_are_bounded(ds):
    sizes = [b.num_rows for b in iter_batches(plan_replay(ds, ReplayRequest(batch_rows=50)))]
    assert max(sizes) <= 50 and sum(sizes) > 50


def test_empty_selections(ds, everything):
    end = everything[-1][0] + 1
    assert list(iter_batches(plan_replay(ds, ReplayRequest(t_from=end, t_to=end + 10)))) == []


def test_request_errors(ds):
    with pytest.raises(ReplayError, match="either --first or --last"):
        plan_replay(ds, ReplayRequest(first=1, last=1))
    with pytest.raises(ReplayError, match="unknown event type 'nope'"):
        plan_replay(ds, ReplayRequest(types=("nope",)))


def test_json_encoding(ds):
    p = plan_replay(ds, ReplayRequest(types=("ping", "took"), first=200))
    batch = next(iter_batches(p))
    rows = row_dicts(batch, p.doc)
    ping = next(r for r in rows if r["event_type"] == "ping")
    took = next(r for r in rows if r["event_type"] == "took")
    assert list(ping)[:8] == ["event_id", "event_type", "event_time", "lamport", "partition_id",
                              "seq", "cause_id", "action_id"]
    assert isinstance(ping["event_id"], str) and isinstance(ping["lamport"], str)
    assert isinstance(ping["seq"], int) and isinstance(ping["n"], int)
    assert TS.match(ping["event_time"]) and "note_id" in ping and "ok" not in ping
    assert took["ok"] in ("yes", "no") and "note_id" not in took
    nums = row_dicts(batch, p.doc, numbers=True)
    assert isinstance(nums[0]["event_id"], int)
    line = to_jsonl(rows[:1])
    assert json.loads(line) == rows[0] and line.endswith("\n")


def test_small_batches_keep_canonical_order_and_last_with_window(ds, everything):
    got = _keys(iter_batches(plan_replay(ds, ReplayRequest(batch_rows=7))))
    assert got == everything
    lo, hi = everything[100][0], everything[500][0]
    inside = [k for k in everything if lo <= k[0] < hi]
    p = plan_replay(ds, ReplayRequest(t_from=lo, t_to=hi, last=30, batch_rows=11))
    assert _keys(iter_batches(p)) == inside[-30:]
    p = plan_replay(ds, ReplayRequest(t_from=lo, first=30, types=("ping", "took")))
    assert [k[0] >= lo for k in _keys(iter_batches(p))] == [True] * 30


def test_empty_selections_and_bad_requests(ds, everything):
    assert list(iter_batches(plan_replay(ds, ReplayRequest(types=())))) == []
    far = everything[-1][0] + 1
    assert list(iter_batches(plan_replay(ds, ReplayRequest(t_from=far, last=5)))) == []
    assert list(iter_batches(plan_replay(ds, ReplayRequest(t_from=far, first=5)))) == []
    for bad, msg in ((ReplayRequest(first=0), "positive"), (ReplayRequest(last=-1), "positive"),
                     (ReplayRequest(t_from=5, t_to=5), "before"),
                     (ReplayRequest(batch_rows=65_537), "batch_rows")):
        with pytest.raises(ReplayError, match=msg):
            plan_replay(ds, bad)


def test_csv_and_table(ds):
    from neorisk_simkit.io.replay.encode import to_csv, to_table
    p = plan_replay(ds, ReplayRequest(types=("ping", "took"), first=5))
    batch = next(iter_batches(p))
    lines = to_csv(batch, p.doc, header=True).splitlines()
    assert lines[0].split(",")[:3] == ["event_id", "event_type", "event_time"] and len(lines) == 6
    assert to_csv(batch, p.doc, header=False).splitlines() == lines[1:]
    tab = to_table(row_dicts(batch, p.doc)).splitlines()
    assert tab[0].startswith("event_id") and len(tab) == 6
