"""The single ordered event log: envelope, order, payload encoding, parts, schema."""

import hashlib
import json
import re
from datetime import UTC, datetime

import polars as pl
import pytest

from neorisk_simkit.io.log import ENVELOPE, LogError, events_schema, log_frame, write_log
from neorisk_simkit.io.read import RunData

T0 = datetime(2021, 1, 1, 9, 0, tzinfo=UTC)
TS = pl.Datetime("us", "UTC")


def _col(name, type_, nullable=False, ref=None):
    c = {"name": name, "type": type_, "nullable": nullable}
    if ref:
        c["ref"] = ref
    return c


COMMON = [_col("event_id", "i64"), _col("event_type", "text"), _col("event_time", "ts"),
          _col("seq", "i64"), _col("partition_id", "i64"), _col("cause_id", "i64", True),
          _col("action_id", "i32")]


def _run(orders: list[dict] | None = None, customers: list[dict] | None = None,
         empty_event: bool = False) -> RunData:
    customers = customers if customers is not None else [
        {"customer_id": 1, "created_at": T0, "ext_id": "c1", "vip": True}]
    orders = orders if orders is not None else [
        {"event_id": 1, "event_type": "order_placed", "event_time": T0, "seq": 1,
         "partition_id": 1, "cause_id": None, "action_id": 0, "customer_id": 1,
         "total": 1050, "rate": 0.1, "note": None, "at": T0}]
    schema = {"format": 1, "pack": "shop", "schema_version": 3, "tables": [
        {"name": "customers", "group": "entity", "key": "customer_id", "columns": [
            _col("customer_id", "i64"), _col("created_at", "ts"), _col("ext_id", "text"),
            _col("vip", "bool")]},
        {"name": "order_placed", "group": "event", "columns": [
            *COMMON, _col("customer_id", "ref", ref="customers"), _col("total", "amount"),
            _col("rate", "f64"), _col("note", "text", True), _col("at", "ts")]},
    ]}
    ent = pl.DataFrame(customers, schema={"customer_id": pl.Int64, "created_at": TS,
                                          "ext_id": pl.String, "vip": pl.Boolean})
    ev_schema = {"event_id": pl.Int64, "event_type": pl.String, "event_time": TS,
                 "seq": pl.Int64, "partition_id": pl.Int64, "cause_id": pl.Int64,
                 "action_id": pl.Int32, "customer_id": pl.Int64, "total": pl.Int64,
                 "rate": pl.Float64, "note": pl.String, "at": TS}
    events = {"order_placed": pl.DataFrame(orders, schema=ev_schema)}
    if empty_event:
        schema["tables"].append({"name": "order_paid", "group": "event", "columns": [
            *COMMON, _col("customer_id", "ref", ref="customers")]})
        events["order_paid"] = pl.DataFrame(schema={k: ev_schema[k] for k in
                                                    [c["name"] for c in COMMON]}
                                            | {"customer_id": pl.Int64})
    return RunData(root=None, manifest={}, schema=schema, events=events,
                   entities={"customers": ent})


def _order(i, t=T0, **kw):
    return {"event_id": i, "event_type": "order_placed", "event_time": t, "seq": i,
            "partition_id": 1, "cause_id": None, "action_id": 0, "customer_id": 1,
            "total": 100 * i, "rate": 1.5, "note": "n", "at": t} | kw


def test_envelope_columns_and_types():
    df = log_frame(_run())
    assert tuple(df.columns) == ENVELOPE
    assert df.schema["event_time"] == TS
    assert df.schema["schema_version"] == pl.Int32
    assert df["schema_version"].to_list() == [3, 3]


def test_entity_precedes_event_at_same_time():
    df = log_frame(_run())
    assert df["event_type"].to_list() == ["customers_created", "order_placed"]
    assert df["seq"].to_list() == [1, 2]


def test_payload_encoding():
    df = log_frame(_run())
    ent, order = (json.loads(p) for p in df["payload"])
    assert ent == {"customer_id": "1", "ext_id": "c1", "vip": True}
    assert order["total"] == "1050" and order["customer_id"] == "1"
    assert order["rate"] == 0.1 and isinstance(order["rate"], float)
    assert order["note"] is None
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z", order["at"])
    assert list(order)[:5] == ["event_id", "sim_seq", "partition_id", "cause_id", "action_id"]
    assert order["event_id"] == "1" and order["sim_seq"] == "1" and order["action_id"] == 0
    assert order["cause_id"] is None


def test_owner_mapping():
    df = log_frame(_run(), owners={"order_placed": "customer_id"})
    row = df.filter(pl.col("event_type") == "order_placed")
    assert row["entity_type"].to_list() == ["customers"]
    assert row["entity_key"].to_list() == ["1"]
    ent = df.filter(pl.col("event_type") == "customers_created")
    assert (ent["entity_type"].to_list(), ent["entity_key"].to_list()) == (["customers"], ["1"])
    bare = log_frame(_run()).filter(pl.col("event_type") == "order_placed")
    assert (bare["entity_type"].to_list(), bare["entity_key"].to_list()) == (["partition"], ["1"])


def test_nan_refused():
    with pytest.raises(LogError, match=r"order_placed\.rate"):
        log_frame(_run(orders=[_order(1, rate=float("nan"))]))
    with pytest.raises(LogError, match=r"order_placed\.rate"):
        log_frame(_run(orders=[_order(1, rate=float("inf"))]))


def test_parts_split_consecutive(tmp_path):
    run = _run(orders=[_order(i) for i in range(1, 5)])
    parts = write_log(run, tmp_path, part_rows=2)
    assert [p.name for p in parts] == ["part-00000.parquet", "part-00001.parquet",
                                       "part-00002.parquet"]
    seqs = [pl.read_parquet(p)["seq"].to_list() for p in parts]
    assert seqs == [[1, 2], [3, 4], [5]]
    assert (tmp_path / "schema" / "events.json").exists()


def test_events_schema_lists_every_type():
    s = events_schema(_run(empty_event=True))
    assert s["format"] == 1 and s["schema_version"] == 3
    names = [(e["name"], e["kind"], e["entity"], e["key"]) for e in s["events"]]
    assert names == [("customers_created", "entity_created", "customers", "customer_id"),
                     ("order_placed", "event", None, None),
                     ("order_paid", "event", None, None)]
    paid = s["events"][2]["fields"]
    assert [f["name"] for f in paid] == ["event_id", "sim_seq", "partition_id", "cause_id",
                                         "action_id", "customer_id"]
    assert paid[3]["nullable"] is True and paid[4]["type"] == "i32"
    assert paid[5] == {"name": "customer_id", "type": "ref", "nullable": False,
                       "ref": "customers"}
    ent = s["events"][0]["fields"]
    assert [f["name"] for f in ent] == ["customer_id", "ext_id", "vip"]


def test_write_is_deterministic(tmp_path):
    def shas(d):
        return {p.relative_to(d).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(d.rglob("*")) if p.is_file()}
    run = _run(orders=[_order(i) for i in range(1, 4)])
    write_log(run, tmp_path / "a")
    write_log(run, tmp_path / "b")
    assert shas(tmp_path / "a") == shas(tmp_path / "b")


def test_created_name_renames_event(tmp_path):
    created = {"customers": "customer_signed_up"}
    df = log_frame(_run(), created=created)
    assert "customer_signed_up" in df["event_type"].to_list()
    assert "customers_created" not in df["event_type"].to_list()
    s = events_schema(_run(), created=created)
    assert (s["events"][0]["name"], s["events"][0]["kind"], s["events"][0]["entity"]) == (
        "customer_signed_up", "entity_created", "customers")
    write_log(_run(), tmp_path, created=created)
    on_disk = json.loads((tmp_path / "schema" / "events.json").read_text())
    assert on_disk["events"][0]["name"] == "customer_signed_up"


def test_created_name_collision_refused():
    with pytest.raises(LogError, match="order_placed"):
        log_frame(_run(), created={"customers": "order_placed"})


def test_created_name_for_unknown_entity_refused():
    with pytest.raises(LogError, match="custmers"):
        events_schema(_run(), created={"custmers": "customer_signed_up"})
