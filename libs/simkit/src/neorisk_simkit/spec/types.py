"""Logical column types: what a pack declares, and how each maps to Polars and Arrow."""

from __future__ import annotations

from dataclasses import dataclass, replace

import polars as pl
import pyarrow as pa

KINDS = ("i32", "i64", "f64", "bool", "text", "cat", "ref", "amount", "ts")
INT64_MIN, INT64_MAX = -(2**63), 2**63 - 1


@dataclass(frozen=True)
class LType:
    kind: str
    nullable: bool = False
    values: tuple[str, ...] = ()      # cat
    target: str | None = None         # ref: the referenced entity table
    asset: str | None = None          # amount: unit, in integer minor units
    minimum: int | None = None
    doc: str = ""


def i32(min: int | None = None, doc: str = "") -> LType:
    return LType("i32", minimum=min, doc=doc)


def i64(min: int | None = None, doc: str = "") -> LType:
    return LType("i64", minimum=min, doc=doc)


def f64(doc: str = "") -> LType:
    return LType("f64", doc=doc)


def boolean(doc: str = "") -> LType:
    return LType("bool", doc=doc)


def text(doc: str = "") -> LType:
    return LType("text", doc=doc)


def ts(doc: str = "") -> LType:
    """A simulated time; actions pass seconds since the run start, exported as UTC µs."""
    return LType("ts", doc=doc)


def cat(*values: str, doc: str = "") -> LType:
    if not values or len(set(values)) != len(values):
        raise ValueError(f"cat needs distinct values, got {values}")
    return LType("cat", values=tuple(values), doc=doc)


def ref(target: str, doc: str = "") -> LType:
    return LType("ref", target=target, doc=doc)


def amount(asset: str = "USD", doc: str = "") -> LType:
    """Integer minor units of `asset` (Python int while running, int64 on export)."""
    return LType("amount", asset=asset, doc=doc)


def opt(t: LType) -> LType:
    return replace(t, nullable=True)


def polars_type(t: LType) -> pl.DataType:
    return {
        "i32": pl.Int32(), "i64": pl.Int64(), "ref": pl.Int64(), "amount": pl.Int64(),
        "f64": pl.Float64(), "bool": pl.Boolean(), "text": pl.String(),
        "ts": pl.Datetime("us", "UTC"),
    }.get(t.kind) or pl.Enum(list(t.values))


def arrow_type(t: LType) -> pa.DataType:
    k = t.kind
    if k == "cat":
        return pa.dictionary(pa.int16(), pa.string())
    if k == "ts":
        return pa.timestamp("us", tz="UTC")
    return {"i32": pa.int32(), "f64": pa.float64(), "bool": pa.bool_(),
            "text": pa.string()}.get(k, pa.int64())


def accepts(t: LType, v: object) -> bool:
    """Whether an action may emit `v` into a column of type `t` (debug-mode emit check)."""
    if v is None:
        return t.nullable
    k = t.kind
    if k in ("i32", "i64", "ref", "amount"):
        ok = isinstance(v, int) and not isinstance(v, bool)
        return ok and (t.minimum is None or v >= t.minimum)
    if k in ("f64", "ts"):
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    if k == "bool":
        return isinstance(v, bool)
    if k == "cat":
        return v in t.values
    return isinstance(v, str)


COMMON = {
    "event_id": i64(doc="Unique across all event tables"),
    "event_type": text(doc="The event table's name"),
    "event_time": ts(doc="When the event happened"),
    "seq": i64(doc="Global commit counter; with event_time and priority, the total order"),
    "partition_id": i64(doc="The owner or shard partition that emitted the row"),
    "cause_id": opt(i64(doc="event_id of the event whose action scheduled this one")),
    "action_id": i32(doc="The emitting action (schema.json lists the ids)"),
}
