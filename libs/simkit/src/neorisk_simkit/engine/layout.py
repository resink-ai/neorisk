"""Per-process tuple layouts that kernel lowering (Task 6) and code generation (Task 8) share.

A `KernelLayout` says where every name of the authoring surface lives in the tuples passed to a
lowered kernel (`ctx`, `s`, `loc`, `cmd`) and which emitters / boundaries / namespaces exist.
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass, field
from typing import Any

from neorisk_simkit.engine.errors import LoweringError
from neorisk_simkit.spec.dist import Dist
from neorisk_simkit.spec.plan import Column, Plan
from neorisk_simkit.spec.types import COMMON_COLUMNS, LType

CTX_FIELDS = ("t", "self_id", "pid", "g", "inst", "action", "occ", "kc", "seed", "cfg", "reads",
              "refs", "lamport", "flags")
(CTX_T, CTX_SELF_ID, CTX_PID, CTX_G, CTX_INST, CTX_ACTION, CTX_OCC, CTX_KC, CTX_SEED, CTX_CFG,
 CTX_READS, CTX_REFS, CTX_LAMPORT, CTX_FLAGS) = range(len(CTX_FIELDS))
CMD_FIELDS = ("kind", "tag", "time", "cursor", "sender")
CMD_PAY = 5
CMD_PAY_ROW = 6
# rng sites >= this are reserved for engine draws (send/response latency keys 30000 + boundary);
# kernel `site=` literals must lie in [0, ENGINE_SITE_BASE).
ENGINE_SITE_BASE = 30000


def make_ctx(t, self_id, pid, g, inst, action, occ, kc, seed, cfg, reads, refs, lamport,
             flags) -> tuple:
    """The `ctx` tuple passed to lowered kernels, in `CTX_FIELDS` order."""
    return (t, self_id, pid, g, inst, action, occ, kc, seed, cfg, reads, refs, lamport, flags)


# Owner state tuple: (lslot, col_0, ...). Shard state tuple: (index, off, n, items, field_0, ...).
OWNER_STATE_BASE = 1
SHARD_INDEX, SHARD_OFF, SHARD_N, SHARD_ITEMS, SHARD_STATE_BASE = range(5)

PAYLOAD_USER_COLS = 7          # pay arena columns 0..6 are user payload; 7..11 are engine-owned
_STATE_RE = re.compile(r"^(\w+?)(?:\[(\w+)\])?$")
_N_COMMON = len(COMMON_COLUMNS)


@dataclass(frozen=True)
class KernelLayout:
    name: str                                         # process name
    partition_kind: str                               # "owner" | "shard"
    state_fields: dict[str, int]                      # scalar state: s[idx][s[0]]
    state_cats: dict[str, tuple[str, ...]]            # cat-typed owner columns -> categories
    array_fields: dict[str, int]                      # shard per-item state: s[idx][s[1] + i]
    items_name: str | None                            # shard items table (s.n_<it>, s.<it>[i])
    local_fields: dict[str, tuple[int, int]]          # name -> (tuple index, width)
    cfg_fields: dict[str, int]                        # top-level config field -> index
    cfg_nested: dict[str, dict]                       # dotted path of nested dataclass -> fields
    reads: dict[str, dict[str, int]]                  # local read name -> column -> reads index
    refs: dict[str, int]                              # local refs name -> j (offs j, idx j+1)
    payload_slots: dict[str, int]                     # inbound payload name -> pay column
    events: dict[str, list[tuple[str, LType]]]        # this partition's events, no common cols
    creates: dict[str, list[tuple[str, LType]] | None]  # every namespace in code order
    requests: dict[str, list[str]]                    # local request name -> payload names
    messages: dict[str, list[str]]                    # local message name -> payload names
    responses: dict[str, list[str]]                   # handled request boundary -> responses
    change_groups: dict[str, list[tuple[str, LType]]]
    # --- beyond the plan's field list: what lowering needs to finish the job
    read_n: dict[str, int | None] = field(default_factory=dict)   # fixed row count or None
    read_cats: dict[str, dict[str, tuple[str, ...]]] = field(default_factory=dict)
    boundary_of: dict[str, str] = field(default_factory=dict)     # request/message local -> b
    out_payload: dict[str, list[tuple[str, LType]]] = field(default_factory=dict)  # by b
    response_payload: dict[str, list[tuple[str, LType]]] = field(default_factory=dict)  # by b
    resources: tuple[str, ...] = ()                   # resource_names(plan)


def resource_names(plan: Plan) -> list[str]:
    """The reserve vector order shared by lowering (`_reserve_<proc>`) and `SlabSet`."""
    return ([f"records:{e.name}" for e in plan.events]
            + [f"records:{g.name}" for g in plan.change_groups]
            + [f"creates:{ns}" for ns in plan.namespaces]
            + ["timers", "requests"])


def _is_nested(v: Any) -> bool:
    return dataclasses.is_dataclass(v) and not isinstance(v, (type, Dist))


def _cfg_layout(cfg: Any) -> tuple[dict[str, int], dict[str, dict]]:
    if cfg is None:
        return {}, {}
    if not _is_nested(cfg):
        raise LoweringError(f"process config must be a dataclass, got {type(cfg).__name__}")
    nested: dict[str, dict] = {}

    def walk(obj: Any, path: str) -> dict[str, int]:
        out: dict[str, int] = {}
        for i, f in enumerate(dataclasses.fields(obj)):
            out[f.name] = i
            v = getattr(obj, f.name)
            if _is_nested(v):
                sub = f"{path}.{f.name}" if path else f.name
                nested[sub] = walk(v, sub)
        return out

    return walk(cfg, ""), nested


def _recipes(plan: Plan) -> list[Any]:
    """Recipe objects (Task 14 protocol) declared as population refs or shard inits."""
    found = [r for pop in plan.populations for r in pop.refs.values()]
    found += [p.init for p in plan.partitions if p.init is not None]
    return [r for r in found if hasattr(r, "read_column_names")]


def _cols(cols: tuple[Column, ...]) -> list[tuple[str, LType]]:
    return [(c.name, c.ltype) for c in cols]


def _check_width(cols: tuple[Column, ...], where: str) -> None:
    if len(cols) > PAYLOAD_USER_COLS:
        c = cols[PAYLOAD_USER_COLS]
        raise LoweringError(f"payload {c.name!r} needs slot {PAYLOAD_USER_COLS}, but payloads "
                            f"hold at most {PAYLOAD_USER_COLS} fields ({where})")


def _add_slots(slots: dict[str, int], cols: tuple[Column, ...], where: str) -> None:
    _check_width(cols, where)
    for j, c in enumerate(cols):
        if slots.setdefault(c.name, j) != j:
            raise LoweringError(f"payload {c.name!r} has slot {slots[c.name]} and slot {j} "
                                f"({where})")


def _layout(plan: Plan, pd, recipes: list[Any], resources: tuple[str, ...]) -> KernelLayout:
    part = plan.partition(pd.partition)
    state_fields: dict[str, int] = {}
    state_cats: dict[str, tuple[str, ...]] = {}
    array_fields: dict[str, int] = {}
    if part.kind == "owner":
        for i, c in enumerate(plan.table(part.table).cols):
            state_fields[c.name] = OWNER_STATE_BASE + i
            if c.ltype.kind == "cat":
                state_cats[c.name] = c.ltype.values
    else:
        for j, (name, decl) in enumerate(part.state.items()):
            m = _STATE_RE.match(decl)
            per_item = m is not None and m.group(2) is not None
            (array_fields if per_item else state_fields)[name] = SHARD_STATE_BASE + j

    local_fields: dict[str, tuple[int, int]] = {}
    if pd.kernel.local is not None:
        for j, (name, (_, width)) in enumerate(pd.kernel.local.fields.items()):
            local_fields[name] = (1 + j, width)

    cfg_fields, cfg_nested = _cfg_layout(pd.config)

    item_tables = {p.items for p in plan.partitions if p.items is not None}
    reads: dict[str, dict[str, int]] = {}
    read_n: dict[str, int | None] = {}
    read_cats: dict[str, dict[str, tuple[str, ...]]] = {}
    j = 0
    for local, tname in pd.reads.items():
        t = plan.table(tname)
        names = [c.name for c in t.cols]
        for r in recipes:
            names += list(r.read_column_names(tname))
        if tname in item_tables:
            names.append("local_index")
        if t.source is not None and getattr(t.source, "weight", None) is not None:
            names.append("cumw")
        reads[local] = {n: j + i for i, n in enumerate(names)}
        j += len(names)
        fixed = getattr(t.source, "n", None) if t.source is not None else None
        read_n[local] = int(fixed) if fixed is not None else None
        read_cats[local] = {c.name: c.ltype.values for c in t.cols if c.ltype.kind == "cat"}

    refs = {local: 2 * i for i, local in enumerate(pd.refs)}

    slots: dict[str, int] = {}
    for b in (*pd.on_request, *pd.on_message):
        _add_slots(slots, plan.boundary(b).payload, f"process {pd.name}, boundary {b}")
    for b, _ in pd.on_response:
        _add_slots(slots, plan.boundary(b).response_payload,
                   f"process {pd.name}, responses of {b}")

    events = {e.name: _cols(e.cols[_N_COMMON:]) for e in plan.events
              if e.partition == part.name}
    creates: dict[str, list[tuple[str, LType]] | None] = {}
    table_names = {t.name for t in plan.tables}
    for ns in plan.namespaces:
        creates[ns] = _cols(plan.table(ns).cols) if ns in table_names else None

    boundary_of: dict[str, str] = {}
    out_payload: dict[str, list[tuple[str, LType]]] = {}
    requests: dict[str, list[str]] = {}
    messages: dict[str, list[str]] = {}
    for dest, src in ((requests, pd.requests), (messages, pd.messages)):
        for local, b in src.items():
            bd = plan.boundary(b)
            dest[local] = [c.name for c in bd.payload]
            boundary_of[local] = b
            _check_width(bd.payload, f"process {pd.name}, boundary {b}")
            out_payload[b] = _cols(bd.payload)
    responses = {b: list(plan.boundary(b).responses) for b in pd.on_request}
    for b in pd.on_request:
        _check_width(plan.boundary(b).response_payload, f"process {pd.name}, responses of {b}")
    response_payload = {b: _cols(plan.boundary(b).response_payload) for b in pd.on_request}

    change_groups = {g.name: _cols(g.cols) for g in plan.change_groups
                     if part.kind == "owner" and g.table == part.table}

    return KernelLayout(
        name=pd.name, partition_kind=part.kind, state_fields=state_fields, state_cats=state_cats,
        array_fields=array_fields, items_name=part.items if part.kind == "shard" else None,
        local_fields=local_fields, cfg_fields=cfg_fields, cfg_nested=cfg_nested, reads=reads,
        refs=refs, payload_slots=slots, events=events, creates=creates, requests=requests,
        messages=messages, responses=responses, change_groups=change_groups, read_n=read_n,
        read_cats=read_cats, boundary_of=boundary_of, out_payload=out_payload,
        response_payload=response_payload, resources=resources)


def kernel_layouts(plan: Plan) -> dict[str, KernelLayout]:
    """One layout per process, keyed by process name."""
    recipes = _recipes(plan)
    resources = tuple(resource_names(plan))
    return {pd.name: _layout(plan, pd, recipes, resources) for pd in plan.processes}
