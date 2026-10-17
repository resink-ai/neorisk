"""Per-worker output slabs: record, create and outbox buffers that generated emitters fill.

`SlabSet.as_tuple(...)` is the `out` tuple passed to lowered kernels and generated helpers; the
`OUT_*` indices below and `buffer_specs(plan)` are the contract `engine.codegen` generates
against. Capacities are fixed at construction (`max(1, slab_bytes // row_bytes)` per buffer
unless `engine.force_capacity[<resource>]` is set); a full buffer makes a reserve fail, the
runner flushes (`flush()`) or moves the outbox aside and re-invokes the command.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

from neorisk_simkit.engine.cmdq import PAYLOAD_W
from neorisk_simkit.engine.layout import resource_names
from neorisk_simkit.spec import dist as _dist
from neorisk_simkit.spec.plan import Column, Plan
from neorisk_simkit.spec.types import COMMON_COLUMNS, storage_dtype

OB_REQUEST, OB_MESSAGE, OB_RESPONSE, OB_CREATE = 1, 2, 3, 4

# out tuple: fixed head, then one buffer tuple per records/creates resource (resource order),
# then the outbox, the latency table, shard sizes per boundary, the seed and the kind of the
# command being dispatched (set by `dispatch`, read by `_continue_at`).
OUT_HEAD = ("cnt", "cap", "resv", "miss", "reqc", "hid", "pool", "pay", "w")
(OUT_CNT, OUT_CAP, OUT_RESV, OUT_MISS, OUT_REQC, OUT_HID, OUT_POOL, OUT_PAY,
 OUT_W) = range(len(OUT_HEAD))
OUT_TAIL = ("outbox", "lat", "shard_n", "seed", "cmd_kind")

HID_FIELDS = ("rseq", "cseq", "ordn", "gen", "self_id", "pid", "qhead")

# Outbox columns (all int64) followed by `pay int64[cap, PAYLOAD_W]`. For requests and messages
# `resp_kind`/`target_action` name the command kind and process the receiver runs; for
# responses they are the requester's `on_response` command id and process (`cmd.pay[10]`).
OUTBOX_COLS = ("kind", "bnd", "time", "prio", "cause", "src_g", "src_pid", "src_seq", "dst",
               "tag", "resp_kind", "target_action")
OUTBOX_PAY = len(OUTBOX_COLS)
OUTBOX_ROW_BYTES = 8 * len(OUTBOX_COLS) + 8 * PAYLOAD_W

_I64, _I32, _I16, _U8 = np.dtype(np.int64), np.dtype(np.int32), np.dtype(np.int16), np.dtype(np.uint8)
RECORD_HEAD = (("time", _I64), ("lamport", _I64), ("pid", _I64), ("seq", _I32),
               ("action", _I16))
CHANGE_HEAD = (*RECORD_HEAD, ("entity_id", _I64))
CREATE_HEAD = (("handle", _I64), ("pid", _I64), ("ordinal", _I32), ("created_at", _I64),
               ("g", _I64), ("lamport", _I64))      # lamport: the creating commit's (D43)


def const_name(resource: str) -> str:
    """`records:ping` -> `RECORDS_PING` (suffix of the generated `R_*` / `OUT_*` constants)."""
    return re.sub(r"\W", "_", resource).upper()


def slab_dtype(c: Column) -> np.dtype:
    """Slab storage of a column: its storage dtype, except `text` (always null in S1, D18)."""
    return _I64 if c.ltype.kind == "text" else storage_dtype(c.ltype)


@dataclass(frozen=True)
class BufferSpec:
    resource: str                                  # e.g. "records:ping", "creates:note"
    name: str                                      # event / change group / namespace name
    kind: str                                      # "event" | "change" | "create"
    head: tuple[tuple[str, np.dtype], ...]
    cols: tuple[Column, ...]                       # user columns after the head

    @property
    def fields(self) -> list[tuple[str, np.dtype]]:
        """Every array of the buffer, in tuple order: head, columns, `valid_<col>` (nullable)."""
        return ([*self.head] + [(c.name, slab_dtype(c)) for c in self.cols]
                + [(f"valid_{c.name}", _U8) for c in self.cols if c.ltype.nullable])

    @property
    def row_bytes(self) -> int:
        return sum(dt.itemsize for _, dt in self.fields)


def buffer_specs(plan: Plan) -> list[BufferSpec]:
    """One buffer per records/creates resource, in `resource_names(plan)` order."""
    specs = []
    for e in plan.events:
        cols = e.cols[len(COMMON_COLUMNS):]                 # common columns come first
        specs.append(BufferSpec(f"records:{e.name}", e.name, "event", RECORD_HEAD, cols))
    for g in plan.change_groups:
        specs.append(BufferSpec(f"records:{g.name}", g.name, "change", CHANGE_HEAD, g.cols))
    tables = {t.name: t for t in plan.tables}
    for ns in plan.namespaces:
        cols = tables[ns].cols if ns in tables else ()
        specs.append(BufferSpec(f"creates:{ns}", ns, "create", CREATE_HEAD, cols))
    return specs


def out_indices(plan: Plan) -> dict[str, int]:
    """Index in the `out` tuple of every buffer (by resource) and of the `OUT_TAIL` entries."""
    idx = {s.resource: len(OUT_HEAD) + i for i, s in enumerate(buffer_specs(plan))}
    base = len(OUT_HEAD) + len(idx)
    idx.update({name: base + i for i, name in enumerate(OUT_TAIL)})
    return idx


@dataclass(frozen=True)
class StepChunk:
    records: dict[str, dict[str, np.ndarray]]      # event / change group -> column -> rows
    creates: dict[str, dict[str, np.ndarray]]      # namespace -> column -> rows


class SlabSet:
    """The output buffers of one worker."""

    def __init__(self, plan: Plan, engine, worker: int):
        self.worker = int(worker)
        self.resources: list[str] = resource_names(plan)
        n = len(self.resources)
        self.cnt = np.zeros(n, np.int64)
        self.cap = np.zeros(n, np.int64)
        self.resv = np.zeros(n, np.int64)
        self.miss = np.zeros(1, np.int64)
        self.req_count = np.zeros(1, np.int64)
        self.cmd_kind = np.zeros(1, np.int64)
        force = dict(engine.force_capacity)

        def capacity(resource: str, row_bytes: int) -> int:
            if resource in force:
                return int(force[resource])
            return max(1, engine.slab_bytes // row_bytes)

        self.specs = buffer_specs(plan)
        self.buffers: dict[str, dict[str, np.ndarray]] = {}
        for spec in self.specs:
            rows = capacity(spec.resource, spec.row_bytes)
            self.cap[self.resources.index(spec.resource)] = rows
            self.buffers[spec.resource] = {name: np.zeros(rows, dt) for name, dt in spec.fields}

        self._r_requests = self.resources.index("requests")
        rows = capacity("requests", OUTBOX_ROW_BYTES)
        self.cap[self._r_requests] = rows               # "timers" stays 0: it is free_n[w]
        self.outbox = {c: np.zeros(rows, np.int64) for c in OUTBOX_COLS}
        self.outbox_pay = np.zeros((rows, PAYLOAD_W), np.int64)

        self.lat = np.zeros((len(plan.boundaries), 4), np.float64)
        self.shard_n = np.zeros(len(plan.boundaries), np.int64)
        for b in plan.boundaries:
            self.lat[b.code] = _dist.encode(b.latency)
            to = plan.partition(b.to)
            self.shard_n[b.code] = to.n if to.kind == "shard" else 0

    def as_tuple(self, hidden, pool, payload, seed: int = 0) -> tuple:
        """The `out` tuple (see `OUT_HEAD`, `buffer_specs`, `OUT_TAIL`)."""
        hid = tuple(getattr(hidden, n) for n in HID_FIELDS)
        bufs = tuple(tuple(self.buffers[s.resource].values()) for s in self.specs)
        outbox = (*self.outbox.values(), self.outbox_pay)
        return (self.cnt, self.cap, self.resv, self.miss, self.req_count, hid, pool.as_tuple(),
                payload.as_tuple(), self.worker, *bufs, outbox, self.lat, self.shard_n,
                int(seed), self.cmd_kind)

    def flush(self) -> StepChunk:
        """Copy the filled record and create rows out and reset those buffers."""
        records: dict[str, dict[str, np.ndarray]] = {}
        creates: dict[str, dict[str, np.ndarray]] = {}
        for spec in self.specs:
            r = self.resources.index(spec.resource)
            n = int(self.cnt[r])
            rows = {name: a[:n].copy() for name, a in self.buffers[spec.resource].items()}
            (creates if spec.kind == "create" else records)[spec.name] = rows
            self.cnt[r] = 0
        return StepChunk(records, creates)

    def outbox_view(self) -> dict[str, np.ndarray]:
        """Copies of the filled outbox rows (`OUTBOX_COLS` plus `pay`)."""
        n = int(self.cnt[self._r_requests])
        view = {c: a[:n].copy() for c, a in self.outbox.items()}
        view["pay"] = self.outbox_pay[:n].copy()
        return view

    def reset_outbox(self) -> None:
        self.cnt[self._r_requests] = 0
