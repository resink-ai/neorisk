"""D73: owner-to-owner messages arrive at t + latency in a later step; the target's presence is
judged at the delivery time, whatever the step length (Review Focus 4, F-02)."""

import json
from datetime import UTC, datetime, timedelta

import polars as pl
import pytest
from conftest import FIXTURES, event_dicts, make_run

from neorisk_simkit.engine import CapExceeded
from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.spec.caps import OUTBOX_ROW_BYTES
from neorisk_simkit.spec.validate import validate

START = datetime(2026, 3, 1, tzinfo=UTC)
H = 3_600_000_000


def _run(tmp_path, overrides=(), **eng):
    return run_to_dataset(FIXTURES / "courier", "sample", list(overrides),
                          out_dir=tmp_path / "run", threads=2, engine_overrides=eng or None)


def _late(res) -> int:
    return json.loads((res.out_dir / "manifest.json").read_text())["late_messages"]


def test_owner_to_owner_messages_validate():
    assert validate(make_run("courier")).ok


def test_latency_below_step_max_is_refused():
    errs = validate(make_run("courier", ["latency_s=3600"])).errors
    assert ("boundary credit: owner-to-owner messages need a minimum latency >= "
            "engine.step_max (86400000000 us)") in errs


def test_message_is_delivered_one_latency_later(tmp_path):
    rows = event_dicts(_run(tmp_path).out_dir)["credited"]
    assert [(r["amount"], r["event_time"]) for r in rows] == [
        (10, START + timedelta(hours=12) + timedelta(days=1))]


def test_messages_to_absent_owners_are_late(tmp_path):
    assert _late(_run(tmp_path)) == 3        # 2 retired before delivery, 3 at +0, 9 absent


def test_presence_is_judged_at_delivery_for_any_step_length(tmp_path):
    a, b = _run(tmp_path / "a"), _run(tmp_path / "b", step_us=24 * H)
    assert event_dicts(a.out_dir)["credited"] == event_dicts(b.out_dir)["credited"]
    assert _late(a) == _late(b) == 3


def test_an_owner_arriving_before_delivery_receives_it(tmp_path):
    first = _run(tmp_path / "probe")
    acct = pl.read_parquet(first.out_dir / "entities" / "acct").sort("created_at")
    arrived = acct["created_at"][-1]                     # acct 4, the only arrival
    assert arrived < START + timedelta(days=2.5), "fixture precondition (see Step 1)"
    send = max(0, int((arrived - START).total_seconds()) - 12 * 3600)
    runs = [_run(tmp_path / n, [f"send4_s={send}"], step_us=st)
            for n, st in (("a", 6 * H), ("b", 24 * H))]
    got = [[r["amount"] for r in event_dicts(r.out_dir)["credited"]] for r in runs]
    assert got[0] == got[1] and 40 in got[0]


def test_the_carried_buffer_is_capped(tmp_path):
    with pytest.raises(CapExceeded) as e:          # acct 0 sends 4 messages in one commit
        _run(tmp_path, ["engine.max_owner_messages_per_step=3"])
    assert (e.value.item, e.value.limit, e.value.attempted) == (
        "max_owner_messages_per_step", 3, 4)


def test_caps_count_the_carried_buffer():
    def cap(n):
        caps = validate(make_run("courier", max_owner_messages_per_step=n)).caps
        return next(c.hard_bytes for c in caps if c.name == "requests_and_inboxes")
    assert cap(1_000) - cap(0) == 1_000 * (OUTBOX_ROW_BYTES + 7 * 8)   # + ceid (D80)
