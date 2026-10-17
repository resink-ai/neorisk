"""Pack-time sources and recipes: `catalog`, `devices`, `stock`.

Everything here is numpy code that runs while a `World` is built, drawing from `rng.uniforms`
streams keyed by table / recipe name; nothing here runs in kernels.

Recipe protocol (objects passed as `population(refs={...})` values or as a shard's `init=`;
`engine.layout`, `engine.world`, `engine.run` and `spec.caps` call it duck-typed):

- `read_column_names(table) -> tuple[str, ...]` (plan time): extra read columns the recipe adds
  to `table`; `layout` puts them after the table's own columns.
- `max_table_rows(table, n_owners) -> int | None` (plan time): an upper bound on the rows of a
  table the recipe builds (`None` for tables it does not build); `spec.caps` sizes with it.
- refs recipes: `max_csr_entries(n_owners) -> int` (plan time): an upper bound on the int64
  entries of its owner CSR (`offs` plus `idx`); `spec.caps` counts them as read inputs.
- build time, called once by `World.build` before any of the accessors below:
  population refs: `generate(plan=, seed=, stream=, owner_times=)`;
  shard init: `init(n_items=, n_shards=, seed=, stream=, item_weights=) -> {field: values}`
  (per-item fields in items-table row order).
- `extra_read_columns(table) -> {column: array}` and `table_rows(table) -> {column: array} | None`
  (build time, after generation); refs recipes also give `csr() -> (offs, idx)`.

Sources (`Source` objects of a table) that set a non-None `weight` attribute make `layout` add
the read column `cumw` to that table, so they must implement `row_weights(seed, stream) ->
float64[n]` (positive view weight per row); `World` builds `cumw` from it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

import numpy as np

from neorisk_simkit.spec import dist as _dist
from neorisk_simkit.spec.dist import Dist, sample_np
from neorisk_simkit.spec.sources import GeneratedSource, Source
from neorisk_simkit.spec.types import cat_code


def _rng():
    from neorisk_simkit.engine import rng  # lazy: engine imports spec, spec imports std

    return rng


def _uniforms(seed: int, stream: int, part: str, n: int) -> tuple[np.ndarray, np.ndarray]:
    rng = _rng()
    s = rng.mix(stream, rng.name_key(part))
    return rng.uniforms(seed, s, n), rng.uniforms(seed, s, n, offset=n)


def _draw(d: Dist, seed: int, stream: int, part: str, n: int) -> np.ndarray:
    """`n` draws of `d`; categorical draws are mapped to their labels."""
    v = sample_np(d, *_uniforms(seed, stream, part, n))
    if d.kind == _dist.CATEGORICAL:
        return np.asarray(d.labels)[v]
    return v


# ---------------------------------------------------------------------------- catalog
@dataclass(frozen=True)
class CatalogSource(GeneratedSource):
    """A generated table plus per-row view weights (`weight`): `zipf(s)` over a keyed random
    permutation of the rows. `World` turns them into the read column `cumw`."""
    weight: Dist | None = None
    hot_rows: int = 0

    def generate(self, n_rows: int, table: Any, seed: int,
                 stream: int) -> dict[str, np.ndarray]:
        out = super().generate(n_rows, table, seed, stream)
        cols = {c.name: c.ltype for c in table.cols}
        for name, d in self.cols.items():               # categorical labels -> category codes
            lt = cols.get(name)
            if d.kind == _dist.CATEGORICAL and lt is not None and lt.kind == "cat":
                codes = np.array([cat_code(lt, str(x)) for x in d.labels], np.int64)
                out[name] = codes[out[name]]
        if self.hot_rows:                               # hot SKU group (D53)
            out["sku_group"][:self.hot_rows] = 0
        return out

    def row_weights(self, seed: int, stream: int) -> np.ndarray:
        """View weight per row (float64, positive)."""
        u, _ = _uniforms(seed, stream, "weight", self.n)
        rank = np.empty(self.n, np.int64)
        rank[np.argsort(u, kind="stable")] = np.arange(self.n)
        return 1.0 / (rank + 1.0) ** self.weight.params[0]


def catalog(n: int, category: Dist, price: Dist, group: Dist, weight: Dist,
            hot_rows: int = 0) -> Source:
    """A catalog of `n` items with columns `category`, `price`, `sku_group` and view weights
    `weight` (a `dist.zipf`) for `ctx.reads.<t>.sample_by_weight`. Rows `[0, hot_rows)` are
    the hot SKU group 0 (D53); other rows draw `sku_group` from `group`."""
    if n < 1:
        raise ValueError("catalog needs n >= 1")
    if not 0 <= hot_rows <= n:
        raise ValueError("hot_rows must be in [0, n]")
    cols = {"category": category, "price": price, "sku_group": group}
    for name, d in (*cols.items(), ("weight", weight)):
        if not isinstance(d, Dist):
            raise TypeError(f"catalog {name}: expected a Dist, got {type(d).__name__}")
    if weight.kind != _dist.ZIPF:
        raise ValueError("catalog weight must be dist.zipf(s=...)")
    return CatalogSource(n=int(n), cols=MappingProxyType(cols), weight=weight,
                         hot_rows=int(hot_rows))


# ---------------------------------------------------------------------------- devices
_KINDS = {"phone": 0.55, "tablet": 0.10, "desktop": 0.35}
_OS = {"phone": {"ios": 0.45, "android": 0.55}, "tablet": {"ios": 0.6, "android": 0.4},
       "desktop": {"windows": 0.7, "macos": 0.25, "linux": 0.05}}


def _count_bound(d: Dist) -> int:
    """Largest count `d` can draw (categorical labels or uniform_int bounds)."""
    if d.kind == _dist.CATEGORICAL:
        labels = [int(x) for x in d.labels]
        lo, hi = min(labels), max(labels)
    elif d.kind == _dist.UNIFORM_INT:
        lo, hi = int(d.params[0]), int(d.params[1])
    else:
        raise ValueError("devices per_user must be dist.categorical({count: p}) or "
                         "dist.uniform_int(lo, hi)")
    if lo < 1:
        raise ValueError("devices per_user must draw at least 1 device")
    return hi


class DevicesRecipe:
    """Device rows (`os`, `kind`, `first_seen`) and the owner -> device CSR (see `devices`)."""

    def __init__(self, per_user: Dist, table: str, share: float,
                 kinds: Mapping[str, float]):
        self.per_user, self.table, self.share = per_user, table, float(share)
        self.kinds = dict(kinds)
        self.max_per_user = _count_bound(per_user)
        self._rows: dict[str, np.ndarray] | None = None
        self._csr: tuple[np.ndarray, np.ndarray] | None = None

    # plan time
    def read_column_names(self, table: str) -> tuple[str, ...]:
        return ()

    def max_table_rows(self, table: str, n_owners: int) -> int | None:
        return n_owners * self.max_per_user if table == self.table else None

    def max_csr_entries(self, n_owners: int) -> int:
        """`offs` (n + 1) plus `idx` (own devices and at most one shared device per owner)."""
        return (n_owners + 1) + n_owners * (self.max_per_user + 1)

    # build time
    def generate(self, *, plan: Any, seed: int, stream: int, owner_times: np.ndarray) -> None:
        tdef = plan.table(self.table)
        lt = {c.name: c.ltype for c in tdef.cols}
        for col in ("os", "kind", "first_seen"):
            if col not in lt:
                raise ValueError(f"devices: table {self.table!r} has no column {col!r}")
        times = np.asarray(owner_times, np.int64)
        n = len(times)
        m = _draw(self.per_user, seed, stream, "count", n).astype(np.int64)
        own_off = np.zeros(n + 1, np.int64)
        own_off[1:] = np.cumsum(m)
        total = int(own_off[-1])
        owner = np.repeat(np.arange(n, dtype=np.int64), m)

        kind_labels = list(self.kinds)
        kind_i = sample_np(_dist.categorical(self.kinds), *_uniforms(seed, stream, "kind", total))
        kind = np.array([cat_code(lt["kind"], k) for k in kind_labels], np.int64)[kind_i]
        u_os = _uniforms(seed, stream, "os", total)[0]
        os_ = np.zeros(total, np.int64)
        for i, k in enumerate(kind_labels):                 # os consistent with the kind
            hit = kind_i == i
            codes = np.array([cat_code(lt["os"], o) for o in _OS[k]], np.int64)
            cum = np.cumsum(list(_OS[k].values()))
            os_[hit] = codes[np.minimum(np.searchsorted(cum, u_os[hit], side="right"),
                                        len(codes) - 1)]

        # households: a `share` of owners also use one device of the previous owner
        u_share, u_pick = _uniforms(seed, stream, "share", n)
        extra = (u_share < self.share) & (np.arange(n) > 0)
        offs = np.zeros(n + 1, np.int64)
        offs[1:] = np.cumsum(m + extra)
        idx = np.empty(int(offs[-1]), np.int64)
        dev = np.arange(total, dtype=np.int64)
        idx[offs[owner] + dev - own_off[owner]] = dev
        sharer = np.flatnonzero(extra)
        prev = sharer - 1
        pick = np.minimum((u_pick[sharer] * m[prev]).astype(np.int64), m[prev] - 1)
        idx[offs[sharer] + m[sharer]] = own_off[prev] + pick
        self._rows = {"os": os_, "kind": kind, "first_seen": times[owner]}
        self._csr = (offs, idx)

    def _built(self) -> None:
        if self._rows is None:
            raise RuntimeError("devices recipe used before World.build generated it")

    def csr(self) -> tuple[np.ndarray, np.ndarray]:
        self._built()
        return self._csr

    def table_rows(self, table: str) -> dict[str, np.ndarray] | None:
        if table != self.table:
            return None
        self._built()
        return dict(self._rows)

    def extra_read_columns(self, table: str) -> dict[str, np.ndarray]:
        return {}


def devices(per_user: Dist, table: str, share: float,
            kinds: dict[str, float] | None = None) -> DevicesRecipe:
    """Devices of a population's owners, as population `refs`: each owner gets `per_user` own
    devices (kind from `kinds`, os consistent with the kind, `first_seen` = owner arrival), and
    a `share` of owners also reuse one device of the previous owner (a household). Kernels use
    `ctx.refs.<name>.count(id)`, `.get(id, j)`, `.pick(id, u)`."""
    if not isinstance(per_user, Dist):
        raise TypeError("devices per_user must be a Dist")
    if not 0.0 <= share <= 1.0:
        raise ValueError("devices share must be in [0, 1]")
    kinds = dict(_KINDS if kinds is None else kinds)
    unknown = sorted(set(kinds) - set(_OS))
    if unknown:
        raise ValueError(f"devices kinds must be among {sorted(_OS)}, got {unknown}")
    if abs(sum(kinds.values()) - 1.0) > 1e-9 or any(p < 0 for p in kinds.values()):
        raise ValueError("devices kinds must be probabilities summing to 1")
    return DevicesRecipe(per_user, table, share, kinds)


# ---------------------------------------------------------------------------- stock
class StockRecipe:
    """Initial `on_hand` / `reserved` of an inventory shard and the read column `stock_target`
    on its items table (see `stock`). `Pack.shard` binds it to the items table (`bind`)."""

    def __init__(self, initial: Dist, by_weight: float, items: str | None = None):
        self.initial, self.by_weight, self.items = initial, float(by_weight), items
        self._target: np.ndarray | None = None

    def bind(self, *, items: str | None) -> StockRecipe:
        """The recipe for a shard whose items are the rows of table `items`."""
        if items is None:
            raise ValueError("std.stock needs a shard with items=")
        return StockRecipe(self.initial, self.by_weight, items)

    # plan time
    def read_column_names(self, table: str) -> tuple[str, ...]:
        return ("stock_target",) if table == self.items else ()

    def max_table_rows(self, table: str, n_owners: int) -> int | None:
        return None

    # build time
    def init(self, *, n_items: int, n_shards: int, seed: int, stream: int,
             item_weights: np.ndarray | None = None) -> dict[str, np.ndarray]:
        """`on_hand` = negbinom draw + `rint(by_weight * mean * w / max(w))` (w = the items'
        view weights, when the items table has them: a bonus added, not a factor, so a hot item
        that draws little stock is still stocked); `reserved` = 0. Per item row."""
        on_hand = sample_np(self.initial, *_uniforms(seed, stream, "on_hand", n_items))
        on_hand = on_hand.astype(np.float64)
        if item_weights is not None and n_items and self.by_weight:
            w = np.asarray(item_weights, np.float64)
            on_hand += np.rint(self.by_weight * self.initial.params[0] * w / w.max())
        on_hand = np.minimum(np.rint(on_hand), np.iinfo(np.int32).max).astype(np.int32)
        self._target = on_hand.copy()
        return {"on_hand": on_hand, "reserved": np.zeros(n_items, np.int32)}

    def table_rows(self, table: str) -> dict[str, np.ndarray] | None:
        return None

    def extra_read_columns(self, table: str) -> dict[str, np.ndarray]:
        if table != self.items:
            return {}
        if self._target is None:
            raise RuntimeError("stock recipe used before World.build generated it")
        return {"stock_target": self._target}


def stock(initial: Dist, by_weight: float = 0.0) -> StockRecipe:
    """Shard `init=` for per-item `on_hand` / `reserved` (`i32[<items>]`): `on_hand` starts at an
    `initial` draw (a `dist.negbinom`) plus a bonus of up to `by_weight` × its mean for heavily
    viewed items (proportional to view weight);
    `reserved` starts at 0. Adds the read column `stock_target` (= initial stock) to the items
    table, the level restocks fill back to."""
    if not isinstance(initial, Dist) or initial.kind != _dist.NEGBINOM:
        raise ValueError("stock initial must be dist.negbinom(mean=..., disp=...)")
    if by_weight < 0:
        raise ValueError("stock by_weight must be >= 0")
    return StockRecipe(initial, by_weight)
