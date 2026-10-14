# neorisk-simkit

Scenario-agnostic primitives for synthetic event data. Import name: `neorisk_simkit`.

| Module | Responsibility | Interface |
|---|---|---|
| `attributes` | AttrSpec + change-point timeline sampler | `AttrSpec`, `sample_timeline` |
| `entities` | Entity type = ID namespace + attr specs; as-of attribute join | `EntitySpec`, `build_entities`, `attach_asof`, `map_ids` |
| `references` | RefSpec + choosers filling reference columns with existing entity idx | `RefSpec`, `uniform`, `skewed`, `hubs`, `resolve_reference` |
| `features` | Point-in-time rolling windows over [t-w, t) grouped by any key | `rolling(df, key=, value=, windows_days=, aggs=, prefix=)` |
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
