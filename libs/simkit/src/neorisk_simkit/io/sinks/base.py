"""Sink protocol, report types, the shared per-batch encoder and the URI parser."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import parse_qs

import pyarrow as pa
import pyarrow.compute as pc

from neorisk_simkit.io.replay import encode
from neorisk_simkit.io.replay.planner import CanonicalKey


class SinkUnavailable(Exception):
    pass


@dataclass(frozen=True)
class SinkOptions:
    format: str
    numbers: bool
    doc: dict


@dataclass
class SinkReport:
    name: str
    rows: int
    seconds: float
    first_key: CanonicalKey | None
    last_key: CanonicalKey | None
    error: str | None


class Sink(Protocol):
    def open(self, schema: pa.Schema, opts: SinkOptions) -> None: ...
    def write(self, batch: pa.RecordBatch) -> None: ...
    def checkpoint(self) -> CanonicalKey | None: ...
    def close(self) -> SinkReport: ...


def _key_at(batch: pa.RecordBatch, i: int) -> CanonicalKey:
    t = pc.cast(batch.column(batch.schema.get_field_index("event_time")), pa.int64())
    rest = (batch.column(batch.schema.get_field_index(k))[i].as_py()
            for k in ("lamport", "partition_id", "seq"))
    return (t[i].as_py(), *rest)


class Progress:
    """Row count, first/last canonical key and wall time shared by the sinks."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.rows = 0
        self.first: CanonicalKey | None = None
        self.last: CanonicalKey | None = None
        self.t0 = time.perf_counter()

    def add(self, batch: pa.RecordBatch) -> None:
        if not batch.num_rows:
            return
        if self.first is None:
            self.first = _key_at(batch, 0)
        self.last = _key_at(batch, batch.num_rows - 1)
        self.rows += batch.num_rows

    def report(self, error: str | None = None) -> SinkReport:
        return SinkReport(self.name, self.rows, time.perf_counter() - self.t0,
                          self.first, self.last, error)


# One batch is written to every sink: its encodings are shared through a single-entry memo,
# so each distinct (format, numbers) is encoded once per batch.
_memo: tuple[pa.RecordBatch, dict] | None = None


def encoded(batch: pa.RecordBatch, opts: SinkOptions, *, csv_header: bool = False) -> str:
    """Text of one batch: jsonl lines, comma-joined objects (json-array), csv rows, table."""
    global _memo
    if _memo is None or _memo[0] is not batch:
        _memo = (batch, {})
    cache = _memo[1]

    def rows() -> list[dict]:
        k = ("rows", opts.numbers)
        if k not in cache:
            cache[k] = encode.row_dicts(batch, opts.doc, opts.numbers)
        return cache[k]

    key = (opts.format, opts.numbers, csv_header)
    if key not in cache:
        fmt = opts.format
        if fmt == "jsonl":
            cache[key] = encode.to_jsonl(rows())
        elif fmt == "json-array":
            cache[key] = ",".join(json.dumps(d, separators=(",", ":")) for d in rows())
        elif fmt == "csv":
            cache[key] = encode.to_csv(batch, opts.doc, csv_header)
        elif fmt == "table":
            cache[key] = encode.to_table(rows())
        else:
            raise ValueError(f"no text encoding for format {fmt!r}")
    return cache[key]


STDOUT_FORMATS = ("jsonl", "table", "csv")
FILE_FORMATS = ("jsonl", "json-array", "csv", "parquet")
_EXT = {".jsonl": "jsonl", ".json": "json-array", ".csv": "csv", ".parquet": "parquet"}


def _query_format(query: str, uri: str) -> str | None:
    params = parse_qs(query, keep_blank_values=True)
    unknown = set(params) - {"format"}
    if unknown:
        raise SinkUnavailable(f"unknown sink option {min(unknown)!r} in {uri!r}")
    return params["format"][-1] if "format" in params else None


def open_sink(uri: str, numbers: bool, doc: dict) -> tuple[Sink, SinkOptions]:
    from neorisk_simkit.io.sinks.file import FileSink
    from neorisk_simkit.io.sinks.stdout import StdoutSink

    head, _, query = uri.partition("?")
    if head in ("stdout", "stdout:"):
        fmt = _query_format(query, uri) or "jsonl"
        if fmt not in STDOUT_FORMATS:
            raise SinkUnavailable(
                f"stdout does not support format {fmt!r} (use {', '.join(STDOUT_FORMATS)})")
        return StdoutSink(), SinkOptions(fmt, numbers, doc)
    if head.startswith("file:"):
        path = head[len("file:"):]
        if not path:
            raise SinkUnavailable(f"file sink needs a path: {uri!r}")
        fmt = _query_format(query, uri)
        if fmt is None:
            dot = path.rfind(".")
            fmt = _EXT.get(path[dot:].lower()) if dot > path.rfind("/") else None
            if fmt is None:
                raise SinkUnavailable(
                    f"cannot infer the format of {path!r}; add ?format="
                    f"{'|'.join(FILE_FORMATS)}")
        if fmt not in FILE_FORMATS:
            raise SinkUnavailable(
                f"file sink does not support format {fmt!r} (use {', '.join(FILE_FORMATS)})")
        return FileSink(path), SinkOptions(fmt, numbers, doc)
    if uri.startswith("kafka:"):
        raise SinkUnavailable("kafka sink arrives in M4")
    raise SinkUnavailable(f"unknown sink {uri!r} (use stdout or file:PATH)")
