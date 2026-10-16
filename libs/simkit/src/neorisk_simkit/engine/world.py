"""World state layout. Task 8 adds the `World` class; this module owns the hidden-array table."""

from __future__ import annotations

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
