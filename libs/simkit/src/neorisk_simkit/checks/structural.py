"""Structural checks, run on every dataset: the output matches its schema and is ordered."""

from __future__ import annotations

import polars as pl

from neorisk_simkit.checks import Data, Result, run_check
from neorisk_simkit.schema import schema_json
from neorisk_simkit.spec.types import polars_type

LEAKY = {"label", "final_label", "label_available_at", "labeled_at", "is_fraud", "score"}


def _tables(d: Data):
    for t in d.schema["tables"]:
        if t["group"] == "event":
            df = d.events.get(t["name"])
        elif t["group"] == "entity":
            df = d.entities.get(t["name"])
        else:
            df = d.labels
        yield t, df


def types(d: Data):
    bad, n = [], 0
    for t, df in _tables(d):
        n += 1
        if df is None:
            bad.append(f"{t['name']}: missing table")
            continue
        want = {c["name"]: polars_type(schema_json.ltype(c)) for c in t["columns"]}
        if list(df.columns) != list(want):
            bad.append(f"{t['name']}: columns {df.columns} != {list(want)}")
            continue
        for c, dt in want.items():
            if df.schema[c] != dt:
                bad.append(f"{t['name']}.{c}: {df.schema[c]} != {dt}")
    return n, pl.DataFrame({"detail": bad}, schema={"detail": pl.String})


def required(d: Data):
    bad, n = [], 0
    for t, df in _tables(d):
        if df is None:
            continue
        for c in t["columns"]:
            n += df.height
            if c["name"] not in df.columns:
                continue
            if not c["nullable"] and df[c["name"]].null_count():
                bad.append(f"{t['name']}.{c['name']}: {df[c['name']].null_count()} nulls")
            if c.get("min") is not None and (df[c["name"]] < c["min"]).any():
                bad.append(f"{t['name']}.{c['name']}: values below {c['min']}")
    return n, pl.DataFrame({"detail": bad}, schema={"detail": pl.String})


def unique_ids(d: Data):
    ev = d.all_events(["event_id", "seq", "partition_id", "action_id"])
    dup = ev.filter(pl.col("event_id").is_duplicated() | pl.col("seq").is_duplicated())
    bad = [dup.with_columns(detail=pl.lit("duplicate event_id or seq"))]
    n = ev.height
    for t in d.schema["tables"]:
        if t["group"] == "entity" and t["name"] in d.entities:
            k = d.entities[t["name"]][t["key"]]
            n += k.len()
            if k.is_duplicated().any():
                bad.append(pl.DataFrame({"detail": [f"{t['name']}.{t['key']} has duplicates"]}))
    return n, pl.concat(bad, how="diagonal")


def references(d: Data):
    keys = {t["name"]: d.entities[t["name"]][t["key"]].implode()
            for t in d.schema["tables"] if t["group"] == "entity" and t["name"] in d.entities}
    bad, n = [], 0
    for t, df in _tables(d):
        if df is None:
            continue
        for c in t["columns"]:
            if c["type"] != "ref" or c["name"] not in df.columns:
                continue
            col = c["name"]
            vals = df.filter(pl.col(col).is_not_null())
            n += vals.height
            miss = vals.filter(~pl.col(col).is_in(keys.get(c["ref"], pl.Series([[]]))))
            if miss.height:
                keep = [k for k in ("partition_id", "seq", "action_id") if k in miss.columns]
                bad.append(miss.select(*keep, pl.format(f"{t['name']}.{col}={{}} not in {c['ref']}",
                                                        col).alias("detail")))
    if not bad:
        return n, pl.DataFrame({"detail": []}, schema={"detail": pl.String})
    return n, pl.concat(bad, how="diagonal")


def ordering(d: Data):
    bad = []
    for name, df in d.events.items():
        if not df["seq"].is_sorted():
            bad.append(pl.DataFrame({"detail": [f"{name} is not in canonical (seq) order"]}))
    ev = d.all_events(["event_time", "seq", "partition_id", "action_id"])
    back = ev.filter(pl.col("event_time") < pl.col("event_time").shift(1))
    bad.append(back.with_columns(detail=pl.lit("event_time goes backwards in seq order")))
    return ev.height, pl.concat(bad, how="diagonal").drop("event_time", strict=False)


def leakage(d: Data):
    bad = [f"{name}.{c}" for name, df in d.events.items() for c in df.columns if c in LEAKY]
    return len(d.events), pl.DataFrame({"detail": bad}, schema={"detail": pl.String})


CHECKS = {"s.types": types, "s.required": required, "s.unique_ids": unique_ids,
          "s.references": references, "s.ordering": ordering, "s.leakage": leakage}


def run_all(d: Data) -> list[Result]:
    return [run_check(d, name, fn, group="structural", doc=fn.__doc__ or "")
            for name, fn in CHECKS.items()]
