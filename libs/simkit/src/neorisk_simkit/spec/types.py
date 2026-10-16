"""Logical column types for the simulator spec and their storage / Arrow mappings."""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import pyarrow as pa

KINDS = ("i16", "i32", "i64", "f64", "bool", "text", "cat", "ref", "amount", "ts")


@dataclass(frozen=True)
class LType:
    kind: str
    nullable: bool = False
    values: tuple[str, ...] = ()
    target: str | None = None
    asset: str | None = None
    quantum: int = 1
    minimum: int | None = None


def i16(min: int | None = None) -> LType:
    return LType("i16", minimum=min)


def i32(min: int | None = None) -> LType:
    return LType("i32", minimum=min)


def i64(min: int | None = None) -> LType:
    return LType("i64", minimum=min)


def f64() -> LType:
    return LType("f64")


def boolean() -> LType:
    return LType("bool")


def text() -> LType:
    return LType("text")


def cat(*values: str) -> LType:
    if not values:
        raise ValueError("cat needs at least one value")
    seen: set[str] = set()
    for v in values:
        if v in seen:
            raise ValueError(f"duplicate category {v!r}")
        seen.add(v)
    return LType("cat", values=tuple(values))


def ref(target: str) -> LType:
    return LType("ref", target=target)


def amount(asset: str, quantum: int = 1) -> LType:
    return LType("amount", asset=asset, quantum=quantum)


def ts() -> LType:
    return LType("ts")


def opt(t: LType) -> LType:
    if t.nullable:
        raise ValueError("type is already optional")
    return replace(t, nullable=True)


_STORAGE = {
    "i16": np.int16,
    "i32": np.int32,
    "i64": np.int64,
    "f64": np.float64,
    "bool": np.uint8,
    "text": object,
    "cat": np.int16,
    "ref": np.int64,
    "amount": np.int64,
    "ts": np.int64,
}


def storage_dtype(t: LType) -> np.dtype:
    return np.dtype(_STORAGE[t.kind])


def arrow_type(t: LType) -> pa.DataType:
    k = t.kind
    if k == "cat":
        return pa.dictionary(pa.int16(), pa.string())
    if k == "ts":
        return pa.timestamp("us", tz="UTC")
    if k == "bool":
        return pa.bool_()
    if k == "text":
        return pa.string()
    if k == "f64":
        return pa.float64()
    if k == "i16":
        return pa.int16()
    if k == "i32":
        return pa.int32()
    return pa.int64()  # i64, ref, amount


def cat_code(t: LType, value: str) -> int:
    try:
        return t.values.index(value)
    except ValueError:
        raise ValueError(f"{value!r} is not a category of {t.values}") from None


COMMON_COLUMNS: tuple[tuple[str, LType], ...] = (
    ("event_id", i64()),
    ("event_type", text()),
    ("event_time", ts()),
    ("lamport", i64()),
    ("partition_id", i64()),
    ("seq", i32()),
    ("cause_id", opt(i64())),
    ("action_id", i16()),
)
