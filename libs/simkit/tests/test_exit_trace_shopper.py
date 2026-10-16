"""Spec §07 exit test: the recurring-shopper trace, reproduced record by record."""

import json
from datetime import UTC, datetime

import polars as pl
import pytest
from conftest import FIXTURES

from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events


@pytest.fixture(scope="module")
def trace(tmp_path_factory):
    r = run_to_dataset(FIXTURES / "trace_shopper", "sample",
                       out_dir=tmp_path_factory.mktemp("trace") / "run", threads=1)
    ev = read_events(r.out_dir)
    rows = pl.concat([t.select("event_time", "lamport", "partition_id", "seq", "event_type")
                      for t in ev.values()]).sort("event_time", "lamport", "partition_id", "seq")
    return r, ev, rows


def test_records_in_canonical_order(trace):
    _, _, rows = trace
    assert rows["event_time"][0] == datetime(2026, 3, 2, 10, 0, 0, tzinfo=UTC)
    got = [(t.strftime("%H:%M:%S.%f")[:-3], e)
           for t, e in zip(rows["event_time"], rows["event_type"])]
    assert got == [
        ("10:00:00.000", "checkout_started"),    # U holds 80, sends reserve(A), reserve(B)
        ("10:00:00.000", "stock_reserved"),      # shard A grants (decision at request time)
        ("10:00:00.000", "stock_rejected"),      # shard B: out of stock
        ("10:00:00.300", "checkout_failed"),     # responses arrive: release hold, release(A)
        ("10:00:00.600", "stock_released"),
        ("10:02:10.000", "checkout_started"),    # substitute SKU C
        ("10:02:10.000", "stock_reserved"),
        ("10:02:10.300", "checkout_succeeded"),  # commit hold, commit(C), create payment P
        ("10:02:10.300", "payment_created"),     # P starts in the next round
        ("10:02:10.600", "stock_committed"),
    ]


def test_hold_is_released_then_committed(trace):
    _, ev, _ = trace
    assert ev["checkout_started"]["hold_after"].to_list() == [80, 80]
    assert ev["checkout_failed"]["hold_after"].to_list() == [0]
    assert ev["checkout_succeeded"]["spent_after"].to_list() == [80]
    assert ev["checkout_failed"]["sku_id"].to_list() == ev["stock_rejected"]["sku_id"].to_list()


def test_partitions_and_clocks(trace):
    _, ev, rows = trace
    user_pid = ev["checkout_started"]["partition_id"][0]
    shard_pids = set(rows.filter(pl.col("event_type").str.starts_with("stock"))["partition_id"])
    assert len(shard_pids) == 3 and user_pid not in shard_pids
    pay_pid = ev["payment_created"]["partition_id"][0]
    assert pay_pid not in shard_pids | {user_pid}
    assert ev["payment_created"]["payment_id"][0] == ev["checkout_succeeded"]["payment_id"][0]
    first = rows.filter(pl.col("event_time") == rows["event_time"][0])
    assert first["lamport"].to_list() == [1, 2, 2]          # responses carry larger clocks
    # lamport = max(partition clock, cause) + 1 at every commit, record or not; outbound rows
    # (responses, messages, timers, creations) carry the sender's commit lamport as cause.
    assert rows["lamport"].to_list() == [
        1,      # U START: max(0, 0) + 1
        2, 2,   # shards A, B: max(0, 1) + 1
        4,      # U: 1st response max(1, 2) + 1 = 3 (no record), 2nd max(3, 2) + 1
        5,      # shard A release: max(2, 4) + 1
        5,      # U timer (cause 4): max(4, 4) + 1
        6,      # shard C reserve: max(0, 5) + 1
        7,      # U response: max(5, 6) + 1
        8,      # P start (creation cause 7): max(0, 7) + 1
        8,      # shard C commit (cause 7): max(6, 7) + 1
    ]


def test_rounds_within_one_step(trace):
    r, _, _ = trace
    stats = json.loads((r.out_dir / "run_stats.json").read_text())
    assert stats["rounds_per_step"] == [4]                  # U's journey: rounds 1-3; P: round 4
    detail = stats["round_detail"][0]
    assert detail["owners_run"] == [1, 1, 1, 1]
    assert detail["shard_cmds"] == [2, 2, 0, 1]
