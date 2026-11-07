"""The Flink streaming engine: the log replayed into one Redpanda topic, the same Flink port
as `flink` run in streaming mode, and each table's changelog folded into its final rows.

- **Replay:** one topic per run, one partition, in `seq` order; key `entity_key`; value the
  envelope as JSON, with `payload` kept as its JSON text (so the views are the batch ones)
  and `event_time` as `YYYY-MM-DD HH:MM:SS.ffffffZ`.
- **Job:** the Kafka source is bounded at the latest offset, so the streaming job finishes
  when the topic is drained. Each table sinks to its own topic in `debezium-json`: Flink
  writes an update as a delete and an insert.
- **Fold:** after the job, each sink topic is read to its end; `c` adds a row, `d` removes
  one. A row removed more often than it was added means the changelog does not fold, and
  the table fails. The run's topics are deleted afterwards.
"""

from __future__ import annotations

import datetime as dt
import json
import time
from collections import Counter
from collections.abc import Iterable, Iterator

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from dataset.engines import Job
from dataset.engines.flink import CONTAINERS, Flink, lit

BROKERS = "localhost:19092"          # from the host
INSIDE = "redpanda:9092"             # from the Flink containers
REDPANDA = "neorisk-engines-redpanda-1"


class FoldError(ValueError):
    pass


def _value(v, t: pa.DataType):
    if v is None:
        return None
    if pa.types.is_timestamp(t):
        return dt.datetime.fromisoformat(str(v).removesuffix("Z")).replace(tzinfo=dt.UTC)
    if pa.types.is_date(t):
        return dt.date.fromisoformat(str(v))
    return v


def fold(messages: Iterable[dict | None], columns: list[tuple[str, pa.DataType]]) -> pa.Table:
    """The final multiset of a debezium-json changelog, typed as `columns`."""
    names = [c for c, _ in columns]
    rows: Counter = Counter()
    for m in messages:
        if m is None:                    # a tombstone
            continue
        if m["op"] in ("d", "u") and m.get("before") is not None:
            rows[tuple(m["before"].get(c) for c in names)] -= 1
        if m["op"] in ("c", "r", "u") and m.get("after") is not None:
            rows[tuple(m["after"].get(c) for c in names)] += 1
    bad = [r for r, n in rows.items() if n < 0]
    if bad:
        raise FoldError(f"the changelog does not fold: {len(bad)} rows are retracted more "
                        f"often than inserted, e.g. {bad[0]}")
    out = list(rows.elements())
    arrays = [pa.array([_value(r[i], t) for r in out], t) for i, (_, t) in enumerate(columns)]
    return pa.Table.from_arrays(arrays, names=names)


def message_values(t: pa.Table) -> Iterator[tuple[bytes, bytes]]:
    """(key, value) of each log row, in the table's order."""
    t = t.set_column(t.schema.get_field_index("event_time"), "event_time",
                     pc.strftime(t["event_time"], "%Y-%m-%d %H:%M:%SZ"))
    for r in t.to_pylist():
        yield (r["entity_key"] or "").encode(), json.dumps(r).encode()


def _admin():
    from confluent_kafka.admin import AdminClient
    return AdminClient({"bootstrap.servers": BROKERS})


def create_topic(name: str) -> None:
    from confluent_kafka.admin import NewTopic
    admin = _admin()                  # held until the futures resolve
    for f in admin.create_topics([NewTopic(name, 1, 1)]).values():
        f.result(timeout=30)


def delete_topics(names: list[str]) -> None:
    if names:
        admin = _admin()
        for f in admin.delete_topics(names).values():
            try:
                f.result(timeout=30)
            except Exception:  # noqa: BLE001, S110 — a topic that never got created
                pass


def replay_log(root, topic: str) -> int:
    """Send the log, in `seq` order, to a new one-partition topic; the events sent."""
    from confluent_kafka import Producer
    create_topic(topic)
    p = Producer({"bootstrap.servers": BROKERS, "linger.ms": 50, "enable.idempotence": True,
                  "compression.type": "lz4"})
    n = 0
    for f in sorted((root / "log").glob("*.parquet")):
        for batch in pq.ParquetFile(f).iter_batches(batch_size=50_000):
            for key, value in message_values(pa.Table.from_batches([batch])):
                while True:
                    try:
                        p.produce(topic, key=key, value=value)
                        break
                    except BufferError:
                        p.poll(0.1)
                p.poll(0)
                n += 1
    if p.flush(120) > 0:
        raise RuntimeError(f"{topic}: messages still undelivered after 120 s")
    return n


def read_topic(topic: str) -> Iterator[dict | None]:
    """Every message of a one-partition topic, from the start to its end now."""
    from confluent_kafka import Consumer, TopicPartition
    c = Consumer({"bootstrap.servers": BROKERS, "group.id": f"fold-{topic}",
                  "enable.auto.commit": False, "auto.offset.reset": "earliest"})
    try:
        low, high = c.get_watermark_offsets(TopicPartition(topic, 0), timeout=30)
        if high <= low:
            return
        c.assign([TopicPartition(topic, 0, low)])
        while True:
            m = c.poll(10)
            if m is None:
                raise RuntimeError(f"{topic}: no message for 10 s before offset {high}")
            if m.error():
                raise RuntimeError(f"{topic}: {m.error()}")
            yield None if m.value() is None else json.loads(m.value())
            if m.offset() >= high - 1:
                return
    finally:
        c.close()


class FlinkStream(Flink):
    name = "flink-stream"
    mode = "streaming"
    containers = (*CONTAINERS, REDPANDA)

    def check(self) -> str | None:
        try:
            import confluent_kafka  # noqa: F401
        except ImportError:
            return "confluent-kafka is not installed; run: uv sync --all-packages --extra engines"
        why = super().check()
        if why:
            return why
        try:
            _admin().list_topics(timeout=5)
        except Exception:  # noqa: BLE001 — KafkaException, or a timeout
            return f"Redpanda does not answer at {BROKERS}; start it with the cluster"
        return None

    def _topic(self, job: Job, table: str | None = None) -> str:
        base = f"{job.cfg.name}-{job.cfg.version}-{job.out.name}"
        return f"{base}-log" if table is None else f"{base}-{table}"

    def prepare(self, job: Job) -> float:
        t0 = time.perf_counter()
        replay_log(job.root, self._topic(job))
        for t in job.columns:
            create_topic(self._topic(job, t))
        return time.perf_counter() - t0

    def source(self, job: Job) -> str:
        return (f"CREATE TABLE log (seq BIGINT, event_time TIMESTAMP_LTZ(6), event_type STRING, "
                f"entity_type STRING, entity_key STRING, schema_version INT, payload STRING) "
                f"WITH ('connector' = 'kafka', 'topic' = {lit(self._topic(job))}, "
                f"'properties.bootstrap.servers' = '{INSIDE}', "
                f"'scan.startup.mode' = 'earliest-offset', "
                f"'scan.bounded.mode' = 'latest-offset', 'format' = 'json')")

    def sink_with(self, job: Job, table: str) -> str:
        return (f"'connector' = 'kafka', 'topic' = {lit(self._topic(job, table))}, "
                f"'properties.bootstrap.servers' = '{INSIDE}', 'format' = 'debezium-json'")

    def collect(self, job: Job, tables: list[str], errors: dict[str, str]) -> float:
        t0 = time.perf_counter()
        try:
            for t in tables:
                try:
                    folded = fold(read_topic(self._topic(job, t)), job.columns[t])
                except (FoldError, RuntimeError, ValueError) as e:
                    errors[t] = str(e)
                    continue
                d = job.table_dir(t)
                d.mkdir(parents=True, exist_ok=True)
                pq.write_table(folded, d / "part-0.parquet")
        finally:
            delete_topics([self._topic(job), *(self._topic(job, t) for t in job.columns)])
        return time.perf_counter() - t0
