"""Replay encodings: flat JSON objects, JSON lines, CSV and a fixed-width table."""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc

_AS_STRING = {"i64", "ref", "amount"}   # int64 kinds: JSON strings unless `numbers`
_WIDTH = 24


def _ts(us: int) -> str:
    sec, micro = divmod(us, 1_000_000)
    return f"{datetime.fromtimestamp(sec, UTC):%Y-%m-%dT%H:%M:%S}.{micro:06d}Z"


def _column_values(batch: pa.RecordBatch, name: str, kind: str, numbers: bool) -> list:
    col = batch.column(batch.schema.get_field_index(name))
    if kind == "ts":
        return [None if v is None else _ts(v) for v in pc.cast(col, pa.int64()).to_pylist()]
    vals = col.to_pylist()
    if kind in _AS_STRING and not numbers:
        return [None if v is None else str(v) for v in vals]
    return vals


def row_dicts(batch: pa.RecordBatch, doc: dict, numbers: bool = False) -> list[dict]:
    """One flat object per row: the common columns, then that row's own type columns."""
    tables = {t["name"]: t["columns"] for t in doc["tables"] if t["kind"] == "event"}
    have = set(batch.schema.names)
    cache: dict[str, list] = {}
    kinds: dict[str, str] = {}
    for cols in tables.values():
        for c in cols:
            kinds.setdefault(c["name"], c["type"])
    for name in batch.schema.names:
        cache[name] = _column_values(batch, name, kinds.get(name, "text"), numbers)
    types = cache["event_type"]
    out = []
    for i in range(batch.num_rows):
        cols = tables[types[i]]
        out.append({c["name"]: cache[c["name"]][i] for c in cols if c["name"] in have})
    return out


def to_jsonl(dicts: list[dict]) -> str:
    return "".join(json.dumps(d, separators=(",", ":")) + "\n" for d in dicts)


def to_csv(batch: pa.RecordBatch, doc: dict, header: bool) -> str:
    """Columns of the batch (the union of the selected types'); other types' cells are empty."""
    names = batch.schema.names
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    if header:
        w.writerow(names)
    for d in row_dicts(batch, doc, numbers=True):
        w.writerow(["" if d.get(n) is None else _csv_cell(d[n]) for n in names])
    return buf.getvalue()


def _csv_cell(v: Any) -> Any:
    return str(v).lower() if isinstance(v, bool) else v


def to_table(dicts: list[dict]) -> str:
    """Fixed-width text: a header line, then one line per row; cells cut at 24 characters."""
    names: list[str] = []
    for d in dicts:
        names.extend(k for k in d if k not in names)
    cells = [[_cell(d.get(n)) for n in names] for d in dicts]
    widths = [min(_WIDTH, max([len(n), *(len(r[j]) for r in cells)])) for j, n in enumerate(names)]

    def line(vals: list[str]) -> str:
        return "  ".join(v[:_WIDTH].ljust(w) for v, w in zip(vals, widths, strict=True)).rstrip()

    return "".join(line(r) + "\n" for r in ([n for n in names], *cells)) if names else ""


def _cell(v: Any) -> str:
    if v is None:
        return ""
    return str(v).lower() if isinstance(v, bool) else str(v)
