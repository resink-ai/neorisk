"""Row sources for static (read-only) tables."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

import numpy as np

from neorisk_simkit.spec.dist import Dist

if TYPE_CHECKING:
    from neorisk_simkit.spec.plan import TableDef


class Source:
    """Produces the rows of a static table. `n` is the fixed row count, or None if unknown."""

    n: int | None = None
    cols: Mapping[str, Dist] = MappingProxyType({})

    def generate(self, n_rows: int, table: TableDef, seed: int,
                 stream: int) -> dict[str, np.ndarray]:
        raise NotImplementedError


@dataclass(frozen=True)
class GeneratedSource(Source):
    n: int
    cols: Mapping[str, Dist]

    def generate(self, n_rows: int, table: TableDef, seed: int,
                 stream: int) -> dict[str, np.ndarray]:
        raise NotImplementedError("generated sources are sampled from Task 5 on")


def generated(n: int, cols: dict[str, Dist]) -> Source:
    """A table of `n` rows whose columns are drawn independently from `cols`."""
    if n < 0:
        raise ValueError("n must be >= 0")
    for name, d in cols.items():
        if not isinstance(d, Dist):
            raise TypeError(f"column {name!r}: expected a Dist, got {type(d).__name__}")
    return GeneratedSource(n=int(n), cols=MappingProxyType(dict(cols)))
