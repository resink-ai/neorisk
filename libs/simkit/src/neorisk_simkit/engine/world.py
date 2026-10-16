"""World state layout: the hidden-array table, its allocation (Task 8); `World` arrives in Task 9."""

from __future__ import annotations

from typing import Any

import numpy as np

# (name, numpy dtype name, per-slot multiplicity: 1, "A" = max processes per partition type,
# "N_NS" = number of id namespaces). The cap formula and the allocation both read this table.
HIDDEN_DTYPES: tuple[tuple[str, str, int | str], ...] = (
    ("pid", "int64", 1),
    ("ptype", "int16", 1),
    ("lslot", "int32", 1),
    ("gen", "uint32", 1),
    ("alive", "uint8", 1),
    ("clock", "int64", 1),
    ("rseq", "int32", 1),
    ("cseq", "int64", 1),
    ("pending", "int32", 1),
    ("qhead", "int32", 1),
    ("inst", "int64", 1),
    ("self_id", "int64", 1),
    ("occ", "uint32", "A"),
    ("ordn", "int32", "N_NS"),
    ("retire_at", "int64", 1),
    ("susp_t", "int64", 1),
    ("susp_delta", "int64", 1),
)


def hidden_bytes(a: int, n_ns: int) -> int:
    """Bytes of hidden partition arrays per global slot."""
    mult = {"A": a, "N_NS": n_ns}
    return sum(np.dtype(dt).itemsize * (m if isinstance(m, int) else mult[m])
               for _, dt, m in HIDDEN_DTYPES)


# Fill value per hidden array; every other array starts at 0.
_I64_MAX = int(np.iinfo(np.int64).max)
_FILL = {"qhead": -1, "retire_at": _I64_MAX, "susp_t": _I64_MAX}


class Hidden:
    """Engine-owned per-slot arrays, one attribute per `HIDDEN_DTYPES` row (length G)."""

    def __init__(self, arrays: dict[str, np.ndarray]):
        for name, _, _ in HIDDEN_DTYPES:
            setattr(self, name, arrays[name])


def hidden_dims(plan: Any) -> dict[str, int]:
    """Resolved multiplicities: A = max processes per partition type, N_NS = id namespaces."""
    per_type: dict[str, int] = {}
    for p in plan.processes:
        per_type[p.partition] = per_type.get(p.partition, 0) + 1
    return {"A": max(1, max(per_type.values(), default=1)), "N_NS": len(plan.namespaces)}


def allocate_hidden(plan: Any, run: Any = None) -> tuple[Hidden, dict[str, int]]:
    """Allocate every hidden array for G = sum(owner max_live) + sum(shard n) global slots.

    Owner slot ranges come first in plan order, then shards; returns `slot_base` per type.
    """
    slot_base: dict[str, int] = {}
    g = 0
    for kind in ("owner", "shard"):
        for part in plan.partitions:
            if part.kind == kind:
                slot_base[part.name] = g
                g += part.max_live if kind == "owner" else part.n
    dims = hidden_dims(plan)
    arrays = {}
    for name, dt, mult in HIDDEN_DTYPES:
        shape = (g,) if mult == 1 else (g, mult if isinstance(mult, int) else dims[mult])
        arrays[name] = np.full(shape, _FILL.get(name, 0), np.dtype(dt))
    return Hidden(arrays), slot_base
