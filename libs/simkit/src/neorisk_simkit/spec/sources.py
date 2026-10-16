"""Row sources for static (read-only) tables."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

import numpy as np

from neorisk_simkit.spec.dist import Dist, sample_np
from neorisk_simkit.spec.types import cat_code

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


@dataclass(frozen=True)
class RowsSource(Source):
    """A table given row by row: one value list per column; `cat` columns take labels."""

    n: int
    cols: Mapping[str, tuple]

    def generate(self, n_rows: int, table: TableDef, seed: int,
                 stream: int) -> dict[str, np.ndarray]:
        if n_rows != self.n:
            raise ValueError(f"row count {n_rows} does not match source n={self.n}")
        kinds = {c.name: c.ltype for c in table.cols}
        missing = sorted(set(kinds) - set(self.cols))
        if missing:
            raise ValueError(f"table {table.name}: rows() gives no values for columns {missing}")
        out: dict[str, np.ndarray] = {}
        for name, values in self.cols.items():
            lt = kinds[name]
            if lt.kind == "cat":
                out[name] = np.array([cat_code(lt, str(v)) for v in values], np.int64)
            else:
                out[name] = np.asarray(values)
        return out


def rows(**cols: list) -> Source:
    """A table of explicit rows: `cols` maps each column to its values, all lists equal length."""
    lengths = {name: len(v) for name, v in cols.items()}
    if not lengths:
        raise ValueError("rows() needs at least one column")
    if len(set(lengths.values())) != 1:
        raise ValueError(f"rows(): columns differ in length {lengths}")
    n = next(iter(lengths.values()))
    return RowsSource(n=n, cols=MappingProxyType({k: tuple(v) for k, v in cols.items()}))
