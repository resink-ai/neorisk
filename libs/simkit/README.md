# neorisk-simkit

The agentic event simulator's library, plus scenario-agnostic primitives for synthetic event
data. Import name: `neorisk_simkit`. Pure Python (NumPy, Polars, PyArrow, PyYAML); Kafka is the
optional extra `neorisk-simkit[kafka]`.

## The simulator

| Package | Responsibility |
|---|---|
| `spec` | The pack API (`Pack`, column types, `Latency`), overlays, the normalized plan and `validate`, distributions |
| `engine` | The event loop (one heap, one thread), the action context, keyed random streams, typed output frames |
| `machine` | The state-machine interpreter (branch, timer, repeat, spawn, join, request, then) |
| `std` | Recipes: owner holds, shard reservations with a TTL, capped pools |
| `checks` | Structural checks, law factories, reference implementations, expectations (`stats`), the overlay regression rule |
| `io` | The dataset writer and reader, single-file export, public ids, the legacy fraud adapter |
| `schema` | `schema.json`, SQL (six dialects), Avro, JSON Schema, Arrow, Markdown, `--diff` |
| `replay` | Selection, pacing and sinks (stdout, file, Kafka) |
| `report` | `report.html` |
| `project` | Project folders, `datagen.toml` profiles, provenance |

How to write packs and overlays: [`examples/AGENTS.md`](../../examples/AGENTS.md). The
design: `docs/superpowers/specs/2026-10-20-agentic-event-simulator-pure-python.md`.

## Primitives

| Module | Responsibility | Interface |
|---|---|---|
| `attributes` | AttrSpec + change-point timeline sampler | `AttrSpec`, `sample_timeline` |
| `entities` | Entity type = ID namespace + attr specs; as-of attribute join | `EntitySpec`, `build_entities`, `attach_asof`, `map_ids` |
| `references` | RefSpec + choosers filling reference columns with existing entity idx | `RefSpec`, `uniform`, `skewed`, `hubs`, `resolve_reference` |
| `features` | Point-in-time rolling windows over [t-w, t) grouped by any key; `rolling_asof` evaluates a source table (e.g. invites keyed by inviter) at arbitrary query rows | `rolling(df, key=, value=, windows_days=, aggs=, prefix=)`, `rolling_asof(queries, source, query_key=, source_key=, ...)` |
| `scorer` | Label-probability scorers and bad-rate calibration | `XGBScorer`, `MLPScorer`, `calibrate`, `sample_labels` |
| `export` | Attach UUIDs and write outputs | `Dataset`, `export(ds, out_dir)` |
| `ids` | Seeded UUID generation | `make_uuids` |

Entities carry an integer `idx` (rank by creation time) internally; UUIDs are attached at export.
`MLPScorer` is an untrained seeded random-weight MLP; `XGBScorer` fits a seeded tree model
(native xgboost train API) to a tanh/sigmoid teacher over z-scored golden features.

```python
import numpy as np
import polars as pl
from neorisk_simkit import (
    AttrSpec,
    Cardinality,
    EntitySpec,
    Volatility,
    attach_asof,
    build_entities,
)

rng = np.random.default_rng(0)
spec = EntitySpec(
    "user",
    n=1000,
    attrs=(
        AttrSpec("country", Cardinality.LOW, Volatility.STATIC),
        AttrSpec("address", Cardinality.HIGH, Volatility.SLOW),
    ),
)
users = build_entities(spec, np.datetime64("2026-01-01"), np.datetime64("2026-07-01"), rng)
events = pl.DataFrame(
    {
        "user_idx": [0, 1],
        "event_time": np.array(["2026-05-01", "2026-05-01"], dtype="datetime64[us]"),
    }
)
events = attach_asof(events, users, idx_col="user_idx")  # adds user_country, user_address
```
