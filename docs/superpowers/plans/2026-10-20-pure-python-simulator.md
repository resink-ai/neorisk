# Pure-Python Agentic Event Simulator Implementation Plan

> **For agentic workers:** executed natively in one session (user choice: no sub-agents), TDD, task by task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Implement the pure-Python revision of the agentic event simulator, P1→P5 and the Exit row.

**Architecture:** A pack is a Python module whose `define(p, cfg)` registers tables, events, partition kinds (owners and shards), processes, actions, sources and checks on a `Pack`. The engine runs one heap loop that dispatches commands to partitions, and it buffers each action's effects until the action commits. Output goes into per-table column lists, which become Polars frames sorted by `(event_time, priority, seq)`. Checks, reports, schema generators and replay all read the finished output.

**Tech Stack:** Python 3.12, NumPy, Polars, PyArrow, PyYAML (for `expectations.yaml`), pytest. `confluent-kafka` is an optional extra.

**Spec:** `docs/superpowers/specs/2026-10-20-agentic-event-simulator-pure-python.md` (deltas over `2026-10-15-agentic-event-simulator-architecture.html`).

## Global Constraints

- Pure Python. No Numba, Cython, C extensions or code generation.
- The engine core, `engine/`, stays under 1,000 lines.
- There are no absolute time or throughput gates. Performance is tested as N vs 4N entities: rows grow about 4×, time grows ≤ about 6×, and peak memory grows ≤ about 4× plus a constant.
- Total order is `(event_time, priority, seq)`. `seq` is a global commit counter, and `lamport` does not exist.
- Common event columns come first, in this order: `event_id, event_type, event_time, seq, partition_id, cause_id, action_id`.
- Layout: `manifest.json`, `run_stats.json`, `schema/schema.json`, `events/<type>.parquet`, `entities/<table>.parquet`, `cases/`, `snapshots/`, `labels/labels.parquet`. There is one file per table and no Hive partitions.
- Amounts are Python ints, exported as int64 after a range check.
- Each process declares `max_spawn_depth` (default 3). The run has a `max_events` guard. Every boundary has δ > 0.

## Decisions taken while planning

- **Partition ids and entity ids are namespaced.** The base pack allocates ids `1, 2, …`. Overlay `k` allocates ids `k·10⁹ + i`. This keeps base ids identical with and without an overlay (regression rule).
- **Keyed rng.** Each partition gets `np.random.default_rng(SeedSequence(seed, spawn_key=crc32 path))`, where the path is `(namespace, creator path, process kind, ordinal)`. Partition ids are not part of the key.
- **Effects are buffered per action.** Emits, schedules, creates and inserts are applied only on commit, so a reject discards them. In debug mode the engine also deep-copies the state before the action and fails the run if a rejected action changed it, or emitted something before rejecting.
- **The base-vs-overlay regression comparison** checks base rows on every column except `event_id`, `seq` and `cause_id`, and checks that base rows stay in the same relative order.
- **Requests.** A request is delivered to the shard at the same instant, with MESSAGE priority. The shard's decision rows carry the request time. The reply arrives at `t + latency`, where latency is drawn from the shard's declared `Latency(min=δ, max)`.
- **`event_id` = `seq` by default.** An optional Feistel permutation applied at export makes `event_id` look random, while `seq` keeps the order.

## Milestones and tasks (estimates are my session time; the spec's budgets are the cap)

### P1: Pack API on the loop. Estimate 3 h (spec budget 1 day)

- [x] **T1 spec:** column types (`i32 i64 f64 text boolean ts cat ref amount opt`), the `Pack` registry (`entity/event/owner/shard/process/action/source/check`), and `load_pack(path)` → `Plan`. Tests: registration, duplicate names, unknown refs.
- [x] **T2 engine:** heap loop and `Ctx` (`emit/after/at/create/request/reply/reject/send/insert/label/retire`), priorities, `late_messages`, `max_events`, spawn depth, keyed rng, buffered commit, and the debug snapshot. Tests: priority inversion, equal keys, reject discards effects, a debug violation fails the run, a timeout races its reply, determinism.
- [x] **T3 io:** `Run` → frames in canonical order, then the writer (layout, manifest with sha256, run_stats, schema.json) and the int64 range check. Test: byte-identical replay, run twice.
- [x] **T4 ecommerce pack:** port `ecommerce.py` to `examples/ecommerce/specs/pack.py` and `datagen.toml` profiles. The referral budget becomes a pool shard reached by request.
- [x] **T5 CLI and legacy:** `datagen validate|run|export`. `legacy.py` moves to `io/legacy.py` and reads the new layout. The bench fixture moves to the new CLI. Delete `sim.py` and `ecommerce.py`.
- [x] **T6 exit tests:** the recurring-shopper trace fixture (§07), deterministic replay, and the scaling ratio test.

### P2: Shards, holds, payments. Estimate 3 h (spec budget 1–2 days)

- [x] **T7 std:** owner holds, shard reservations with TTL, a capped pool, and ledger helpers.
- [x] **T8 ecommerce:** inventory shards and multi-SKU checkout (reserve, join, commit or release), plus a hot SKU group.
- [x] **T9 payments pack:** auth/capture/refund/dispute, refund holds, refunds rejected during a dispute, and idempotency keys.
- [x] **T10 checks:** structural, per-partition laws (lifecycle, sum_le, non-negative, holds resolved) and cross-partition laws (reservation resolved by TTL, pool ≤ cap, request/response pairing). Failures cite `(partition_id, seq, action)`. Includes mutation tests and reference implementations for holds.
- [x] **T11 `datagen check`:** writes `checks.json`, and exits non-zero when a required check fails.

### P3: State machine and overlays. Estimate 4 h (spec budget 2 days)

- [x] **T12 machine interpreter:** `branch timer repeat until/then spawn join request then`, with the original's edge-case semantics.
- [x] **T13 overlay contract:** `cohort(size|share|rate)`, `suppress`, extension points, labels with `label_available_at`, namespaces. Includes the `bounty_hunters` overlay on ecommerce, the regression rule and the interference report.
- [x] **T14 expectations.yaml and statistics:** exact metrics with CIs across held-out seeds, and `report.html`.
- [x] **T15 exit:** the campaign trace (exact pool cap), legacy export parity, and bench passing.

### P4: Labels, schema, replay. Estimate 3 h (spec budget 1–2 days)

- [x] **T16 labels:** label delay end to end, and a bench loader that does maturity-aware splits from `label_available_at`.
- [x] **T17 schema:** SQL (postgres, duckdb, bigquery, snowflake, clickhouse, spark), Avro, JSON Schema, Arrow, Markdown, and `--diff`.
- [x] **T18 replay:** `--first/--last/--from/--to/--types/--where/--owners/--resume-from`, sinks (stdout, file, kafka as an optional import), pacing, `--rebase`, `--with-labels`, and the replay state file.

### P5: Vocabulary trial and Exit. Estimate 3 h (spec budget 1–2 days)

- [x] **T19 small packs:** order book (price/time, FOK preflight, IOC/GTC), L1 envelope (nonce, fee, revert), SNS cascade. Each gets laws and reference-implementation tests.
- [x] **T20 exit:** `examples/AGENTS.md`, then a payments variant and a new overlay written from a brief using only AGENTS.md, with no engine changes. Then the full suite and the scaling test.

## Review Focus

1. A pack action that raises an exception. Expected: the run fails with the process, action, partition and time in the message.
2. A timer or message to a retired partition. Expected: it is dropped and counted in `late_messages`, never raised (T2 test).
3. A runaway spawn or event loop. Expected: the run fails with a diagnostic naming the process (T2 test).
4. An existing run directory without `--force`. Expected: refuse with exit code 2 (T5 test).
5. An emitted column missing from the schema, or of the wrong type. Expected: debug mode fails at emit time, and normal mode fails at end of run (T3 test).

## Actuals (2026-10-19, one native session, 22:44 → 23:50)

| Milestone | Estimate | Actual | Notes |
|---|---|---|---|
| P1 | 3 h | 17 min | The ring overlay and `std` holds/reservations were pulled forward (port and trace needed them) |
| P2 | 3 h | 9 min | |
| P3 | 4 h | 13 min | |
| P4 | 3 h | 7 min | |
| P5 + Exit | 3 h | 20 min | The exit exercise found a label-identity defect (fixed: labels keyed by table and id) |

Engine core: 747 lines (target < 1,000). Library: about 5,000 lines (estimate 3.8–6k). Tests: 245, about 37 s.

Deviations from the plan or spec:
- `history/` (change groups) is not written; attribute changes are ordinary events (`address_changed`).
- Reference implementations live in `checks/reference.py` rather than `checks/domains/`.
- The CODEOWNERS rule is not added: it needs real reviewer handles.
