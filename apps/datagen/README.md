# datagen

The command line of the agentic event simulator (`neorisk_simkit`). Every command takes a project folder (`examples/<project>`) or a dataset folder (`<project>/out/<run>`).

```bash
uv run datagen validate examples/ecommerce --overlay bounty_hunters
uv run datagen run      examples/ecommerce --profile sample --overlay bounty_hunters [--set users=500] [--seed 42] [--force] [--debug]
uv run datagen check    examples/ecommerce/out/sample-s7+bounty_hunters [--seeds 2] [--skip-stats]
uv run datagen schema   examples/ecommerce --format sql --dialect duckdb [--with-fks] [--load RUN] [--unified-view]
uv run datagen schema   --diff OLD NEW
uv run datagen replay   RUN --first 100 [--with-labels] [--sink file:x.jsonl] [--sink kafka://host:9092/ecom.{event_type}]
uv run datagen export   RUN (--legacy-fraud [--labels roles|xgb|mlp] [--bad-rate R] --out DIR | --single-file all.parquet | --public-ids --out DIR)
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
  - `--labels roles` (default): a row is bad exactly when its user, or its inviter, is a ring member.
    These labels are noise-free, and the ring always buys the cheapest qualifying SKU, so every
    `bench compare` model reaches AUC ≈ 1. Good for checking the plumbing, useless for ranking
    models.
  - The `bench` profile blurs the ring with two `bounty_hunters` knobs, so role labels stop being
    trivial. `stealth_p` (0.5 there) makes that share of ring members blend in: own device,
    ordinary products at list price, ongoing browsing. They are still labeled, so they are the
    misses. `promoters_share` (0.004 there) adds genuine users whose invited friends look like
    zombies: some share the promoter's device and open with the cheapest qualifying order.
    They are never labeled, so they are the false alarms. Both knobs default to 0, and other
    profiles are unchanged.
  - `--labels xgb|mlp`: labels are sampled from a scorer over the golden features plus `is_ring`,
    calibrated to `--bad-rate` (default 0.02) and seeded by the run's seed. This is how the
    benchmark was labeled before D89. Golden `score` holds the probability, and `meta.json`
    records the scorer and its weights under `labels`. See
    `docs/superpowers/specs/2026-10-20-scorer-labels-design.md`.

Exit codes: 0 success, 1 a failed run or check, 2 a usage error or refusal.
