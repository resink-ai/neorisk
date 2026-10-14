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
libs/simkit/        framework (no scenario knowledge)
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

### Linkages (edges)

A linkage is a typed, directed edge list between entities, with edge attributes:
`(edge_id, src_id, dst_id, edge_time, <edge attrs>)`. Example: `invite` edges
(inviter -> invitee) with edge attribute `referral_bonus`. Edge attributes use the same
synthetic-value rules as entity attributes (integers, cardinality/volatility specs; edge
attrs are fixed at `edge_time`).

- `LinkageSpec(name, src_entity, dst_entity, edge_attrs, generator)`: the generator
  decides who links to whom, so scenarios can plant structure (e.g. a few "bounty
  hunter" inviters each with many low-activity "zombie" invitees and large total bonus).
- Edges are time-stamped, so graph features are computed point-in-time like any other
  golden feature.
- Visibility is per linkage (`visible=True|False`): visible edge lists are exported as
  raw benchmark input; hidden ones join the ground truth. Graph-*derived* features are
  always golden.

### Golden features

Derived from events + entity attributes, computed point-in-time (strictly before the
event) so there is no future leakage. Examples: per-user count/sum/avg/max/min over
7/14/30 days; max-to-median amount ratio; users-per-device over 7d; recent
address/state change count. Graph-derived examples: out-degree per inviter over
7/14/30d, total/avg/max referral bonus per inviter, share of invitees with no further
activity (zombie ratio), invitee-cluster size. Never present in benchmark inputs.

### Labels

`golden features -> Scorer -> p in [0,1] -> calibrate to target bad rate -> Bernoulli`.
Scorer is a fixed-parameter XGBoost (random preset weights, seeded) or small MLP.

## 4. Components

### libs/simkit

| Module | Responsibility | Interface |
|---|---|---|
| `attributes` | AttrSpec + change-point timeline sampler | `build_entity_table(n, specs, time_range, rng) -> pl.DataFrame` |
| `entities` | Entity type = ID namespace + attr specs | `EntitySpec(name, n, attrs)` |
| `linkages` | LinkageSpec + edge sampler with time-stamped edge attributes | `generate_edges(spec, entity_tables, time_range, rng) -> pl.DataFrame` |
| `events` | Sample events, link entities, as-of join attributes | `EventSpec(...)`, `generate_events(...)` |
| `features` | Point-in-time rolling-window helpers (events and edges) | `rolling(events, key, col, windows, aggs)`, `edge_agg(edges, key, col, windows, aggs)` |
| `scorer` | Scorer interface, XGBScorer, MLPScorer, bad-rate calibration | `Scorer.score(df) -> p`, `calibrate(p, target_rate)` |
| `export` | Write outputs | `export(dataset, out_dir)` |

### apps/datagen

`datagen generate --scenario fraud --n-events 1000000 --seed 42 --out data/fraud/`

Scenarios are modules in `datagen/scenarios/` exposing `build(config) -> Scenario`.

Outputs:
- `events.parquet` — raw event/entity columns + label (benchmark input)
- `golden.parquet` — `event_id` + golden features + score (hidden ground truth)
- `edges_<linkage>.parquet` — one per visible linkage (`edge_id, src_id, dst_id,
  edge_time, edge attrs`); hidden linkages go to `golden_edges_<linkage>.parquet`
- `meta.json` — seed, scenario, config, achieved bad rate, versions

### apps/bench

`bench run data/fraud/` reads only `events.parquet`; time-based train/valid/test split;
baselines: logistic regression, XGBoost on raw columns; optional `--oracle` trains on
golden features as an upper bound. Reports AUC, PR-AUC, recall@fixed-precision as a
table and JSON.

## 5. Fraud scenario (v1)

- Entities: user (~5–10 synthetic attrs incl. state, street), device (static OS/model,
  fast battery, slow-ish IP), product (static launch time, category).
- Behavior: bursty per-user activity; some users warm up with small amounts then one
  large amount.
- Golden features: velocity (count/sum/avg/max/min × 7/14/30d), amount ratio,
  users-per-device 7d, recent address-change count.
- Linkage: `invite` (user -> user, edge attr `referral_bonus`). Plant bounty-hunter
  inviters with many zombie invitees and large total bonus; their events are more
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
- Linkages: edge endpoints reference existing entity IDs; edge times within range;
  planted structure present (bounty hunters' degree and bonus well above baseline);
  graph features at *t* use only edges with `edge_time < t`.
- Export: golden columns absent from `events.parquet`.
- Bench smoke test on tiny data: oracle AUC > raw-column AUC > 0.5.

## 8. Out of scope (v1)

Heterogeneous multi-hop graph features beyond 1-hop aggregates, graph neural-net
baselines, agent-based behavior simulation, declarative YAML scenarios, distributed scale
(Spark), full model leaderboard/reports, LTV and growth-risk scenarios (framework
must make them addable, but they are not built).
