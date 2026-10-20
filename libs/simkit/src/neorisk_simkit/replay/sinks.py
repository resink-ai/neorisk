"""Replay sinks. A sink is the whole extension surface: one class per URI scheme.

    stdout[:?format=jsonl|table|csv]
    file:PATH[?format=jsonl|json-array|csv|parquet]      written to PATH.tmp, renamed at close
    kafka://BROKERS/TOPIC[?key=partition_id&format=json] needs the optional confluent-kafka;
                                                          TOPIC may be a template: ecom.{event_type}

File and Kafka sinks write `<target>.replay-state.json` with the last delivered canonical key
after each batch (at-least-once); `--resume` continues after it.
"""

from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qs, urlsplit


class Sink(Protocol):
    def open(self, schema: dict) -> None: ...
    def write(self, msgs: list[dict], keys: list[str]) -> None: ...   # canonical order
    def checkpoint(self) -> str | None: ...                           # last key delivered
    def close(self) -> dict: ...


class _Base:
    name = "sink"

    def __init__(self, fmt: str):
        self.fmt, self.sent, self.last = fmt, 0, None

    def open(self, schema: dict) -> None:
        pass

    def checkpoint(self) -> str | None:
        return self.last

    def close(self) -> dict:
        return {"sink": self.name, "sent": self.sent, "last_key": self.last}


class StdoutSink(_Base):
    name = "stdout"

    def __init__(self, fmt: str = "jsonl", stream=None):
        super().__init__(fmt)
        self.out = stream or sys.stdout
        self.closed_pipe = False
        self._header = None

    def write(self, msgs, keys):
        if self.closed_pipe:
            return
        try:
            for m in msgs:
                if self.fmt == "jsonl":
                    self.out.write(json.dumps(m) + "\n")
                elif self.fmt == "csv":
                    buf = io.StringIO()
                    w = csv.writer(buf)
                    if self._header != list(m):
                        self._header = list(m)
                        w.writerow(self._header)
                    w.writerow(m.values())
                    self.out.write(buf.getvalue())
                else:                                     # table
                    self.out.write("  ".join(f"{k}={v}" for k, v in m.items()) + "\n")
            self.out.flush()
        except BrokenPipeError:                           # `| head`: stop quietly
            self.closed_pipe = True
            return
        self.sent += len(msgs)
        self.last = keys[-1] if keys else self.last


def _state_path(target: str) -> Path:
    return Path(f"{target}.replay-state.json")


def read_state(target: str) -> str | None:
    p = _state_path(target)
    return json.loads(p.read_text())["last_key"] if p.exists() else None


class FileSink(_Base):
    name = "file"

    def __init__(self, path: str, fmt: str = "jsonl"):
        super().__init__(fmt)
        self.path = Path(path)
        self.tmp = Path(f"{path}.tmp")
        self.rows: list[dict] = []
        self._first = True

    def open(self, schema):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.f = self.tmp.open("w") if self.fmt != "parquet" else None
        if self.fmt == "json-array":
            self.f.write("[")

    def write(self, msgs, keys):
        if self.fmt == "parquet":
            self.rows += msgs
        else:
            for m in msgs:
                if self.fmt == "json-array":
                    self.f.write(("" if self._first else ",\n") + json.dumps(m))
                elif self.fmt == "csv":
                    w = csv.DictWriter(self.f, fieldnames=list(m), extrasaction="ignore")
                    w.writerow(m)
                else:
                    self.f.write(json.dumps(m) + "\n")
                self._first = False
            self.f.flush()
        self.sent += len(msgs)
        self.last = keys[-1] if keys else self.last
        _state_path(str(self.path)).write_text(json.dumps({"last_key": self.last}))

    def close(self):
        if self.fmt == "parquet":
            import polars as pl
            pl.DataFrame(self.rows, infer_schema_length=None).write_parquet(self.tmp)
        else:
            if self.fmt == "json-array":
                self.f.write("]\n")
            self.f.close()
        self.tmp.replace(self.path)
        return {**super().close(), "path": str(self.path)}


class KafkaSink(_Base):
    name = "kafka"

    def __init__(self, brokers: str, topic: str, key: str = "partition_id", fmt: str = "json",
                 producer: Any = None):
        super().__init__(fmt)
        self.brokers, self.topic, self.key = brokers, topic, key
        self.producer = producer
        self.target = f"kafka-{brokers.replace(':', '_')}-{topic.replace('/', '_')}"

    def open(self, schema):
        if self.producer is None:
            try:
                from confluent_kafka import Producer
            except ImportError:
                raise RuntimeError("the kafka sink needs the optional extra: "
                                   "uv add confluent-kafka (neorisk-simkit[kafka])") from None
            self.producer = Producer({"bootstrap.servers": self.brokers, "acks": "all",
                                      "enable.idempotence": True, "compression.type": "zstd",
                                      "linger.ms": 20})
        self.version = str(schema.get("schema_version", 1))

    def write(self, msgs, keys):
        for m in msgs:
            topic = self.topic.format(event_type=m.get("event_type", "events"))
            key = m.get(self.key)
            headers = [("event_type", str(m.get("event_type")).encode()),
                       ("schema_version", self.version.encode()),
                       ("event_id", str(m.get("event_id")).encode())]
            self.producer.produce(topic, value=json.dumps(m).encode(),
                                  key=None if key is None else str(key).encode(),
                                  headers=headers)
        self.producer.flush()
        self.sent += len(msgs)
        self.last = keys[-1] if keys else self.last
        _state_path(self.target).write_text(json.dumps({"last_key": self.last}))


def parse(uri: str, **kw) -> Any:
    """A sink from its URI."""
    if uri.startswith("stdout"):
        q = parse_qs(uri.partition("?")[2])
        return StdoutSink(q.get("format", ["jsonl"])[0], **kw)
    if uri.startswith("file:"):
        path, _, query = uri[5:].partition("?")
        return FileSink(path, parse_qs(query).get("format", ["jsonl"])[0])
    if uri.startswith("kafka://"):
        u = urlsplit(uri)
        q = parse_qs(u.query)
        return KafkaSink(u.netloc, u.path.lstrip("/"), q.get("key", ["partition_id"])[0],
                         q.get("format", ["json"])[0], **kw)
    raise ValueError(f"unknown sink {uri!r}: stdout, file:PATH or kafka://BROKERS/TOPIC")


def target_of(sink: Any) -> str | None:
    if isinstance(sink, FileSink):
        return str(sink.path)
    if isinstance(sink, KafkaSink):
        return sink.target
    return None
