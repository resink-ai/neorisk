"""Decode a dataset's event log (`log/*.parquet` + `schema/events.json`) into DuckDB views.

The views have the names and columns the pack's Parquet tables had, so `build.sql` runs over
the log alone:

- a business event `e` is a view `e` with event_id, event_type, event_time, seq (simkit's
  own, from the payload's `sim_seq`), partition_id, cause_id, action_id, then its columns;
- an `<entity>_created` event is a view named after the entity, with the key (from
  `entity_key`), created_at (= event_time), then its columns.

Each payload is parsed once, by `json_transform` into a struct typed from the schema; 64-bit
integers travel as JSON strings and are cast back here. The connection must run in UTC.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

SQL_TYPE = {"i32": "INTEGER", "i64": "BIGINT", "ref": "BIGINT", "amount": "BIGINT",
            "f64": "DOUBLE", "bool": "BOOLEAN", "text": "VARCHAR", "cat": "VARCHAR",
            "ts": "TIMESTAMPTZ"}
# how each kind is read out of the JSON before the final cast
JSON_TYPE = {"i32": "INTEGER", "f64": "DOUBLE", "bool": "BOOLEAN"}


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _lit(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _view(e: dict) -> str:
    structure = {f["name"]: JSON_TYPE.get(f["type"], "VARCHAR") for f in e["fields"]}
    cols = {f["name"]: f"CAST(p.{_q(f['name'])} AS {SQL_TYPE[f['type']]})"
            for f in e["fields"]}
    if e["kind"] == "entity_created":
        key = e["key"]
        sel = [f"CAST(entity_key AS BIGINT) AS {_q(key)}", "event_time AS created_at"]
        sel += [f"{expr} AS {_q(n)}" for n, expr in cols.items() if n != key]
    else:
        sel = [f"{cols['event_id']} AS event_id", "event_type", "event_time",
               f"{cols['sim_seq']} AS seq", f"{cols['partition_id']} AS partition_id",
               f"{cols['cause_id']} AS cause_id", f"{cols['action_id']} AS action_id"]
        sel += [f"{expr} AS {_q(n)}" for n, expr in cols.items()
                if n not in ("event_id", "sim_seq", "partition_id", "cause_id", "action_id")]
    return (f"SELECT {', '.join(sel)} FROM (SELECT entity_key, event_type, event_time, "
            f"json_transform(payload, {_lit(json.dumps(structure))}) AS p FROM log "
            f"WHERE event_type = {_lit(e['name'])})")


def attach_log(con: duckdb.DuckDBPyConnection, root: Path) -> list[str]:
    """Create the view `log` and one view per event type; returns the per-type view names."""
    root = Path(root)
    schema = json.loads((root / "schema" / "events.json").read_text())
    parts = str(root / "log" / "*.parquet")
    con.execute(f"CREATE OR REPLACE VIEW log AS SELECT * FROM read_parquet({_lit(parts)})")
    names = []
    for e in schema["events"]:
        name = e["entity"] if e["kind"] == "entity_created" else e["name"]
        con.execute(f"CREATE OR REPLACE VIEW {_q(name)} AS {_view(e)}")
        names.append(name)
    return names
