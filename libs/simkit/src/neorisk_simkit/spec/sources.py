"""Row sources for static (read-only) tables."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

import numpy as np

from neorisk_simkit.spec.dist import Dist, sample_np

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
        from neorisk_simkit.engine import rng  # lazy: engine imports spec.dist

        if n_rows != self.n:
            raise ValueError(f"row count {n_rows} does not match source n={self.n}")
        out: dict[str, np.ndarray] = {}
        for name, d in self.cols.items():
            col_stream = rng.mix(stream, rng.name_key(name))
            u = rng.uniforms(seed, col_stream, n_rows)
            u2 = rng.uniforms(seed, col_stream, n_rows, offset=n_rows)
            out[name] = sample_np(d, u, u2)
        return out


def generated(n: int, cols: dict[str, Dist]) -> Source:
    """A table of `n` rows whose columns are drawn independently from `cols`."""
    if n < 0:
        raise ValueError("n must be >= 0")
    for name, d in cols.items():
        if not isinstance(d, Dist):
            raise TypeError(f"column {name!r}: expected a Dist, got {type(d).__name__}")
    return GeneratedSource(n=int(n), cols=MappingProxyType(dict(cols)))
