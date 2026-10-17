"""Constants shared by the io modules (sealing, writing, indexing, replay, checks)."""

from __future__ import annotations

import pyarrow as pa

from neorisk_simkit.std.checked import I64_MAX, NULL

TS = pa.timestamp("us", tz="UTC")              # every exported time column

__all__ = ["I64_MAX", "NULL", "TS"]
