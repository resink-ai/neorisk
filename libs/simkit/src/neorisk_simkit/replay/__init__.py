"""Replay a finished dataset as a stream of events, in canonical order (§15).

Mechanism: load the selected tables, filter, concatenate, sort by the canonical key, slice.
Memory is O(selected events). With `with_labels`, each label becomes a `label_available`
event at its `label_available_at`, so a downstream system sees labels arrive late.

The canonical key of a row is `"<event_time µs>:<seq>"`; label rows sort after the events of
their instant. `resume_from` continues strictly after a key.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import polars as pl

from neorisk_simkit.io.read import RunData

LABEL_SEQ0 = 1 << 62
OPS = {">=": "ge", "<=": "le", "!=": "ne", "=": "eq", ">": "gt", "<": "lt"}


@dataclass
class Selection:
    first: int | None = None
    last: int | None = None
    start: datetime | None = None             # --from (inclusive)
    end: datetime | None = None               # --to (exclusive)
    types: list[str] | None = None
    where: str | None = None                  # "amount>10000 and region=CA"
    owners: float | None = None               # a share of owners (by partition hash)
    owner_ids: list[int] | None = None        # or these partitions
    resume_from: str | None = None
    with_labels: bool = False


def parse_where(text: str) -> list[tuple[str, str, Any]]:
    out = []
    for part in re.split(r"\s+and\s+", text.strip()):
        m = re.fullmatch(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*(>=|<=|!=|=|>|<)\s*([^<>=!\s].*?)\s*", part)
        if not m:
            raise ValueError(f"bad --where clause {part!r}: use col<op>value joined by 'and'")
        col, op, raw = m.groups()
        raw = raw.strip("'\"")
        try:
            val: Any = int(raw)
        except ValueError:
            try:
                val = float(raw)
            except ValueError:
                val = raw
        out.append((col, op, val))
    return out


def _filter(df: pl.DataFrame, clauses: list[tuple[str, str, Any]]) -> pl.DataFrame | None:
    for col, op, val in clauses:
        if col not in df.columns:
            return None                       # a type without the column cannot match
        c = pl.col(col).cast(pl.String) if isinstance(val, str) else pl.col(col)
        df = df.filter(getattr(c, f"__{OPS[op]}__")(val))
    return df


def _key(df: pl.DataFrame) -> pl.Expr:
    return pl.format("{}:{}", pl.col("event_time").dt.epoch("us"), "seq")


def select(run: RunData, sel: Selection) -> pl.DataFrame:
    """Every selected row, unified (common columns first), in canonical order, with `_key`."""
    types = sel.types or sorted(run.events)
    unknown = set(types) - set(run.events) - {"label_available"}
    if unknown:
        raise ValueError(f"unknown event types {sorted(unknown)}")
    clauses = parse_where(sel.where) if sel.where else []
    frames = []
    for name in types:
        if name == "label_available":
            continue
        df = run.events[name].with_columns(pl.col(pl.Enum).cast(pl.String))
        df = _filter(df, clauses)
        if df is not None and df.height:
            frames.append(df)
    if sel.with_labels and run.labels.height:
        lab = run.labels.select(
            pl.lit(None, pl.Int64).alias("event_id"), pl.lit("label_available").alias("event_type"),
            pl.col("label_available_at").alias("event_time"),
            (pl.lit(LABEL_SEQ0) + pl.int_range(pl.len())).alias("seq"),
            "target_table", "target_id", "role", "outcome", "campaign_id", "final_label")
        lab = _filter(lab, clauses) if clauses else lab
        if lab is not None:
            frames.append(lab)
    if not frames:
        return pl.DataFrame({"_key": []}, schema={"_key": pl.String})
    df = pl.concat(frames, how="diagonal_relaxed").sort("event_time", "seq")
    if sel.start is not None:
        df = df.filter(pl.col("event_time") >= sel.start)
    if sel.end is not None:
        df = df.filter(pl.col("event_time") < sel.end)
    if sel.owner_ids is not None:
        df = df.filter(pl.col("partition_id").is_in(sel.owner_ids)
                       | pl.col("partition_id").is_null())
    elif sel.owners is not None:
        h = pl.col("partition_id").hash(seed=7) % 1_000_000
        df = df.filter((h < sel.owners * 1_000_000) | pl.col("partition_id").is_null())
    df = df.with_columns(_key=_key(df))
    if sel.resume_from:
        t, s = (int(x) for x in sel.resume_from.split(":"))
        us, seq = pl.col("event_time").dt.epoch("us"), pl.col("seq")
        df = df.filter((us > t) | ((us == t) & (seq > s)))
    if sel.first is not None:
        df = df.head(sel.first)
    if sel.last is not None:
        df = df.tail(sel.last)
    return df


# --- encoding ---------------------------------------------------------------------------

def big_columns(schema: dict) -> set[str]:
    """Columns that hold 64-bit ids or amounts (JSON strings unless --numbers)."""
    out = {"target_id", "campaign_id"}
    for t in schema["tables"]:
        out |= {c["name"] for c in t["columns"] if c["type"] in ("i64", "ref", "amount")}
    return out


def encode(rows: list[dict], big: set[str], numbers: bool = False) -> list[dict]:
    out = []
    for r in rows:
        m = {}
        for k, v in r.items():
            if k == "_key":
                continue
            if isinstance(v, datetime):
                v = v.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            elif k in big and v is not None and not numbers:
                v = str(v)
            m[k] = v
        out.append(m)
    return out


def _rows(df: pl.DataFrame, columns_of: dict[str, list[str]]) -> Iterator[dict]:
    """Rows as dicts holding only their type's columns (no sparse wide rows)."""
    for r in df.iter_rows(named=True):
        cols = columns_of.get(r["event_type"])
        yield {k: r[k] for k in cols} | {"_key": r["_key"]} if cols else r


# --- running ----------------------------------------------------------------------------

@dataclass
class Pacing:
    mode: str = "asap"                     # asap | realtime | xN
    rate: float | None = None              # max events per second
    rebase: bool = False                   # shift so the first event is "now"
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))

    def speed(self) -> float | None:
        if self.mode == "asap":
            return None
        if self.mode == "realtime":
            return 1.0
        if self.mode.startswith("x"):
            return float(self.mode[1:])
        raise ValueError(f"bad --pace {self.mode!r}: asap, realtime or xN")


def replay(run: RunData, sel: Selection, sinks: list, pacing: Pacing | None = None,
           numbers: bool = False, batch: int = 10_000) -> dict:
    """Stream the selection to every sink; returns the exit report."""
    pacing = pacing or Pacing()
    df = select(run, sel)
    columns_of = {t["name"]: [c["name"] for c in t["columns"]] for t in run.schema["tables"]}
    columns_of["label_available"] = ["event_type", "event_time", "target_table", "target_id",
                                     "role", "outcome", "campaign_id", "final_label"]
    big = big_columns(run.schema)
    speed = pacing.speed()
    shift = None
    if pacing.rebase and df.height:
        shift = pacing.clock() - df["event_time"][0]
    report = {"rows": df.height, "first_key": df["_key"][0] if df.height else None,
              "last_key": df["_key"][-1] if df.height else None, "sinks": []}
    for s in sinks:
        s.open(run.schema)
    t_prev = None
    buf: list[dict] = []
    errors: dict[int, str] = {}

    def flush():
        msgs = encode(buf, big, numbers)
        for i, s in enumerate(sinks):
            if i in errors:
                continue
            try:
                s.write(msgs, [r["_key"] for r in buf])
            except Exception as exc:  # noqa: BLE001 - one failing sink must not stop others
                errors[i] = f"{type(exc).__name__}: {exc}"
        buf.clear()

    for r in _rows(df, columns_of):
        if shift is not None:
            r["event_time"] = r["event_time"] + shift
        if speed is not None and t_prev is not None:
            gap = (r["event_time"] - t_prev).total_seconds() / speed
            if gap > 0:
                flush()
                pacing.sleep(gap)
        if pacing.rate:
            pacing.sleep(1.0 / pacing.rate)
        t_prev = r["event_time"]
        buf.append(r)
        if len(buf) >= batch:
            flush()
    if buf:
        flush()
    for i, s in enumerate(sinks):
        rep = s.close()
        if i in errors:
            rep = {**rep, "error": errors[i]}
        report["sinks"].append(rep)
    report["ok"] = not errors and all("error" not in r for r in report["sinks"])
    return report


def dry_run(run: RunData, sel: Selection, pacing: Pacing | None = None) -> dict:
    df = select(run, sel)
    out = {"rows": df.height, "types": df["event_type"].value_counts(sort=True).to_dicts()
           if df.height else [], "first_key": df["_key"][0] if df.height else None,
           "last_key": df["_key"][-1] if df.height else None}
    speed = (pacing or Pacing()).speed()
    if speed and df.height > 1:
        out["duration_s"] = (df["event_time"][-1] - df["event_time"][0]).total_seconds() / speed
    return json.loads(json.dumps(out, default=str))
