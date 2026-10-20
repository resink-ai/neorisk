# datagen

The command line of the agentic event simulator (`neorisk_simkit`). Every command takes a project folder (`examples/<project>`) or a dataset folder (`<project>/out/<run>`).

```bash
uv run datagen validate examples/ecommerce --overlay bounty_hunters
uv run datagen run      examples/ecommerce --profile sample --overlay bounty_hunters [--set users=500] [--seed 42] [--force] [--debug]
uv run datagen check    examples/ecommerce/out/sample-s7+bounty_hunters [--seeds 2] [--skip-stats]
uv run datagen schema   examples/ecommerce --format sql --dialect duckdb [--with-fks] [--load RUN] [--unified-view]
uv run datagen schema   --diff OLD NEW
uv run datagen replay   RUN --first 100 [--with-labels] [--sink file:x.jsonl] [--sink kafka://host:9092/ecom.{event_type}]
uv run datagen export   RUN (--legacy-fraud --out DIR | --single-file all.parquet | --public-ids --out DIR)
```

## Commands

- **`validate`** reports structural contradictions:
  - schema errors and unknown references;
  - δ = 0 boundaries;
  - unbounded spawns;
  - bad state machines;
  - overlay contract violations;
  - mutable module globals.
- **`run`** writes `out/<profile>-s<seed>[+overlay]`:
  - `manifest.json`, which is part of replay identity: provenance, config, counts, stats and file hashes;
  - `run_stats.json`: timings and peak RSS;
  - `schema/schema.json`;
  - `events/<type>.parquet`, in canonical order;
  - `entities/`, `labels/`, `cases/` and `snapshots/`.

  Runs are deterministic: the same specs, settings and lockfile give byte-identical files. An existing run folder is never overwritten without `--force`. `--debug` checks every emit against the schema and snapshots state around rejections; it never changes the rows.
- **`check`** writes `reports/<run>/checks.json` and `report.html`. It runs:
  - structural checks;
  - the pack's laws;
  - `expectations.yaml`, with 95% intervals across held-out seeds when given `--seeds`;
  - for overlay runs, the regression rule and the interference report.

  It exits 1 when a required check fails, errors, is inconclusive, or is unanchored (the specs changed since the run).
- **`schema`** generates SQL (postgres, duckdb, bigquery, snowflake, clickhouse, spark), Avro, JSON Schema, Arrow or Markdown from a pack or from a dataset. `--diff` exits 1 on a column change without a `SCHEMA_VERSION` bump.
- **`replay`** streams a dataset in canonical order:
  - selection: `--first`/`--last`, `--from`/`--to`, `--types`, `--where`, `--owners`, `--resume-from`/`--resume`;
  - pacing: `--pace x60`, `--rate`, `--rebase now`;
  - `--with-labels` adds `label_available` events at the time each label becomes known.

  Sinks are stdout, files (jsonl, json-array, csv, parquet) and Kafka. Kafka needs `neorisk-simkit[kafka]`. Delivery is at-least-once, with a `.replay-state.json` for resuming.
- **`export --legacy-fraud`** writes the shape `bench` reads (`events.parquet`, `golden.parquet`, `meta.json`) from an e-commerce + `bounty_hunters` run.

Exit codes: 0 success, 1 a failed run or check, 2 a usage error or refusal.
