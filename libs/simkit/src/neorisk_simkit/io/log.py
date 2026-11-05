"""The single ordered event log: a dataset as one Kafka-like stream with JSON payloads.

Every entity row becomes an `<entity>_created` event at its `created_at` (or a domain name
the recipe gives, such as `customer_signed_up`); every business
event keeps its columns. Rows sort by (event_time, entities before events, entity order then
key / simkit `seq`), and the log's `seq` is the 1-based position in that order.

Payload JSON: i64, ref and amount are strings (no reader loses precision above 2**53); i32 is
a number; ts is `YYYY-MM-DDTHH:MM:SS.ffffffZ`; f64 is a number in shortest round-trip form
(NaN and inf are refused); bool is true/false; text is carried byte for byte. A business
event's payload starts with `event_id`, `sim_seq` (simkit's own `seq`), `partition_id`,
`cause_id` and `action_id`. `schema/events.json` lists every event type and its fields.
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl

from neorisk_simkit.io.read import RunData
from neorisk_simkit.io.writer import _write

ENVELOPE = ("seq", "event_time", "event_type", "entity_type", "entity_key",
            "schema_version", "payload")
BIG = {"i64", "ref", "amount"}
INTERNAL = [("event_id", "event_id", "i64", False), ("sim_seq", "seq", "i64", False),
            ("partition_id", "partition_id", "i64", False),
            ("cause_id", "cause_id", "i64", True), ("action_id", "action_id", "i32", False)]
SKIP = {"event_id", "event_type", "event_time", "seq", "partition_id", "cause_id", "action_id"}


class LogError(ValueError):
    pass


def _field(c: dict) -> dict:
    f = {"name": c["name"], "type": c["type"], "nullable": c["nullable"]}
    if c.get("ref"):
        f["ref"] = c["ref"]
    return f


def _entry(t: dict, created: dict[str, str]) -> dict:
    """One events.json entry, with `src` (the frame column) on each field for encoding."""
    if t["group"] == "entity":
        fields = [_field(c) | {"src": c["name"]} for c in t["columns"]
                  if c["name"] != "created_at"]
        return {"name": created.get(t["name"], f"{t['name']}_created"), "kind": "entity_created",
                "entity": t["name"], "key": t["key"], "fields": fields}
    fields = [{"name": n, "type": k, "nullable": nl, "src": s} for n, s, k, nl in INTERNAL]
    fields += [_field(c) | {"src": c["name"]} for c in t["columns"] if c["name"] not in SKIP]
    return {"name": t["name"], "kind": "event", "entity": None, "key": None, "fields": fields}


def _entries(run: RunData, created: dict[str, str] | None = None) -> list[tuple[dict, dict]]:
    """`created` maps an entity to its creation event's domain name."""
    created = created or {}
    tables = [t for t in run.schema["tables"] if t["group"] in ("entity", "event")]
    ents = [t for t in tables if t["group"] == "entity"]
    evs = [t for t in tables if t["group"] == "event"]
    unknown = sorted(set(created) - {t["name"] for t in ents})
    if unknown:
        raise LogError(f"creation event names given for unknown entities: {unknown}")
    out = [(t, _entry(t, created)) for t in ents + evs]
    seen: dict[str, str] = {}
    for t, e in out:
        if e["name"] in seen:
            raise LogError(f"event type {e['name']!r} is both {seen[e['name']]!r} and "
                           f"{t['name']!r}; give the creation event another name")
        seen[e["name"]] = t["name"]
    return out


def events_schema(run: RunData, *, created: dict[str, str] | None = None) -> dict:
    return {"format": 1, "schema_version": int(run.schema["schema_version"]),
            "events": [e | {"fields": [{k: v for k, v in f.items() if k != "src"}
                                       for f in e["fields"]]}
                       for _, e in _entries(run, created)]}


def _payload(df: pl.DataFrame, entry: dict) -> pl.Expr:
    exprs = []
    for f in entry["fields"]:
        c = pl.col(f["src"])
        if f["type"] == "f64":
            bad = df.filter(pl.col(f["src"]).is_not_null() & ~pl.col(f["src"]).is_finite())
            if bad.height:
                raise LogError(f"{entry['name']}.{f['name']}: {bad.height} NaN or infinite "
                               f"values cannot be written as JSON")
        if f["type"] in BIG:
            c = c.cast(pl.String)
        elif f["type"] == "ts":
            c = c.dt.convert_time_zone("UTC").dt.strftime("%Y-%m-%dT%H:%M:%S%.6fZ")
        exprs.append(c.alias(f["name"]))
    if not exprs:
        return pl.lit("{}")
    return pl.struct(exprs).struct.json_encode()


def _owner(run: RunData, t: dict, owners: dict[str, str]) -> tuple[pl.Expr, pl.Expr]:
    col = owners.get(t["name"])
    if col is None:
        return pl.lit("partition"), pl.col("partition_id").cast(pl.String)
    spec = next((c for c in t["columns"] if c["name"] == col), None)
    if spec is None:
        raise LogError(f"{t['name']}: owner column {col!r} is not one of its columns")
    return pl.lit(spec.get("ref") or col), pl.col(col).cast(pl.String)


def log_frame(run: RunData, *, owners: dict[str, str] | None = None,
              created: dict[str, str] | None = None) -> pl.DataFrame:
    owners = owners or {}
    version = int(run.schema["schema_version"])
    parts = []
    for i, (t, e) in enumerate(_entries(run, created)):
        if e["kind"] == "entity_created":
            df = run.entities[t["name"]]
            kind, rank = 0, pl.col(t["key"])
            et, ek = pl.lit(t["name"]), pl.col(t["key"]).cast(pl.String)
            when = pl.col("created_at")
        else:
            df = run.events[t["name"]]
            kind, rank = 1, pl.col("seq")
            et, ek = _owner(run, t, owners)
            when = pl.col("event_time")
        parts.append(df.select(
            when.dt.convert_time_zone("UTC").alias("event_time"),
            pl.lit(kind, pl.Int8).alias("_kind"), pl.lit(i, pl.Int32).alias("_tab"),
            rank.cast(pl.Int64).alias("_rank"),
            pl.lit(e["name"]).alias("event_type"), et.cast(pl.String).alias("entity_type"),
            ek.alias("entity_key"), _payload(df, e).cast(pl.String).alias("payload")))
    # entities sort by pack order then key; events by simkit seq (their _tab never matters)
    allp = pl.concat(parts).with_columns(
        pl.when(pl.col("_kind") == 0).then(pl.col("_tab")).otherwise(0).alias("_tab"))
    out = allp.sort(["event_time", "_kind", "_tab", "_rank"], maintain_order=True)
    return out.select(
        pl.int_range(1, out.height + 1, dtype=pl.Int64).alias("seq"),
        pl.col("event_time").cast(pl.Datetime("us", "UTC")), "event_type", "entity_type",
        "entity_key", pl.lit(version, pl.Int32).alias("schema_version"), "payload")


def write_log(run: RunData, out_dir: str | Path, *, owners: dict[str, str] | None = None,
              created: dict[str, str] | None = None, part_rows: int = 1_000_000) -> list[Path]:
    """Write `log/part-NNNNN.parquet` (consecutive seq ranges) and `schema/events.json`."""
    if part_rows < 1:
        raise ValueError("part_rows must be at least 1")
    out = Path(out_dir)
    df = log_frame(run, owners=owners, created=created)
    paths = []
    for n, start in enumerate(range(0, max(df.height, 1), part_rows)):
        p = out / "log" / f"part-{n:05d}.parquet"
        _write(df.slice(start, part_rows), p)
        paths.append(p)
    sp = out / "schema" / "events.json"
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps(events_schema(run, created=created), indent=2, ensure_ascii=False) + "\n")
    return paths
