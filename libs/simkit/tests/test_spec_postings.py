"""D45: postings are typed tables apart from events: own folder, own counts, never replayed."""

import json

import pytest
from conftest import FIXTURES

from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events, read_postings
from neorisk_simkit.io.replay.planner import ReplayError, ReplayRequest, plan_replay
from neorisk_simkit.io.schema.schema_json import load_schema
from neorisk_simkit.io.step_index import read_step_index
from neorisk_simkit.spec.pack import Pack, PackError
from neorisk_simkit.spec.types import amount


@pytest.fixture(scope="module")
def ds(tmp_path_factory):
    return run_to_dataset(FIXTURES / "ledger", "sample",
                          out_dir=tmp_path_factory.mktemp("ledger") / "run", threads=1).out_dir


def test_postings_are_written_apart(ds):
    m = json.loads((ds / "manifest.json").read_text())
    opened = m["counts"]["opened"]
    assert opened > 0 and "entry" not in m["counts"]
    assert m["posting_counts"] == {"entry": 2 * opened}
    assert sorted(ds.glob("postings/entry/date=*/step-*.parquet"))
    assert not (ds / "events" / "entry").exists()
    stats = json.loads((ds / "run_stats.json").read_text())
    assert stats["exported_events"] == opened


def test_postings_read_back_in_canonical_order(ds):
    p = read_postings(ds)["entry"]
    assert p.columns[:8] == ["event_id", "event_type", "event_time", "lamport", "partition_id",
                             "seq", "cause_id", "action_id"]
    assert p.height == 2 * read_events(ds)["opened"].height
    assert p.sort("event_time", "lamport", "partition_id", "seq").equals(p)
    assert set(p["side"]) == {"debit", "credit"}


def test_schema_index_and_replay_leave_postings_out(ds):
    kinds = {t["name"]: t["kind"] for t in load_schema(ds)["tables"]}
    assert kinds["entry"] == "posting" and kinds["opened"] == "event"
    assert "rows__entry" not in read_step_index(ds).column_names
    assert "entry" not in read_events(ds)
    with pytest.raises(ReplayError):
        plan_replay(ds, ReplayRequest(types=("entry",)))


def test_postings_share_the_record_namespace():
    p = Pack("x", 1)
    p.table("t", key="t_id", mutable=True, cols={"a": amount(asset="USD")})
    p.owner("t", table="t", max_live=1)
    p.event("e", owner="t", cols={"a": amount(asset="USD")})
    with pytest.raises(PackError, match="duplicate"):
        p.postings("e", owner="t", cols={"a": amount(asset="USD")})
