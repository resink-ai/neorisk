# Synthetic Event Data Generator + Baseline Benchmark — Design

Date: 2026-10-13
Status: Draft for review

## 1. Goal

Build, inside the uv workspace, an application that generates realistic-*structured*
synthetic tabular event data for benchmarking risk-control and user-profiling models
(fraud first; growth risk and LTV later). Labels are produced from hidden "golden
features" via a preset-weight scorer, so ground truth is known exactly. A minimal
benchmark runner trains baselines on the exported raw data to confirm the planted
signal is learnable.

### Decisions (from brainstorming)

| Topic | Decision |
|---|---|
| Realism | Planted-signal: sampled entities/events, golden features computed point-in-time, preset scorer produces labels. No agent-based simulation in v1. |
| Scenario definition | Python modules on a shared framework lib (no YAML engine). |
| Scale / format | Up to ~1–10M events; Parquet; polars. |
| v1 scope | Generator + minimal baseline benchmark runner. Full benchmark suite is a later project. |
| Attribute values | Synthetic integers (no real values); UUID IDs; attributes may be unnamed (`attr_i`). |
| Attribute dynamics | Change points sampled independently of events; fast attributes random-walk. |

## 2. Layout

```
libs/simkit/        framework, import name `neorisk_simkit` (no scenario knowledge)
apps/datagen/       CLI + scenarios (fraud first)
apps/bench/         baseline runner; reads only exported events.parquet
```

Follows the repo convention (`libs/*` shared, `apps/*` consume via `workspace = true`).

## 3. Data model

### Entities and attributes

Each entity type (user, device, product, ip, ...) has a UUID ID namespace and a set of
synthetic attributes. Every attribute is described by `AttrSpec` along two axes:

| Axis | Values | Example |
|---|---|---|
| cardinality | low (int 1..K) / high (wide int range) | state 1..50; street 0..10^6 |
| volatility | static / slow / fast | device model static; state slow; battery fast |

Generation per entity: sample an initial value from the attribute's distribution, then
sample change points over the simulation time range (Poisson rate by volatility). Fast
attributes move by small random walk steps (e.g. battery 7→6→8); slow attributes
redraw rarely. Stored long-form: `(entity_id, attr, valid_from, value)`.

Properties:
- Within a short window the same entity's attributes are stable across events.
- Across entities, values are independent draws, so mostly different.
- Static attributes never change for a given entity ID.
- Address is split into `state` (low-cardinality, slow) and `street`/`zip` (high-cardinality).

### Events

One row per event. Columns: `event_id` (UUID), `event_time`, linked entity IDs
(`user_id`, `device_id`, `product_id` nullable), event attributes (`amount`,
`currency`, ...), and entity attributes resolved **as-of event time** (latest
`valid_from <= event_time`), plus `label`.

### Linkages (reference columns)

There is no separate edge table. A linkage is a **reference column**: an ordinary event
or entity attribute whose value is another entity's ID. Example: an `invite` event has
`user_id` (the invitee), `inviter_id` (the inviter's `user_id`), and `referral_bonus`
(an event attribute). The graph is implicit in these columns and is recovered by
grouping on the reference column.

- `RefSpec(column, target_entity, nullable, chooser)`: declares a reference column and a
  `chooser` that picks the referenced ID per row, so scenarios can plant structure (e.g.
  few "bounty hunter" inviters chosen far more often, whose invitees are zombies).
- Event-level references take the event time; entity-level references are ordinary
  attributes with change points (so a reference can also change over time).
- Referenced IDs must exist before the row's time (inviter registered earlier).
- Reference columns are normal raw columns and are visible to the benchmark. Features
  derived by aggregating over them (degree, bonus totals, zombie ratio) are golden.

### Golden features

Derived from events + entity attributes, computed point-in-time (strictly before the
event) so there is no future leakage. Examples: per-user count/sum/avg/max/min over
7/14/30 days; max-to-median amount ratio; users-per-device over 7d; recent
address/state change count. Graph-derived examples: out-degree per inviter over
7/14/30d, total/avg/max referral bonus per inviter, share of invitees with no further
activity (zombie ratio), invitee-cluster size. Never present in benchmark inputs.

### Labels

`golden features -> Scorer -> p in [0,1] -> calibrate to target bad rate -> Bernoulli`.
Scorer is an XGBScorer, which fits a seeded tree model to a tanh/sigmoid teacher over z-scored golden
features, or a small seeded MLP.

## 4. Components

### libs/simkit (import `neorisk_simkit`)

Entities carry an integer `idx` (rank by creation time) internally; UUIDs are attached at export.
There is no separate `events` module in the final implementation: scenarios sample events directly and use
`attach_asof` / `resolve_reference`. `MLPScorer` is an untrained, seeded random-weight MLP; `XGBScorer` fits a
seeded tree model (native xgboost train API) to a tanh/sigmoid teacher over z-scored golden features.

| Module | Responsibility | Interface |
|---|---|---|
| `attributes` | AttrSpec + change-point timeline sampler | `sample_timeline(spec, created_at, t1, rng)` |
| `entities` | Entity type = ID namespace + attr specs; as-of attribute join | `EntitySpec(name, n, attrs)`, `build_entities`, `attach_asof` |
| `references` | RefSpec + choosers that fill reference columns with existing entity IDs | `RefSpec(column, target_entity, chooser)`; used by scenario code via `resolve_reference` |
| `features` | Point-in-time rolling-window helpers (grouped by any ID or reference column) | `rolling(df, key=, value=, windows_days=, aggs=, prefix=)`; `key` may be a reference column |
| `scorer` | Scorer interface, XGBScorer, MLPScorer, bad-rate calibration | `Scorer.score(golden) -> p`, `calibrate(p, target_rate)`, `sample_labels` |
| `export` | Write outputs | `export(dataset, out_dir)` |

### apps/datagen

`datagen generate --scenario fraud --n-events 1000000 --seed 42 --out data/fraud/`

Scenarios are modules in `datagen/scenarios/` exposing `generate(cfg) -> Dataset`, registered in `datagen.scenarios.SCENARIOS`.

Outputs:
- `events.parquet` — raw event/entity columns + label (benchmark input)
- `golden.parquet` — `event_id` + golden features + score (hidden ground truth). Columns: `u_amt_{count,sum,mean,max,min}_{7,14,30}d`, `dev_users_n_unique_7d`, `addr_chg_sum_30d`, `amt_ratio_30d`, `inv_bonus_{count,sum,mean,max}_{7,14,30}d`, `inv_zombie_mean_30d`, `invitee_is_zombie`, `score`. Graph features on a transaction are looked up as-of from the user's invite row (frozen at invite time).
- `meta.json` — seed, scenario, config, achieved bad rate, versions

### apps/bench

`bench run data/fraud/` reads only `events.parquet`; time-based train/valid/test split;
baselines: logistic regression, XGBoost on raw columns; optional `--oracle` trains XGBoost on raw numeric columns plus all golden columns except `score`
(the label-generating probability, which stays in `golden.parquet`), so it is a golden-feature ceiling rather than a realistic feature-engineering bound. Reports AUC, PR-AUC, recall@fixed-precision as a
table and JSON.

## 5. Fraud scenario (v1)

- Entities: user (~5–10 synthetic attrs incl. state, street), device (static OS/model,
  fast battery, slow-ish IP), product (static launch time, category).
- Behavior: bursty per-user activity; some users warm up with small amounts then one
  large amount.
- Golden features: velocity (count/sum/avg/max/min × 7/14/30d), amount ratio,
  users-per-device 7d, recent address-change count.
- Linkage: `invite` events carry `inviter_id` and `referral_bonus`. Plant bounty-hunter
  inviters with many zombie invitees and large total bonus; events tied to them are more
  likely labeled bad via the graph-derived golden features.
- Target bad rate default ~2%, configurable.

## 6. Error handling

- Config validation up front (cardinalities, rates, windows, target bad rate in (0,1)).
- Export refuses to write golden columns into `events.parquet` (guard check).
- Bench fails fast if `events.parquet` contains no label or contains known golden column names.

## 7. Testing

- Determinism: same seed → identical output.
- Attributes: short-window stability, cross-entity variation, volatility ordering,
  cardinality ranges.
- Leakage: rolling features at *t* use only events < *t* (property test vs brute force).
- Labels: achieved bad rate within tolerance.
- References: referenced IDs exist and predate the row; planted structure present
  (bounty hunters' degree and bonus well above baseline); features grouped by a
  reference column at *t* use only rows with time < *t*.
- Export: golden columns absent from `events.parquet`.
- Bench smoke test on tiny data: oracle AUC > raw-column AUC > 0.5.

## 8. Out of scope (v1)

Heterogeneous multi-hop graph features beyond 1-hop aggregates, graph neural-net
baselines, agent-based behavior simulation, declarative YAML scenarios, distributed scale
(Spark), full model leaderboard/reports, LTV and growth-risk scenarios (framework
must make them addable, but they are not built).
