# dataset

Validation datasets: one ordered event log in, organized tables out. The catalogue and the layout are in [`datasets/README.md`](../../datasets/README.md); the design is `docs/superpowers/specs/2026-11-03-validation-datasets-design.md`.

```bash
uv run dataset list [--json]                       # name, kind, version, built here: yes | unrecorded | stale | no
uv run dataset build NAME [--db SRC] [--record]    # recipe → log, results, expected, manifest
uv run dataset verify NAME [--json FILE]           # reference build over the log vs the results
uv run dataset resolve NAME/VERSION[/PATH]         # the path under NEORISK_DATA_ROOT
```

Exit codes are 0 for success, 1 for a difference (or a build that differs from its lock), and 2 for a usage error, an unknown name or a missing input.

| Module | Holds |
|---|---|
| `names` | Data names (`<dataset>/<version>/<path>`) and the data root (`NEORISK_DATA_ROOT`, default `data/datasets`) |
| `config` | `dataset.toml` |
| `tables` | Results tables from SQLite, typed by their stored values; the exact comparator every engine is graded with |
| `manifest` | File checksums, the recipe hash, and the lock file (`<version>.lock.json`) |
| `spider2` | `build_spider2` and `verify` |

The log itself is written by `neorisk_simkit.io.log` and decoded for SQL by `refdata.logviews`.
