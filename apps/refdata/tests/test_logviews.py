"""The log decoder: the log's views equal the dataset's frames, value for value."""

import struct
from datetime import UTC, datetime

import duckdb
import polars as pl

from neorisk_simkit.io import read
from neorisk_simkit.io.log import write_log
from neorisk_simkit.io.read import RunData
from refdata.ingest import ingest
from refdata.logviews import attach_log

T0 = datetime(2021, 1, 1, 9, 0, tzinfo=UTC)
TS = pl.Datetime("us", "UTC")


def _con():
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    return con


def _sorted(df: pl.DataFrame) -> pl.DataFrame:
    return df.sort(df.columns[0])


def test_views_equal_run_frames(shop, tmp_path):
    proj, db = shop
    run = read(ingest(proj, db, tmp_path / "ds"))
    write_log(run, tmp_path / "log")
    con = _con()
    names = attach_log(con, tmp_path / "log")
    assert set(names) == set(run.events) | set(run.entities)
    for name, want in {**run.events, **run.entities}.items():
        got = con.sql(f'SELECT * FROM "{name}"').pl()
        assert got.columns == want.columns, name
        assert got.schema == want.schema, name
        assert _sorted(got).equals(_sorted(want)), name


def _entity_run(values: list, kind: str, dtype: pl.DataType) -> RunData:
    """One entity table `things` with a column `v` of the given simkit kind."""
    n = len(values)
    df = pl.DataFrame({"thing_id": list(range(1, n + 1)), "created_at": [T0] * n, "v": values},
                      schema={"thing_id": pl.Int64, "created_at": TS, "v": dtype})
    schema = {"format": 1, "pack": "t", "schema_version": 1, "tables": [
        {"name": "things", "group": "entity", "key": "thing_id", "columns": [
            {"name": "thing_id", "type": "i64", "nullable": False},
            {"name": "created_at", "type": "ts", "nullable": False},
            {"name": "v", "type": kind, "nullable": True}]}]}
    return RunData(root=None, manifest={}, schema=schema, events={}, entities={"things": df})


def _round_trip(tmp_path, values, kind, dtype) -> list:
    write_log(_entity_run(values, kind, dtype), tmp_path / "log")
    con = _con()
    attach_log(con, tmp_path / "log")
    return [r[0] for r in con.execute('SELECT v FROM things ORDER BY thing_id').fetchall()]


def test_text_survives_json(tmp_path):
    values = ['a"b', "back\\slash", "nl\nx", "nul\x00x", "\x01\x1f", "😀", "\\N", "",
              " pad ", None]
    assert _round_trip(tmp_path, values, "text", pl.String) == values


def test_floats_bit_exact(tmp_path):
    values = [0.1, 5e-324, 1.7976931348623157e308, -0.0, 123456789.12345679]
    got = _round_trip(tmp_path, values, "f64", pl.Float64)
    assert [struct.pack("<d", v) for v in got] == [struct.pack("<d", v) for v in values]


def test_int64_limits(tmp_path):
    values = [2**63 - 1, -(2**63), 2**53 + 1]
    assert _round_trip(tmp_path, values, "i64", pl.Int64) == values


def test_empty_event_type_typed_view(tmp_path):
    run = _entity_run(["x"], "text", pl.String)
    run.schema["tables"].append({"name": "poked", "group": "event", "columns": [
        {"name": "event_id", "type": "i64", "nullable": False},
        {"name": "event_type", "type": "text", "nullable": False},
        {"name": "event_time", "type": "ts", "nullable": False},
        {"name": "seq", "type": "i64", "nullable": False},
        {"name": "partition_id", "type": "i64", "nullable": False},
        {"name": "cause_id", "type": "i64", "nullable": True},
        {"name": "action_id", "type": "i32", "nullable": False},
        {"name": "rate", "type": "f64", "nullable": False}]})
    run.events["poked"] = pl.DataFrame(schema={
        "event_id": pl.Int64, "event_type": pl.String, "event_time": TS, "seq": pl.Int64,
        "partition_id": pl.Int64, "cause_id": pl.Int64, "action_id": pl.Int32,
        "rate": pl.Float64})
    write_log(run, tmp_path / "log")
    con = _con()
    attach_log(con, tmp_path / "log")
    got = con.sql("SELECT * FROM poked").pl()
    assert got.height == 0
    assert got.schema == run.events["poked"].schema
