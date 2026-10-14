# Synthetic Event Data Generator + Baseline Bench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a framework lib (`neorisk-simkit`), a data-generator app (`datagen`, fraud scenario first) and a baseline benchmark app (`bench`) that produce and evaluate synthetic tabular event data with hidden, exactly-known golden features.

**Architecture:** `libs/simkit` holds scenario-agnostic primitives (attribute timelines, entities, reference columns, point-in-time rolling features, scorers, export). `apps/datagen` composes them in a Python scenario module (`fraud`) and exposes a CLI. `apps/bench` reads only the exported `events.parquet` (plus golden features only under `--oracle`) and reports baseline metrics.

**Tech Stack:** Python 3.12, uv workspace, polars, numpy, xgboost, scikit-learn, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-10-13-ml-sim-datagen-design.md`

**Spec refinements made by this plan** (applied to the spec in Task 11):
- Lib import name follows repo convention: dist `neorisk-simkit`, import `neorisk_simkit`.
- Scenario modules expose `generate(cfg) -> Dataset` (instead of `build(config) -> Scenario`).
- Entities carry an integer `idx` (rank by creation time) internally; UUID strings are attached at the end.
- `MLPScorer` is a seeded, untrained random-weight MLP (preset parameters, no training).

## Global Constraints

- Python `>=3.12`; ruff `line-length = 100` (root `pyproject.toml`).
- Workspace members are `libs/*` and `apps/*`; apps depend on libs with `{ workspace = true }`.
- Build backend is `uv_build>=0.11.26,<0.12.0` (same as `libs/core`, `apps/hello`).
- pytest `testpaths = ["libs", "apps"]`: test file basenames must be unique across the repo (no `__init__.py` in test dirs).
- Attribute values are synthetic integers; IDs are UUID strings; no real-world values.
- Same seed must reproduce byte-identical datasets (single `np.random.Generator` threaded through; `n_jobs=1` for xgboost).
- Golden features must never appear in `events.parquet`; rolling features are strictly point-in-time (window `[t - w, t)`).
- Commit messages end with the attribution trailers required by the session (`Co-Authored-By: ...`, `Claude-Session: ...`).

## Review Focus

Failure modes the spec implies but a straight-line implementation tends to miss (each is pinned by a test in the owning task):
1. **No eligible entity at event time** (event before any entity exists, tiny datasets): references resolve to null, no crash (Task 4).
2. **Identical timestamps**: rolling windows exclude all rows at time `t`, regardless of row order (Task 5).
3. **Null keys** (null `product_id`, `inviter_id`, `device_id`): rolling and as-of joins skip them and yield null/0 features, no crash (Tasks 3, 5).
4. **Single-class split** in bench (tiny data, all-good test slice): metrics are NaN, not an exception (Task 10).
5. **Zero-variance golden feature** in scorer standardisation: no NaN/inf scores (Task 6).

## File Structure

```
libs/simkit/
  pyproject.toml
  src/neorisk_simkit/{__init__,ids,attributes,entities,references,features,scorer,export}.py
  src/neorisk_simkit/py.typed
  tests/test_simkit_{ids_attributes,entities,references,features,scorer,export}.py
apps/datagen/
  pyproject.toml
  src/datagen/{__init__,config,cli}.py
  src/datagen/scenarios/{__init__,fraud}.py
  tests/test_datagen_{fraud,cli}.py
apps/bench/
  pyproject.toml
  src/bench/{__init__,runner,cli}.py
  tests/test_bench_runner.py
```

---

### Task 1: Scaffold simkit lib

**Files:**
- Create: `libs/simkit/pyproject.toml`, `libs/simkit/README.md`, `libs/simkit/src/neorisk_simkit/__init__.py`, `libs/simkit/src/neorisk_simkit/py.typed`

**Interfaces:**
- Produces: importable package `neorisk_simkit`; later tasks add modules and re-export from `__init__`.

- [ ] **Step 1: Create files**

`libs/simkit/pyproject.toml`:
```toml
[project]
name = "neorisk-simkit"
version = "0.1.0"
description = "Framework for generating synthetic tabular event data with hidden golden features"
readme = "README.md"
requires-python = ">=3.12"
dependencies = ["numpy>=1.26", "polars>=1.0", "xgboost>=2.0"]

[build-system]
requires = ["uv_build>=0.11.26,<0.12.0"]
build-backend = "uv_build"
```
`libs/simkit/README.md`: `# neorisk-simkit` plus one line: "Scenario-agnostic primitives: attribute timelines, entities, reference columns, point-in-time rolling features, scorers, export."
`libs/simkit/src/neorisk_simkit/__init__.py`: empty docstring `"""Synthetic event data framework."""`
`libs/simkit/src/neorisk_simkit/py.typed`: empty file.

- [ ] **Step 2: Sync and import**

Run: `uv sync --all-packages && uv run python -c "import neorisk_simkit, polars, numpy, xgboost; print('ok')"`
Expected: prints `ok`. If xgboost fails on macOS with a libomp error, run `brew install libomp` and retry.

- [ ] **Step 3: Commit**

```bash
git add libs/simkit uv.lock
git commit -m "chore: scaffold neorisk-simkit lib"
```

---

### Task 2: IDs and attribute timelines

**Files:**
- Create: `libs/simkit/src/neorisk_simkit/ids.py`, `libs/simkit/src/neorisk_simkit/attributes.py`
- Test: `libs/simkit/tests/test_simkit_ids_attributes.py`

**Interfaces:**
- Produces:
  - `make_uuids(n: int, rng: np.random.Generator) -> list[str]`
  - `Cardinality` (`LOW`, `HIGH`), `Volatility` (`STATIC`, `SLOW`, `FAST`) str-enums
  - `AttrSpec(name, cardinality=LOW, volatility=STATIC, k=None)` with `.size` (k or default 10 / 1_000_000)
  - `sample_timeline(spec: AttrSpec, created_at: np.ndarray[datetime64[us]], t1: np.datetime64, rng) -> pl.DataFrame` with columns `idx:Int64, valid_from:Datetime(us), value:Int64`, sorted by `(idx, valid_from)`; first row per idx has `valid_from == created_at[idx]`.

- [ ] **Step 1: Write the failing tests**

```python
import numpy as np
import polars as pl

from neorisk_simkit.attributes import AttrSpec, Cardinality, Volatility, sample_timeline
from neorisk_simkit.ids import make_uuids

T0 = np.datetime64("2026-01-01T00:00:00", "us")
T1 = T0 + np.timedelta64(90, "D")


def _timeline(spec, n=300, seed=0):
    created = np.full(n, T0)
    return sample_timeline(spec, created, T1, np.random.default_rng(seed))


def test_uuids_unique_and_deterministic():
    a = make_uuids(100, np.random.default_rng(1))
    b = make_uuids(100, np.random.default_rng(1))
    assert a == b and len(set(a)) == 100 and len(a[0]) == 36


def test_static_attribute_never_changes():
    df = _timeline(AttrSpec("os", Cardinality.LOW, Volatility.STATIC, k=4))
    assert df.height == 300
    assert df["value"].min() >= 0 and df["value"].max() < 4


def test_fast_changes_more_than_slow():
    slow = _timeline(AttrSpec("s", Cardinality.LOW, Volatility.SLOW, k=50))
    fast = _timeline(AttrSpec("f", Cardinality.LOW, Volatility.FAST, k=10))
    assert fast.height > slow.height > 300


def test_fast_low_cardinality_is_random_walk():
    df = _timeline(AttrSpec("battery", Cardinality.LOW, Volatility.FAST, k=10))
    steps = df.sort("idx", "valid_from").with_columns(d=pl.col("value").diff().over("idx"))
    assert steps["d"].drop_nulls().abs().max() <= 1


def test_first_row_at_created_at_and_sorted():
    created = np.sort(T0 + (np.arange(50) * 3600_000_000).astype("timedelta64[us]"))
    df = sample_timeline(
        AttrSpec("x", Cardinality.HIGH, Volatility.SLOW), created, T1, np.random.default_rng(3)
    )
    first = df.group_by("idx").agg(pl.col("valid_from").min()).sort("idx")
    assert (first["valid_from"].to_numpy() == created).all()
    assert df.equals(df.sort("idx", "valid_from"))
    assert df["value"].max() < 1_000_000


def test_same_seed_same_timeline():
    spec = AttrSpec("x", Cardinality.LOW, Volatility.FAST)
    assert _timeline(spec, seed=5).equals(_timeline(spec, seed=5))
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest libs/simkit/tests/test_simkit_ids_attributes.py -v`
Expected: FAIL (`ModuleNotFoundError: neorisk_simkit.ids`)

- [ ] **Step 3: Implement**

`ids.py`:
```python
import uuid

import numpy as np


def make_uuids(n: int, rng: np.random.Generator) -> list[str]:
    """Deterministic version-4 UUID strings drawn from ``rng``."""
    raw = rng.bytes(16 * n)
    return [str(uuid.UUID(bytes=raw[i * 16 : (i + 1) * 16], version=4)) for i in range(n)]
```

`attributes.py`:
```python
from dataclasses import dataclass
from enum import Enum

import numpy as np
import polars as pl

DAY = np.timedelta64(1, "D")
_US_PER_DAY = 86_400_000_000


class Cardinality(str, Enum):
    LOW = "low"
    HIGH = "high"


class Volatility(str, Enum):
    STATIC = "static"
    SLOW = "slow"
    FAST = "fast"


# expected change points per entity per day
RATES = {Volatility.STATIC: 0.0, Volatility.SLOW: 1 / 90, Volatility.FAST: 1 / 2}
DEFAULT_K = {Cardinality.LOW: 10, Cardinality.HIGH: 1_000_000}


@dataclass(frozen=True)
class AttrSpec:
    name: str
    cardinality: Cardinality = Cardinality.LOW
    volatility: Volatility = Volatility.STATIC
    k: int | None = None

    @property
    def size(self) -> int:
        k = self.k or DEFAULT_K[self.cardinality]
        if k < 2:
            raise ValueError(f"attribute {self.name!r}: k must be >= 2, got {k}")
        return k


def sample_timeline(
    spec: AttrSpec, created_at: np.ndarray, t1: np.datetime64, rng: np.random.Generator
) -> pl.DataFrame:
    """Long-form (idx, valid_from, value) timeline for one attribute.

    Each entity starts with an independent draw at ``created_at``; change points are
    Poisson in time. SLOW/STATIC redraw; FAST attributes random-walk (clipped to range).
    """
    n = len(created_at)
    k = spec.size
    init = rng.integers(0, k, size=n)
    idx_parts = [np.arange(n, dtype="int64")]
    time_parts = [created_at]
    value_parts = [init]

    dur_days = (t1 - created_at) / DAY
    counts = rng.poisson(RATES[spec.volatility] * dur_days)
    total = int(counts.sum())
    if total:
        idx = np.repeat(np.arange(n, dtype="int64"), counts)
        offs = (rng.random(total) * dur_days[idx] * _US_PER_DAY).astype("int64")
        times = created_at[idx] + offs.astype("timedelta64[us]")
        order = np.lexsort((times, idx))
        idx, times = idx[order], times[order]
        if spec.volatility is Volatility.FAST:
            s = 1 if spec.cardinality is Cardinality.LOW else max(1, k // 100)
            steps = rng.choice(np.array([-s, s]), size=total)
            cum = (
                pl.DataFrame({"idx": idx, "step": steps})
                .with_columns(c=pl.col("step").cum_sum().over("idx"))["c"]
                .to_numpy()
            )
            values = np.clip(init[idx] + cum, 0, k - 1)
        else:
            values = rng.integers(0, k, size=total)
        idx_parts.append(idx)
        time_parts.append(times)
        value_parts.append(values)

    return pl.DataFrame(
        {
            "idx": np.concatenate(idx_parts),
            "valid_from": np.concatenate(time_parts),
            "value": np.concatenate(value_parts).astype("int64"),
        }
    ).sort("idx", "valid_from")
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest libs/simkit/tests/test_simkit_ids_attributes.py -v`
Expected: 6 passed. (If `test_fast_changes_more_than_slow` is flaky, the failure is statistical: raise `n` in the test, not the rates.)

- [ ] **Step 5: Commit**

```bash
git add libs/simkit
git commit -m "feat(simkit): UUID ids and attribute change-point timelines"
```

---

### Task 3: Entities and as-of attribute attach

**Files:**
- Create: `libs/simkit/src/neorisk_simkit/entities.py`
- Test: `libs/simkit/tests/test_simkit_entities.py`

**Interfaces:**
- Consumes: `AttrSpec`, `sample_timeline`, `make_uuids`.
- Produces:
  - `EntitySpec(name: str, n: int, attrs: tuple[AttrSpec, ...], created_frac: float = 0.5)`
  - `EntityTable(name: str, ids: pl.DataFrame[idx, entity_id, created_at], attrs: pl.DataFrame[idx, attr, valid_from, value])` with `.n` and `.created_at() -> np.ndarray` (sorted `datetime64[us]`; `idx` is the rank by `created_at`)
  - `build_entities(spec, t0: np.datetime64, t1: np.datetime64, rng) -> EntityTable`
  - `attach_asof(events: pl.DataFrame, table: EntityTable, *, idx_col: str, time_col: str = "event_time", prefix: str | None = None) -> pl.DataFrame` adding columns `f"{prefix or table.name}_{attr}"`, preserving row order; null `idx_col` yields null attrs.
  - `map_ids(table: EntityTable, idx: pl.Series) -> pl.Series` (Utf8; null idx -> null)

- [ ] **Step 1: Write the failing tests**

```python
import numpy as np
import polars as pl

from neorisk_simkit.attributes import AttrSpec, Cardinality, Volatility
from neorisk_simkit.entities import (
    EntitySpec,
    EntityTable,
    attach_asof,
    build_entities,
    map_ids,
)

T0 = np.datetime64("2026-01-01T00:00:00", "us")
T1 = T0 + np.timedelta64(90, "D")


def test_build_entities_shape_and_order():
    spec = EntitySpec(
        "user",
        200,
        (
            AttrSpec("state", Cardinality.LOW, Volatility.SLOW, k=50),
            AttrSpec("street", Cardinality.HIGH, Volatility.SLOW),
        ),
        created_frac=0.5,
    )
    t = build_entities(spec, T0, T1, np.random.default_rng(0))
    created = t.created_at()
    assert t.n == 200 and (np.diff(created.astype("int64")) >= 0).all()
    assert created.max() < T0 + np.timedelta64(45, "D")
    assert t.ids["entity_id"].n_unique() == 200
    assert set(t.attrs["attr"].unique()) == {"state", "street"}


def test_entities_differ_across_ids_for_slow_attr():
    spec = EntitySpec("user", 300, (AttrSpec("street", Cardinality.HIGH, Volatility.SLOW),))
    t = build_entities(spec, T0, T1, np.random.default_rng(1))
    first = t.attrs.sort("idx", "valid_from").group_by("idx", maintain_order=True).first()
    assert first["value"].n_unique() > 290


def _manual_table():
    ids = pl.DataFrame(
        {"idx": [0], "entity_id": ["u0"], "created_at": [T0]},
        schema={"idx": pl.Int64, "entity_id": pl.Utf8, "created_at": pl.Datetime("us")},
    )
    attrs = pl.DataFrame(
        {
            "idx": [0, 0],
            "attr": ["state", "state"],
            "valid_from": [T0, T0 + np.timedelta64(10, "D")],
            "value": [5, 7],
        }
    )
    return EntityTable("user", ids, attrs)


def test_attach_asof_picks_latest_valid_value_and_preserves_order():
    ev = pl.DataFrame(
        {
            "user_idx": [0, 0, 0],
            "event_time": [
                T0 + np.timedelta64(11, "D"),
                T0 + np.timedelta64(1, "D"),
                T0 + np.timedelta64(10, "D"),
            ],
        }
    )
    out = attach_asof(ev, _manual_table(), idx_col="user_idx")
    assert out["user_state"].to_list() == [7, 5, 7]


def test_attach_asof_null_idx_gives_null_attrs():
    ev = pl.DataFrame(
        {"user_idx": [0, None], "event_time": [T0 + np.timedelta64(1, "D")] * 2},
        schema={"user_idx": pl.Int64, "event_time": pl.Datetime("us")},
    )
    out = attach_asof(ev, _manual_table(), idx_col="user_idx")
    assert out["user_state"].to_list() == [5, None]


def test_map_ids_handles_nulls():
    s = map_ids(_manual_table(), pl.Series("x", [0, None], dtype=pl.Int64))
    assert s.to_list() == ["u0", None]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest libs/simkit/tests/test_simkit_entities.py -v`
Expected: FAIL (`ModuleNotFoundError: neorisk_simkit.entities`)

- [ ] **Step 3: Implement**

```python
from dataclasses import dataclass

import numpy as np
import polars as pl

from neorisk_simkit.attributes import AttrSpec, sample_timeline
from neorisk_simkit.ids import make_uuids


@dataclass(frozen=True)
class EntitySpec:
    name: str
    n: int
    attrs: tuple[AttrSpec, ...]
    created_frac: float = 0.5  # entities are created within the first created_frac of the span


@dataclass
class EntityTable:
    name: str
    ids: pl.DataFrame  # idx (rank by created_at), entity_id (UUID), created_at
    attrs: pl.DataFrame  # idx, attr, valid_from, value (long form)

    @property
    def n(self) -> int:
        return self.ids.height

    def created_at(self) -> np.ndarray:
        return self.ids["created_at"].to_numpy()


def build_entities(
    spec: EntitySpec, t0: np.datetime64, t1: np.datetime64, rng: np.random.Generator
) -> EntityTable:
    span_us = int((t1 - t0) / np.timedelta64(1, "us"))
    offs = (rng.random(spec.n) * spec.created_frac * span_us).astype("int64")
    created = np.sort(t0 + offs.astype("timedelta64[us]"))
    ids = pl.DataFrame(
        {
            "idx": np.arange(spec.n, dtype="int64"),
            "entity_id": make_uuids(spec.n, rng),
            "created_at": created,
        }
    )
    parts = [
        sample_timeline(a, created, t1, rng).with_columns(attr=pl.lit(a.name)) for a in spec.attrs
    ]
    attrs = pl.concat(parts).select("idx", "attr", "valid_from", "value")
    return EntityTable(spec.name, ids, attrs)


def attach_asof(
    events: pl.DataFrame,
    table: EntityTable,
    *,
    idx_col: str,
    time_col: str = "event_time",
    prefix: str | None = None,
) -> pl.DataFrame:
    """Add each attribute's value as-of ``time_col`` for the entity in ``idx_col``."""
    prefix = prefix or table.name
    left = events.with_row_index("_row").sort(time_col)
    for attr in table.attrs["attr"].unique(maintain_order=True):
        right = (
            table.attrs.filter(pl.col("attr") == attr)
            .select(
                pl.col("idx").alias(idx_col),
                pl.col("valid_from").cast(left[time_col].dtype).alias(time_col),
                pl.col("value").alias(f"{prefix}_{attr}"),
            )
            .sort(time_col)
        )
        left = left.join_asof(right, on=time_col, by=idx_col, strategy="backward")
    return left.sort("_row").drop("_row")


def map_ids(table: EntityTable, idx: pl.Series) -> pl.Series:
    """Entity idx -> UUID string; null idx stays null."""
    valid = idx.is_not_null().to_numpy()
    out = np.full(len(idx), None, dtype=object)
    ids = table.ids["entity_id"].to_numpy()
    out[valid] = ids[idx.filter(idx.is_not_null()).to_numpy()]
    return pl.Series(idx.name, out, dtype=pl.Utf8)
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest libs/simkit/tests/test_simkit_entities.py -v`
Expected: 5 passed. If `join_asof` rejects null `by` keys in the installed polars, filter nulls out before the join and left-join the result back on `_row`; keep the null test.

- [ ] **Step 5: Commit**

```bash
git add libs/simkit
git commit -m "feat(simkit): entity tables and as-of attribute attach"
```

---

### Task 4: Reference columns

**Files:**
- Create: `libs/simkit/src/neorisk_simkit/references.py`
- Test: `libs/simkit/tests/test_simkit_references.py`

**Interfaces:**
- Produces:
  - `Chooser = Callable[[np.ndarray, np.random.Generator], np.ndarray]`: given `m` (eligible-entity count per row), returns idx in `[0, m)`.
  - `uniform(m, rng)`, `skewed(alpha: float) -> Chooser` (alpha > 1 favours low idx = early entities), `hubs(hub_idx: np.ndarray, p: float, base: Chooser = uniform) -> Chooser`
  - `RefSpec(column: str, target: str, chooser: Chooser, null_prob: float = 0.0, strict: bool = True)`
  - `resolve_reference(spec: RefSpec, times: np.ndarray, target_created_at: np.ndarray, rng) -> pl.Series` (Int64 named `spec.column`; null when no entity existed before `times` (`strict`) / at or before, or with prob `null_prob`)

- [ ] **Step 1: Write the failing tests**

```python
import numpy as np

from neorisk_simkit.references import RefSpec, hubs, resolve_reference, skewed, uniform

T0 = np.datetime64("2026-01-01T00:00:00", "us")


def _created(n=100):
    return T0 + (np.arange(n) * 3_600_000_000).astype("timedelta64[us]")


def test_referenced_entity_predates_row():
    created = _created()
    times = created[10:] + np.timedelta64(1, "us")
    s = resolve_reference(RefSpec("r", "user", uniform), times, created, np.random.default_rng(0))
    idx = s.to_numpy()
    assert (created[idx] < times).all()


def test_strict_excludes_same_instant():
    created = _created()
    times = created[5:6]
    s = resolve_reference(RefSpec("r", "user", uniform), times, created, np.random.default_rng(0))
    assert s.to_numpy()[0] < 5


def test_no_eligible_entity_gives_null():
    created = _created()
    times = np.array([T0 - np.timedelta64(1, "D"), created[0]])
    s = resolve_reference(RefSpec("r", "user", uniform), times, created, np.random.default_rng(0))
    assert s.to_list() == [None, None]


def test_null_prob():
    created = _created()
    times = np.full(5000, created[-1] + np.timedelta64(1, "D"))
    spec = RefSpec("r", "user", uniform, null_prob=0.3)
    s = resolve_reference(spec, times, created, np.random.default_rng(0))
    assert 0.25 < s.null_count() / len(s) < 0.35


def test_hubs_concentrate_references():
    created = _created()
    times = np.full(5000, created[-1] + np.timedelta64(1, "D"))
    hub_idx = np.array([0, 1, 2])
    spec = RefSpec("r", "user", hubs(hub_idx, 0.5))
    idx = resolve_reference(spec, times, created, np.random.default_rng(0)).to_numpy()
    assert 0.45 < np.isin(idx, hub_idx).mean() < 0.6


def test_hubs_not_yet_created_are_not_chosen():
    created = _created()
    times = np.full(2000, created[1] + np.timedelta64(1, "us"))  # only idx 0,1 exist
    spec = RefSpec("r", "user", hubs(np.array([0, 50]), 1.0))
    idx = resolve_reference(spec, times, created, np.random.default_rng(0)).to_numpy()
    assert (idx == 0).all()


def test_skewed_favours_early_entities():
    m = np.full(10_000, 100)
    idx = skewed(3.0)(m, np.random.default_rng(0))
    assert idx.mean() < 30 and idx.max() < 100
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest libs/simkit/tests/test_simkit_references.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Implement**

```python
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import polars as pl

Chooser = Callable[[np.ndarray, np.random.Generator], np.ndarray]


def uniform(m: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    return np.floor(rng.random(len(m)) * m).astype("int64")


def skewed(alpha: float) -> Chooser:
    def choose(m: np.ndarray, rng: np.random.Generator) -> np.ndarray:
        return np.floor(m * rng.random(len(m)) ** alpha).astype("int64")

    return choose


def hubs(hub_idx: np.ndarray, p: float, base: Chooser = uniform) -> Chooser:
    """With probability ``p`` pick uniformly among hubs that already exist, else ``base``."""
    hub_idx = np.sort(np.asarray(hub_idx, dtype="int64"))

    def choose(m: np.ndarray, rng: np.random.Generator) -> np.ndarray:
        out = base(m, rng)
        n_elig = np.searchsorted(hub_idx, m, side="left")  # hubs with idx < m
        use = (rng.random(len(m)) < p) & (n_elig > 0)
        pick = np.floor(rng.random(len(m)) * np.maximum(n_elig, 1)).astype("int64")
        out[use] = hub_idx[pick[use]]
        return out

    return choose


@dataclass(frozen=True)
class RefSpec:
    column: str
    target: str  # target entity name
    chooser: Chooser
    null_prob: float = 0.0
    strict: bool = True  # referenced entity must be created strictly before the row


def resolve_reference(
    spec: RefSpec, times: np.ndarray, target_created_at: np.ndarray, rng: np.random.Generator
) -> pl.Series:
    """Fill a reference column with idx of target entities that exist at ``times``."""
    side = "left" if spec.strict else "right"
    m = np.searchsorted(target_created_at, times, side=side)
    idx = spec.chooser(m, rng)
    ok = (m > 0) & (rng.random(len(m)) >= spec.null_prob)
    return (
        pl.DataFrame({"v": idx.astype("int64"), "ok": ok})
        .select(pl.when(pl.col("ok")).then(pl.col("v")).alias(spec.column))
        .to_series()
    )
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest libs/simkit/tests/test_simkit_references.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add libs/simkit
git commit -m "feat(simkit): reference columns with hub/skew choosers"
```

---

### Task 5: Point-in-time rolling features

**Files:**
- Create: `libs/simkit/src/neorisk_simkit/features.py`
- Test: `libs/simkit/tests/test_simkit_features.py`

**Interfaces:**
- Produces: `rolling(df, *, key: str, value: str, windows_days: Sequence[int], aggs: Sequence[str], prefix: str, id_col: str = "event_id", time_col: str = "event_time") -> pl.DataFrame` with columns `id_col` + `f"{prefix}_{agg}_{w}d"`, one row per input row with non-null `key`; each value aggregates `value` over rows with the same `key` and time in `[t - w days, t)`. Empty window -> 0. `aggs` subset of `count, sum, mean, max, min, n_unique`. Rows with null `key` are absent from the result (callers left-join and fill).

- [ ] **Step 1: Write the failing tests**

```python
import numpy as np
import polars as pl
import pytest

from neorisk_simkit.features import rolling

T0 = np.datetime64("2026-01-01T00:00:00", "us")


def _frame(n=300, n_keys=7, seed=0, with_ties=True):
    rng = np.random.default_rng(seed)
    hours = rng.integers(0, 24 * 40, n) if with_ties else rng.permutation(24 * 40)[:n]
    keys = rng.integers(0, n_keys, n).astype("float")
    keys[rng.random(n) < 0.1] = np.nan  # null keys
    return pl.DataFrame(
        {
            "event_id": [f"e{i}" for i in range(n)],
            "event_time": T0 + (hours * 3_600_000_000).astype("timedelta64[us]"),
            "key": pl.Series(keys).fill_nan(None),
            "amt": rng.random(n) * 100,
        }
    )


def _brute(df, w, agg):
    rows = df.to_dicts()
    out = {}
    for r in rows:
        if r["key"] is None:
            continue
        lo = r["event_time"] - np.timedelta64(w, "D").astype("timedelta64[us]").item()
        vals = [
            x["amt"]
            for x in rows
            if x["key"] == r["key"] and lo <= x["event_time"] < r["event_time"]
        ]
        if not vals:
            out[r["event_id"]] = 0.0
        else:
            out[r["event_id"]] = {
                "count": len(vals),
                "sum": sum(vals),
                "mean": sum(vals) / len(vals),
                "max": max(vals),
                "min": min(vals),
            }[agg]
    return out


@pytest.mark.parametrize("with_ties", [True, False])
def test_rolling_matches_bruteforce(with_ties):
    df = _frame(with_ties=with_ties)
    aggs = ["count", "sum", "mean", "max", "min"]
    got = rolling(df, key="key", value="amt", windows_days=[7, 14], aggs=aggs, prefix="f")
    for w in (7, 14):
        for agg in aggs:
            exp = _brute(df, w, agg)
            col = dict(zip(got["event_id"], got[f"f_{agg}_{w}d"]))
            assert set(col) == set(exp)
            for k, v in exp.items():
                assert col[k] == pytest.approx(v), (w, agg, k)


def test_null_keys_absent_and_no_future_leakage():
    df = _frame()
    got = rolling(df, key="key", value="amt", windows_days=[30], aggs=["count"], prefix="f")
    assert got.height == df["key"].drop_nulls().len()
    # a row's own time is excluded: first event per key has count 0
    first = df.drop_nulls("key").sort("event_time").group_by("key").first()
    cnt = dict(zip(got["event_id"], got["f_count_30d"]))
    assert all(cnt[e] == 0 for e in first["event_id"])


def test_n_unique_and_unknown_agg():
    df = pl.DataFrame(
        {
            "event_id": ["a", "b", "c"],
            "event_time": [T0, T0 + np.timedelta64(1, "D"), T0 + np.timedelta64(2, "D")],
            "device": [1, 1, 1],
            "user": [10, 11, 10],
        }
    )
    got = rolling(df, key="device", value="user", windows_days=[7], aggs=["n_unique"], prefix="d")
    assert got["d_n_unique_7d"].to_list() == [0, 1, 2]
    with pytest.raises(ValueError):
        rolling(df, key="device", value="user", windows_days=[7], aggs=["median"], prefix="d")
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest libs/simkit/tests/test_simkit_features.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Implement**

```python
from collections.abc import Sequence

import polars as pl

_AGGS = {
    "count": lambda c: pl.col(c).count(),
    "sum": lambda c: pl.col(c).sum(),
    "mean": lambda c: pl.col(c).mean(),
    "max": lambda c: pl.col(c).max(),
    "min": lambda c: pl.col(c).min(),
    "n_unique": lambda c: pl.col(c).n_unique(),
}


def rolling(
    df: pl.DataFrame,
    *,
    key: str,
    value: str,
    windows_days: Sequence[int],
    aggs: Sequence[str],
    prefix: str,
    id_col: str = "event_id",
    time_col: str = "event_time",
) -> pl.DataFrame:
    """Per-key aggregates of ``value`` over the window [t - w days, t) (strictly before t)."""
    unknown = set(aggs) - set(_AGGS)
    if unknown:
        raise ValueError(f"unknown aggregations: {sorted(unknown)}")
    base = (
        df.filter(pl.col(key).is_not_null())
        .select(id_col, key, time_col, value)
        .sort([key, time_col], maintain_order=True)
    )
    out = base.select(id_col)
    if base.height == 0:
        return out.with_columns(
            [pl.lit(0.0).alias(f"{prefix}_{a}_{w}d") for w in windows_days for a in aggs]
        )
    for w in windows_days:
        r = base.rolling(index_column=time_col, period=f"{w}d", closed="left", group_by=key).agg(
            [_AGGS[a](value).alias(f"{prefix}_{a}_{w}d") for a in aggs]
        )
        if r.height != base.height or not (
            r[key].equals(base[key]) and r[time_col].equals(base[time_col])
        ):
            raise RuntimeError("rolling output is not row-aligned with its sorted input")
        out = out.hstack(r.drop(key, time_col))
    return out.with_columns(pl.exclude(id_col).fill_null(0))
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest libs/simkit/tests/test_simkit_features.py -v`
Expected: 4 passed. If the alignment guard trips, the installed polars orders `rolling(group_by=...)` output differently: keep the guard and restore alignment by joining the result back on `(key, time)` with a per-row tiebreak, then re-run.

- [ ] **Step 5: Commit**

```bash
git add libs/simkit
git commit -m "feat(simkit): point-in-time rolling features"
```

---

### Task 6: Scorers and bad-rate calibration

**Files:**
- Create: `libs/simkit/src/neorisk_simkit/scorer.py`
- Test: `libs/simkit/tests/test_simkit_scorer.py`

**Interfaces:**
- Produces:
  - `Scorer` protocol: `score(golden: pl.DataFrame) -> np.ndarray` (probabilities in (0, 1))
  - `XGBScorer(weights: Mapping[str, float], seed: int = 0, n_estimators: int = 60, max_depth: int = 3)`: builds teacher `sigmoid(sum_i w_i * tanh(z_i) + bias)` over standardised columns and fits a seeded XGBRegressor to it; the fitted trees are the generating model.
  - `MLPScorer(columns: Sequence[str], hidden: int = 16, seed: int = 0)`: untrained, seeded random-weight tanh MLP.
  - `calibrate(p: np.ndarray, target_rate: float) -> np.ndarray` (shifts logits so `mean(p') == target_rate`, tolerance 1e-4)
  - `sample_labels(p: np.ndarray, rng) -> np.ndarray` (int 0/1 Bernoulli)

- [ ] **Step 1: Write the failing tests**

```python
import numpy as np
import polars as pl

from neorisk_simkit.scorer import MLPScorer, XGBScorer, calibrate, sample_labels


def _golden(n=2000, seed=0):
    rng = np.random.default_rng(seed)
    return pl.DataFrame(
        {
            "a": rng.normal(size=n),
            "b": rng.normal(size=n),
            "const": np.full(n, 3.0),  # zero variance
        }
    )


def test_xgb_scorer_deterministic_and_bounded():
    g = _golden()
    s1 = XGBScorer({"a": 2.0, "b": 0.5, "const": 1.0}, seed=1).score(g)
    s2 = XGBScorer({"a": 2.0, "b": 0.5, "const": 1.0}, seed=1).score(g)
    assert np.array_equal(s1, s2)
    assert np.isfinite(s1).all() and s1.min() > 0 and s1.max() < 1


def test_xgb_scorer_follows_weights():
    g = _golden()
    p = XGBScorer({"a": 3.0, "b": 0.0}, seed=0).score(g)
    corr_a = np.corrcoef(p, g["a"].to_numpy())[0, 1]
    corr_b = np.corrcoef(p, g["b"].to_numpy())[0, 1]
    assert corr_a > 0.8 and abs(corr_b) < 0.2


def test_mlp_scorer_deterministic_and_zero_variance_safe():
    g = _golden()
    p1 = MLPScorer(["a", "b", "const"], seed=2).score(g)
    p2 = MLPScorer(["a", "b", "const"], seed=2).score(g)
    assert np.array_equal(p1, p2) and np.isfinite(p1).all()
    assert 0 < p1.min() and p1.max() < 1


def test_calibrate_hits_target_rate():
    p = np.random.default_rng(0).beta(2, 8, size=10_000)
    for target in (0.01, 0.02, 0.2):
        assert abs(calibrate(p, target).mean() - target) < 1e-3


def test_sample_labels_rate():
    rng = np.random.default_rng(0)
    y = sample_labels(np.full(50_000, 0.02), rng)
    assert set(np.unique(y)) <= {0, 1} and 0.017 < y.mean() < 0.023
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest libs/simkit/tests/test_simkit_scorer.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Implement**

```python
from collections.abc import Mapping, Sequence
from typing import Protocol

import numpy as np
import polars as pl
from xgboost import XGBRegressor

_EPS = 1e-6


class Scorer(Protocol):
    def score(self, golden: pl.DataFrame) -> np.ndarray: ...


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def _zscore(golden: pl.DataFrame, cols: Sequence[str]) -> tuple[np.ndarray, np.ndarray]:
    x = golden.select(list(cols)).to_numpy().astype("float64")
    sd = x.std(axis=0)
    sd[sd == 0] = 1.0  # zero-variance column -> contributes 0 after centring
    return x, (x - x.mean(axis=0)) / sd


class XGBScorer:
    def __init__(
        self,
        weights: Mapping[str, float],
        seed: int = 0,
        n_estimators: int = 60,
        max_depth: int = 3,
    ):
        self.weights = dict(weights)
        self.seed = seed
        self.n_estimators = n_estimators
        self.max_depth = max_depth

    def score(self, golden: pl.DataFrame) -> np.ndarray:
        cols = list(self.weights)
        x, z = _zscore(golden, cols)
        teacher = _sigmoid(np.tanh(z) @ np.array([self.weights[c] for c in cols]))
        model = XGBRegressor(
            n_estimators=self.n_estimators,
            max_depth=self.max_depth,
            learning_rate=0.2,
            random_state=self.seed,
            n_jobs=1,
            tree_method="hist",
        )
        model.fit(x, teacher)
        return np.clip(model.predict(x), _EPS, 1 - _EPS).astype("float64")


class MLPScorer:
    def __init__(self, columns: Sequence[str], hidden: int = 16, seed: int = 0):
        rng = np.random.default_rng(seed)
        self.columns = list(columns)
        self.w1 = rng.normal(size=(len(self.columns), hidden)) / np.sqrt(len(self.columns))
        self.b1 = rng.normal(size=hidden) * 0.1
        self.w2 = rng.normal(size=hidden) / np.sqrt(hidden)

    def score(self, golden: pl.DataFrame) -> np.ndarray:
        _, z = _zscore(golden, self.columns)
        logit = np.tanh(z @ self.w1 + self.b1) @ self.w2 * 2.0
        return np.clip(_sigmoid(logit), _EPS, 1 - _EPS)


def calibrate(p: np.ndarray, target_rate: float, iters: int = 60) -> np.ndarray:
    """Shift logits by a constant so the mean probability equals ``target_rate``."""
    if not 0 < target_rate < 1:
        raise ValueError("target_rate must be in (0, 1)")
    p = np.clip(p, _EPS, 1 - _EPS)
    logit = np.log(p / (1 - p))
    lo, hi = -30.0, 30.0
    for _ in range(iters):
        mid = (lo + hi) / 2
        if _sigmoid(logit + mid).mean() > target_rate:
            hi = mid
        else:
            lo = mid
    return _sigmoid(logit + (lo + hi) / 2)


def sample_labels(p: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    return (rng.random(len(p)) < p).astype("int64")
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest libs/simkit/tests/test_simkit_scorer.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add libs/simkit
git commit -m "feat(simkit): preset scorers and bad-rate calibration"
```

---

### Task 7: Dataset export with leakage guard

**Files:**
- Create: `libs/simkit/src/neorisk_simkit/export.py`; modify `libs/simkit/src/neorisk_simkit/__init__.py`
- Test: `libs/simkit/tests/test_simkit_export.py`

**Interfaces:**
- Produces:
  - `Dataset(events: pl.DataFrame, golden: pl.DataFrame, meta: dict)`; `events` has `event_id` and `label`; `golden` has `event_id` + golden columns.
  - `export(ds: Dataset, out_dir: str | Path) -> None` writes `events.parquet`, `golden.parquet`, `meta.json` (meta gains `golden_columns`, `n_events`, `bad_rate`). Raises `ValueError` if any golden column name is in `events`, if `event_id`/`label` is missing from events, or golden `event_id` set differs from events.
  - `neorisk_simkit.__init__` re-exports: `AttrSpec, Cardinality, Volatility, EntitySpec, EntityTable, build_entities, attach_asof, map_ids, RefSpec, resolve_reference, uniform, skewed, hubs, rolling, XGBScorer, MLPScorer, calibrate, sample_labels, Dataset, export, make_uuids`.

- [ ] **Step 1: Write the failing tests**

```python
import json

import polars as pl
import pytest

from neorisk_simkit import Dataset, export


def _ds(**overrides):
    events = pl.DataFrame({"event_id": ["a", "b"], "amount": [1.0, 2.0], "label": [0, 1]})
    golden = pl.DataFrame({"event_id": ["a", "b"], "vel_7d": [0.0, 3.0], "score": [0.1, 0.9]})
    ds = Dataset(events, golden, {"scenario": "t", "seed": 1})
    for k, v in overrides.items():
        setattr(ds, k, v)
    return ds


def test_export_writes_files_and_meta(tmp_path):
    export(_ds(), tmp_path)
    ev = pl.read_parquet(tmp_path / "events.parquet")
    gd = pl.read_parquet(tmp_path / "golden.parquet")
    meta = json.loads((tmp_path / "meta.json").read_text())
    assert ev.columns == ["event_id", "amount", "label"]
    assert gd.columns == ["event_id", "vel_7d", "score"]
    assert meta["golden_columns"] == ["vel_7d", "score"]
    assert meta["n_events"] == 2 and meta["bad_rate"] == 0.5 and meta["seed"] == 1


def test_export_refuses_golden_column_in_events(tmp_path):
    leaky = _ds().events.with_columns(vel_7d=pl.lit(0.0))
    with pytest.raises(ValueError, match="vel_7d"):
        export(_ds(events=leaky), tmp_path)


def test_export_requires_label_and_matching_ids(tmp_path):
    with pytest.raises(ValueError, match="label"):
        export(_ds(events=_ds().events.drop("label")), tmp_path)
    with pytest.raises(ValueError, match="event_id"):
        export(_ds(golden=_ds().golden.head(1)), tmp_path)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest libs/simkit/tests/test_simkit_export.py -v`
Expected: FAIL (`ImportError: cannot import name 'Dataset'`)

- [ ] **Step 3: Implement**

`export.py`:
```python
import json
from dataclasses import dataclass, field
from pathlib import Path

import polars as pl


@dataclass
class Dataset:
    events: pl.DataFrame  # raw benchmark input incl. label
    golden: pl.DataFrame  # event_id + hidden golden columns
    meta: dict = field(default_factory=dict)


def export(ds: Dataset, out_dir: str | Path) -> None:
    for col in ("event_id", "label"):
        if col not in ds.events.columns:
            raise ValueError(f"events is missing required column {col!r}")
    if "event_id" not in ds.golden.columns:
        raise ValueError("golden is missing required column 'event_id'")
    golden_cols = [c for c in ds.golden.columns if c != "event_id"]
    leaked = [c for c in golden_cols if c in ds.events.columns]
    if leaked:
        raise ValueError(f"golden columns present in events: {leaked}")
    if set(ds.golden["event_id"]) != set(ds.events["event_id"]):
        raise ValueError("event_id sets differ between events and golden")

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    ds.events.write_parquet(out / "events.parquet")
    ds.golden.write_parquet(out / "golden.parquet")
    meta = {
        **ds.meta,
        "golden_columns": golden_cols,
        "n_events": ds.events.height,
        "bad_rate": float(ds.events["label"].mean()),
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2, default=str))
```

`__init__.py`:
```python
"""Synthetic event data framework."""

from neorisk_simkit.attributes import AttrSpec, Cardinality, Volatility
from neorisk_simkit.entities import EntitySpec, EntityTable, attach_asof, build_entities, map_ids
from neorisk_simkit.export import Dataset, export
from neorisk_simkit.features import rolling
from neorisk_simkit.ids import make_uuids
from neorisk_simkit.references import RefSpec, hubs, resolve_reference, skewed, uniform
from neorisk_simkit.scorer import MLPScorer, XGBScorer, calibrate, sample_labels

__all__ = [
    "AttrSpec",
    "Cardinality",
    "Volatility",
    "EntitySpec",
    "EntityTable",
    "attach_asof",
    "build_entities",
    "map_ids",
    "Dataset",
    "export",
    "rolling",
    "make_uuids",
    "RefSpec",
    "hubs",
    "resolve_reference",
    "skewed",
    "uniform",
    "MLPScorer",
    "XGBScorer",
    "calibrate",
    "sample_labels",
]
```

- [ ] **Step 4: Run all simkit tests**

Run: `uv run pytest libs/simkit -v && uv run ruff check libs/simkit`
Expected: all pass, ruff clean

- [ ] **Step 5: Commit**

```bash
git add libs/simkit
git commit -m "feat(simkit): dataset export with golden-leak guard"
```

---

### Task 8: datagen app, config and fraud scenario

**Files:**
- Create: `apps/datagen/pyproject.toml`, `apps/datagen/README.md`, `apps/datagen/src/datagen/__init__.py`, `apps/datagen/src/datagen/config.py`, `apps/datagen/src/datagen/scenarios/__init__.py`, `apps/datagen/src/datagen/scenarios/fraud.py`
- Test: `apps/datagen/tests/test_datagen_fraud.py`

**Interfaces:**
- Consumes: everything exported from `neorisk_simkit`.
- Produces:
  - `FraudConfig(n_events=100_000, seed=0, span_days=90, target_bad_rate=0.02, invite_frac=0.15, hunter_prob=0.4, users_per_event=0.05)` with `.validate()`, `.n_users`, `.n_devices`, `.n_products`, `.n_hunters`
  - `datagen.scenarios.fraud.generate(cfg: FraudConfig) -> Dataset`
  - `datagen.scenarios.SCENARIOS: dict[str, Callable[[FraudConfig], Dataset]]`
- Event columns (events.parquet): `event_id, event_time, event_type (0 txn / 1 invite), user_id, device_id, product_id, inviter_id, amount, currency, referral_bonus, user_*, device_*, product_*, label`.
- Golden columns: `u_amt_{count,sum,mean,max,min}_{7,14,30}d, dev_users_n_unique_7d, addr_chg_sum_30d, amt_ratio_30d, inv_bonus_{count,sum,mean,max}_{7,14,30}d, inv_zombie_mean_30d, invitee_is_zombie, score`.

- [ ] **Step 1: Scaffold app files**

`apps/datagen/pyproject.toml`:
```toml
[project]
name = "datagen"
version = "0.1.0"
description = "Synthetic tabular event data generator (fraud scenario first)"
readme = "README.md"
requires-python = ">=3.12"
dependencies = ["neorisk-simkit"]

[project.scripts]
datagen = "datagen.cli:main"

[build-system]
requires = ["uv_build>=0.11.26,<0.12.0"]
build-backend = "uv_build"

[tool.uv.sources]
neorisk-simkit = { workspace = true }
```
`README.md`: title + usage `uv run datagen generate --scenario fraud --n-events 100000 --seed 42 --out data/fraud`.
`__init__.py`: docstring only. Run `uv sync --all-packages` (workspace members are only installed with `--all-packages`).

- [ ] **Step 2: Write the failing tests**

```python
import numpy as np
import polars as pl
import pytest

from datagen.config import FraudConfig
from datagen.scenarios.fraud import generate

CFG = FraudConfig(n_events=6000, seed=7, span_days=60)


@pytest.fixture(scope="module")
def ds():
    return generate(CFG)


def test_config_validation():
    for bad in (
        dict(n_events=0),
        dict(target_bad_rate=0.0),
        dict(target_bad_rate=1.0),
        dict(span_days=0),
        dict(invite_frac=1.5),
    ):
        with pytest.raises(ValueError):
            FraudConfig(**bad).validate()


def test_deterministic():
    a, b = generate(CFG), generate(CFG)
    assert a.events.equals(b.events) and a.golden.equals(b.golden)


def test_shape_and_no_golden_in_events(ds):
    assert ds.events.height == CFG.n_events
    golden_cols = set(ds.golden.columns) - {"event_id"}
    assert not golden_cols & set(ds.events.columns)
    assert set(ds.events["event_id"]) == set(ds.golden["event_id"])
    for c in ("event_time", "user_id", "device_id", "amount", "label", "inviter_id"):
        assert c in ds.events.columns


def test_bad_rate_near_target(ds):
    assert 0.01 < ds.events["label"].mean() < 0.04


def test_attributes_are_stable_within_short_window(ds):
    ev = ds.events.filter(pl.col("event_type") == 0).sort("event_time")
    # static attribute: constant per device
    assert (
        ev.group_by("device_id").agg(pl.col("device_os").n_unique()).get_column("device_os").max()
        == 1
    )
    # slow attribute: few changes per user over the span
    chg = ev.group_by("user_id").agg(
        (pl.col("user_state").diff().fill_null(0) != 0).sum().alias("c"), pl.len().alias("n")
    )
    assert chg.filter(pl.col("n") > 5)["c"].mean() < 3


def test_invites_reference_other_users(ds):
    inv = ds.events.filter(pl.col("event_type") == 1)
    assert inv.height > 0
    ok = inv.drop_nulls("inviter_id")
    assert (ok["inviter_id"] != ok["user_id"]).all()
    txn = ds.events.filter(pl.col("event_type") == 0)
    assert txn["inviter_id"].null_count() == txn.height


def test_bounty_hunter_signature_is_planted(ds):
    g = ds.golden.join(ds.events.select("event_id", "event_type"), on="event_id")
    inv = g.filter(pl.col("event_type") == 1)
    zombie = inv.filter(pl.col("invitee_is_zombie") == 1)
    normal = inv.filter(pl.col("invitee_is_zombie") == 0)
    assert zombie.height > 0
    assert zombie["inv_bonus_sum_30d"].mean() > 2 * normal["inv_bonus_sum_30d"].mean()
    assert zombie["score"].mean() > normal["score"].mean()


def test_rolling_features_have_no_future_leakage(ds):
    first = (
        ds.events.filter(pl.col("event_type") == 0).sort("event_time").group_by("user_id").first()
    )
    g = ds.golden.filter(pl.col("event_id").is_in(first["event_id"]))
    assert (g["u_amt_count_30d"] == 0).all()


def test_tiny_dataset_does_not_crash():
    out = generate(FraudConfig(n_events=300, seed=1, span_days=10))
    assert out.events.height == 300 and np.isfinite(out.golden["score"].to_numpy()).all()
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest apps/datagen/tests/test_datagen_fraud.py -v`
Expected: FAIL (`ModuleNotFoundError: datagen.config`)

- [ ] **Step 4: Implement config**

`config.py`:
```python
from dataclasses import dataclass


@dataclass(frozen=True)
class FraudConfig:
    n_events: int = 100_000
    seed: int = 0
    span_days: int = 90
    target_bad_rate: float = 0.02
    invite_frac: float = 0.15  # share of users that were invited by someone
    hunter_prob: float = 0.4  # chance an invite comes from a bounty hunter
    users_per_event: float = 0.05

    @property
    def n_users(self) -> int:
        return max(50, int(self.n_events * self.users_per_event))

    @property
    def n_devices(self) -> int:
        return max(10, int(self.n_users * 0.8))

    @property
    def n_products(self) -> int:
        return 200

    @property
    def n_hunters(self) -> int:
        return max(3, self.n_users // 100)

    def validate(self) -> None:
        if self.n_events < 100:
            raise ValueError("n_events must be >= 100")
        if self.span_days < 1:
            raise ValueError("span_days must be >= 1")
        if not 0 < self.target_bad_rate < 1:
            raise ValueError("target_bad_rate must be in (0, 1)")
        if not 0 <= self.invite_frac <= 1 or not 0 <= self.hunter_prob <= 1:
            raise ValueError("invite_frac and hunter_prob must be in [0, 1]")
        if self.users_per_event <= 0:
            raise ValueError("users_per_event must be > 0")
```
Note: the "tiny dataset" test uses `n_events=300`, which satisfies `>= 100`; `n_events=0` in the validation test triggers the first check.

- [ ] **Step 5: Implement the fraud scenario**

`scenarios/fraud.py`:
```python
import dataclasses

import numpy as np
import polars as pl
import xgboost
from neorisk_simkit import (
    AttrSpec,
    Cardinality,
    Dataset,
    EntitySpec,
    RefSpec,
    Volatility,
    XGBScorer,
    attach_asof,
    build_entities,
    calibrate,
    hubs,
    make_uuids,
    map_ids,
    resolve_reference,
    rolling,
    sample_labels,
    skewed,
)

from datagen.config import FraudConfig

L, H = Cardinality.LOW, Cardinality.HIGH
S, SL, F = Volatility.STATIC, Volatility.SLOW, Volatility.FAST

USER_ATTRS = (
    AttrSpec("age_bucket", L, S, k=10),
    AttrSpec("currency", L, S, k=5),
    AttrSpec("state", L, SL, k=50),
    AttrSpec("street", H, SL),
    AttrSpec("zip", H, SL),
    AttrSpec("segment", L, SL, k=8),
)
DEVICE_ATTRS = (
    AttrSpec("os", L, S, k=4),
    AttrSpec("model", L, S, k=30),
    AttrSpec("battery", L, F, k=10),
    AttrSpec("ip", H, F),
    AttrSpec("user_agent", L, SL, k=20),
)
PRODUCT_ATTRS = (
    AttrSpec("category", L, S, k=20),
    AttrSpec("launch_day", H, S, k=3650),
)

# Planted signal: weight of each golden feature in the label-generating scorer.
GOLDEN_WEIGHTS = {
    "amt_ratio_30d": 1.0,
    "u_amt_count_7d": 0.3,
    "u_amt_max_30d": 0.4,
    "dev_users_n_unique_7d": 0.8,
    "addr_chg_sum_30d": 0.5,
    "inv_bonus_count_30d": 0.8,
    "inv_bonus_sum_30d": 1.0,
    "inv_zombie_mean_30d": 1.2,
}

T0 = np.datetime64("2026-01-01T00:00:00", "us")


def _times(rng, lo: np.datetime64, hi: np.datetime64, n: int) -> np.ndarray:
    span = int((hi - lo) / np.timedelta64(1, "us"))
    offs = (rng.random(n) * span).astype("int64")
    return np.sort(lo + offs.astype("timedelta64[us]"))


def _invites(cfg, users, created, user_device, rng):
    """Invite events + the hidden zombie flag. Mutates ``user_device`` for ring members."""
    n_u = cfg.n_users
    hunter_idx = np.arange(cfg.n_hunters)
    is_invited = (rng.random(n_u) < cfg.invite_frac) & (np.arange(n_u) >= cfg.n_hunters)
    invitee = np.flatnonzero(is_invited)
    ref = RefSpec("inviter_idx", "user", hubs(hunter_idx, cfg.hunter_prob))
    inviter = resolve_reference(ref, created[invitee], created, rng)
    inviter_np = inviter.fill_null(-1).to_numpy()
    from_hunter = np.isin(inviter_np, hunter_idx)
    zombie = rng.random(len(invitee)) < np.where(from_hunter, 0.9, 0.02)
    bonus = np.where(
        from_hunter, rng.integers(30, 100, len(invitee)), rng.integers(1, 10, len(invitee))
    )
    ring = zombie & from_hunter & (rng.random(len(invitee)) < 0.7)
    user_device[invitee[ring]] = user_device[inviter_np[ring]]  # multi-account device sharing
    user_is_zombie = np.zeros(n_u, dtype=bool)
    user_is_zombie[invitee] = zombie
    df = pl.DataFrame(
        {
            "event_time": created[invitee],
            "event_type": np.ones(len(invitee), dtype="int64"),
            "user_idx": invitee.astype("int64"),
            "device_idx": user_device[invitee].astype("int64"),
            "inviter_idx": inviter_np.astype("int64"),
            "referral_bonus": bonus.astype("int64"),
            "zombie": zombie,
        }
    ).with_columns(
        pl.when(pl.col("inviter_idx") >= 0).then(pl.col("inviter_idx")).alias("inviter_idx")
    )
    return df, user_is_zombie


def _transactions(cfg, n_txn, created, user_device, user_is_zombie, t1, rng):
    times = _times(rng, created[0], t1, n_txn)
    m = np.searchsorted(created, times, side="right")
    choose = skewed(2.0)
    user = choose(m, rng)
    for _ in range(3):  # zombies are (almost) inactive
        bad = user_is_zombie[user]
        if not bad.any():
            break
        user[bad] = choose(m[bad], rng)
    device = np.where(
        rng.random(n_txn) < 0.1, rng.integers(0, cfg.n_devices, n_txn), user_device[user]
    )
    product = np.where(rng.random(n_txn) < 0.7, rng.integers(0, cfg.n_products, n_txn), -1)
    cashout = (rng.random(cfg.n_users) < 0.03) & ~user_is_zombie
    df = pl.DataFrame(
        {
            "event_time": times,
            "event_type": np.zeros(n_txn, dtype="int64"),
            "user_idx": user.astype("int64"),
            "device_idx": device.astype("int64"),
            "product_idx": product.astype("int64"),
            "amount": np.round(rng.lognormal(3.0, 0.8, n_txn), 2),
            "cashout_user": cashout[user],
        }
    ).with_columns(
        pl.when(pl.col("product_idx") >= 0).then(pl.col("product_idx")).alias("product_idx")
    )
    # warm-up / cash-out: cashout users send small amounts, then a large burst at the end
    return (
        df.with_columns(rank=pl.int_range(pl.len()).over("user_idx"), n=pl.len().over("user_idx"))
        .with_columns(
            amount=pl.when(pl.col("cashout_user"))
            .then(
                pl.when(pl.col("rank") >= (pl.col("n") * 0.9).floor())
                .then(pl.col("amount") * 15)
                .otherwise(pl.col("amount") * 0.3)
            )
            .otherwise(pl.col("amount"))
        )
        .drop("rank", "n", "cashout_user")
    )


def _address_changes(events: pl.DataFrame, users) -> pl.DataFrame:
    ch = (
        users.attrs.filter(pl.col("attr") == "state")
        .join(users.ids.select("idx", "created_at"), on="idx")
        .filter(pl.col("valid_from") > pl.col("created_at"))
        .select(
            pl.lit(None, dtype=pl.Utf8).alias("event_id"),
            pl.col("idx").alias("user_idx"),
            pl.col("valid_from").alias("event_time"),
            pl.lit(1.0).alias("is_change"),
        )
    )
    ev = events.select("event_id", "user_idx", "event_time").with_columns(is_change=pl.lit(0.0))
    both = pl.concat([ev, ch.select(ev.columns)]).with_row_index("_rid")
    r = rolling(
        both,
        key="user_idx",
        value="is_change",
        windows_days=[30],
        aggs=["sum"],
        prefix="addr_chg",
        id_col="_rid",
    )
    return (
        both.join(r, on="_rid")
        .filter(pl.col("event_id").is_not_null())
        .select("event_id", "addr_chg_sum_30d")
    )


def _golden(events: pl.DataFrame, users) -> pl.DataFrame:
    txn = events.filter(pl.col("event_type") == 0)
    inv = events.filter(pl.col("event_type") == 1).with_columns(
        zombie_f=pl.col("zombie").cast(pl.Float64)
    )
    vel = rolling(
        txn,
        key="user_idx",
        value="amount",
        windows_days=[7, 14, 30],
        aggs=["count", "sum", "mean", "max", "min"],
        prefix="u_amt",
    )
    devu = rolling(
        txn,
        key="device_idx",
        value="user_idx",
        windows_days=[7],
        aggs=["n_unique"],
        prefix="dev_users",
    )
    g_bonus = rolling(
        inv,
        key="inviter_idx",
        value="referral_bonus",
        windows_days=[7, 14, 30],
        aggs=["count", "sum", "mean", "max"],
        prefix="inv_bonus",
    )
    g_zombie = rolling(
        inv,
        key="inviter_idx",
        value="zombie_f",
        windows_days=[30],
        aggs=["mean"],
        prefix="inv_zombie",
    )
    # graph features of the invite that brought each user in, looked up as-of event time
    inv_feats = (
        inv.select("event_id", "user_idx", "event_time")
        .join(g_bonus, on="event_id", how="left")
        .join(g_zombie, on="event_id", how="left")
        .drop("event_id")
        .sort("event_time")
    )
    graph = (
        events.select("event_id", "user_idx", "event_time")
        .sort("event_time")
        .join_asof(inv_feats, on="event_time", by="user_idx", strategy="backward")
        .drop("user_idx", "event_time")
    )
    zombie_flag = events.select(
        "event_id", pl.col("zombie").fill_null(False).cast(pl.Int64).alias("invitee_is_zombie")
    )
    out = (
        events.select("event_id", "amount")
        .join(vel, on="event_id", how="left")
        .join(devu, on="event_id", how="left")
        .join(_address_changes(events, users), on="event_id", how="left")
        .join(graph, on="event_id", how="left")
        .join(zombie_flag, on="event_id")
        .with_columns(
            amt_ratio_30d=pl.col("amount").fill_null(0.0) / (pl.col("u_amt_mean_30d") + 1.0)
        )
        .drop("amount")
    )
    return out.with_columns(pl.exclude("event_id").fill_null(0))


def generate(cfg: FraudConfig) -> Dataset:
    cfg.validate()
    rng = np.random.default_rng(cfg.seed)
    t0, t1 = T0, T0 + np.timedelta64(cfg.span_days, "D")

    users = build_entities(EntitySpec("user", cfg.n_users, USER_ATTRS, 0.5), t0, t1, rng)
    devices = build_entities(EntitySpec("device", cfg.n_devices, DEVICE_ATTRS, 0.0), t0, t1, rng)
    products = build_entities(
        EntitySpec("product", cfg.n_products, PRODUCT_ATTRS, 0.0), t0, t1, rng
    )
    created = users.created_at()
    user_device = rng.integers(0, cfg.n_devices, cfg.n_users)

    invites, user_is_zombie = _invites(cfg, users, created, user_device, rng)
    n_txn = cfg.n_events - invites.height
    if n_txn <= 0:
        raise ValueError("n_events is too small for the configured invite_frac")
    txns = _transactions(cfg, n_txn, created, user_device, user_is_zombie, t1, rng)

    events = (
        pl.concat([invites, txns], how="diagonal_relaxed")
        .sort("event_time", "event_type", "user_idx")
        .with_columns(event_id=pl.Series(make_uuids(cfg.n_events, rng)))
    )
    events = attach_asof(events, users, idx_col="user_idx")
    events = attach_asof(events, devices, idx_col="device_idx")
    events = attach_asof(events, products, idx_col="product_idx")
    home = events["user_currency"].to_numpy()
    other = rng.integers(0, 5, events.height)
    events = events.with_columns(
        currency=pl.when(pl.col("event_type") == 0).then(
            pl.Series(np.where(rng.random(events.height) < 0.9, home, other))
        )
    )

    golden = _golden(events, users)
    p = calibrate(XGBScorer(GOLDEN_WEIGHTS, seed=cfg.seed).score(golden), cfg.target_bad_rate)
    labels = sample_labels(p, rng)
    golden = golden.with_columns(score=pl.Series(p))

    out = events.with_columns(
        user_id=map_ids(users, events["user_idx"]),
        device_id=map_ids(devices, events["device_idx"]),
        product_id=map_ids(products, events["product_idx"]),
        inviter_id=map_ids(users, events["inviter_idx"]),
        label=pl.Series(labels),
    ).drop("user_idx", "device_idx", "product_idx", "inviter_idx", "zombie")
    lead = [
        "event_id",
        "event_time",
        "event_type",
        "user_id",
        "device_id",
        "product_id",
        "inviter_id",
        "amount",
        "currency",
        "referral_bonus",
    ]
    out = out.select(lead + [c for c in out.columns if c not in lead and c != "label"] + ["label"])

    meta = {
        "scenario": "fraud",
        "seed": cfg.seed,
        "config": dataclasses.asdict(cfg),
        "versions": {"polars": pl.__version__, "xgboost": xgboost.__version__},
    }
    return Dataset(out, golden, meta)
```
`scenarios/__init__.py`:
```python
from collections.abc import Callable

from neorisk_simkit import Dataset

from datagen.config import FraudConfig
from datagen.scenarios import fraud

SCENARIOS: dict[str, Callable[[FraudConfig], Dataset]] = {"fraud": fraud.generate}
```

- [ ] **Step 6: Run to verify pass**

Run: `uv run pytest apps/datagen/tests/test_datagen_fraud.py -v`
Expected: 8 passed. Likely tuning points if a statistical test fails (adjust the scenario, never the assertion direction): `test_bad_rate_near_target` (calibration is on the golden set, so check the label sampling), `test_bounty_hunter_signature_is_planted` (raise `hunter_prob`/`invite_frac` in the test config before touching weights).

- [ ] **Step 7: Commit**

```bash
git add apps/datagen uv.lock
git commit -m "feat(datagen): fraud scenario with planted bounty-hunter linkage signal"
```

---

### Task 9: datagen CLI

**Files:**
- Create: `apps/datagen/src/datagen/cli.py`
- Test: `apps/datagen/tests/test_datagen_cli.py`

**Interfaces:**
- Consumes: `SCENARIOS`, `FraudConfig`, `neorisk_simkit.export`.
- Produces: `main(argv: Sequence[str] | None = None) -> int`; `datagen generate --scenario fraud --n-events N --seed S --out DIR [--bad-rate R] [--span-days D]`.

- [ ] **Step 1: Write the failing test**

```python
import json

import polars as pl
import pytest

from datagen.cli import main


def test_generate_writes_dataset(tmp_path):
    out = tmp_path / "fraud"
    rc = main(
        [
            "generate",
            "--scenario",
            "fraud",
            "--n-events",
            "3000",
            "--seed",
            "3",
            "--span-days",
            "30",
            "--out",
            str(out),
        ]
    )
    assert rc == 0
    ev = pl.read_parquet(out / "events.parquet")
    meta = json.loads((out / "meta.json").read_text())
    assert ev.height == 3000 and meta["scenario"] == "fraud" and meta["seed"] == 3
    assert not set(meta["golden_columns"]) & set(ev.columns)


def test_unknown_scenario_exits_nonzero(tmp_path):
    with pytest.raises(SystemExit) as e:
        main(["generate", "--scenario", "nope", "--out", str(tmp_path)])
    assert e.value.code != 0
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest apps/datagen/tests/test_datagen_cli.py -v`
Expected: FAIL (`ModuleNotFoundError: datagen.cli`)

- [ ] **Step 3: Implement**

```python
import argparse
from collections.abc import Sequence

from neorisk_simkit import export

from datagen.config import FraudConfig
from datagen.scenarios import SCENARIOS


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="datagen")
    sub = parser.add_subparsers(dest="cmd", required=True)
    gen = sub.add_parser("generate", help="generate a synthetic dataset")
    gen.add_argument("--scenario", required=True, choices=sorted(SCENARIOS))
    gen.add_argument("--n-events", type=int, default=FraudConfig.n_events)
    gen.add_argument("--seed", type=int, default=0)
    gen.add_argument("--span-days", type=int, default=FraudConfig.span_days)
    gen.add_argument("--bad-rate", type=float, default=FraudConfig.target_bad_rate)
    gen.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    cfg = FraudConfig(
        n_events=args.n_events,
        seed=args.seed,
        span_days=args.span_days,
        target_bad_rate=args.bad_rate,
    )
    ds = SCENARIOS[args.scenario](cfg)
    export(ds, args.out)
    print(
        f"wrote {ds.events.height} events to {args.out} (bad rate {ds.events['label'].mean():.4f})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run to verify pass, then smoke the real entry point**

Run: `uv run pytest apps/datagen -v && uv run datagen generate --scenario fraud --n-events 20000 --seed 42 --out /tmp/neorisk-fraud-smoke`
Expected: tests pass; command prints `wrote 20000 events ...`.

- [ ] **Step 5: Commit**

```bash
git add apps/datagen
git commit -m "feat(datagen): generate CLI"
```

---

### Task 10: bench app

**Files:**
- Create: `apps/bench/pyproject.toml`, `apps/bench/README.md`, `apps/bench/src/bench/__init__.py`, `apps/bench/src/bench/runner.py`, `apps/bench/src/bench/cli.py`
- Test: `apps/bench/tests/test_bench_runner.py`

**Interfaces:**
- Produces:
  - `load_events(data_dir) -> (events: pl.DataFrame, meta: dict)`; raises `ValueError` if `label` is missing or any `meta["golden_columns"]` is in events.
  - `time_split(df, fracs=(0.6, 0.2, 0.2)) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]` ordered by `event_time`.
  - `raw_features(df) -> pl.DataFrame` (numeric columns only; drops `label`, `*_id`; nulls -> -1).
  - `evaluate(y, p, precision_floor=0.5) -> dict(auc, pr_auc, recall_at_precision)` (NaN when `y` has a single class).
  - `run(data_dir, oracle=False) -> list[dict]` rows `{model, split, auc, pr_auc, recall_at_precision}`.
  - CLI: `bench run DATA_DIR [--oracle] [--json PATH]`.
- Dependency: `scikit-learn`, `xgboost`, `polars`, `numpy`; depends on `neorisk-simkit` only in tests (dev group) to build a tiny dataset via datagen.

- [ ] **Step 1: Scaffold**

`apps/bench/pyproject.toml`:
```toml
[project]
name = "bench"
version = "0.1.0"
description = "Baseline model benchmark runner for synthetic event datasets"
readme = "README.md"
requires-python = ">=3.12"
dependencies = ["numpy>=1.26", "polars>=1.0", "scikit-learn>=1.4", "xgboost>=2.0"]

[project.scripts]
bench = "bench.cli:main"

[dependency-groups]
dev = ["datagen"]

[build-system]
requires = ["uv_build>=0.11.26,<0.12.0"]
build-backend = "uv_build"

[tool.uv.sources]
datagen = { workspace = true }
```
`README.md`: title + usage `uv run bench run data/fraud [--oracle] [--json out.json]`; state that only `events.parquet` is read unless `--oracle`. `__init__.py`: docstring. Run `uv sync --all-packages`.

- [ ] **Step 2: Write the failing tests**

```python
import numpy as np
import polars as pl
import pytest
from datagen.cli import main as datagen_main

from bench.runner import evaluate, load_events, raw_features, run, time_split


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory):
    out = tmp_path_factory.mktemp("fraud")
    datagen_main(
        [
            "generate",
            "--scenario",
            "fraud",
            "--n-events",
            "20000",
            "--seed",
            "11",
            "--span-days",
            "60",
            "--out",
            str(out),
        ]
    )
    return out


def test_time_split_is_ordered_and_disjoint(data_dir):
    ev, _ = load_events(data_dir)
    tr, va, te = time_split(ev)
    assert tr.height + va.height + te.height == ev.height
    assert tr["event_time"].max() <= va["event_time"].min()
    assert va["event_time"].max() <= te["event_time"].min()


def test_raw_features_numeric_only_no_ids_no_label(data_dir):
    ev, _ = load_events(data_dir)
    x = raw_features(ev)
    assert "label" not in x.columns and not any(c.endswith("_id") for c in x.columns)
    assert all(t.is_numeric() for t in x.schema.values())
    assert x.null_count().sum_horizontal().item() == 0


def test_load_events_rejects_leaked_golden(data_dir, tmp_path):
    ev = pl.read_parquet(data_dir / "events.parquet").with_columns(u_amt_sum_7d=pl.lit(0.0))
    ev.write_parquet(tmp_path / "events.parquet")
    (tmp_path / "meta.json").write_text((data_dir / "meta.json").read_text())
    with pytest.raises(ValueError, match="golden"):
        load_events(tmp_path)


def test_evaluate_single_class_is_nan():
    m = evaluate(np.zeros(10, dtype=int), np.linspace(0, 1, 10))
    assert np.isnan(m["auc"]) and np.isnan(m["pr_auc"])


def test_evaluate_perfect_ranking():
    y = np.array([0, 0, 0, 1, 1])
    m = evaluate(y, np.array([0.1, 0.2, 0.3, 0.8, 0.9]))
    assert m["auc"] == 1.0 and m["recall_at_precision"] == 1.0


def test_oracle_beats_raw_beats_chance(data_dir):
    rows = run(data_dir, oracle=True)
    test = {r["model"]: r for r in rows if r["split"] == "test"}
    raw = max(test["logreg_raw"]["auc"], test["xgb_raw"]["auc"])
    assert test["xgb_oracle"]["auc"] > raw > 0.5
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest apps/bench/tests/test_bench_runner.py -v`
Expected: FAIL (`ModuleNotFoundError: bench.runner`)

- [ ] **Step 4: Implement**

`runner.py`:
```python
import json
from pathlib import Path

import numpy as np
import polars as pl
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier


def load_events(data_dir: str | Path) -> tuple[pl.DataFrame, dict]:
    d = Path(data_dir)
    events = pl.read_parquet(d / "events.parquet")
    meta = json.loads((d / "meta.json").read_text())
    if "label" not in events.columns:
        raise ValueError("events.parquet has no label column")
    leaked = [c for c in meta.get("golden_columns", []) if c in events.columns]
    if leaked:
        raise ValueError(f"golden columns found in events.parquet: {leaked}")
    return events, meta


def time_split(df: pl.DataFrame, fracs=(0.6, 0.2, 0.2)):
    df = df.sort("event_time")
    n = df.height
    a = int(n * fracs[0])
    b = a + int(n * fracs[1])
    return df[:a], df[a:b], df[b:]


def raw_features(df: pl.DataFrame) -> pl.DataFrame:
    cols = [
        c for c, t in df.schema.items() if t.is_numeric() and c != "label" and not c.endswith("_id")
    ]
    return df.select(cols).fill_null(-1)


def evaluate(y: np.ndarray, p: np.ndarray, precision_floor: float = 0.5) -> dict:
    if len(np.unique(y)) < 2:
        nan = float("nan")
        return {"auc": nan, "pr_auc": nan, "recall_at_precision": nan}
    prec, rec, _ = precision_recall_curve(y, p)
    ok = prec >= precision_floor
    return {
        "auc": float(roc_auc_score(y, p)),
        "pr_auc": float(average_precision_score(y, p)),
        "recall_at_precision": float(rec[ok].max()) if ok.any() else 0.0,
    }


def _models() -> dict:
    return {
        "logreg": lambda: make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000)),
        "xgb": lambda: XGBClassifier(
            n_estimators=200, max_depth=4, learning_rate=0.1, n_jobs=1, tree_method="hist"
        ),
    }


def run(data_dir: str | Path, oracle: bool = False) -> list[dict]:
    events, meta = load_events(data_dir)
    feature_sets = {"raw": events}
    if oracle:
        golden = pl.read_parquet(Path(data_dir) / "golden.parquet")
        feature_sets["oracle"] = events.join(golden, on="event_id")

    rows: list[dict] = []
    for fs_name, frame in feature_sets.items():
        tr, va, te = time_split(frame)
        splits = {"train": tr, "valid": va, "test": te}
        xs = {k: raw_features(v).to_numpy().astype("float64") for k, v in splits.items()}
        ys = {k: v["label"].to_numpy() for k, v in splits.items()}
        names = ["logreg", "xgb"] if fs_name == "raw" else ["xgb"]
        for name in names:
            if len(np.unique(ys["train"])) < 2:
                continue
            model = _models()[name]()
            model.fit(xs["train"], ys["train"])
            for split in ("valid", "test"):
                p = model.predict_proba(xs[split])[:, 1]
                rows.append(
                    {"model": f"{name}_{fs_name}", "split": split, **evaluate(ys[split], p)}
                )
    return rows
```

`cli.py`:
```python
import argparse
import json
from collections.abc import Sequence

from bench.runner import run


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bench")
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="train baselines on a generated dataset")
    r.add_argument("data_dir")
    r.add_argument("--oracle", action="store_true", help="also train on golden features")
    r.add_argument("--json", dest="json_path", default=None)
    args = parser.parse_args(argv)

    rows = run(args.data_dir, oracle=args.oracle)
    print(f"{'model':<14}{'split':<7}{'auc':>8}{'pr_auc':>8}{'rec@p0.5':>10}")
    for x in rows:
        print(
            f"{x['model']:<14}{x['split']:<7}{x['auc']:>8.3f}{x['pr_auc']:>8.3f}"
            f"{x['recall_at_precision']:>10.3f}"
        )
    if args.json_path:
        with open(args.json_path, "w") as f:
            json.dump(rows, f, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest apps/bench -v`
Expected: 6 passed. If `test_oracle_beats_raw_beats_chance` fails because raw AUC is near 0.5, the planted signal is too weak for raw columns at this size: raise the cash-out multiplier or hunter bonus range in `fraud.py` (the raw `amount`/`referral_bonus` columns should carry some signal), do not weaken the assertion.

- [ ] **Step 6: Commit**

```bash
git add apps/bench uv.lock
git commit -m "feat(bench): baseline benchmark runner with oracle upper bound"
```

---

### Task 11: Docs, spec sync and end-to-end verification

**Files:**
- Modify: `README.md`, `docs/superpowers/specs/2026-10-13-ml-sim-datagen-design.md`
- Create: `apps/datagen/README.md` (flesh out), `libs/simkit/README.md` (flesh out)

**Interfaces:** none.

- [ ] **Step 1: Update root README**

Add a section to `README.md`:
```markdown
## Synthetic event data + benchmark

```sh
uv run datagen generate --scenario fraud --n-events 100000 --seed 42 --out data/fraud
uv run bench run data/fraud --oracle
```

`events.parquet` is the benchmark input; `golden.parquet` holds hidden golden features and
labels' ground truth; `meta.json` records seed, config and achieved bad rate.
```
Add `data/` to `.gitignore`.

- [ ] **Step 2: Sync the spec with the refinements listed in this plan's header**

In the spec: change the `simkit` module paths to `neorisk_simkit`, replace "`build(config) -> Scenario`" with "`generate(cfg) -> Dataset`", and note that entities carry an integer `idx` (rank by creation time) internally with UUIDs attached at export, and that `MLPScorer` is an untrained seeded random-weight MLP.

- [ ] **Step 3: Flesh out the two READMEs**

`libs/simkit/README.md`: module table (copy from the spec section 4) and a 10-line example building one entity type and attaching attributes. `apps/datagen/README.md`: CLI flags, output files, and how to add a scenario (module with `generate(cfg) -> Dataset`, register in `SCENARIOS`).

- [ ] **Step 4: Full verification**

Run:
```bash
uv run ruff check . && uv run ruff format --check .
uv run pytest -v
uv run datagen generate --scenario fraud --n-events 200000 --seed 42 --out data/fraud
uv run bench run data/fraud --oracle --json /tmp/neorisk-bench.json
```
Expected: lint clean, all tests pass, generation completes (note wall time), bench table shows `xgb_oracle` test AUC above `xgb_raw` and `logreg_raw`, both above 0.5. Run the datagen command twice with the same seed and confirm `events.parquet` checksums match (`shasum`).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "docs: usage, spec sync, end-to-end verification"
```
