"""Standard library for kernels and packs (checked arithmetic, sources, handoff)."""

from neorisk_simkit.spec import law
from neorisk_simkit.spec.sources import generated
from neorisk_simkit.std import handoff
from neorisk_simkit.std.checked import (
    I64_MAX,
    I64_MIN,
    NULL,
    checked_add,
    checked_max,
    checked_min,
    checked_mul,
    checked_sub,
)
from neorisk_simkit.std.sources import catalog, devices, stock

__all__ = [
    "I64_MAX",
    "I64_MIN",
    "NULL",
    "catalog",
    "checked_add",
    "checked_max",
    "checked_min",
    "checked_mul",
    "checked_sub",
    "devices",
    "generated",
    "handoff",
    "law",
    "stock",
]
