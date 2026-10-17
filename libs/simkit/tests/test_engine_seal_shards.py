"""D38: seal remaps handles held by shards: `ref` state, `Local` refs, payload column 9."""

from conftest import FIXTURES, make_run

from neorisk_simkit import std
from neorisk_simkit.engine.world import World
from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events
from neorisk_simkit.spec.caps import compute_caps, hidden_bytes, row_bytes


def _run(tmp_path, threads=1, fixture="holder", **engine):
    r = run_to_dataset(FIXTURES / fixture, "sample", out_dir=tmp_path / f"{fixture}-t{threads}",
                       threads=threads, engine_overrides=engine or None)
    return r, read_events(r.out_dir)


def test_ref_state_starts_null():
    w = World.build(make_run("holder"), threads=1)
    assert w.state["desk"][0].tolist() == [std.NULL]


def test_shard_state_and_local_refs_survive_the_seal(tmp_path):
    _, ev = _run(tmp_path)
    opened, noted, echoed = ev["opened"], ev["noted"], ev["echoed"]
    assert opened.height == noted.height == echoed.height == 3
    assert set(noted["ticket_id"]) == set(opened["ticket_id"])
    # the desk echoes two hours (two steps) after it stored the provisional ticket handles
    assert (echoed["event_time"].dt.hour() == 2).all() and (noted["event_time"].dt.hour() == 0).all()
    assert set(echoed["last_id"]) == {noted["ticket_id"][-1]}      # state `last`: last noted
    assert set(echoed["first_id"]) == {noted["ticket_id"][0]}     # Local `seen[0]`: first noted


def test_queued_sender_is_remapped(tmp_path):
    _, ev = _run(tmp_path)
    heard, opened = ev["heard"], ev["opened"]
    assert heard.height == 3 and (heard["event_time"].dt.hour() == 2).all()
    pairs = dict(zip(opened["ticket_id"], opened["pay_id"], strict=True))
    for ticket, sender in zip(heard["ticket_id"], heard["sender_id"], strict=True):
        assert pairs[ticket] == sender                 # cmd.sender = the pay owner's final id


def test_threads_do_not_change_holder(tmp_path):
    from conftest import event_dicts
    a, _ = _run(tmp_path, threads=1)
    b, _ = _run(tmp_path, threads=4, parallel_min_partitions=1)   # 7 partitions run in parallel
    assert event_dicts(a.out_dir) == event_dicts(b.out_dir)


def test_shard_locals_count_as_live_state():
    run = make_run("holder")
    plan = run.plan
    caps = {c.name: c for c in compute_caps(run)}
    hid = hidden_bytes(plan)
    owners = (3 * (row_bytes(plan.table("acct").cols) + hid)
              + 3 * (row_bytes(plan.table("pay").cols) + hid))
    desk = 1 * (hid + 8) + 1 * (8 * 4 + 4)            # state `last` + Local seen[4], n
    assert caps["live_partition_state"].hard_bytes == owners + desk


def test_per_item_ref_state_starts_null():
    w = World.build(make_run("rack"), threads=1)
    assert w.offs["rack"].tolist() == [0, 2, 4]
    assert w.state["rack"][0].tolist() == [std.NULL] * 4


def test_per_item_ref_state_survives_the_seal(tmp_path):
    _, ev = _run(tmp_path, fixture="rack")
    opened, stowed, echoed = ev["opened"], ev["stowed"], ev["echoed"]
    assert opened.height == stowed.height == echoed.height == 1
    assert (stowed["event_time"].dt.hour() == 0).all() and (echoed["event_time"].dt.hour() == 2).all()
    assert echoed["partition_id"].to_list() == stowed["partition_id"].to_list()
    assert [pid & ((1 << 56) - 1) for pid in stowed["partition_id"]] == [1]       # rack 1 only
    assert echoed["held_id"].to_list() == stowed["ticket_id"].to_list() == opened["ticket_id"].to_list()
