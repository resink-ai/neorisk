# Agentic Event Simulator — Milestone S1 Implementation Plan

**Spec:** `docs/superpowers/specs/2026-10-15-agentic-event-simulator-architecture.html` (binding authority; §18 defines S1, §17 the module layout). Read §05, §06, §10, §12, §13, §14, §15 before any engine task.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship milestone S1, the owner slice: e-commerce users with sessions, carts, single-SKU checkout against inventory shards and cross-device KYC as handwritten Numba kernels; the output layout with a step index; `datagen schema` for Postgres and DuckDB; replay to stdout and file; the bench feature allowlist; every S1 exit test; and `benchmarks/s1.toml` with the gate measured and reported.

**Architecture:** `libs/simkit` gains `spec/` (pack API, plan, validate, memory caps), `engine/` (ABI, AST lowering of kernels to Numba free functions, generated emitters, slabs, command queues, calendar queue, rounds with a safe horizon, identity, keyed RNG), `std/` (checked arithmetic, sources, handoff), `checks/structural.py`, and `io/` (seal merge, Parquet writer, manifest, step index, schema generators, replay, sinks). `apps/datagen` gets `validate · run · schema · replay · benchmark` next to the legacy `generate`. A new project `examples/ecommerce_s1/` is the S1 slice the engine runs; `examples/ecommerce/` stays the M3 target, untouched.

**Tech Stack:** Python 3.12, uv workspace, numba, numpy, pyarrow, polars, duckdb (tests only), pytest, ruff.

## Global Constraints

Every task implicitly includes this section. Values are copied from the spec; do not change them.

**Repo**
- Python `>=3.12`; ruff `line-length = 100`; ruff must pass after every task on the existing paths among `libs apps examples/ecommerce_s1 benchmarks` (`examples/ecommerce_s1` exists from Task 14, `benchmarks` from Task 24; naming a missing path fails with E902). Every task's lint step uses exactly this form: `uv run ruff check $(ls -d libs apps examples/ecommerce_s1 benchmarks 2>/dev/null)` (Task 1 adds a per-file ignore of `B008`, `RUF009` for `examples/**`, where dataclass `dist.*` defaults are the authoring style).
- Workspace members `libs/*`, `apps/*`. Run tests with `uv run --all-packages pytest ...` (a bare `uv run pytest` does not install workspace members in this checkout). The full existing suite `uv run --all-packages pytest` must keep passing after every task.
- Test file basenames are unique across the repo; no `__init__.py` in test dirs. Fixture projects live in `libs/simkit/tests/fixtures/<name>/` (`datagen.toml` + `specs/pack.py` + `specs/kernels.py`, no `__init__.py`; the loader treats `specs/` as a package).
- New dependencies (spec §17): `numba` and `pyarrow` in `libs/simkit/pyproject.toml`; `duckdb` in the root `dev` group (tests only). `confluent-kafka` is not added in S1.
- Commit messages end with:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN
  ```

**Action interface (§05)**
- Every action follows: validate → reserve every resource it might use → commit. Nothing after a successful reserve can fail.
- `reserve` takes counts for every resource: records per event table, created rows per table, timer-heap entries, outbound requests and messages. Each kernel declares its maxima (`max=Res(…)`); the runtime checks the vector against the worker's slabs and pools in one call.
- `reject` and `RETRY` are legal only before the first write; debug (checked) mode snapshots the row and fails the run otherwise.
- `RETRY` means the runtime swaps in a fresh slab and re-invokes the same command. Random draws are keyed by `(seed, instance, action, occurrence, site, k)`, where `k` counts draws at one site within an invocation and `occurrence` advances only on commit or reject, so a retry replays identical draws.
- Unbounded fan-out declares a constant sub-step size (e.g. 64), processes at most that many, stores a cursor, and schedules a same-time continuation at the top priority. Results never depend on buffer capacity.
- `a.then(b)` is two atomic actions; an atomic composite is one kernel.
- Typed generated emitters: `out.emit_<event>`, `out.create_<table>`, `out.timer`, `out.request…` are generated per schema and write into slabs. `create` returns a provisional handle usable immediately within the step.
- Kernels get a row view of their own partition's state and read-only arrays for shared inputs. A lint flags mutable module globals. Debug mode runs compiled with bounds checking; arithmetic on amounts uses checked helpers, so overflow behaves the same compiled and uncompiled.
- A timer or message addressed to a retired instance is detected by slot generation, dropped, and counted as `late_messages` in the manifest.

**Execution model and order (§06)**
- Every piece of mutable state has exactly one partition (owner or shard). Partitions interact only through immutable messages; payloads are copied, never aliased.
- Every boundary declares a minimum latency δ > 0. Responses arrive at `t_request + latency`, latency ≥ δ. Shard-emitted records carry the shard's true decision time.
- Joint constraints use holds: the owner holds its side, the shard decides its side, the owner commits or releases.
- Creating an owner is a creation message; the new owner starts at its creation time in the next round of the same step.
- Run ahead: each runnable owner executes its events in order until the step end or until it issues a request, then the whole owner suspends.
- Safe horizon `H = min(step end, min over suspended owners of (request time + δ))`; shards process every request with time < H in canonical order. (Planner extension: see decision D5.)
- Calendar queue: partitions in time buckets by next event time; no step scans all owners.
- `max_spawn_depth` default 3 (depth enforcement in S2, spec §17); per-step `max_admissions`; exceeding either fails the run naming the process (S1: `CapExceeded("max_admissions_per_step", …)` whose message ends with `in process <name>`, Tasks 10 and 18).
- A step seals only when no owner is runnable below the step end, no request below the step end is pending, and no creation is unadmitted.
- Execution pops commands by `(time, priority, cause_lamport, seq)`. Scheduled times must be ≥ the current time.
- `lamport = max(partition_clock, cause_lamport) + 1`, assigned at commit; one `partition_clock` per partition, shards included.
- Replay canonical key: `(event_time, lamport, partition_id, seq)`.
- Same-time precedence is declared as command priority: messages before timers by default, continuations first. KYC declares redemption at exactly the expiry instant as expired.
- Run boundary mode `time` (default): warm-up generated but not exported. (Snapshots, censoring reports, `population` and event-count modes are deferred.)

**Identity (§12)**
- `create` returns `(partition, local ordinal)`, flagged provisional, usable immediately in the same step.
- New rows of each table get dense indices at step close by prefix sum over partitions in `partition_id` order, then local ordinal. In-step references are remapped before writing.
- Exported IDs are a seeded Feistel permutation of `(table, dense index)` into 63 bits: collision-free, positive signed int64.
- Live state rows are slots; each slot has a generation bumped on reuse.
- Identical replay: byte-identical data files and manifest under a fixed writer config; `run_stats.json` excluded.
- Thread, slab and step invariance: 1, 4, 16 threads × two slab sizes × two step lengths give identical logical records.

**Output layout (§13)**
```
<run>/
  manifest.json      # schema version, revisions, seed, config, counts per table, checks, file list + sha256
  run_stats.json     # timings, rates, peak RSS (not part of replay identity)
  schema/schema.json # every table, column, type, nullability, refs, docs
  _index/steps.parquet   # one row per step: step, t_start, t_end, first/last canonical key, rows per table
  events/<type>/date=YYYY-MM-DD/step-NNNNNN.parquet
  entities/<table>/part-00000.parquet    # public id, created_at, origin, static columns
  history/<group>/date=YYYY-MM-DD/step-NNNNNN.parquet
```
- One typed table per event type; one file per frontier step; every file sorted by the canonical key.
- Writer settings fixed and pinned in the manifest: zstd level 3, 128k-row groups (131,072), dictionary encoding for categories, statistics on `event_time` and IDs.
- Common columns, first in every event table, in this order: `event_id, event_type, event_time (timestamp µs UTC), lamport, partition_id, seq, cause_id, action_id`.
- Amounts are int64 at a declared per-asset quantum.

**Schema (§14)** — type mapping for the two S1 dialects:

| Logical | Arrow / Parquet | Postgres | DuckDB |
|---|---|---|---|
| ref, ids | int64 | BIGINT | BIGINT |
| i16 / i32 / i64 | int16 / int32 / int64 | SMALLINT / INTEGER / BIGINT | SMALLINT / INTEGER / BIGINT |
| amount | int64 | NUMERIC(38,0) | DECIMAL(38,0) |
| timestamp | timestamp[µs, UTC] | TIMESTAMPTZ | TIMESTAMPTZ |
| cat(…) | dictionary<int16, string> | TEXT + CHECK | ENUM |
| text, bool, f64 | string, bool, float64 | TEXT, BOOLEAN, DOUBLE PRECISION | VARCHAR, BOOLEAN, DOUBLE |
| opt(x) | nullable x | column without NOT NULL | column without NOT NULL |

(The spec table lists `i32 / i64` only; `i16 → SMALLINT` is decision D24.) Header line: `-- generated by datagen schema · pack <name> @ <revision> · schema_version <n>`. `COMMENT ON TABLE`; `CREATE INDEX <t>_time ON <t> (event_time, lamport);`.

**Replay & sinks (§15)**
- Replay never reruns the simulation; it reads Parquet only. Order is always canonical.
- `--first N`, `--last N`, `--from T --to T` (from ≤ event_time < to), `--types a,b`; filters combine first, then `--first`/`--last`.
- Sinks: `stdout` (jsonl default, table, csv; a closed pipe ends the replay without error); `file:PATH` (jsonl, json-array, csv, parquet; written to `PATH.tmp` and renamed when complete; json-array is one valid streamed list).
- Message shape: one flat object per event, common columns then that type's columns. IDs and amounts are JSON strings by default; `--numbers` emits numbers. Timestamps are RFC 3339 with microseconds.
- `Sink` protocol: `open(schema, opts)`, `write(batch)` (canonical order, ≤ 64k rows), `checkpoint()`, `close() -> SinkReport`. Exit report: rows read and sent per sink, rate, first and last canonical key, errors; exit code non-zero if any sink failed. Labels are excluded.

**Memory (§10)** — every item has a hard cap enforced at runtime and an estimate from validate; a run whose caps exceed the budget is refused up front; a run that hits a cap fails with the item named; v1 has no spilling.

| Item (name used in code) | Hard cap |
|---|---|
| `output_slabs` | workers × slabs per worker × slab bytes |
| `step_output` | per-step row and byte cap; step length adapts deterministically from the previous step's row count, targeting 25% of the cap |
| `merge_working_space` | 2 × step output |
| `live_partition_state` | declared max live partitions × row bytes |
| `timer_heaps` | physical entries × entry bytes (D8: 40 B) |

Deviation from spec §10 (24 B): kept at 40 B to avoid a payload indirection on the hot path; memory caps use the real size.
| `requests_and_inboxes` | per-step message count × payload bytes |
| `fanout_bursts` | sub-step size × record bytes per partition |
| `read_inputs` | counted as resident |
| `checker_state` | keyed aggregates × bytes per key (0 in S1) |
| `scorer` | fixed model size plus one batch (0 in S1) |

**Gate (§10, §18)**
- `benchmarks/s1.toml`: 2M users, 90 days, 10⁷ exported events, 12 property columns (~120 B/row), one typed change group, Pareto activity α = 1.2, 8% of proposals touching inventory shards.
- Gate: `benchmarks/s1.toml` ≤ 60 s warm, peak RSS ≤ 16 GB. Timing runs from engine start with a warm JIT cache to `manifest.json` written; cold compile is timed separately. Numba plus Polars threads are capped at 16. Reference machine: one 16-core, 64 GB machine.

## Decisions made by the planner

Where the spec is silent or ambiguous; each line is binding for this plan.

- **D1** S1 runs a new slice project `examples/ecommerce_s1/`; `examples/ecommerce/` is left untouched — it needs M3 machines, S2 `std.reservations`/`std.capped_pool` and overlays.
- **D2** The authoring surface (`out.emit_x(...)`, `s.x`, `loc.x`, `cmd.x`, `ctx.rng.f(site=…)`) is kept and lowered by an AST pass to Numba free functions over tuples of arrays — jitclass cannot be cached, and the warm-JIT gate needs `cache=True`.
- **D3** "Uncompiled" = the same run in a subprocess with `NUMBA_DISABLE_JIT=1`; "checked" = `NUMBA_BOUNDSCHECK=1` plus the engine's ABI debug checks (`checked=True`) — both apply uniformly to generated and static code.
- **D4** Rounds whose runnable set is smaller than `engine.parallel_min_partitions` run inside one compiled loop on the calling thread; only large rounds use the thread pool — with `H` = earliest request + δ, rounds per step track distinct request windows, so per-round Python overhead would break the gate. Rounds per step are reported.
- **D5** The safe horizon is also bounded by the earliest unadmitted creation time: `H = min(step end, min(t_req + δ), min(t_create))` — a created owner starts next round and could otherwise request below `H`.
- **D6** A shard decides a request at the request's time (§07 shows decision records at 10:00:00.0); one-way messages (`p.message`) are processed at send time + latency and never suspend the sender; only requests (which have responses) suspend.
- **D7** An owner is suspended while it has outstanding responses (`pending > 0`) and executes nothing meanwhile (blocking, spec §06). It resumes at T_r, the latest of those responses' times: the responses run first, then every command queued before T_r, in order, at the effective time max(time, T_r). Requests are dated exactly `ctx.t`; every partition executes commands in nondecreasing time (always-on guard).
- **D8** A command node is 40 B (time, key, seq, tag, next, kind, proc, payload index), not 24 B; `timer_heaps` uses 40 B. Deviation from spec §10 (24 B): kept at 40 B to avoid a payload indirection on the hot path; memory caps use the real size.
- **D9** Command key packing: `key = priority << 56 | cause_lamport`, priority 0..63, cause_lamport < 2⁵⁶; the fourth key part is the receiving partition's command sequence number.
- **D10** Priorities: `PRIO_CONTINUE = 0`, `PRIO_MESSAGE = 1` (responses, messages, starts), `PRIO_EXPIRY = 2`, `PRIO_TIMER = 5` (default for `out.timer`).
- **D11** Provisional handle = bit 62 | ns(6 bits) << 56 | global slot(32 bits) << 24 | per-step ordinal(24 bits). At seal, handles are remapped to dense values in records, created rows, state and local `ref` fields of touched partitions, and the tag/payload of every command queued this step; a slot retired in a step is reused only after that step seals.
- **D12** `partition_id = ptype_code << 56 | serial`: population owners use their population ordinal, shards their shard index, created owners the dense index of their row (assigned at seal); `ptype_code` ∈ 1..31 in plan order. Tie order involving created owners across step lengths is S2's concern (S1's slice creates no owners).
- **D13** Invariance across different step lengths compares records after renaming each ID namespace by first appearance in canonical order (dense indices legitimately depend on step boundaries); same-step-length comparisons are exact.
- **D14** `cause_id` is written as null in S1 (request/response pairing checks arrive in S2).
- **D15** `out.new_id(ns)` consumes one `creates[ns]` reservation; `p.ids(...)` namespaces have no entity table.
- **D16** Created child rows (`child_of`) are write-only in S1: exported to `entities/<table>`, never read back by kernels (instance kernels are M3).
- **D17** Request, response and message payload fields are int64 (refs, amounts, ints; cats as codes). Every request carries a `tag` that its response echoes.
- **D18** Events emitted by kernels may contain `text` only as `opt(text)`, always written null.
- **D19** A change group is `p.change_group(name, table=, cols=)`; kernels call `out.change_<group>(t, **cols)`, which writes the state columns and one history row; reserved under `records={"<group>": n}`; written to `history/<group>/date=…/step-NNNNNN.parquet` with the common ordering columns `entity_id, valid_from, lamport, partition_id, seq` first.
- **D20** Time mode simulates `[start − warmup, start + span)`; a step boundary is forced at `start`; only rows with `event_time ≥ start` are exported; warm-up-created rows still appear in `entities/`.
- **D21** Run name `<profile>-s<seed>`; `--set` overrides are recorded in the manifest, not the name; `--out DIR` overrides the run folder. Overrides prefixed `engine.`, `budget.`, `writer.` route to those tables, `run.` to the `[defaults]` run keys (`start`, `span`, `warmup`, `seed`), the rest to the pack `Config`.
- **D22** Pack revision = first 7 hex digits of sha256 over `specs/**/*.py` and `specs/expectations.yaml` (sorted paths, bytes); engine revision = `neorisk-simkit` version + `@` + first 7 hex of sha256 over `neorisk_simkit/{spec,engine,std,io}/**/*.py`.
- **D23** Replay batches use a unified Arrow schema (common columns + union of the selected types' columns, nullable); encoders drop other types' columns per row.
- **D24** `i16` maps to `SMALLINT` in both dialects; DuckDB categories use an inline `ENUM(...)`; event columns of kind `text` map to `TEXT`/`VARCHAR`.
- **D25** Shard state fields typed `"T[<table>]"` are per-item arrays; items are the rows of `<table>` grouped by the column named by the shard's `key`; `ctx.reads.<table>.local_index[row]` gives the item's index inside its shard.
- **D26** Periodic shard processes (`every=`, `jitter=`) are scheduled by the runtime: occurrence 0 at `t_first = sim_start + u·every` (`u` a keyed uniform per shard, so groups are phase-spread), and when occurrence `j`'s first sub-step (cursor 0) pops, occurrence `j+1` is queued at `t_first + (j+1)·every + jitter_{j+1}` (keyed draw, clamped to ≥ the current time). Start and periodic commands use the reserved command kind `START = 0`.
- **D27** Single-SKU checkout: a cart holds one line in S1 (adding a product replaces it).
- **D28** KYC starts with probability `kyc_start_p` on a desktop session of a user with `kyc_level == 0` who owns both a desktop and a phone; the handoff token expires 300 s after issue.
- **D29** Bench allowlist: `meta.json["feature_allowlist"]` is an upper bound on raw model inputs; engine columns (`lamport, partition_id, seq, cause_id, action_id`) are never features (a string `event_type` is non-numeric and never a feature anyway); legacy `datagen generate` writes the allowlist so bench outputs are unchanged.
- **D30** The gate is measured on the available machine with `threads = min(16, os.cpu_count())`; the report records the machine and flags non-reference hardware.
- **D31** Engine knobs live in a new `[engine]` table of `datagen.toml` (step, step_min, step_max, adapt, slab_bytes, timer_nodes, payload_slots, max_messages_per_step, parallel_min_partitions); `[budget]` keeps machine limits.
- **D32** The §07 trace fixture uses constant 300 ms latencies (δ = 300 ms ⇒ `H` = 10:00:00.3, consistent with "H ≥ 10:00:00.2"); payment P is admitted and runs in round 4, after U's three rounds.
- **D33** Parallelism is a `ThreadPoolExecutor` of `threads` workers over `@njit(nogil=True)` functions; `NUMBA_NUM_THREADS=1`; `POLARS_MAX_THREADS` and `pyarrow.set_cpu_count` = `threads`.
- **D34** JIT cache: generated modules are written to `$NEORISK_JIT_CACHE` (default `~/.cache/neorisk-simkit/jit/`) as `gen_<sha256[:16]>.py` and imported from there; every `@njit` uses `cache=True`.
- **D35** `datagen` exit codes: 0 ok, 1 gate failed or internal error, 2 usage/validation error, 3 `CapExceeded`.

## Review Focus

Inputs the spec implies but no exit test names; each line has a pinning test in the owning task.
1. **Events exactly on boundaries**: `t == step end` belongs to the next step, `t == start` is exported, `t == start − 1µs` is warm-up only; a step that crosses midnight writes the same `step-NNNNNN.parquet` name under two `date=` dirs (Tasks 11, 12).
2. **Owners with nothing to do**: a user with no devices of a kind, a cart that is empty at checkout, a user whose queue empties (retires) and later gets a late response — no crash, counted as `late_messages` (Tasks 9, 14, 15).
3. **Kernel addressing bugs**: a request to a shard index ≥ n, or a timer scheduled before `ctx.t`, fails the run with `EngineError` naming the process and command (Task 10, Task 9).
4. **Empty selections and empty runs**: replay with `--types` matching nothing, `--from` after the last event, or a run whose export window holds zero events — exit 0, zero rows, `json-array` writes `[]`, manifest still written (Tasks 12, 21, 22).
5. **Re-running into an existing folder / interrupted sink**: `datagen run` without `--force` refuses; a file sink that fails mid-way leaves no final file and no stale `.tmp` (Tasks 19, 22).

## Engine reference (shared by Tasks 5–18)

Implementers of engine tasks read this section; names here are the contract.

**Global partition slots.** Owners of every type and shards share one slot space `g ∈ [0, G)`, `G = Σ owners max_live + Σ shards n`. Hidden arrays in `engine/world.py`, length `G`:
`pid int64, ptype int16, lslot int32` (row in the type's state arrays), `gen uint32, alive uint8, clock int64` (Lamport), `rseq int32` (next record seq), `cseq int64` (next command seq), `pending int32` (outstanding responses), `qhead int32` (−1 = empty), `inst int64` (RNG instance key), `self_id int64` (own row id: dense, or provisional handle in its creation step; shard index for shards), `occ uint32[G, A]` (A = max processes per partition type), `ordn int32[G, N_NS]` (per-step create ordinal per namespace), `retire_at int64` (I64_MAX unless retiring), `susp_t int64` (time of the suspending request, I64_MAX when not suspended; Task 9), `susp_delta int64` (δ of the suspending request's boundary; Task 10). All hidden arrays and their dtypes are declared once in `engine/world.py` as `HIDDEN_DTYPES: tuple[tuple[str, np.dtype, int], ...]` (`(name, dtype, per-slot multiplicity)`, where multiplicity `"A"`/`"N_NS"` is resolved per plan); `spec.caps` derives `HIDDEN_BYTES` from it (Task 4 creates the table with every array above, Task 8 allocates them all from it, and Tasks 9 and 10 only use `susp_t`/`susp_delta`).

**Command node pool** (`engine/cmdq.py`, capacity `engine.timer_nodes`): `n_time int64, n_key int64, n_seq int64, n_tag int64, n_next int32, n_kind int16, n_proc int16, n_pay int32` (payload row or −1). Per-partition singly linked list sorted by `(time, key, seq)`; free lists per worker (`free_head int32[W]`, `free_n int64[W]`) plus a global reserve list. **Payload arena**: `pay int64[payload_slots, PAYLOAD_W]` (`PAYLOAD_W = 12`: columns 0..6 user payload, 7 `src_g`, 8 `src_gen`, 9 `src_self_id`, 10 `src_action`, 11 reserved) with its own free lists.

**Tuples passed to lowered kernels** (Task 6 lowers attribute access to these indices; Tasks 8–9 build them):
- `ctx = (t, self_id, pid, g, inst, action, occ, kc, seed, cfg, reads, refs, lamport, flags)` → indices `CTX_T=0 … CTX_FLAGS=13`. `kc` is the worker's int64[33] site counter (`kc[0]` = pairs used, then `(site, k)` pairs), reset per invocation.
- Owner `s = (lslot, col_0, col_1, …)` in table column order; `s.x` → `s[1+i][s[0]]`.
- Shard `s = (index, off, n, items, field_0, …)`; `s.n_<items>` → `s[2]`, `s.<items>[i]` → `s[3][s[1]+i]`, `s.f[i]` → `s[4+j][s[1]+i]`.
- `loc = (lslot, f_0, …)`; scalar fields are 1-D arrays, `"T[n]"` fields are 2-D `[max_live, n]` arrays.
- `cmd = (kind, tag, time, cursor, sender, pay, pay_row)`; `cmd.<payload name>` → `cmd[5][cmd[6], j]` with `j` fixed per name by the plan (D17).
- `cfg` = the process config dataclass flattened to a tuple in field order (nested dataclasses as nested tuples, `Dist` as `(code, p1, p2, p3)`); `reads` = flat tuple of read arrays; `refs` = flat tuple of `(offs, idx)` CSR pairs.
- `out` = the worker's `SlabSet.as_tuple(...)` (Task 8 defines the order).

**Return codes.** `COMMIT = 0`, `RETRY = -1`, `reject(c) = 1 + c`. Reserved command kind `START = 0` (D26).

**Statuses returned by compiled runners** (Task 9): `DONE = 0`, `NEED_SWAP = 1` (a slab buffer is full: flush and re-invoke), `NEED_NODES = 2` (worker node/payload free list empty: refill from the reserve), `SUSPENDED` is per-partition state, not a status.

## File structure

```
pyproject.toml                                   # dev: duckdb; ruff per-file ignores for examples/**
.gitignore                                       # benchmarks/results/
benchmarks/s1.toml  benchmarks/README.md
examples/ecommerce_s1/                           # D1: the S1 slice project
  README.md  datagen.toml  specs/{brief.md,pack.py,kernels.py}  out/ reports/ logs/ (.gitkeep)
libs/simkit/pyproject.toml                       # numba, pyarrow
libs/simkit/src/neorisk_simkit/
  spec/{__init__,types,dist,pack,plan,project,sources,law,validate,caps}.py
  engine/{__init__,abi,rng,identity,lower,layout,codegen,build,slabs,cmdq,calendar,
          world,route,rounds,run,errors}.py
  std/{__init__,checked,sources,handoff}.py
  checks/{__init__,structural}.py
  io/{__init__,seal,writer,manifest,step_index,entities,dataset,read,stats}.py
  io/schema/{__init__,schema_json,sql}.py
  io/replay/{__init__,planner,reader,encode}.py
  io/sinks/{__init__,base,stdout,file}.py
libs/simkit/tests/
  conftest.py
  fixtures/{mini,bad_abi,ordering,abi_proof,trace_shopper,schema_demo}/
  test_spec_types.py test_engine_abi.py test_spec_pack.py test_spec_validate.py
  test_engine_rng_identity.py test_engine_lower.py test_engine_codegen.py
  test_engine_cmdq_calendar.py test_engine_execute.py test_engine_rounds.py
  test_engine_seal.py test_io_writer.py test_exit_abi_proof.py test_std_handoff.py
  test_exit_trace_shopper.py test_exit_invariance.py test_exit_memory_caps.py
  test_schema_sql.py test_replay_core.py test_replay_sinks.py
apps/datagen/src/datagen/{cli,run_cmds,schema_cmd,replay_cmd,benchmark}.py
apps/datagen/tests/{test_example_ecom_s1.py,test_example_ecom_s1_kyc.py,
                    test_datagen_run_cli.py,test_datagen_schema_cli.py,
                    test_datagen_replay_cli.py,test_benchmark_s1.py}
apps/bench/src/bench/allowlist.py  apps/bench/tests/test_bench_allowlist.py
```

Task dependency order: execute in numeric order. Hard dependencies: 1 → 2 → … → 12 are linear; 13, 14, 16, 19, 20, 21 need 12; 15 needs 14; 17 needs 15; 18 needs 16; 22 needs 15, 19 and 21; 23 needs nothing new (it can run any time); 24 needs 15 and 19.

---
### Task 1: Dependencies, logical types and distributions

**Files:**
- Modify: `libs/simkit/pyproject.toml` (add `"numba>=0.60"`, `"pyarrow>=17"`), root `pyproject.toml` (dev group: `"duckdb>=1.1"`; add `[tool.ruff.lint.per-file-ignores] "examples/**" = ["B008", "RUF009"]`), `uv.lock`
- Create: `libs/simkit/src/neorisk_simkit/spec/__init__.py`, `spec/types.py`, `spec/dist.py`
- Test: `libs/simkit/tests/test_spec_types.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `LType` frozen dataclass: `kind: str` (one of `i16 i32 i64 f64 bool text cat ref amount ts`), `nullable: bool = False`, `values: tuple[str, ...] = ()`, `target: str | None = None`, `asset: str | None = None`, `quantum: int = 1`, `minimum: int | None = None`.
  - Constructors `i16(min=None)`, `i32(min=None)`, `i64(min=None)`, `f64()`, `boolean()`, `text()`, `cat(*values)`, `ref(target)`, `amount(asset, quantum=1)`, `ts()`, `opt(t) -> LType` (same type, `nullable=True`).
  - `storage_dtype(t: LType) -> np.dtype` (cat→int16, ref/amount/ts→int64, bool→uint8, text→object); `arrow_type(t: LType) -> pa.DataType` (cat→`pa.dictionary(pa.int16(), pa.string())`, ts→`pa.timestamp("us", tz="UTC")`, amount→`pa.int64()`, bool→`pa.bool_()`).
  - `cat_code(t: LType, value: str) -> int`.
  - `COMMON_COLUMNS: tuple[tuple[str, LType], ...]` = event_id `i64`, event_type `text`, event_time `ts`, lamport `i64`, partition_id `i64`, seq `i32`, cause_id `opt(i64)`, action_id `i16`.
  - `spec.dist`: `Dist(kind: int, params: tuple[float, float, float])`, kind constants `CONST, EXP, LOGNORMAL, SHIFTED_LOGNORMAL, GAMMA, NORMAL, PARETO, GEOMETRIC, NEGBINOM, UNIFORM_INT, CATEGORICAL, ZIPF, POISSON_DAILY, LOGNORMAL_MINOR` (ints 0..13); constructors `constant(ms=None, s=None)`, `exp(mean_s=None, mean_days=None)`, `lognormal(median_s=None, median_ms=None, sigma=0.6)`, `shifted_lognormal(min_ms, median_ms, sigma=0.5)`, `gamma(mean_days=None, mean_s=None, shape=2.0, max_days=None)`, `normal(mean_h=0.0, sd_h=1.0)`, `pareto(alpha, min_h)`, `geometric(mean, max=None)`, `negbinom(mean, disp)`, `uniform_int(lo, hi)`, `categorical(probs: dict)`, `zipf(s)`, `poisson_daily(weekly=(1,)*7, trend=0.0)`, `lognormal_minor(median, sigma, min=None, max=None)`; `encode(d) -> tuple[int, float, float, float]`; `min_us(d) -> int` (lower bound of a duration dist in µs; 0 when unbounded below). `categorical` keeps its labels in `Dist.labels: tuple` and probabilities in `Dist.weights: tuple[float, ...]`.

- [ ] **Step 1: Add dependencies and sync**

Edit the two `pyproject.toml` files as listed, then:

Run: `uv lock && uv sync --all-packages && uv run --all-packages python -c "import numba, pyarrow, duckdb; print(numba.__version__, pyarrow.__version__)"`
Expected: two version strings. If the resolver must move numpy below the locked 2.5.4 to satisfy numba, accept it and continue; Step 6 proves the existing suite still passes.

- [ ] **Step 2: Write the failing tests**

`libs/simkit/tests/test_spec_types.py`:
```python
import numpy as np
import pyarrow as pa
import pytest

from neorisk_simkit.spec import dist
from neorisk_simkit.spec.types import (
    COMMON_COLUMNS, amount, arrow_type, boolean, cat, cat_code, f64, i16, i32, i64, opt, ref,
    storage_dtype, text, ts,
)


def test_storage_dtypes():
    assert storage_dtype(i16()) == np.int16
    assert storage_dtype(i32()) == np.int32
    assert storage_dtype(i64()) == np.int64
    assert storage_dtype(f64()) == np.float64
    assert storage_dtype(cat("a", "b")) == np.int16
    assert storage_dtype(ref("user")) == np.int64
    assert storage_dtype(amount(asset="USD")) == np.int64
    assert storage_dtype(ts()) == np.int64
    assert storage_dtype(boolean()) == np.uint8


def test_arrow_types():
    assert arrow_type(ts()) == pa.timestamp("us", tz="UTC")
    assert arrow_type(cat("web", "app")) == pa.dictionary(pa.int16(), pa.string())
    assert arrow_type(amount(asset="USD")) == pa.int64()
    assert arrow_type(opt(text())) == pa.string()
    assert arrow_type(boolean()) == pa.bool_()
    assert arrow_type(i16()) == pa.int16()


def test_opt_marks_nullable_and_keeps_kind():
    t = opt(ref("sku"))
    assert t.nullable and t.kind == "ref" and t.target == "sku"
    assert not ref("sku").nullable
    with pytest.raises(ValueError, match="already optional"):
        opt(t)


def test_cat_codes_and_errors():
    c = cat("web", "app", "api")
    assert cat_code(c, "web") == 0 and cat_code(c, "app") == 1
    with pytest.raises(ValueError, match="not a category"):
        cat_code(c, "tv")
    with pytest.raises(ValueError, match="duplicate"):
        cat("a", "a")
    with pytest.raises(ValueError, match="at least one"):
        cat()


def test_constraints_recorded():
    assert i32(min=1).minimum == 1
    a = amount(asset="USD")
    assert a.asset == "USD" and a.quantum == 1


def test_common_columns_order_and_types():
    names = [n for n, _ in COMMON_COLUMNS]
    assert names == ["event_id", "event_type", "event_time", "lamport", "partition_id", "seq",
                     "cause_id", "action_id"]
    d = dict(COMMON_COLUMNS)
    assert d["cause_id"].nullable and not d["event_id"].nullable
    assert d["seq"].kind == "i32" and d["action_id"].kind == "i16"
    assert d["event_time"].kind == "ts"


def test_dist_encode_and_min_latency():
    d = dist.shifted_lognormal(min_ms=150, median_ms=240)
    code, _, _, _ = dist.encode(d)
    assert code == dist.SHIFTED_LOGNORMAL
    assert dist.min_us(d) == 150_000
    assert dist.min_us(dist.constant(ms=300)) == 300_000
    assert dist.min_us(dist.exp(mean_s=5)) == 0
    assert dist.encode(dist.constant(s=2)) == (dist.CONST, 2_000_000.0, 0.0, 0.0)


def test_dist_validation():
    with pytest.raises(ValueError):
        dist.lognormal(median_s=-1)
    with pytest.raises(ValueError, match="sum to 1"):
        dist.categorical({"a": 0.5, "b": 0.6})
    with pytest.raises(ValueError):
        dist.shifted_lognormal(min_ms=300, median_ms=200)
    c = dist.categorical({"x": 0.25, "y": 0.75})
    assert c.labels == ("x", "y") and c.weights == (0.25, 0.75)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run --all-packages pytest libs/simkit/tests/test_spec_types.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'neorisk_simkit.spec'`.

- [ ] **Step 4: Implement**

`spec/types.py` notes:
- `cat(*values)` raises `ValueError("cat needs at least one value")`, `ValueError("duplicate category 'a'")`; stores `values`.
- `opt(t)` raises `ValueError("type is already optional")` if `t.nullable`.
- `cat_code` raises `ValueError(f"{value!r} is not a category of {t.values}")`.
- `arrow_type` for `text` → `pa.string()`, `f64` → `pa.float64()`, `ref`/`i64` → `pa.int64()`.

`spec/dist.py` notes:
- Durations are encoded in µs: `constant(ms=300)` → params `(300_000.0, 0, 0)`; `exp(mean_s)` → `(mean_us, 0, 0)`; `lognormal(median_s|median_ms, sigma)` → `(median_us, sigma, 0)`; `shifted_lognormal(min_ms, median_ms, sigma)` → `(min_us, median_us - min_us, sigma)` (requires `median_ms > min_ms`); `gamma(mean_days|mean_s, shape, max_days)` → `(mean_us, shape, max_us or 0)`; `normal(mean_h, sd_h)` → `(mean_us, sd_us, 0)`; `pareto(alpha, min_h)` → `(alpha, min_us, 0)`.
- Count/value dists keep natural units: `geometric(mean, max)` → `(mean, max or 0, 0)`; `negbinom(mean, disp)`; `uniform_int(lo, hi)` (inclusive); `zipf(s)`; `lognormal_minor(median, sigma, min, max)`.
- `categorical(probs)`: probabilities must be ≥ 0 and sum to 1 within 1e-9 (`ValueError("categorical probabilities must sum to 1")`); `kind=CATEGORICAL`, `params=(len, 0, 0)`, `labels`, `weights`. `poisson_daily(weekly, trend)` keeps `weekly` (7 floats) in `weights` and `trend` in params.
- `min_us`: CONST → p1; SHIFTED_LOGNORMAL → p1; everything else → 0.
- `Dist` is frozen and hashable (`labels`/`weights` are tuples with `default=()`).

`spec/__init__.py`: `from neorisk_simkit.spec import dist, types` (Task 3 adds `Pack`, `std`, `law`).

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run --all-packages pytest libs/simkit/tests/test_spec_types.py -v`
Expected: PASS (8 tests).

- [ ] **Step 6: Full suite and lint**

Run: `uv run --all-packages pytest -q && uv run ruff check $(ls -d libs apps examples/ecommerce_s1 benchmarks 2>/dev/null)`
Expected: all existing tests pass; `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock libs/simkit/pyproject.toml libs/simkit/src/neorisk_simkit/spec libs/simkit/tests/test_spec_types.py
git commit -m "simkit: add numba/pyarrow, logical types and distributions

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 2: Kernel ABI surface and checked arithmetic

**Files:**
- Create: `libs/simkit/src/neorisk_simkit/engine/__init__.py`, `engine/abi.py`, `engine/errors.py`, `libs/simkit/src/neorisk_simkit/std/__init__.py`, `std/checked.py`
- Test: `libs/simkit/tests/test_engine_abi.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `engine.abi`: `COMMIT = 0`, `RETRY = -1`, `START = 0`, `PRIO_CONTINUE = 0`, `PRIO_MESSAGE = 1`, `PRIO_EXPIRY = 2`, `PRIO_TIMER = 5`; `reject(code: int) -> int` (`@njit(cache=True)`; returns `1 + code`; `code` must be ≥ 0); `Res(records: dict[str,int] | None = None, creates: dict[str,int] | None = None, timers: int = 0, requests: int = 0)` frozen dataclass (dicts stored as `MappingProxyType`); `Local(**fields: str)` with `.fields: dict[str, tuple[str, int]]` (type in `i8 i16 i32 i64 u8 u32 f64 ref`, optional `[n]` suffix → length n, else 1); `KernelSpec(name, func, module_file, state, local, commands, max, substep, params)` — a `@dataclass(frozen=True)` (Task 4's tests call `dataclasses.replace(p.kernel, state=…, max=…, commands=…)`); `kernel(state, local=None, commands=(), max=Res(), substep=None) -> Callable` (returns the function unchanged with `fn.__kernel__ = KernelSpec(...)`); `is_kernel(fn) -> bool`.
  - `engine.errors`: `AbiViolation(Exception)`, `EngineError(Exception)`, `CapExceeded(Exception)` with constructor `CapExceeded(item, limit, attempted, process=None)`, attributes `item: str, limit: int, attempted: int, process: str | None` and message `f"memory cap exceeded: {item} (limit {limit}, attempted {attempted})"` followed by `f" in process {process}"` when `process` is given (spec §06: exceeding `max_admissions` fails the run naming the process; Task 10 passes the creating process).
  - `engine/__init__.py` re-exports `COMMIT, RETRY, START, PRIO_*, Local, Res, kernel, reject, KernelSpec, AbiViolation, EngineError, CapExceeded`.
  - `std.checked`: `I64_MAX`, `I64_MIN`, `NULL = I64_MIN`; `checked_add(a, b)`, `checked_sub(a, b)`, `checked_mul(a, b)`, `checked_min(a, b)`, `checked_max(a, b)` — all `@njit(cache=True)`, raise `OverflowError("int64 overflow")`. `std/__init__.py` re-exports them and `NULL`. `neorisk_simkit.std` is the one and only `std` package: Task 3 adds `generated` and `law` to it, Task 14 `catalog`/`devices`/`stock`, Task 15 `handoff`, Task 16 `rows`; `neorisk_simkit.spec` re-exports this same package as `spec.std` (Task 3).

- [ ] **Step 1: Write the failing tests**

`libs/simkit/tests/test_engine_abi.py`:
```python
import numba
import pytest

from neorisk_simkit import std
from neorisk_simkit.engine import (
    COMMIT, PRIO_CONTINUE, PRIO_EXPIRY, PRIO_MESSAGE, PRIO_TIMER, RETRY, START, CapExceeded,
    KernelSpec, Local, Res, kernel, reject,
)


def test_codes_and_priorities():
    assert COMMIT == 0 and RETRY == -1 and START == 0
    assert reject(0) == 1 and reject(7) == 8
    assert PRIO_CONTINUE < PRIO_MESSAGE < PRIO_EXPIRY < PRIO_TIMER


def test_kernel_decorator_records_spec():
    @kernel(state="user", local=Local(n="i16", cart="i32[5]", h="ref"), commands=(1, 2),
            max=Res(records={"a": 1}, creates={"order": 1}, timers=2, requests=3))
    def k(ctx, s, loc, cmd, out):
        return COMMIT

    spec = k.__kernel__
    assert isinstance(spec, KernelSpec)
    assert spec.name == "k" and spec.state == "user" and spec.commands == (1, 2)
    assert dict(spec.max.records) == {"a": 1} and dict(spec.max.creates) == {"order": 1}
    assert spec.max.timers == 2 and spec.max.requests == 3
    assert spec.local.fields == {"n": ("i16", 1), "cart": ("i32", 5), "h": ("ref", 1)}
    assert spec.params == ("ctx", "s", "loc", "cmd", "out")
    assert spec.module_file.endswith("test_engine_abi.py")
    assert k(None, None, None, None, None) == COMMIT


def test_kernel_signature_is_checked():
    with pytest.raises(TypeError, match="ctx, s, loc, cmd, out"):
        @kernel(state="user", local=Local(n="i16"))
        def bad(ctx, s, cmd, out):
            return COMMIT
    with pytest.raises(TypeError, match="ctx, s, cmd, out"):
        @kernel(state="user")
        def bad2(ctx, s, loc, cmd, out):
            return COMMIT


def test_local_and_res_validation():
    with pytest.raises(ValueError, match="unknown local type"):
        Local(x="str")
    with pytest.raises(ValueError, match="must be >= 0"):
        Res(timers=-1)
    with pytest.raises(ValueError, match="must be >= 0"):
        Res(records={"a": -2})
    with pytest.raises(ValueError, match="substep"):
        kernel(state="bin", substep=0)


def test_command_ids_must_not_use_start_twice():
    with pytest.raises(ValueError, match="duplicate command"):
        kernel(state="user", commands=(START, 1, 1))


def test_checked_arithmetic_python():
    assert std.checked_add(2, 3) == 5
    assert std.checked_sub(2, 3) == -1
    assert std.checked_min(3, 2) == 2 and std.checked_max(3, 2) == 3
    assert std.checked_mul(-4, 5) == -20
    with pytest.raises(OverflowError):
        std.checked_add(2**63 - 1, 1)
    with pytest.raises(OverflowError):
        std.checked_sub(-(2**63), 1)
    with pytest.raises(OverflowError):
        std.checked_mul(2**62, 2)


def test_checked_arithmetic_compiled_matches():
    add = numba.njit(lambda a, b: std.checked_add(a, b))
    mul = numba.njit(lambda a, b: std.checked_mul(a, b))
    assert add(2, 3) == 5 and mul(6, 7) == 42
    with pytest.raises(OverflowError):
        add(2**63 - 1, 1)
    with pytest.raises(OverflowError):
        mul(2**62, 2)
    assert std.NULL == -(2**63)


def test_cap_exceeded_message():
    e = CapExceeded("timer_heaps", 10, 11)
    assert e.item == "timer_heaps" and "timer_heaps" in str(e) and "limit 10" in str(e)
    a = CapExceeded("max_admissions_per_step", 0, 1, process="journey")
    assert a.item == "max_admissions_per_step" and a.process == "journey"
    assert str(a).endswith("in process journey") and e.process is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --all-packages pytest libs/simkit/tests/test_engine_abi.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'neorisk_simkit.engine'`.

- [ ] **Step 3: Implement**

`std/checked.py` (works identically in Python and compiled code because it never relies on wrap-around):
```python
from numba import njit

I64_MAX = 9_223_372_036_854_775_807
I64_MIN = -9_223_372_036_854_775_808
NULL = I64_MIN


@njit(cache=True)
def checked_add(a, b):
    if b > 0 and a > I64_MAX - b:
        raise OverflowError("int64 overflow")
    if b < 0 and a < I64_MIN - b:
        raise OverflowError("int64 overflow")
    return a + b


@njit(cache=True)
def checked_sub(a, b):
    if b < 0 and a > I64_MAX + b:
        raise OverflowError("int64 overflow")
    if b > 0 and a < I64_MIN + b:
        raise OverflowError("int64 overflow")
    return a - b
```
`checked_mul`: if either is 0 return 0; check `abs` bounds via division (`a > I64_MAX // b` cases by sign) before multiplying; `checked_min`/`checked_max` are plain comparisons (kept for the ABI vocabulary).

`engine/abi.py`:
- `kernel(...)` validates: `substep is None or substep >= 1` (`ValueError("substep must be >= 1")`); command ids unique (`ValueError("duplicate command id 1")`); the decorated function's parameter names must equal `("ctx", "s", "loc", "cmd", "out")` when `local` is given, else `("ctx", "s", "cmd", "out")` — raise `TypeError(f"kernel {name} must take (ctx, s, loc, cmd, out)")` / `(ctx, s, cmd, out)`. `module_file = inspect.getsourcefile(fn)`.
- `Local` parses `"i32[5]"` with a regex `^(i8|i16|i32|i64|u8|u32|f64|ref)(?:\[(\d+)\])?$`.
- `KernelSpec` and `Res` are `@dataclass(frozen=True)`; `Local` is a frozen dataclass holding `fields`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --all-packages pytest libs/simkit/tests/test_engine_abi.py -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Lint and commit**

Run: `uv run ruff check $(ls -d libs apps examples/ecommerce_s1 benchmarks 2>/dev/null)`
```bash
git add libs/simkit/src/neorisk_simkit/engine libs/simkit/src/neorisk_simkit/std libs/simkit/tests/test_engine_abi.py
git commit -m "simkit: kernel ABI surface and checked arithmetic

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 3: Pack API, normalized plan, project loader and the `mini` fixture

**Files:**
- Create: `libs/simkit/src/neorisk_simkit/spec/pack.py`, `spec/plan.py`, `spec/project.py`, `spec/sources.py`, `spec/law.py`
- Modify: `spec/__init__.py` (export `Pack`, `PackError`, `dist`, `law`, and `std` = the Task 2 package `neorisk_simkit.std`); `libs/simkit/src/neorisk_simkit/std/__init__.py` (add `generated` and `law`)
- Create fixture: `libs/simkit/tests/fixtures/mini/datagen.toml`, `fixtures/mini/specs/pack.py`, `fixtures/mini/specs/kernels.py`
- Create: `libs/simkit/tests/conftest.py`
- Test: `libs/simkit/tests/test_spec_pack.py`

**Interfaces:**
- Consumes: Task 1 types/dist; Task 2 `kernel`, `KernelSpec`, `START`.
- Produces:
  - `Pack(name: str, schema_version: int)` with methods (all keyword-only after the name):
    `table(name, *, key, cols, mutable=False, doc="", child_of=None, source=None) -> str`;
    `event(name, *, cols, owner=None, shard=None, doc="") -> str`;
    `ids(*names) -> None`;
    `owner(name, *, table, max_live, children=(), retire_when_idle=True, execution_owner=None) -> str`;
    `shard(name, *, key, n, items: str | None, state: dict[str, str], init=None, doc="") -> str` (`items=None` with `state={}` declares a shard with no per-item arrays; a `"T[<table>]"` state field then raises `PackError("shard <name>: per-item state needs items=")`);
    `request(name, *, frm, to, payload, responses, latency, response_payload=None) -> str`;
    `message(name, *, frm, to, payload, latency) -> str`;
    `population(table, *, n, initial, arrivals=None, attrs=None, refs=None) -> None`;
    `process(name, *, kernel, owner=None, shard=None, config=None, start=None, requests=None, messages=None, on_request=None, on_response=None, on_message=None, reads=None, refs=None, commands=(), every=None, jitter=None) -> None`;
    `change_group(name, *, table, cols) -> None`; `check(id, law, required=False) -> None` (stored, not evaluated in S1); `on_created(table) -> Trigger`.
    `machine`, `expose`, `expose_param`, `feature`, `accumulator` raise `PackError("<method> arrives in M3")` (or `"S2"` for `accumulator`).
  - `spec.plan`: frozen dataclasses `Column(name, ltype)`, `TableDef(name, code, key, cols, mutable, doc, child_of, source, creatable)`, `EventDef(name, code, partition, kind, doc, cols)` (cols include the 8 common columns first), `PartitionDef(name, kind, ptype_code, table, n, max_live, items, key, state, init, retire_when_idle)`, `BoundaryDef(name, code, kind ("request"|"message"), frm, to, payload, response_payload, responses, latency, min_latency_us)`, `ProcessDef(name, partition, action_id, kernel: KernelSpec, config, start, requests, messages, on_request, on_response, on_message, reads, refs, commands, every_us, jitter)`, `PopulationDef(table, n, initial, arrivals, attrs, refs)`, `ChangeGroupDef(name, code, table, cols)`, `Plan(pack, schema_version, revision, tables, events, namespaces, partitions, boundaries, processes, populations, change_groups, checks, cfg)` with lookups `plan.table(n)`, `plan.event(n)`, `plan.partition(n)`, `plan.boundary(n)`, `plan.process(n)`, `plan.change_group(n)`, and `plan.ns_code(name) -> int`.
    `build_plan(pack_module, cfg, specs_dir: Path) -> Plan`.
    `action_id` = index of the process in declaration order (0-based, global); `ptype_code` = 1 + index of the partition in declaration order; event/table/boundary/change-group codes are 0-based in declaration order; `namespaces` = creatable tables (`child_of` set, or owner tables without a population) in declaration order, then `p.ids` names.
  - `spec.project` (every class below is a `@dataclass(frozen=True)`; Tasks 4, 8–13 and 17 call `dataclasses.replace` on `RunSpec`, `Budget`, `EngineSettings` and `WriterSettings`): `Budget(threads, memory_bytes, max_step_rows, max_step_bytes, max_spawn_depth, max_admissions_per_step)`, `WriterSettings(compression, compression_level, row_group_rows)`, `EngineSettings(step_us, step_min_us, step_max_us, adapt, slab_bytes, timer_nodes, payload_slots, max_messages_per_step, parallel_min_partitions, force_capacity: Mapping[str,int])`, `Project(dir, name, pack_path, toml)`, `RunSpec(name, profile, seed, start_us, span_us, warmup_us, mode, budget, writer, engine, cfg, plan, overrides)`; `load_project(dir) -> Project`; `resolve_run(project, profile, overrides=(), seed=None) -> RunSpec`; `parse_duration(s) -> int` (µs; units `us ms s m h d`); `parse_size(s) -> int` (bytes; `KB MB GB`, powers of 1024); `ProjectError(Exception)`.
  - `spec.sources`: `generated(n, cols: dict[str, Dist]) -> Source` (exported as `std.generated` by `std/__init__.py`), base class `Source` with `generate(n_rows, table: TableDef, seed: int, stream: int) -> dict[str, np.ndarray]` (Task 5 fills in the keyed sampling; this task stores the object only).
  - `spec.law`: inert builders `never_negative(path)`, `resolved(...)`, `sum_le(...)`, `at_most_once(...)` returning `LawSpec(kind, args)` (exported as `std.law`, so packs write `std.law.never_negative(...)`).
  - `std/__init__.py` gains `from neorisk_simkit.spec import law` and `from neorisk_simkit.spec.sources import generated`. `spec/__init__.py` imports `std` last (`from neorisk_simkit import std`), after `dist`, `types`, `law`, `sources`, `pack`, so the `spec` ↔ `std` cycle resolves (`std` only imports spec submodules).
  - `conftest.py`: `FIXTURES: Path`; fixture `fixture_project(name) -> Path`; plain helpers (imported by tests as `from conftest import …`) `make_run(name, overrides=(), **engine) -> RunSpec` (`resolve_run(load_project(FIXTURES / name), "sample", list(overrides))`, then `dataclasses.replace(run, engine=dataclasses.replace(run.engine, **engine))` when `engine` is non-empty) and `dataset_tree(d: Path) -> dict[str, bytes]` (POSIX relative path → file bytes for every file under `d` except `run_stats.json`, which is not part of replay identity; used by Tasks 12 and 17). Task 9 appends `records_of`; Task 12 appends `event_dicts`.

- [ ] **Step 1: Create the `mini` fixture project**

`libs/simkit/tests/fixtures/mini/datagen.toml`:
```toml
[project]
name = "mini"
pack = "specs/pack.py"

[paths]
out = "out"

[defaults]
seed = 7
start = "2026-03-01T00:00:00Z"
mode = "time"
span = "2d"
warmup = "6h"

[budget]
threads = 2
memory = "2GB"
max_step_rows = 200_000
max_step_bytes = "64MB"
max_spawn_depth = 3
max_admissions_per_step = 10_000

[writer]
compression = "zstd"
compression_level = 3
row_group_rows = 131_072

[engine]
step = "6h"
step_min = "15m"
step_max = "1d"
adapt = false
slab_bytes = "256KB"
timer_nodes = 100_000
payload_slots = 10_000
max_messages_per_step = 100_000
parallel_min_partitions = 64

[profiles.sample]
set = { users = 200 }
```

`fixtures/mini/specs/pack.py`:
```python
"""Mini pack: a test fixture that touches every S1 engine path at tiny scale."""

from dataclasses import dataclass, field

from neorisk_simkit.spec import Pack, dist, std
from neorisk_simkit.spec.types import amount, cat, i32, opt, ref

from . import kernels as k

PACK = "mini"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Behavior:
    ping_gap: dist.Dist = dist.exp(mean_s=3600)
    take_p: float = 0.3
    note_p: float = 0.2
    max_pings: int = 50


@dataclass(frozen=True)
class Config:
    users: int = 200
    max_live: int = 0                  # 0 = users; tests lower it to hit the live-state cap
    items: int = 40
    bins: int = 4
    behavior: Behavior = field(default_factory=Behavior)


def define(p: Pack, cfg: Config) -> None:
    item = p.table("item", key="item_id", cols={"bin": i32(), "price": amount(asset="USD")},
                   source=std.generated(n=cfg.items, cols={
                       "bin": dist.uniform_int(0, cfg.bins - 1),
                       "price": dist.uniform_int(100, 5_000)}))
    user = p.table("user", key="user_id", mutable=True, cols={
        "tier": cat("a", "b"), "balance": amount(asset="USD"), "last_note": opt(ref("note"))})
    p.table("note", key="note_id", mutable=True, child_of="user", cols={"size": i32()})
    p.ids("visit")
    p.owner("user", table=user, max_live=cfg.max_live or cfg.users)
    p.population(user, n=cfg.users, initial=0.5,
                 arrivals=dist.poisson_daily(weekly=(1, 1, 1, 1, 1, 1, 1)),
                 attrs={"tier": dist.categorical({"a": 0.5, "b": 0.5})})
    bins = p.shard("bin", key="bin", n=cfg.bins, items=item, state={"on_hand": "i32[item]"},
                   init={"on_hand": dist.uniform_int(0, 3)})
    take = p.request("take", frm="user", to=bins, payload={"item_id": ref("item")},
                     response_payload={"item_id": ref("item")}, responses=("ok", "none"),
                     latency=dist.constant(ms=200))
    p.event("user_joined", owner="user", cols={"user_id": ref("user"), "tier": cat("a", "b")})
    p.event("ping", owner="user", cols={
        "user_id": ref("user"), "visit_id": ref("visit"), "n": i32(min=0),
        "note_id": opt(ref("note"))})
    p.event("took", owner="user", cols={
        "user_id": ref("user"), "item_id": ref("item"), "ok": cat("yes", "no")})
    p.event("item_taken", shard="bin", cols={
        "bin": i32(), "item_id": ref("item"), "left": i32(min=0)})
    p.event("take_failed", shard="bin", cols={"bin": i32(), "item_id": ref("item")})
    p.process("user_main", owner="user", kernel=k.user_main, config=cfg.behavior,
              start=p.on_created("user"), requests={"take": take},
              on_response={("take", "ok"): k.R_OK, ("take", "none"): k.R_NONE},
              reads={"item": item}, commands=k.USER_COMMANDS)
    p.process("bin_desk", shard=bins, kernel=k.bin_desk, on_request={"take": k.C_TAKE},
              reads={"item": item})
```

`fixtures/mini/specs/kernels.py`:
```python
"""Mini kernels: an owner that pings, creates rows and requests stock; a shard that answers."""

from neorisk_simkit import std
from neorisk_simkit.engine import COMMIT, PRIO_TIMER, RETRY, START, Local, Res, kernel, reject

C_PING = 1
R_OK = 2
R_NONE = 3
USER_COMMANDS = (START, C_PING, R_OK, R_NONE)
C_TAKE = 1
REJ_DONE = 1


@kernel(state="user", local=Local(pings="i32", visit="ref"), commands=USER_COMMANDS,
        max=Res(records={"user_joined": 1, "ping": 1, "took": 1},
                creates={"note": 1, "visit": 1}, timers=1, requests=1))
def user_main(ctx, s, loc, cmd, out):
    cfg = ctx.cfg
    if cmd.kind == START:
        if not out.reserve(records={"user_joined": 1}, timers=1):
            return RETRY
        out.emit_user_joined(ctx.t, user_id=ctx.self_id, tier=s.tier)
        out.timer(ctx.t + ctx.rng.dist_us(site=1, d=cfg.ping_gap), C_PING, prio=PRIO_TIMER)
        return COMMIT
    if cmd.kind == C_PING:
        if loc.pings >= cfg.max_pings:
            return reject(REJ_DONE)                    # no timer: the user goes idle and retires
        take = ctx.rng.bernoulli(site=2, p=cfg.take_p)
        note = ctx.rng.bernoulli(site=3, p=cfg.note_p)
        if not out.reserve(records={"ping": 1}, creates={"note": 1, "visit": 1}, timers=1,
                           requests=1):
            return RETRY
        loc.visit = out.new_id("visit")
        nid = s.last_note                              # a handle from an earlier step, or NULL
        if note:
            nid = out.create_note(size=ctx.rng.uniform_int(site=4, lo=1, hi=9))
            s.last_note = nid                          # provisional until the step seals
        loc.pings += 1
        out.emit_ping(ctx.t, user_id=ctx.self_id, visit_id=loc.visit, n=loc.pings, note_id=nid)
        if take:
            item = ctx.rng.uniform_int(site=5, lo=0, hi=ctx.reads.item.n - 1)
            out.request_take(ctx.t, shard=ctx.reads.item.bin[item], item_id=item, tag=loc.visit)
        else:
            out.timer(ctx.t + ctx.rng.dist_us(site=6, d=cfg.ping_gap), C_PING, prio=PRIO_TIMER)
        return COMMIT
    if not out.reserve(records={"took": 1}, timers=1):
        return RETRY
    if cmd.kind == R_OK:
        out.emit_took(ctx.t, user_id=ctx.self_id, item_id=cmd.item_id, ok="yes")
    else:
        out.emit_took(ctx.t, user_id=ctx.self_id, item_id=cmd.item_id, ok="no")
    out.timer(ctx.t + ctx.rng.dist_us(site=7, d=cfg.ping_gap), C_PING, prio=PRIO_TIMER)
    return COMMIT


@kernel(state="bin", commands=(C_TAKE,),
        max=Res(records={"item_taken": 1, "take_failed": 1}, requests=1))
def bin_desk(ctx, s, cmd, out):
    i = ctx.reads.item.local_index[cmd.item_id]
    if not out.reserve(records={"item_taken": 1, "take_failed": 1}, requests=1):
        return RETRY
    if s.on_hand[i] > 0:
        s.on_hand[i] = std.checked_sub(s.on_hand[i], 1)
        out.emit_item_taken(ctx.t, bin=ctx.self_id, item_id=cmd.item_id, left=s.on_hand[i])
        out.respond(cmd, "ok", item_id=cmd.item_id)
    else:
        out.emit_take_failed(ctx.t, bin=ctx.self_id, item_id=cmd.item_id)
        out.respond(cmd, "none", item_id=cmd.item_id)
    return COMMIT
```

`libs/simkit/tests/conftest.py`:
```python
import dataclasses
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_project():
    def get(name: str) -> Path:
        path = FIXTURES / name
        assert (path / "datagen.toml").exists(), path
        return path
    return get


def make_run(name, overrides=(), **engine):
    from neorisk_simkit.spec.project import load_project, resolve_run  # lazy: conftest loads first

    run = resolve_run(load_project(FIXTURES / name), "sample", list(overrides))
    if engine:
        run = dataclasses.replace(run, engine=dataclasses.replace(run.engine, **engine))
    return run


def dataset_tree(d: Path) -> dict[str, bytes]:
    """Every file of a dataset except run_stats.json (not part of replay identity), by path."""
    return {p.relative_to(d).as_posix(): p.read_bytes() for p in sorted(d.rglob("*"))
            if p.is_file() and p.name != "run_stats.json"}
```

- [ ] **Step 2: Write the failing tests**

`libs/simkit/tests/test_spec_pack.py`:
```python
import pytest

from neorisk_simkit.spec import Pack, PackError
from neorisk_simkit.spec.project import (
    ProjectError, load_project, parse_duration, parse_size, resolve_run,
)


def _run(fixture_project, *overrides, profile="sample"):
    return resolve_run(load_project(fixture_project("mini")), profile, list(overrides))


def test_run_spec_from_project(fixture_project):
    run = _run(fixture_project, "users=50", "behavior.take_p=0.5", "engine.step=1h")
    assert run.name == "sample-s7" and run.seed == 7
    assert run.cfg.users == 50 and run.cfg.behavior.take_p == 0.5
    assert run.engine.step_us == 3_600_000_000
    assert run.start_us == 1_772_323_200_000_000          # 2026-03-01T00:00:00Z
    assert run.warmup_us == 6 * 3_600_000_000 and run.span_us == 2 * 86_400_000_000
    assert run.budget.threads == 2 and run.budget.memory_bytes == 2 * 1024**3
    assert run.writer.row_group_rows == 131_072
    assert run.overrides == ("users=50", "behavior.take_p=0.5", "engine.step=1h")


def test_run_prefix_overrides_window(fixture_project):
    run = _run(fixture_project, "run.span=1d", "run.warmup=0s")
    assert run.span_us == 86_400_000_000 and run.warmup_us == 0


def test_seed_override_changes_name(fixture_project):
    run = resolve_run(load_project(fixture_project("mini")), "sample", [], seed=9)
    assert run.name == "sample-s9" and run.seed == 9


def test_unknown_override_and_profile(fixture_project):
    with pytest.raises(ProjectError, match="unknown setting 'userz'"):
        _run(fixture_project, "userz=3")
    with pytest.raises(ProjectError, match="unknown profile 'nope'"):
        _run(fixture_project, profile="nope")
    with pytest.raises(ProjectError, match="expected key=value"):
        _run(fixture_project, "users")


def test_plan_codes_and_lookups(fixture_project):
    plan = _run(fixture_project).plan
    assert plan.pack == "mini" and plan.schema_version == 1 and len(plan.revision) == 7
    assert [t.name for t in plan.tables] == ["item", "user", "note"]
    assert [e.name for e in plan.events] == [
        "user_joined", "ping", "took", "item_taken", "take_failed"]
    assert [e.code for e in plan.events] == [0, 1, 2, 3, 4]
    ping = plan.event("ping")
    assert [c.name for c in ping.cols] == [
        "event_id", "event_type", "event_time", "lamport", "partition_id", "seq", "cause_id",
        "action_id", "user_id", "visit_id", "n", "note_id"]
    assert ping.partition == "user" and ping.kind == "owner"
    assert plan.event("item_taken").kind == "shard"
    take = plan.boundary("take")
    assert take.kind == "request" and take.min_latency_us == 200_000
    assert take.responses == ("ok", "none") and take.frm == "user" and take.to == "bin"
    b = plan.partition("bin")
    assert b.kind == "shard" and b.n == 4 and b.items == "item" and b.key == "bin"
    u = plan.partition("user")
    assert u.kind == "owner" and u.max_live == 200 and u.ptype_code == 1 and b.ptype_code == 2
    assert plan.process("user_main").action_id == 0 and plan.process("bin_desk").action_id == 1
    assert plan.process("user_main").kernel.name == "user_main"
    assert plan.namespaces == ("note", "visit") and plan.ns_code("visit") == 1
    assert plan.table("note").creatable and not plan.table("user").creatable


def test_revision_is_stable(fixture_project):
    assert _run(fixture_project).plan.revision == _run(fixture_project, "users=9").plan.revision


def test_unsupported_vocabulary_names_milestone():
    p = Pack("x", 1)
    with pytest.raises(PackError, match="arrives in M3"):
        p.machine("fulfillment", owner="user", initial="placed")
    with pytest.raises(PackError, match="arrives in M3"):
        p.expose(signup=None)


def test_pack_rejects_duplicates_and_unknown_refs():
    p = Pack("x", 1)
    p.table("user", key="user_id", mutable=True, cols={})
    with pytest.raises(PackError, match="duplicate table 'user'"):
        p.table("user", key="user_id", cols={})
    with pytest.raises(PackError, match="unknown partition 'ghost'"):
        p.event("e", owner="ghost", cols={})
    with pytest.raises(PackError, match="exactly one of owner= or shard="):
        p.event("e2", cols={})
    assert p.shard("desk", key="desk", n=1, items=None, state={}) == "desk"
    with pytest.raises(PackError, match="per-item state needs items="):
        p.shard("desk2", key="desk", n=1, items=None, state={"x": "i32[user]"})


def test_make_run_helper_applies_engine_settings():
    from conftest import make_run
    run = make_run("mini", ["users=20"], slab_bytes=4096)
    assert run.cfg.users == 20 and run.engine.slab_bytes == 4096


def test_parse_helpers():
    assert parse_duration("300ms") == 300_000 and parse_duration("90d") == 90 * 86_400_000_000
    assert parse_duration("15m") == 900_000_000
    assert parse_size("8MB") == 8 * 1024**2 and parse_size("16GB") == 16 * 1024**3
    with pytest.raises(ProjectError):
        parse_duration("3 weeks")
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run --all-packages pytest libs/simkit/tests/test_spec_pack.py -v`
Expected: FAIL with `ImportError: cannot import name 'Pack'`.

- [ ] **Step 4: Implement**

Notes:
- `Pack` methods accept either a name string or the string returned by an earlier call (so `table=user` works when `user` is the returned name). `owner(..., table=)` requires a mutable table. `event` requires exactly one of `owner=`/`shard=` naming a declared partition. Ref targets are resolved in `build_plan` (tables + `ids` namespaces); unknown → `PackError("unknown ref target 'x' in event e.col")`.
- `project.load_project(dir)` reads `datagen.toml` with `tomllib`; `[project].pack` defaults to `specs/pack.py`.
- Importing the pack: create a synthetic package name `neorisk_project_<name>_<sha8 of abs dir>` with `importlib.util.spec_from_file_location(pkg, specs/__init__ path or None, submodule_search_locations=[specs_dir])`, register it in `sys.modules`, then import `<pkg>.pack` (so `from . import kernels as k` works) — the specs folder needs no `__init__.py`.
- `resolve_run`: merge `[defaults]` ← `[profiles.<profile>]` (top-level keys like `span`) ← `profiles.<profile>.set` ← overrides. Override values parse as TOML scalars (`tomllib.loads(f"v = {value}")`, falling back to the raw string). Keys prefixed `engine.`/`budget.`/`writer.` set those tables, `run.` keys set `start`/`span`/`warmup`/`seed`; other keys walk the `Config` dataclass by dotted path and are applied with `dataclasses.replace` (nested). Unknown → `ProjectError(f"unknown setting {key!r}")`.
- `start` parses RFC 3339 `Z` to epoch µs. `mode` must be `"time"` (`ProjectError("mode 'population' arrives later")`).
- `build_plan(pack_module, cfg, specs_dir)`: `p = Pack(pack_module.PACK, pack_module.SCHEMA_VERSION)`; `pack_module.define(p, cfg)`; normalize; revision per D22 (hash `specs/**/*.py` and `specs/expectations.yaml` if present).
- `EngineSettings.force_capacity` defaults to an empty mapping; `engine.force_capacity` is only set by tests through `resolve_run(..., overrides=[...])` is not needed — tests pass it via `run_to_dataset(engine_overrides=...)` (Task 12).
- `Source.generate` raises `NotImplementedError` here; Task 5 implements it.
- `shard(..., items=None, state={})` is legal (the `ordering` and `abi_proof` fixtures of Tasks 10 and 13 use it): `PartitionDef.items` is `None` and the shard has no per-item arrays.
- `KernelSpec` (Task 2), `RunSpec`, `Budget`, `EngineSettings`, `WriterSettings` and every `spec.plan` class are frozen dataclasses.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run --all-packages pytest libs/simkit/tests/test_spec_pack.py -v`
Expected: PASS (10 tests).

- [ ] **Step 6: Lint and commit**

Run: `uv run ruff check $(ls -d libs apps examples/ecommerce_s1 benchmarks 2>/dev/null)`
```bash
git add libs/simkit/src/neorisk_simkit/spec libs/simkit/src/neorisk_simkit/std/__init__.py libs/simkit/tests/conftest.py libs/simkit/tests/fixtures/mini libs/simkit/tests/test_spec_pack.py
git commit -m "simkit: pack API, normalized plan, project loader, mini fixture

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 4: `validate` and memory caps

**Files:**
- Create: `libs/simkit/src/neorisk_simkit/spec/validate.py`, `spec/caps.py`, `libs/simkit/src/neorisk_simkit/engine/world.py` (only the hidden-array dtype table; Task 8 adds the `World` class to this file)
- Test: `libs/simkit/tests/test_spec_validate.py`

**Interfaces:**
- Consumes: Task 3 `Plan`, `RunSpec`, `build_plan` (all frozen dataclasses); Task 2 `KernelSpec` (frozen dataclass), `CapExceeded`.
- Produces:
  - `spec.caps`: `CAP_ITEMS = ("output_slabs", "step_output", "merge_working_space", "live_partition_state", "timer_heaps", "requests_and_inboxes", "fanout_bursts", "read_inputs", "checker_state", "scorer")`; `CapItem(name, hard_bytes, estimate_bytes, note)`; `NODE_BYTES = 40` (D8; deviation from spec §10 (24 B): kept at 40 B to avoid a payload indirection on the hot path; memory caps use the real size); `PAYLOAD_W = 12` and `OUTBOX_ROW_BYTES = 8 * 12 + 8 * PAYLOAD_W` (= 192; `engine.cmdq` does not exist yet, so the width is hard-coded here and Task 7's test asserts `caps.PAYLOAD_W == cmdq.PAYLOAD_W` and `caps.OUTBOX_ROW_BYTES == 8*12 + 8*cmdq.PAYLOAD_W`); `hidden_bytes(plan) -> int` (per-slot bytes of the hidden partition arrays: imports `engine.world.hidden_bytes` lazily inside the function and calls it with `a` = max processes per partition type, `n_ns = len(plan.namespaces)`); `row_bytes(cols) -> int` (sum of storage itemsizes + 1 per nullable column); `slabs_per_worker(plan) -> int` (= #events + #change groups + #namespaces + 1 outbox); `compute_caps(run: RunSpec) -> list[CapItem]`; `BudgetError(Exception)`; `check_budget(caps, budget) -> None` (raises `BudgetError` naming every item, largest first, when `Σ hard_bytes > budget.memory_bytes`).
  - `spec.validate`: `ValidationReport(errors: list[str], warnings: list[str], caps: list[CapItem])` with `.ok`; `validate(run: RunSpec) -> ValidationReport`.
  - `engine.world` (this task creates the module with only these two names; it imports numpy only): `HIDDEN_DTYPES: tuple[tuple[str, str, int | str], ...]` — `(name, numpy dtype name, per-slot multiplicity)` with multiplicity `1`, `"A"` or `"N_NS"`, one row per hidden array of the Engine reference, in this order: `pid int64 1, ptype int16 1, lslot int32 1, gen uint32 1, alive uint8 1, clock int64 1, rseq int32 1, cseq int64 1, pending int32 1, qhead int32 1, inst int64 1, self_id int64 1, occ uint32 A, ordn int32 N_NS, retire_at int64 1, susp_t int64 1, susp_delta int64 1`; `hidden_bytes(a: int, n_ns: int) -> int` = `Σ itemsize × multiplicity` (= `8*8 + 4*5 + 2 + 1 + 4a + 4n_ns`). Task 8's `World` allocates every hidden array from this table (2-D `[G, A]` / `[G, N_NS]` for the non-1 multiplicities), so the cap and the allocation cannot drift; Tasks 9 and 10 use `susp_t` / `susp_delta` without adding arrays.

- [ ] **Step 1: Write the failing tests**

`libs/simkit/tests/test_spec_validate.py`:
```python
import dataclasses

import pytest

from neorisk_simkit.spec import dist
from neorisk_simkit.spec.caps import CAP_ITEMS, NODE_BYTES, BudgetError, check_budget, compute_caps
from neorisk_simkit.spec.project import load_project, resolve_run
from neorisk_simkit.spec.validate import validate


@pytest.fixture
def run(fixture_project):
    return resolve_run(load_project(fixture_project("mini")), "sample", [])


def _with_boundary(run, name, **changes):
    plan = run.plan
    bs = tuple(dataclasses.replace(b, **changes) if b.name == name else b for b in plan.boundaries)
    return dataclasses.replace(run, plan=dataclasses.replace(plan, boundaries=bs))


def _with_kernel(run, proc, **changes):
    plan = run.plan
    ps = tuple(dataclasses.replace(p, kernel=dataclasses.replace(p.kernel, **changes))
               if p.name == proc else p for p in plan.processes)
    return dataclasses.replace(run, plan=dataclasses.replace(plan, processes=ps))


def test_mini_is_valid(run):
    rep = validate(run)
    assert rep.ok, rep.errors
    assert [c.name for c in rep.caps] == list(CAP_ITEMS)


def test_zero_latency_boundary_is_an_error(run):
    bad = _with_boundary(run, "take", latency=dist.constant(ms=0), min_latency_us=0)
    assert "boundary take: minimum latency must be > 0" in validate(bad).errors


def test_cross_partition_write_is_an_error(run):
    bad = _with_kernel(run, "bin_desk", state="user")
    errs = validate(bad).errors
    assert any("process bin_desk runs in partition 'bin' but its kernel state is 'user'" in e
               for e in errs)


def test_reserving_foreign_or_unknown_records_is_an_error(run):
    from neorisk_simkit.engine import Res
    bad = _with_kernel(run, "user_main", max=Res(records={"item_taken": 1, "nope": 1}))
    errs = validate(bad).errors
    assert any("user_main reserves records of 'item_taken' owned by partition 'bin'" in e
               for e in errs)
    assert any("user_main reserves unknown record type 'nope'" in e for e in errs)


def test_start_command_without_start_trigger_and_bad_command_ids(run):
    bad = _with_kernel(run, "bin_desk", commands=(0, 1))
    assert any("bin_desk handles START but has no start= or every=" in e
               for e in validate(bad).errors)


def test_caps_formulas(run):
    caps = {c.name: c for c in compute_caps(run)}
    from neorisk_simkit.spec.caps import slabs_per_worker
    spw = slabs_per_worker(run.plan)
    assert spw == 5 + 0 + 2 + 1
    assert caps["output_slabs"].hard_bytes == run.budget.threads * spw * run.engine.slab_bytes
    assert caps["merge_working_space"].hard_bytes == 2 * caps["step_output"].hard_bytes
    assert caps["timer_heaps"].hard_bytes == run.engine.timer_nodes * NODE_BYTES == 100_000 * 40
    assert caps["checker_state"].hard_bytes == 0 and caps["scorer"].hard_bytes == 0
    assert all(c.estimate_bytes <= c.hard_bytes for c in caps.values())


def test_hidden_bytes_follow_the_world_dtype_table(run):
    import numpy as np

    from neorisk_simkit.engine.world import HIDDEN_DTYPES, hidden_bytes
    from neorisk_simkit.spec import caps as caps_mod
    per = {1: 1, "A": 3, "N_NS": 2}
    expect = sum(np.dtype(dt).itemsize * per[m] for _, dt, m in HIDDEN_DTYPES)
    assert hidden_bytes(3, 2) == expect == 8 * 8 + 4 * 5 + 2 + 1 + 4 * 3 + 4 * 2
    names = [n for n, _, _ in HIDDEN_DTYPES]
    assert "susp_t" in names and "susp_delta" in names and len(names) == len(set(names))
    assert caps_mod.hidden_bytes(run.plan) == hidden_bytes(1, len(run.plan.namespaces))


def test_forced_timer_capacity_below_a_kernel_maximum_is_an_error(run):
    bad = dataclasses.replace(run, engine=dataclasses.replace(
        run.engine, force_capacity={"timers": 0}))
    assert any("force_capacity timers=0 is below the declared maximum timers=1 of user_main" in e
               for e in validate(bad).errors)
    ok = dataclasses.replace(run, engine=dataclasses.replace(
        run.engine, force_capacity={"timers": 1}))
    assert validate(ok).ok


def test_budget_refusal_names_items(run):
    small = dataclasses.replace(run, budget=dataclasses.replace(run.budget, memory_bytes=1024))
    with pytest.raises(BudgetError, match="exceed the memory budget") as e:
        check_budget(compute_caps(small), small.budget)
    assert "step_output" in str(e.value) and "timer_heaps" in str(e.value)
    assert not validate(small).ok
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --all-packages pytest libs/simkit/tests/test_spec_validate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'neorisk_simkit.spec.validate'`.

- [ ] **Step 3: Implement**

Structural rules in `validate` (each produces one error string, exact prefixes as in the tests):
1. `boundary <b>: minimum latency must be > 0` when `min_latency_us <= 0`.
2. `process <p> runs in partition '<x>' but its kernel state is '<y>'` (cross-partition write).
3. `<proc> reserves records of '<e>' owned by partition '<x>'`; `<proc> reserves unknown record type '<e>'` (records keys are event or change-group names); same for `creates` keys (must be namespaces): `<proc> reserves unknown namespace '<n>'`.
4. `<proc> handles START but has no start= or every=`; every command id in `on_request/on_response/on_message` values must appear in `kernel.commands`: `<proc> maps <what> to command <c> not listed in commands`.
5. Events emitted by kernels with non-optional `text` columns: `event <e>: column <c> is text; S1 kernels can only write opt(text)` (D18).
6. Requests must go owner → shard: `boundary <b>: requests go from an owner to a shard`; messages owner → shard only in S1 (owner → owner next-step delivery is deferred): `boundary <b>: owner-to-owner messages arrive in S2`.
7. Kernel max: `timers` > `engine.timer_nodes`, or any records count > slab rows for that table → `<proc>: declared maximum of <res> exceeds slab capacity` (capacity = `slab_bytes // row_bytes`). Forced capacities (Task 8 semantics; `force_capacity["timers"] = n` caps each worker's node refill chunk): `engine: force_capacity timers=<n> is below the declared maximum timers=<m> of <proc>` for every process whose `kernel.max.timers > n` (a kernel that reserves `m` timers could never succeed).
8. Spawn bound placeholder: `budget.max_spawn_depth` must be ≥ 1.
9. Caps over budget: append `BudgetError` message from `check_budget` to errors.
Warnings: `checks declared but not evaluated until S2: chk.x, ...` when `plan.checks` is non-empty.

`compute_caps(run)`:
- `output_slabs` = `threads × slabs_per_worker × slab_bytes`.
- `step_output` = `max(max_step_rows × max event row bytes (incl. common columns), max_step_bytes)`... use `min(max_step_rows × max_row_bytes, max_step_bytes)` if `max_step_bytes` is set, else the product.
- `merge_working_space` = `2 × step_output`.
- `live_partition_state` = `Σ owners max_live × (table row bytes + Σ local bytes of its processes + HIDDEN_BYTES)` + `Σ shards (n × HIDDEN_BYTES + items × state bytes)`, `HIDDEN_BYTES = caps.hidden_bytes(plan)` (derived from `engine.world.HIDDEN_DTYPES`; never a hand-written formula).
- `timer_heaps` = `timer_nodes × NODE_BYTES`.
- `requests_and_inboxes` = `max_messages_per_step × OUTBOX_ROW_BYTES + payload_slots × 8 × PAYLOAD_W`.
- `fanout_bursts` = `Σ processes with substep: substep × max record row bytes`.
- `read_inputs` = `Σ read tables rows × row bytes + refs CSR (estimate 3 ints per owner)`.
- `checker_state`, `scorer` = 0 with note `"not used in S1"`.
- Estimates: `step_output` estimate = 25% of the cap (the adaptive target); others = hard.
`check_budget` message: `"memory caps exceed the memory budget (<total> > <budget>): step_output=…, timer_heaps=…, …"` listing items largest first in MiB.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --all-packages pytest libs/simkit/tests/test_spec_validate.py -v`
Expected: PASS (9 tests).

- [ ] **Step 5: Lint and commit**

Run: `uv run ruff check $(ls -d libs apps examples/ecommerce_s1 benchmarks 2>/dev/null)`
```bash
git add libs/simkit/src/neorisk_simkit/spec libs/simkit/src/neorisk_simkit/engine/world.py libs/simkit/tests/test_spec_validate.py
git commit -m "simkit: structural validation and memory caps

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 5: Keyed RNG, sources and identity

**Files:**
- Create: `libs/simkit/src/neorisk_simkit/engine/rng.py`, `engine/identity.py`
- Modify: `spec/sources.py` (implement `Source.generate` for `generated`), `spec/dist.py` (add `sample_np(d, u: np.ndarray, u2: np.ndarray) -> np.ndarray`)
- Test: `libs/simkit/tests/test_engine_rng_identity.py`

**Interfaces:**
- Consumes: Task 1 `dist`; Task 3 `Source`.
- Produces (all `@njit(cache=True, nogil=True)` unless noted):
  - `rng.u64(x) -> uint64`: a plain Python function `np.uint64(int(x) & 0xFFFF_FFFF_FFFF_FFFF)` with a `numba.extending.overload` whose compiled implementation is `uint64(x)` (wrap-around cast). Every njit function in `rng`/`identity` converts integer arguments with `u64(...)`, never with `uint64(...)` directly, so the uncompiled leg (`NUMBA_DISABLE_JIT=1`, where `numba.uint64` is `np.uint64` and NumPy 2 raises `OverflowError` on negative Python ints) gives the same bits as the compiled one. `rng.MASK64 = 0xFFFF_FFFF_FFFF_FFFF`.
  - `rng.mix64(x) -> uint64` (splitmix64 finalizer; `x = u64(x)` first); `rng.name_key(name: str) -> int` (Python: `int.from_bytes(sha256(name)[:8], "little")`, an unsigned value in `[0, 2^64)`); Python callers mask every key part with `& MASK64` before `mix64` (`feistel_key`, `uniforms`, the `inst = mix(name_key(table), ordinal)` instance keys); `rng.key_uniform(seed, inst, action, occ, site, k) -> float64` in [0, 1); `rng.next_k(kc, site) -> int` (returns and advances the per-invocation counter for `site`); samplers taking a uniform pair: `rng.sample_us(code, p1, p2, p3, u1, u2) -> int64` for duration dists, `rng.geometric(mean, u) -> int64`, `rng.bernoulli(p, u) -> bool`, `rng.uniform_int(lo, hi, u) -> int64`, `rng.categorical(weights_tuple, u) -> int64`, `rng.pareto_us(alpha, min_us, u)`, `rng.normal(u1, u2) -> float64` (Box–Muller); vectorized Python helper `rng.uniforms(seed, stream, n, offset=0) -> np.ndarray` (= `key_uniform(seed, stream, 0, 0, 0, offset+i)`).
  - `identity.FLAG = 1 << 62`; `make_handle(ns, slot, ordinal) -> int64`; `handle_ns(h)`, `handle_slot(h)`, `handle_ordinal(h)`; `is_provisional(v) -> bool` (`v >= 0 and v & FLAG`); `feistel_key(seed: int, name: str) -> np.ndarray[uint64, 4]` (Python; round keys); `feistel63(dense: int64, keys) -> int64` (bijection `[0, 2^63-1) → [1, 2^63-1]`); `feistel63_array(dense: np.ndarray, keys) -> np.ndarray`; `assign_dense(pids: np.ndarray, ordinals: np.ndarray, base: int) -> np.ndarray` (dense value per row, ranked by `(pid, ordinal)`); `remap_inplace(values: np.ndarray, src_sorted: np.ndarray, dst: np.ndarray) -> int` (replaces provisional values found in `src_sorted` by the matching `dst`; returns number of provisional values not found).
  - `Source.generate(n_rows, table, seed, stream) -> dict[str, np.ndarray]` for `generated(n, cols)`: column `c` uses uniforms of stream `hash(stream, c)`.

- [ ] **Step 1: Write the failing tests**

`libs/simkit/tests/test_engine_rng_identity.py`:
```python
import numpy as np
import pytest

from neorisk_simkit.engine import identity as ident
from neorisk_simkit.engine import rng
from neorisk_simkit.spec import dist


def test_key_uniform_deterministic_and_sensitive_to_every_key_part():
    base = rng.key_uniform(42, 7, 1, 3, 5, 0)
    assert 0.0 <= base < 1.0 and base == rng.key_uniform(42, 7, 1, 3, 5, 0)
    others = [rng.key_uniform(43, 7, 1, 3, 5, 0), rng.key_uniform(42, 8, 1, 3, 5, 0),
              rng.key_uniform(42, 7, 2, 3, 5, 0), rng.key_uniform(42, 7, 1, 4, 5, 0),
              rng.key_uniform(42, 7, 1, 3, 6, 0), rng.key_uniform(42, 7, 1, 3, 5, 1)]
    assert len(set(others + [base])) == 7


def test_key_uniform_is_roughly_uniform():
    u = np.array([rng.key_uniform(1, 2, 3, 4, 5, k) for k in range(100_000)])
    assert abs(u.mean() - 0.5) < 0.005 and u.min() >= 0 and u.max() < 1


def test_python_and_compiled_agree():
    assert rng.key_uniform.py_func(42, 7, 1, 3, 5, 9) == rng.key_uniform(42, 7, 1, 3, 5, 9)
    assert ident.feistel63.py_func(123, ident.feistel_key(1, "user")) == ident.feistel63(
        123, ident.feistel_key(1, "user"))


def test_negative_and_high_bit_keys_work_uncompiled():
    # instance keys live in int64 arrays, so half of them are negative; the uncompiled leg
    # (NUMBA_DISABLE_JIT=1) must accept them and agree bit for bit with the compiled code
    for name in ("user", "order", "device", "sku", "session", "payment", "item", "note"):
        assert 0 <= rng.name_key(name) < 2**64
        keys = ident.feistel_key(7, name)
        assert keys.dtype == np.uint64 and len(keys) == 4
    u_py = rng.key_uniform.py_func(42, -12345, 1, 3, 5, 0)
    assert u_py == rng.key_uniform(42, -12345, 1, 3, 5, 0) and 0.0 <= u_py < 1.0
    assert int(rng.mix64.py_func(-1)) == int(rng.mix64(-1))
    assert int(rng.mix64.py_func(2**64 - 1)) == int(rng.mix64(-1))


def test_next_k_counts_per_site():
    kc = np.zeros(33, np.int64)
    assert [rng.next_k(kc, 5), rng.next_k(kc, 5), rng.next_k(kc, 9), rng.next_k(kc, 5)] == [
        0, 1, 0, 2]
    kc[0] = 0                                    # reset per invocation
    assert rng.next_k(kc, 5) == 0


def test_duration_samplers():
    c, a, b, d = dist.encode(dist.constant(ms=300))
    assert rng.sample_us(c, a, b, d, 0.3, 0.7) == 300_000
    c, a, b, d = dist.encode(dist.shifted_lognormal(min_ms=150, median_ms=240))
    xs = [rng.sample_us(c, a, b, d, rng.key_uniform(1, 1, 1, 1, 1, k),
                        rng.key_uniform(1, 1, 1, 1, 2, k)) for k in range(2000)]
    assert min(xs) >= 150_000 and 200_000 < float(np.median(xs)) < 280_000
    c, a, b, d = dist.encode(dist.exp(mean_s=10))
    xs = [rng.sample_us(c, a, b, d, rng.key_uniform(2, 1, 1, 1, 1, k), 0.5) for k in range(20000)]
    assert 9.5e6 < np.mean(xs) < 10.5e6


def test_feistel_is_a_positive_bijection_per_table():
    keys = ident.feistel_key(7, "order")
    dense = np.arange(200_000, dtype=np.int64)
    out = ident.feistel63_array(dense, keys)
    assert len(np.unique(out)) == len(out) and out.min() >= 1
    other = ident.feistel63_array(dense, ident.feistel_key(7, "user"))
    assert (out != other).mean() > 0.999
    assert not np.array_equal(out, ident.feistel63_array(dense, ident.feistel_key(8, "order")))


def test_handles_roundtrip_and_flag():
    h = ident.make_handle(5, 1_000_000, 77)
    assert ident.is_provisional(h) and not ident.is_provisional(12345)
    assert (ident.handle_ns(h), ident.handle_slot(h), ident.handle_ordinal(h)) == (5, 1_000_000, 77)
    assert 0 < h < 2**63


def test_assign_dense_orders_by_pid_then_ordinal():
    pids = np.array([30, 10, 10, 20], np.int64)
    ords = np.array([0, 1, 0, 0], np.int64)
    assert ident.assign_dense(pids, ords, 100).tolist() == [103, 101, 100, 102]


def test_remap_inplace():
    h1, h2 = ident.make_handle(0, 1, 0), ident.make_handle(0, 2, 0)
    src = np.sort(np.array([h1, h2], np.int64))
    dst = np.array([10, 11], np.int64) if src[0] == h1 else np.array([11, 10], np.int64)
    vals = np.array([h2, 5, h1, -(2**63)], np.int64)
    missing = ident.remap_inplace(vals, src, dst)
    assert missing == 0 and vals.tolist() == [11, 5, 10, -(2**63)]
    vals2 = np.array([ident.make_handle(0, 9, 9)], np.int64)
    assert ident.remap_inplace(vals2, src, dst) == 1


def test_generated_source_is_keyed_and_bounded(fixture_project):
    from neorisk_simkit.spec.project import load_project, resolve_run
    run = resolve_run(load_project(fixture_project("mini")), "sample", [])
    item = run.plan.table("item")
    cols = item.source.generate(40, item, seed=run.seed, stream=1)
    again = item.source.generate(40, item, seed=run.seed, stream=1)
    assert set(cols) == {"bin", "price"} and np.array_equal(cols["bin"], again["bin"])
    assert cols["bin"].min() >= 0 and cols["bin"].max() <= 3
    with pytest.raises(ValueError, match="row count"):
        item.source.generate(41, item, seed=run.seed, stream=1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --all-packages pytest libs/simkit/tests/test_engine_rng_identity.py -v`
Expected: FAIL with `ImportError: cannot import name 'identity'`.

- [ ] **Step 3: Implement**

Key code (`engine/rng.py`):
```python
import numpy as np
from numba import njit, uint64
from numba.extending import overload

_GOLD = np.uint64(0x9E3779B97F4A7C15)


MASK64 = 0xFFFF_FFFF_FFFF_FFFF


def u64(x):                       # used as-is when NUMBA_DISABLE_JIT=1
    return np.uint64(int(x) & MASK64)


@overload(u64)
def _u64_jit(x):                  # compiled: a wrap-around cast
    return lambda x: uint64(x)


@njit(cache=True, nogil=True)
def mix64(x):
    x = u64(x)
    x = (x ^ (x >> uint64(30))) * uint64(0xBF58476D1CE4E5B9)
    x = (x ^ (x >> uint64(27))) * uint64(0x94D049BB133111EB)
    return x ^ (x >> uint64(31))


@njit(cache=True, nogil=True)
def key_uniform(seed, inst, action, occ, site, k):
    h = mix64(u64(seed) + _GOLD)
    h = mix64(h ^ u64(inst))
    h = mix64(h ^ (u64(action) << uint64(32)) ^ u64(site))
    h = mix64(h ^ u64(occ))
    h = mix64(h ^ u64(k))
    return (h >> uint64(11)) * (1.0 / 9007199254740992.0)    # 53 bits -> [0, 1)
```
(`uint64(<constant>)` on literals is safe in both modes because the constants are non-negative.)
- `next_k(kc, site)`: linear scan of the `kc[0]` used pairs; append `(site, 0)` if absent (raise `EngineError`-free `ValueError("more than 16 sites")` beyond 16 distinct sites per invocation).
- `sample_us`: CONST → `p1`; EXP → `-p1 * log(1-u1)`; LOGNORMAL → `p1 * exp(p2 * z)`; SHIFTED_LOGNORMAL → `p1 + p2 * exp(p3 * z)`; GAMMA → Marsaglia–Tsang is not usable with two fixed uniforms, so use the Wilson–Hilferty approximation `mean * (1 - 1/(9k) + z*sqrt(1/(9k)))**3` clipped at 0 and at `p3` when `p3 > 0`; NORMAL → `p1 + p2 * z`; PARETO → `min_us * (1-u1)**(-1/alpha)`; `z` = Box–Muller from `(u1, u2)`; result rounded to int64.
- `feistel63`: 4-round balanced Feistel on 64 bits with round function `mix64(right ^ key[i]) & 0xFFFFFFFF`; cycle-walk until the output is `< 2^63 - 1`; return `output + 1`. Domain input must be `< 2^63 - 1`.
- `feistel_key(seed, name)`: `k_i = mix64(((seed & MASK64) ^ name_key(name) ^ i) & MASK64)` for i in 0..3, as a uint64 array (`name_key` is unsigned, so no negative Python int ever reaches `np.uint64`).
- `assign_dense`: `np.lexsort((ordinals, pids))` ranks → `base + rank` scattered back (njit with `np.argsort` on a combined structured key is fine in Python; implement in numpy, not njit).
- `remap_inplace`: `np.searchsorted` over `src_sorted` for values with the flag bit; misses counted.
- `Source.generate` for `generated`: for each column, `u = rng.uniforms(seed, mix(stream, name_key(col)), n)`, then `dist.sample_np(d, u, u2)` supporting UNIFORM_INT, CATEGORICAL (returns codes), LOGNORMAL_MINOR, NEGBINOM (gamma–Poisson via inverse transform on two uniforms), ZIPF (bounded by n rows: weights `1/(i+1)^s`). `n_rows != self.n` → `ValueError("row count 41 does not match source n=40")`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --all-packages pytest libs/simkit/tests/test_engine_rng_identity.py -v`
Expected: PASS (11 tests).

- [ ] **Step 5: Lint and commit**

Run: `uv run ruff check $(ls -d libs apps examples/ecommerce_s1 benchmarks 2>/dev/null)`
```bash
git add libs/simkit/src/neorisk_simkit libs/simkit/tests/test_engine_rng_identity.py
git commit -m "simkit: keyed RNG, Feistel public IDs, provisional handles, generated sources

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 6: Kernel lowering (AST pass)

**Files:**
- Create: `libs/simkit/src/neorisk_simkit/engine/layout.py`, `engine/lower.py`
- Test: `libs/simkit/tests/test_engine_lower.py`

**Interfaces:**
- Consumes: Task 3 `Plan`; Task 2 `KernelSpec`.
- Produces:
  - `engine.layout` (`payload_slots` = union over every inbound boundary: requests, messages, responses; `reads` row counts are constants only for fixed-`n` sources): `CTX_FIELDS = ("t", "self_id", "pid", "g", "inst", "action", "occ", "kc", "seed", "cfg", "reads", "refs", "lamport", "flags")`; `CMD_FIELDS = ("kind", "tag", "time", "cursor", "sender")` with `CMD_PAY = 5`, `CMD_PAY_ROW = 6`; `KernelLayout(name, partition_kind, state_fields: dict[str, int], state_cats: dict[str, tuple[str,...]], array_fields: dict[str, int], items_name: str | None, local_fields: dict[str, tuple[int, int]], cfg_fields: dict[str, int], cfg_nested: dict[str, dict], reads: dict[str, dict[str, int]], refs: dict[str, int], payload_slots: dict[str, int], events: dict[str, list[tuple[str, LType]]], creates: dict[str, list[tuple[str, LType]] | None], requests: dict[str, list[str]], messages: dict[str, list[str]], responses: dict[str, list[str]], change_groups: dict[str, list[tuple[str, LType]]])`; `kernel_layouts(plan) -> dict[str, KernelLayout]` (keyed by process name; a module-level helper function used by several kernels is lowered once per *module* using the union layout, see notes).
  - `engine.lower`: `LoweringError(Exception)`; `lower_module(source: str, layouts: Mapping[str, KernelLayout], kernel_funcs: Mapping[str, str]) -> str` where `kernel_funcs` maps function name → process name. Output is plain Python (no decorators) referencing only helper names `_emit_<event>`, `_create_<ns>`, `_new_id`, `_timer`, `_request_<b>`, `_send_<b>`, `_respond_<b>_<response>`, `_continue_at`, `_change_<group>`, `_reserve_<proc>`, `_rng_<method>`, `_reads_sample_by_weight`, `_refs_pick`, `_refs_count`, `_refs_get`, `reject`, `std`, and the integer constants it defines itself.

Lowering rules (the whole contract; anything else raises `LoweringError` with `file:line`):

| Kernel source | Lowered |
|---|---|
| `ctx.t`, `ctx.self_id`, `ctx.partition_id` | `ctx[0]`, `ctx[1]`, `ctx[2]` |
| `ctx.cfg` (or a local name bound to it) `.f` | `ctx[9][i_f]` / `cfg[i_f]`; nested dataclass `.a.b` → `[i_a][i_b]` |
| `ctx.reads.<t>.<col>[i]`, `ctx.reads.<t>.n`, `.local_index[i]` | `ctx[10][j][i]`; `.n` → the constant row count only when `<t>` has a `source` with a fixed `n` (e.g. `std.generated(n=…)`), otherwise `ctx[10][j_0].shape[0]` (`j_0` = the table's first read column) so recipe-built tables whose size scales with the population (e.g. `std.devices`) bake no population-dependent constant into the generated module (Task 24 asserts the compile run and the scaled run share one module file); `ctx[10][j_li][i]` |
| `ctx.reads.<t>.sample_by_weight(u)` | `_reads_sample_by_weight(ctx[10][j_cumw], u)` |
| `ctx.refs.<r>.pick(id, u)` / `.count(id)` / `.get(id, k)` | `_refs_pick(ctx[11][j], ctx[11][j+1], id, u)` etc. |
| `ctx.rng.<m>(site=N, **kw)` (N an int literal) | `_rng_<m>(ctx, N, *kw in declared order)`; methods: `uniform()`, `bernoulli(p)`, `geometric(mean)`, `uniform_int(lo, hi)`, `categorical(p)`, `exp_us(mean_s)`, `pareto_us(alpha, min_h)`, `dist_us(d)`, `lognormal_minor(median, sigma)` |
| `s.<col>` (owner) | `s[1+i][s[0]]` (load and store, AugAssign included) |
| `s.<field>[i]`, `s.n_<items>`, `s.<items>[i]` (shard) | `s[4+j][s[1]+i]`, `s[2]`, `s[3][s[1]+i]` |
| `loc.<f>` / `loc.<f>[i]` | `loc[1+j][loc[0]]` / `loc[1+j][loc[0], i]` |
| `cmd.kind/tag/time/cursor/sender` | `cmd[0..4]` |
| `cmd.<payload>` | `cmd[5][cmd[6], j]` |
| `out.reserve(records={...}, creates={...}, timers=a, requests=b)` | `_reserve_<proc>(out, (v_0, …, v_R))` — full resource vector in the order of `SlabSet` resources (Task 8), zeros where unspecified; dict keys must be string literals |
| `out.emit_<e>(t, **cols)` | `_emit_<e>(out, ctx, t, c_1, …, c_n)` in event column order (common columns excluded); missing `opt` column → `std.NULL`; missing required → error; string literal on a `cat` column → its code |
| `out.create_<ns>(**cols)` | `_create_<ns>(out, ctx, c_1, …)` (returns handle) |
| `out.new_id("<ns>")` | `_new_id(out, ctx, <ns code>)` |
| `out.timer(t, kind, prio=PRIO_TIMER, tag=0)` | `_timer(out, ctx, t, kind, prio, tag)` |
| `out.request_<b>(t, shard=x, tag=y, **payload)` | `_request_<b>(out, ctx, t, x, y, p_1, …)` |
| `out.send_<b>(t, to=x, tag=y, **payload)` | `_send_<b>(out, ctx, t, x, y, p_1, …)` |
| `out.respond(cmd, "<resp>", **payload)` | `_respond_<b>_<resp>(out, ctx, cmd, p_1, …)` (`b` = the request boundary handled by this kernel; exactly one) |
| `out.continue_at(t, cursor=c)` | `_continue_at(out, ctx, t, c)` |
| `out.change_<g>(t, **cols)` | `_change_<g>(out, ctx, s, t, c_1, …)` |
| a string literal compared (`==`, `!=`) with, or assigned to, a cat-typed `s.<col>` or `ctx.reads.<t>.<catcol>[i]` | the category code |
| `reject(c)`, `COMMIT`, `RETRY`, module int/float/str/tuple constants, `std.<name>` | unchanged |

Also: every `site=N` literal is unique within a process's call graph (`LoweringError("site 3 used twice in user_main")`); references to module-level names bound to lists, dicts, sets, numpy arrays or other mutable objects raise `LoweringError("mutable module global 'CACHE' used in user_main")` (the §05 lint). Helper functions (non-kernel module functions) called from kernels are lowered with the caller's layout; a helper called from kernels with different layouts is an error (`LoweringError("helper _x is shared by kernels with different state")`). Kernel decorators and `@kernel`/`Local`/`Res` imports are dropped from the output; `from neorisk_simkit import std` and `from neorisk_simkit.engine import ...` imports are replaced by a fixed prelude (`from neorisk_simkit import std`, `from neorisk_simkit.engine.abi import reject, COMMIT, RETRY, START, PRIO_CONTINUE, PRIO_MESSAGE, PRIO_EXPIRY, PRIO_TIMER`).

- [ ] **Step 1: Write the failing tests**

`libs/simkit/tests/test_engine_lower.py`:
```python
import textwrap

import numpy as np
import pytest

from neorisk_simkit.engine.layout import kernel_layouts
from neorisk_simkit.engine.lower import LoweringError, lower_module
from neorisk_simkit.spec.project import load_project, resolve_run

STD_NULL = -(2**63)


@pytest.fixture
def plan(fixture_project):
    return resolve_run(load_project(fixture_project("mini")), "sample", []).plan


def _lower(plan, body, proc="user_main"):
    src = textwrap.dedent(body)
    return lower_module(src, kernel_layouts(plan), {"k": proc})


def _exec(lowered, **stubs):
    ns = dict(stubs)
    exec(compile(lowered, "<lowered>", "exec"), ns)
    return ns


class Rec:
    def __init__(self, ret=None):
        self.calls, self.ret = [], ret

    def __call__(self, *args):
        self.calls.append(args)
        return self.ret


def _ctx(t=1000, self_id=3):
    cfg = ((1, 3.6e9, 0.0, 0.0), 0.3, 0.2, 50)
    return (t, self_id, 99, 0, 0, 0, 0, np.zeros(33, np.int64), 7, cfg, (), (), 1, 0)


def test_emit_maps_kwargs_to_column_order_and_cat_codes(plan):
    low = _lower(plan, """
        def k(ctx, s, loc, cmd, out):
            out.emit_took(ctx.t, ok="no", item_id=5, user_id=ctx.self_id)
            return 0
    """)
    emit = Rec()
    ns = _exec(low, _emit_took=emit)
    c = _ctx()                      # one ctx object: tuple == short-circuits on identity
    ns["k"](c, None, None, None, "OUT")
    assert emit.calls == [("OUT", c, 1000, 3, 5, 1)]


def test_missing_optional_becomes_null_and_missing_required_fails(plan):
    low = _lower(plan, """
        def k(ctx, s, loc, cmd, out):
            out.emit_ping(ctx.t, user_id=1, visit_id=2, n=3)
            return 0
    """)
    emit = Rec()
    ns = _exec(low, _emit_ping=emit)
    ns["k"](_ctx(), None, None, None, "OUT")
    assert emit.calls[0][-1] == STD_NULL
    with pytest.raises(LoweringError, match="missing required column 'n'"):
        _lower(plan, """
            def k(ctx, s, loc, cmd, out):
                out.emit_ping(ctx.t, user_id=1, visit_id=2)
                return 0
        """)
    with pytest.raises(LoweringError, match="unknown column 'zzz'"):
        _lower(plan, """
            def k(ctx, s, loc, cmd, out):
                out.emit_ping(ctx.t, user_id=1, visit_id=2, n=1, zzz=1)
                return 0
        """)


def test_state_and_local_access_reads_and_writes_arrays(plan):
    low = _lower(plan, """
        def k(ctx, s, loc, cmd, out):
            s.balance = s.balance + 5
            loc.pings += 1
            if s.tier == "b":
                return 1
            return 0
    """)
    ns = _exec(low)
    tier, balance, last_note = (np.array([0, 1], np.int16), np.array([10, 20], np.int64),
                                np.array([STD_NULL] * 2, np.int64))
    s = (1, tier, balance, last_note)
    loc = (1, np.array([0, 4], np.int32), np.zeros(2, np.int64))
    assert ns["k"](_ctx(), s, loc, None, None) == 1
    assert balance.tolist() == [10, 25] and loc[1].tolist() == [0, 5]


def test_cfg_alias_and_rng_calls(plan):
    low = _lower(plan, """
        def k(ctx, s, loc, cmd, out):
            cfg = ctx.cfg
            if ctx.rng.bernoulli(site=2, p=cfg.take_p):
                return ctx.rng.dist_us(site=1, d=cfg.ping_gap)
            return 0
    """)
    bern, dus = Rec(True), Rec(77)
    ns = _exec(low, _rng_bernoulli=bern, _rng_dist_us=dus)
    assert ns["k"](_ctx(), None, None, None, None) == 77
    assert bern.calls[0][1:] == (2, 0.3) and dus.calls[0][1:] == (1, (1, 3.6e9, 0.0, 0.0))


def test_site_rules(plan):
    with pytest.raises(LoweringError, match="site 2 used twice in user_main"):
        _lower(plan, """
            def k(ctx, s, loc, cmd, out):
                a = ctx.rng.uniform(site=2)
                b = ctx.rng.uniform(site=2)
                return 0
        """)
    with pytest.raises(LoweringError, match="site= must be an int literal"):
        _lower(plan, """
            def k(ctx, s, loc, cmd, out):
                return ctx.rng.uniform()
        """)


def test_reserve_builds_full_vector(plan):
    low = _lower(plan, """
        def k(ctx, s, loc, cmd, out):
            if not out.reserve(records={"ping": 1}, creates={"visit": 1}, timers=1, requests=1):
                return -1
            return 0
    """)
    res = Rec(True)
    ns = _exec(low, _reserve_user_main=res)
    ns["k"](_ctx(), None, None, None, "OUT")
    vec = res.calls[0][1]
    # resources: 5 events, 0 change groups, 2 namespaces, timers, outbox
    assert vec == (0, 1, 0, 0, 0, 0, 1, 1, 1)


def test_mutable_global_and_unknown_out_method_are_rejected(plan):
    with pytest.raises(LoweringError, match="mutable module global 'CACHE'"):
        _lower(plan, """
            CACHE = []
            def k(ctx, s, loc, cmd, out):
                return len(CACHE)
        """)
    with pytest.raises(LoweringError, match="unknown out method 'frobnicate'"):
        _lower(plan, """
            def k(ctx, s, loc, cmd, out):
                out.frobnicate()
                return 0
        """)


def test_payload_and_shard_views(plan):
    low = _lower(plan, """
        def k(ctx, s, cmd, out):
            i = cmd.item_id
            s.on_hand[i] -= 1
            return s.n_item + s.item[i]
    """, proc="bin_desk")
    ns = _exec(low)
    pay = np.zeros((4, 12), np.int64)
    pay[2, 0] = 1
    cmd = (1, 0, 0, 0, 0, pay, 2)
    on_hand = np.array([5, 5, 5, 5], np.int32)
    s = (1, 2, 2, np.array([10, 11, 12, 13], np.int64), on_hand)
    assert ns["k"](_ctx(), s, cmd, None) == 2 + 13
    assert on_hand.tolist() == [5, 5, 5, 4]


def test_lowering_the_real_mini_kernels(plan):
    from pathlib import Path
    src = Path(plan.process("user_main").kernel.module_file).read_text()
    low = lower_module(src, kernel_layouts(plan), {"user_main": "user_main", "bin_desk": "bin_desk"})
    compile(low, "<mini>", "exec")
    assert "_emit_ping(" in low and "_respond_take_ok(" in low and "@kernel" not in low
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --all-packages pytest libs/simkit/tests/test_engine_lower.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'neorisk_simkit.engine.layout'`.

- [ ] **Step 3: Implement**

- `kernel_layouts(plan)`: for each process build a `KernelLayout`. Owner state fields: the owner table's columns in order (index i → tuple index `1+i`); shard: fields from `PartitionDef.state` (`"i32[item]"` → array field), `items_name` = the items table name. Local fields from `KernelSpec.local`. Config fields from the process config dataclass (`dataclasses.fields`, recursive). Reads: for each `reads={"item": item}` entry, every column of the table plus `local_index` (if the table is some shard's items table) and `cumw` (if it has a weight source); `n` is inlined as a constant only for tables whose `source` declares a fixed `n`; every other table (recipe-built, e.g. Task 14's `device`) reads `n` at runtime from the reads tuple (`ctx[10][j_0].shape[0]`). Payload slots: union over every inbound boundary of the kernel — requests (shards), messages (`p.message`, e.g. shard `commit`/`release` commands that read `cmd.quantity`) and responses (owners); a name with two different slot indices → `LoweringError`.
- Resource vector order (shared with Task 8, also exposed as `layout.resource_names(plan) -> list[str]`): `[f"records:{e}" for events] + [f"records:{g}" for change groups] + [f"creates:{ns}" for namespaces] + ["timers", "requests"]`. In the mini plan: 5 + 0 + 2 + 2 = 9.
- Implement with `ast.NodeTransformer`: first pass collects module constants (`Assign` of literals and tuples of literals at module level) and mutable globals; second pass per kernel function (and the helpers it calls, followed transitively by name) rewrites. Track local aliases: `x = ctx.cfg` makes `x` a cfg alias; a parameter named `cfg` in a helper is a cfg alias when every caller passes a cfg alias in that position.
- Output = prelude + module constants + lowered functions, formatted with `ast.unparse`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --all-packages pytest libs/simkit/tests/test_engine_lower.py -v`
Expected: PASS (9 tests).

- [ ] **Step 5: Lint and commit**

Run: `uv run ruff check $(ls -d libs apps examples/ecommerce_s1 benchmarks 2>/dev/null)`
```bash
git add libs/simkit/src/neorisk_simkit/engine libs/simkit/tests/test_engine_lower.py
git commit -m "simkit: lower kernel authoring surface to Numba-compilable code

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---
### Task 7: Command queues and the calendar queue

**Files:**
- Create: `libs/simkit/src/neorisk_simkit/engine/cmdq.py`, `engine/calendar.py`
- Test: `libs/simkit/tests/test_engine_cmdq_calendar.py`

**Interfaces:**
- Consumes: Task 2 `EngineError`, `CapExceeded`; Task 4 `spec.caps.PAYLOAD_W`, `OUTBOX_ROW_BYTES` (the test asserts they agree with `cmdq.PAYLOAD_W`).
- Produces:
  - `cmdq.PAYLOAD_W = 12` (columns 0..6 user payload, 7 `src_g`, 8 `src_gen`, 9 `src_self_id`, 10 `src_action`, 11 reserved); `cmdq.PAY_CONTINUE = -2` (an `n_pay` marker: the node is a continuation and `n_tag` is its cursor).
  - `NodePool(capacity: int, workers: int)` with arrays `time, key, seq, tag (int64), next (int32), kind, proc (int16), pay (int32)`, `free_head int32[W]`, `free_n int64[W]`, `reserve_head int32[1]`, `reserve_n int64[1]`; methods `as_tuple()`, `refill(worker: int, n: int) -> bool`, `splice_all() -> None`, `in_use() -> int`.
  - `PayloadPool(capacity: int, workers: int)` with `rows int64[capacity, PAYLOAD_W]` and the same free-list API.
  - `@njit(cache=True, nogil=True)`: `pack_key(prio, cause) -> int64` (raises `ValueError("priority out of range")` / `ValueError("cause_lamport out of range")`); `q_push(P, w, qhead, g, time, prio, cause, seq, kind, proc, tag, pay) -> int32` (−1 when worker `w` has no free node); `q_peek(P, qhead, g) -> int32` (−1 empty); `q_pop(P, qhead, g) -> int32` (unlinks the head); `q_free(P, w, node)`; `pay_alloc(PA, w) -> int32` (−1 when empty); `pay_free(PA, w, row)`.
  - `Calendar(n_slots: int, origin_us: int, width_us: int, n_buckets: int, capacity: int)` with `as_tuple()`; `@njit`: `cal_push(C, g, t) -> bool` (False when entries are exhausted), `cal_collect(C, next_t, t0, t1, out: int32[:]) -> int` (writes each slot with `t0 <= next_t[g] < t1` once, drops stale entries, keeps valid entries ≥ t1), and Python `Calendar.compact(next_t)` (rebuild from `next_t` of live slots; called when `cal_push` returns False).

- [ ] **Step 1: Write the failing tests**

`libs/simkit/tests/test_engine_cmdq_calendar.py`:
```python
import numpy as np
import pytest

from neorisk_simkit.engine import calendar as cal
from neorisk_simkit.engine import cmdq


def _pool(cap=64, workers=2):
    pool = cmdq.NodePool(cap, workers)
    assert pool.refill(0, cap // 2) and pool.refill(1, cap // 2)
    return pool


def _drain(P, qhead, g, w=0):
    out = []
    while True:
        n = cmdq.q_pop(P, qhead, g)
        if n < 0:
            return out
        out.append((int(P[0][n]), int(P[1][n] >> 56), int(P[1][n] & ((1 << 56) - 1)),
                    int(P[2][n]), int(P[5][n])))
        cmdq.q_free(P, w, n)


def test_pop_order_is_time_priority_cause_seq():
    pool = _pool()
    P, qhead = pool.as_tuple(), np.full(4, -1, np.int32)
    items = [(10, 5, 1, 0, 1), (5, 5, 9, 1, 2), (10, 1, 7, 2, 3), (10, 5, 1, 3, 4),
             (10, 5, 0, 4, 5), (5, 0, 0, 5, 6)]
    for t, prio, cause, seq, kind in [items[i] for i in (3, 0, 5, 2, 1, 4)]:
        assert cmdq.q_push(P, 0, qhead, 2, t, prio, cause, seq, kind, 0, 0, -1) >= 0
    got = _drain(P, qhead, 2)
    assert [x[4] for x in got] == [6, 2, 3, 5, 1, 4]


def test_priority_inversion_same_time():
    pool = _pool()
    P, qhead = pool.as_tuple(), np.full(1, -1, np.int32)
    cmdq.q_push(P, 0, qhead, 0, 100, 5, 1, 0, 1, 0, 0, -1)      # debit, scheduled first
    cmdq.q_push(P, 0, qhead, 0, 100, 1, 3, 1, 2, 0, 0, -1)      # credit, scheduled later
    assert [x[4] for x in _drain(P, qhead, 0)] == [2, 1]


def test_worker_free_lists_and_refill():
    pool = cmdq.NodePool(4, 2)
    P, qhead = pool.as_tuple(), np.full(1, -1, np.int32)
    assert cmdq.q_push(P, 1, qhead, 0, 1, 5, 0, 0, 1, 0, 0, -1) == -1   # worker 1 has nothing
    assert pool.refill(1, 3) and not pool.refill(0, 2)                  # reserve holds 1 node
    for s in range(3):
        assert cmdq.q_push(P, 1, qhead, 0, 1, 5, 0, s, 1, 0, 0, -1) >= 0
    assert cmdq.q_push(P, 1, qhead, 0, 1, 5, 0, 9, 1, 0, 0, -1) == -1
    n = cmdq.q_pop(P, qhead, 0)
    cmdq.q_free(P, 0, n)                                                # freed into worker 0
    pool.splice_all()
    assert pool.in_use() == 2 and pool.reserve_n[0] == 2


def test_pack_key_ranges():
    assert cmdq.pack_key(5, 7) == (5 << 56) | 7
    with pytest.raises(ValueError, match="priority out of range"):
        cmdq.pack_key(64, 0)
    with pytest.raises(ValueError, match="cause_lamport out of range"):
        cmdq.pack_key(1, 1 << 56)


def test_payload_pool():
    pp = cmdq.PayloadPool(3, 1)
    assert pp.refill(0, 3)
    PA = pp.as_tuple()
    rows = [cmdq.pay_alloc(PA, 0) for _ in range(4)]
    assert sorted(rows[:3]) == [0, 1, 2] and rows[3] == -1
    cmdq.pay_free(PA, 0, rows[0])
    assert cmdq.pay_alloc(PA, 0) == rows[0]
    assert pp.rows.shape == (3, cmdq.PAYLOAD_W)


def test_calendar_collects_each_slot_once_and_skips_stale():
    c = cal.Calendar(n_slots=8, origin_us=0, width_us=100, n_buckets=16, capacity=64)
    C = c.as_tuple()
    next_t = np.full(8, np.iinfo(np.int64).max, np.int64)
    for g, t in [(1, 50), (2, 150), (3, 420), (4, 99)]:
        next_t[g] = t
        assert cal.cal_push(C, g, t)
    next_t[2] = 260                       # slot 2 moved later: its first entry is now stale
    cal.cal_push(C, 2, 260)
    out = np.zeros(8, np.int32)
    n = cal.cal_collect(C, next_t, 0, 200, out)
    assert sorted(out[:n].tolist()) == [1, 4]
    n = cal.cal_collect(C, next_t, 200, 400, out)
    assert out[:n].tolist() == [2]
    n = cal.cal_collect(C, next_t, 400, 500, out)
    assert out[:n].tolist() == [3]


def test_calendar_straddling_bucket_keeps_later_entries():
    c = cal.Calendar(n_slots=4, origin_us=0, width_us=100, n_buckets=4, capacity=16)
    C = c.as_tuple()
    next_t = np.array([10, 60, 0, 0], np.int64)
    cal.cal_push(C, 0, 10)
    cal.cal_push(C, 1, 60)
    out = np.zeros(4, np.int32)
    assert out[: cal.cal_collect(C, next_t, 0, 50, out)].tolist() == [0]
    assert out[: cal.cal_collect(C, next_t, 50, 100, out)].tolist() == [1]


def test_calendar_compaction_when_full():
    c = cal.Calendar(n_slots=4, origin_us=0, width_us=10, n_buckets=4, capacity=3)
    C = c.as_tuple()
    never = np.iinfo(np.int64).max
    next_t = np.array([5, 5, never, 5], np.int64)
    assert cal.cal_push(C, 0, 5) and cal.cal_push(C, 1, 5)
    next_t[0] = 7                          # slot 0 moved later: its first entry is now stale
    assert cal.cal_push(C, 0, 7)
    assert not cal.cal_push(C, 3, 5)       # 3 entries (one stale): the entry pool is full
    c.compact(next_t)                      # rebuild drops the stale entry
    C = c.as_tuple()
    assert cal.cal_push(C, 3, 5)           # compaction freed space
    out = np.zeros(4, np.int32)
    n = cal.cal_collect(C, next_t, 0, 10, out)
    assert sorted(out[:n].tolist()) == [0, 1, 3]


def test_caps_agree_with_payload_width():
    from neorisk_simkit.spec import caps
    assert caps.PAYLOAD_W == cmdq.PAYLOAD_W
    assert caps.OUTBOX_ROW_BYTES == 8 * 12 + 8 * cmdq.PAYLOAD_W
```
(`compact` keeps one entry per slot that already had an entry and whose `next_t` is finite, at time `next_t[slot]`; stale entries are dropped, so slot 3 is pushed again by the caller after compaction. The test pins that compaction frees space without losing live entries.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --all-packages pytest libs/simkit/tests/test_engine_cmdq_calendar.py -v`
Expected: FAIL with `ImportError: cannot import name 'calendar'`.

- [ ] **Step 3: Implement**

- `P = (time, key, seq, tag, next, kind, proc, pay, free_head, free_n)`; `q_push` takes the head of `free_head[w]`, fills it, and inserts into slot `g`'s list sorted by `(time, key, seq)` with a linear walk (per-partition lists are short). Ties on all three are impossible because `seq` is unique per receiving partition.
- `NodePool.__init__` links every node into the reserve list; `refill(w, n)` moves `n` nodes from the reserve to worker `w` (False if `reserve_n < n`); `splice_all()` moves every worker list back to the reserve (walk to each list's tail once).
- `Calendar`: entries `(slot int32, time int64, next int32)` in a pool with a free list; buckets `head int32[n_buckets]`; bucket index `min((t - origin) // width, n_buckets - 1)` (times before origin go to bucket 0). `cal_collect` walks every bucket overlapping `[t0, t1)`; for each entry: stale if `next_t[slot] != time` → free; if `t0 <= time < t1` and `stamp[slot] != epoch` → emit, set stamp, free; otherwise (valid but `time >= t1`) keep. `epoch` increments per collect; `stamp int64[n_slots]` lives in the tuple.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --all-packages pytest libs/simkit/tests/test_engine_cmdq_calendar.py -v`
Expected: PASS (9 tests).

- [ ] **Step 5: Lint and commit**

Run: `uv run ruff check $(ls -d libs apps examples/ecommerce_s1 benchmarks 2>/dev/null)`
```bash
git add libs/simkit/src/neorisk_simkit/engine libs/simkit/tests/test_engine_cmdq_calendar.py
git commit -m "simkit: per-partition command queues and calendar queue

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 8: Slabs, generated emitters and the engine build

**Files:**
- Create: `libs/simkit/src/neorisk_simkit/engine/slabs.py`, `engine/codegen.py`, `engine/build.py`
- Modify: `engine/world.py` (Task 4 created it with `HIDDEN_DTYPES`/`hidden_bytes`; this task adds `Hidden` and `allocate_hidden` only), `engine/errors.py` (`EngineError.__str__`)
- Test: `libs/simkit/tests/test_engine_codegen.py`

**Interfaces:**
- Consumes: Task 3 `Plan`, `RunSpec`, `EngineSettings` (frozen dataclasses); Task 4 `engine.world.HIDDEN_DTYPES`, `spec.caps.hidden_bytes`; Task 5 `rng`, `identity`; Task 6 `kernel_layouts`, `lower_module`, `resource_names`; Task 7 `NodePool`, `PayloadPool`, `PAYLOAD_W`, `PAY_CONTINUE`.
- Produces:
  - `world.Hidden` (one attribute per `HIDDEN_DTYPES` row, so `susp_t` and `susp_delta` exist from this task on) and `world.allocate_hidden(plan, run) -> tuple[Hidden, dict[str, int]]` (`slot_base` per partition type). Arrays are allocated by looping over `HIDDEN_DTYPES` (`[G]` for multiplicity 1, `[G, A]` / `[G, N_NS]` otherwise); no hidden array is declared anywhere else, so `G × caps.hidden_bytes(plan)` equals the allocated bytes.
  - `slabs.SlabSet(plan, engine: EngineSettings, worker: int)`: `resources: list[str]` (= `resource_names(plan)`), `cap/cnt/resv int64[R]`, `miss int64[1]` (index of the resource a failed reserve lacked), `req_count int64[1]` (requests issued by the current command), buffers per event / change group (`time, lamport, pid, seq, action` + one array per column + `valid_<col>` uint8 for nullable columns), per namespace (`handle, pid, ordinal, created_at, g` + table columns), outbox (`kind, bnd, time, prio, cause, src_g, src_pid, src_seq, dst, tag, resp_kind, target_action` + `pay int64[cap, PAYLOAD_W]`); `as_tuple(hidden, pool, payload) -> tuple`; `flush() -> StepChunk` (copies filled record/create rows, resets those counters; the outbox is drained separately by routing, or moved aside by `World.run_slots` on a `requests` miss — Task 9); `outbox_view() -> dict[str, np.ndarray]` (copies of the filled outbox rows); `reset_outbox()`. Capacities: `max(1, slab_bytes // row_bytes)` per buffer unless `engine.force_capacity[name]` is set; `timers` capacity is the worker's free node count (dynamic); `requests` = outbox rows. `force_capacity["timers"] = n` caps the per-worker node refill chunk: `World` refills a worker with at most `n` nodes and its free list never holds more than `n` (Task 9); `validate` (Task 4) requires `n ≥` every kernel's declared `max.timers`, so a kernel's reserve can always succeed after a refill.
  - `StepChunk(records: dict[str, dict[str, np.ndarray]], creates: dict[str, dict[str, np.ndarray]])`.
  - Outbox kinds: `OB_REQUEST = 1, OB_MESSAGE = 2, OB_RESPONSE = 3, OB_CREATE = 4`.
  - `codegen.generate_module(plan, *, checked: bool) -> str`: prelude + lowered kernels (with `@njit(cache=True, nogil=True, boundscheck=<checked>)` added) + per-resource constants `R_<NAME>` + `OUT_*`/`HID_*` tuple indices + generated `_reserve_<proc>`, `_emit_<e>`, `_create_<ns>`, `_new_id`, `_timer`, `_request_<b>`, `_send_<b>`, `_respond_<b>_<r>`, `_continue_at`, `_change_<g>` + `dispatch(action, ctx, cmd, world_state, out) -> int` + `RESOURCES = [...]` + `CHECKED = <bool>`. Task 9 adds `run_partitions`; Task 10 adds routing/round drivers.
  - `build.build_engine(plan, *, checked: bool = False) -> types.ModuleType` (D34): writes `gen_<sha256(source)[:16]>.py` into `$NEORISK_JIT_CACHE` (default `~/.cache/neorisk-simkit/jit/`) if absent and imports it by path; returns the module (`module.__file__` identifies it).
  - `layout.make_ctx(t, self_id, pid, g, inst, action, occ, kc, seed, cfg, reads, refs, lamport, flags) -> tuple` (plain tuple builder for tests and the runner).

Generated emitter semantics (every mode):
- `_emit_<e>(out, ctx, t, cols…)`: `t != ctx.t` → `EngineError("records must be emitted at ctx.t")`; row `i = cnt[r]`; `time=t, lamport=ctx.lamport, pid=ctx.pid, seq=rseq[g]` then `rseq[g] += 1`, `action=ctx.action`; nullable columns: `valid = value != std.NULL`; `cnt[r] += 1`. Checked mode: `resv[r] -= 1`, `resv[r] < 0` → `AbiViolation("emit beyond reservation: <e>")`.
- `_create_<ns>(out, ctx, cols…)`: `ordinal = ordn[g, ns]`, `ordn[g, ns] += 1`, `h = make_handle(ns, g, ordinal)`; row `(h, pid, ordinal, created_at=ctx.t, g, cols)`; for owner-table namespaces also append an `OB_CREATE` outbox row (consumes one `requests` unit; `pay[7..10] = (g, gen[g], self_id, action)` as for a request, so admission can name the creating process). Returns `h`.
- `_new_id(out, ctx, ns)` (`p.ids` namespaces, D15): `ordinal = ordn[g, ns]`, `ordn[g, ns] += 1`, `h = make_handle(ns, g, ordinal)`; appends `(handle=h, pid=ctx.pid, ordinal, created_at=ctx.t, g)` to the namespace buffer of `ns` (`cnt[r] += 1` for `r = creates:<ns>`; the namespace has no table columns) and decrements `resv[r]` (checked mode: `resv[r] < 0` → `AbiViolation("new_id beyond reservation: <ns>")`). Returns `h`. The dense remap at seal (Task 11) reads these rows exactly like created rows.
- `_timer(out, ctx, t, kind, prio, tag)`: `t < ctx.t` → `EngineError("timer scheduled before current time in <action name>")`; `q_push(own queue, seq=cseq[g]++, cause=ctx.lamport, proc=ctx.action)`.
- Error messages that name the process: Numba needs constant exception arguments, so a generated helper shared by several processes branches on `ctx.action` (one branch per process that can call it, known from the plan) and raises a constant message per branch, prefixed `<proc>: ` (Review Focus #3: the run fails naming the process and command).
- `_request_<b>(out, ctx, t, shard, tag, payload…)`: `t < ctx.t` → `EngineError("<proc>: request <b> scheduled before current time")`; `shard >= n` or `< 0` → `EngineError("<proc>: request <b> to shard <x> but <partition> has <n>")`, generated per `(proc, b)` branch as `raise EngineError("user_main: request take to shard ", x, " but bin has 4")` (constant strings plus the runtime index; `EngineError.__str__` joins `args` with no separator, see Step 3); outbox row `OB_REQUEST`, `time=t`, `prio=PRIO_MESSAGE`, `cause=ctx.lamport`, `src_seq=cseq[g]++`, payload cols 0.., `pay[7..10] = (g, gen[g], self_id, action)`; `req_count[0] += 1`.
- `_send_<b>`: like a request but `OB_MESSAGE`, `time = t + latency` with latency `sample_us(boundary latency, key_uniform(seed, inst, 30000 + b, ctx.lamport, j, 0), key_uniform(..., j, 1))`, `j` = index of this send within the command; does not touch `req_count`.
- `_respond_<b>_<r>(out, ctx, cmd, payload…)`: `OB_RESPONSE` to `(cmd.pay[7], cmd.pay[8])`, `time = ctx.t + latency` (drawn with key `(seed, inst, 30000 + b, ctx.lamport, j, k)`), `prio=PRIO_MESSAGE`, `cause=ctx.lamport`, `tag=cmd.tag`, `resp_kind` = the requester's `on_response[(b, r)]` command id, `target_action = cmd.pay[10]`.
- `_continue_at(out, ctx, t, cursor)`: `t != ctx.t` → `EngineError`; `q_push(..., prio=PRIO_CONTINUE, kind=<current cmd kind>, tag=cursor, pay=PAY_CONTINUE)`.
- `_change_<g>(out, ctx, s, t, cols…)`: writes each column into the owner state row and appends a history row (resource `records:<g>`).
- `_reserve_<proc>(out, vec)`: for each `r` with `vec[r] > 0`: records/creates need `cap[r] - cnt[r] >= vec[r]`; `timers` needs `free_n[w] >= vec[r]`; `requests` needs outbox room. On failure set `miss[0] = r` and return False; on success `resv[:] = vec` and return True.
- `req_count[0]` counts requests issued by the command being dispatched; `run_partitions` (Task 9) sets it to 0 before every dispatch.

- [ ] **Step 1: Write the failing tests**

`libs/simkit/tests/test_engine_codegen.py`:
```python
import dataclasses

import numpy as np
import pytest

from neorisk_simkit.engine import AbiViolation, EngineError
from neorisk_simkit.engine.build import build_engine
from neorisk_simkit.engine.cmdq import NodePool, PayloadPool
from neorisk_simkit.engine.identity import handle_ns, handle_ordinal, handle_slot, is_provisional
from neorisk_simkit.engine.layout import make_ctx
from neorisk_simkit.engine.slabs import SlabSet
from neorisk_simkit.engine.world import allocate_hidden
from neorisk_simkit.spec.project import load_project, resolve_run

NULL = -(2**63)


@pytest.fixture
def run(fixture_project):
    return resolve_run(load_project(fixture_project("mini")), "sample", [])


def _setup(run, checked=False, force=None):
    if force:
        run = dataclasses.replace(run, engine=dataclasses.replace(run.engine, force_capacity=force))
    gen = build_engine(run.plan, checked=checked)
    hidden, _ = allocate_hidden(run.plan, run)
    pool, pay = NodePool(1000, 1), PayloadPool(100, 1)
    pool.refill(0, 500)
    pay.refill(0, 50)
    slab = SlabSet(run.plan, run.engine, worker=0)
    return gen, hidden, pool, slab, slab.as_tuple(hidden, pool, pay)


def _ctx(g=3, t=1_000, lamport=4, pid=(1 << 56) | 3, action=0):
    return make_ctx(t, 3, pid, g, 11, action, 0, np.zeros(33, np.int64), 7, (), (), (), lamport, 0)


def test_build_is_cached_by_content(run):
    a, b = build_engine(run.plan), build_engine(run.plan)
    assert a.__file__ == b.__file__ and a.RESOURCES == [
        "records:user_joined", "records:ping", "records:took", "records:item_taken",
        "records:take_failed", "creates:note", "creates:visit", "timers", "requests"]
    assert build_engine(run.plan, checked=True).__file__ != a.__file__


def test_reserve_and_emit_until_slab_is_full(run):
    gen, hidden, _, slab, out = _setup(run, force={"records:ping": 2})
    vec = np.array([0, 1, 0, 0, 0, 0, 0, 0, 0], np.int64)
    ctx = _ctx()
    for n in range(2):
        assert gen._reserve_user_main(out, vec)
        gen._emit_ping(out, ctx, 1_000, 3, 77, n, NULL)
    assert not gen._reserve_user_main(out, vec)
    assert slab.miss[0] == slab.resources.index("records:ping")
    chunk = slab.flush()
    ping = chunk.records["ping"]
    assert ping["seq"].tolist() == [0, 1] and ping["lamport"].tolist() == [4, 4]
    assert ping["n"].tolist() == [0, 1] and ping["valid_note_id"].tolist() == [0, 0]
    assert ping["pid"].tolist() == [(1 << 56) | 3] * 2 and ping["action"].tolist() == [0, 0]
    assert hidden.rseq[3] == 2
    assert gen._reserve_user_main(out, vec)          # flush made room again


def test_checked_mode_catches_emit_without_reservation(run):
    gen, _, _, _, out = _setup(run, checked=True)
    with pytest.raises(AbiViolation, match="emit beyond reservation: ping"):
        gen._emit_ping(out, _ctx(), 1_000, 3, 77, 0, NULL)


def test_emit_time_must_equal_ctx_t(run):
    gen, _, _, _, out = _setup(run)
    gen._reserve_user_main(out, np.array([0, 1, 0, 0, 0, 0, 0, 0, 0], np.int64))
    with pytest.raises(EngineError, match="records must be emitted at ctx.t"):
        gen._emit_ping(out, _ctx(), 999, 3, 77, 0, NULL)


def test_create_and_new_id_return_provisional_handles(run):
    gen, hidden, _, slab, out = _setup(run)
    gen._reserve_user_main(out, np.array([0, 0, 0, 0, 0, 1, 2, 0, 0], np.int64))
    h1 = gen._create_note(out, _ctx(), 5)
    v1, v2 = gen._new_id(out, _ctx(), 1), gen._new_id(out, _ctx(), 1)
    assert is_provisional(h1) and handle_ns(h1) == 0 and handle_slot(h1) == 3
    assert [handle_ordinal(v) for v in (v1, v2)] == [0, 1] and handle_ns(v1) == 1
    chunk = slab.flush()
    assert chunk.creates["note"]["size"].tolist() == [5]
    assert chunk.creates["visit"]["ordinal"].tolist() == [0, 1]


def test_timer_rules(run):
    gen, hidden, pool, _, out = _setup(run)
    gen._reserve_user_main(out, np.array([0, 0, 0, 0, 0, 0, 0, 1, 0], np.int64))
    gen._timer(out, _ctx(), 5_000, 1, 5, 0)
    head = hidden.qhead[3]
    assert head >= 0 and pool.time[head] == 5_000 and pool.key[head] == (5 << 56) | 4
    assert hidden.cseq[3] == 1
    with pytest.raises(EngineError, match="timer scheduled before current time"):
        gen._timer(out, _ctx(), 999, 1, 5, 0)


def test_request_bounds_and_outbox_row(run):
    gen, hidden, _, slab, out = _setup(run)
    gen._reserve_user_main(out, np.array([0, 0, 0, 0, 0, 0, 0, 0, 1], np.int64))
    gen._request_take(out, _ctx(), 1_000, 2, 99, 17)
    ob = slab.outbox_view()
    assert ob["kind"].tolist() == [1] and ob["dst"].tolist() == [2] and ob["tag"].tolist() == [99]
    assert ob["pay"][0, 0] == 17 and ob["pay"][0, 7] == 3 and slab.req_count[0] == 1
    with pytest.raises(EngineError, match="user_main: request take to shard 9 but bin has 4"):
        gen._request_take(out, _ctx(), 1_000, 9, 99, 17)


def test_hidden_arrays_match_the_cap_table(run):
    from neorisk_simkit.engine.world import HIDDEN_DTYPES
    from neorisk_simkit.spec.caps import hidden_bytes
    hidden, slot_base = allocate_hidden(run.plan, run)
    G = len(hidden.pid)
    assert G == 200 + 4 and slot_base == {"user": 0, "bin": 200}
    assert sum(getattr(hidden, n).nbytes for n, _, _ in HIDDEN_DTYPES) == G * hidden_bytes(run.plan)
    assert hidden.susp_t.dtype == np.int64 and hidden.susp_delta.dtype == np.int64
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --all-packages pytest libs/simkit/tests/test_engine_codegen.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'neorisk_simkit.engine.build'`.

- [ ] **Step 3: Implement**

- Generate code as text with small template functions in `codegen.py` (one function per helper family). Every generated function is decorated `@njit(cache=True, nogil=True, boundscheck=CHECKED)`. Emitters index tuples with module-level integer constants (`OUT_CNT = 0`, `OUT_CAP = 1`, `OUT_RESV = 2`, `OUT_MISS = 3`, `OUT_REQC = 4`, `OUT_HID = 5`, `OUT_POOL = 6`, `OUT_PAY = 7`, `OUT_W = 8`, then buffers in resource order, then the outbox, then the latency table `float64[n_boundaries, 4]`, shard sizes `int64[n_boundaries]`, `seed`).
- `HID` sub-tuple order: `(rseq, cseq, ordn, gen, self_id, pid, qhead)`.
- Exceptions raised in generated code use the classes from `neorisk_simkit.engine.errors` with constant messages (Numba requires compile-time constant arguments; build the message text into the generated source per event/boundary name).
- `build_engine`: `source = generate_module(plan, checked=checked)`; `digest = sha256(source.encode()).hexdigest()[:16]`; path = cache dir / f"gen_{digest}.py"; write atomically (`.tmp` + `os.replace`) if missing; import with `importlib.util.spec_from_file_location(f"neorisk_gen_{digest}", path)`; memoize in a module dict.
- `allocate_hidden(plan, run)`: `G = Σ owners max_live + Σ shards n`; owner slot ranges first (in plan order) then shards; allocates every array from `HIDDEN_DTYPES` (fill values: `qhead = -1`, `retire_at = susp_t = I64_MAX`, the rest 0); returns `(hidden, slot_base)`.
- `EngineError.__str__` (Task 2's class, in `engine/errors.py`) renders `"".join(str(a) for a in self.args)` so generated raises with constant-plus-scalar arguments read as one sentence (a single-argument `EngineError("text")` is unchanged).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --all-packages pytest libs/simkit/tests/test_engine_codegen.py -v`
Expected: PASS (8 tests). The first run compiles (tens of seconds); a second run must be faster (warm cache) — check with `time`.

- [ ] **Step 5: Lint and commit**

Run: `uv run ruff check $(ls -d libs apps examples/ecommerce_s1 benchmarks 2>/dev/null)`
```bash
git add libs/simkit/src/neorisk_simkit/engine libs/simkit/tests/test_engine_codegen.py
git commit -m "simkit: slabs, generated typed emitters and cached engine build

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 9: World building and the partition executor

**Files:**
- Modify: `libs/simkit/src/neorisk_simkit/engine/world.py` (full `World`), `engine/codegen.py` (generate `run_partitions` and per-type snapshot helpers)
- Create fixture: `libs/simkit/tests/fixtures/bad_abi/{datagen.toml,specs/pack.py,specs/kernels.py}`
- Test: `libs/simkit/tests/test_engine_execute.py`

**Interfaces:**
- Consumes: Tasks 3–8.
- Produces:
  - `World.build(run: RunSpec, *, threads: int, checked: bool = False) -> World` — builds the engine module, read tables (sources), refs CSR (from population `refs` recipes), population schedule (initial owners at `start − warmup`, arrivals drawn from `arrivals` with keyed uniforms, ordinal = rank by `(arrival time, draw index)`), owner state arrays per type, local arrays per process, shard state (items CSR by the shard key column; `init` dict of `Dist` or explicit lists, or a `std` recipe object with `.init(...)`), per-process `cfg` tuples, `Hidden`, `NodePool`, `PayloadPool`, `Calendar`, one `SlabSet` per worker.
  - `World.admit_population(t0, t1) -> np.ndarray` (global slots admitted; queues `START` at the arrival time with `PRIO_MESSAGE` for every process with `start=on_created(table)`; raises `CapExceeded("live_partition_state", …)` when the type has no free slot).
  - `World.init_shards() -> None` (queues the first `START` of each periodic process, D26).
  - `World.run_slots(worker: int, slots: np.ndarray, limit_t: int, *, owners: bool) -> None` — calls the generated `run_partitions` until it returns `DONE`, handling `NEED_SWAP` and `NEED_NODES`:
    - `NEED_SWAP` with `slab.miss[0]` = a `records:*`/`creates:*` resource: flush that worker's slab into `World.chunks[worker]`.
    - `NEED_SWAP` with `slab.miss[0]` = `requests` (the outbox is full): append `slab.outbox_view()` to `World.pending_outbox[worker]` and call `slab.reset_outbox()`, then re-invoke. Routing (Task 10) consumes `pending_outbox` plus the live outboxes and sorts by key, so moving rows aside changes neither RNG draws nor order, and a full outbox can never livelock.
    - `NEED_NODES` (`timers` or payload free list empty): `pool.refill(worker, chunk)` where `chunk = engine.force_capacity.get("timers", <default chunk>) - free_n[worker]` when `"timers"` is forced (the worker free list never holds more than `force_capacity["timers"]` nodes; Task 8 semantics), else the default chunk; if the reserve is empty → `CapExceeded("timer_heaps", …)`.
  - `World.slabs: list[SlabSet]` (one per worker; tests read `w.slabs[0].outbox_view()`), `World.pending_outbox: list[list[dict[str, np.ndarray]]]` (per worker, outbox snapshots moved aside this round; emptied by routing).
  - Generated `run_partitions(W, out, worker, slots, start, limit_t, owners) -> (status, index)`. Per slot `g`: loop `node = q_peek`; stop when `node < 0` or `time >= limit_t`, or (owners) `pending[g] > 0`; build `cmd`; `lamport = max(clock[g], cause) + 1`; reset `kc[0] = 0` and `req_count[0] = 0` (before every dispatch, including a re-invocation after `RETRY`); `rc = dispatch(...)`. `COMMIT`: `clock[g] = lamport`, `occ[g, a] += 1`, pop+free the node (free its payload row), if `req_count > 0`: `pending[g] += req_count`, `susp_t[g] = time`, stop this slot. `rc >= 1` (reject): `occ[g, a] += 1`, pop+free, count `rejects[a] += 1`. `RETRY`: leave the node, return `(NEED_SWAP or NEED_NODES by miss[0], index)`. After the loop, owners with an empty queue and `pending == 0` and `retire_when_idle` get `retire_at[g] = last time` (freed at seal). Periodic `START` nodes with cursor 0 enqueue the next occurrence before dispatch (D26).
  - Checked mode (generated only when `CHECKED`): before dispatch copy the state row, local row, `cnt[:]`, `cseq[g]`, `ordn[g]`; after `RETRY` or reject, any difference → `AbiViolation("process <name> wrote before returning reject|RETRY")`.
  - `World.chunks: list[list[StepChunk]]`, `World.flush_all() -> None` (flushes every worker slab into its `chunks` list), `World.take_chunks() -> list[StepChunk]` (returns and clears them; used by seal), `World.stats` (`rejects` per process name, `retries`, `late_messages`, `continuations` = continuation nodes executed).

- [ ] **Step 1: Create the `bad_abi` fixture**

`fixtures/bad_abi/datagen.toml`: copy of mini's with `name = "bad_abi"`, `warmup = "0s"`, `span = "1h"`, `[profiles.sample] set = { mode = 0 }`.

`fixtures/bad_abi/specs/pack.py`:
```python
"""Kernels that break the action interface on purpose; checked mode must catch each."""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack
from neorisk_simkit.spec.types import i32, ref

from . import kernels as k

PACK = "bad_abi"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Config:
    mode: int = 0          # 0 write-then-reject, 1 emit without reserve, 2 past timer, 3 write-then-retry


def define(p: Pack, cfg: Config) -> None:
    acct = p.table("acct", key="acct_id", mutable=True, cols={"n": i32()})
    p.owner("acct", table=acct, max_live=3)
    p.population(acct, n=3, initial=1.0)
    p.event("e", owner="acct", cols={"acct_id": ref("acct")})
    p.process("bad", owner="acct", kernel=k.bad, config=cfg, start=p.on_created("acct"),
              commands=(0,))
```

`fixtures/bad_abi/specs/kernels.py`:
```python
from neorisk_simkit.engine import COMMIT, RETRY, Res, kernel, reject


@kernel(state="acct", commands=(0,), max=Res(records={"e": 1}, timers=1))
def bad(ctx, s, cmd, out):
    mode = ctx.cfg.mode
    if mode == 0:
        s.n = 1
        return reject(1)
    if mode == 1:
        out.emit_e(ctx.t, acct_id=ctx.self_id)
        return COMMIT
    if mode == 2:
        if not out.reserve(timers=1):
            return RETRY
        out.timer(ctx.t - 1, 0)
        return COMMIT
    if not out.reserve(records={"e": 1}):
        return RETRY
    s.n = 2
    return RETRY
```

Add `import numpy as np` to the top import block of `libs/simkit/tests/conftest.py` (after `import dataclasses`; an import below the existing definitions fails ruff E402), and append this plain helper, shared by engine tests:
```python
def records_of(world, table):
    """All records of one event table held by a World, in canonical order (flushes slabs)."""
    world.flush_all()
    parts = [c.records[table] for chunks in world.chunks for c in chunks
             if table in c.records and len(c.records[table]["time"])]
    if not parts:
        return {"time": np.array([], np.int64)}
    cols = {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}
    order = np.lexsort((cols["seq"], cols["pid"], cols["lamport"], cols["time"]))
    return {k: v[order] for k, v in cols.items()}
```

- [ ] **Step 2: Write the failing tests**

`libs/simkit/tests/test_engine_execute.py`:
```python
import numpy as np
import pytest

from conftest import make_run
from conftest import records_of as _records
from neorisk_simkit.engine import AbiViolation, EngineError
from neorisk_simkit.engine.world import World

H = 3_600_000_000


def _world(name="mini", overrides=(), checked=False, force=None, threads=1):
    run = make_run(name, overrides, **({"force_capacity": force} if force else {}))
    return run, World.build(run, threads=threads, checked=checked)


def test_population_admission():
    run, w = _world()
    t0 = run.start_us - run.warmup_us
    slots = w.admit_population(t0, t0 + 1)
    assert len(slots) == 100                                  # initial = 0.5 of 200
    assert (w.hidden.alive[slots] == 1).all() and (w.hidden.qhead[slots] >= 0).all()
    later = w.admit_population(t0 + 1, run.start_us + run.span_us)
    assert len(later) == 100 and len(np.intersect1d(slots, later)) == 0


def test_owner_run_assigns_lamport_and_seq():
    run, w = _world(overrides=["behavior.take_p=0.0"])
    t0 = run.start_us - run.warmup_us
    slots = w.admit_population(t0, t0 + 1)
    w.run_slots(0, slots, t0 + 6 * H, owners=True)
    joined = _records(w, "user_joined")
    assert len(joined["time"]) == 100 and (joined["time"] == t0).all()
    assert (joined["lamport"] == 1).all() and (joined["seq"] == 0).all()
    ping = _records(w, "ping")
    for pid in np.unique(ping["pid"]):
        mine = ping["pid"] == pid
        assert (np.diff(ping["lamport"][mine]) > 0).all()
        assert ping["seq"][mine].tolist() == list(range(1, mine.sum() + 1))
    assert (ping["time"] < t0 + 6 * H).all()


def test_reject_advances_occurrence_and_retires():
    run, w = _world(overrides=["behavior.max_pings=1", "behavior.take_p=0.0"])
    t0 = run.start_us - run.warmup_us
    slots = w.admit_population(t0, t0 + 1)
    w.run_slots(0, slots, run.start_us + run.span_us, owners=True)
    assert w.stats["rejects"]["user_main"] == 100                       # one reject per user
    assert (w.hidden.occ[slots, 0] == 3).all()                # START, ping, rejected ping
    assert (w.hidden.retire_at[slots] < np.iinfo(np.int64).max).all()


def test_retry_with_tiny_slabs_gives_identical_records():
    over = ["behavior.take_p=0.0"]
    run, big = _world(overrides=over)
    _, small = _world(overrides=over, force={"records:ping": 1, "timers": 1})
    t0 = run.start_us - run.warmup_us
    for w in (big, small):
        w.run_slots(0, w.admit_population(t0, t0 + 1), t0 + 12 * H, owners=True)
    a, b = _records(big, "ping"), _records(small, "ping")
    assert all(np.array_equal(a[k], b[k]) for k in a)
    assert small.stats["retries"] > big.stats["retries"]


def test_request_suspends_owner():
    run, w = _world(overrides=["behavior.take_p=1.0"])
    t0 = run.start_us - run.warmup_us
    slots = w.admit_population(t0, t0 + 1)
    w.run_slots(0, slots, t0 + 24 * H, owners=True)
    assert (w.hidden.pending[slots] == 1).all()               # every user waits for one answer
    ob = w.slabs[0].outbox_view()
    assert len(ob["kind"]) == 100 and (ob["kind"] == 1).all()


def test_full_outbox_is_moved_aside_instead_of_livelocking():
    run, w = _world(overrides=["behavior.take_p=1.0"], force={"requests": 1})
    t0 = run.start_us - run.warmup_us
    slots = w.admit_population(t0, t0 + 1)
    w.run_slots(0, slots, t0 + 24 * H, owners=True)
    assert (w.hidden.pending[slots] == 1).all()
    moved = sum(len(ob["kind"]) for ob in w.pending_outbox[0])
    assert moved + len(w.slabs[0].outbox_view()["kind"]) == 100


@pytest.mark.parametrize("mode,exc,msg", [
    (0, AbiViolation, "wrote before returning reject"),
    (1, AbiViolation, "emit beyond reservation: e"),
    (2, EngineError, "timer scheduled before current time"),
    (3, AbiViolation, "wrote before returning RETRY"),
])
def test_checked_mode_catches_abi_violations(mode, exc, msg):
    run, w = _world("bad_abi", overrides=[f"mode={mode}"], checked=True)
    slots = w.admit_population(run.start_us, run.start_us + 1)
    with pytest.raises(exc, match=msg):
        w.run_slots(0, slots, run.start_us + H, owners=True)


def test_unchecked_mode_still_rejects_time_travel():
    run, w = _world("bad_abi", overrides=["mode=2"])
    slots = w.admit_population(run.start_us, run.start_us + 1)
    with pytest.raises(EngineError, match="timer scheduled before current time"):
        w.run_slots(0, slots, run.start_us + H, owners=True)
```
(Mode 3 would loop forever without checked mode; the unchecked runner caps consecutive retries of one command at 8 and raises `EngineError("command retried 8 times without progress")`, which also protects against kernels whose declared max exceeds the slab.)

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run --all-packages pytest libs/simkit/tests/test_engine_execute.py -v`
Expected: FAIL with `ImportError: cannot import name 'World'`.

- [ ] **Step 4: Implement**

- `cmd` tuple: `(kind, tag_or_0, time, cursor_or_0, sender_self_id, pay_rows, pay_row)` where `pay_row = n_pay` (or a dummy row index 0 of a 1-row zero array when `n_pay < 0`).
- `reads`/`refs`/`cfg` tuples are built once per process in `World.build` and passed to the generated runner as a per-action tuple-of-tuples generated by codegen (`ACTION_ARGS` is assembled in Python and passed as one argument).
- RNG instance keys: population owner `inst = mix(name_key(table), ordinal)`; shard `mix(name_key(partition), index)`; created owner `mix(creator inst, lamport, ordinal)` (Task 10).
- `pid`: population owner `ptype_code << 56 | ordinal`; shard `ptype_code << 56 | index` (D12).
- Initial values: state and local fields of kind `ref` (and every nullable state column) start at `std.NULL`; other fields start at 0; population `attrs` overwrite their columns.
- Retirement bookkeeping only marks `retire_at`; Task 11 frees the slot at seal (bumps `gen`, sets `alive = 0`, clears queues).

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run --all-packages pytest libs/simkit/tests/test_engine_execute.py -v`
Expected: PASS (11 tests).

- [ ] **Step 6: Lint and commit**

Run: `uv run ruff check $(ls -d libs apps examples/ecommerce_s1 benchmarks 2>/dev/null)`
```bash
git add libs/simkit/src/neorisk_simkit/engine libs/simkit/tests/conftest.py libs/simkit/tests/fixtures/bad_abi libs/simkit/tests/test_engine_execute.py
git commit -m "simkit: world building and the partition executor with ABI checks

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 10: Rounds, shards, routing and ordering tests

**Files:**
- Create: `libs/simkit/src/neorisk_simkit/engine/route.py`, `engine/rounds.py`
- Modify: `engine/codegen.py` (generated `drain_small_rounds`), `engine/world.py` (creation admission)
- Create fixture: `libs/simkit/tests/fixtures/ordering/{datagen.toml,specs/pack.py,specs/kernels.py}`
- Test: `libs/simkit/tests/test_engine_rounds.py`

**Interfaces:**
- Consumes: Tasks 7–9.
- Produces:
  - `route.safe_horizon(step_end: int, susp_t: np.ndarray, susp_delta: np.ndarray, create_t: np.ndarray) -> int` (D5).
  - `@njit route_outbox(...)`: merges every worker's outbox rows — the live outbox of each `World.slabs[w]` plus every snapshot in `World.pending_outbox[w]` (rows moved aside on a full outbox, Task 9), which it empties together with `reset_outbox()` — sorts them by `(time, prio, cause, src_pid, src_seq)`, and delivers: `OB_REQUEST` → shard queue at the request time (receiver `cseq`); `OB_MESSAGE` → destination queue at its delivery time; `OB_RESPONSE` → owner queue if `gen[dst] == src_gen` and `alive`, then `pending[dst] -= 1`; otherwise `late_messages += 1`; `OB_CREATE` → pending admissions list. Messages counted per step against `max_messages_per_step` (`CapExceeded("requests_and_inboxes", …)`). Payload rows move with the command (allocated from the routing worker's payload list).
  - `World.admit_created(limit_t)`: allocates slots for pending creations (`CapExceeded("max_admissions_per_step", limit, attempted, process=<creating process name>)` beyond `budget.max_admissions_per_step` — the message ends with `in process <name>`, the process whose `create` produced the first admission over the cap, looked up from the `OB_CREATE` row's `src_action` (payload column 10); `CapExceeded("live_partition_state", …)` without a free slot), copies the create row into the new owner's state, `self_id = handle`, `pid = handle` (provisional; D12), `inst = mix(creator inst, lamport, ordinal)`, queues `START` at the creation time.
  - `rounds.RoundStats(rounds: int, owners_run: list[int], shard_cmds: list[int], compiled_rounds: int)`.
  - `rounds.run_step(world, t0: int, t1: int) -> RoundStats`: admit population arrivals in `[t0, t1)`; runnable = calendar collect ∪ admitted; loop { owner phase (thread pool when `len(runnable) >= parallel_min_partitions`, else inline); route; `H = safe_horizon(...)`; shard phase: every shard with a queued command `< H` runs to `H` (thread pool if many, inline otherwise); route; admit creations; runnable = owners whose `pending` dropped to 0 with head `< t1` ∪ admitted } until closure (no owner runnable below `t1`, no shard command below `t1`, no pending creation). Push calendar entries for every owner touched. Small rounds after the first go through the generated `drain_small_rounds`, which repeats the same steps in compiled code until a round is large or a slab/pool needs Python (D4).
  - `World.touched` (global slots touched this step: ran, received a command, or were created).

- [ ] **Step 1: Create the `ordering` fixture**

`fixtures/ordering/datagen.toml`: copy of mini's with `name = "ordering"`, `start = "2026-03-01T00:00:00Z"`, `warmup = "0s"`, `span = "6h"`, `[engine] step = "6h"`, `parallel_min_partitions = 1`, and `[profiles.sample] set = {}`.

`fixtures/ordering/specs/pack.py`:
```python
"""Priority inversion (credit before debit at one instant) and equal-key ordering."""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, dist
from neorisk_simkit.spec.types import amount, i32, ref

from . import kernels as k

PACK = "ordering"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Config:
    accts: int = 2


def define(p: Pack, cfg: Config) -> None:
    acct = p.table("acct", key="acct_id", mutable=True, cols={"balance": amount(asset="USD")})
    p.owner("acct", table=acct, max_live=cfg.accts)
    p.population(acct, n=cfg.accts, initial=1.0)
    ledger = p.shard("ledger", key="ledger", n=1, items=None, state={})
    note = p.request("note", frm="acct", to=ledger, payload={"v": i32()}, responses=("ack",),
                     latency=dist.constant(ms=100))
    p.event("opened", owner="acct", cols={"acct_id": ref("acct")})
    p.event("credited", owner="acct", cols={"acct_id": ref("acct"),
                                            "balance_after": amount(asset="USD")})
    p.event("debited", owner="acct", cols={"acct_id": ref("acct"),
                                           "balance_after": amount(asset="USD")})
    p.event("noted", shard="ledger", cols={"v": i32()})
    p.process("acct_main", owner="acct", kernel=k.acct_main, config=cfg,
              start=p.on_created("acct"), requests={"note": note},
              on_response={("note", "ack"): k.R_ACK}, commands=k.ACCT_COMMANDS)
    p.process("ledger_desk", shard=ledger, kernel=k.ledger_desk, on_request={"note": k.C_NOTE})
```

`fixtures/ordering/specs/kernels.py`:
```python
from neorisk_simkit import std
from neorisk_simkit.engine import (
    COMMIT, PRIO_MESSAGE, PRIO_TIMER, RETRY, START, Res, kernel, reject,
)

C_PREP, C_CREDIT, C_DEBIT, R_ACK = 1, 2, 3, 4
ACCT_COMMANDS = (START, C_PREP, C_CREDIT, C_DEBIT, R_ACK)
C_NOTE = 1
HOUR = 3_600_000_000
REJ_FUNDS = 1


@kernel(state="acct", commands=ACCT_COMMANDS,
        max=Res(records={"opened": 1, "credited": 1, "debited": 1}, timers=2, requests=1))
def acct_main(ctx, s, cmd, out):
    if cmd.kind == START:
        if not out.reserve(records={"opened": 1}, timers=2, requests=1):
            return RETRY
        out.emit_opened(ctx.t, acct_id=ctx.self_id)
        out.timer(ctx.t + HOUR, C_DEBIT, prio=PRIO_TIMER)          # low priority, scheduled first
        out.timer(ctx.t + 1_000_000, C_PREP, prio=PRIO_TIMER)
        out.request_note(ctx.t, shard=0, tag=0, v=ctx.self_id)     # equal keys across accounts
        return COMMIT
    if cmd.kind == C_PREP:
        if not out.reserve(timers=1):
            return RETRY
        out.timer(ctx.t - 1_000_000 + HOUR, C_CREDIT, prio=PRIO_MESSAGE)   # same instant, higher
        return COMMIT
    if cmd.kind == C_CREDIT:
        if not out.reserve(records={"credited": 1}):
            return RETRY
        s.balance = std.checked_add(s.balance, 100)
        out.emit_credited(ctx.t, acct_id=ctx.self_id, balance_after=s.balance)
        return COMMIT
    if cmd.kind == C_DEBIT:
        if s.balance < 100:
            return reject(REJ_FUNDS)
        if not out.reserve(records={"debited": 1}):
            return RETRY
        s.balance = std.checked_sub(s.balance, 100)
        out.emit_debited(ctx.t, acct_id=ctx.self_id, balance_after=s.balance)
        return COMMIT
    return COMMIT                                                   # R_ACK: nothing to record


@kernel(state="ledger", commands=(C_NOTE,), max=Res(records={"noted": 1}, requests=1))
def ledger_desk(ctx, s, cmd, out):
    if not out.reserve(records={"noted": 1}, requests=1):
        return RETRY
    out.emit_noted(ctx.t, v=cmd.v)
    out.respond(cmd, "ack")
    return COMMIT
```
(A shard with `items=None` has no per-item state; Task 3's `p.shard` API and `test_spec_pack.py` already cover it.)

- [ ] **Step 2: Write the failing tests**

`libs/simkit/tests/test_engine_rounds.py`:
```python
import numpy as np
import pytest

from conftest import make_run, records_of
from neorisk_simkit.engine import CapExceeded
from neorisk_simkit.engine.rounds import run_step
from neorisk_simkit.engine.route import safe_horizon
from neorisk_simkit.engine.world import World

H = 3_600_000_000


def _step(name, overrides=(), threads=1, engine=None):
    run = make_run(name, overrides, **(engine or {}))
    w = World.build(run, threads=threads)
    w.init_shards()
    t0 = run.start_us - run.warmup_us
    stats = run_step(w, t0, t0 + run.engine.step_us)
    return run, w, stats


def _rows(w, table):
    return records_of(w, table)


def test_safe_horizon():
    inf = np.iinfo(np.int64).max
    assert safe_horizon(1000, np.array([], np.int64), np.array([], np.int64),
                        np.array([], np.int64)) == 1000
    assert safe_horizon(1000, np.array([100, 50], np.int64), np.array([200, 300], np.int64),
                        np.array([], np.int64)) == 300
    assert safe_horizon(1000, np.array([100], np.int64), np.array([200], np.int64),
                        np.array([120], np.int64)) == 120
    assert safe_horizon(250, np.array([100], np.int64), np.array([200], np.int64),
                        np.array([inf], np.int64)) == 250


def test_mini_step_closes_with_responses_after_delta():
    run, w, stats = _step("mini", ["behavior.take_p=1.0"])
    t1 = run.start_us - run.warmup_us + run.engine.step_us
    taken = np.concatenate([_rows(w, "item_taken")["time"], _rows(w, "take_failed")["time"]])
    expected = sorted(int(x) + 200_000 for x in taken if x + 200_000 < t1)
    took = _rows(w, "took")
    assert len(expected) > 0 and expected == sorted(took["time"].tolist())
    assert w.next_command_time(owners=False) >= t1
    assert stats.rounds >= 2


def test_priority_inversion_credit_runs_before_debit():
    _, w, _ = _step("ordering")
    cr, de = _rows(w, "credited"), _rows(w, "debited")
    assert len(cr["time"]) == 2 and len(de["time"]) == 2
    assert (cr["time"] == de["time"]).all()
    assert (cr["lamport"] < de["lamport"]).all()
    assert de["balance_after"].tolist() == [0, 0]
    assert w.stats["rejects"].get("acct_main", 0) == 0


@pytest.mark.parametrize("threads", [1, 4])
def test_equal_keys_order_by_partition_id(threads):
    _, w, _ = _step("ordering", threads=threads)
    opened = _rows(w, "opened")
    assert (opened["lamport"] == 1).all() and opened["pid"].tolist() == sorted(opened["pid"])
    noted = _rows(w, "noted")
    assert noted["v"].tolist() == [0, 1]                 # shard handled acct 0 first
    assert noted["lamport"].tolist() == [2, 3]


def test_threads_do_not_change_mini_records():
    a = _step("mini", ["behavior.take_p=0.5"], threads=1)[1]
    b = _step("mini", ["behavior.take_p=0.5"], threads=4,
              engine={"parallel_min_partitions": 1})[1]
    for table in ("ping", "took", "item_taken"):
        ra, rb = _rows(a, table), _rows(b, table)
        assert all(np.array_equal(ra[k], rb[k]) for k in ra)


def test_late_response_to_retired_slot_is_dropped():
    run, w, _ = _step("mini", ["behavior.take_p=1.0"])
    assert w.route_stale_response_for_test() == 1          # bumps gen of a waiting slot, routes
    assert w.stats["late_messages"] == 1


def test_message_cap():
    with pytest.raises(CapExceeded, match="requests_and_inboxes"):
        _step("mini", ["behavior.take_p=1.0"],
              engine={"max_messages_per_step": 1})
```
`World.route_stale_response_for_test()` is a small test hook: pick one owner with `pending > 0` whose request was answered in the outbox of a fresh shard run, bump its `gen` before routing, route, and return the number of dropped responses. Keep it in `world.py`, prefixed `_for_test` and documented as such.

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run --all-packages pytest libs/simkit/tests/test_engine_rounds.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'neorisk_simkit.engine.rounds'`.

- [ ] **Step 4: Implement**

- `safe_horizon`: `h = step_end`; for each suspended owner `h = min(h, susp_t + delta)` where `delta` is the δ of the boundary its oldest outstanding request used; for each pending creation `h = min(h, t_create)`.
- Owner phase: split the runnable slots into `threads` contiguous chunks (sorted by slot for reproducible scheduling), run each with `World.run_slots(worker, chunk, t1, owners=True)` in a `ThreadPoolExecutor`; the generated functions release the GIL.
- Shard phase: shards with a head `< H` run with `limit_t = H` (shards never suspend).
- `World.next_command_time(owners: bool) -> int`: min head time over live owners (or shards).
- Track `susp_delta[g]` at suspension from the boundary of the request (minimum δ over the requests of that commit). `susp_t`/`susp_delta` are hidden arrays declared in Task 4's `HIDDEN_DTYPES` and allocated by Task 8; this task adds no array.
- A request to a shard index ≥ n (or < 0) fails in the generated `_request_<b>` (Task 8) with `EngineError("<proc>: request <b> to shard <x> but <partition> has <n>")`, naming the process and the command (Review Focus #3).
- Round loop must terminate: each round either runs an owner, processes a shard command `< H`, or admits a creation; assert progress and raise `EngineError("no progress in round <n>")` otherwise.
- Per-step counters: `rounds`, `owners_run` and `shard_cmds` per round (lists), `compiled_rounds`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run --all-packages pytest libs/simkit/tests/test_engine_rounds.py libs/simkit/tests/test_engine_execute.py -v`
Expected: PASS.

- [ ] **Step 6: Lint and commit**

Run: `uv run ruff check $(ls -d libs apps examples/ecommerce_s1 benchmarks 2>/dev/null)`
```bash
git add libs/simkit/src/neorisk_simkit/engine libs/simkit/tests/fixtures/ordering libs/simkit/tests/test_engine_rounds.py
git commit -m "simkit: rounds with safe horizon, shard processing and routing

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 11: Frontier steps, seal, dense identity and structural checks

**Files:**
- Create: `libs/simkit/src/neorisk_simkit/engine/run.py`, `io/__init__.py`, `io/seal.py`, `checks/__init__.py`, `checks/structural.py`
- Test: `libs/simkit/tests/test_engine_seal.py`

**Interfaces:**
- Consumes: Tasks 5, 9, 10.
- Produces:
  - `engine.run.Simulation(run: RunSpec, *, threads: int, checked: bool = False)` with `static_entities() -> dict[str, pa.Table]` (read tables and population owner tables: `id` public, `created_at`, `origin` in {"initial", "arrival", "static"}, every table column at creation), `steps() -> Iterator[SealedStep]`, `stats: dict` (cumulative: `steps`, `rows_per_table`, `late_messages` (int), `rejects` (dict: process name → count), `retries` (int), `continuations` (int, continuation nodes executed), `rounds_per_step`, `round_detail`, stage seconds `generate_s`, `seal_s`; the four counters are copied from `World.stats` after every step, and Task 12 writes them verbatim into `run_stats.json` and `RunResult.stats`).
  - `io.seal.SealedStep(step: int, t_start: int, t_end: int, exported: bool, events: dict[str, pa.Table], history: dict[str, pa.Table], entities: dict[str, pa.Table], stats: dict)`; event tables have the plan's columns in order with Arrow types from `arrow_type` (`event_time` as timestamp, IDs as public int64, `cause_id` null, `event_type` string); rows sorted by the canonical key.
  - `io.seal.seal_step(world, step, t0, t1, exported, id_bases) -> SealedStep`; `id_bases: dict[str, int]` holds one cumulative base per namespace (key `<ns>`) and one per event table (key `event:<name>`), both starting at 0 and advanced by the rows sealed in each step, so dense indices and `event_id`s never repeat across steps.
  - `checks.structural.check_step(sealed, plan) -> dict[str, int]` (counts per check; raises `EngineError` on: non-increasing canonical key within a table, null in a required column, cat code out of range, provisional handle left after remap, `event_time` outside `[t_start, t_end)`).
  - `engine.run.next_step_length(prev_len, rows, engine, budget) -> int`.

Step loop (`Simulation.steps`): `t = start − warmup`, `end = start + span`, `len = engine.step_us`; call `world.init_shards()` once (queues the first `START` of every periodic shard process, D26; without it periodic processes such as Task 14's `restock` never run); while `t < end`: `t1 = min(t + len, end)`; if `t < start < t1`: `t1 = start` (D20); `run_step(world, t, t1)`; `seal_step(...)`; `exported = t >= start`; yield; `t = t1`; if `engine.adapt`: `len = next_step_length(len, rows, …)`.

Seal (`seal_step`), in this order:
1. Collect every worker's flushed `StepChunk`s.
2. Dense assignment per namespace: rows created this step get `dense = id_bases[ns] + rank by (pid, ordinal)` (`identity.assign_dense`); `id_bases[ns] += n`. Created owners' final `pid = ptype_code << 56 | dense`.
3. Remap provisional handles (D11) with `identity.remap_inplace` in: event ref columns, created rows' ref columns, `pid` columns of records from created owners, owner state and local `ref` fields and `self_id`/`pid` of touched slots, `n_tag` and payload columns 0..6 of every queued node of touched slots. A provisional value not found → `EngineError("unresolved handle …")`.
4. Free slots with `retire_at` set: `alive = 0`, `gen += 1`, release queue nodes.
5. Event dense indices per table: `dense = id_bases["event:<name>"] + rank by (pid, seq)` within the step, then `id_bases["event:<name>"] += rows`; `event_id = feistel63(dense, feistel_key(seed, <event name>))`; ref columns → `feistel63(value, feistel_key(seed, <target>))` (null stays null); `event_type` constant.
6. Canonical sort per table: `np.lexsort((seq, pid, lamport, time))`.
7. Step caps: total rows `> budget.max_step_rows` or bytes `> budget.max_step_bytes` → `CapExceeded("step_output", …)`.
8. Warm-up steps: drop events (D20) and `history` rows (time-indexed, like events) but keep `entities`; state changes made by change groups still apply to owner state.
9. `check_step` on exported steps.

- [ ] **Step 1: Write the failing tests**

`libs/simkit/tests/test_engine_seal.py`:
```python
import dataclasses

import numpy as np
import pyarrow.compute as pc
import pytest

from conftest import make_run
from neorisk_simkit.engine import CapExceeded
from neorisk_simkit.engine.run import Simulation, next_step_length

H = 3_600_000_000


def _sim(overrides=(), **engine):
    run = make_run("mini", overrides, **engine)
    return run, Simulation(run, threads=2)


def test_steps_cover_the_window_with_a_boundary_at_start():
    run, sim = _sim(step_us=4 * H)
    steps = list(sim.steps())
    t0, end = run.start_us - run.warmup_us, run.start_us + run.span_us
    assert steps[0].t_start == t0 and steps[-1].t_end == end
    assert all(a.t_end == b.t_start for a, b in zip(steps, steps[1:]))
    assert any(s.t_end == run.start_us for s in steps)
    assert all(not s.exported for s in steps if s.t_end <= run.start_us)
    for s in steps:
        assert all(t.num_rows == 0 for t in s.events.values()) or s.exported


def test_events_are_canonical_and_ids_public():
    _, sim = _sim()
    seen = set()
    for s in sim.steps():
        for name, t in s.events.items():
            if t.num_rows == 0:
                continue
            key = np.lexsort([t["seq"].to_numpy(), t["partition_id"].to_numpy(),
                              t["lamport"].to_numpy(),
                              t["event_time"].cast("int64").to_numpy()])
            assert (key == np.arange(t.num_rows)).all()
            ids = t["event_id"].to_numpy()
            assert (ids > 0).all() and not (set(ids.tolist()) & seen)
            seen |= set(ids.tolist())
            assert t["cause_id"].null_count == t.num_rows
            assert t.column_names[:8] == ["event_id", "event_type", "event_time", "lamport",
                                          "partition_id", "seq", "cause_id", "action_id"]


def test_created_rows_get_contiguous_dense_ids_and_refs_resolve():
    _, sim = _sim(["behavior.note_p=0.5"])
    notes, refs = [], []
    for s in sim.steps():
        if "note" in s.entities:
            notes.extend(s.entities["note"]["id"].to_pylist())
        ping = s.events.get("ping")
        if ping is not None and ping.num_rows:
            refs.extend(x for x in ping["note_id"].to_pylist() if x is not None)
    assert notes and len(set(notes)) == len(notes)
    assert set(refs) <= set(notes)                   # cross-step references resolve


def test_static_entities():
    run, sim = _sim()
    ents = sim.static_entities()
    assert ents["user"].num_rows == 200 and ents["item"].num_rows == 40
    assert set(ents["user"]["origin"].to_pylist()) == {"initial", "arrival"}
    assert ents["user"].column_names[:3] == ["id", "created_at", "origin"]


def test_boundary_instants():
    run, sim = _sim(step_us=6 * H)
    for s in sim.steps():
        for t in s.events.values():
            if t.num_rows:
                times = pc.cast(t["event_time"], "int64").to_numpy()
                assert times.min() >= s.t_start and times.max() < s.t_end
                assert times.min() >= run.start_us


def test_step_output_cap():
    run, sim = _sim()
    run2 = dataclasses.replace(run, budget=dataclasses.replace(run.budget, max_step_rows=10))
    with pytest.raises(CapExceeded, match="step_output"):
        list(Simulation(run2, threads=1).steps())


def test_next_step_length_targets_quarter_of_cap():
    run, _ = _sim()
    eng, bud = run.engine, dataclasses.replace(run.budget, max_step_rows=1000)
    assert next_step_length(4 * H, 500, eng, bud) == 2 * H        # 25% of 1000 = 250 rows
    assert next_step_length(4 * H, 0, eng, bud) == eng.step_max_us
    assert next_step_length(4 * H, 10**9, eng, bud) == eng.step_min_us


def test_stats_carry_engine_counters():
    _, sim = _sim(["behavior.max_pings=1", "behavior.take_p=0.0"])
    steps = list(sim.steps())
    st = sim.stats
    assert st["steps"] == len(steps) and len(st["rounds_per_step"]) == len(steps)
    assert 0 < st["rejects"]["user_main"] <= 200 and isinstance(st["retries"], int)
    assert isinstance(st["late_messages"], int) and isinstance(st["continuations"], int)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --all-packages pytest libs/simkit/tests/test_engine_seal.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'neorisk_simkit.engine.run'`.

- [ ] **Step 3: Implement**

- `next_step_length(prev, rows, eng, bud)`: `target = bud.max_step_rows // 4`; `new = eng.step_max_us if rows == 0 else prev * target // rows`; clamp to `[step_min_us, step_max_us]`; floor to whole seconds. Deterministic: depends only on row counts.
- Arrow conversion: `event_time` → `pa.array(time_us, pa.int64()).cast(pa.timestamp("us", tz="UTC"))`; cat columns → `pa.DictionaryArray.from_arrays(codes.astype(int16), values)`; nullable columns use their `valid_*` mask.
- `io/__init__.py` stays minimal (no heavy imports).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --all-packages pytest libs/simkit/tests/test_engine_seal.py -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Lint and commit**

Run: `uv run ruff check $(ls -d libs apps examples/ecommerce_s1 benchmarks 2>/dev/null)`
```bash
git add libs/simkit/src/neorisk_simkit libs/simkit/tests/test_engine_seal.py
git commit -m "simkit: frontier steps, seal with dense ids and public ids, structural checks

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 12: Writer, manifest, step index, schema.json and `run_to_dataset`

**Files:**
- Create: `libs/simkit/src/neorisk_simkit/io/writer.py`, `io/manifest.py`, `io/step_index.py`, `io/entities.py`, `io/dataset.py`, `io/read.py`, `io/stats.py`, `io/schema/__init__.py`, `io/schema/schema_json.py`
- Modify: `libs/simkit/tests/conftest.py` (append `event_dicts`)
- Test: `libs/simkit/tests/test_io_writer.py`

**Interfaces:**
- Consumes: Task 11 `Simulation` (incl. `stats["rejects"/"retries"/"late_messages"/"continuations"]`), `SealedStep`; Task 4 `validate`, `check_budget`; Task 3 conftest `FIXTURES`, `dataset_tree`.
- Produces:
  - `io.writer.writer_options(writer: WriterSettings, dict_cols: list[str], stat_cols: list[str]) -> dict` (the exact `pq.write_table` kwargs, pinned in the manifest); `write_step(run_dir, sealed, writer, plan) -> list[FileEntry]`; `FileEntry(path: str, rows: int, sha256: str)`.
  - `io.step_index.write_step_index(run_dir, rows: list[dict])`, `read_step_index(run_dir) -> pa.Table`. Columns: `step int32, t_start ts, t_end ts, rows int64, first_time ts, first_lamport int64, first_partition int64, first_seq int32, last_time ts, last_lamport, last_partition, last_seq`, then `rows__<type> int64` per event type (zero-row steps keep null first/last keys).
  - `io.schema.schema_json.schema_document(plan) -> dict` (keys: `pack`, `revision`, `schema_version`, `tables`: list of `{name, kind: "event"|"entity"|"history", doc, columns: [{name, type, nullable, arrow, ref, values, asset, quantum, minimum, doc}]}`), `write_schema(run_dir, plan)`, `load_schema(dataset_dir) -> dict`.
  - `io.manifest.write_manifest(run_dir, run, files, counts, checks, late_messages) -> dict` (keys: `schema_version`, `pack`, `pack_revision`, `engine_revision`, `uv_lock_sha256`, `seed`, `profile`, `overrides`, `config` (merged, JSON-safe), `writer`, `counts` (per table), `checks`, `late_messages`, `files` (sorted by path, with `rows` and `sha256`)); JSON written with `sort_keys=True, indent=2` and a trailing newline.
  - `io.stats.write_run_stats(run_dir, stats)` (`run_stats.json`: timings, stage seconds, rates, peak RSS bytes, rounds per step, `round_detail`, threads, `machine = {"arch", "cpus", "ram_bytes"}` (exactly these keys; Task 24 reads them), and the engine counters `rejects` (process name → count), `retries`, `late_messages`, `continuations` copied verbatim from `Simulation.stats`).
  - `io.dataset.ValidationFailed(Exception)` holding `.report: ValidationReport`; `str(e)` = `"; ".join(report.errors)` (Tasks 18 and 19 match error text such as `"exceed the memory budget"` against it).
  - `io.dataset.RunResult(out_dir: Path, manifest: dict, stats: dict)` (`stats` = the dict written to `run_stats.json`, so `RunResult.stats["retries"]`, `["continuations"]`, `["rejects"]` exist); `run_to_dataset(project_dir, profile="sample", overrides=(), *, seed=None, out_dir=None, threads=None, checked=False, force=False, engine_overrides=None) -> RunResult` — validate (raise `ValidationFailed(report)` on errors, `BudgetError` included), refuse an existing `out_dir` without `force` (`FileExistsError`), write into `out_dir.with_suffix(".partial")` then rename, stream steps to the writer.
  - `io.read.read_events(dataset_dir, types=None) -> dict[str, pl.DataFrame]` (all step files per type, canonical order).
  - `conftest.event_dicts(d: Path) -> dict[str, list[dict]]` = `{k: v.to_dicts() for k, v in sorted(read_events(d).items())}` (used by Tasks 13 and 17).

- [ ] **Step 1: Write the failing tests**

Append to `libs/simkit/tests/conftest.py`:
```python
def event_dicts(d: Path) -> dict[str, list[dict]]:
    """Every event table of a dataset as row dicts, keyed by type, in canonical order."""
    from neorisk_simkit.io.read import read_events  # lazy: conftest loads before io exists

    return {k: v.to_dicts() for k, v in sorted(read_events(d).items())}
```


`libs/simkit/tests/test_io_writer.py`:
```python
import hashlib
import json
from datetime import datetime, timezone

import polars as pl
import pyarrow.parquet as pq
import pytest

from conftest import FIXTURES, dataset_tree
from neorisk_simkit.io.dataset import ValidationFailed, run_to_dataset
from neorisk_simkit.io.read import read_events
from neorisk_simkit.io.step_index import read_step_index


@pytest.fixture(scope="module")
def ds(tmp_path_factory):
    out = tmp_path_factory.mktemp("mini") / "sample-s7"
    return run_to_dataset(FIXTURES / "mini", "sample", ["behavior.take_p=0.4"], out_dir=out)


def test_layout(ds):
    d = ds.out_dir
    for p in ("manifest.json", "run_stats.json", "schema/schema.json", "_index/steps.parquet",
              "entities/user/part-00000.parquet", "entities/item/part-00000.parquet"):
        assert (d / p).exists(), p
    files = sorted((d / "events" / "ping").rglob("*.parquet"))
    assert files and all(f.parent.name.startswith("date=2026-03-0") for f in files)
    assert all(f.name.startswith("step-") and len(f.stem) == len("step-000000") for f in files)


def test_files_sorted_and_dated(ds):
    for f in (ds.out_dir / "events").rglob("*.parquet"):
        t = pl.read_parquet(f)
        key = t.select("event_time", "lamport", "partition_id", "seq")
        assert key.equals(key.sort(["event_time", "lamport", "partition_id", "seq"]))
        day = f.parent.name.removeprefix("date=")
        assert (t["event_time"].dt.strftime("%Y-%m-%d") == day).all()


def test_writer_settings_are_pinned(ds):
    f = next((ds.out_dir / "events" / "took").rglob("*.parquet"))
    md = pq.ParquetFile(f).metadata
    col = md.row_group(0).column(md.schema.names.index("ok"))
    assert col.compression == "ZSTD" and "RLE_DICTIONARY" in col.encodings
    assert md.row_group(0).column(md.schema.names.index("event_time")).statistics is not None
    assert ds.manifest["writer"]["compression_level"] == 3
    assert ds.manifest["writer"]["row_group_size"] == 131_072


def test_manifest_counts_and_hashes(ds):
    m = ds.manifest
    events = read_events(ds.out_dir)
    assert {k: v.height for k, v in events.items()} == {
        k: m["counts"][k] for k in events}
    for entry in m["files"]:
        data = (ds.out_dir / entry["path"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == entry["sha256"]
    assert m["seed"] == 7 and m["pack"] == "mini" and len(m["pack_revision"]) == 7
    assert "late_messages" in m and m["overrides"] == ["behavior.take_p=0.4"]


def test_step_index_matches_files(ds):
    idx = read_step_index(ds.out_dir)
    assert idx["step"].to_pylist() == sorted(idx["step"].to_pylist())
    assert sum(idx["rows__ping"].to_pylist()) == ds.manifest["counts"]["ping"]


def test_schema_json_lists_common_columns_first(ds):
    doc = json.loads((ds.out_dir / "schema" / "schema.json").read_text())
    ping = next(t for t in doc["tables"] if t["name"] == "ping")
    assert [c["name"] for c in ping["columns"]][:3] == ["event_id", "event_type", "event_time"]
    note_col = next(c for c in ping["columns"] if c["name"] == "note_id")
    assert note_col["nullable"] and note_col["ref"] == "note"


def test_identical_replay_is_byte_identical(ds, tmp_path):
    again = run_to_dataset(FIXTURES / "mini", "sample", ["behavior.take_p=0.4"],
                           out_dir=tmp_path / "again", threads=1)
    assert dataset_tree(ds.out_dir) == dataset_tree(again.out_dir)


def test_refuses_to_overwrite_without_force(ds):
    with pytest.raises(FileExistsError):
        run_to_dataset(FIXTURES / "mini", "sample", ["behavior.take_p=0.4"], out_dir=ds.out_dir)


def test_empty_export_window_still_writes_manifest(tmp_path):
    r = run_to_dataset(FIXTURES / "bad_abi", "sample", ["mode=0"], out_dir=tmp_path / "empty")
    assert (r.out_dir / "manifest.json").exists() and (r.out_dir / "_index/steps.parquet").exists()
    assert r.manifest["counts"]["e"] == 0
    assert not list((r.out_dir / "events").rglob("*.parquet"))


def test_run_stats_carry_engine_counters_and_machine(ds):
    stats = json.loads((ds.out_dir / "run_stats.json").read_text())
    for key in ("rejects", "retries", "late_messages", "continuations"):
        assert stats[key] == ds.stats[key]
    assert isinstance(stats["rejects"], dict) and isinstance(stats["retries"], int)
    assert set(stats["machine"]) == {"arch", "cpus", "ram_bytes"}


def test_validation_failure_message_lists_errors(tmp_path):
    with pytest.raises(ValidationFailed, match="exceed the memory budget") as e:
        run_to_dataset(FIXTURES / "mini", "sample", ["budget.memory=1KB"],
                       out_dir=tmp_path / "refused")
    assert e.value.report.errors and not (tmp_path / "refused").exists()


def test_step_crossing_midnight_and_the_start_instant(tmp_path):
    # mini: start 2026-03-01T00:00Z, warm-up 6h; 5h steps from 02-28T18:00 give 18-23, 23-00
    # (forced boundary at start), then 00-05, 05-10, 10-15, 15-20, 20-01 (crosses midnight)
    r = run_to_dataset(FIXTURES / "mini", "sample", ["engine.step=5h"], out_dir=tmp_path / "m5")
    dirs: dict[tuple[str, str], set[str]] = {}
    for f in (r.out_dir / "events").rglob("*.parquet"):
        dirs.setdefault((f.parent.parent.name, f.stem), set()).add(f.parent.name)
    assert any(len(v) == 2 for v in dirs.values())        # same step-NNNNNN under two date= dirs
    start = datetime(2026, 3, 1, tzinfo=timezone.utc)
    for t in read_events(r.out_dir).values():
        if t.height:
            assert t["event_time"].min() >= start          # start - 1us is warm-up only
```
(`bad_abi` mode 0 rejects every command in unchecked mode, so the run exports zero events.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --all-packages pytest libs/simkit/tests/test_io_writer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'neorisk_simkit.io.dataset'`.

- [ ] **Step 3: Implement**

`writer_options` (pinned, exact):
```python
def writer_options(writer, dict_cols, stat_cols):
    return dict(compression=writer.compression, compression_level=writer.compression_level,
                row_group_size=writer.row_group_rows, use_dictionary=dict_cols,
                write_statistics=stat_cols)
```
`dict_cols` = `event_type` + cat columns; `stat_cols` = `event_time` + `event_id` + `partition_id` + every ref column. The manifest stores these options (lists sorted) plus `pyarrow.__version__`.
- Per sealed step and event type, split rows by UTC date of `event_time` and write `events/<type>/date=YYYY-MM-DD/step-%06d.parquet` (same step number under each date). History groups likewise under `history/<group>/`. Entities: one file per table `entities/<table>/part-00000.parquet` written at the end (concatenating static and per-step created rows, sorted by `id`'s dense order).
- Build the step-index rows from each sealed step (first/last key over all event types).
- `uv_lock_sha256`: sha256 of the workspace `uv.lock` if found by walking up from the project dir, else `null`.
- Thread caps (D33): `run_to_dataset` sets `pyarrow.set_cpu_count(threads)` and `os.environ.setdefault("POLARS_MAX_THREADS", str(threads))`; `threads` defaults to `budget.threads`.
- `run_stats.json` holds wall times, per-stage seconds, rows/s, `peak_rss_bytes` (`resource.getrusage(RUSAGE_SELF).ru_maxrss`, bytes on macOS, KiB × 1024 on Linux), `rounds_per_step`, `round_detail` (per step: `{"owners_run": [...], "shard_cmds": [...]}` from `RoundStats`), `threads`, `machine = {"arch": platform.machine(), "cpus": os.cpu_count(), "ram_bytes": os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")}`, and `rejects`, `retries`, `late_messages`, `continuations` copied verbatim from `Simulation.stats`. `RunResult.stats` is the same dict.
- `ValidationFailed(report)`: `super().__init__("; ".join(report.errors))` and `self.report = report`; `run_to_dataset` raises it before creating any folder.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --all-packages pytest libs/simkit/tests/test_io_writer.py -v`
Expected: PASS (12 tests).

- [ ] **Step 5: Full suite, lint and commit**

Run: `uv run --all-packages pytest -q && uv run ruff check $(ls -d libs apps examples/ecommerce_s1 benchmarks 2>/dev/null)`
```bash
git add libs/simkit/src/neorisk_simkit/io libs/simkit/tests/conftest.py libs/simkit/tests/test_io_writer.py
git commit -m "simkit: parquet writer, manifest, step index, schema.json, run_to_dataset

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---
### Task 13: Exit test — native ABI proof under forced exhaustion

**Files:**
- Create fixture: `libs/simkit/tests/fixtures/abi_proof/{datagen.toml,specs/pack.py,specs/kernels.py}`
- Test: `libs/simkit/tests/test_exit_abi_proof.py`

**Interfaces:**
- Consumes: Task 12 `run_to_dataset(..., engine_overrides={"force_capacity": {...}}, checked=...)`, `read_events`, `RunResult.stats["retries"]`, `run_stats.json["rejects"]`, conftest `event_dicts`; Task 8 `force_capacity` semantics (records/creates = buffer rows; `timers` = cap on each worker's node refill chunk, so its free list never holds more than n nodes — `validate` requires n ≥ every kernel's `max.timers`, and `MINIMA["timers"] = 2` equals `prove`'s maximum; `requests` = outbox rows, and a full outbox is moved aside to `World.pending_outbox` by Task 9, so `requests: 1` with 30 provers makes progress).
- Produces: the §05 exit test. No production code unless the test exposes a bug (fix it in the owning module and say so in the commit body).

- [ ] **Step 1: Create the fixture**

`fixtures/abi_proof/datagen.toml`: copy of mini's with `name = "abi_proof"`, `warmup = "0s"`, `span = "6h"`, `[engine] step = "6h"`, `[profiles.sample] set = {}`.

`fixtures/abi_proof/specs/pack.py`:
```python
"""ABI proof (spec §05 exit test): one kernel emits three record types, creates rows and ids,
schedules timers, sends requests and rejects; a shard answers."""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, dist
from neorisk_simkit.spec.types import i32, opt, ref

from . import kernels as k

PACK = "abi_proof"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Config:
    provers: int = 30
    ticks: int = 12


def define(p: Pack, cfg: Config) -> None:
    prover = p.table("prover", key="prover_id", mutable=True, cols={
        "n": i32(), "last_box": opt(ref("box"))})
    p.table("box", key="box_id", mutable=True, child_of="prover", cols={"w": i32()})
    p.ids("tok")
    p.owner("prover", table=prover, max_live=cfg.provers)
    p.population(prover, n=cfg.provers, initial=1.0)
    sink = p.shard("sink", key="sink", n=2, items=None, state={})
    put = p.request("put", frm="prover", to=sink, payload={"w": i32()},
                    response_payload={"w": i32()}, responses=("ok",),
                    latency=dist.constant(ms=50))
    p.event("e_alpha", owner="prover", cols={
        "prover_id": ref("prover"), "tok_id": ref("tok"), "k": i32()})
    p.event("e_beta", owner="prover", cols={
        "prover_id": ref("prover"), "box_id": ref("box"), "w": i32()})
    p.event("e_gamma", owner="prover", cols={
        "prover_id": ref("prover"), "k": i32(), "note": opt(i32())})
    p.event("sunk", shard="sink", cols={"w": i32()})
    p.process("prove", owner="prover", kernel=k.prove, config=cfg,
              start=p.on_created("prover"), requests={"put": put},
              on_response={("put", "ok"): k.R_OK}, commands=k.COMMANDS)
    p.process("sink_desk", shard=sink, kernel=k.sink_desk, on_request={"put": k.C_PUT})
```

`fixtures/abi_proof/specs/kernels.py`:
```python
from neorisk_simkit.engine import COMMIT, RETRY, START, Res, kernel, reject

C_TICK, C_ECHO, R_OK = 1, 2, 3
COMMANDS = (START, C_TICK, C_ECHO, R_OK)
C_PUT = 1
MINUTE = 60_000_000


@kernel(state="prover", commands=COMMANDS,
        max=Res(records={"e_alpha": 1, "e_beta": 1, "e_gamma": 2},
                creates={"box": 1, "tok": 1}, timers=2, requests=1))
def prove(ctx, s, cmd, out):
    if cmd.kind == START:
        if not out.reserve(timers=1):
            return RETRY
        out.timer(ctx.t + MINUTE, C_TICK)
        return COMMIT
    if cmd.kind == C_TICK:
        if s.n >= ctx.cfg.ticks:
            return reject(1)
        w = ctx.rng.uniform_int(site=1, lo=1, hi=100)
        target = ctx.rng.uniform_int(site=3, lo=0, hi=1)
        gap = ctx.rng.uniform_int(site=4, lo=1, hi=5)
        if not out.reserve(records={"e_alpha": 1, "e_beta": 1, "e_gamma": 2},
                           creates={"box": 1, "tok": 1}, timers=2, requests=1):
            return RETRY
        s.n += 1
        tok = out.new_id("tok")
        box = out.create_box(w=w)
        s.last_box = box
        out.emit_e_alpha(ctx.t, prover_id=ctx.self_id, tok_id=tok, k=s.n)
        out.emit_e_beta(ctx.t, prover_id=ctx.self_id, box_id=box, w=w)
        for j in range(2):                                   # one site, k counts the draws
            out.emit_e_gamma(ctx.t, prover_id=ctx.self_id,
                             k=j + ctx.rng.uniform_int(site=2, lo=0, hi=9))
        out.request_put(ctx.t, shard=target, tag=tok, w=w)
        out.timer(ctx.t + gap * MINUTE, C_TICK)
        out.timer(ctx.t, C_ECHO)
        return COMMIT
    if cmd.kind == C_ECHO:
        if s.n % 3 == 2:
            return reject(2)
        if not out.reserve(records={"e_gamma": 1}):
            return RETRY
        out.emit_e_gamma(ctx.t, prover_id=ctx.self_id, k=100 + s.n)
        return COMMIT
    if not out.reserve(records={"e_gamma": 1}):
        return RETRY
    out.emit_e_gamma(ctx.t, prover_id=ctx.self_id, k=200, note=cmd.w)
    return COMMIT


@kernel(state="sink", commands=(C_PUT,), max=Res(records={"sunk": 1}, requests=1))
def sink_desk(ctx, s, cmd, out):
    if not out.reserve(records={"sunk": 1}, requests=1):
        return RETRY
    out.emit_sunk(ctx.t, w=cmd.w)
    out.respond(cmd, "ok", w=cmd.w)
    return COMMIT
```
(Draws happen before `reserve` so a `RETRY` replays identical values; the draw inside the emit loop happens after `reserve`, which is legal because it is not a write.)

- [ ] **Step 2: Write the failing test**

`libs/simkit/tests/test_exit_abi_proof.py`:
```python
"""Spec §05 exit test: native ABI proof.

A compiled kernel that emits several record types, creates rows, schedules timers and requests,
and rejects, runs under forced exhaustion of each resource in turn, compiled with checked mode and
uncompiled, and must produce identical logical output.
"""

import json
import os
import subprocess
import sys

import polars as pl
import pytest

from conftest import FIXTURES, event_dicts
from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events

PROJECT = FIXTURES / "abi_proof"
MINIMA = {"records:e_alpha": 1, "records:e_beta": 1, "records:e_gamma": 2, "creates:box": 1,
          "creates:tok": 1, "timers": 2, "requests": 1}


def logical(out_dir):
    """Every event table and the created-row entities, as comparable Python objects."""
    data = event_dicts(out_dir)
    data["entities/box"] = pl.read_parquet(out_dir / "entities/box/part-00000.parquet").to_dicts()
    return data


@pytest.fixture(scope="module")
def baseline(tmp_path_factory):
    out = tmp_path_factory.mktemp("abi") / "baseline"
    run_to_dataset(PROJECT, "sample", out_dir=out, threads=2)
    return out


def test_baseline_exercises_every_path(baseline):
    m = json.loads((baseline / "manifest.json").read_text())
    stats = json.loads((baseline / "run_stats.json").read_text())
    assert m["counts"]["e_alpha"] > 0 and m["counts"]["e_beta"] == m["counts"]["e_alpha"]
    assert m["counts"]["sunk"] > 0 and m["counts"]["e_gamma"] > 2 * m["counts"]["e_alpha"]
    assert stats["rejects"]["prove"] > 0
    ev = read_events(baseline)
    assert ev["e_gamma"]["note"].null_count() < ev["e_gamma"].height


@pytest.mark.parametrize("resource", sorted(MINIMA))
def test_forced_exhaustion_matches_baseline(resource, baseline, tmp_path):
    r = run_to_dataset(PROJECT, "sample", out_dir=tmp_path / "forced", threads=2,
                       engine_overrides={"force_capacity": {resource: MINIMA[resource]}})
    assert r.stats["retries"] > 0, f"{resource} was never exhausted"
    assert logical(r.out_dir) == logical(baseline)


SCRIPT = """
import sys
from pathlib import Path
from neorisk_simkit.io.dataset import run_to_dataset
project, root, minima = Path(sys.argv[1]), Path(sys.argv[2]), eval(sys.argv[3])
run_to_dataset(project, "sample", out_dir=root / "all", threads=1, checked=True)
for res, n in minima.items():
    run_to_dataset(project, "sample", out_dir=root / res.replace(":", "_"), threads=1,
                   checked=True, engine_overrides={"force_capacity": {res: n}})
"""


@pytest.mark.parametrize("mode", ["checked", "uncompiled"])
def test_checked_and_uncompiled_runs_match(mode, baseline, tmp_path):
    env = dict(os.environ)
    if mode == "checked":
        env["NUMBA_BOUNDSCHECK"] = "1"
        env["NUMBA_CACHE_DIR"] = str(tmp_path.parent / "numba-checked-cache")
    else:
        env["NUMBA_DISABLE_JIT"] = "1"
    subprocess.run([sys.executable, "-c", SCRIPT, str(PROJECT), str(tmp_path), repr(MINIMA)],
                   env=env, check=True, timeout=3600)
    want = logical(baseline)
    assert logical(tmp_path / "all") == want
    for res in MINIMA:
        assert logical(tmp_path / res.replace(":", "_")) == want, res
```

- [ ] **Step 3: Run the test**

Run: `uv run --all-packages pytest libs/simkit/tests/test_exit_abi_proof.py -v`
Expected: PASS (1 + 7 + 2 tests; the fixture was created in Step 1). If a forced-exhaustion case differs from the baseline, the bug is in RETRY handling (Task 9) or slab flushing (Task 8): fix it there; never relax the comparison.

- [ ] **Step 4: Lint and commit**

Run: `uv run ruff check $(ls -d libs apps examples/ecommerce_s1 benchmarks 2>/dev/null)`
```bash
git add libs/simkit/tests/fixtures/abi_proof libs/simkit/tests/test_exit_abi_proof.py
git commit -m "test: S1 exit test - native ABI proof under forced exhaustion

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 14: S1 e-commerce slice — shoppers, carts, single-SKU checkout, inventory shards

**Files:**
- Create: `examples/ecommerce_s1/README.md`, `examples/ecommerce_s1/datagen.toml`, `examples/ecommerce_s1/specs/brief.md`, `examples/ecommerce_s1/specs/pack.py`, `examples/ecommerce_s1/specs/kernels.py`, `examples/ecommerce_s1/{out,reports,logs}/.gitkeep`
- Create: `libs/simkit/src/neorisk_simkit/std/sources.py` (`catalog`, `devices`, `stock`); Modify: `std/__init__.py` (export `catalog`, `devices`, `stock` only; `generated` and `law` are already exported since Task 3), `examples/README.md` (one row for `ecommerce_s1/`, marked "S1 slice; superseded by `ecommerce/` at M3")
- Modify (engine wiring for recipe-derived tables and read columns): `libs/simkit/src/neorisk_simkit/engine/layout.py` (read columns include a recipe's extra read columns; recipe-built read tables), `engine/world.py` (build read tables and extra read columns from recipes), `engine/run.py` (`static_entities()` includes recipe-built tables)
- Test: `apps/datagen/tests/test_example_ecom_s1.py`

**Interfaces:**
- Consumes: Tasks 1–12 (`std` package from Tasks 2–3; `layout.kernel_layouts`, `World.build`, `Simulation.static_entities`).
- Produces:
  - Recipe protocol (the object passed as `population(refs={...})` values or as a shard's `init=`; `std.devices` and `std.stock` implement it, and Tasks 6/9/11 code paths call it duck-typed): `read_column_names(table: str) -> tuple[str, ...]` (plan-time, no data; extra read columns the recipe adds to `table`, e.g. `("stock_target",)` for the items table of `std.stock`), `extra_read_columns(table: str) -> dict[str, np.ndarray]` (build-time, after the recipe generated its data with keyed streams), and `table_rows(table: str) -> dict[str, np.ndarray] | None` (build-time; the full rows of a table the recipe generates, e.g. `device` for `std.devices`, `None` for tables it does not build). Wiring: `layout` appends `read_column_names(t)` after `t`'s own columns (and before `local_index`/`cumw`) for every reads entry, and a read table with no `source` gets its rows from the recipe that builds it, with its `n` read at runtime (Task 6 rule: only fixed-`n` sources are inlined); `World.build` fills those reads from `extra_read_columns`/`table_rows`; `Simulation.static_entities()` writes recipe-built tables (`origin = "static"`, `created_at` = the column `first_seen` when present, else `start − warmup`).
  - `std.catalog(n, category: Dist, price: Dist, group: Dist, weight: Dist) -> Source` for a table with columns `category`, `price`, `sku_group`; adds read-only derived arrays `cumw` (cumulative view weight, for `sample_by_weight`) and is the items table of the inventory shard.
  - `std.devices(per_user: Dist, table: str, share: float, kinds: dict[str, float] | None = None) -> RefsRecipe`: generates the device table rows (`os`, `kind`, `first_seen`) and the user→device CSR (each user ≥ 1 device; a `share` of users additionally reuse one device of a random earlier user — the household). Exposed in kernels as `ctx.refs.<name>.count(id)`, `.get(id, j)`, `.pick(id, u)`.
  - `std.stock(initial: Dist, by_weight: float = 0.0) -> ShardInit`: initial `on_hand` per SKU (`negbinom` draw, scaled up for heavy-weight SKUs), `reserved = 0`, and the derived read column `stock_target` on the items table (= initial stock).
  - Project `examples/ecommerce_s1` with pack `ecommerce_s1`, `SCHEMA_VERSION = 1`, processes `shopper` (owner `user`), `inventory_desk` and `restock` (shard `inventory`).

- [ ] **Step 1: Write the project files**

`examples/ecommerce_s1/datagen.toml`:
```toml
# S1 slice of the e-commerce project (spec §18 S1). Same layout as examples/ecommerce.
[project]
name = "ecommerce_s1"
pack = "specs/pack.py"

[paths]
out = "out"
reports = "reports"
logs = "logs"

[defaults]
seed = 42
start = "2026-01-01T00:00:00Z"
mode = "time"
span = "90d"
warmup = "14d"

[budget]
threads = 16
memory = "16GB"
max_step_rows = 4_000_000
max_step_bytes = "1GB"
max_spawn_depth = 3
max_admissions_per_step = 200_000

[writer]
compression = "zstd"
compression_level = 3
row_group_rows = 131_072

[engine]
step = "1d"
step_min = "1h"
step_max = "7d"
adapt = true
slab_bytes = "8MB"
timer_nodes = 12_000_000
payload_slots = 2_000_000
max_messages_per_step = 4_000_000
parallel_min_partitions = 2_048

[profiles.sample]
span = "21d"
warmup = "3d"
set = { users = 20_000, skus = 5_000, sku_groups = 64 }

[profiles.full]                        # the S1 benchmark shape (benchmarks/s1.toml)
set = { users = 2_000_000, skus = 50_000, sku_groups = 512 }

[replay.presets.peek]
first = 100
sink = "stdout:?format=table"

[replay.presets.last_json]
last = 100
sink = "file:last100.json?format=json-array"
```

`examples/ecommerce_s1/specs/pack.py`:
```python
"""E-commerce S1 slice (spec §18 S1).

Shoppers browse in sessions, keep a one-line cart, and check out a single SKU against the
inventory shard that owns it. Everything is a handwritten kernel; state machines, multi-SKU
reservations, referrals and overlays arrive with examples/ecommerce at M3.

Partitions
    owner  user        one shopper: profile, cart scratch, checkout in flight
    shard  inventory   one inventory group: on_hand and reserved per SKU

Boundaries (immutable, latency >= delta)
    user -> inventory  reserve (request, answered granted/rejected)   delta 150 ms
    user -> inventory  commit, release (one-way messages)             delta 150 ms
"""

from dataclasses import dataclass, field

from neorisk_simkit.spec import Pack, dist, std
from neorisk_simkit.spec.types import amount, boolean, cat, i16, i32, opt, ref, ts

from . import kernels as k

PACK = "ecommerce_s1"
SCHEMA_VERSION = 1

CATEGORIES = (
    "apparel", "shoes", "beauty", "home", "kitchen", "garden", "toys", "baby", "books",
    "music", "video_games", "electronics", "phones", "computers", "office", "pets", "sports",
    "outdoors", "auto", "tools", "grocery", "health", "jewelry", "luggage",
)
CHANNELS = ("web", "app")
ACQUISITION = ("organic", "search_ad", "social_ad", "affiliate")
SOURCES = ("home", "search", "category", "recommendation")
REFERRERS = ("none", "email", "social", "ads")


@dataclass(frozen=True)
class Journey:
    """Shopper behavior; consumed by kernels.shopper."""
    signup_delay: dist.Dist = dist.exp(mean_s=3600)
    session_gap_alpha: float = 1.2          # Pareto tail of gaps between sessions
    session_gap_min_h: float = 30.0
    views_mean: float = 6.0                 # geometric views per session
    view_gap: dist.Dist = dist.exp(mean_s=40)
    add_to_cart_p: float = 0.18             # per view; replaces the one cart line (S1)
    checkout_p: float = 0.35                # per session end with a non-empty cart
    checkout_delay: dist.Dist = dist.exp(mean_s=25)
    substitute_p: float = 0.45              # after out-of-stock: browse for a substitute
    auth_fail_p: float = 0.03
    auth_latency: dist.Dist = dist.lognormal(median_s=2.5, sigma=0.6)


@dataclass(frozen=True)
class Config:
    users: int = 20_000                     # population at the end of the span
    initial_share: float = 0.6
    skus: int = 5_000
    sku_groups: int = 64                    # inventory shards
    restock_period: str = "7d"
    household_share_device: float = 0.12
    journey: Journey = field(default_factory=Journey)


def define(p: Pack, cfg: Config) -> None:
    sku = p.table("sku", key="sku_id", doc="Catalog, fixed for the run", cols={
        "category": cat(*CATEGORIES), "price": amount(asset="USD"), "sku_group": i16()},
        source=std.catalog(n=cfg.skus, category=dist.categorical(
            {c: 1 / len(CATEGORIES) for c in CATEGORIES}),
            price=dist.lognormal_minor(median=2_500, sigma=0.9, min=199, max=200_000),
            group=dist.uniform_int(0, cfg.sku_groups - 1), weight=dist.zipf(s=1.07)))
    device = p.table("device", key="device_id", doc="Shopper devices", cols={
        "os": cat("ios", "android", "windows", "macos", "linux"),
        "kind": cat("phone", "tablet", "desktop"), "first_seen": ts()})
    user = p.table("user", key="user_id", mutable=True, doc="A shopper", cols={
        "age_band": cat("18-24", "25-34", "35-44", "45-54", "55+"),
        "acquisition": cat(*ACQUISITION), "status": cat("active", "dormant")})
    p.table("order", key="order_id", mutable=True, child_of="user", cols={
        "sku_id": ref("sku"), "quantity": i16(), "amount": amount(asset="USD")})
    p.ids("session", "checkout")

    p.owner("user", table=user, max_live=cfg.users, retire_when_idle=False)
    p.population(
        user, n=cfg.users, initial=cfg.initial_share,
        arrivals=dist.poisson_daily(weekly=(1.0, 0.95, 0.95, 1.0, 1.1, 1.3, 1.25), trend=0.002),
        attrs={"age_band": dist.categorical({"18-24": .17, "25-34": .31, "35-44": .24,
                                             "45-54": .16, "55+": .12}),
               "acquisition": dist.categorical({"organic": .55, "search_ad": .2,
                                                "social_ad": .15, "affiliate": .1})},
        refs={"device": std.devices(per_user=dist.categorical({1: .6, 2: .3, 3: .1}),
                                    table=device, share=cfg.household_share_device)})

    inventory = p.shard("inventory", key="sku_group", n=cfg.sku_groups, items=sku,
                        doc="Stock per inventory group",
                        state={"on_hand": "i32[sku]", "reserved": "i32[sku]"},
                        init=std.stock(initial=dist.negbinom(mean=40, disp=0.7), by_weight=8.0))
    lat = dist.shifted_lognormal(min_ms=150, median_ms=240)
    line = {"sku_id": ref("sku"), "quantity": i16()}
    reserve = p.request("reserve", frm="user", to=inventory, payload=line,
                        responses=("granted", "rejected"), latency=lat)
    commit = p.message("commit", frm="user", to=inventory, payload=line, latency=lat)
    release = p.message("release", frm="user", to=inventory, payload=line, latency=lat)

    u = {"user_id": ref("user")}
    p.event("user_signed_up", owner="user", doc="A shopper creates an account", cols={
        **u, "device_id": ref("device"), "acquisition": cat(*ACQUISITION),
        "age_band": cat("18-24", "25-34", "35-44", "45-54", "55+")})
    p.event("session_started", owner="user", cols={
        **u, "session_id": ref("session"), "device_id": ref("device"), "channel": cat(*CHANNELS)})
    p.event("product_viewed", owner="user", doc="12 property columns (S1 benchmark shape)", cols={
        **u, "session_id": ref("session"), "sku_id": ref("sku"), "device_id": ref("device"),
        "position": i16(), "source": cat(*SOURCES), "channel": cat(*CHANNELS),
        "category": cat(*CATEGORIES), "price": amount(asset="USD"), "page_ms": i32(min=0),
        "referrer": cat(*REFERRERS), "is_recommended": boolean()})
    p.event("cart_item_added", owner="user", cols={
        **u, "session_id": ref("session"), "sku_id": ref("sku"), "quantity": i16(),
        "unit_price": amount(asset="USD")})
    p.event("checkout_started", owner="user", cols={
        **u, "session_id": ref("session"), "checkout_id": ref("checkout"), "sku_id": ref("sku"),
        "quantity": i16(), "subtotal": amount(asset="USD")})
    p.event("checkout_failed", owner="user", cols={
        **u, "checkout_id": ref("checkout"), "reason": cat("out_of_stock", "payment_declined"),
        "sku_id": opt(ref("sku"))})
    p.event("payment_authorized", owner="user", cols={
        **u, "checkout_id": ref("checkout"), "amount": amount(asset="USD"),
        "method": cat("card", "wallet", "bnpl")})
    p.event("payment_failed", owner="user", cols={
        **u, "checkout_id": ref("checkout"), "amount": amount(asset="USD"),
        "decline_code": cat("insufficient_funds", "do_not_honor", "expired_card",
                            "fraud_suspected")})
    p.event("order_placed", owner="user", doc="Stock committed and payment authorized", cols={
        **u, "order_id": ref("order"), "checkout_id": ref("checkout"), "device_id": ref("device"),
        "sku_id": ref("sku"), "quantity": i16(), "amount": amount(asset="USD"),
        "category": cat(*CATEGORIES)})
    stock_cols = {"sku_group": i16(), "sku_id": ref("sku"), "checkout_id": ref("checkout"),
                  "quantity": i16()}
    p.event("stock_reserved", shard="inventory", cols=stock_cols)
    p.event("stock_rejected", shard="inventory", cols=stock_cols)
    p.event("stock_committed", shard="inventory", cols={**stock_cols, "on_hand_after": i32()})
    p.event("stock_released", shard="inventory", cols=stock_cols)
    p.event("restocked", shard="inventory", doc="Supplier delivery to an inventory group", cols={
        "sku_group": i16(), "sku_id": ref("sku"), "quantity": i32(min=1), "on_hand_after": i32()})

    p.process("shopper", owner="user", kernel=k.shopper, config=cfg.journey,
              start=p.on_created("user"), requests={"reserve": reserve},
              messages={"commit": commit, "release": release},
              on_response={("reserve", "granted"): k.R_GRANTED,
                           ("reserve", "rejected"): k.R_REJECTED},
              reads={"sku": sku, "device": device}, refs={"device": "device"},
              commands=k.SHOPPER_COMMANDS)
    p.process("inventory_desk", shard=inventory, kernel=k.inventory_desk,
              on_request={"reserve": k.C_RESERVE},
              on_message={"commit": k.C_COMMIT, "release": k.C_RELEASE}, reads={"sku": sku})
    p.process("restock", shard=inventory, kernel=k.restock, every=cfg.restock_period,
              jitter=dist.normal(mean_h=0, sd_h=18), reads={"sku": sku})

    p.check("chk.stock_never_negative", std.law.never_negative("inventory.on_hand"),
            required=True)
```
(`std.law` is `neorisk_simkit.spec.law`; checks are recorded, evaluated from S2.)

`examples/ecommerce_s1/specs/kernels.py`:
```python
"""Handwritten kernels for the S1 e-commerce slice.

Every kernel: validate (draws allowed, no writes) -> out.reserve(...) -> commit.
Each random draw has its own site number.
"""

from neorisk_simkit import std
from neorisk_simkit.engine import COMMIT, PRIO_TIMER, RETRY, START, Local, Res, kernel, reject

C_SESSION, C_VIEW, C_CHECKOUT, C_AUTH, R_GRANTED, R_REJECTED = 1, 2, 3, 4, 5, 6
SHOPPER_COMMANDS = (START, C_SESSION, C_VIEW, C_CHECKOUT, C_AUTH, R_GRANTED, R_REJECTED)
C_RESERVE, C_COMMIT, C_RELEASE = 1, 2, 3

REJ_DORMANT, REJ_NO_CART, REJ_STALE, REJ_BUSY = 1, 2, 3, 4

SHOPPER_LOCAL = Local(session="ref", device="ref", views_left="i16", cart_sku="ref",
                      cart_qty="i16", cart_price="i64", cart_n="i8", checkout="ref")


@kernel(state="user", local=SHOPPER_LOCAL, commands=SHOPPER_COMMANDS,
        max=Res(records={"user_signed_up": 1, "session_started": 1, "product_viewed": 1,
                         "cart_item_added": 1, "checkout_started": 1, "checkout_failed": 1,
                         "payment_authorized": 1, "payment_failed": 1, "order_placed": 1},
                creates={"order": 1, "session": 1, "checkout": 1}, timers=2, requests=1))
def shopper(ctx, s, loc, cmd, out):
    cfg = ctx.cfg
    if cmd.kind == START:
        return _signup(ctx, s, out, cfg)
    if cmd.kind == C_SESSION:
        return _session(ctx, s, loc, out, cfg)
    if cmd.kind == C_VIEW:
        return _view(ctx, loc, out, cfg)
    if cmd.kind == C_CHECKOUT:
        return _checkout(ctx, loc, out)
    if cmd.kind == R_GRANTED:
        return _granted(ctx, loc, cmd, out, cfg)
    if cmd.kind == R_REJECTED:
        return _rejected(ctx, loc, cmd, out, cfg)
    return _auth(ctx, loc, cmd, out, cfg)


def _signup(ctx, s, out, cfg):
    delay = ctx.rng.dist_us(site=1, d=cfg.signup_delay)
    if not out.reserve(records={"user_signed_up": 1}, timers=1):
        return RETRY
    out.emit_user_signed_up(ctx.t, user_id=ctx.self_id,
                            device_id=ctx.refs.device.get(ctx.self_id, 0),
                            acquisition=s.acquisition, age_band=s.age_band)
    out.timer(ctx.t + delay, C_SESSION, prio=PRIO_TIMER)
    return COMMIT


def _channel(ctx, device):
    if ctx.reads.device.kind[device] == "desktop":
        return 0                                           # web
    return 1                                               # app


def _session(ctx, s, loc, out, cfg):
    if s.status != "active":
        return reject(REJ_DORMANT)
    n_dev = ctx.refs.device.count(ctx.self_id)
    dev = ctx.refs.device.get(ctx.self_id, ctx.rng.uniform_int(site=2, lo=0, hi=n_dev - 1))
    views = 1 + ctx.rng.geometric(site=3, mean=cfg.views_mean - 1.0)
    gap = ctx.rng.pareto_us(site=4, alpha=cfg.session_gap_alpha, min_h=cfg.session_gap_min_h)
    first = ctx.rng.dist_us(site=5, d=cfg.view_gap)
    if not out.reserve(records={"session_started": 1}, creates={"session": 1}, timers=2):
        return RETRY
    loc.session = out.new_id("session")
    loc.device = dev
    loc.views_left = views
    out.emit_session_started(ctx.t, user_id=ctx.self_id, session_id=loc.session, device_id=dev,
                             channel=_channel(ctx, dev))
    out.timer(ctx.t + first, C_VIEW, prio=PRIO_TIMER)
    out.timer(ctx.t + gap, C_SESSION, prio=PRIO_TIMER)
    return COMMIT


def _view(ctx, loc, out, cfg):
    if loc.views_left <= 0:                                # session over: maybe check out
        if loc.cart_n == 0 or loc.checkout != std.NULL:
            return reject(REJ_NO_CART)
        if not ctx.rng.bernoulli(site=10, p=cfg.checkout_p):
            return reject(REJ_NO_CART)
        delay = ctx.rng.dist_us(site=11, d=cfg.checkout_delay)
        if not out.reserve(timers=1):
            return RETRY
        out.timer(ctx.t + delay, C_CHECKOUT, prio=PRIO_TIMER)
        return COMMIT
    sku = ctx.reads.sku.sample_by_weight(ctx.rng.uniform(site=12))
    add = ctx.rng.bernoulli(site=13, p=cfg.add_to_cart_p)
    qty = 1 + ctx.rng.geometric(site=14, mean=0.25)
    pos = 1 + ctx.rng.geometric(site=15, mean=4.0)
    src = ctx.rng.categorical(site=16, p=(0.25, 0.35, 0.2, 0.2))
    referrer = ctx.rng.categorical(site=17, p=(0.7, 0.1, 0.12, 0.08))
    page_ms = 200 + ctx.rng.geometric(site=18, mean=800.0)
    nxt = ctx.rng.dist_us(site=19, d=cfg.view_gap)
    if not out.reserve(records={"product_viewed": 1, "cart_item_added": 1}, timers=1):
        return RETRY
    out.emit_product_viewed(ctx.t, user_id=ctx.self_id, session_id=loc.session, sku_id=sku,
                            device_id=loc.device, position=pos, source=src,
                            channel=_channel(ctx, loc.device),
                            category=ctx.reads.sku.category[sku], price=ctx.reads.sku.price[sku],
                            page_ms=page_ms, referrer=referrer, is_recommended=src == 3)
    if add and loc.checkout == std.NULL:                   # one-line cart (D27)
        loc.cart_sku = sku
        loc.cart_qty = qty
        loc.cart_price = ctx.reads.sku.price[sku]
        loc.cart_n = 1
        out.emit_cart_item_added(ctx.t, user_id=ctx.self_id, session_id=loc.session, sku_id=sku,
                                 quantity=qty, unit_price=loc.cart_price)
    loc.views_left -= 1
    out.timer(ctx.t + nxt, C_VIEW, prio=PRIO_TIMER)
    return COMMIT


def _checkout(ctx, loc, out):
    if loc.cart_n == 0 or loc.checkout != std.NULL:
        return reject(REJ_BUSY)
    if not out.reserve(records={"checkout_started": 1}, creates={"checkout": 1}, requests=1):
        return RETRY
    loc.checkout = out.new_id("checkout")
    out.emit_checkout_started(ctx.t, user_id=ctx.self_id, session_id=loc.session,
                              checkout_id=loc.checkout, sku_id=loc.cart_sku,
                              quantity=loc.cart_qty,
                              subtotal=std.checked_mul(loc.cart_price, loc.cart_qty))
    out.request_reserve(ctx.t, shard=ctx.reads.sku.sku_group[loc.cart_sku], tag=loc.checkout,
                        sku_id=loc.cart_sku, quantity=loc.cart_qty)
    return COMMIT                                          # the owner suspends until answered


def _granted(ctx, loc, cmd, out, cfg):
    if cmd.tag != loc.checkout:
        return reject(REJ_STALE)
    delay = ctx.rng.dist_us(site=30, d=cfg.auth_latency)
    if not out.reserve(timers=1):
        return RETRY
    out.timer(ctx.t + delay, C_AUTH, prio=PRIO_TIMER, tag=loc.checkout)
    return COMMIT


def _rejected(ctx, loc, cmd, out, cfg):
    if cmd.tag != loc.checkout:
        return reject(REJ_STALE)
    substitute = ctx.rng.bernoulli(site=31, p=cfg.substitute_p)
    more = 1 + ctx.rng.geometric(site=32, mean=2.0)
    nxt = ctx.rng.dist_us(site=33, d=cfg.view_gap)
    if not out.reserve(records={"checkout_failed": 1}, timers=1):
        return RETRY
    out.emit_checkout_failed(ctx.t, user_id=ctx.self_id, checkout_id=loc.checkout,
                             reason="out_of_stock", sku_id=loc.cart_sku)
    loc.checkout = std.NULL
    loc.cart_n = 0
    if substitute:
        loc.views_left = more
        out.timer(ctx.t + nxt, C_VIEW, prio=PRIO_TIMER)
    return COMMIT


def _auth(ctx, loc, cmd, out, cfg):
    if cmd.tag != loc.checkout:
        return reject(REJ_STALE)
    fail = ctx.rng.bernoulli(site=40, p=cfg.auth_fail_p)
    code = ctx.rng.categorical(site=41, p=(0.45, 0.3, 0.15, 0.1))
    method = ctx.rng.categorical(site=42, p=(0.7, 0.22, 0.08))
    if not out.reserve(records={"payment_authorized": 1, "payment_failed": 1,
                                "order_placed": 1, "checkout_failed": 1},
                       creates={"order": 1}, requests=1):
        return RETRY
    amount = std.checked_mul(loc.cart_price, loc.cart_qty)
    group = ctx.reads.sku.sku_group[loc.cart_sku]
    if fail:
        out.emit_payment_failed(ctx.t, user_id=ctx.self_id, checkout_id=loc.checkout,
                                amount=amount, decline_code=code)
        out.send_release(ctx.t, to=group, tag=loc.checkout, sku_id=loc.cart_sku,
                         quantity=loc.cart_qty)
        out.emit_checkout_failed(ctx.t, user_id=ctx.self_id, checkout_id=loc.checkout,
                                 reason="payment_declined", sku_id=loc.cart_sku)
    else:
        out.emit_payment_authorized(ctx.t, user_id=ctx.self_id, checkout_id=loc.checkout,
                                    amount=amount, method=method)
        out.send_commit(ctx.t, to=group, tag=loc.checkout, sku_id=loc.cart_sku,
                        quantity=loc.cart_qty)
        order = out.create_order(sku_id=loc.cart_sku, quantity=loc.cart_qty, amount=amount)
        out.emit_order_placed(ctx.t, user_id=ctx.self_id, order_id=order,
                              checkout_id=loc.checkout, device_id=loc.device,
                              sku_id=loc.cart_sku, quantity=loc.cart_qty, amount=amount,
                              category=ctx.reads.sku.category[loc.cart_sku])
    loc.checkout = std.NULL
    loc.cart_n = 0
    return COMMIT


@kernel(state="inventory", commands=(C_RESERVE, C_COMMIT, C_RELEASE),
        max=Res(records={"stock_reserved": 1, "stock_rejected": 1, "stock_committed": 1,
                         "stock_released": 1}, requests=1))
def inventory_desk(ctx, s, cmd, out):
    i = ctx.reads.sku.local_index[cmd.sku_id]
    if not out.reserve(records={"stock_reserved": 1, "stock_rejected": 1,
                                "stock_committed": 1, "stock_released": 1}, requests=1):
        return RETRY
    if cmd.kind == C_RESERVE:                              # decided at the request's time (D6)
        if s.on_hand[i] - s.reserved[i] >= cmd.quantity:
            s.reserved[i] = std.checked_add(s.reserved[i], cmd.quantity)
            out.emit_stock_reserved(ctx.t, sku_group=ctx.self_id, sku_id=cmd.sku_id,
                                    checkout_id=cmd.tag, quantity=cmd.quantity)
            out.respond(cmd, "granted")
        else:
            out.emit_stock_rejected(ctx.t, sku_group=ctx.self_id, sku_id=cmd.sku_id,
                                    checkout_id=cmd.tag, quantity=cmd.quantity)
            out.respond(cmd, "rejected")
        return COMMIT
    s.reserved[i] = std.checked_sub(s.reserved[i], cmd.quantity)
    if cmd.kind == C_COMMIT:
        s.on_hand[i] = std.checked_sub(s.on_hand[i], cmd.quantity)
        out.emit_stock_committed(ctx.t, sku_group=ctx.self_id, sku_id=cmd.sku_id,
                                 checkout_id=cmd.tag, quantity=cmd.quantity,
                                 on_hand_after=s.on_hand[i])
    else:
        out.emit_stock_released(ctx.t, sku_group=ctx.self_id, sku_id=cmd.sku_id,
                                checkout_id=cmd.tag, quantity=cmd.quantity)
    return COMMIT


@kernel(state="inventory", commands=(START,), max=Res(records={"restocked": 64}, timers=1),
        substep=64)
def restock(ctx, s, cmd, out):
    """Weekly restock of one inventory group, 64 SKUs per sub-step, continued at top priority."""
    start = cmd.cursor
    stop = min(start + 64, s.n_sku)
    if not out.reserve(records={"restocked": 64}, timers=1):
        return RETRY
    for i in range(start, stop):
        gap = ctx.reads.sku.stock_target[s.sku[i]] - s.on_hand[i]
        if gap > 0:
            qty = 1 + ctx.rng.uniform_int(site=1, lo=0, hi=gap - 1)     # suppliers short-ship
            s.on_hand[i] = std.checked_add(s.on_hand[i], qty)
            out.emit_restocked(ctx.t, sku_group=ctx.self_id, sku_id=s.sku[i], quantity=qty,
                               on_hand_after=s.on_hand[i])
    if stop < s.n_sku:
        out.continue_at(ctx.t, cursor=stop)
    return COMMIT
```

`examples/ecommerce_s1/specs/brief.md`: a short brief: the shopper/catalog/inventory parts of `examples/ecommerce/specs/brief.md` (sessions, one-line carts, single-SKU checkout, payment auth ~3% failures, weekly restock), plus a "Scope" paragraph naming what is left for `examples/ecommerce` at M3 (multi-line carts, fulfillment, returns, referrals, overlays). `README.md`: model table (partitions, processes), events list, the run/validate/schema/replay commands with `examples/ecommerce_s1`.

- [ ] **Step 2: Write the failing tests**

`apps/datagen/tests/test_example_ecom_s1.py`:
```python
from pathlib import Path

import polars as pl
import pytest

from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events
from neorisk_simkit.spec.project import load_project, resolve_run
from neorisk_simkit.spec.validate import validate

EX = Path(__file__).resolve().parents[3] / "examples" / "ecommerce_s1"
SMALL = ["users=3000", "skus=1200", "sku_groups=8", "run.span=7d", "run.warmup=1d"]


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    return run_to_dataset(EX, "sample", SMALL, out_dir=tmp_path_factory.mktemp("ecom") / "run",
                          threads=4)


@pytest.fixture(scope="module")
def ev(run):
    return read_events(run.out_dir)


def test_project_validates():
    for profile in ("sample", "full"):
        rep = validate(resolve_run(load_project(EX), profile, []))
        assert rep.ok, rep.errors


def test_product_viewed_has_twelve_property_columns(ev):
    assert len(ev["product_viewed"].columns) - 8 == 12


def test_each_checkout_has_at_most_one_outcome(ev):
    outcomes = pl.concat([ev["order_placed"].select("checkout_id"),
                          ev["checkout_failed"].select("checkout_id")])
    assert outcomes.group_by("checkout_id").len()["len"].max() == 1
    started = set(ev["checkout_started"]["checkout_id"])
    resolved = started & set(outcomes["checkout_id"])
    assert len(resolved) >= 0.95 * len(started)


def test_shard_decides_at_request_time(ev):
    j = ev["checkout_started"].join(
        pl.concat([ev["stock_reserved"], ev["stock_rejected"]]).select(
            "checkout_id", pl.col("event_time").alias("decided")), on="checkout_id")
    assert j.height > 0 and (j["event_time"] == j["decided"]).all()


def test_stock_never_negative_and_reservations_resolved(ev):
    for t in ("stock_committed", "restocked"):
        assert ev[t]["on_hand_after"].min() >= 0
    reserved = set(ev["stock_reserved"]["checkout_id"])
    done = set(ev["stock_committed"]["checkout_id"]) | set(ev["stock_released"]["checkout_id"])
    assert len(reserved - done) <= 0.02 * len(reserved)       # only checkouts open at the end


def test_restock_uses_continuations(run, ev):
    assert ev["restocked"].height > 0
    assert run.stats["continuations"] > 0          # 150 SKUs per group: 3 sub-steps of 64


def test_recipe_built_tables_are_exported(run):
    dev = pl.read_parquet(run.out_dir / "entities/device/part-00000.parquet")
    assert dev.height >= 3000 and set(dev["origin"]) == {"static"}
    assert pl.read_parquet(run.out_dir / "entities/sku/part-00000.parquet").height == 1200


def test_rates_are_plausible(ev):
    sessions, checkouts = ev["session_started"].height, ev["checkout_started"].height
    assert 0.01 < checkouts / sessions < 0.30
    oos = ev["checkout_failed"].filter(pl.col("reason") == "out_of_stock").height
    assert oos / checkouts < 0.25
```

- [ ] **Step 3: Run tests to verify they fail, then implement `std.sources`**

Run: `uv run --all-packages pytest apps/datagen/tests/test_example_ecom_s1.py -v`
Expected: FAIL with `AttributeError: module 'neorisk_simkit.std' has no attribute 'catalog'`.

Implement `std/sources.py` (pack-time numpy code using `rng.uniforms` streams keyed by table/recipe name; nothing here runs in kernels):
- `catalog`: columns from the dists (category codes, price via `lognormal_minor`, `sku_group` via `uniform_int`); weights `zipf(s)` over a keyed random permutation of rows; `cumw` = normalized cumulative weights (float64). `sample_by_weight(cumw, u)` in Task 6/8 is `np.searchsorted(cumw, u, side="right")`.
- `devices`: per user `m ~ per_user` devices; kinds drawn from `kinds` (default `{"phone": .55, "tablet": .10, "desktop": .35}`), `os` consistent with kind (phone/tablet → ios/android, desktop → windows/macos/linux), `first_seen` = owner arrival time; household sharing: with probability `share` append one device of the previous user in ordinal order. CSR `(offs int64[n_users+1], idx int64[total])`.
- `stock`: `on_hand = negbinom(mean, disp)` scaled by `1 + by_weight * w / w.max()`, cast to int32; `stock_target = on_hand` copy exposed through the recipe protocol (`read_column_names("sku") == ("stock_target",)`, `extra_read_columns("sku") == {"stock_target": …}`).
- `devices`: `table_rows("device")` returns the generated device rows; `read_column_names` returns `()`.
- Engine wiring (Files above): `layout.kernel_layouts` collects recipes from `plan.populations[*].refs` and `plan.partitions[*].init`; `World.build` and `Simulation.static_entities` call the protocol methods. No other engine change.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --all-packages pytest apps/datagen/tests/test_example_ecom_s1.py -v`
Expected: PASS (8 tests). If a rate test fails, tune `Journey` defaults (not the test bounds) and note the change in the commit body.

- [ ] **Step 5: Lint and commit**

Run: `uv run ruff check $(ls -d libs apps examples/ecommerce_s1 benchmarks 2>/dev/null)`
```bash
git add examples/ecommerce_s1 examples/README.md libs/simkit/src/neorisk_simkit/std libs/simkit/src/neorisk_simkit/engine/layout.py libs/simkit/src/neorisk_simkit/engine/world.py libs/simkit/src/neorisk_simkit/engine/run.py apps/datagen/tests/test_example_ecom_s1.py
git commit -m "examples: ecommerce_s1 slice (sessions, carts, single-SKU checkout, inventory shards)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 15: Cross-device KYC with `std.handoff` and the `user_kyc` change group

**Files:**
- Create: `libs/simkit/src/neorisk_simkit/std/handoff.py`; Modify: `std/__init__.py` (export `handoff`)
- Modify: `examples/ecommerce_s1/specs/pack.py`, `examples/ecommerce_s1/specs/kernels.py`, `examples/ecommerce_s1/README.md`
- Test: `libs/simkit/tests/test_std_handoff.py`, `apps/datagen/tests/test_example_ecom_s1_kyc.py`

**Interfaces:**
- Consumes: Task 14 project; Task 8 `_change_<g>` emitter; `PRIO_EXPIRY`; Task 11 seal rule that warm-up steps drop `history` rows as well as events (so exported history rows equal exported `kyc_completed` rows); Task 2/3 `std` package (`std/__init__.py` gains `handoff`).
- Produces:
  - `std.handoff` (`@njit(cache=True)`): status constants `NONE = 0, OPEN = 1, REDEEMED = 2, EXPIRED = 3, DONE = 4`; outcome constants `OK = 0, REJ_EXPIRED = 1, REJ_ALREADY = 2, REJ_UNKNOWN = 3`; `redeem(status, expires_at, t, token, presented) -> int` (`presented != token` → `REJ_UNKNOWN`; `status == REDEEMED or status == DONE` → `REJ_ALREADY`; `status == EXPIRED or t >= expires_at` → `REJ_EXPIRED`; `status == OPEN` → `OK`); `expire(status) -> int` (`OPEN` → `EXPIRED`, else unchanged).
  - Pack additions: `p.ids("flow")`; user columns `kyc_level: i16()`, `kyc_device: opt(ref("device"))`; `p.change_group("user_kyc", table="user", cols=["kyc_level", "kyc_device"])`; events `kyc_started(user_id, flow_id, session_id, device_id, expires_at: ts)`, `kyc_handoff_redeemed(user_id, flow_id, device_id)`, `kyc_handoff_rejected(user_id, flow_id, device_id, reason: cat("expired", "already_redeemed"))`, `kyc_handoff_expired(user_id, flow_id)`, `kyc_completed(user_id, flow_id, session_id, device_id, scan_device_id)`.
  - `Journey` additions: `kyc_start_p: float = 0.05`, `kyc_expiry_s: int = 300`, `kyc_redeem_delay: dist.Dist = dist.lognormal(median_s=90, sigma=0.8)`, `kyc_late_scan_p: float = 0.02` (scan lands exactly at expiry), `kyc_duplicate_p: float = 0.03`, `kyc_duplicate_gap: dist.Dist = dist.exp(mean_s=20)`, `kyc_face_delay: dist.Dist = dist.lognormal(median_s=40, sigma=0.5)`.
  - Kernel additions in `shopper`: commands `C_KYC_REDEEM = 7`, `C_KYC_EXPIRE = 8`, `C_KYC_FACE = 9`; local fields `kyc_flow="ref"`, `kyc_session="ref"`, `kyc_desktop="ref"`, `kyc_phone="ref"`, `kyc_expires="i64"`, `kyc_status="i8"`; `max` gains the five KYC records, `user_kyc`, `creates={"flow": 1}`, `timers=5`.

Flow (D28): in `_session`, after `session_started`, when `s.kyc_level == 0`, `loc.kyc_status == NONE`, the session device is a desktop, the user owns a phone (first device of kind `phone` in `ctx.refs.device`), and `bernoulli(kyc_start_p)`: create `flow`, set `kyc_*` locals (`kyc_status = OPEN`, `kyc_expires = t + expiry`), emit `kyc_started`, schedule `C_KYC_EXPIRE` at `kyc_expires` with `PRIO_EXPIRY` and `C_KYC_REDEEM` at `t + redeem_delay` (or exactly `kyc_expires` with probability `kyc_late_scan_p`) with `PRIO_TIMER`, both `tag = flow`; with probability `kyc_duplicate_p` a second `C_KYC_REDEEM` at the first redemption time + `kyc_duplicate_gap`. `C_KYC_EXPIRE`: if `expire(status)` changes it → emit `kyc_handoff_expired`, else `reject`. `C_KYC_REDEEM`: `handoff.redeem(...)` → `OK`: status `REDEEMED`, emit `kyc_handoff_redeemed` on the phone, schedule `C_KYC_FACE`; `REJ_EXPIRED`/`REJ_ALREADY`: emit `kyc_handoff_rejected` with that reason on the phone; `REJ_UNKNOWN`: `reject`. `C_KYC_FACE`: status `DONE`, emit `kyc_completed` on the desktop (`device_id`) with `scan_device_id` = phone, and `out.change_user_kyc(ctx.t, kyc_level=1, kyc_device=phone)`. Because `PRIO_EXPIRY < PRIO_TIMER`, a scan at exactly the expiry instant runs after the expiry and is rejected as expired (§06).

- [ ] **Step 1: Write the failing tests**

`libs/simkit/tests/test_std_handoff.py`:
```python
import numba

from neorisk_simkit.std import handoff as h


def test_redeem_outcomes():
    assert h.redeem(h.OPEN, 1_000, 999, 7, 7) == h.OK
    assert h.redeem(h.OPEN, 1_000, 1_000, 7, 7) == h.REJ_EXPIRED       # exactly at expiry
    assert h.redeem(h.EXPIRED, 1_000, 10, 7, 7) == h.REJ_EXPIRED
    assert h.redeem(h.REDEEMED, 1_000, 10, 7, 7) == h.REJ_ALREADY
    assert h.redeem(h.DONE, 1_000, 10, 7, 7) == h.REJ_ALREADY
    assert h.redeem(h.OPEN, 1_000, 10, 7, 8) == h.REJ_UNKNOWN          # token bound to the flow


def test_expire_only_from_open():
    assert h.expire(h.OPEN) == h.EXPIRED
    assert h.expire(h.REDEEMED) == h.REDEEMED and h.expire(h.NONE) == h.NONE


def test_compiled_matches_python():
    f = numba.njit(lambda s, e, t: h.redeem(s, e, t, 1, 1))
    for args in [(h.OPEN, 5, 4), (h.OPEN, 5, 5), (h.REDEEMED, 5, 1)]:
        assert f(*args) == h.redeem.py_func(*args, 1, 1)
```

`apps/datagen/tests/test_example_ecom_s1_kyc.py`:
```python
from pathlib import Path

import polars as pl
import pytest

from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events

EX = Path(__file__).resolve().parents[3] / "examples" / "ecommerce_s1"
SMALL = ["users=2000", "skus=200", "sku_groups=4", "run.span=5d", "run.warmup=1d",
         "journey.kyc_start_p=0.5"]


def _run(tmp_path, *extra):
    r = run_to_dataset(EX, "sample", SMALL + list(extra), out_dir=tmp_path / "run", threads=2)
    return r, read_events(r.out_dir)


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    return _run(tmp_path_factory.mktemp("kyc"))


def test_cross_device_flow(base):
    r, ev = base
    started, done = ev["kyc_started"], ev["kyc_completed"]
    assert started.height > 0 and done.height > 0
    devices = pl.read_parquet(r.out_dir / "entities/device/part-00000.parquet")
    kind = dict(zip(devices["id"], devices["kind"]))
    assert all(kind[d] == "desktop" for d in started["device_id"])
    redeemed = ev["kyc_handoff_redeemed"]
    assert all(kind[d] == "phone" for d in redeemed["device_id"])
    j = done.join(started.select("flow_id", pl.col("session_id").alias("s0")), on="flow_id")
    assert (j["session_id"] == j["s0"]).all()                 # callback to the desktop session
    assert (j["device_id"] != j["scan_device_id"]).all()


def test_change_group_written(base):
    r, ev = base
    hist = pl.read_parquet(sorted((r.out_dir / "history" / "user_kyc").rglob("*.parquet")))
    assert hist.height == ev["kyc_completed"].height
    assert hist.columns[:5] == ["entity_id", "valid_from", "lamport", "partition_id", "seq"]
    assert (hist["kyc_level"] == 1).all()


def test_scan_exactly_at_expiry_counts_as_expired(tmp_path):
    _, ev = _run(tmp_path, "journey.kyc_late_scan_p=1.0", "journey.kyc_duplicate_p=0.0")
    exp, rej = ev["kyc_handoff_expired"], ev["kyc_handoff_rejected"]
    assert ev["kyc_handoff_redeemed"].height == 0 and exp.height > 0
    j = rej.join(exp.select("flow_id", pl.col("event_time").alias("t_exp")), on="flow_id")
    assert (j["reason"] == "expired").all() and (j["event_time"] == j["t_exp"]).all()
    started = ev["kyc_started"].select("flow_id", "expires_at")
    k = exp.join(started, on="flow_id")
    assert (k["event_time"] == k["expires_at"]).all()


def test_second_redemption_is_already_redeemed(tmp_path):
    _, ev = _run(tmp_path, "journey.kyc_duplicate_p=1.0", "journey.kyc_late_scan_p=0.0")
    rej = ev["kyc_handoff_rejected"]
    assert rej.height > 0 and set(rej["reason"]) <= {"already_redeemed", "expired"}
    assert (rej["reason"] == "already_redeemed").sum() > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --all-packages pytest libs/simkit/tests/test_std_handoff.py apps/datagen/tests/test_example_ecom_s1_kyc.py -v`
Expected: FAIL (`ImportError: cannot import name 'handoff'`).

- [ ] **Step 3: Implement**

Write `std/handoff.py`, then extend the pack and the `shopper` kernel exactly as the flow above (add `_kyc_start`, `_kyc_expire`, `_kyc_redeem`, `_kyc_face` helpers; new site numbers 50–59; the `_session` reservation becomes `records={"session_started": 1, "kyc_started": 1}, creates={"session": 1, "flow": 1}, timers=5`). Kernels call `std.handoff.redeem(...)`/`std.handoff.expire(...)`; Task 6 lowering leaves `std.*` calls untouched. Update the README event list.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --all-packages pytest libs/simkit/tests/test_std_handoff.py apps/datagen/tests/test_example_ecom_s1_kyc.py apps/datagen/tests/test_example_ecom_s1.py -v`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

Run: `uv run ruff check $(ls -d libs apps examples/ecommerce_s1 benchmarks 2>/dev/null)`
```bash
git add libs/simkit/src/neorisk_simkit/std examples/ecommerce_s1 libs/simkit/tests/test_std_handoff.py apps/datagen/tests/test_example_ecom_s1_kyc.py
git commit -m "examples: cross-device KYC kernel with std.handoff and the user_kyc change group

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 16: Exit test — the recurring-shopper trace (§07) as a fixture

**Files:**
- Modify: `libs/simkit/src/neorisk_simkit/spec/sources.py` (add `rows(**cols: list)` explicit-rows source), `libs/simkit/src/neorisk_simkit/std/__init__.py` (export it: `from neorisk_simkit.spec.sources import generated, rows`)
- Create fixture: `libs/simkit/tests/fixtures/trace_shopper/{datagen.toml,specs/pack.py,specs/kernels.py}`
- Test: `libs/simkit/tests/test_exit_trace_shopper.py`

**Interfaces:**
- Consumes: Task 12 `run_to_dataset`, `read_events`, `run_stats.json["round_detail"]`; owner creation (Task 10); one-way messages (D6).
- Produces: `std.rows(**cols)` (all lists equal length; `n` = that length); the §07 trace exit test.

- [ ] **Step 1: Create the fixture**

`fixtures/trace_shopper/datagen.toml`: copy of mini's with `name = "trace_shopper"`, `start = "2026-03-02T10:00:00Z"`, `warmup = "0s"`, `span = "5m"`, `[engine] step = "5m"`, `adapt = false`, `parallel_min_partitions = 64`, `[profiles.sample] set = {}`.

`fixtures/trace_shopper/specs/pack.py`:
```python
"""Spec §07: a recurring shopper buying two SKUs. Shards A, B, C hold 1, 0, 1 units."""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, dist, std
from neorisk_simkit.spec.types import amount, cat, i16, opt, ref

from . import kernels as k

PACK = "trace_shopper"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Config:
    spend_limit: int = 100
    hold: int = 80
    substitute_after_us: int = 129_700_000          # 10:00:00.3 -> 10:02:10.0


def define(p: Pack, cfg: Config) -> None:
    sku = p.table("sku", key="sku_id", cols={"sku_group": i16(), "label": cat("A", "B", "C")},
                  source=std.rows(sku_group=[0, 1, 2], label=["A", "B", "C"]))
    user = p.table("user", key="user_id", mutable=True, cols={
        "spend_limit": amount(asset="USD"), "hold": amount(asset="USD"),
        "spent": amount(asset="USD")})
    payment = p.table("payment", key="payment_id", mutable=True, cols={
        "user_id": ref("user"), "amount": amount(asset="USD")})
    p.ids("checkout")
    p.owner("user", table=user, max_live=1)
    p.owner("payment", table=payment, max_live=4)
    p.population(user, n=1, initial=1.0)
    inv = p.shard("inventory", key="sku_group", n=3, items=sku,
                  state={"on_hand": "i32[sku]", "reserved": "i32[sku]"},
                  init={"on_hand": [1, 0, 1]})
    lat = dist.constant(ms=300)
    line = {"sku_id": ref("sku")}
    reserve = p.request("reserve", frm="user", to=inv, payload=line, response_payload=line,
                        responses=("granted", "rejected"), latency=lat)
    release = p.message("release", frm="user", to=inv, payload=line, latency=lat)
    commit = p.message("commit", frm="user", to=inv, payload=line, latency=lat)
    u = {"user_id": ref("user"), "checkout_id": ref("checkout")}
    p.event("checkout_started", owner="user", cols={**u, "lines": i16(),
                                                    "hold_after": amount(asset="USD")})
    p.event("checkout_failed", owner="user", cols={
        **u, "reason": cat("out_of_stock"), "sku_id": opt(ref("sku")),
        "hold_after": amount(asset="USD")})
    p.event("checkout_succeeded", owner="user", cols={
        **u, "payment_id": ref("payment"), "spent_after": amount(asset="USD")})
    p.event("payment_created", owner="payment", cols={
        "payment_id": ref("payment"), "user_id": ref("user"), "amount": amount(asset="USD")})
    stock = {"sku_id": ref("sku"), "checkout_id": ref("checkout")}
    for name in ("stock_reserved", "stock_rejected", "stock_released", "stock_committed"):
        p.event(name, shard="inventory", cols=stock)
    p.process("journey", owner="user", kernel=k.journey, config=cfg,
              start=p.on_created("user"), requests={"reserve": reserve},
              messages={"release": release, "commit": commit},
              on_response={("reserve", "granted"): k.R_GRANTED,
                           ("reserve", "rejected"): k.R_REJECTED},
              reads={"sku": sku}, commands=k.JOURNEY_COMMANDS)
    p.process("payment_start", owner="payment", kernel=k.payment_start,
              start=p.on_created("payment"), commands=(0,))
    p.process("desk", shard=inv, kernel=k.desk, on_request={"reserve": k.C_RESERVE},
              on_message={"release": k.C_RELEASE, "commit": k.C_COMMIT}, reads={"sku": sku})
```

`fixtures/trace_shopper/specs/kernels.py`:
```python
from neorisk_simkit import std
from neorisk_simkit.engine import COMMIT, PRIO_TIMER, RETRY, START, Local, Res, kernel, reject

C_SUBSTITUTE, R_GRANTED, R_REJECTED = 1, 2, 3
JOURNEY_COMMANDS = (START, C_SUBSTITUTE, R_GRANTED, R_REJECTED)
C_RESERVE, C_RELEASE, C_COMMIT = 1, 2, 3
SKU_A, SKU_B, SKU_C = 0, 1, 2
REJ_LIMIT, REJ_STALE = 1, 2

LOCAL = Local(checkout="ref", pending="i8", granted="u8", failed_sku="ref", lines="i8",
              sku="ref[2]")


@kernel(state="user", local=LOCAL, commands=JOURNEY_COMMANDS,
        max=Res(records={"checkout_started": 1, "checkout_failed": 1, "checkout_succeeded": 1},
                creates={"checkout": 1, "payment": 1}, timers=1, requests=3))
def journey(ctx, s, loc, cmd, out):
    cfg = ctx.cfg
    if cmd.kind == START:                                 # 10:00:00.0: check out A and B
        return _start_checkout(ctx, s, loc, out, cfg, SKU_A, SKU_B, 2)
    if cmd.kind == C_SUBSTITUTE:                          # 10:02:10.0: substitute C
        return _start_checkout(ctx, s, loc, out, cfg, SKU_C, SKU_C, 1)
    return _on_response(ctx, s, loc, cmd, out, cfg)


def _start_checkout(ctx, s, loc, out, cfg, a, b, lines):
    limit = cfg.spend_limit
    if limit - s.hold - s.spent < cfg.hold:               # validate the owner side first
        return reject(REJ_LIMIT)
    if not out.reserve(records={"checkout_started": 1}, creates={"checkout": 1},
                       requests=lines):
        return RETRY
    s.spend_limit = limit
    s.hold = std.checked_add(s.hold, cfg.hold)            # the owner holds its side
    loc.checkout = out.new_id("checkout")
    loc.pending, loc.granted, loc.failed_sku, loc.lines = lines, 0, std.NULL, lines
    loc.sku[0] = a
    loc.sku[1] = b
    out.emit_checkout_started(ctx.t, user_id=ctx.self_id, checkout_id=loc.checkout,
                              lines=lines, hold_after=s.hold)
    for j in range(lines):                                # immutable payloads, one per shard
        out.request_reserve(ctx.t, shard=ctx.reads.sku.sku_group[loc.sku[j]],
                            tag=loc.checkout, sku_id=loc.sku[j])
    return COMMIT                                         # suspends: join of `lines`


def _line_of(loc, sku_id):
    if loc.sku[0] == sku_id:
        return 0
    return 1


def _on_response(ctx, s, loc, cmd, out, cfg):
    if cmd.tag != loc.checkout or loc.pending == 0:
        return reject(REJ_STALE)
    if not out.reserve(records={"checkout_failed": 1, "checkout_succeeded": 1},
                       creates={"payment": 1}, timers=1, requests=2):
        return RETRY
    if cmd.kind == R_GRANTED:
        loc.granted |= 1 << _line_of(loc, cmd.sku_id)
    else:
        loc.failed_sku = cmd.sku_id
    loc.pending -= 1
    if loc.pending > 0:
        return COMMIT
    if loc.granted == (1 << loc.lines) - 1:               # every line granted: commit all
        s.hold = std.checked_sub(s.hold, cfg.hold)
        s.spent = std.checked_add(s.spent, cfg.hold)
        for j in range(loc.lines):
            out.send_commit(ctx.t, to=ctx.reads.sku.sku_group[loc.sku[j]], tag=loc.checkout,
                            sku_id=loc.sku[j])
        pay = out.create_payment(user_id=ctx.self_id, amount=cfg.hold)
        out.emit_checkout_succeeded(ctx.t, user_id=ctx.self_id, checkout_id=loc.checkout,
                                    payment_id=pay, spent_after=s.spent)
    else:                                                 # release all, release the hold
        s.hold = std.checked_sub(s.hold, cfg.hold)
        for j in range(loc.lines):
            if loc.granted & (1 << j):
                out.send_release(ctx.t, to=ctx.reads.sku.sku_group[loc.sku[j]],
                                 tag=loc.checkout, sku_id=loc.sku[j])
        out.emit_checkout_failed(ctx.t, user_id=ctx.self_id, checkout_id=loc.checkout,
                                 reason="out_of_stock", sku_id=loc.failed_sku,
                                 hold_after=s.hold)
        out.timer(ctx.t + cfg.substitute_after_us, C_SUBSTITUTE, prio=PRIO_TIMER)
    loc.checkout = std.NULL
    return COMMIT


@kernel(state="payment", commands=(START,), max=Res(records={"payment_created": 1}))
def payment_start(ctx, s, cmd, out):
    if not out.reserve(records={"payment_created": 1}):
        return RETRY
    out.emit_payment_created(ctx.t, payment_id=ctx.self_id, user_id=s.user_id, amount=s.amount)
    return COMMIT


@kernel(state="inventory", commands=(C_RESERVE, C_RELEASE, C_COMMIT),
        max=Res(records={"stock_reserved": 1, "stock_rejected": 1, "stock_released": 1,
                         "stock_committed": 1}, requests=1))
def desk(ctx, s, cmd, out):
    i = ctx.reads.sku.local_index[cmd.sku_id]
    if not out.reserve(records={"stock_reserved": 1, "stock_rejected": 1,
                                "stock_released": 1, "stock_committed": 1}, requests=1):
        return RETRY
    if cmd.kind == C_RESERVE:
        if s.on_hand[i] - s.reserved[i] >= 1:
            s.reserved[i] += 1
            out.emit_stock_reserved(ctx.t, sku_id=cmd.sku_id, checkout_id=cmd.tag)
            out.respond(cmd, "granted", sku_id=cmd.sku_id)
        else:
            out.emit_stock_rejected(ctx.t, sku_id=cmd.sku_id, checkout_id=cmd.tag)
            out.respond(cmd, "rejected", sku_id=cmd.sku_id)
        return COMMIT
    s.reserved[i] -= 1
    if cmd.kind == C_COMMIT:
        s.on_hand[i] -= 1
        out.emit_stock_committed(ctx.t, sku_id=cmd.sku_id, checkout_id=cmd.tag)
    else:
        out.emit_stock_released(ctx.t, sku_id=cmd.sku_id, checkout_id=cmd.tag)
    return COMMIT
```
`s.spend_limit` is written only after `reserve` succeeds: a write before it would violate the ABI (checked mode would fail the run).

- [ ] **Step 2: Write the failing test**

`libs/simkit/tests/test_exit_trace_shopper.py`:
```python
"""Spec §07 exit test: the recurring-shopper trace, reproduced record by record."""

import json

import polars as pl
import pytest

from conftest import FIXTURES
from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events


@pytest.fixture(scope="module")
def trace(tmp_path_factory):
    r = run_to_dataset(FIXTURES / "trace_shopper", "sample",
                       out_dir=tmp_path_factory.mktemp("trace") / "run", threads=1)
    ev = read_events(r.out_dir)
    rows = pl.concat([t.select("event_time", "lamport", "partition_id", "seq", "event_type")
                      for t in ev.values()]).sort("event_time", "lamport", "partition_id", "seq")
    return r, ev, rows


def test_records_in_canonical_order(trace):
    _, _, rows = trace
    got = [(t.strftime("%M:%S.%f")[:-3], e) for t, e in zip(rows["event_time"], rows["event_type"])]
    assert got == [
        ("00:00.000", "checkout_started"),       # U holds 80, sends reserve(A), reserve(B)
        ("00:00.000", "stock_reserved"),         # shard A grants (decision at request time)
        ("00:00.000", "stock_rejected"),         # shard B: out of stock
        ("00:00.300", "checkout_failed"),        # responses arrive: release hold, release(A)
        ("00:00.600", "stock_released"),
        ("02:10.000", "checkout_started"),       # substitute SKU C
        ("02:10.000", "stock_reserved"),
        ("02:10.300", "checkout_succeeded"),     # commit hold, commit(C), create payment P
        ("02:10.300", "payment_created"),        # P starts in the next round
        ("02:10.600", "stock_committed"),
    ]


def test_hold_is_released_then_committed(trace):
    _, ev, _ = trace
    assert ev["checkout_started"]["hold_after"].to_list() == [80, 80]
    assert ev["checkout_failed"]["hold_after"].to_list() == [0]
    assert ev["checkout_succeeded"]["spent_after"].to_list() == [80]
    assert ev["checkout_failed"]["sku_id"].to_list() == ev["stock_rejected"]["sku_id"].to_list()


def test_partitions_and_clocks(trace):
    _, ev, rows = trace
    user_pid = ev["checkout_started"]["partition_id"][0]
    shard_pids = set(rows.filter(pl.col("event_type").str.starts_with("stock"))["partition_id"])
    assert len(shard_pids) == 3 and user_pid not in shard_pids
    pay_pid = ev["payment_created"]["partition_id"][0]
    assert pay_pid not in shard_pids | {user_pid}
    assert ev["payment_created"]["payment_id"][0] == ev["checkout_succeeded"]["payment_id"][0]
    first = rows.filter(pl.col("event_time") == rows["event_time"][0])
    assert first["lamport"].to_list() == [1, 2, 2]          # responses carry larger clocks


def test_rounds_within_one_step(trace):
    r, _, _ = trace
    stats = json.loads((r.out_dir / "run_stats.json").read_text())
    assert stats["rounds_per_step"] == [4]                  # U's journey: rounds 1-3; P: round 4
    detail = stats["round_detail"][0]
    assert detail["owners_run"] == [1, 1, 1, 1]
    assert detail["shard_cmds"] == [2, 2, 0, 1]
```

- [ ] **Step 3: Run the test**

Run: `uv run --all-packages pytest libs/simkit/tests/test_exit_trace_shopper.py -v`
Expected: FAIL first (`AttributeError: ... has no attribute 'rows'`), then PASS (4 tests) after adding `std.rows` and the fixture. A mismatch in `shard_cmds` means the horizon ignores pending creations (D5) or messages suspend the sender (D6) — fix the engine, not the expectation.

- [ ] **Step 4: Lint and commit**

Run: `uv run ruff check $(ls -d libs apps examples/ecommerce_s1 benchmarks 2>/dev/null)`
```bash
git add libs/simkit/src/neorisk_simkit/spec/sources.py libs/simkit/src/neorisk_simkit/std/__init__.py libs/simkit/tests/fixtures/trace_shopper libs/simkit/tests/test_exit_trace_shopper.py
git commit -m "test: S1 exit test - recurring-shopper trace fixture (spec section 07)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 17: Exit test — thread, slab and step invariance (and identical replay of the slice)

**Files:**
- Test: `libs/simkit/tests/test_exit_invariance.py`

**Interfaces:**
- Consumes: Task 12 `run_to_dataset`, `read_events`, `load_schema`, conftest `event_dicts`; Task 3 conftest `dataset_tree`; Task 9 full-outbox handling (`World.pending_outbox`, so the 16KB-slab runs, about 85 outbox rows per worker, make progress); Task 15 slice project.
- Produces: the §10/§12 invariance exit test and the helper `canonicalize_ids(d: Path) -> dict[str, list[dict]]` (test-local; reads the dataset's events and `schema.json` itself).

- [ ] **Step 1: Write the test**

`libs/simkit/tests/test_exit_invariance.py`:
```python
"""Spec §10/§12 exit test: identical logical records across 1, 4 and 16 threads, two slab sizes
and two step lengths; identical replay is byte-identical."""

import itertools
from pathlib import Path

import polars as pl
import pytest

from conftest import dataset_tree, event_dicts
from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events
from neorisk_simkit.io.schema.schema_json import load_schema

EX = Path(__file__).resolve().parents[3] / "examples" / "ecommerce_s1"
SMALL = ["users=1500", "skus=300", "sku_groups=8", "run.span=4d", "run.warmup=1d",
         "journey.kyc_start_p=0.3", "engine.adapt=false"]
THREADS = (1, 4, 16)
SLABS = ("8MB", "16KB")             # 16KB forces constant slab swaps (RETRY path)
STEPS = ("6h", "1d")
KEY = ["event_time", "lamport", "partition_id", "seq"]


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    root = tmp_path_factory.mktemp("inv")
    out = {}
    for threads, slab, step in itertools.product(THREADS, SLABS, STEPS):
        d = root / f"t{threads}-{slab}-{step}"
        run_to_dataset(EX, "sample", SMALL + [f"engine.slab_bytes={slab!r}",
                                              f"engine.step={step!r}"],
                       out_dir=d, threads=threads,
                       engine_overrides={"parallel_min_partitions": 1})
        out[(threads, slab, step)] = d
    return out


def canonicalize_ids(d: Path) -> dict[str, list[dict]]:
    """Rename every ID namespace by first appearance in global canonical order (D13)."""
    schema, events = load_schema(d), read_events(d)
    refs = {t["name"]: {c["name"]: c["ref"] for c in t["columns"] if c.get("ref")}
            for t in schema["tables"] if t["kind"] == "event"}
    merged = pl.concat([
        e.select(*KEY, pl.lit(name).alias("_t"), pl.int_range(pl.len()).alias("_i"))
        for name, e in events.items() if e.height], how="vertical").sort(KEY)
    order = {(t, i): n for n, (t, i) in enumerate(zip(merged["_t"], merged["_i"]))}
    rename: dict[str, dict[int, int]] = {}
    out = {}
    for name, e in events.items():
        rows = e.to_dicts()
        for i, row in enumerate(rows):
            row["_pos"] = order[(name, i)]
        out[name] = rows
    flat = sorted((r["_pos"], name, r) for name, rows in out.items() for r in rows)
    for _, name, row in flat:
        for col, ns in refs[name].items():
            v = row[col]
            if v is not None:
                row[col] = rename.setdefault(ns, {}).setdefault(v, len(rename[ns]))
        row["event_id"] = row.pop("_pos")
        row["partition_id"] = rename.setdefault("_pid", {}).setdefault(
            row["partition_id"], len(rename["_pid"]))
    return out


@pytest.mark.parametrize("step", STEPS)
def test_threads_and_slabs_give_identical_records(runs, step):
    base = event_dicts(runs[(1, "8MB", step)])
    assert sum(len(v) for v in base.values()) > 10_000
    for threads, slab in itertools.product(THREADS, SLABS):
        assert event_dicts(runs[(threads, slab, step)]) == base, (threads, slab, step)


def test_step_lengths_give_identical_logical_records(runs):
    assert canonicalize_ids(runs[(1, "8MB", "6h")]) == canonicalize_ids(runs[(4, "16KB", "1d")])


def test_identical_replay_is_byte_identical(runs, tmp_path):
    again = tmp_path / "again"
    run_to_dataset(EX, "sample", SMALL + ["engine.slab_bytes='8MB'", "engine.step='6h'"],
                   out_dir=again, threads=4, engine_overrides={"parallel_min_partitions": 1})
    first = runs[(4, "8MB", "6h")]
    assert dataset_tree(first) == dataset_tree(again)
```
(`partition_id` is renamed only because created-owner IDs may differ by step length (D12); the S1 slice creates no owners, so the rename is a no-op today.)

- [ ] **Step 2: Run the test**

Run: `uv run --all-packages pytest libs/simkit/tests/test_exit_invariance.py -v`
Expected: PASS (4 tests). Any difference is an engine bug (usually: an RNG key that depends on worker, slab or step; an unsorted merge; or a dense ID used in logic). Fix the engine; do not loosen the comparison.

- [ ] **Step 3: Lint and commit**

Run: `uv run ruff check $(ls -d libs apps examples/ecommerce_s1 benchmarks 2>/dev/null)`
```bash
git add libs/simkit/tests/test_exit_invariance.py
git commit -m "test: S1 exit test - thread, slab and step invariance

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 18: Exit test — memory caps enforced

**Files:**
- Modify: `libs/simkit/src/neorisk_simkit/engine/world.py` (add `World.allocated_slab_bytes()`)
- Modify (only if a case fails): `spec/caps.py`, `engine/route.py`, `io/dataset.py`
- Test: `libs/simkit/tests/test_exit_memory_caps.py`

**Interfaces:**
- Consumes: Task 4 caps; runtime cap checks from Tasks 9–12; `io.dataset.ValidationFailed` (`str(e)` joins the report errors); Task 10 `CapExceeded("max_admissions_per_step", …, process=…)` (message ends with `in process <name>`).
- Produces: the §10 exit test and `World.allocated_slab_bytes() -> int` (sum of `nbytes` of every buffer of every worker's `SlabSet`).

- [ ] **Step 1: Write the test**

`libs/simkit/tests/test_exit_memory_caps.py`:
```python
"""Spec §10 exit test: memory caps are enforced. A run whose caps exceed the budget is refused
up front; a run that hits a cap fails with the item named and leaves no dataset."""

import pytest

from conftest import FIXTURES
from neorisk_simkit.engine import CapExceeded
from neorisk_simkit.engine.world import World
from neorisk_simkit.io.dataset import ValidationFailed, run_to_dataset
from neorisk_simkit.spec.caps import compute_caps
from neorisk_simkit.spec.project import load_project, resolve_run

MINI = FIXTURES / "mini"


def test_over_budget_run_is_refused_before_anything_is_written(tmp_path):
    out = tmp_path / "refused"
    with pytest.raises(ValidationFailed, match="exceed the memory budget") as e:
        run_to_dataset(MINI, "sample", ["budget.memory='1MB'"], out_dir=out)
    assert "timer_heaps" in str(e.value) and "step_output" in str(e.value)
    assert not out.exists() and not out.with_suffix(".partial").exists()


@pytest.mark.parametrize("project,overrides,item", [
    (MINI, ["engine.timer_nodes=40"], "timer_heaps"),
    (MINI, ["budget.max_step_rows=20"], "step_output"),
    (MINI, ["max_live=50"], "live_partition_state"),
    (MINI, ["behavior.take_p=1.0", "engine.max_messages_per_step=1"], "requests_and_inboxes"),
    (FIXTURES / "trace_shopper", ["budget.max_admissions_per_step=0"],
     "max_admissions_per_step"),
])
def test_runtime_caps_fail_with_the_item_named(tmp_path, project, overrides, item):
    out = tmp_path / "capped"
    with pytest.raises(CapExceeded) as e:
        run_to_dataset(project, "sample", overrides, out_dir=out)
    assert e.value.item == item and item in str(e.value)
    if item == "max_admissions_per_step":                 # spec §06: names the process
        assert str(e.value).endswith("in process journey")
    assert not out.exists() and not out.with_suffix(".partial").exists()


def test_slab_allocation_stays_within_its_cap():
    run = resolve_run(load_project(MINI), "sample", [])
    caps = {c.name: c for c in compute_caps(run)}
    w = World.build(run, threads=run.budget.threads)
    assert w.allocated_slab_bytes() <= caps["output_slabs"].hard_bytes


def test_estimates_and_caps_are_reported_separately():
    run = resolve_run(load_project(MINI), "sample", [])
    caps = {c.name: c for c in compute_caps(run)}
    assert caps["step_output"].estimate_bytes < caps["step_output"].hard_bytes
```

- [ ] **Step 2: Run the test**

Run: `uv run --all-packages pytest libs/simkit/tests/test_exit_memory_caps.py -v`
Expected: PASS (8 tests). For each failing case, add the missing check where the item is consumed (timer node refill → `timer_heaps`; seal → `step_output`; admission → `live_partition_state` / `max_admissions_per_step`; routing → `requests_and_inboxes`), and make `run_to_dataset` delete the `.partial` folder on any exception before re-raising. `validate` must not refuse these runtime cases up front (they are under budget); if it does, the validate rule is too strict.

- [ ] **Step 3: Lint and commit**

Run: `uv run ruff check $(ls -d libs apps examples/ecommerce_s1 benchmarks 2>/dev/null)`
```bash
git add libs/simkit libs/simkit/tests/test_exit_memory_caps.py
git commit -m "test: S1 exit test - memory caps enforced

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---
### Task 19: `datagen validate` and `datagen run`

**Files:**
- Modify: `apps/datagen/src/datagen/cli.py` (subcommands; `generate` unchanged)
- Create: `apps/datagen/src/datagen/run_cmds.py`
- Modify: `apps/datagen/README.md` (new commands)
- Test: `apps/datagen/tests/test_datagen_run_cli.py`

**Interfaces:**
- Consumes: Task 4 `validate`; Task 12 `run_to_dataset`, `ValidationFailed` (`str(e)` = the report errors joined with `"; "`, so printing it shows `exceed the memory budget …`); Task 2 `CapExceeded`.
- Produces:
  - `datagen validate PROJECT [--profile NAME] [--set K=V]...` — prints `pack <name> @ <revision> · schema_version <n>`, partitions, events, processes, warnings, then a caps table (`item`, `hard`, `estimate`, MiB) and `OK` or the errors; exit 0 or 2 (D35).
  - `datagen run PROJECT [--profile NAME] [--set K=V]... [--seed N] [--threads N] [--out DIR] [--force] [--checked]` — default run folder `<project>/<paths.out>/<profile>-s<seed>` (D21); prints the folder, exported rows per table, rounds and seconds; exit 0, 2 (validation failed, folder exists), 3 (`CapExceeded`, message names the item on stderr).
  - `run_cmds.cmd_validate(args) -> int`, `run_cmds.cmd_run(args) -> int`.
  - `cli.main` sets `NUMBA_NUM_THREADS=1` and imports `neorisk_simkit` engine modules lazily inside the commands (D33).

- [ ] **Step 1: Write the failing tests**

`apps/datagen/tests/test_datagen_run_cli.py`:
```python
import json
import shutil
from pathlib import Path

import pytest

from datagen.cli import main

FIXTURES = Path(__file__).resolve().parents[3] / "libs" / "simkit" / "tests" / "fixtures"


@pytest.fixture
def mini(tmp_path):
    dst = tmp_path / "mini"
    shutil.copytree(FIXTURES / "mini", dst)
    return dst


def test_validate_ok_prints_caps(mini, capsys):
    assert main(["validate", str(mini)]) == 0
    out = capsys.readouterr().out
    assert "pack mini @" in out and "timer_heaps" in out and "estimate" in out and "OK" in out


def test_validate_reports_structural_errors(mini, capsys):
    pack = mini / "specs" / "pack.py"
    pack.write_text(pack.read_text().replace("dist.constant(ms=200)", "dist.constant(ms=0)"))
    assert main(["validate", str(mini)]) == 2
    assert "boundary take: minimum latency must be > 0" in capsys.readouterr().out


def test_run_writes_the_named_folder_and_refuses_to_overwrite(mini, capsys):
    assert main(["run", str(mini), "--set", "users=50"]) == 0
    run_dir = mini / "out" / "sample-s7"
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["overrides"] == ["users=50"] and manifest["seed"] == 7
    assert main(["run", str(mini), "--set", "users=50"]) == 2
    assert "already exists" in capsys.readouterr().err
    assert main(["run", str(mini), "--set", "users=50", "--force"]) == 0


def test_run_seed_threads_and_out(mini, tmp_path):
    out = tmp_path / "elsewhere"
    assert main(["run", str(mini), "--seed", "9", "--threads", "1", "--out", str(out)]) == 0
    assert json.loads((out / "manifest.json").read_text())["seed"] == 9


def test_cap_exceeded_exits_3(mini, capsys):
    assert main(["run", str(mini), "--set", "engine.timer_nodes=40"]) == 3
    assert "timer_heaps" in capsys.readouterr().err


def test_budget_refusal_exits_2(mini, capsys):
    assert main(["run", str(mini), "--set", "budget.memory='1MB'"]) == 2
    assert "exceed the memory budget" in capsys.readouterr().err
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --all-packages pytest apps/datagen/tests/test_datagen_run_cli.py -v`
Expected: FAIL with `SystemExit: 2` (`invalid choice: 'validate'`).

- [ ] **Step 3: Implement**

`argparse` subparsers `generate` (existing options, unchanged), `validate`, `run`; `--set` uses `action="append", default=[]`. Map exceptions: `ValidationFailed`/`BudgetError`/`ProjectError`/`FileExistsError` → print to stderr, return 2; `CapExceeded` → print `str(e)` to stderr, return 3. The existing `test_datagen_cli.py` must keep passing unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --all-packages pytest apps/datagen/tests -v`
Expected: PASS (all datagen tests, old and new).

- [ ] **Step 5: Lint and commit**

Run: `uv run ruff check $(ls -d libs apps examples/ecommerce_s1 benchmarks 2>/dev/null)`
```bash
git add apps/datagen libs/simkit
git commit -m "datagen: validate and run commands for project folders

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 20: `datagen schema` for Postgres and DuckDB

**Files:**
- Create: `libs/simkit/src/neorisk_simkit/io/schema/sql.py`, `apps/datagen/src/datagen/schema_cmd.py`
- Create fixture: `libs/simkit/tests/fixtures/schema_demo/{datagen.toml,specs/pack.py,specs/kernels.py}`
- Modify: `apps/datagen/src/datagen/cli.py`
- Test: `libs/simkit/tests/test_schema_sql.py`, `apps/datagen/tests/test_datagen_schema_cli.py`

**Interfaces:**
- Consumes: Task 12 `schema_document`, `load_schema`, `run_to_dataset`.
- Produces:
  - `io.schema.sql.DIALECTS = ("postgres", "duckdb")`; `render_sql(doc: dict, dialect: str, tables: Sequence[str] | None = None, with_fks: bool = False) -> dict[str, str]` (table name → DDL text, each starting with the header line and ending with a newline); `quote_ident(name, dialect) -> str` (double-quotes reserved words such as `user`, `order`, `group`, `select`, `table`); `SqlError(Exception)`.
  - Column line format (§14 snippet): `f"    {name:<14}{type:<12} {constraints}"` right-stripped; `NOT NULL` for non-nullable; `PRIMARY KEY` on `event_id` (events) and `id` (entities); `CHECK (event_type = '<t>')`; `CHECK (<col> >= <min>)` for `min=`; Postgres cats `TEXT … CHECK (<col> IN ('a', 'b'))`, DuckDB cats `ENUM('a', 'b')`; amounts get the trailing comment `-- <ASSET> minor units` plus ` (cents)` for USD/EUR, ` (pence)` for GBP, placed after the comma with three spaces. Then `COMMENT ON TABLE <t> IS '<doc>';` (only when `doc` is non-empty) and `CREATE INDEX <t>_time ON <t> (event_time, lamport);` for event tables.
  - Entity tables: `id BIGINT NOT NULL PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL, origin TEXT|VARCHAR NOT NULL`, then the table columns (nullable as declared). History tables: `entity_id, valid_from, lamport, partition_id, seq` then the group columns. `--with-fks`: `REFERENCES <target> (id)` on ref columns whose target is an entity table.
  - `datagen schema TARGET [--profile NAME] [--set K=V]... [--format sql|json] [--dialect postgres|duckdb] [--tables a,b] [--with-fks] [--out DIR]` — `TARGET` is a project folder (plan built without running) or a dataset folder (has `manifest.json`; reads `schema/schema.json`); without `--out` prints everything to stdout (tables in schema order); with `--out` writes `<table>.sql` per table. Other formats/dialects → exit 2 with `"<x> arrives in M4"`.

- [ ] **Step 1: Create the `schema_demo` fixture**

`fixtures/schema_demo/datagen.toml`: copy of mini's with `name = "ecommerce"`.

`fixtures/schema_demo/specs/pack.py` (exactly the §14 example event):
```python
"""Schema fixture: the order_placed event from spec section 14, no processes."""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack
from neorisk_simkit.spec.types import amount, cat, i32, opt, ref, text

PACK = "ecommerce"
SCHEMA_VERSION = 7


@dataclass(frozen=True)
class Config:
    users: int = 10


def define(p: Pack, cfg: Config) -> None:
    user = p.table("user", key="user_id", mutable=True, cols={"tier": cat("a", "b")})
    p.table("sku", key="sku_id", cols={"price": amount(asset="USD")})
    p.table("order", key="order_id", mutable=True, child_of="user", cols={
        "amount": amount(asset="USD")})
    p.owner("user", table=user, max_live=cfg.users)
    p.population(user, n=cfg.users, initial=1.0)
    p.event("order_placed", owner="user", doc="A shopper submits a cart", cols={
        "order_id":    ref("order"),
        "user_id":     ref("user"),
        "sku_id":      ref("sku"),
        "quantity":    i32(min=1),
        "amount":      amount(asset="USD"),               # int64 minor units
        "channel":     cat("web", "app", "api"),
        "coupon_code": opt(text()),
    })
```
`fixtures/schema_demo/specs/kernels.py`: a one-line module docstring (`"""No kernels: schema-only fixture."""`). The `sku` table has no source; `schema_document` does not need one.

- [ ] **Step 2: Write the failing tests**

`libs/simkit/tests/test_schema_sql.py`:
```python
import duckdb
import pytest

from conftest import FIXTURES
from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.schema.schema_json import load_schema, schema_document
from neorisk_simkit.io.schema.sql import SqlError, render_sql
from neorisk_simkit.spec.project import load_project, resolve_run

PG = """-- generated by datagen schema · pack ecommerce @ {rev} · schema_version 7
CREATE TABLE order_placed (
    event_id      BIGINT       NOT NULL PRIMARY KEY,
    event_type    TEXT         NOT NULL CHECK (event_type = 'order_placed'),
    event_time    TIMESTAMPTZ  NOT NULL,
    lamport       BIGINT       NOT NULL,
    partition_id  BIGINT       NOT NULL,
    seq           INTEGER      NOT NULL,
    cause_id      BIGINT,
    action_id     SMALLINT     NOT NULL,
    order_id      BIGINT       NOT NULL,
    user_id       BIGINT       NOT NULL,
    sku_id        BIGINT       NOT NULL,
    quantity      INTEGER      NOT NULL CHECK (quantity >= 1),
    amount        NUMERIC(38,0) NOT NULL,   -- USD minor units (cents)
    channel       TEXT         NOT NULL CHECK (channel IN ('web', 'app', 'api')),
    coupon_code   TEXT
);
COMMENT ON TABLE order_placed IS 'A shopper submits a cart';
CREATE INDEX order_placed_time ON order_placed (event_time, lamport);
"""

DUCK_LINES = [
    "    event_type    VARCHAR      NOT NULL CHECK (event_type = 'order_placed'),",
    "    amount        DECIMAL(38,0) NOT NULL,   -- USD minor units (cents)",
    "    channel       ENUM('web', 'app', 'api') NOT NULL,",
    "    coupon_code   VARCHAR",
]


@pytest.fixture(scope="module")
def doc():
    run = resolve_run(load_project(FIXTURES / "schema_demo"), "sample", [])
    return schema_document(run.plan)


def test_postgres_matches_the_spec_example(doc):
    got = render_sql(doc, "postgres", tables=["order_placed"])["order_placed"]
    assert got == PG.format(rev=doc["revision"])


def test_duckdb_types(doc):
    got = render_sql(doc, "duckdb", tables=["order_placed"])["order_placed"]
    for line in DUCK_LINES:
        assert line in got.splitlines()


def test_reserved_names_are_quoted_and_fks_optional(doc):
    sql = render_sql(doc, "postgres", with_fks=True)
    assert sql["user"].splitlines()[1] == 'CREATE TABLE "user" ('
    assert 'REFERENCES "order" (id)' in sql["order_placed"]
    assert "REFERENCES" not in render_sql(doc, "postgres")["order_placed"]


def test_unknown_dialect_and_table(doc):
    with pytest.raises(SqlError, match="dialect 'bigquery' arrives in M4"):
        render_sql(doc, "bigquery")
    with pytest.raises(SqlError, match="unknown table 'nope'"):
        render_sql(doc, "postgres", tables=["nope"])


def test_duckdb_ddl_loads_a_real_dataset(tmp_path):
    r = run_to_dataset(FIXTURES / "mini", "sample", ["users=40"], out_dir=tmp_path / "ds")
    doc = load_schema(r.out_dir)
    con = duckdb.connect()
    for name, ddl in render_sql(doc, "duckdb").items():
        con.execute(ddl)
    for t in doc["tables"]:
        if t["kind"] != "event":
            continue
        files = list((r.out_dir / "events" / t["name"]).rglob("*.parquet"))
        if not files:
            continue
        con.execute(f"INSERT INTO {t['name']} BY NAME SELECT * FROM read_parquet("
                    f"{[str(f) for f in files]}, hive_partitioning = false)")
        assert con.execute(f"SELECT count(*) FROM {t['name']}").fetchone()[0] == \
            r.manifest["counts"][t["name"]]


def test_dataset_and_pack_give_the_same_sql(tmp_path):
    r = run_to_dataset(FIXTURES / "mini", "sample", ["users=40"], out_dir=tmp_path / "ds")
    plan = resolve_run(load_project(FIXTURES / "mini"), "sample", ["users=40"]).plan
    assert render_sql(load_schema(r.out_dir), "postgres") == render_sql(
        schema_document(plan), "postgres")
```

`apps/datagen/tests/test_datagen_schema_cli.py`:
```python
from pathlib import Path

from datagen.cli import main

FIXTURES = Path(__file__).resolve().parents[3] / "libs" / "simkit" / "tests" / "fixtures"


def test_schema_to_stdout(capsys):
    assert main(["schema", str(FIXTURES / "schema_demo"), "--format", "sql",
                 "--dialect", "postgres", "--tables", "order_placed"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("-- generated by datagen schema · pack ecommerce @ ")
    assert "CREATE INDEX order_placed_time" in out


def test_schema_one_file_per_table(tmp_path):
    assert main(["schema", str(FIXTURES / "schema_demo"), "--dialect", "duckdb",
                 "--out", str(tmp_path)]) == 0
    assert {p.name for p in tmp_path.iterdir()} >= {"order_placed.sql", "user.sql"}


def test_schema_json_and_unsupported_format(capsys):
    assert main(["schema", str(FIXTURES / "schema_demo"), "--format", "json"]) == 0
    assert '"schema_version": 7' in capsys.readouterr().out
    assert main(["schema", str(FIXTURES / "schema_demo"), "--format", "avro"]) == 2
    assert "avro arrives in M4" in capsys.readouterr().err
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run --all-packages pytest libs/simkit/tests/test_schema_sql.py apps/datagen/tests/test_datagen_schema_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'neorisk_simkit.io.schema.sql'`.

- [ ] **Step 4: Implement**

Type map per §14 and D24 (Global Constraints table). The header uses `doc["pack"]`, `doc["revision"]`, `doc["schema_version"]`. Strings in `COMMENT` and `CHECK` lists escape `'` as `''`. Output dict preserves schema order (event tables, then entity tables, then history tables).

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run --all-packages pytest libs/simkit/tests/test_schema_sql.py apps/datagen/tests/test_datagen_schema_cli.py -v`
Expected: PASS (6 + 3 tests).

- [ ] **Step 6: Lint and commit**

Run: `uv run ruff check $(ls -d libs apps examples/ecommerce_s1 benchmarks 2>/dev/null)`
```bash
git add libs/simkit apps/datagen
git commit -m "datagen schema: Postgres and DuckDB DDL from a pack or a dataset

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 21: Replay core — planner, reader, canonical merge, encoding

**Files:**
- Create: `libs/simkit/src/neorisk_simkit/io/replay/__init__.py`, `io/replay/planner.py`, `io/replay/reader.py`, `io/replay/encode.py`
- Test: `libs/simkit/tests/test_replay_core.py`

**Interfaces:**
- Consumes: Task 12 layout, `read_step_index`, `load_schema`.
- Produces:
  - `CanonicalKey = tuple[int, int, int, int]` (event_time µs, lamport, partition_id, seq). All replay time arguments are int µs since the epoch; the test builds its expected keys with `event_time` as int µs (`pl.col("event_time").dt.epoch("us")` for frames, `pc.cast(…, pa.int64())` for batches).
  - `ReplayRequest(first: int | None = None, last: int | None = None, t_from: int | None = None, t_to: int | None = None, types: tuple[str, ...] | None = None, batch_rows: int = 65_536)`; `ReplayError(Exception)`.
  - `plan_replay(dataset_dir, req) -> ReplayPlan` with `steps: list[int]` (ascending, pruned by the index for `--from/--to` and `--last`), `types: list[str]`, `schema: pa.Schema` (unified, D23), `doc: dict` (schema.json). Errors: `first` and `last` together, non-positive N, `t_from >= t_to`, unknown type, `batch_rows > 65_536`.
  - `iter_batches(plan) -> Iterator[pa.RecordBatch]`: canonical order, each batch ≤ `batch_rows`; reads only the files of selected types and planned steps (all `date=` dirs of a step), concatenates a step's tables, sorts by the key, applies the time filter, then `first`/`last`. `--last N` walks steps backwards using `rows__<type>` from the index (and real filtered counts when a time filter is set), then emits forward. `plan.files_opened` counts opened files (for tests).
  - `encode.row_dicts(batch, doc, numbers=False) -> list[dict]`: one flat object per row with the common columns then that row's type columns (own nulls kept, other types' columns dropped); int64 IDs, refs, `lamport`, `partition_id`, `event_id`, `cause_id` and amounts as strings unless `numbers`; i16/i32 (`seq`, `action_id`, `quantity`…) as numbers; timestamps RFC 3339 with 6 fractional digits and `Z`; cats as strings; bools as JSON booleans.
  - `encode.to_jsonl(dicts) -> str`, `encode.to_csv(batch, doc, header: bool) -> str`, `encode.to_table(dicts) -> str` (fixed-width, header + rows, columns truncated at 24 chars).

- [ ] **Step 1: Write the failing tests**

`libs/simkit/tests/test_replay_core.py`:
```python
import json
import re

import polars as pl
import pyarrow as pa
import pyarrow.compute as pc
import pytest

from conftest import FIXTURES
from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events
from neorisk_simkit.io.replay.encode import row_dicts, to_jsonl
from neorisk_simkit.io.replay.planner import ReplayError, ReplayRequest, plan_replay
from neorisk_simkit.io.replay.reader import iter_batches

KEY = ["event_time", "lamport", "partition_id", "seq"]
TS = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z$")


@pytest.fixture(scope="module")
def ds(tmp_path_factory):
    r = run_to_dataset(FIXTURES / "mini", "sample", ["behavior.take_p=0.4", "engine.step='3h'"],
                       out_dir=tmp_path_factory.mktemp("rp") / "ds")
    return r.out_dir


def _keys(batches):
    """Canonical keys with event_time as int µs (ReplayRequest.t_from/t_to are int µs)."""
    out = []
    for b in batches:
        t = pc.cast(b.column("event_time"), pa.int64()).to_pylist()
        out.extend(zip(t, *(b.column(k).to_pylist() for k in KEY[1:])))
    return out


@pytest.fixture(scope="module")
def everything(ds):
    ev = read_events(ds)
    allk = pl.concat([v.select(pl.col("event_time").dt.epoch("us"), *KEY[1:])
                      for v in ev.values()]).sort(KEY)
    return [tuple(r) for r in allk.iter_rows()]


def test_full_replay_is_the_canonical_order(ds, everything):
    got = _keys(iter_batches(plan_replay(ds, ReplayRequest())))
    assert got == everything and got == sorted(got)


def test_first_and_last(ds, everything):
    p = plan_replay(ds, ReplayRequest(first=100))
    assert _keys(iter_batches(p)) == everything[:100]
    full = plan_replay(ds, ReplayRequest())
    list(iter_batches(full))
    assert p.files_opened < full.files_opened
    assert _keys(iter_batches(plan_replay(ds, ReplayRequest(last=100)))) == everything[-100:]


def test_time_window_and_types(ds, everything):
    lo, hi = everything[200][0], everything[400][0]
    got = _keys(iter_batches(plan_replay(ds, ReplayRequest(t_from=lo, t_to=hi))))
    assert got == [k for k in everything if lo <= k[0] < hi]
    p = plan_replay(ds, ReplayRequest(types=("took",)))
    rows = [r for b in iter_batches(p) for r in b.to_pylist()]
    assert rows and {r["event_type"] for r in rows} == {"took"}


def test_batches_are_bounded(ds):
    sizes = [b.num_rows for b in iter_batches(plan_replay(ds, ReplayRequest(batch_rows=50)))]
    assert max(sizes) <= 50 and sum(sizes) > 50


def test_empty_selections(ds, everything):
    end = everything[-1][0] + 1
    assert list(iter_batches(plan_replay(ds, ReplayRequest(t_from=end, t_to=end + 10)))) == []


def test_request_errors(ds):
    with pytest.raises(ReplayError, match="either --first or --last"):
        plan_replay(ds, ReplayRequest(first=1, last=1))
    with pytest.raises(ReplayError, match="unknown event type 'nope'"):
        plan_replay(ds, ReplayRequest(types=("nope",)))


def test_json_encoding(ds):
    p = plan_replay(ds, ReplayRequest(types=("ping", "took"), first=200))
    batch = next(iter_batches(p))
    rows = row_dicts(batch, p.doc)
    ping = next(r for r in rows if r["event_type"] == "ping")
    took = next(r for r in rows if r["event_type"] == "took")
    assert list(ping)[:8] == ["event_id", "event_type", "event_time", "lamport", "partition_id",
                              "seq", "cause_id", "action_id"]
    assert isinstance(ping["event_id"], str) and isinstance(ping["lamport"], str)
    assert isinstance(ping["seq"], int) and isinstance(ping["n"], int)
    assert TS.match(ping["event_time"]) and "note_id" in ping and "ok" not in ping
    assert took["ok"] in ("yes", "no") and "note_id" not in took
    nums = row_dicts(batch, p.doc, numbers=True)
    assert isinstance(nums[0]["event_id"], int)
    line = to_jsonl(rows[:1])
    assert json.loads(line) == rows[0] and line.endswith("\n")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --all-packages pytest libs/simkit/tests/test_replay_core.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'neorisk_simkit.io.replay'`.

- [ ] **Step 3: Implement**

Read step files with `pq.read_table(paths, columns=...)`; cast dictionary columns to string in the unified schema; `t_from`/`t_to` filters use `pyarrow.compute` on `event_time` and the index's `first_time`/`last_time` to skip steps. Memory: one step of the selected types plus one batch.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --all-packages pytest libs/simkit/tests/test_replay_core.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Lint and commit**

Run: `uv run ruff check $(ls -d libs apps examples/ecommerce_s1 benchmarks 2>/dev/null)`
```bash
git add libs/simkit/src/neorisk_simkit/io/replay libs/simkit/tests/test_replay_core.py
git commit -m "simkit: replay planner, reader and canonical encoding

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 22: Sinks (stdout, file) and `datagen replay`

**Files:**
- Create: `libs/simkit/src/neorisk_simkit/io/sinks/__init__.py`, `io/sinks/base.py`, `io/sinks/stdout.py`, `io/sinks/file.py`, `apps/datagen/src/datagen/replay_cmd.py`
- Modify: `apps/datagen/src/datagen/cli.py`, `apps/datagen/README.md`
- Test: `libs/simkit/tests/test_replay_sinks.py`, `apps/datagen/tests/test_datagen_replay_cli.py`

**Interfaces:**
- Consumes: Task 21.
- Produces:
  - `io.sinks.base`: `SinkOptions(format: str, numbers: bool, doc: dict)`; `SinkReport(name: str, rows: int, seconds: float, first_key: CanonicalKey | None, last_key: CanonicalKey | None, error: str | None)`; `class Sink(Protocol)` with exactly `open(schema: pa.Schema, opts: SinkOptions) -> None`, `write(batch: pa.RecordBatch) -> None`, `checkpoint() -> CanonicalKey | None`, `close() -> SinkReport`; `SinkUnavailable(Exception)`; `open_sink(uri: str, numbers: bool, doc: dict) -> tuple[Sink, SinkOptions]` — `stdout` / `stdout:?format=jsonl|table|csv`; `file:PATH?format=jsonl|json-array|csv|parquet` (format defaults from the extension: `.jsonl`, `.json` → json-array, `.csv`, `.parquet`); `kafka://…` → `SinkUnavailable("kafka sink arrives in M4")`; anything else → `SinkUnavailable("unknown sink …")`.
  - `StdoutSink`: writes encoded rows to `sys.stdout`; `BrokenPipeError` → stops quietly (report `error=None`, `rows` = rows delivered) and redirects stdout to `os.devnull` so interpreter shutdown does not print a traceback.
  - `FileSink`: writes `PATH.tmp`, renames to `PATH` on `close()`; `abort()` deletes `PATH.tmp`; `json-array` streams `[`, comma-separated objects, `]` (`[]` when empty); `parquet` uses one `pq.ParquetWriter` with the unified schema.
  - `datagen replay DATASET [--first N | --last N] [--from T] [--to T] [--types a,b] [--sink URI]... [--numbers] [--batch-rows N] [--preset NAME]` — `T` is RFC 3339 or a date (`2026-03-01`); presets come from `[replay.presets.<name>]` in the project's `datagen.toml` (`DATASET/../../datagen.toml`), and explicit flags override preset keys; default sink `stdout`. Every batch is encoded once per distinct format and written to every sink (tee). The exit report goes to stderr: per sink `rows`, rate, first/last key, error. Exit 0; 1 if any sink failed; 2 for bad arguments or unavailable sinks.

- [ ] **Step 1: Write the failing tests**

`libs/simkit/tests/test_replay_sinks.py`:
```python
import json

import pyarrow.parquet as pq
import pytest

from conftest import FIXTURES
from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.replay.planner import ReplayRequest, plan_replay
from neorisk_simkit.io.replay.reader import iter_batches
from neorisk_simkit.io.sinks.base import SinkUnavailable, open_sink


@pytest.fixture(scope="module")
def plan(tmp_path_factory):
    r = run_to_dataset(FIXTURES / "mini", "sample", ["behavior.take_p=0.4"],
                       out_dir=tmp_path_factory.mktemp("sk") / "ds")
    return lambda **kw: plan_replay(r.out_dir, ReplayRequest(**kw))


def _drain(p, uri):
    sink, opts = open_sink(uri, numbers=False, doc=p.doc)
    sink.open(p.schema, opts)
    for b in iter_batches(p):
        sink.write(b)
    return sink.close()


def test_json_array_file(plan, tmp_path):
    path = tmp_path / "out.json"
    rep = _drain(plan(first=50), f"file:{path}?format=json-array")
    data = json.loads(path.read_text())
    assert len(data) == 50 == rep.rows and rep.error is None
    assert rep.first_key is not None and rep.last_key >= rep.first_key
    assert not path.with_name("out.json.tmp").exists()


def test_empty_json_array(plan, tmp_path):
    path = tmp_path / "empty.json"
    _drain(plan(types=("took",), t_from=0, t_to=1), f"file:{path}")
    assert json.loads(path.read_text()) == []


def test_csv_and_parquet_files(plan, tmp_path):
    _drain(plan(first=20), f"file:{tmp_path / 'a.csv'}")
    lines = (tmp_path / "a.csv").read_text().splitlines()
    assert lines[0].startswith("event_id,event_type,event_time") and len(lines) == 21
    _drain(plan(first=20), f"file:{tmp_path / 'a.parquet'}")
    assert pq.read_table(tmp_path / "a.parquet").num_rows == 20


def test_failed_file_sink_leaves_nothing(plan, tmp_path):
    p = plan(first=50)
    path = tmp_path / "bad.jsonl"
    sink, opts = open_sink(f"file:{path}", numbers=False, doc=p.doc)
    sink.open(p.schema, opts)
    sink.write(next(iter_batches(p)))
    sink.abort()
    assert not path.exists() and not path.with_name("bad.jsonl.tmp").exists()


def test_stdout_formats(plan, capsys):
    _drain(plan(first=3), "stdout")
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 3 and all(json.loads(x)["event_id"] for x in lines)
    _drain(plan(first=3), "stdout:?format=table")
    assert capsys.readouterr().out.splitlines()[0].split()[:2] == ["event_id", "event_type"]


def test_unavailable_sinks(plan):
    with pytest.raises(SinkUnavailable, match="kafka sink arrives in M4"):
        open_sink("kafka://localhost:9092/x", numbers=False, doc=plan().doc)
```

`apps/datagen/tests/test_datagen_replay_cli.py`:
```python
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from datagen.cli import main
from neorisk_simkit.io.dataset import run_to_dataset

EX = Path(__file__).resolve().parents[3] / "examples" / "ecommerce_s1"


@pytest.fixture(scope="module")
def ds(tmp_path_factory):
    proj = tmp_path_factory.mktemp("proj") / "ecommerce_s1"
    shutil.copytree(EX, proj, ignore=shutil.ignore_patterns("out", "reports", "logs"))
    r = run_to_dataset(proj, "sample", ["users=800", "skus=200", "sku_groups=4", "run.span=3d",
                                        "run.warmup=1d"],
                       out_dir=proj / "out" / "sample-s42")
    return r.out_dir


def test_first_to_stdout(ds, capsys):
    assert main(["replay", str(ds), "--first", "5"]) == 0
    cap = capsys.readouterr()
    rows = [json.loads(x) for x in cap.out.splitlines()]
    assert len(rows) == 5 and "rows" in cap.err and "stdout" in cap.err


def test_tee_to_stdout_and_file(ds, tmp_path, capsys):
    path = tmp_path / "last.json"
    assert main(["replay", str(ds), "--last", "7", "--sink", "stdout",
                 "--sink", f"file:{path}?format=json-array"]) == 0
    assert len(capsys.readouterr().out.splitlines()) == 7
    assert len(json.loads(path.read_text())) == 7


def test_types_window_and_numbers(ds, capsys):
    # the whole exported span (start 2026-01-01, run.span=3d), so the selection is not empty
    assert main(["replay", str(ds), "--types", "order_placed", "--from", "2026-01-01",
                 "--to", "2026-01-04", "--numbers"]) == 0
    rows = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
    assert rows
    assert all(r["event_type"] == "order_placed" and isinstance(r["amount"], int) for r in rows)


def test_preset_from_project_file(ds, capsys):
    assert main(["replay", str(ds), "--preset", "peek"]) == 0
    assert capsys.readouterr().out.splitlines()[0].split()[0] == "event_id"


def test_bad_arguments_and_kafka(ds, capsys):
    assert main(["replay", str(ds), "--first", "1", "--last", "1"]) == 2
    assert main(["replay", str(ds), "--sink", "kafka://localhost:9092/t"]) == 2
    assert "arrives in M4" in capsys.readouterr().err


def test_closed_pipe_is_not_an_error(ds):
    cmd = (f"set -o pipefail; {sys.executable} -m datagen.cli replay {ds} --first 100000 "
           f"| head -1")
    res = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=600)
    assert res.returncode == 0, res.stderr
    assert "Traceback" not in res.stderr and len(res.stdout.splitlines()) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --all-packages pytest libs/simkit/tests/test_replay_sinks.py apps/datagen/tests/test_datagen_replay_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'neorisk_simkit.io.sinks'`.

- [ ] **Step 3: Implement**

- Parse sink URIs with `urllib.parse.urlsplit` (for `file:` take everything between `file:` and `?` as the path, relative to the current directory).
- `replay_cmd` builds one `ReplayPlan`, opens every sink, loops batches, and on an exception in one sink calls its `abort()` (file) and records the error while the others continue; reports at the end.
- `cli.py` gains `if __name__ == "__main__": raise SystemExit(main())` if missing (it exists today) — the pipe test runs `python -m datagen.cli`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --all-packages pytest libs/simkit/tests/test_replay_sinks.py apps/datagen/tests/test_datagen_replay_cli.py -v`
Expected: PASS (6 + 6 tests).

- [ ] **Step 5: Lint and commit**

Run: `uv run ruff check $(ls -d libs apps examples/ecommerce_s1 benchmarks 2>/dev/null)`
```bash
git add libs/simkit/src/neorisk_simkit/io/sinks libs/simkit/tests/test_replay_sinks.py apps/datagen
git commit -m "datagen replay: stdout and file sinks with tee and exit report

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 23: Bench feature allowlist

**Files:**
- Create: `apps/bench/src/bench/allowlist.py`
- Modify: `apps/bench/src/bench/runner.py` (`load_events`, `raw_features`, `run`), `apps/bench/src/bench/features.py` (`build_features`, `_raw_columns`), `apps/bench/src/bench/compare.py` and `apps/bench/src/bench/curves.py` (pass the allowlist), `apps/datagen/src/datagen/scenarios/fraud.py` (write `meta["feature_allowlist"]`), `apps/bench/README.md` (one paragraph)
- Test: `apps/bench/tests/test_bench_allowlist.py`

**Interfaces:**
- Consumes: existing bench and legacy datagen code.
- Produces:
  - `bench.allowlist.ENGINE_COLUMNS = frozenset({"lamport", "partition_id", "seq", "cause_id", "action_id"})` (D29). The legacy integer `event_type` stays an allowed raw feature; the engine's string `event_type` is non-numeric and therefore never one.
  - `resolve_allowlist(meta: dict, events: pl.DataFrame) -> list[str]`: if `meta["feature_allowlist"]` exists, validate it (every name present in `events` → else `ValueError("feature_allowlist names missing columns: [...]")`; none is `label`, a golden column, an `*_id` column or an engine column → else `ValueError("feature_allowlist contains forbidden columns: [...]")`) and return it in events' column order; otherwise return numeric columns that are not `label`, not `*_id`, not `event_id`/`event_time`, and not in `ENGINE_COLUMNS`.
  - `load_events(data_dir)` adds `meta["_allowlist"] = resolve_allowlist(meta, events)`.
  - `raw_features(df, allowlist: Sequence[str] | None = None)` and `build_features(events, allowlist: Sequence[str] | None = None)` restrict raw columns to the allowlist when given (existing behavior when `None`); `runner.run` passes `meta["_allowlist"]` for the raw set and `meta["_allowlist"] + golden columns` for the oracle set.
  - Legacy `datagen generate` writes `feature_allowlist` = the numeric, non-`*_id`, non-label event columns (exactly today's raw set), so bench results on legacy data are unchanged.

- [ ] **Step 1: Write the failing tests**

`apps/bench/tests/test_bench_allowlist.py`:
```python
import json

import polars as pl
import pytest

from bench.allowlist import ENGINE_COLUMNS, resolve_allowlist
from bench.features import build_features
from bench.runner import load_events, raw_features
from datagen.cli import main as datagen_main


def _events():
    return pl.DataFrame({
        "event_id": [1, 2], "event_time": [1, 2], "user_id": [5, 6], "amount": [1.0, 2.0],
        "lamport": [1, 2], "partition_id": [7, 7], "seq": [0, 1], "action_id": [0, 0],
        "label": [0, 1]})


def test_engine_columns_are_never_features():
    allowed = resolve_allowlist({}, _events())
    assert allowed == ["amount"] and not set(allowed) & ENGINE_COLUMNS
    assert raw_features(_events(), allowed).columns == ["amount"]


def test_meta_allowlist_restricts_and_is_validated():
    ev = _events().with_columns(pl.col("amount").alias("amount2"))
    assert resolve_allowlist({"feature_allowlist": ["amount2"]}, ev) == ["amount2"]
    with pytest.raises(ValueError, match="missing columns"):
        resolve_allowlist({"feature_allowlist": ["nope"]}, ev)
    with pytest.raises(ValueError, match="forbidden columns"):
        resolve_allowlist({"feature_allowlist": ["lamport"]}, ev)
    with pytest.raises(ValueError, match="forbidden columns"):
        resolve_allowlist({"feature_allowlist": ["label"]}, ev)
    with pytest.raises(ValueError, match="forbidden columns"):
        resolve_allowlist({"feature_allowlist": ["g1"], "golden_columns": ["g1"]},
                          ev.with_columns(pl.lit(0).alias("g1")))


def test_legacy_dataset_carries_an_allowlist_equal_to_todays_raw_set(tmp_path):
    out = tmp_path / "fraud"
    assert datagen_main(["generate", "--scenario", "fraud", "--n-events", "3000",
                         "--seed", "3", "--out", str(out)]) == 0
    meta = json.loads((out / "meta.json").read_text())
    events, loaded = load_events(out)
    assert meta["feature_allowlist"] == loaded["_allowlist"]
    assert raw_features(events, loaded["_allowlist"]).columns == raw_features(events).columns
    a = build_features(events, loaded["_allowlist"])
    b = build_features(events)
    assert a.columns == b.columns
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --all-packages pytest apps/bench/tests/test_bench_allowlist.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bench.allowlist'`.

- [ ] **Step 3: Implement** as specified in Interfaces; `features._raw_columns(events, allowlist=None)` keeps its `IDENTIFIER_LIKE` exclusion and intersects with the allowlist.

- [ ] **Step 4: Run all bench and datagen tests**

Run: `uv run --all-packages pytest apps/bench apps/datagen -q`
Expected: PASS (new tests plus every existing bench test unchanged).

- [ ] **Step 5: Lint and commit**

Run: `uv run ruff check $(ls -d libs apps examples/ecommerce_s1 benchmarks 2>/dev/null)`
```bash
git add apps/bench apps/datagen/src/datagen/scenarios/fraud.py
git commit -m "bench: feature allowlist; engine columns are never model inputs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 24: `benchmarks/s1.toml`, `datagen benchmark`, calibration and the gate

**Files:**
- Create: `benchmarks/s1.toml`, `benchmarks/README.md`, `apps/datagen/src/datagen/benchmark.py`
- Modify: `apps/datagen/src/datagen/cli.py`, `.gitignore` (add `benchmarks/results/`), `examples/ecommerce_s1/specs/pack.py` (calibrated `Journey`/`Config` defaults only), `libs/simkit/src/neorisk_simkit/io/dataset.py` and `engine/world.py` (stats fields below, if missing)
- Test: `apps/datagen/tests/test_benchmark_s1.py`

**Interfaces:**
- Consumes: Tasks 12 (`run_stats.json` incl. `machine = {"arch", "cpus", "ram_bytes"}`), 15, 19; Task 6 rule that only fixed-`n` source tables have `n` inlined.
- Produces:
  - Stats fields in `run_stats.json` (add any that are missing): `engine_seconds` (from `run_to_dataset` entry to `manifest.json` written), `stage_seconds` (`build`, `generate`, `seal`, `write`), `exported_events`, `events_per_second`, `peak_rss_bytes`, `proposals` (owner commands dispatched, retries excluded), `requests_by_boundary`, `rounds_per_step`, `threads`, `machine` — exactly `{"arch": platform.machine(), "cpus": os.cpu_count(), "ram_bytes": <total RAM via os.sysconf>}` as Task 12 writes it (`evaluate` reads `machine["cpus"]` and `machine["ram_bytes"]` for `reference_hardware`).
  - `benchmark.load_workload(path) -> Workload(name, project: Path, profile, seed, overrides: list[str], expect: dict, gate: dict)`.
  - `benchmark.evaluate(stats: dict, wl: Workload, *, scale: float) -> dict` → `{"verdict": "pass"|"fail"|"skipped", "checks": [{"name", "value", "limit", "ok"}], "reference_hardware": bool}`; `skipped` when `scale != 1`.
  - `benchmark.run_benchmark(path, *, scale=1.0, cold=False, threads=None, out_json=None) -> dict`: (1) compile run in a subprocess on the same plan shape (`users=1000`, `run.span=1d`, `run.warmup=0s`; with `--cold`, fresh `NEORISK_JIT_CACHE`/`NUMBA_CACHE_DIR` dirs), timed as `cold_compile_seconds`; (2) warm run in a subprocess `python -m datagen.benchmark --child …` with the same cache dirs; (3) read its `run_stats.json`; (4) `evaluate`; (5) write the JSON report to `out_json` or `benchmarks/results/<name>-<utc>.json`; print a summary table.
  - `datagen benchmark WORKLOAD.toml [--scale X] [--cold] [--threads N] [--out FILE] [--no-gate]` → exit 0 on pass/skipped, 1 on fail (D35).

- [ ] **Step 1: Write the workload file**

`benchmarks/s1.toml`:
```toml
# S1 benchmark workload (spec §10 and §18). An ordinary run of a project and profile:
#   uv run --all-packages datagen benchmark benchmarks/s1.toml
[workload]
name = "s1"
project = "../examples/ecommerce_s1"     # relative to this file
profile = "full"
seed = 42
set = []                                 # the profile and Config defaults fix the shape

[workload.shape]                         # documentation of what the workload fixes (spec §10)
users = 2_000_000
span = "90d"
exported_events = 10_000_000
property_columns = 12                    # product_viewed, ~120 B/row
change_groups = ["user_kyc"]
activity = "Pareto alpha = 1.2 (Journey.session_gap_alpha)"
inventory_share_of_proposals = 0.08

[expect]
exported_events = { around = 10_000_000, tolerance = 0.05 }
inventory_share_of_proposals = { around = 0.08, tolerance = 0.02 }

[gate]
warm_seconds = 60
peak_rss_gb = 16
threads = 16                             # min(16, cores) on smaller machines (D30)
reference = "16 cores / 64 GB"
```

- [ ] **Step 2: Write the failing tests**

`apps/datagen/tests/test_benchmark_s1.py`:
```python
import json
from pathlib import Path

from datagen.benchmark import evaluate, load_workload
from datagen.cli import main

S1 = Path(__file__).resolve().parents[3] / "benchmarks" / "s1.toml"


def _stats(**kw):
    base = {"engine_seconds": 50.0, "peak_rss_bytes": 8 * 1024**3, "exported_events": 10_100_000,
            "proposals": 40_000_000, "requests_by_boundary": {"reserve": 3_300_000},
            "threads": 16, "machine": {"arch": "x86_64", "cpus": 16, "ram_bytes": 64 * 1024**3}}
    return base | kw


def test_workload_loads():
    wl = load_workload(S1)
    assert wl.project.name == "ecommerce_s1" and wl.profile == "full" and wl.seed == 42
    assert wl.gate["warm_seconds"] == 60 and wl.gate["peak_rss_gb"] == 16


def test_gate_pass_and_fail():
    wl = load_workload(S1)
    assert evaluate(_stats(), wl, scale=1.0)["verdict"] == "pass"
    assert evaluate(_stats(engine_seconds=61.0), wl, scale=1.0)["verdict"] == "fail"
    assert evaluate(_stats(peak_rss_bytes=17 * 1024**3), wl, scale=1.0)["verdict"] == "fail"
    assert evaluate(_stats(exported_events=8_000_000), wl, scale=1.0)["verdict"] == "fail"
    r = evaluate(_stats(machine={"arch": "arm64", "cpus": 14, "ram_bytes": 36 * 1024**3}), wl,
                 scale=1.0)
    assert r["reference_hardware"] is False
    assert evaluate(_stats(), wl, scale=0.01)["verdict"] == "skipped"


def test_scaled_smoke_run(tmp_path):
    out = tmp_path / "report.json"
    assert main(["benchmark", str(S1), "--scale", "0.002", "--threads", "4",
                 "--out", str(out)]) == 0
    rep = json.loads(out.read_text())
    for key in ("engine_seconds", "cold_compile_seconds", "peak_rss_bytes", "exported_events",
                "stage_seconds", "rounds_per_step", "verdict"):
        assert key in rep, key
    assert rep["verdict"] == "skipped" and rep["exported_events"] > 0
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run --all-packages pytest apps/datagen/tests/test_benchmark_s1.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'datagen.benchmark'`.

- [ ] **Step 4: Implement `benchmark.py` and the stats fields**

- `inventory_share_of_proposals = requests_by_boundary["reserve"] / proposals`.
- `--scale X` overrides `users = round(2_000_000 * X)` (other shape values unchanged), so the generated module is the same as the full run's: it depends only on plan structure and on the row counts of fixed-`n` sources (`sku`, inlined by Task 6); recipe-built tables whose size scales with users (`device`, from `std.devices`) read their `n` at runtime (Task 6 rule), so no population-dependent constant is baked in. Assert in the child that `build_engine(plan).__file__` equals the compile run's; a mismatch means codegen inlined a population-dependent value — fix codegen, not the assertion.
- Peak RSS is the warm child's own `ru_maxrss` from its `run_stats.json` (normalize macOS bytes vs Linux KiB).
- Threads default to `min(gate.threads, os.cpu_count())` (D30); the child sets `NUMBA_NUM_THREADS=1`, `POLARS_MAX_THREADS=<threads>`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run --all-packages pytest apps/datagen/tests/test_benchmark_s1.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Calibrate the full profile**

Run: `uv run --all-packages datagen benchmark benchmarks/s1.toml --no-gate --out /tmp/s1-calib.json` (prints events and the inventory share).
Adjust only `examples/ecommerce_s1/specs/pack.py` defaults (`Journey.checkout_p`, `views_mean`, `session_gap_min_h`, `add_to_cart_p`) until `exported_events` is within 10⁷ ± 5% and the inventory share within 8% ± 2%. Re-run `uv run --all-packages pytest apps/datagen/tests/test_example_ecom_s1.py apps/datagen/tests/test_example_ecom_s1_kyc.py` after each change.

- [ ] **Step 7: Measure the gate and report it**

Run: `uv run --all-packages datagen benchmark benchmarks/s1.toml --cold --out benchmarks/results/s1-cold.json` then `uv run --all-packages datagen benchmark benchmarks/s1.toml --out benchmarks/results/s1-warm.json`.
Write `benchmarks/README.md`: what each workload file fixes, how to run it, the gate (≤ 60 s warm, peak RSS ≤ 16 GB on 16 cores / 64 GB), and a results table filled from the two JSON reports:

| Date | Machine (cores / RAM) | Threads | Exported events | Warm s | Cold compile s | Peak RSS GB | generate / seal / write s | Rounds per step (max) | Verdict |
|---|---|---|---|---|---|---|---|---|---|

Report the measured numbers exactly. If the verdict is `fail`, keep it, name the stage that misses its §10 rate band, and do not change the gate or the workload; S1 is not exited until a later change passes it.

- [ ] **Step 8: Full suite, lint and commit**

Run: `uv run --all-packages pytest -q && uv run ruff check $(ls -d libs apps examples/ecommerce_s1 benchmarks 2>/dev/null)`
```bash
git add benchmarks/s1.toml benchmarks/README.md .gitignore apps/datagen libs/simkit examples/ecommerce_s1
git commit -m "bench: S1 workload, datagen benchmark, measured gate

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

## Deferred to later milestones

Nothing below is built in S1; each S1 component fails loudly (`PackError`/`SinkUnavailable`/exit 2 naming the milestone) when asked for it.

**S2 (shard slice)**
- Payments with refunds and disputes; multi-SKU reservations through `std.reservations` with TTL expiry (`stock_expired`) and the join/commit-all/release-all recipe; a hot SKU group; the capped bonus pool (`std.capped_pool`) and `p.accumulator`.
- Rounds at scale (parallel shard phases tuned for hot shards), spawn/`join` with `max_spawn_depth` enforcement, owner-to-owner messages delivered at the next step boundary (`on_message` between owners).
- Checks beyond structural: per-partition and cross-partition law reducers, `law.*` evaluation, request/response pairing (and `cause_id` population, D14), reference kernel tests against fixtures, mutation tests, referential-integrity bitsets.
- `benchmarks/s2.toml` (≤ 10 min warm) and `benchmarks/s2_pool.toml` (shard path ≥ 80k events/s).
- Created-owner `partition_id` stability across step lengths (D12).

**M3**
- State machines (`p.machine`, branch/timer/repeat/until/spawn/join/request/then) and the generated dispatch module; `p.expose`/`expose_param`; overlays (`Overlay`, cohorts, `suppress`, labels) and the bounty-hunter/flash-sale overlays; the full `examples/ecommerce` pack at parity; legacy adapter `datagen export --legacy-fraud`; replacing `scenarios/fraud.generate`; the interference report; instance kernels over child rows (D16).
- `datagen check`, `report.html`, `checks.json`, `expectations.yaml` evaluation (statistical checks, sampling by owner hash, censoring), CODEOWNERS rule.
- Cross-owner enrichment (`p.feature`, rolling reducers on merged step output) and `golden/`; scorer changes (frozen sample-fit model); `attributes.sample_timeline` incremental rework.

**M4**
- Kafka sink (`neorisk-simkit[kafka]`), `--pace`, `--rate`, `--rebase`, `--with-labels`, `--owners`, `--owner-ids`, `--where`, `--resume`/`--resume-from`/`.replay-state.json`, `--rotate`, `--dry-run`.
- Schema formats avro, json-schema, arrow, markdown; dialects bigquery, snowflake, clickhouse, spark; `--load`, `--unified-view`, `--diff`, `--single-file` for schema; `datagen export --single-file`.
- Payments with label delay, bench generic loader and maturity-aware splits, `labels/`.

**Later / not scheduled**
- Run modes `population` and event-count; opening snapshots (`snapshots/`), `cases/`, censoring reports, drain; `relations/`, `postings/`.
- `sweep`, spilling, distributed execution (non-goals in v1).

## Self-review notes (planner)

- **Spec coverage (§18 S1):** owner slice → Tasks 14–15; bench feature allowlist → Task 23; output layout with step index → Tasks 11–12; `datagen schema` Postgres/DuckDB → Task 20; replay to stdout and file → Tasks 21–22; exit tests: native ABI proof → Task 13; priority inversion and equal-key ordering → Task 10; thread/slab/step invariance → Task 17; recurring-shopper trace → Task 16; memory caps enforced → Task 18; `benchmarks/s1.toml` gate measured and reported → Task 24.
- **Interfaces checked across tasks:** resource vector order (Task 6 ↔ Task 8), `PAYLOAD_W = 12` (Engine reference, Tasks 4, 7, 8), `force_capacity` keys (Tasks 8, 9, 13), `records_of` (Tasks 9, 10), `run_stats.json` fields used by Tasks 13, 14, 16, 24 (`rejects` by process name, `retries`, `continuations`, `rounds_per_step`, `round_detail`, `engine_seconds`), `run.` override prefix (Tasks 3, 14, 15, 17, 20, 22).
- **Known risk to watch during execution:** Numba compile time of large generated modules (mitigated by `cache=True`, D34) and the D4 small-round loop; if the gate fails, Task 24 reports the stage instead of changing the gate.
