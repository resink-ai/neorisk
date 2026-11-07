"""The log's views in each engine's SQL: the names and columns `refdata.logviews` gives
DuckDB, so a port's blocks read the same tables on every engine.

- a business event `e` is a view `e`: event_id, event_type, event_time, seq (simkit's own,
  the payload's `sim_seq`), partition_id, cause_id, action_id, then its columns;
- an `<entity>_created` event is a view named after the entity: the key (from
  `entity_key`), created_at (= event_time), then its columns.

64-bit integers travel as JSON strings and timestamps as ISO text; both are cast here.
"""

from __future__ import annotations

ENVELOPE = ("event_id", "sim_seq", "partition_id", "cause_id", "action_id")

SPARK_TYPE = {"i32": "INT", "i64": "BIGINT", "ref": "BIGINT", "amount": "BIGINT",
              "f64": "DOUBLE", "bool": "BOOLEAN", "text": "STRING", "cat": "STRING",
              "ts": "TIMESTAMP"}
SPARK_JSON = {"i32": "INT", "f64": "DOUBLE", "bool": "BOOLEAN"}     # else read as text


def _bq(name: str) -> str:
    return "`" + name.replace("`", "``") + "`"


def _lit(text: str) -> str:
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _select(e: dict, col, q, time: str = "event_time") -> list[str]:
    """The view's select list; `col(field)` is the engine's expression for a payload field,
    `q(name)` quotes an identifier and `time` is the expression for the event time."""
    if e["kind"] == "entity_created":
        key = e["key"]
        sel = [f"CAST(entity_key AS BIGINT) AS {q(key)}", f"{time} AS created_at"]
        return sel + [f"{col(f)} AS {q(f['name'])}" for f in e["fields"] if f["name"] != key]
    by = {f["name"]: f for f in e["fields"]}
    sel = [f"{col(by['event_id'])} AS event_id", "event_type", f"{time} AS event_time",
           f"{col(by['sim_seq'])} AS seq", f"{col(by['partition_id'])} AS partition_id",
           f"{col(by['cause_id'])} AS cause_id", f"{col(by['action_id'])} AS action_id"]
    return sel + [f"{col(f)} AS {q(f['name'])}" for f in e["fields"]
                  if f["name"] not in ENVELOPE]


def view_name(e: dict) -> str:
    return e["entity"] if e["kind"] == "entity_created" else e["name"]


def spark_views(schema: dict) -> list[tuple[str, str]]:
    """(view, Spark SQL over a `log` view) for every event type; the payload is parsed once
    by `from_json` into a struct typed from the schema."""
    out = []
    for e in schema["events"]:
        struct = ", ".join(f"{_bq(f['name'])} {SPARK_JSON.get(f['type'], 'STRING')}"
                           for f in e["fields"]) or "_none STRING"
        sel = _select(e, lambda f: f"CAST(p.{_bq(f['name'])} AS {SPARK_TYPE[f['type']]})",
                      _bq)
        out.append((view_name(e),
                    (f"SELECT {', '.join(sel)} FROM (SELECT entity_key, event_type, event_time, "
                    f"from_json(payload, {_lit(struct)}) AS p FROM log "
                    f"WHERE event_type = {_lit(e['name'])})")))
    return out


FLINK_TYPE = {"i32": "INT", "i64": "BIGINT", "ref": "BIGINT", "amount": "BIGINT",
              "f64": "DOUBLE", "bool": "BOOLEAN", "text": "STRING", "cat": "STRING"}


def _flink_lit(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _flink_col(f: dict) -> str:
    name = f["name"]
    path = f"$.{name}" if name.isidentifier() else "$['" + name.replace("'", "\\'") + "']"
    v = f"JSON_VALUE(payload, {_flink_lit(path)})"
    if f["type"] == "ts":        # ISO text, `2016-10-20T00:00:00.000000Z`, in UTC
        return f"CAST(REPLACE(REPLACE({v}, 'T', ' '), 'Z', '') AS TIMESTAMP(6))"
    return f"CAST({v} AS {FLINK_TYPE[f['type']]})"


def flink_views(schema: dict) -> list[tuple[str, str]]:
    """(view, Flink SQL over a `log` table) for every event type; each payload field is
    read with `JSON_VALUE` (the payload is the same JSON text in batch and streaming).
    Times are TIMESTAMP(6) in UTC, not TIMESTAMP_LTZ, which Flink's LEAD/LAG reject."""
    out = []
    for e in schema["events"]:
        sel = _select(e, _flink_col, lambda n: "`" + n.replace("`", "``") + "`",
                      "CAST(event_time AS TIMESTAMP(6))")
        out.append((view_name(e), (f"SELECT {', '.join(sel)} FROM log "
                                  f"WHERE event_type = {_flink_lit(e['name'])}")))
    return out
