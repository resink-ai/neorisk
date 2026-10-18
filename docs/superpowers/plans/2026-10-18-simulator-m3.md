# Agentic Event Simulator — Milestone M3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship milestone M3: the state machine with every operation of §04 (branch, timer, repeat, until…then, spawn, join, request, then) compiled through a generated, inspectable dispatch module; the overlay contract (cohorts with their own execution owner, base extension points, `suppress`, hidden labels, the regression rule and the interference report); the §07 campaign trace as an exit test; the real `examples/ecommerce` pack with the `bounty_hunters` overlay, exported at parity with today's fraud dataset through `datagen export --legacy-fraud`, replacing `datagen.scenarios.fraud`; plus the S2 → M3 obligations (runtime spawn depth, owner-to-owner messages, `sum_le` against state, statistical checks, `datagen check`, `report.html`, `checks.json`, `cause_id`).

**Architecture:** A machine is declared in the pack (`p.machine` / `o.machine`) and compiled at plan build into authoring-dialect kernel source: all machines of one owner partition type become one generated process `mx_<partition>` whose `Local` holds a fixed table of machine instances, whose commands are tagged timers and responses, and whose actions are copies of `@action` functions (and `std` helper actions) rewritten for that process. The generated text is lowered and compiled by the existing S1/S2 pipeline (lowering → codegen → Numba), so a machine is exactly as fast, retry-safe and invariant as a handwritten kernel, and `datagen validate --dump-machines DIR` writes the text that is compiled. Overlays add cohort owner partitions that execute on behalf of an exposed base table: they emit the base events, send the base requests and create member rows of the base table without becoming base owners, so the schema never changes and base IDs never move.

**Tech Stack:** Python 3.12, uv workspace, numba, numpy, pyarrow, polars, PyYAML (new, D84), duckdb (tests only), pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-10-15-agentic-event-simulator-architecture.html` (binding; §18 defines M3, §17 the module layout `machine/`). Read §04, §05, §06, §07, §08, §11, §12, §13 before any task. The S1 plan (`docs/superpowers/plans/2026-10-16-simulator-s1.md`, D1–D35, Engine reference) and the S2 plan (`docs/superpowers/plans/2026-10-17-simulator-s2.md`, D36–D61, Engine reference deltas, contracts in `.superpowers/sdd/2026-10-17-simulator-s2/contracts.md`) stay binding wherever this plan does not amend them.

## Global Constraints

Every task implicitly includes this section. Values are copied from the spec; do not change them.

**Repo and process**
- Python `>=3.12`; ruff `line-length = 100`. Lint step of every task, exactly: `uv run ruff check $(ls -d libs apps examples/ecommerce_s1 examples/ecommerce_s2 benchmarks 2>/dev/null)`; from Task 14 on, append `examples/ecommerce` to that list (its specs are rewritten there; before Task 14 they are a design sketch that does not import).
- Tests run with `uv run --all-packages pytest ...`; the full suite `uv run --all-packages pytest` must keep passing after every task.
- Test file basenames are unique across the repo; no `__init__.py` in test dirs. Read a date-partitioned folder (`history/`, `labels/`, `postings/`) with `pl.read_parquet(sorted(folder.rglob("*.parquet")))`; an `entities/<t>` folder may be read directly. Fixture projects live in `libs/simkit/tests/fixtures/<name>/` (`datagen.toml` + `specs/pack.py` + `specs/kernels.py` [+ `specs/overlays/<name>.py`]).
- Kernel modules (`specs/kernels.py`) import only `from neorisk_simkit import std` and `from neorisk_simkit.engine import ...`; overlay modules import only `from neorisk_simkit.spec import Overlay, dist, std` (and `dataclasses`).
- Stage files by name: **never** `git add -A` or `git add .`. Commit messages end with exactly:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN
  ```
- **No checked-mode runs inside tasks** (user directive): no task runs `--checked`, `checked=True` worlds or `NUMBA_BOUNDSCHECK=1`. The checked engine runs once, at the milestone's final review (D90). Uncompiled comparisons (`NUMBA_DISABLE_JIT=1` subprocesses) are allowed where a task asks for them.
- **Compile time** (D90): a cold Numba compile of an ecommerce_s2-sized module takes 45–90 min on this machine; a small fixture compiles in 1–5 min. Every edit under `engine/`, `std/` or `spec/dist.py` changes the runtime fingerprint and recompiles every module. Hence: keep fixtures small (few events, few processes), write a kernel completely before its first compile, batch engine edits inside a task, run long test files in the background, and never edit engine/std files in Tasks 14–23 (all engine work lands in Tasks 1–12).
- **S1 identity:** the S1 reduced-profile dataset hash `4659ac00c0af3e400065aee6cf9d7d89d26a42a4c3a635a0e9d593fada09695d` must stay unchanged by every task except Task 12, which changes S1 output on purpose (`cause_id` values) and records the new hash. Procedure (cold compile ~8 min, warm ~10 s):
  ```bash
  uv run --all-packages datagen run examples/ecommerce_s1 --profile full --seed 42 \
      --set users=400000 --set run.span=30d --out /tmp/s1r --force
  (cd /tmp/s1r && find . -type f ! -name manifest.json ! -name run_stats.json | LC_ALL=C sort \
      | while read f; do echo "$f $(shasum -a 256 "$f" | cut -d' ' -f1)"; done \
      | shasum -a 256 | cut -d' ' -f1)
  ```
- Machine: 14 cores / 36 GiB. A gate whose caps exceed ~30 GiB is reported "not measured — needs the 64 GB reference machine", never shrunk (S2 Task 21 ruling).
- No new runtime dependencies except `pyyaml>=6` for `expectations.yaml` (D84). `confluent-kafka` is not added.

**M3 scope (§18, verbatim)**
- "M3 | State machine; e-commerce pack at parity through the legacy adapter; bounty-hunter overlay replaces the hand-coded fraud scenario | All machine operations, the overlay contract, the campaign trace, the interference report".

**State machine operations (§04, verbatim)**
| Operation | Semantics | Edge cases decided |
|---|---|---|
| branch | On entering a state, pick one outcome by probability, then wait its delay | Unpicked mass is an explicit otherwise |
| timer | Fires after a delay unless the state is left first | Leaving bumps a generation counter; stale timers drop when popped |
| repeat | Self-transition with its own delay and maximum count | Stops at the maximum, or when until becomes true |
| until … then | Conditional termination evaluated after each committed action | Conditions are typed helpers, never expressions |
| spawn | Create child processes (same owner) or new owners | Counts declared; depth and admissions bounded (06) |
| join | Wait for a named message from each expected child, with timeout | Zero children fires immediately. Duplicates are suppressed by a per-parent bitset of child ordinals, bounded by max children. Late arrivals follow a declared late="ignore" \| "count" |
| request | Send an immutable request to a shard and wait for its response | Timeout and a rejection branch are mandatory |
| then | Sequential composition: each part is its own atomic action | If the second rejects, the first stays committed and the second's fallback runs. An atomic composite is written as one kernel |
- "A table-driven interpreter with closed semantics … Calls actions through a generated, inspectable dispatch module."

**Execution model (§06, verbatim)**
- "Spawn bounds. Each process declares max_spawn_depth (default 3), and each step has a max_admissions limit. Exceeding either fails the run with a diagnostic naming the process."
- "Owner-to-owner messages (an inviter credited when an invitee qualifies) are allowed only when the target doesn't act on them within the step: they're delivered at the next step boundary or later. Anything tighter means the two belong to one owner (a campaign, a household)."
- "A timer or message addressed to a retired instance is detected by slot generation, dropped, and counted as late_messages in the manifest." (§05)
- Every S1/S2 rule stays: blocking suspension (contracts Task 10 ruling), requests dated exactly `ctx.t`, `H = min(step end, min(t_req + δ), min(t_create))`, `lamport = max(partition_clock, cause_lamport) + 1`, canonical key `(event_time, lamport, partition_id, seq)`, D61 sender keys.

**Overlay contract (§08, verbatim)**
| Need | Mechanism |
|---|---|
| Configurable size | cohort(size=… \| share=… \| rate=…) with arrivals; member IDs come from their own deterministic namespace |
| Same event schema | Overlays emit observable rows only through base-pack actions and std helpers |
| Different behavior | Cohort members run overlay processes; suppress disables named base processes for them |
| Base pack extension points | Named actions, named processes, a parameterized execution_owner, and reference hooks; validate checks them against the resolved plan |
| Waiting on children | join with timeout, duplicate suppression and a declared late policy (04) |
| No cross-owner cycle | Hunter and zombies share the campaign owner; campaigns run in parallel |
| Bonus pool | Uncapped: accumulate. Capped: a pool shard reached by request; normal users' claims use the same shard |
| Labels | Hidden labels/ rows: campaign, role, outcome, label_available_at |
| Regression | If the overlay shares no decision-relevant state with the base (validation decides from access declarations), base rows must be identical with and without it. If it does (a capped pool, inventory), CI asserts instead that base users' exogenous draws (arrivals, attributes, journey choices before first contact) are identical, laws and conservation hold, and the report shows interference: base outcomes that changed, for example normal claims rejected because hunters drained the pool |

**Campaign trace (§07, verbatim)**
| Time | Partition | What happens |
|---|---|---|
| day 12 09:14 | campaign C (owner) | Zombie Z7 places its first order above the minimum; the campaign's zombie process sends claim(invitee=Z7, amount=20) to the pool shard and the owner suspends |
| round | pool shard | Processes all claims below H in canonical order, from all campaigns and normal users. Grants Z7's claim and decrements the remaining cap |
| 09:14 + 0.5 s | campaign C | Response: granted. Emits bonus_paid(Z7). Join counter decrements; the hunter process continues |
| day 12 16:40 | campaign C | Z11's claim is rejected (cap exhausted). Z11 leaves; label outcome = attempted |

**Checks, report and workflow (§11, §02, §16, verbatim)**
- "Statistical | Samples or exact streams | … | Funnels, gaps, degree, concentration, cohort shares". "Cases are sampled by owner hash, stratified so rare cohorts get a minimum count, including censored cases. Estimates use inverse-probability weights per stratum, and the censoring rate is reported next to every case metric." "Concentration is exact from streaming per-entity aggregates." "Campaigns are sampled whole." "Statistics carry minimum sample sizes and case-level confidence intervals on held-out seeds."
- "One compact report: counts, linkages, transitions, concentration, rejections, cohorts, interference, checks."
- "CI generates the report for the PR head SHA. Required checks fail CI if missing, inconclusive or unanchored." "A one-line CODEOWNERS rule requires someone other than the author to approve changes to expectations.yaml or checks/domains/."
- Output (§13): `labels/` holds "target id, final_label, label_available_at, campaign_id, role, outcome"; common column `cause_id` (nullable BIGINT). "Legacy adapter: datagen export --legacy-fraud writes today's events.parquet / golden.parquet / meta.json for bench." §10 table: "scenarios/fraud.generate | Replaced by the e-commerce pack plus the bounty-hunter overlay (M3)".

## Decisions made by the planner

Where the spec is silent or ambiguous; each line is binding for this plan. Numbering continues from S2 (D61).

- **D62** *Machine compilation.* All machines declared on one owner partition type compile into **one** generated process `mx_<partition>` (one action id), so parents, children and joins of one owner share one `Local` and need no intra-partition messaging. Its kernel source is authoring-dialect text built by `machine.compile`: the text of the kernels file that holds the machines' `@action` functions (if any) followed by the generated machine text; `KernelSpec.source` carries that combined text and `codegen.lowered_kernels` lowers it instead of reading the file. Machines live only on owner partitions (shards keep handwritten kernels). Plan order of processes: base `p.process` in declaration order, then base machine processes (partition order), then overlay machine processes; overlays declare no `p.process`, so base action ids never move.
- **D63** *Instances.* A machine declares `max_instances=K` (default 1, at most 64); instance memory is `Local` arrays of width `max(K, 2)` named `<machine>__<field>`. Implicit fields: `st` (i16, 0 = free, else 1 + state index), `gen` (i64, bumped on every state entry), `ep` (i64, bumped on allocation), `rep` (i16), `t0` (i64, entry time), `dep` (i8, spawn depth), `par` (i8, parent instance or -1), `pm` (i8, parent machine index), `pep` (i64, parent epoch), `ord` (i8, ordinal among the parent's children), `kids` (i8), `jb` (i64, join bitset), `jn` (i8), `jl` (i8, D69), `actor` (ref), `pactor` (ref); declared `fields={name: "i64"|"ref"|...}` follow. An instance's actor is `ctx.self_id` for a machine on a base owner and its `actor` field (a member row) for a cohort machine.
- **D64** *Commands and tags.* Command kinds of `mx_<p>`: `START` (0), `MX_FIRE` (1) for every machine timer, and 2.. for the responses of request ops (`on_response`). A tag is `m << 41 | i << 35 | (gen & 0xFFFFF) << 15 | op << 12 | x` (machine ≤ 16 per partition, instance < 64, generation modulo 2^20, op 3 bits, 12-bit index); ops `OP_BRANCH 1, OP_TIMER 2, OP_REPEAT 3, OP_CHAIN 4, OP_SPAWN 5, OP_NOW 6, OP_REQUEST 7`. A popped command whose instance is free or whose generation differs is stale and returns `reject(MX_STALE)` before any write (§04 "stale timers drop when popped"). A stale match after exactly 2^20 entries is accepted as negligible.
- **D65** *Action ABI.* `@action(state=, max=Res(...), fields={...})` decorates `(ctx, s, m, cmd, out)` and returns an `ActionRef`. An action never calls `out.reserve` (the machine reserves `max` plus its own needs before calling, so an action can never RETRY); it may `return reject(code)` only before its first write; `m.id` is the actor, `m.parent_id` the parent's actor, `m.<field>` a declared instance field (the action's `fields` must be declared by every machine that calls it — validate). The generator copies each called action and its helper call graph per machine (renamed `mx_<m>_<fn>`), rewriting `m.*`, `ctx.cfg` → `ctx.cfg.<machine>` and `site=N` → `site=9000 + 128·copy + N` (actions use sites `0 ≤ N < 128`, at most 163 copies per partition; machine-op draws of state `k` of machine `m` use sites `1 + 16·(32·m + k) + j`, `j < 16`, so a machine has at most 32 states, a partition at most 16 machines, and one state entry at most 16 draw sites — validate). Sites are assigned in declaration order, so edit stability is best effort (§12).
- **D66** *Rejected parts.* A rejected action part never rejects the machine command: the machine commits its own bookkeeping. A part with `.otherwise(b)` runs `b` as the next part; without a fallback the chain ends and the instance enters the state's `on_reject` target if declared, else ends (frees). Rejected parts are counted per machine in `run_stats.json` `machines.<m>.rejects` (the out-tail array `mstat`, D82).
- **D67** *Request timeout.* Blocking suspension (S1 ruling) means no timer of a suspended owner can fire, so a request op's `timeout` is judged on arrival: a response with `ctx.t − t_request > timeout` takes `on_timeout` (default `on_reject`), whatever it says; `== timeout` is in time. A request op must declare `timeout=` and `on_reject=` (validate).
- **D68** *Entry and priorities.* Entering a state happens inside the committing command (no extra command). Machine timers use `PRIO_TIMER`; chain parts after the first and immediate firings (`OP_NOW`: a join with zero children, `until` already true on entry) are queued at `ctx.t` with `PRIO_CONTINUE`, so generated code never recurses. A branch outcome with delay `None` is a 0-delay `PRIO_TIMER` timer.
- **D69** *Join.* Children of a join are the instances this instance spawned (same owner, `kids` of them). `std.send_parent(msg)` updates the parent's `jb`/`jn` in the child's command (one process, D62) whatever state the parent is in, so a child that answers before the parent reaches its join state is not lost; a duplicate child ordinal is suppressed by `jb`. A join state completes when `jn == kids`: on entry (via `OP_NOW`, zero children included) or on the message that completes it. After the parent has left a join state (completion or timeout), or when the parent ended or its epoch changed, a message is late: dropped, and counted in `machines.<m>.late` when that join state declared `late="count"` (instance field `jl`: 0 none, 1 left an ignoring join, 2 left a counting join). Children send exactly the message their parent's join names (validate). A join completing at the same instant as its timeout: whichever command pops first wins (canonical queue order); the loser is stale.
- **D70** *until.* Typed conditions `std.cond.ge|le|eq(a, b)` and `std.cond.repeats_ge(n)` over instance fields, owner state columns, the repeat count and constants; evaluated on entering the state and after each committed action of that instance in that state; true → `then` target via `OP_NOW`.
- **D71** *Branch probabilities.* An outcome's probability is a float, `std.p_by(col, {value: p}, otherwise=p)` (by an owner state category) or `None`; at most one outcome is `None` and takes `1 − Σ others`; without a `None` outcome the probabilities must sum to 1 within 1e-9 (validate: "give the unpicked mass an explicit otherwise outcome").
- **D72** *Spawn depth at runtime (resolves F-04, supersedes D42's static check).* `p.process(..., max_spawn_depth=)` and `p.machine(..., max_spawn_depth=)` default to `budget.max_spawn_depth`. Each slot has a hidden `depth` (population owners and shards 0; a created owner = creator + 1); a same-owner child instance has `dep` = parent + 1. A creation or spawn beyond the creating process's limit fails the run: `CapExceeded("max_spawn_depth", limit, depth, process=<creator>)` (admission) or `EngineError("<machine>: spawn depth ...")` (in-kernel). validate no longer refuses creation cycles (they are bounded at runtime) and refuses `max_spawn_depth < 1` per process.
- **D73** *Owner-to-owner messages (resolves D57).* A `p.message` from an owner partition to an owner partition is allowed when (a) its latency's minimum is ≥ `engine.step_max` (so delivery `t + latency` always lands in a later step and does not depend on step length) and (b) the target partition has a population (targets are addressed by the target table's dense id, the population ordinal). Rows are set aside at routing, delivered at the end of the step's rounds (before `end_step`) into the target's queue under the sender's D61 key; a target that has not arrived, has retired or is a member row (id ≥ population n) is dropped and counted in `late_messages`.
- **D74** *Execution owner (§08 "a parameterized execution_owner").* A base pack exposes an owner partition with `p.expose_owner("user")`. An overlay cohort creates a new owner partition type (one owner per campaign, keyed by `execution_owner`, default `<cohort>_id`) with `acts_for="user"`: its processes may emit every event of `user`, send every boundary whose `frm` is `user`, and create member rows of the `user` table with `out.add_member_user(...)` (a row in `entities/user`, no owner admission). Base users always execute as their own owners.
- **D75** *Member identity.* Namespace codes: base creatable tables, base `p.ids`, then tables and ids added by overlays, so base codes never move. A member row of a population table gets dense index `n_population + k` (k by the §12 prefix sum), so base IDs never move; the D48 ref range for that table becomes `[0, pop.next) ∪ [n, id_bases[table])`.
- **D76** *Labels.* `p.labels(name, owner=, cols=)` declares hidden label records (record group `"labels"`, like D45 postings): emitted with `out.emit_<name>`, written to `labels/<name>/date=YYYY-MM-DD/step-NNNNNN.parquet`, counted in manifest `label_counts`, typed `"label"` in `schema.json`, never in `counts`, `exported_events`, `_index/steps.parquet` or replay. `o.label(...)` declares `labels_<cohort>` with columns `target_id, campaign_id, role, outcome, final_label, label_available_at`; a target's label is its last row. *Deviation:* §13 shows `labels/part-*.parquet`; per-step files keep the writer streaming like every other table.
- **D77** *Overlay parameters.* `apply(o, **params)` gets values from `[profiles.<p>.overlay.<name>]` then `--set <name>.<param>=v`; only `int|float|str|bool` defaults are settable (a `Dist` default is fixed in code). Overlays are enabled by `[profiles.<p>] overlays = [...]` or `--overlay NAME` (repeatable); the run name is `<profile>-s<seed>+<o1>+<o2>`. Overlay op parameters live in the machine process config, so `--set` never changes generated source (no recompile).
- **D78** *Regression rule.* An overlay shares decision-relevant state iff one of its processes sends a boundary whose target is a base shard or base owner (`checks.interference.shared_partitions(plan)`). Base rows are the rows of base partitions; they are compared with `event_id` excluded (event dense ids advance by overlay rows of earlier steps) and created IDs canonicalized (D37). No sharing ⇒ base rows equal as multisets. Sharing ⇒ base entity rows equal, base rows with `event_time` before the overlay's first boundary row to a shared partition equal, every required law passes in both runs, and the interference report lists the changes.
- **D79** *Interference report.* For `stat.interference(base=E, cause=S)`: per base event type count with and without the overlay; the number of base owners whose `E` rows differ; and, for shard `S`, base requests answered differently (granted ↔ rejected) — read from the two datasets, written to `checks.json` and `report.html`.
- **D80** *`cause_id` (resolves D14).* The `event_id` of the first record (lowest `seq`) of the nearest commit in the command's causal chain that emitted a record; null when the chain starts at a population/periodic `START` without such a commit or the causing record was not exported (warm-up). Nodes carry `cpid`/`ceid`; a per-worker commit log resolves causes at seal (Task 12).
- **D81** *`sum_le` against state (resolves F-07).* `law.sum_le("refund_issued.amount", "order.amount", by="order_id")`: when the right side is `<owner table>.<column>`, `by` must name the owner table's key; the law keeps the last seen value per key (read from live and just-retired owners at each seal, warm-up included) and judges each exported left-side row's running sum against it; a key never seen on the right is judged against 0.
- **D82** *Machine statistics.* `out.mstat(i, v)` adds to a per-worker `int64` array (out tail `mstat`); per machine the counters are `late, rejects, spawned, entries[state]`; `World.take_machine_stats()` folds them; `run_stats.json["machines"]` reports them (never the manifest, so packs without machines keep byte-identical manifests).
- **D83** *Request op form.* `std.request(local, ok="granted", shard=0, store={resp_field: instance_field}, **payload)`; responses other than `ok` take `on_reject`.
- **D84** *Expectations.* `expectations.yaml` is parsed with PyYAML (new runtime dependency of `neorisk-simkit`); each `metric:` is a string parsed by `ast` as one call `stat.<name>(kw=literal, ...)` (no expressions). Supported metrics: `funnel, share, quantiles, top_share, distribution, cohort_share, interference`. Targets: `between`, `lt`, `gt`, `around`+`tolerance`, `reported`, per-quantile maps.
- **D85** *Sampling and confidence.* Cases are owners (`partition_id`). A case is sampled when `mix64(partition_id) / 2^64 < rate`; strata are the base partitions and each cohort partition; a stratum's rate is raised to reach `min_sample` cases (or all); estimates are inverse-probability weighted per stratum; campaigns are whole owners, so "sampled whole" holds. Proportions get a 95% Wilson interval on effective case counts; quantiles a binomial order-statistic interval; a metric with fewer than `min_sample` cases is `inconclusive`. Funnels with `within=` censor cases whose start is later than `end − within` and report the censoring rate. Held-out seeds are deferred (Later).
- **D86** *`datagen check`.* `datagen check <project> --profile P [--overlay N] [--baseline DIR]` reads `out/<run>`, writes `reports/<run>/report.html` and `checks.json`, and exits 0 when every required check passes, **5** when a required check fails, is missing, inconclusive or unanchored (no `source:`), 2 on usage errors.
- **D87** *Legacy adapter mapping.* `order_placed` → `event_type 0`; `referral_bonus_paid` with `role = "inviter"` → `event_type 1` with `user_id` = the invitee and `inviter_id` = the inviter; `event_id` = `"<event type>:<engine event_id>"`; amounts in dollars (`float64`, cents / 100); user, device and product attributes as integer codes as of the event time (`user_state` from the `address` change group); `label = 1` when the row's user (or, for invite rows, its inviter) is a labeled cohort target, label maturity ignored (M4); `golden.parquet` = batch rolling features of today's names plus `actor_role` and `score = label`; `meta.json` carries `feature_allowlist`, `source` (pack, revision, overlays, run) and the run's seed.
- **D88** *Parity.* Parity means: the adapter output passes `neorisk_simkit.export` validation, bench `load_events`, `runner.run` and `compare` on it, and the properties today's fraud tests pin (determinism, no golden leakage, bad rate band, stable attributes, invites reference other users, planted bounty-hunter signature, no future leakage, aligned golden) hold — `apps/datagen/tests/test_legacy_fraud_parity.py` ports `test_datagen_fraud.py` to the adapter.
- **D89** *Fraud scenario retired.* `apps/datagen/src/datagen/scenarios/`, `datagen/config.py` and `datagen generate` are deleted; `datagen generate` prints the replacement command and exits 2. The library's legacy modules (`attributes`, `entities`, `features`, `scorer`, `references`, `export`) stay (bench uses `features.rolling*`; the adapter uses `export`).
- **D90** *Process.* Checked-mode runs only at the milestone's final review; engine edits only in Tasks 1–12; examples tasks change `examples/` and `checks/`/`io`/apps code outside the runtime fingerprint.
- **D91** *E-commerce model.* `examples/ecommerce` is rewritten to the real API (the current files are a design sketch): owner `user` (population; invitees are population users with `referred` and `invited_by` among the first `inviter_share` of users), created owner `order` (one per placed order, ≤ 7 columns, D43) running the `fulfillment` machine, shards `inventory` (hold table, D49) and `referral_pool` (n = 1, budget reset every 30 days by a periodic process — "monthly" approximated), owner-to-owner `inviter_credit` (D73, one-day minimum latency, `engine.step_max = "1d"`). Carts hold up to 5 lines. `flash_sale` is deferred (D93).
- **D92** *Gates in M3.* §18 sets no M3 gate. Task 23 re-measures the S1 gate (≤ 60 s warm, ≤ 16 GB) and `s2_pool` (both D55 rates) after the engine changes; `s2` full stays "not measured" on this machine. The open S2 items are carried, not resolved (see "Open items carried").
- **D93** *Deferred overlay pieces.* `flash_sale` (needs `existing=True` cohorts of base owners and shard-state hooks `pick_skus`/`adjust_stock`), cohorts with `existing=True`, and machines on shards are Later; machines and overlays in M3 cover the bounty-hunter overlay and the fixtures.
- **D94** *Cohort references.* A refs recipe given on a cohort (`o.cohort(..., refs={"device": std.devices(...)})`) appends its rows to the base read table after the base rows (ids offset by the base row count), so base device IDs never move; `std.pick_ref(refs, parent_share=p)` initializes an instance field from the owner's refs (with probability `p` the parent's value).

## Review Focus

Inputs the spec implies but no exit test names; each line has a pinning test in the owning task.
1. **Spawning more children than a machine has instance slots** (or a `std.spawn` count drawn above `max_instances`): the run fails naming the machine — never a silent truncation or an overwritten instance (Task 7, `test_spawn_beyond_instances_fails_naming_the_machine`).
2. **A join completing at the same instant as its timeout:** exactly one transition happens and the other command is stale (Task 7, `test_join_and_timeout_at_one_instant_transition_once`).
3. **A request whose response arrives exactly at the timeout:** in time (`==`), one microsecond later is a timeout (Task 8, `test_timeout_boundary_is_inclusive`).
4. **An owner-to-owner message to an owner that retired, has not arrived, or is a member row:** dropped and counted in `late_messages`, never delivered into a reused slot (Task 2, `test_messages_to_absent_owners_are_late`).
5. **An overlay cohort of size 0, and an overlay whose cohort arrives after the run ends:** the run passes, the schema is unchanged, `label_counts` is 0, base rows are identical to the base run, and statistics over too few cases are `inconclusive`, not errors (Task 10 `test_a_zero_size_cohort_changes_nothing_in_the_base`, `test_a_cohort_arriving_after_the_end_never_acts`; Task 18 `test_small_samples_are_inconclusive`).

## Engine reference deltas (M3)

Everything in the S1 Engine reference and the S2 deltas stays except:
- **`KernelSpec`** gains `source: str | None = None` (D62). **`ActionSpec`** `(name, func, module_file, state, max: Res, fields: Mapping[str, str])`; `engine.action(...)` returns `ActionRef(spec, parts=((spec, None),))` with `.then(x)` and `.otherwise(y)`.
- **`ProcessDef`** gains `max_spawn_depth: int | None = None` (D72) and `machine_partition: str | None = None` (set on `mx_<p>`).
- **`PartitionDef`** gains `acts_for: str | None = None` (D74). **`BoundaryDef`** gains `o2o: bool = False` (D73).
- **`Plan`** gains `machines: tuple[MachineDef, ...] = ()`, `machine_sources: Mapping[str, str]` (partition → generated machine text), `overlays: tuple[str, ...] = ()`, `cohorts: tuple[CohortDef, ...] = ()`, `exposed: Mapping[str, Any]`, `exposed_owners: tuple[str, ...]`, `member_tables: tuple[str, ...]`.
- **Hidden arrays:** `("depth", "uint8", 1)` appended (D72).
- **World tuple `W`:** `WORLD_FIELDS` += `"max_depth"` (int64[actions], resolved limit per action) (Task 1).
- **Admission statuses:** `ADM_DEPTH = 4` (value = the CQ row) (Task 1).
- **Route tuple `R`:** `RT_O2O` (28): `(cols int64[C, len(OUTBOX_COLS)], pay int64[C, PAYLOAD_W], n int64[1])` with `C = engine.max_messages_per_step`; `RT_BND_O2O` (29): `uint8[boundaries]` (Task 2).
- **`out` tuple tail:** `OUT_TAIL = ("outbox", "lat", "shard_n", "seed", "cmd_kind", "acc", "mstat", "clog", "clog_n")`; `mstat` int64[max(1, machine counters)] (Task 6); `clog` int64[cap, 5] `(pid, lamport, cpid, clamport, ceid)` and `clog_n` int64[1] (Task 12).
- **Command nodes:** `NODE_FIELDS` += `("cpid", "int64"), ("ceid", "int64")` (Task 12); `NODE_BYTES` follows.
- **Generated helpers:** `_member_<table>(out, ctx, *cols) -> handle` (Task 3), `_mstat(out, ctx, i, v)` (Task 6). Lowering: `out.add_member_<table>(**cols)`, `out.mstat(i, v)`.
- **Records group** `"labels"` beside `"events"` and `"postings"` (Task 4).

## File structure

```
libs/simkit/src/neorisk_simkit/
  engine/{abi,lower,codegen,layout,slabs,world,route,cmdq,admit,rounds,run,errors}.py
  machine/__init__.py   machine/spec.py      # builder, MachineDef, ops, validation (Task 5)
  machine/helpers.py                          # std.emit/spawn/send_parent/label/request/... (Task 5)
  machine/layout.py                           # instance fields, tag layout, sites (Task 6)
  machine/copy.py                             # action copies: AST rewrite of m./ctx.cfg/site (Task 6)
  machine/compile.py                          # generated machine text + mx_<p> ProcessDef (Tasks 6-8)
  spec/{pack,plan,validate,project,caps,law,dist,overlay,expectations}.py
  std/{__init__,sources}.py
  checks/{laws,structural,interference,stats}.py
  io/{seal,writer,manifest,dataset,legacy}.py   io/schema/schema_json.py
  report/__init__.py   report/html.py         # report.html (Task 19)
libs/simkit/tests/
  fixtures/{recur,courier,crew,tagged,mx_basic,mx_family,mx_pay,ring,campaign_trace,causes,refunds}/
  test_engine_spawn_depth.py test_engine_owner_messages.py test_engine_members.py
  test_spec_labels.py test_machine_spec.py test_machine_basic.py test_machine_family.py
  test_machine_request.py test_exit_machines.py test_overlay_api.py
  test_exit_campaign_trace.py test_engine_cause.py test_checks_laws_m3.py test_checks_stats.py
  test_checks_interference.py test_exit_invariance_m3.py
apps/datagen/src/datagen/{cli,run_cmds,check_cmd,export_cmd}.py   (scenarios/, config.py deleted)
apps/datagen/tests/test_example_ecom.py test_example_ecom_referral.py test_example_ecom_bounty.py
  test_example_ecom_interference.py test_datagen_check_cli.py test_legacy_fraud_parity.py
  test_example_ecom_calibration.py   (test_datagen_fraud.py deleted)
apps/bench/src/bench/datagen_section.py  apps/bench/README.md  apps/bench/tests/test_bench_allowlist.py
examples/ecommerce/{README.md,datagen.toml,specs/{brief.md,expectations.yaml,pack.py,kernels.py,
  overlays/bounty_hunters.py}}   (overlays/flash_sale.py deleted, D93)
examples/README.md  examples/AGENTS.md  benchmarks/README.md (M3 section)
```

Task dependency order: execute in numeric order. Hard dependencies: 1 → 2 → 3 → 4 (engine seams: hidden arrays, route tuple, layout, writer); 5 needs 4; 6 needs 5; 7 needs 6; 8 needs 7 and 1; 9 needs 8; 10 needs 3, 4, 8; 11 needs 10; 12 needs 11 (last engine edit); 13 needs 12; 14 needs 13; 15 needs 14 and 2; 16 needs 15 and 10; 17 needs 16; 18 needs 17; 19 needs 18; 20 needs 16; 21 needs 20; 22 needs 19 and 21; 23 needs 22.

---
### Task 1: Spawn depth at runtime, per process (F-04, D72)

S2's D42 refused every owner-creation cycle at validate and used one budget-wide static depth. §06 gives each process its own `max_spawn_depth` (default 3) and fails at runtime. This task makes depth a hidden per-slot counter checked by the compiled admission, so bounded recursion runs and excess fails naming the creating process.

**Files:**
- Create: `libs/simkit/tests/fixtures/recur/{datagen.toml,specs/pack.py,specs/kernels.py}`
- Modify: `libs/simkit/src/neorisk_simkit/spec/pack.py` (`process(..., max_spawn_depth=None)`), `spec/plan.py` (`ProcessDef.max_spawn_depth`), `spec/validate.py` (drop `_spawn_errors`, `_creation_cycle`, `_longest_spawn_chain`; per-process check), `engine/world.py` (`HIDDEN_DTYPES` += `depth`; `_reset_slots` zeroes it; `max_depth` array in `W`; `admit_created` handles `ADM_DEPTH`), `engine/admit.py` (`ADM_DEPTH = 4`), `engine/codegen.py` (`WORLD_FIELDS` += `"max_depth"`; `admit()` checks and writes depth)
- Modify tests: `libs/simkit/tests/test_spec_validate.py` (replace `test_chain_depth_two_is_valid_and_bounded` and `test_creation_cycle_is_an_unbounded_spawn`)
- Test: `libs/simkit/tests/test_engine_spawn_depth.py`

**Interfaces:**
- Consumes: S2 admission (`admit_created(W, R, CQ, FS, limit_t, out_slots)`, `CQ_SRC_G`, `CQ_ACTION`), `CapExceeded(item, limit, attempted, process=)`.
- Produces: `Pack.process(..., max_spawn_depth: int | None = None)`; `ProcessDef.max_spawn_depth: int | None = None` (last field, default None); hidden array `depth` (uint8); `W[_W_MAX_DEPTH]` int64[actions] = `pd.max_spawn_depth or run.budget.max_spawn_depth`; `World.max_depth` (same array); `admit.ADM_DEPTH = 4` with value = the CQ row; `World.admit_created` raises `CapExceeded("max_spawn_depth", limit, depth, process=<creating process>)`. Task 7 reuses `World.max_depth` semantics for machines (`ProcessDef.max_spawn_depth` of `mx_<p>`).

- [ ] **Step 1: Write the fixture**

`libs/simkit/tests/fixtures/recur/datagen.toml`: copy `libs/simkit/tests/fixtures/spawn/datagen.toml` and change `name = "recur"`, `span = "2h"`, `step = "2h"`.

`libs/simkit/tests/fixtures/recur/specs/pack.py`:
```python
"""Bounded recursion of created owners (D72): a node creates a child node until `levels`."""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack
from neorisk_simkit.spec.types import i32, ref

from . import kernels as k

PACK = "recur"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Config:
    seeds: int = 2
    levels: int = 3
    max_depth: int = 3


def define(p: Pack, cfg: Config) -> None:
    seed = p.table("seed", key="seed_id", mutable=True, cols={"n": i32()})
    node = p.table("node", key="node_id", mutable=True, cols={"level": i32()})
    p.owner("seed", table=seed, max_live=cfg.seeds)
    p.owner("node", table=node, max_live=cfg.seeds * (cfg.levels + 1))
    p.population(seed, n=cfg.seeds, initial=1.0)
    p.event("grown", owner="node", cols={"node_id": ref("node"), "level": i32()})
    p.process("plant", owner="seed", kernel=k.plant, config=cfg, start=p.on_created("seed"))
    p.process("grow", owner="node", kernel=k.grow, config=cfg, start=p.on_created("node"),
              max_spawn_depth=cfg.max_depth)
```

`libs/simkit/tests/fixtures/recur/specs/kernels.py`:
```python
from neorisk_simkit.engine import COMMIT, RETRY, START, Res, kernel


@kernel(state="seed", commands=(START,), max=Res(creates={"node": 1}))
def plant(ctx, s, cmd, out):
    if not out.reserve(creates={"node": 1}):
        return RETRY
    out.create_node(level=1)
    return COMMIT


@kernel(state="node", commands=(START,), max=Res(records={"grown": 1}, creates={"node": 1}))
def grow(ctx, s, cmd, out):
    if not out.reserve(records={"grown": 1}, creates={"node": 1}):
        return RETRY
    out.emit_grown(ctx.t, node_id=ctx.self_id, level=s.level)
    if s.level < ctx.cfg.levels:
        out.create_node(level=s.level + 1)
    return COMMIT
```

- [ ] **Step 2: Write the failing tests**

`libs/simkit/tests/test_engine_spawn_depth.py`:
```python
"""D72 / F-04: spawn depth is a runtime counter per slot, bounded per creating process."""

import pytest
from conftest import FIXTURES, make_run

from neorisk_simkit.engine import CapExceeded
from neorisk_simkit.engine.world import World
from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events
from neorisk_simkit.spec.validate import validate


def test_a_creation_cycle_validates():
    assert validate(make_run("recur")).ok


def test_bounded_recursion_runs(tmp_path):
    res = run_to_dataset(FIXTURES / "recur", "sample", [], out_dir=tmp_path / "r", threads=1)
    levels = sorted(read_events(res.out_dir)["grown"]["level"].to_list())
    assert levels == [1, 1, 2, 2, 3, 3]


def test_depth_beyond_the_process_limit_fails_naming_it(tmp_path):
    with pytest.raises(CapExceeded) as e:
        run_to_dataset(FIXTURES / "recur", "sample", ["levels=4"], out_dir=tmp_path / "r",
                       threads=1)
    assert (e.value.item, e.value.limit, e.value.attempted, e.value.process) == (
        "max_spawn_depth", 3, 4, "grow")


def test_a_process_without_a_limit_takes_the_budget_default():
    run = make_run("recur", ["budget.max_spawn_depth=5"])
    w = World.build(run, threads=1)
    plan = run.plan
    assert int(w.max_depth[plan.process("plant").action_id]) == 5
    assert int(w.max_depth[plan.process("grow").action_id]) == 3


def test_process_max_spawn_depth_must_be_positive():
    errs = validate(make_run("recur", ["max_depth=0"])).errors
    assert "grow: max_spawn_depth must be >= 1" in errs


def test_chain_fixture_fails_at_runtime_beyond_the_budget(tmp_path):
    with pytest.raises(CapExceeded) as e:
        run_to_dataset(FIXTURES / "chain", "sample", ["budget.max_spawn_depth=1"],
                       out_dir=tmp_path / "c", threads=1)
    assert e.value.item == "max_spawn_depth" and e.value.process == "b_main"
```
(`b_main` is the `chain` fixture's process that creates the depth-2 owner; read `libs/simkit/tests/fixtures/chain/specs/pack.py` and use the name of the process whose `max.creates` names the second created table, if it differs.)

In `libs/simkit/tests/test_spec_validate.py` replace `test_chain_depth_two_is_valid_and_bounded` and `test_creation_cycle_is_an_unbounded_spawn` with:
```python
def test_chain_validates_whatever_the_budget_depth(fixture_project):
    """D72: depth is checked at runtime (test_engine_spawn_depth.py), not by validate."""
    assert validate(_run_of(fixture_project, "chain")).ok
    assert validate(_run_of(fixture_project, "chain", ["budget.max_spawn_depth=1"])).ok


def test_creation_cycle_validates(fixture_project):
    from neorisk_simkit.engine import Res
    run = _run_of(fixture_project, "spawn")
    cyc = _with_kernel(run, "pay_main", max=Res(records={"paid": 1}, creates={"pay": 1},
                                                 requests=1))
    assert validate(cyc).ok
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run --all-packages pytest libs/simkit/tests/test_engine_spawn_depth.py libs/simkit/tests/test_spec_validate.py -q`
Expected: FAIL — `PackError`/`TypeError` (`process() got an unexpected keyword argument 'max_spawn_depth'`) for the recur tests; `test_creation_cycle_validates` fails with the "unbounded spawn" error still reported.

- [ ] **Step 4: Implement**

1. `spec/pack.py` `process(...)`: add keyword `max_spawn_depth: int | None = None`; store it in the process dict. `spec/plan.py`: `ProcessDef.max_spawn_depth: int | None = None` (append as the last field) and pass `d["max_spawn_depth"]` in `build_plan`.
2. `engine/admit.py`: `ADM_OK, ADM_CAP, ADM_LIVE, ADM_NODES, ADM_DEPTH = 0, 1, 2, 3, 4`.
3. `engine/world.py`: append `("depth", "uint8", 1)` to `HIDDEN_DTYPES` (comment: "spawn depth of the slot's owner: 0 for population owners and shards, creator + 1 for a created owner (D72)"); `_reset_slots` sets `hid.depth[g] = 0`; in `_build_world_tuple` build
   ```python
   self.max_depth = np.array([pd.max_spawn_depth or self.run.budget.max_spawn_depth
                              for pd in plan.processes] or [0], np.int64)
   ```
   and add `"max_depth": self.max_depth` to `parts`. `World.admit_created` handles the new status before `ADM_CAP`:
   ```python
   if st == ADM_DEPTH:
       a = int(self.CQ.action[v])
       depth = int(self.hidden.depth[int(self.CQ.src_g[v])]) + 1
       raise CapExceeded("max_spawn_depth", int(self.max_depth[a]), depth,
                         process=self.plan.processes[a].name)
   ```
4. `engine/codegen.py`: `WORLD_FIELDS` += `"max_depth"` (last); import `ADM_DEPTH` and emit `_ADM_DEPTH`; in `admit()` add `"depth"` to the `hid` list and, in the first (all-or-nothing) loop, before the live-slot check:
   ```python
   "    if np.int64(depth[CQ[CQ_SRC_G][i]]) + 1 > W[_W_MAX_DEPTH][CQ[CQ_ACTION][i]]:",
   "        return np.int64(_ADM_DEPTH), np.int64(i)",
   ```
   (the hidden arrays must be read before that loop: move `hid = W[_W_HID]` and the `depth = hid[_WH_DEPTH]` line above the first loop). In the admitting loop write `depth[g] = depth[CQ[CQ_SRC_G][i]] + 1` next to `created[g] = 1`.
5. `spec/validate.py`: delete `_creation_cycle`, `_longest_spawn_chain`, `_spawn_errors` and the `errs += _spawn_errors(run)` line (keep `creation_graph` only if something else imports it — it does not today; delete it too). Keep `budget.max_spawn_depth must be >= 1`. In the per-process loop add:
   ```python
   if p.max_spawn_depth is not None and p.max_spawn_depth < 1:
       errs.append(f"{p.name}: max_spawn_depth must be >= 1")
   ```
6. `spec/caps.py` needs nothing: `hidden_bytes` reads `HIDDEN_DTYPES`.

- [ ] **Step 5: Run the tests**

Run: `uv run --all-packages pytest libs/simkit/tests/test_engine_spawn_depth.py libs/simkit/tests/test_spec_validate.py libs/simkit/tests/test_engine_admit.py -q`
Expected: PASS. Then the full suite `uv run --all-packages pytest -q` (in the background; every module recompiles once) — PASS. Then the S1 reduced-profile hash (Global Constraints) — unchanged.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check $(ls -d libs apps examples/ecommerce_s1 examples/ecommerce_s2 benchmarks 2>/dev/null)
git add libs/simkit/src/neorisk_simkit/spec/pack.py libs/simkit/src/neorisk_simkit/spec/plan.py \
  libs/simkit/src/neorisk_simkit/spec/validate.py libs/simkit/src/neorisk_simkit/engine/world.py \
  libs/simkit/src/neorisk_simkit/engine/admit.py libs/simkit/src/neorisk_simkit/engine/codegen.py \
  libs/simkit/tests/fixtures/recur libs/simkit/tests/test_engine_spawn_depth.py \
  libs/simkit/tests/test_spec_validate.py
git commit -m "feat(engine): spawn depth is a runtime counter bounded per process (F-04, D72)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 2: Owner-to-owner messages (D57 → D73)

**Files:**
- Create: `libs/simkit/tests/fixtures/courier/{datagen.toml,specs/pack.py,specs/kernels.py}`
- Modify: `spec/plan.py` (`BoundaryDef.o2o`), `spec/validate.py` (owner→owner rules), `engine/route.py` (`RT_O2O`, `RT_BND_O2O`, set-aside in `route_outbox`, `deliver_owner_messages`), `engine/world.py` (`_build_route` adds the buffer; `pop_slot` per population table; `deliver_owner_messages()`; `_free_retired` clears `pop_slot` — that function lives in `io/seal.py`), `engine/rounds.py` (call delivery before `end_step`), `engine/codegen.py` (`_send_<b>` skips the shard-range check for owner targets), `io/seal.py` (`_free_retired`), `spec/caps.py` (`requests_and_inboxes` counts the buffer)
- Test: `libs/simkit/tests/test_engine_owner_messages.py`

**Interfaces:**
- Consumes: S2 `route_outbox(R, CQ, ob, n)`, `sender_keys`, `q_push_from`, `pay_alloc`, `World.mark_touched`, counters row 0 `late_messages`.
- Produces: `BoundaryDef.o2o: bool = False` (True for owner→owner messages); route indices `RT_O2O = 28` (tuple `(cols int64[C, len(OUTBOX_COLS)], pay int64[C, PAYLOAD_W], n int64[1])`), `RT_BND_O2O = 29` (uint8[boundaries]); `route.deliver_owner_messages(R, slots) -> (status, k)` with statuses `ROUTED/NEED_NODES/NEED_PAYLOAD` and `slots` a tuple (indexed by boundary code) of int64 arrays mapping target dense id → global slot (-1 = absent; an empty array for non-o2o boundaries); `World.pop_slot: dict[str, np.ndarray]` (population table → int64[n], -1 when the owner is not live); `World.deliver_owner_messages()`; validate errors `"boundary {b}: owner-to-owner messages need a minimum latency >= engine.step_max ({step_max})"` and `"boundary {b}: owner-to-owner messages need a target partition with a population"`. Task 15 (`inviter_credit`) consumes all of this.

- [ ] **Step 1: Write the fixture**

`libs/simkit/tests/fixtures/courier/datagen.toml`: copy `fixtures/spawn/datagen.toml`; set `name = "courier"`, `span = "3d"`, `[engine] step = "6h"`, `step_min = "1h"`, `step_max = "1d"`.

`libs/simkit/tests/fixtures/courier/specs/pack.py`:
```python
"""Owner-to-owner messages (D73): delivered at t + latency, latency >= engine.step_max."""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, dist
from neorisk_simkit.spec.types import i64, ref

from . import kernels as k

PACK = "courier"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Config:
    accts: int = 4
    targets: tuple = (1, 3, 9)        # acct 0 credits each: 3 retires idle, 9 does not exist
    latency_s: int = 86_400


def define(p: Pack, cfg: Config) -> None:
    acct = p.table("acct", key="acct_id", mutable=True, cols={"bal": i64()})
    p.owner("acct", table=acct, max_live=cfg.accts)
    p.population(acct, n=cfg.accts, initial=1.0)
    credit = p.message("credit", frm="acct", to="acct", payload={"amount": i64()},
                       latency=dist.constant(s=cfg.latency_s))
    p.event("credited", owner="acct", cols={"acct_id": ref("acct"), "sender": ref("acct"),
                                            "amount": i64()})
    p.process("acct_main", owner="acct", kernel=k.acct_main, config=cfg,
              start=p.on_created("acct"), messages={"credit": credit},
              on_message={"credit": k.C_CREDIT}, commands=k.ACCT_COMMANDS)
```

`libs/simkit/tests/fixtures/courier/specs/kernels.py`:
```python
from neorisk_simkit.engine import COMMIT, PRIO_TIMER, RETRY, START, Res, kernel, reject

C_CREDIT, C_KEEP = 1, 2
ACCT_COMMANDS = (START, C_CREDIT, C_KEEP)
DAY = 86_400_000_000


@kernel(state="acct", commands=ACCT_COMMANDS,
        max=Res(records={"credited": 1}, timers=1, requests=3))
def acct_main(ctx, s, cmd, out):
    if cmd.kind == START:
        if ctx.self_id == 3:
            return COMMIT                              # nothing queued: retires idle
        if not out.reserve(timers=1, requests=3):
            return RETRY
        if ctx.self_id == 0:
            for j in range(3):
                out.send_credit(ctx.t, to=ctx.cfg.targets[j], amount=10 + j)
        out.timer(ctx.t + 2 * DAY, C_KEEP, prio=PRIO_TIMER)       # stays live for delivery
        return COMMIT
    if cmd.kind == C_KEEP:
        return reject(0)
    if not out.reserve(records={"credited": 1}):
        return RETRY
    s.bal += cmd.amount
    out.emit_credited(ctx.t, acct_id=ctx.self_id, sender=cmd.sender, amount=cmd.amount)
    return COMMIT
```

- [ ] **Step 2: Write the failing tests**

`libs/simkit/tests/test_engine_owner_messages.py`:
```python
"""D73: owner-to-owner messages arrive at t + latency in a later step; absent targets are
late (Review Focus 4)."""

import json
from datetime import UTC, datetime

from conftest import FIXTURES, event_dicts, make_run

from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.spec.validate import validate

DAY = 86_400_000_000


def _run(tmp_path, overrides=(), **eng):
    return run_to_dataset(FIXTURES / "courier", "sample", list(overrides),
                          out_dir=tmp_path / "run", threads=2, engine_overrides=eng or None)


def test_owner_to_owner_messages_validate():
    assert validate(make_run("courier")).ok


def test_latency_below_step_max_is_refused():
    errs = validate(make_run("courier", ["latency_s=3600"])).errors
    assert ("boundary credit: owner-to-owner messages need a minimum latency >= "
            "engine.step_max (86400000000 us)") in errs


def test_message_is_delivered_one_latency_later(tmp_path):
    rows = event_dicts(_run(tmp_path).out_dir)["credited"]
    assert len(rows) == 1
    (r,) = rows
    assert r["amount"] == 10
    assert r["event_time"] == datetime(2026, 3, 2, tzinfo=UTC)   # start + 1 day


def test_messages_to_absent_owners_are_late(tmp_path):
    res = _run(tmp_path)
    m = json.loads((res.out_dir / "manifest.json").read_text())
    assert m["late_messages"] == 2                 # acct 3 retired idle, acct 9 does not exist


def test_delivery_does_not_depend_on_step_length(tmp_path):
    a = event_dicts(_run(tmp_path / "a").out_dir)["credited"]
    b = event_dicts(_run(tmp_path / "b", step_us=12 * 3_600_000_000).out_dir)["credited"]
    assert a == b
```
(The courier fixture's `[defaults] start` is `2026-03-01T00:00:00Z`, copied from `spawn`; if `event_dicts` yields naive datetimes, compare with `datetime(2026, 3, 2)`.)

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run --all-packages pytest libs/simkit/tests/test_engine_owner_messages.py -q`
Expected: FAIL — validate reports `boundary credit: owner-to-owner messages arrive in M3`.

- [ ] **Step 4: Implement**

1. `spec/plan.py`: `BoundaryDef.o2o: bool = False`, set in `build_plan` when `kind == "message"` and both `frm` and `to` partitions are owners.
2. `spec/validate.py`: replace the "arrive in M3" branch:
   ```python
   elif b.o2o:
       if b.min_latency_us < eng.step_max_us:
           errs.append(f"boundary {b.name}: owner-to-owner messages need a minimum latency >= "
                       f"engine.step_max ({eng.step_max_us} us)")
       target = plan.partition(b.to)
       if not any(pop.table == target.table for pop in plan.populations):
           errs.append(f"boundary {b.name}: owner-to-owner messages need a target partition "
                       "with a population")
   ```
3. `engine/codegen.py` `outbound(bd, "send")`: when `bd.o2o`, no `OUT_SHARD_N` range check (the target is validated at delivery).
4. `engine/route.py`: add `RT_O2O, RT_BND_O2O = 28, 29` (document them in the module docstring). In `route_outbox`, inside the delivery loop, before `g = bnd_base[...]`:
   ```python
   if kind == OB_MESSAGE and R[RT_BND_O2O][ob[_BND][i]] == 1:
       buf = R[RT_O2O]
       j = buf[2][0]
       for c in range(len(OUTBOX_COLS)):
           buf[0][j, c] = ob[c][i]
       for c in range(PAYLOAD_W):
           buf[1][j, c] = src[i, c]
       buf[2][0] = j + 1
       continue
   ```
   (`OB_MESSAGE` imported from `engine.slabs`; the message budget `msg` already counts the row, so the buffer of capacity `max_messages_per_step` cannot overflow within a step; `P`/`PA` reserve checks stay as they are — they over-count by the set-aside rows, which is harmless.) Add:
   ```python
   @njit(cache=True, nogil=True)
   def deliver_owner_messages(R, slots):
       """Queue the step's owner-to-owner messages (D73) at their delivery time in sender-key
       order; a target whose slot is -1 or not alive is late. All or nothing on the reserves."""
       buf = R[RT_O2O]
       n = buf[2][0]
       if n == 0:
           return ROUTED, np.int64(0)
       cols, src = buf[0], buf[1]
       P, PA = R[RT_POOL], R[RT_PAY]
       if P[P_FREE_N][0] < n:
           return NEED_NODES, n
       if PA[3][0] < n:
           return NEED_PAYLOAD, n
       ob = (cols[:n, 0], cols[:n, 1], cols[:n, 2], cols[:n, 3], cols[:n, 4], cols[:n, 5],
             cols[:n, 6], cols[:n, 7], cols[:n, 8], cols[:n, 9], cols[:n, 10], cols[:n, 11],
             src[:n])
       keys = sender_keys(R, ob[_SRC_G], n)
       k0, k1, k2, k3, k4, k5 = keys
       order = _route_order(ob, n, keys)
       qhead, alive, counters = R[RT_QHEAD], R[RT_ALIVE], R[RT_COUNTERS]
       rows = PA[0]
       for j in range(n):
           i = order[j]
           table = slots[cols[i, _BND]]
           d = cols[i, _DST]
           g = table[d] if 0 <= d < table.shape[0] else np.int64(-1)
           if g < 0 or alive[g] == 0:
               counters[0, _LATE] += 1
               continue
           row = pay_alloc(PA, 0)
           for c in range(PAYLOAD_W):
               rows[row, c] = src[i, c]
           rows[row, PAY_KIND] = OB_MESSAGE
           q_push_from(P, 0, qhead, g, cols[i, _TIME], cols[i, _PRIO], cols[i, _CAUSE],
                       cols[i, _SRC_SEQ], cols[i, _RESP_KIND], cols[i, _TARGET], cols[i, _TAG],
                       row, 2 * k0[i] + k1[i], k2[i], k3[i], k4[i], k5[i])
           mark_touched(R, g)
       buf[2][0] = 0
       return ROUTED, n
   ```
   (Use the module's existing `_KIND/_BND/_TIME/...` column constants; build `ob` with `OUTBOX_COLS` order exactly as `route_outbox` reads it.)
5. `engine/world.py`: in `_build_route` append to `self.R`:
   ```python
   C = int(self.run.engine.max_messages_per_step)
   self.o2o = (np.zeros((max(1, C), len(OUTBOX_COLS)), np.int64),
               np.zeros((max(1, C), PAYLOAD_W), np.int64), np.zeros(1, np.int64))
   o2o_flag = np.zeros(max(1, len(plan.boundaries)), np.uint8)
   for b in plan.boundaries:
       o2o_flag[b.code] = 1 if b.o2o else 0
   ```
   and add `self.o2o, o2o_flag` as the last two entries of the `self.R` tuple (after `self._adm`, matching `RT_O2O = 28`, `RT_BND_O2O = 29`). In `_build_populations` create `self.pop_slot = {pop.table: np.full(pop.n, -1, np.int64) for pop in plan.populations}`; `admit_population` sets `self.pop_slot[pop.table][ords] = g`; `deliver_owner_messages()`:
   ```python
   def deliver_owner_messages(self) -> None:
       empty = np.full(0, -1, np.int64)
       slots = tuple(self.pop_slot[self.plan.partition(b.to).table] if b.o2o else empty
                     for b in self.plan.boundaries) or (empty,)
       while True:
           st, k = rt.deliver_owner_messages(self.R, slots)
           if st == rt.ROUTED:
               return
           if st == rt.NEED_NODES:
               self._take_reserve_nodes(int(k))
           else:
               self._take_reserve_payload(int(k))
   ```
6. `io/seal.py` `_free_retired`: after computing `gone`, for each population owner part clear its slots: `world.pop_slot[part.table][hid.pid[mine] & ((1 << 56) - 1)] = -1` for `mine` with `hid.created[mine] == 0` (created owners are not addressable).
7. `engine/rounds.py` `run_step`: call `world.deliver_owner_messages()` right before `world.end_step(t1)`.
8. `spec/caps.py`: add `max_messages_per_step × (len(OUTBOX_COLS) + PAYLOAD_W) × 8` to `requests_and_inboxes` when any boundary has `o2o`.

- [ ] **Step 5: Run the tests**

Run: `uv run --all-packages pytest libs/simkit/tests/test_engine_owner_messages.py libs/simkit/tests/test_engine_pairing.py libs/simkit/tests/test_spec_validate.py -q`
Expected: PASS. Full suite in the background — PASS; S1 reduced hash unchanged.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check $(ls -d libs apps examples/ecommerce_s1 examples/ecommerce_s2 benchmarks 2>/dev/null)
git add libs/simkit/src/neorisk_simkit/spec/plan.py libs/simkit/src/neorisk_simkit/spec/validate.py \
  libs/simkit/src/neorisk_simkit/spec/caps.py libs/simkit/src/neorisk_simkit/engine/route.py \
  libs/simkit/src/neorisk_simkit/engine/world.py libs/simkit/src/neorisk_simkit/engine/rounds.py \
  libs/simkit/src/neorisk_simkit/engine/codegen.py libs/simkit/src/neorisk_simkit/io/seal.py \
  libs/simkit/tests/fixtures/courier libs/simkit/tests/test_engine_owner_messages.py
git commit -m "feat(engine): owner-to-owner messages delivered one latency later (D57, D73)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 3: Execution owners and member rows (D74, D75)

The engine half of the overlay contract's "parameterized execution_owner": a partition that acts for an exposed base owner table emits that table's partition's events, sends its boundaries and creates member rows of the table.

**Files:**
- Create: `libs/simkit/tests/fixtures/crew/{datagen.toml,specs/pack.py,specs/kernels.py}`
- Modify: `spec/pack.py` (`expose_owner`, `owner(..., acts_for=)`), `spec/plan.py` (`PartitionDef.acts_for`, `Plan.exposed_owners`, `Plan.member_tables`, namespace order), `engine/layout.py` (executor events; `members`; population tables never `create_`-able), `engine/lower.py` (`out.add_member_<table>`), `engine/codegen.py` (`_member_<table>`; no `_create_<t>` for member tables; executor processes in emit/error lists), `spec/validate.py` (records and boundaries of the acted-for partition), `engine/run.py` (`id_bases[table]` starts at the population size for member tables), `io/seal.py` (member entities `origin = "member"`), `checks/structural.py` (`ref_bounds` union ranges)
- Test: `libs/simkit/tests/test_engine_members.py`

**Interfaces:**
- Consumes: S2 create buffers (`creates:<ns>`), `assign_dense`, `entity_table`, `ref_bounds`, `check_ref_range`.
- Produces: `Pack.expose_owner(name: str) -> None`; `Pack.owner(..., acts_for: str | None = None)`; `PartitionDef.acts_for: str | None = None` (last field); `Plan.exposed_owners: tuple[str, ...] = ()`; `Plan.member_tables: tuple[str, ...] = ()` (tables of partitions named by some `acts_for`, in declaration order); namespace order (D75): creatable tables, `p.ids`, member tables; `KernelLayout.members: dict[str, list[tuple[str, LType]]]` (table → columns; non-empty only for executor processes); lowering `out.add_member_<table>(**cols)` → `_member_<table>(out, ctx, *cols)` returning the provisional handle (reserve under `creates={"<table>": n}`); `ref_bounds(world, id_bases) -> dict[str, tuple[int, int, int]]` meaning `[0, a) ∪ [b, c)`; `check_ref_range(where, values, target, bound, cite=None)` takes that tuple. Tasks 10, 11, 16 rely on all of it.

- [ ] **Step 1: Write the fixture**

`libs/simkit/tests/fixtures/crew/datagen.toml`: copy `fixtures/spawn/datagen.toml`; `name = "crew"`, `span = "2h"`, `step = "2h"`.

`libs/simkit/tests/fixtures/crew/specs/pack.py`:
```python
"""Execution owners (D74): a crew owner acts for the user table — it emits user events, sends
the user's request and creates member rows of `user` without admitting them as owners."""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, dist
from neorisk_simkit.spec.types import cat, i32, ref

from . import kernels as k

PACK = "crew"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Config:
    users: int = 3
    crews: int = 2


def define(p: Pack, cfg: Config) -> None:
    user = p.table("user", key="user_id", mutable=True, cols={"tier": cat("a", "b")})
    p.owner("user", table=user, max_live=cfg.users)
    p.population(user, n=cfg.users, initial=1.0,
                 attrs={"tier": dist.categorical({"a": 0.5, "b": 0.5})})
    p.expose_owner("user")
    desk = p.shard("desk", key="desk", n=1, items=None, state={"asks": "i64"})
    ask = p.request("ask", frm="user", to=desk, payload={"who": ref("user")},
                    responses=("ok",), latency=dist.constant(ms=100))
    p.event("joined", owner="user", cols={"user_id": ref("user"), "tier": cat("a", "b")})
    p.event("asked", shard="desk", cols={"who": ref("user")})
    p.process("user_main", owner="user", kernel=k.user_main, start=p.on_created("user"),
              requests={"ask": ask}, on_response={("ask", "ok"): k.R_OK},
              commands=k.USER_COMMANDS)
    p.process("desk_main", shard=desk, kernel=k.desk_main, on_request={"ask": k.C_ASK})
    crew = p.table("crew", key="crew_id", mutable=True, cols={"size": i32()})
    p.owner("crew", table=crew, max_live=max(1, cfg.crews), acts_for="user")
    p.population(crew, n=cfg.crews, initial=1.0, attrs={"size": dist.uniform_int(2, 3)})
    p.process("crew_main", owner="crew", kernel=k.crew_main, start=p.on_created("crew"),
              requests={"ask": ask}, on_response={("ask", "ok"): k.R_OK},
              commands=k.CREW_COMMANDS)
```

`libs/simkit/tests/fixtures/crew/specs/kernels.py`:
```python
from neorisk_simkit.engine import COMMIT, RETRY, START, Res, kernel

R_OK, C_ASK = 1, 1
USER_COMMANDS = (START, R_OK)
CREW_COMMANDS = (START, R_OK)


@kernel(state="user", commands=USER_COMMANDS, max=Res(records={"joined": 1}, requests=1))
def user_main(ctx, s, cmd, out):
    if cmd.kind == R_OK:
        return COMMIT
    if not out.reserve(records={"joined": 1}, requests=1):
        return RETRY
    out.emit_joined(ctx.t, user_id=ctx.self_id, tier=s.tier)
    out.request_ask(ctx.t, shard=0, who=ctx.self_id)
    return COMMIT


@kernel(state="crew", commands=CREW_COMMANDS,
        max=Res(records={"joined": 3}, creates={"user": 3}, requests=1))
def crew_main(ctx, s, cmd, out):
    if cmd.kind == R_OK:
        return COMMIT
    if not out.reserve(records={"joined": 3}, creates={"user": 3}, requests=1):
        return RETRY
    first = 0
    for j in range(s.size):
        mid = out.add_member_user(tier="b")
        if j == 0:
            first = mid
        out.emit_joined(ctx.t, user_id=mid, tier="b")
    out.request_ask(ctx.t, shard=0, who=first)
    return COMMIT


@kernel(state="desk", commands=(C_ASK,), max=Res(records={"asked": 1}, requests=1))
def desk_main(ctx, s, cmd, out):
    if not out.reserve(records={"asked": 1}, requests=1):
        return RETRY
    s.asks += 1
    out.emit_asked(ctx.t, who=cmd.who)
    out.respond(cmd, "ok")
    return COMMIT
```

- [ ] **Step 2: Write the failing tests**

`libs/simkit/tests/test_engine_members.py`:
```python
"""D74/D75: execution owners emit the acted-for partition's events and create member rows of
its table; base IDs never move."""

import polars as pl
import pytest
from conftest import FIXTURES, make_run

from neorisk_simkit.engine.errors import LoweringError
from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events
from neorisk_simkit.spec import PackError
from neorisk_simkit.spec.validate import validate


def _run(tmp_path, overrides=()):
    return run_to_dataset(FIXTURES / "crew", "sample", list(overrides),
                          out_dir=tmp_path / "run", threads=2)


def test_member_table_is_the_last_namespace():
    plan = make_run("crew").plan
    assert plan.member_tables == ("user",) and plan.namespaces[-1] == "user"
    assert plan.partition("crew").acts_for == "user"
    assert validate(make_run("crew")).ok


def test_executors_emit_user_events_for_member_rows(tmp_path):
    res = _run(tmp_path)
    users = pl.read_parquet(res.out_dir / "entities" / "user")
    joined = read_events(res.out_dir)["joined"]
    crew_rows = joined.filter((pl.col("partition_id") >> 56) == 3)    # crew is ptype 3
    sizes = pl.read_parquet(res.out_dir / "entities" / "crew")["size"].sum()
    assert crew_rows.height == sizes
    assert users.height == 3 + sizes
    assert set(crew_rows["user_id"]) <= set(users["id"])
    members = users.filter(pl.col("origin") == "member")
    assert members.height == sizes and set(members["id"]) == set(crew_rows["user_id"])


def test_executors_send_the_acted_for_request(tmp_path):
    ev = read_events(_run(tmp_path).out_dir)
    assert ev["asked"].height == 3 + 2


def test_base_ids_do_not_move_with_members(tmp_path):
    a = pl.read_parquet(_run(tmp_path / "a", ["crews=0"]).out_dir / "entities" / "user")
    b = pl.read_parquet(_run(tmp_path / "b").out_dir / "entities" / "user")
    base = b.filter(pl.col("origin") != "member")
    assert a.sort("id").equals(base.sort("id"))


def test_acts_for_needs_an_exposed_owner():
    from neorisk_simkit.spec.pack import Pack
    from neorisk_simkit.spec.types import i32

    p = Pack("x", 1)
    t = p.table("u", key="u_id", mutable=True, cols={"a": i32()})
    p.owner("u", table=t, max_live=1)
    c = p.table("c", key="c_id", mutable=True, cols={"a": i32()})
    with pytest.raises(PackError, match="needs p.expose_owner"):
        p.owner("c", table=c, max_live=1, acts_for="u")


def test_add_member_is_only_for_executors(tmp_path):
    src = (FIXTURES / "crew" / "specs" / "kernels.py").read_text()
    bad = src.replace("out.emit_joined(ctx.t, user_id=ctx.self_id, tier=s.tier)",
                      "out.emit_joined(ctx.t, user_id=out.add_member_user(tier='a'), tier=s.tier)")
    from neorisk_simkit.engine.layout import kernel_layouts
    from neorisk_simkit.engine.lower import lower_module

    plan = make_run("crew").plan
    with pytest.raises(LoweringError, match="unknown out method 'add_member_user'"):
        lower_module(bad, kernel_layouts(plan), {"user_main": "user_main"})
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run --all-packages pytest libs/simkit/tests/test_engine_members.py -q`
Expected: FAIL — `AttributeError: 'Pack' object has no attribute 'expose_owner'`.

- [ ] **Step 4: Implement**

1. `spec/pack.py`: `self.exposed_owners: list[str] = []`; `expose_owner(name)` checks `_partition(name, "owner")` and appends; `owner(..., acts_for=None)`: when given, `self._partition(acts_for, "owner")` and `acts_for in self.exposed_owners` else `PackError(f"owner {name}: acts_for {acts_for!r} needs p.expose_owner({acts_for!r}) in the base pack")`; store `"acts_for"` in the partition dict (None for shards).
2. `spec/plan.py`: `PartitionDef.acts_for: str | None = None`; `Plan.exposed_owners`, `Plan.member_tables` (the `table` of each acted-for partition, first appearance order); `namespaces = creatable tables + p.ids + member tables not already listed`.
3. `engine/layout.py` `_layout`: `acted = plan.partition(part.acts_for) if getattr(part, "acts_for", None) else None`; `events` include `e.partition == acted.name` too; `members = {acted.table: _cols(plan.table(acted.table).cols)} if acted else {}`; `creates[ns]` is `None` for tables that have a population (population owners are never `create_`-able) — member tables are created only through `members`.
4. `engine/lower.py` `_out_call`: before the `create_` branch:
   ```python
   if m.startswith("add_member_") and m[11:] in lay.members:
       self._positional(node, what, 0, 0)
       return _call(f"_member_{m[11:]}", out, ctx,
                    *self._columns(node, lay.members[m[11:]], kw, what))
   ```
5. `engine/codegen.py`: in `generate()`, for each namespace that is a table: if it is in `plan.member_tables`, emit `member(ns, code)` (the `create()` body without the `OB_CREATE` outbox block, function name `_member_<ns>`); otherwise `create(ns, code)` as today. `emit(e)`: `procs` = processes of `e.partition` plus processes of partitions whose `acts_for == e.partition` (error messages only). `_reserve_<proc>`: unchanged (reserving `creates:<member table>` also reserves outbox rows because the table is an owner table — harmless over-reservation, document it in the docstring).
6. `spec/validate.py`: a process may reserve records owned by its partition **or** by its partition's `acts_for`; requests/messages of a process must have `frm` equal to its partition or its `acts_for` (add that check while you are in the per-process loop: `for b in (*p.requests.values(), *p.messages.values())`).
7. `engine/run.py` `Simulation.__init__`: `for t in plan.member_tables: self.id_bases[t] = next(pop.n for pop in plan.populations if pop.table == t)` (a member table without population starts at 0).
8. `io/seal.py`: `ORIGIN_MEMBER = "member"`; entities of a member table use it; `seal_step` keeps computing `pids` for owner tables (member rows never become partitions; the values are unused).
9. `checks/structural.py`: `ref_bounds` returns `(a, b, c)`: static/recipe tables `(n, n, n)`; population tables `(pop.next, pop.n, max(pop.n, id_bases.get(t, pop.n)))`; created namespaces `(id_bases[ns], id_bases[ns], id_bases[ns])`. `check_ref_range` accepts `bound=(a, b, c)` and refuses `v < 0 or (a <= v < b) or v >= c`; its message prints `[0, a) ∪ [b, c)` when `b > a`, else `[0, a)` (S2 tests pin the single-range text).

- [ ] **Step 5: Run the tests**

Run: `uv run --all-packages pytest libs/simkit/tests/test_engine_members.py libs/simkit/tests/test_checks_refs.py libs/simkit/tests/test_engine_lower.py -q`
Expected: PASS. Full suite in the background — PASS; S1 reduced hash unchanged.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check $(ls -d libs apps examples/ecommerce_s1 examples/ecommerce_s2 benchmarks 2>/dev/null)
git add libs/simkit/src/neorisk_simkit/spec/pack.py libs/simkit/src/neorisk_simkit/spec/plan.py \
  libs/simkit/src/neorisk_simkit/spec/validate.py libs/simkit/src/neorisk_simkit/engine/layout.py \
  libs/simkit/src/neorisk_simkit/engine/lower.py libs/simkit/src/neorisk_simkit/engine/codegen.py \
  libs/simkit/src/neorisk_simkit/engine/run.py libs/simkit/src/neorisk_simkit/io/seal.py \
  libs/simkit/src/neorisk_simkit/checks/structural.py libs/simkit/tests/fixtures/crew \
  libs/simkit/tests/test_engine_members.py
git commit -m "feat(engine): execution owners act for an exposed table; member rows (D74, D75)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 4: Hidden label records (D76)

**Files:**
- Create: `libs/simkit/tests/fixtures/tagged/{datagen.toml,specs/pack.py,specs/kernels.py}`
- Modify: `spec/pack.py` (`labels(...)`), `io/seal.py` (`SealedStep.labels`), `io/writer.py` (`labels/` directory), `io/manifest.py` + `io/dataset.py` (`label_counts`), `io/schema/schema_json.py` (`"label"` tables), `engine/run.py` (accounting)
- Test: `libs/simkit/tests/test_spec_labels.py`

**Interfaces:**
- Consumes: D45 record groups (`EventDef.group`), the postings writer path.
- Produces: `Pack.labels(name, *, cols, owner=None, shard=None, doc="") -> str` (an `EventDef` with `group="labels"`); `SealedStep.labels: dict[str, pa.Table]` (default empty); files `labels/<name>/date=YYYY-MM-DD/step-NNNNNN.parquet`; manifest key `label_counts: {name: rows}`; `schema.json` table entries with the same type field postings use, value `"label"`. Task 10's `o.label` and Task 20's adapter read these.

- [ ] **Step 1: Write the fixture**

`fixtures/tagged/datagen.toml`: copy `fixtures/spawn/datagen.toml`; `name = "tagged"`, `span = "2h"`, `step = "1h"`.

`fixtures/tagged/specs/pack.py`:
```python
"""Hidden label records (D76): written to labels/, never to events/ or replay."""

from neorisk_simkit.spec import Pack
from neorisk_simkit.spec.types import boolean, cat, i32, ref, ts

from . import kernels as k

PACK = "tagged"
SCHEMA_VERSION = 1


def define(p: Pack, cfg) -> None:
    acct = p.table("acct", key="acct_id", mutable=True, cols={"n": i32()})
    p.owner("acct", table=acct, max_live=3)
    p.population(acct, n=3, initial=1.0)
    p.event("seen", owner="acct", cols={"acct_id": ref("acct")})
    p.labels("tags", owner="acct", cols={
        "target_id": ref("acct"), "role": cat("bad", "good"), "outcome": cat("tried", "done"),
        "final_label": boolean(), "label_available_at": ts()})
    p.process("acct_main", owner="acct", kernel=k.acct_main, start=p.on_created("acct"))
```

`fixtures/tagged/specs/kernels.py`:
```python
from neorisk_simkit.engine import COMMIT, RETRY, START, Res, kernel


@kernel(state="acct", commands=(START,), max=Res(records={"seen": 1, "tags": 1}))
def acct_main(ctx, s, cmd, out):
    if not out.reserve(records={"seen": 1, "tags": 1}):
        return RETRY
    out.emit_seen(ctx.t, acct_id=ctx.self_id)
    out.emit_tags(ctx.t, target_id=ctx.self_id, role="bad", outcome="done", final_label=1,
                  label_available_at=ctx.t + 3_600_000_000)
    return COMMIT
```

- [ ] **Step 2: Write the failing tests**

`libs/simkit/tests/test_spec_labels.py`:
```python
"""D76: label records live in labels/, are counted apart and are never replayed."""

import json

import polars as pl
from conftest import FIXTURES

from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events


def test_labels_are_written_apart_and_counted(tmp_path):
    res = run_to_dataset(FIXTURES / "tagged", "sample", [], out_dir=tmp_path / "r", threads=1)
    d = res.out_dir
    m = json.loads((d / "manifest.json").read_text())
    assert m["label_counts"] == {"tags": 3}
    assert "tags" not in m["counts"] and m["counts"]["seen"] == 3
    tags = pl.read_parquet(sorted((d / "labels" / "tags").rglob("*.parquet")))
    assert tags.height == 3 and set(tags["role"]) == {"bad"}
    assert "tags" not in read_events(d)
    assert not (d / "events" / "tags").exists()
    schema = json.loads((d / "schema" / "schema.json").read_text())
    entry = next(t for t in schema["tables"] if t["name"] == "tags")
    assert "label" in entry.values()
```
(If `schema.json` keeps tables under another key than `tables`, follow how `test_spec_postings.py` reads posting entries and assert the same way.)

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run --all-packages pytest libs/simkit/tests/test_spec_labels.py -q`
Expected: FAIL — `AttributeError: 'Pack' object has no attribute 'labels'`.

- [ ] **Step 4: Implement** — follow every place `group == "postings"` is handled (`grep -rn postings libs/simkit/src`) and add the `"labels"` group beside it: `Pack.labels` = `self._record("labels", "labels", name, cols, owner, shard, doc)`; `seal_step` builds `labels = {e.name: records_out[e.name] for e in plan.events if e.group == "labels"}` into `SealedStep(labels=...)`; the writer writes them under `labels/` with the postings layout; `_simulate` counts `label_counts` and passes it to `write_manifest(..., label_counts=...)`; `schema_json` types them `"label"`; `step_index_row`, `counts`, `exported_events` and `run_stats` row totals exclude them like postings; laws may name label tables like posting tables (no change needed).

- [ ] **Step 5: Run the tests** — `uv run --all-packages pytest libs/simkit/tests/test_spec_labels.py libs/simkit/tests/test_spec_postings.py -q` → PASS; full suite in the background → PASS; S1 reduced hash unchanged.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check $(ls -d libs apps examples/ecommerce_s1 examples/ecommerce_s2 benchmarks 2>/dev/null)
git add libs/simkit/src/neorisk_simkit/spec/pack.py libs/simkit/src/neorisk_simkit/io \
  libs/simkit/src/neorisk_simkit/engine/run.py libs/simkit/tests/fixtures/tagged \
  libs/simkit/tests/test_spec_labels.py
git commit -m "feat(io): hidden label records in labels/ (D76)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 5: Machine declarations — builder, vocabulary, closed-semantics validation

No code generation yet: this task makes `p.machine(...)` declare machines, `@action` declare actions, `std.*` provide the closed vocabulary, and `build_plan` normalize and validate them into `Plan.machines`. Task 6 compiles them.

**Files:**
- Create: `libs/simkit/src/neorisk_simkit/machine/__init__.py`, `machine/helpers.py`, `machine/spec.py`
- Create: `libs/simkit/tests/fixtures/mx_basic/{datagen.toml,specs/pack.py,specs/kernels.py}`
- Modify: `engine/abi.py` (`ActionSpec`, `ActionRef`, `action`), `engine/__init__.py` (export `action`, `ActionRef`, `ActionSpec`), `spec/pack.py` (`machine(...)`; the "arrives in M3" stub goes), `spec/plan.py` (`Plan.machines`, call `build_machines`), `std/__init__.py` (re-export the vocabulary), `io/manifest.py` (engine revision hashes `machine/` too, D22)
- Test: `libs/simkit/tests/test_machine_spec.py`

**Interfaces:**
- Consumes: `Pack` registries, `Trigger`, `Res`, `Local` type grammar (`_LOCAL_RE`), `dist.Dist`, `spec.project.parse_duration`.
- Produces (exact names; Tasks 6–11 build on them):
  - `engine.abi.ActionSpec(name, func, module_file, state, max: Res, fields: Mapping[str, str])`; `engine.abi.ActionRef(spec)` with `.then(x) -> Chain`, `.otherwise(x) -> Chain`; `engine.abi.action(state, max=Res(), fields=None)` (signature `(ctx, s, m, cmd, out)`, `fields` values scalar `Local` types).
  - `machine.helpers`: values `actor()`, `parent()`, `col(name)`, `field(name)`, `new_id(ns)`, `now()`, `after(delay: Dist)`, `near(value: int, above: float)`, `pick_ref(refs: str, parent_share: float | None = None)`; conditions `cond.ge(a, b)`, `cond.le(a, b)`, `cond.eq(a, b)`, `cond.repeats_ge(n)` (dataclass `Cond(op, a, b)`); `p_by(col, probs: dict, otherwise=0.0) -> PBy`; actions returning `Chain`: `emit(event, **values)`, `spawn(machine, n=1, stagger=None, fields=None)`, `send_parent(msg)`, `label(role, outcome)`, `create_owner(table, **values)`, `set_field(name, value)`, `add_field(name, value=1)`; `request(local, *, ok="granted", shard=0, store=None, **payload) -> Request`; data classes `Part(act, fallback=None)`, `Chain(parts)` with `.then/.otherwise`, `as_chain(x)`, and the act types `Emit, Spawn, SendParent, LabelAct, CreateOwner, SetField`.
  - `machine.spec`: `Outcome(target, p, delay, chain)`, `StateDef(...)`, `MachineDef(...)` (fields below), `Machine` builder (`.state(...)`, `.final(*names)`), `build_machines(pack) -> tuple[tuple[MachineDef, ...], list[str]]`.
  - `Pack.machine(name, *, owner, initial, start=None, config=None, max_instances=1, fields=None, reads=None, refs=None, max_spawn_depth=None) -> Machine`; `Plan.machines: tuple[MachineDef, ...] = ()`; `build_plan` raises `PackError` with every machine error joined by newlines.

- [ ] **Step 1: `engine/abi.py` additions**

```python
@dataclass(frozen=True)
class ActionSpec:
    name: str
    func: Callable[..., Any]
    module_file: str
    state: str
    max: Res
    fields: Mapping[str, str]


class ActionRef:
    """An `@action` function as a machine part (D65): `.then(...)` / `.otherwise(...)` compose."""

    __slots__ = ("spec",)

    def __init__(self, spec: ActionSpec):
        self.spec = spec

    def then(self, other):
        from neorisk_simkit.machine.helpers import as_chain
        return as_chain(self).then(other)

    def otherwise(self, other):
        from neorisk_simkit.machine.helpers import as_chain
        return as_chain(self).otherwise(other)

    def __repr__(self) -> str:
        return f"ActionRef({self.spec.name})"


def action(state, max=Res(), fields=None) -> Callable:  # noqa: B008
    """Decorate `(ctx, s, m, cmd, out)`: validate, then commit; never `out.reserve` (the calling
    machine reserves `max`, D65); `m.id`, `m.parent_id`, `m.<field>` name the instance."""
    fields = dict(fields or {})
    for name, decl in fields.items():
        if _LOCAL_RE.match(decl) is None or "[" in decl:
            raise ValueError(f"action field {name!r}: {decl!r} is not a scalar local type")

    def deco(fn: Callable) -> ActionRef:
        params = tuple(inspect.signature(fn).parameters)
        if params != ("ctx", "s", "m", "cmd", "out"):
            raise TypeError(f"action {fn.__name__} must take (ctx, s, m, cmd, out)")
        return ActionRef(ActionSpec(fn.__name__, fn, inspect.getsourcefile(fn) or "", state,
                                    max, MappingProxyType(fields)))

    return deco
```
Also `KernelSpec.source: str | None = None` (append as the last field; Task 6 fills it).

- [ ] **Step 2: `machine/helpers.py`**

```python
"""The closed vocabulary of machines (re-exported by `neorisk_simkit.std`): std actions, value
helpers, typed conditions, probability helpers and request descriptors. Everything here is inert
frozen data; `machine.compile` turns it into generated kernel source (D62)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from neorisk_simkit.engine.abi import ActionRef, ActionSpec
from neorisk_simkit.spec.dist import Dist
from neorisk_simkit.spec.pack import PackError


# ---------------------------------------------------------------- values
@dataclass(frozen=True)
class Actor:
    """The instance's actor: the owner (base machines) or its member row (cohort machines)."""


@dataclass(frozen=True)
class ParentActor:
    """The actor of the instance that spawned this one (std.NULL for a root instance)."""


@dataclass(frozen=True)
class Col:
    name: str                     # owner state column (read)


@dataclass(frozen=True)
class Field:
    name: str                     # declared instance field


@dataclass(frozen=True)
class NewId:
    ns: str                       # a p.ids namespace; reserves one id


@dataclass(frozen=True)
class Now:
    pass


@dataclass(frozen=True)
class After:
    delay: Dist                   # ctx.t + a draw


@dataclass(frozen=True)
class Near:
    value: int
    above: float                  # value + uniform_int(0, floor(value * above))


@dataclass(frozen=True)
class PickRef:
    refs: str                     # the owner's refs CSR (e.g. "device")
    parent_share: float | None = None   # with this probability copy the parent's field


@dataclass(frozen=True)
class Repeats:
    pass                          # the repeat count of the current state


def actor() -> Actor:
    return Actor()


def parent() -> ParentActor:
    return ParentActor()


def col(name: str) -> Col:
    return Col(name)


def field(name: str) -> Field:
    return Field(name)


def new_id(ns: str) -> NewId:
    return NewId(ns)


def now() -> Now:
    return Now()


def after(delay: Dist) -> After:
    if not isinstance(delay, Dist):
        raise PackError("std.after needs a Dist")
    return After(delay)


def near(value: int, above: float) -> Near:
    if not 0 <= above <= 10:
        raise PackError("std.near: above must be in [0, 10]")
    return Near(int(value), float(above))


def pick_ref(refs: str, parent_share: float | None = None) -> PickRef:
    if parent_share is not None and not 0.0 <= parent_share <= 1.0:
        raise PackError("std.pick_ref: parent_share must be in [0, 1]")
    return PickRef(refs, parent_share)


# ---------------------------------------------------------------- conditions and probabilities
@dataclass(frozen=True)
class Cond:
    op: str                       # "ge" | "le" | "eq"
    a: Any
    b: Any


class _Cond:
    """Typed conditions for until (D70); operands are ints, std.col/std.field or repeats."""

    @staticmethod
    def ge(a, b) -> Cond:
        return Cond("ge", a, b)

    @staticmethod
    def le(a, b) -> Cond:
        return Cond("le", a, b)

    @staticmethod
    def eq(a, b) -> Cond:
        return Cond("eq", a, b)

    @staticmethod
    def repeats_ge(n: int) -> Cond:
        return Cond("ge", Repeats(), int(n))


cond = _Cond()


@dataclass(frozen=True)
class PBy:
    col: str
    probs: tuple[tuple[str, float], ...]
    otherwise: float


def p_by(col: str, probs: dict, otherwise: float = 0.0) -> PBy:
    """A branch probability chosen by an owner state category (D71)."""
    for k, v in probs.items():
        if not isinstance(k, str) or not 0.0 <= float(v) <= 1.0:
            raise PackError(f"std.p_by: {k!r}: probabilities are floats in [0, 1] by category")
    return PBy(col, tuple((k, float(v)) for k, v in probs.items()), float(otherwise))


# ---------------------------------------------------------------- actions
@dataclass(frozen=True)
class Emit:
    event: str
    values: tuple[tuple[str, Any], ...]


@dataclass(frozen=True)
class Spawn:
    machine: str
    n: Any                        # int | Dist | Col | Field
    stagger: Dist | None
    fields: tuple[tuple[str, Any], ...]


@dataclass(frozen=True)
class SendParent:
    msg: str


@dataclass(frozen=True)
class LabelAct:
    role: str
    outcome: str


@dataclass(frozen=True)
class CreateOwner:
    table: str
    values: tuple[tuple[str, Any], ...]


@dataclass(frozen=True)
class SetField:
    name: str
    value: Any
    add: bool


@dataclass(frozen=True)
class Part:
    act: Any                      # ActionSpec | Emit | Spawn | SendParent | LabelAct | ...
    fallback: Any = None          # one act, run when `act` rejects (D66)


@dataclass(frozen=True)
class Chain:
    parts: tuple[Part, ...]

    def then(self, other) -> Chain:
        return Chain(self.parts + as_chain(other).parts)

    def otherwise(self, other) -> Chain:
        if len(self.parts) != 1 or self.parts[0].fallback is not None:
            raise PackError(".otherwise() applies to one action; write a.then(b.otherwise(c))")
        alt = as_chain(other)
        if len(alt.parts) != 1:
            raise PackError(".otherwise() takes one action, not a chain")
        return Chain((Part(self.parts[0].act, alt.parts[0].act),))


def as_chain(x) -> Chain:
    if isinstance(x, Chain):
        return x
    if isinstance(x, ActionRef):
        return Chain((Part(x.spec),))
    raise PackError(f"expected an @action or a std action, got {type(x).__name__}")


def _one(act) -> Chain:
    return Chain((Part(act),))


def emit(event: str, **values) -> Chain:
    return _one(Emit(event, tuple(values.items())))


def spawn(machine: str, n=1, stagger: Dist | None = None, fields: dict | None = None) -> Chain:
    return _one(Spawn(machine, n, stagger, tuple((fields or {}).items())))


def send_parent(msg: str) -> Chain:
    return _one(SendParent(msg))


def label(role: str, outcome: str) -> Chain:
    return _one(LabelAct(role, outcome))


def create_owner(table: str, **values) -> Chain:
    return _one(CreateOwner(table, tuple(values.items())))


def set_field(name: str, value) -> Chain:
    return _one(SetField(name, value, False))


def add_field(name: str, value=1) -> Chain:
    return _one(SetField(name, value, True))


# ---------------------------------------------------------------- requests (D83)
@dataclass(frozen=True)
class Request:
    local: str                    # a boundary sent by the machine's partition (or acts_for)
    ok: str
    shard: Any
    store: tuple[tuple[str, str], ...]     # response payload field -> instance field
    payload: tuple[tuple[str, Any], ...]


def request(local: str, *, ok: str = "granted", shard=0, store: dict | None = None,
            **payload) -> Request:
    return Request(local, ok, shard, tuple((store or {}).items()), tuple(payload.items()))


__all__ = ["ActionSpec", "After", "Actor", "Chain", "Col", "Cond", "CreateOwner", "Emit",
           "Field", "LabelAct", "Near", "NewId", "Now", "PBy", "ParentActor", "Part", "PickRef",
           "Repeats", "Request", "SendParent", "SetField", "Spawn", "actor", "add_field",
           "after", "as_chain", "col", "cond", "create_owner", "emit", "field", "label",
           "near", "new_id", "now", "p_by", "parent", "pick_ref", "request", "send_parent",
           "set_field", "spawn"]
```

`std/__init__.py` re-exports: `from neorisk_simkit.machine.helpers import (actor, add_field, after, col, cond, create_owner, emit, field, label, near, new_id, now, p_by, parent, pick_ref, request, send_parent, set_field, spawn)` (and lists them in `__all__`).

- [ ] **Step 3: `machine/spec.py`**

```python
"""Machine declarations (spec §04): the builder `p.machine(...)` returns, the normalized
`MachineDef`, and the closed-semantics validation `build_machines` runs at plan build."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from neorisk_simkit.engine.abi import _LOCAL_RE, ActionSpec
from neorisk_simkit.machine import helpers as h
from neorisk_simkit.spec.dist import Dist
from neorisk_simkit.spec.pack import PackError, Trigger

MAX_MACHINES, MAX_STATES, MAX_INSTANCES = 16, 32, 64
LATE = ("ignore", "count")


@dataclass(frozen=True)
class Outcome:
    target: str
    p: Any                        # float | h.PBy | None (the unpicked mass, D71)
    delay: Dist | None
    chain: h.Chain | None


@dataclass(frozen=True)
class StateDef:
    name: str
    code: int                     # 1 + declaration index
    branch: tuple[Outcome, ...] = ()
    timers: tuple[tuple[str, Dist], ...] = ()
    repeat: tuple[Dist, float, h.Chain | None] | None = None
    max_repeats: Any = None       # int | Dist | h.Field | None
    until: h.Cond | None = None
    then: str | None = None
    join: tuple[str, str] | None = None             # (target, message)
    late: str = "ignore"
    request: tuple[str, h.Request] | None = None    # (target, request)
    on_reject: str | None = None
    on_timeout: str | None = None
    timeout_us: int | None = None
    spawn: tuple[tuple[str, float, Dist | None, Any], ...] = ()  # (child, p, delay, n)


@dataclass(frozen=True)
class MachineDef:
    name: str
    partition: str
    index: int                    # tag field m (position among the partition's machines)
    start: Trigger | None
    initial: str
    states: tuple[StateDef, ...]
    finals: tuple[str, ...]
    config: Any
    max_instances: int
    fields: Mapping[str, str]
    reads: Mapping[str, str]
    refs: Mapping[str, Any]
    max_spawn_depth: int | None
    member_table: str | None = None                 # cohort machines (Task 10)
    root_member: bool = False
    member_values: tuple[tuple[str, Any], ...] = ()
    labels: str | None = None
    label_delay: Dist | None = None
    overlay: str | None = None

    def state(self, name: str) -> StateDef:
        return next(s for s in self.states if s.name == name)

    def code(self, name: str) -> int:
        """1 + state index for states; finals follow the states."""
        for s in self.states:
            if s.name == name:
                return s.code
        return len(self.states) + 1 + self.finals.index(name)


def _dur(v) -> Dist:
    from neorisk_simkit.spec import dist
    from neorisk_simkit.spec.project import parse_duration
    if isinstance(v, Dist):
        return v
    return dist.constant(s=parse_duration(v) / 1_000_000)


class Machine:
    """Builder returned by `p.machine(...)` (and `o.machine(...)`, Task 10)."""

    def __init__(self, name: str, partition: str, *, initial: str, start, config,
                 max_instances: int, fields, reads, refs, max_spawn_depth, **extra):
        self.name, self.partition, self.initial = name, partition, initial
        self.start, self.config = start, config
        self.max_instances, self.max_spawn_depth = int(max_instances), max_spawn_depth
        self.fields = dict(fields or {})
        self.reads, self.refs = dict(reads or {}), dict(refs or {})
        self.extra = extra
        self._states: list[dict] = []
        self._finals: list[str] = []

    def state(self, name: str, *, branch=None, timer=None, repeat=None, max_repeats=None,
              until=None, then=None, join=None, late="ignore", request=None, on_reject=None,
              on_timeout=None, timeout=None, spawn=None) -> Machine:
        self._states.append(dict(
            name=name, branch=branch or {}, timer=timer or {}, repeat=repeat,
            max_repeats=max_repeats, until=until, then=then, join=join or {}, late=late,
            request=request or {}, on_reject=on_reject, on_timeout=on_timeout,
            timeout=timeout, spawn=spawn or {}))
        return self

    def final(self, *names: str) -> Machine:
        self._finals.extend(names)
        return self

    def build(self, index: int) -> MachineDef:
        from neorisk_simkit.spec.project import parse_duration
        states = []
        for k, d in enumerate(self._states):
            outcomes = tuple(
                Outcome(t, p, delay, h.as_chain(c) if c is not None else None)
                for t, (p, delay, c) in d["branch"].items())
            rep = d["repeat"]
            if rep is not None:
                rep = (_dur(rep[0]), float(rep[1]),
                       h.as_chain(rep[2]) if rep[2] is not None else None)
            join = next(iter(d["join"].items())) if d["join"] else None
            req = next(iter(d["request"].items())) if d["request"] else None
            states.append(StateDef(
                name=d["name"], code=k + 1, branch=outcomes,
                timers=tuple((t, _dur(v)) for t, v in d["timer"].items()),
                repeat=rep, max_repeats=d["max_repeats"], until=d["until"], then=d["then"],
                join=join, late=d["late"], request=req, on_reject=d["on_reject"],
                on_timeout=d["on_timeout"],
                timeout_us=parse_duration(d["timeout"]) if isinstance(d["timeout"], str)
                else d["timeout"],
                spawn=tuple((c, float(v[0]), v[1], v[2] if len(v) > 2 else 1)
                            for c, v in d["spawn"].items())))
        return MachineDef(
            name=self.name, partition=self.partition, index=index, start=self.start,
            initial=self.initial, states=tuple(states), finals=tuple(self._finals),
            config=self.config, max_instances=self.max_instances,
            fields=MappingProxyType(self.fields), reads=MappingProxyType(self.reads),
            refs=MappingProxyType(self.refs), max_spawn_depth=self.max_spawn_depth,
            **self.extra)
```

`build_machines(pack)` builds every registered builder (index = order among machines of its partition) and returns `(machines, errors)`. The errors, each exact (tests pin them):

```python
def _chain_acts(chain):
    for part in chain.parts:
        yield part.act
        if part.fallback is not None:
            yield part.fallback


def _state_chains(st):
    for o in st.branch:
        if o.chain is not None:
            yield o.chain
    if st.repeat is not None and st.repeat[2] is not None:
        yield st.repeat[2]


def build_machines(pack) -> tuple[tuple[MachineDef, ...], list[str]]:
    errs: list[str] = []
    by_part: dict[str, int] = {}
    out = []
    for b in pack.machines.values():
        i = by_part.get(b.partition, 0)
        by_part[b.partition] = i + 1
        out.append(b.build(i))
    for part, n in by_part.items():
        if n > MAX_MACHINES:
            errs.append(f"partition {part}: more than {MAX_MACHINES} machines")
    names = {m.name: m for m in out}
    for m in out:
        errs += _machine_errors(m, names, pack)
    return tuple(out), errs


def _machine_errors(m: MachineDef, names, pack) -> list[str]:
    e: list[str] = []
    w = f"machine {m.name}"
    declared = [s.name for s in m.states]
    known = set(declared) | set(m.finals)
    if not 1 <= m.max_instances <= MAX_INSTANCES:
        e.append(f"{w}: max_instances must be in [1, {MAX_INSTANCES}]")
    if len(m.states) > MAX_STATES:
        e.append(f"{w}: more than {MAX_STATES} states")
    if m.max_spawn_depth is not None and m.max_spawn_depth < 1:
        e.append(f"{w}: max_spawn_depth must be >= 1")
    if m.initial not in declared:
        e.append(f"{w}: initial state {m.initial!r} is not declared")
    for s in sorted({x for x in declared + list(m.finals)
                     if (declared + list(m.finals)).count(x) > 1}):
        e.append(f"{w}: state {s!r} declared twice")
    for f, decl in m.fields.items():
        if _LOCAL_RE.match(decl) is None or "[" in decl:
            e.append(f"{w}: field {f!r}: {decl!r} is not a scalar local type")
    for st in m.states:
        sw = f"{w}: state {st.name!r}"
        targets = [o.target for o in st.branch] + [t for t, _ in st.timers]
        targets += [x for x in (st.then, st.on_reject, st.on_timeout) if x is not None]
        targets += [st.join[0]] if st.join else []
        targets += [st.request[0]] if st.request else []
        for t in targets:
            if t not in known:
                e.append(f"{sw}: unknown target {t!r}")
        main = [bool(st.branch), st.repeat is not None, st.join is not None,
                st.request is not None]
        if sum(main) > 1:
            e.append(f"{sw}: branch, repeat, join and request exclude each other")
        if not any(main) and not st.timers and not st.spawn and st.until is None:
            e.append(f"{sw} has no operation (declare it final)")
        if st.branch:
            nones = [o for o in st.branch if o.p is None]
            if len(nones) > 1:
                e.append(f"{sw}: at most one branch outcome may have p=None")
            fixed = [o.p for o in st.branch if isinstance(o.p, (int, float))]
            total = math.fsum(float(p) for p in fixed)
            pby = [o for o in st.branch if isinstance(o.p, h.PBy)]
            if not nones and not pby and abs(total - 1.0) > 1e-9:
                e.append(f"{sw}: branch probabilities sum to {total:.6g}; give the unpicked "
                         "mass an explicit otherwise outcome (p=None)")
            if total > 1.0 + 1e-9:
                e.append(f"{sw}: branch probabilities sum to {total:.6g} > 1")
        if (st.until is not None or st.max_repeats is not None) and st.then is None:
            e.append(f"{sw}: until/max_repeats need then=")
        if st.join is not None and not st.timers:
            e.append(f"{sw}: join needs a timer= (its timeout)")
        if st.late not in LATE:
            e.append(f"{sw}: late must be 'ignore' or 'count'")
        if st.request is not None:
            if st.timeout_us is None or st.on_reject is None:
                e.append(f"{sw}: request needs timeout= and on_reject=")
            if st.timers:
                e.append(f"{sw}: request states cannot declare timer= (the owner is "
                         "suspended; use timeout=)")
        for child, *_ in st.spawn:
            if child not in names or names[child].partition != m.partition:
                e.append(f"{sw}: spawns unknown machine {child!r} (machines spawn on their own "
                         "partition)")
        for chain in _state_chains(st):
            for act in _chain_acts(chain):
                e += _act_errors(w, sw, act, m, names, pack)
    return e
```
`_act_errors` checks: `ActionSpec` — `act.state` is the machine's partition or the partition it acts for (`pack.partitions[m.partition].get("acts_for")`), else `f"{w}: action {act.name} is for partition {act.state!r}, not {m.partition!r}"`; every `act.fields` entry is declared with the same type: `f"{w}: action {act.name} needs instance field {f!r} ({t})"`. `h.Emit` — the event exists (`f"{sw}: emits unknown event {ev!r}"`) and belongs to the partition or its `acts_for` (`f"{sw}: event {ev!r} belongs to partition {owner!r}"`). `h.Spawn` — like the state `spawn`. `h.SendParent` — some machine whose states spawn `m.name` (op or `std.spawn` act) has a join on that message: else `f"{w}: send_parent({msg!r}) but no machine that spawns {m.name!r} joins on {msg!r}"`. `h.SetField` — the field is declared. Field references in values (`h.Field`) must be declared: `f"{w}: unknown field {name!r}"`.

`spec/pack.py`:
```python
def machine(self, name: str, *, owner: str, initial: str, start: Trigger | None = None,
            config=None, max_instances: int = 1, fields=None, reads=None, refs=None,
            max_spawn_depth: int | None = None, **extra):
    from neorisk_simkit.machine.spec import Machine
    if name in self.machines or name in self.processes:
        raise PackError(f"duplicate machine {name!r}")
    part = self.partitions.get(owner)
    if part is None or part["kind"] != "owner":
        raise PackError(f"machine {name}: machines live on owner partitions (got {owner!r})")
    for t in (reads or {}).values():
        self._table(t)
    m = Machine(name, owner, initial=initial, start=start, config=config,
                max_instances=max_instances, fields=fields, reads=reads, refs=refs,
                max_spawn_depth=max_spawn_depth, **extra)
    self.machines[name] = m
    return m
```
(`self.machines: dict[str, Machine] = {}` in `__init__`; `expose`, `expose_param`, `feature` stubs: `expose`/`expose_param` arrive in Task 10, `feature` stays a stub with the message "feature arrives in M4 (D-deferred)".)

`spec/plan.py` `build_plan`: after `define`, `machines, errs = build_machines(p)`; `if errs: raise PackError("\n".join(errs))`; `Plan.machines=machines` (new field, default `()`).

- [ ] **Step 4: Write the `mx_basic` fixture** (used by Tasks 5, 6, 9)

`fixtures/mx_basic/datagen.toml`: copy `fixtures/spawn/datagen.toml`; `name = "mx_basic"`, `span = "6h"`, `step = "6h"`, `step_max = "1d"`.

`fixtures/mx_basic/specs/pack.py`:
```python
"""Machine basics: a branch with an explicit otherwise racing a timer (earliest wins), a
then-chain whose second part falls back on reject, and @action calls."""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, dist, std
from neorisk_simkit.spec.types import cat, i32, ref

from . import kernels as k

PACK = "mx_basic"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Config:
    parcels: int = 6
    sent_p: float = 0.5
    max_weight: int = 5


def define(p: Pack, cfg: Config) -> None:
    parcel = p.table("parcel", key="parcel_id", mutable=True, cols={"weight": i32()})
    p.owner("parcel", table=parcel, max_live=cfg.parcels)
    p.population(parcel, n=cfg.parcels, initial=1.0, attrs={"weight": dist.uniform_int(1, 9)})
    pid = {"parcel_id": ref("parcel")}
    p.event("sent", owner="parcel", cols={**pid, "carrier": cat("ups", "dhl")})
    for name in ("lost", "expired", "audited", "audit_failed"):
        p.event(name, owner="parcel", cols=pid)
    p.event("delivered", owner="parcel", cols={**pid, "weight": i32()})
    m = p.machine("ship", owner="parcel", start=p.on_created("parcel"), initial="placed",
                  config=cfg)
    m.state("placed", branch={
        "sent": (cfg.sent_p, dist.constant(s=3600),
                 std.emit("sent", parcel_id=std.actor(),
                          carrier=dist.categorical({"ups": 0.5, "dhl": 0.5}))),
        "lost": (None, dist.constant(s=7200), std.emit("lost", parcel_id=std.actor())),
    }, timer={"expiring": "90m"})
    m.state("expiring", branch={
        "expired": (1.0, None, std.emit("expired", parcel_id=std.actor()))})
    m.state("sent", branch={"done": (1.0, dist.constant(s=600), k.deliver.then(
        k.audit.otherwise(std.emit("audit_failed", parcel_id=std.actor()))))})
    m.final("done", "lost", "expired")
```

`fixtures/mx_basic/specs/kernels.py`:
```python
from neorisk_simkit.engine import COMMIT, Res, action, reject


@action(state="parcel", max=Res(records={"delivered": 1}))
def deliver(ctx, s, m, cmd, out):
    out.emit_delivered(ctx.t, parcel_id=m.id, weight=s.weight)
    return COMMIT


@action(state="parcel", max=Res(records={"audited": 1}))
def audit(ctx, s, m, cmd, out):
    if s.weight > ctx.cfg.max_weight:
        return reject(1)
    out.emit_audited(ctx.t, parcel_id=m.id)
    return COMMIT
```

- [ ] **Step 5: Write the failing tests**

`libs/simkit/tests/test_machine_spec.py`:
```python
"""Machine declarations and their closed-semantics validation (§04, D63-D71)."""

import pytest
from conftest import make_run

from neorisk_simkit.engine import COMMIT, Res, action
from neorisk_simkit.machine import helpers as h
from neorisk_simkit.machine.spec import build_machines
from neorisk_simkit.spec import Pack, PackError, dist, std
from neorisk_simkit.spec.types import i32, ref


def _pack() -> Pack:
    p = Pack("t", 1)
    t = p.table("acct", key="acct_id", mutable=True, cols={"n": i32()})
    p.owner("acct", table=t, max_live=2)
    p.population(t, n=2, initial=1.0)
    p.event("ping", owner="acct", cols={"acct_id": ref("acct")})
    return p


def _errors(p: Pack) -> list[str]:
    return build_machines(p)[1]


def test_mx_basic_builds_into_the_plan():
    plan = make_run("mx_basic").plan
    (m,) = plan.machines
    assert (m.name, m.partition, m.index, m.initial) == ("ship", "parcel", 0, "placed")
    assert [s.name for s in m.states] == ["placed", "expiring", "sent"]
    assert m.finals == ("done", "lost", "expired")
    assert m.code("placed") == 1 and m.code("done") == 4
    placed = m.state("placed")
    assert [o.target for o in placed.branch] == ["sent", "lost"]
    assert placed.branch[1].p is None and placed.timers[0][0] == "expiring"
    (chain,) = [o.chain for o in m.state("sent").branch]
    assert len(chain.parts) == 2 and chain.parts[1].fallback is not None


def test_machines_live_on_owners():
    p = _pack()
    p.shard("desk", key="desk", n=1, items=None, state={})
    with pytest.raises(PackError, match="machines live on owner partitions"):
        p.machine("m", owner="desk", initial="a")


@pytest.mark.parametrize("build, message", [
    (lambda m: m.state("a", branch={"b": (0.5, None, None)}).final("b"),
     "state 'a': branch probabilities sum to 0.5; give the unpicked mass an explicit "
     "otherwise outcome (p=None)"),
    (lambda m: m.state("a", branch={"b": (None, None, None), "c": (None, None, None)})
     .final("b", "c"), "state 'a': at most one branch outcome may have p=None"),
    (lambda m: m.state("a", branch={"zz": (1.0, None, None)}), "state 'a': unknown target 'zz'"),
    (lambda m: m.state("a").final("b"), "state 'a' has no operation (declare it final)"),
    (lambda m: m.state("a", join={"b": "done"}).final("b"),
     "state 'a': join needs a timer= (its timeout)"),
    (lambda m: m.state("a", request={"b": std.request("x")}).final("b"),
     "state 'a': request needs timeout= and on_reject="),
    (lambda m: m.state("a", repeat=(dist.exp(mean_s=1), 1.0, None), max_repeats=2),
     "state 'a': until/max_repeats need then="),
    (lambda m: m.state("a", join={"b": "x"}, timer={"b": "1h"}, late="sometimes").final("b"),
     "state 'a': late must be 'ignore' or 'count'"),
    (lambda m: m.state("a", branch={"b": (1.0, None, std.emit("nope"))}).final("b"),
     "state 'a': emits unknown event 'nope'"),
    (lambda m: m.state("a", branch={"b": (1.0, None, None)}, spawn={"ghost": (1.0, None, 1)})
     .final("b"), "state 'a': spawns unknown machine 'ghost'"),
])
def test_closed_semantics_errors(build, message):
    p = _pack()
    build(p.machine("m", owner="acct", initial="a", start=p.on_created("acct")))
    assert any(message in e for e in _errors(p)), _errors(p)


def test_initial_must_be_declared():
    p = _pack()
    p.machine("m", owner="acct", initial="nowhere").state(
        "a", branch={"b": (1.0, None, None)}).final("b")
    assert "machine m: initial state 'nowhere' is not declared" in _errors(p)


def test_actions_compose_and_check_their_fields():
    @action(state="acct", max=Res(records={"ping": 1}), fields={"amount": "i64"})
    def pinger(ctx, s, m, cmd, out):
        out.emit_ping(ctx.t, acct_id=m.id)
        return COMMIT

    chain = pinger.then(std.emit("ping", acct_id=std.actor()))
    assert isinstance(chain, h.Chain) and len(chain.parts) == 2
    with pytest.raises(PackError, match="applies to one action"):
        chain.otherwise(std.emit("ping", acct_id=std.actor()))
    p = _pack()
    p.machine("m", owner="acct", initial="a").state(
        "a", branch={"b": (1.0, None, pinger)}).final("b")
    assert "machine m: action pinger needs instance field 'amount' (i64)" in _errors(p)


def test_action_signature_is_checked():
    with pytest.raises(TypeError, match=r"must take \(ctx, s, m, cmd, out\)"):
        @action(state="acct")
        def bad(ctx, s, cmd, out):
            return COMMIT
```

- [ ] **Step 6: Run the tests to verify they fail, implement, run them again**

Run: `uv run --all-packages pytest libs/simkit/tests/test_machine_spec.py -q`
Expected first: FAIL (`ModuleNotFoundError: neorisk_simkit.machine`). After Steps 1–4: PASS. Full suite in the background — PASS (no generated module changes: `KernelSpec.source` is unused until Task 6); S1 reduced hash unchanged.

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff check $(ls -d libs apps examples/ecommerce_s1 examples/ecommerce_s2 benchmarks 2>/dev/null)
git add libs/simkit/src/neorisk_simkit/machine libs/simkit/src/neorisk_simkit/engine/abi.py \
  libs/simkit/src/neorisk_simkit/engine/__init__.py libs/simkit/src/neorisk_simkit/spec/pack.py \
  libs/simkit/src/neorisk_simkit/spec/plan.py libs/simkit/src/neorisk_simkit/std/__init__.py \
  libs/simkit/src/neorisk_simkit/io/manifest.py libs/simkit/tests/fixtures/mx_basic \
  libs/simkit/tests/test_machine_spec.py
git commit -m "feat(machine): declarations, closed vocabulary and validation (spec §04)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 6: Machine compiler I — the generated process, branch, timer, final, then, actions

**Files:**
- Create: `libs/simkit/src/neorisk_simkit/machine/layout.py`, `machine/copy.py`, `machine/compile.py`
- Modify: `spec/plan.py` (`ProcessDef.machine_partition`, `Plan.machine_sources`; compile machines into `mx_<p>` processes), `engine/codegen.py` (`lowered_kernels` uses `KernelSpec.source`; `_mstat`), `engine/lower.py` (`out.mstat`), `engine/slabs.py` (`OUT_TAIL` += `"mstat"`), `engine/world.py` (`take_machine_stats`), `engine/run.py` (`stats["machines"]`), `io/dataset.py` (`run_stats.json["machines"]`), `io/manifest.py` (`_REVISION_DIRS` += `"machine"`), `apps/datagen/src/datagen/cli.py` + `run_cmds.py` (`validate --dump-machines DIR`)
- Test: `libs/simkit/tests/test_machine_basic.py`

**Interfaces:**
- Consumes: Task 5 (`MachineDef`, `StateDef`, `Outcome`, `helpers.*`, `ActionSpec`), lowering (`lower_module`, views `ctx s loc cmd out`), `KernelSpec.source`.
- Produces:
  - `machine.layout`: `MX_STALE = 0`, `MX_FIRE = 1`, `FIRST_RESPONSE_KIND = 2`, `OP_BRANCH … OP_REQUEST = 1 … 7`, `GEN_MASK = (1 << 20) - 1`, `IMPLICIT` (D63 fields, plus `("mr", "i16")`: the max repeat count drawn at entry), `tag(m, i, g, op, x) -> int`, `width(md) -> int`, `local_fields(machines) -> dict[str, str]`, `stat_layout(machines) -> dict[str, int]` (machine → base index; counters `late, rejects, spawned, entries[code − 1]`) and `n_stats(machines) -> int`.
  - `machine.copy.copy_action(spec: ActionSpec, md: MachineDef, copy: int) -> tuple[str, str]` (copy function name, source of the copy and its helper copies).
  - `machine.compile.compile_machines(plan) -> list[MxProcess]`; `MxProcess(name, partition, kernel, config, start, requests, on_response, reads, refs, commands, max_spawn_depth, text)`; `Need` (reservation vector with `add`, `union`, `src()`, `res()`).
  - `ProcessDef.machine_partition: str | None = None`; `Plan.machine_sources: Mapping[str, str]` (partition → generated text, also what `--dump-machines` writes).
  - Generated names (prefix `mx_`): root kernel `mx_<partition>(ctx, s, loc, cmd, out)`, `mx_start_<partition>`, `mx_fire_<m>`, `mx_enter_<m>_<code>`, `mx_end_<m>`, `mx_tr_<m>_<t>`, `mx_part_<m>_<t>_<q>`, `mx_alloc_<m>`, `mx_init_<m>`, `mx_tag`; config `ctx.cfg.c_<m>` (the machine's own config) and `ctx.cfg.x_<m>` (generated op parameters `s<code>_b<j>_p`, `s<code>_b<j>_d`, `s<code>_t<j>_d`, …).
  - `out.mstat(i, v)` → generated `_mstat`; `World.take_machine_stats() -> dict[str, dict[str, Any]]`; `run_stats.json["machines"][<m>] = {"late": n, "rejects": n, "spawned": n, "entries": {state: n}}`.

- [ ] **Step 1: Write the failing tests**

`libs/simkit/tests/test_machine_basic.py`:
```python
"""Machines compile into one generated process per partition (D62); branch, timer, final and
then-chains with a fallback behave as §04 decides."""

import json
import subprocess
import sys

import polars as pl
from conftest import FIXTURES, make_run

from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events

H = 3_600_000_000


def _run(tmp_path, overrides=()):
    return run_to_dataset(FIXTURES / "mx_basic", "sample", list(overrides),
                          out_dir=tmp_path / "run", threads=2)


def _us(col: pl.Series) -> list[int]:
    return col.cast(pl.Int64).to_list()


def test_machines_become_one_generated_process():
    plan = make_run("mx_basic").plan
    mx = plan.process("mx_parcel")
    assert mx.machine_partition == "parcel" and mx.action_id == len(plan.processes) - 1
    assert "def mx_parcel(ctx, s, loc, cmd, out):" in plan.machine_sources["parcel"]
    assert mx.kernel.source.endswith(plan.machine_sources["parcel"])


def test_earliest_wins_and_stale_timers_drop(tmp_path):
    res = _run(tmp_path)
    ev = read_events(res.out_dir)
    t0 = _us(ev["sent"]["event_time"])[0] - H if ev["sent"].height else None
    n_sent, n_exp = ev["sent"].height, ev["expired"].height
    assert n_sent + n_exp == 6 and ev["lost"].height == 0       # the 90m timer beats "lost"
    if t0 is not None:
        assert set(_us(ev["expired"]["event_time"])) <= {t0 + 90 * 60_000_000}
    stats = json.loads((res.out_dir / "run_stats.json").read_text())
    assert stats["rejects"]["mx_parcel"] == 6                   # one stale timer per parcel
    entries = stats["machines"]["ship"]["entries"]
    assert entries["placed"] == 6 and entries["sent"] == n_sent
    assert entries["expiring"] == n_exp and entries["lost"] == 0


def test_then_parts_are_separate_commands_and_the_fallback_runs(tmp_path):
    res = _run(tmp_path, ["sent_p=1.0"])
    ev = read_events(res.out_dir)
    users = pl.read_parquet(res.out_dir / "entities" / "parcel").select(
        pl.col("id").alias("parcel_id"), "weight")
    d = ev["delivered"].join(users, on="parcel_id")
    assert d.height == 6
    heavy = set(d.filter(pl.col("weight") > 5)["parcel_id"])
    assert set(ev["audit_failed"]["parcel_id"]) == heavy
    assert set(ev["audited"]["parcel_id"]) == set(d["parcel_id"]) - heavy
    both = pl.concat([ev["audited"], ev["audit_failed"]]).select(
        "parcel_id", pl.col("lamport").alias("l2"), pl.col("event_time").alias("t2"))
    j = ev["delivered"].join(both, on="parcel_id")
    assert (j["lamport"] < j["l2"]).all() and (j["event_time"] == j["t2"]).all()
    stats = json.loads((res.out_dir / "run_stats.json").read_text())
    assert stats["machines"]["ship"]["rejects"] == len(heavy)


def test_op_parameters_are_config_not_source():
    a = make_run("mx_basic").plan.machine_sources["parcel"]
    b = make_run("mx_basic", ["sent_p=1.0"]).plan.machine_sources["parcel"]
    assert a == b


def test_dump_machines_writes_the_compiled_text(tmp_path):
    out = tmp_path / "dump"
    r = subprocess.run([sys.executable, "-m", "datagen.cli", "validate",
                        str(FIXTURES / "mx_basic"), "--dump-machines", str(out)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    plan = make_run("mx_basic").plan
    assert (out / "parcel.py").read_text() == plan.machine_sources["parcel"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --all-packages pytest libs/simkit/tests/test_machine_basic.py -q`
Expected: FAIL — `KeyError: unknown process 'mx_parcel'`.

- [ ] **Step 3: `machine/layout.py`**

```python
"""Instance memory, command tags, draw sites and statistics of machine processes (D63-D65)."""

from __future__ import annotations

from neorisk_simkit.spec.pack import PackError

MX_STALE = 0                      # reject(MX_STALE): a stale command (§04 "drop when popped")
MX_FIRE = 1                       # command kind of every machine timer
FIRST_RESPONSE_KIND = 2           # request-op responses take kinds 2, 3, ... (Task 8)
OP_BRANCH, OP_TIMER, OP_REPEAT, OP_CHAIN, OP_SPAWN, OP_NOW, OP_REQUEST = 1, 2, 3, 4, 5, 6, 7
GEN_MASK = (1 << 20) - 1
IMPLICIT = (("st", "i16"), ("gen", "i64"), ("ep", "i64"), ("rep", "i16"), ("mr", "i16"),
            ("t0", "i64"), ("dep", "i8"), ("par", "i8"), ("pm", "i8"), ("pep", "i64"),
            ("ord", "i8"), ("kids", "i8"), ("jb", "i64"), ("jn", "i8"), ("jl", "i8"),
            ("actor", "ref"), ("pactor", "ref"))
STATE_SITES, MAX_STATES_PER_SITEBLOCK = 16, 32
ACTION_SITE_BASE, ACTION_SITE_SPAN, MAX_COPIES = 9000, 128, 163


def tag(m: int, i: int, g: int, op: int, x: int) -> int:
    return (m << 41) | (i << 35) | ((g & GEN_MASK) << 15) | (op << 12) | x


def width(md) -> int:
    return max(2, md.max_instances)


def local_fields(machines) -> dict[str, str]:
    out: dict[str, str] = {}
    for md in machines:
        w = width(md)
        for f, t in (*IMPLICIT, *md.fields.items()):
            out[f"{md.name}__{f}"] = f"{t}[{w}]"
    return out


def state_site(md, state_index: int, j: int) -> int:
    if j >= STATE_SITES:
        raise PackError(f"machine {md.name}: state {md.states[state_index].name!r} needs more "
                        f"than {STATE_SITES} draw sites")
    return 1 + STATE_SITES * (MAX_STATES_PER_SITEBLOCK * md.index + state_index) + j


def action_site(copy: int, n: int) -> int:
    if copy >= MAX_COPIES:
        raise PackError(f"more than {MAX_COPIES} action copies in one machine process")
    if not 0 <= n < ACTION_SITE_SPAN:
        raise PackError(f"action draw site {n} must be in [0, {ACTION_SITE_SPAN})")
    return ACTION_SITE_BASE + ACTION_SITE_SPAN * copy + n


def stat_layout(machines) -> dict[str, int]:
    base, n = {}, 0
    for md in machines:
        base[md.name] = n
        n += 3 + len(md.states) + len(md.finals)
    return base


def n_stats(machines) -> int:
    return sum(3 + len(md.states) + len(md.finals) for md in machines)
```

- [ ] **Step 4: `machine/copy.py`**

```python
"""Per-machine copies of @action functions and their helpers (D65): renamed, `m.id` /
`m.parent_id` / `m.<field>` -> instance fields, `ctx.cfg` -> `ctx.cfg.c_<machine>`, and every
`site=N` literal moved into the copy's site block."""

from __future__ import annotations

import ast
import copy as _copy
import functools
from pathlib import Path

from neorisk_simkit.engine.abi import ActionSpec
from neorisk_simkit.machine import layout as L
from neorisk_simkit.spec.pack import PackError


@functools.cache
def _module(path: str) -> dict[str, ast.FunctionDef]:
    tree = ast.parse(Path(path).read_text(), path)
    return {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}


def _sub(base: str, attr: str, idx: str, ctx) -> ast.Subscript:
    return ast.Subscript(ast.Attribute(ast.Name(base, ast.Load()), attr, ast.Load()),
                         ast.Name(idx, ast.Load()), ctx)


class _Rewrite(ast.NodeTransformer):
    def __init__(self, md, copy: int, prefix: str, funcs, where: str):
        self.md, self.copy, self.prefix, self.funcs, self.where = md, copy, prefix, funcs, where
        self.called: list[str] = []

    def visit_Attribute(self, node: ast.Attribute):
        v = node.value
        if isinstance(v, ast.Name) and v.id == "m":
            mm = self.md.name
            if node.attr == "id":
                if self.md.member_table is None:
                    return ast.copy_location(ast.Attribute(ast.Name("ctx", ast.Load()), "self_id",
                                                           node.ctx), node)
                return ast.copy_location(_sub("loc", f"{mm}__actor", "mi", node.ctx), node)
            if node.attr == "parent_id":
                return ast.copy_location(_sub("loc", f"{mm}__pactor", "mi", node.ctx), node)
            if node.attr not in self.md.fields:
                raise PackError(f"{self.where}: m.{node.attr} is not a field of machine {mm}")
            return ast.copy_location(_sub("loc", f"{mm}__{node.attr}", "mi", node.ctx), node)
        if (node.attr == "cfg" and isinstance(v, ast.Name) and v.id == "ctx"):
            return ast.copy_location(ast.Attribute(
                ast.Attribute(ast.Name("ctx", ast.Load()), "cfg", ast.Load()),
                f"c_{self.md.name}", node.ctx), node)
        return self.generic_visit(node)

    def visit_Name(self, node: ast.Name):
        if node.id == "m":
            raise PackError(f"{self.where}: m may only be used as m.<field>")
        return node

    def visit_Call(self, node: ast.Call):
        f = node.func
        if isinstance(f, ast.Name) and f.id in self.funcs:
            self.called.append(f.id)
            node.func = ast.Name(f"{self.prefix}{f.id}", ast.Load())
        if (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Attribute)
                and f.value.attr == "rng"):
            for kw in node.keywords:
                if kw.arg == "site" and isinstance(kw.value, ast.Constant):
                    kw.value = ast.Constant(L.action_site(self.copy, int(kw.value.value)))
        return self.generic_visit(node)


def copy_action(spec: ActionSpec, md, copy: int) -> tuple[str, str]:
    """(name of the copy, source of the copy and of every helper it calls, transitively)."""
    funcs = _module(spec.module_file)
    prefix = f"mx_{md.name}_c{copy}_"
    done: dict[str, str] = {}
    todo = [spec.name]
    while todo:
        name = todo.pop()
        if name in done:
            continue
        fn = _copy.deepcopy(funcs[name])
        fn.decorator_list = []
        if name == spec.name:
            fn.args.args = [ast.arg(a) for a in ("ctx", "s", "loc", "cmd", "out", "mi")]
        elif any(a.arg == "m" for a in fn.args.args):
            raise PackError(f"helper {name} of action {spec.name}: pass m.<field> values, not m")
        rw = _Rewrite(md, copy, prefix, funcs, f"action {spec.name}")
        fn = rw.visit(fn)
        fn.name = f"{prefix}{name}"
        done[name] = ast.unparse(ast.fix_missing_locations(fn))
        todo += rw.called
    return f"{prefix}{spec.name}", "\n\n\n".join(done.values())
```

- [ ] **Step 5: `machine/compile.py` (this task: start, branch, timer, final, chains, `std.emit`, `@action`; Tasks 7 and 8 add the remaining ops in the marked places)**

```python
"""Generate the machine process of one owner partition (D62): authoring-dialect kernel text
appended to the actions' kernels file and compiled by the ordinary lowering and codegen.
`Plan.machine_sources[partition]` holds the text; `datagen validate --dump-machines DIR`
writes it (the inspectable dispatch module of §04)."""

from __future__ import annotations

import dataclasses
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

from neorisk_simkit.engine.abi import START, ActionSpec, KernelSpec, Local, Res
from neorisk_simkit.machine import helpers as h
from neorisk_simkit.machine import layout as L
from neorisk_simkit.machine.copy import copy_action
from neorisk_simkit.spec.dist import CATEGORICAL, UNIFORM_INT, Dist
from neorisk_simkit.spec.pack import PackError

_HEADER = ("# ---- generated by neorisk_simkit.machine for partition {part!r}; do not edit\n"
           "from neorisk_simkit import std\n"
           "from neorisk_simkit.engine import COMMIT, PRIO_CONTINUE, PRIO_TIMER, RETRY, START, "
           "reject\n\n"
           f"MX_STALE = {L.MX_STALE}\nMX_FIRE = {L.MX_FIRE}\n")
VIEWS = ("ctx", "s", "loc", "cmd", "out")


@dataclass
class Need:
    records: Counter = field(default_factory=Counter)
    creates: Counter = field(default_factory=Counter)
    timers: int = 0
    requests: int = 0

    @staticmethod
    def of(res: Res) -> Need:
        return Need(Counter(dict(res.records)), Counter(dict(res.creates)), res.timers,
                    res.requests)

    def add(self, o: Need) -> Need:
        return Need(self.records + o.records, self.creates + o.creates,
                    self.timers + o.timers, self.requests + o.requests)

    def union(self, o: Need) -> Need:
        return Need(self.records | o.records, self.creates | o.creates,
                    max(self.timers, o.timers), max(self.requests, o.requests))

    def src(self) -> str:
        out = []
        if self.records:
            out.append("records={" + ", ".join(f"{k!r}: {v}" for k, v in
                                               sorted(self.records.items())) + "}")
        if self.creates:
            out.append("creates={" + ", ".join(f"{k!r}: {v}" for k, v in
                                               sorted(self.creates.items())) + "}")
        if self.timers:
            out.append(f"timers={self.timers}")
        if self.requests:
            out.append(f"requests={self.requests}")
        return ", ".join(out)

    def res(self) -> Res:
        return Res(records=dict(self.records), creates=dict(self.creates),
                   timers=self.timers, requests=self.requests)


@dataclass(frozen=True)
class MxProcess:
    name: str
    partition: str
    kernel: KernelSpec
    config: Any
    start: Any
    requests: Mapping[str, str]
    on_response: Mapping[tuple[str, str], int]
    reads: Mapping[str, str]
    refs: Mapping[str, Any]
    commands: tuple[int, ...]
    max_spawn_depth: int | None
    text: str


@dataclass(frozen=True)
class _Pad:
    pad: int = 0


class _Gen:
    def __init__(self, part: str, machines: list, plan):
        self.part, self.ms, self.plan = part, machines, plan
        self.by_name = {m.name: m for m in machines}
        self.funcs: list[str] = []
        self.need = Need()
        self.params: dict[str, dict[str, Any]] = {m.name: {} for m in machines}
        self.copies: dict[tuple[str, str], str] = {}
        self.copy_src: list[str] = []
        self.files: set[str] = set()
        self.stat = L.stat_layout(machines)
        self.next_site: dict[tuple[str, int], int] = {}
        self.trans: dict[str, list[tuple]] = {m.name: [] for m in machines}
        self.responses: dict[tuple[str, str], int] = {}

    # ---------------------------------------------------------------- small pieces
    def fn(self, name: str, params: str, body: list[str]) -> None:
        self.funcs.append(f"def {name}({params}):\n" + "\n".join(f"    {ln}" for ln in body))

    def site(self, m, st) -> int:
        k = (m.name, st.code)
        j = self.next_site.get(k, 0)
        self.next_site[k] = j + 1
        return L.state_site(m, st.code - 1, j)

    def param(self, m, name: str, value) -> str:
        self.params[m.name][name] = value
        return f"c.{name}"

    def reserve(self, need: Need) -> list[str]:
        self.need = self.need.union(need)
        src = need.src()
        return [f"if not out.reserve({src}):", "    return RETRY"] if src else []

    def actor(self, m) -> str:
        return "ctx.self_id" if m.member_table is None else f"loc.{m.name}__actor[i]"

    def enter_call(self, m, target: str) -> str:
        code = m.code(target)
        if target in m.finals:
            return f"mx_end_{m.name}(ctx, s, loc, cmd, out, i, {code})"
        return f"mx_enter_{m.name}_{code}(ctx, s, loc, cmd, out, i)"

    def tid(self, m, st, kind: str, key, target: str, chain) -> int:
        lst = self.trans[m.name]
        lst.append((st, kind, key, target, chain))
        if len(lst) > 255:
            raise PackError(f"machine {m.name}: more than 255 transitions")
        return len(lst) - 1

    def delay(self, m, st, name: str, d: Dist | None) -> str:
        if d is None:
            return "ctx.t"
        return f"ctx.t + ctx.rng.dist_us(site={self.site(m, st)}, d={self.param(m, name, d)})"

    # ---------------------------------------------------------------- values (std vocabulary)
    def value(self, m, st, v, ltype=None) -> tuple[str, Need]:
        if isinstance(v, h.Actor):
            return self.actor(m), Need()
        if isinstance(v, h.ParentActor):
            return f"loc.{m.name}__pactor[i]", Need()
        if isinstance(v, h.Col):
            return f"s.{v.name}", Need()
        if isinstance(v, h.Field):
            return f"loc.{m.name}__{v.name}[i]", Need()
        if isinstance(v, h.NewId):
            return f"out.new_id({v.ns!r})", Need(creates=Counter({v.ns: 1}))
        if isinstance(v, h.Now):
            return "ctx.t", Need()
        if isinstance(v, h.After):
            return self.delay(m, st, f"v{len(self.params[m.name])}", v.delay), Need()
        if isinstance(v, h.Near):
            hi = int(v.value * v.above)
            return (f"{v.value} + ctx.rng.uniform_int(site={self.site(m, st)}, lo=0, hi={hi})",
                    Need())
        if isinstance(v, Dist) and v.kind == CATEGORICAL:
            labels = list(v.labels)
            if ltype is not None and ltype.kind == "cat":
                codes = tuple(ltype.values.index(x) for x in labels)
            else:
                codes = tuple(int(x) for x in labels)
            return (f"{codes!r}[ctx.rng.categorical(site={self.site(m, st)}, "
                    f"p={tuple(v.weights)!r})]", Need())
        if isinstance(v, Dist) and v.kind == UNIFORM_INT:
            lo, hi = int(v.params[0]), int(v.params[1])
            return f"ctx.rng.uniform_int(site={self.site(m, st)}, lo={lo}, hi={hi})", Need()
        if isinstance(v, bool):
            return ("1" if v else "0"), Need()
        if isinstance(v, (int, float, str)):
            return repr(v), Need()
        raise PackError(f"machine {m.name}: unsupported value {v!r}")

    # ---------------------------------------------------------------- parts
    def part(self, m, st, act, fname: str) -> tuple[str, Need]:
        """Define the function of one part; return the call expression and its need."""
        if isinstance(act, ActionSpec):
            key = (m.name, act.name)
            if key not in self.copies:
                name, src = copy_action(act, m, len(self.copies))
                self.copies[key] = name
                self.copy_src.append(src)
                self.files.add(act.module_file)
            return f"{self.copies[key]}(ctx, s, loc, cmd, out, i)", Need.of(act.max)
        if isinstance(act, h.Emit):
            ev = self.plan.event(act.event)
            cols = {c.name: c.ltype for c in ev.cols}
            args, need = [], Need(records=Counter({act.event: 1}))
            for name, v in act.values:
                src, n = self.value(m, st, v, cols.get(name))
                args.append(f"{name}={src}")
                need = need.add(n)
            self.fn(fname, "ctx, s, loc, cmd, out, i",
                    [f"out.emit_{act.event}(ctx.t, {', '.join(args)})", "return COMMIT"])
            return f"{fname}(ctx, s, loc, cmd, out, i)", need
        return self.part_more(m, st, act, fname)            # Tasks 7, 8

    def part_more(self, m, st, act, fname):
        raise PackError(f"machine {m.name}: {type(act).__name__} arrives in a later task")

    # ---------------------------------------------------------------- entry, end, transitions
    def entry_need(self, m, target: str) -> Need:
        if target in m.finals:
            return Need()
        st = m.state(target)
        n = Need(timers=(1 if st.branch else 0) + len(st.timers))
        return n.add(self.entry_need_more(m, st))          # Tasks 7, 8

    def entry_need_more(self, m, st) -> Need:
        return Need()

    def enter(self, m, st) -> None:
        p, k = m.name, st.code
        body = [f"loc.{p}__st[i] = {k}", f"loc.{p}__gen[i] += 1", f"loc.{p}__rep[i] = 0",
                f"loc.{p}__t0[i] = ctx.t", f"out.mstat({self.stat[p] + 3 + k - 1}, 1)",
                f"g = loc.{p}__gen[i]", f"c = ctx.cfg.x_{p}"]
        for j, (target, d) in enumerate(st.timers):
            t = self.tid(m, st, "timer", j, target, None)
            body.append(f"out.timer({self.delay(m, st, f's{k}_t{j}_d', d)}, MX_FIRE, "
                        f"prio=PRIO_TIMER, tag=mx_tag({m.index}, i, g, {L.OP_TIMER}, {t}))")
        body += self.enter_more(m, st)                      # Tasks 7, 8
        if st.branch:
            body += self.branch_entry(m, st)
        self.fn(f"mx_enter_{p}_{k}", "ctx, s, loc, cmd, out, i", body)

    def enter_more(self, m, st) -> list[str]:
        return []

    def branch_entry(self, m, st) -> list[str]:
        k = st.code
        lines = [f"u = ctx.rng.uniform(site={self.site(m, st)})", "acc = 0.0"]
        rest = last = None
        for j, o in enumerate(st.branch):
            t = self.tid(m, st, "branch", j, o.target, o.chain)
            push = (f"out.timer({self.delay(m, st, f's{k}_b{j}_d', o.delay)}, MX_FIRE, "
                    f"prio=PRIO_TIMER, tag=mx_tag({m.index}, i, g, {L.OP_BRANCH}, {t}))")
            last = push
            if o.p is None:
                rest = push
                continue
            if isinstance(o.p, h.PBy):
                lines.append(f"pb = {self.param(m, f's{k}_b{j}_po', o.p.otherwise)}")
                for q, (value, prob) in enumerate(o.p.probs):
                    lines += [f"if s.{o.p.col} == {value!r}:",
                              f"    pb = {self.param(m, f's{k}_b{j}_p{q}', prob)}"]
                lines.append("acc += pb")
            else:
                lines.append(f"acc += {self.param(m, f's{k}_b{j}_p', float(o.p))}")
            lines += ["if u < acc:", f"    {push}", "    return"]
        lines.append(rest if rest is not None else last)   # the unpicked mass / rounding
        return lines

    def end(self, m) -> None:
        p = m.name
        self.fn(f"mx_end_{p}", "ctx, s, loc, cmd, out, i, code", [
            "if code > 0:",
            f"    out.mstat({self.stat[p] + 3} + code - 1, 1)",
            f"loc.{p}__st[i] = 0",
            f"loc.{p}__gen[i] += 1"] + self.end_more(m))

    def end_more(self, m) -> list[str]:
        return []

    def transition(self, m, t: int) -> None:
        st, _kind, _key, target, chain = self.trans[m.name][t]
        p = m.name
        parts = chain.parts if chain is not None else ()
        body = []
        if not parts:
            body += self.reserve(self.entry_need(m, target))
            body += [self.enter_call(m, target), "return COMMIT"]
            self.fn(f"mx_tr_{p}_{t}", "ctx, s, loc, cmd, out, i, part", body)
            return
        fail = (self.enter_call(m, st.on_reject) if st.on_reject is not None
                else f"mx_end_{p}(ctx, s, loc, cmd, out, i, 0)")
        fail_need = self.entry_need(m, st.on_reject) if st.on_reject else Need()
        for q, prt in enumerate(parts):
            call, need = self.part(m, st, prt.act, f"mx_part_{p}_{t}_{q}")
            fb_call = None
            if prt.fallback is not None:
                fb_call, fb_need = self.part(m, st, prt.fallback, f"mx_part_{p}_{t}_{q}f")
                need = need.union(fb_need)
            last = q == len(parts) - 1
            ok_need = self.entry_need(m, target) if last else Need(timers=1)
            need = need.add(ok_need.union(fail_need))
            body += [f"if part == {q}:", *("    " + x for x in self.reserve(need)),
                     f"    rc = {call}",
                     "    if rc != COMMIT:",
                     f"        out.mstat({self.stat[p] + 1}, 1)"]
            if fb_call is not None:
                body.append(f"        rc = {fb_call}")
            body += ["    if rc != COMMIT:", f"        {fail}", "        return COMMIT"]
            body += self.after_part(m, st, t, q)                # Task 7 (until)
            if last:
                body.append(f"    {self.enter_call(m, target)}")
            else:
                body.append(f"    out.timer(ctx.t, MX_FIRE, prio=PRIO_CONTINUE, tag=mx_tag("
                            f"{m.index}, i, loc.{p}__gen[i], {L.OP_CHAIN}, {(t << 4) | (q + 1)}))")
            body.append("    return COMMIT")
        body.append("return reject(MX_STALE)")
        self.fn(f"mx_tr_{p}_{t}", "ctx, s, loc, cmd, out, i, part", body)

    def after_part(self, m, st, t, q) -> list[str]:
        return []

    def fire(self, m) -> None:
        p = m.name
        body = [f"if loc.{p}__st[i] == 0 or (loc.{p}__gen[i] & {L.GEN_MASK}) != g:",
                "    return reject(MX_STALE)",
                f"if op == {L.OP_CHAIN}:"]
        for t in range(len(self.trans[p])):
            body += [f"    if (x >> 4) == {t}:",
                     f"        return mx_tr_{p}_{t}(ctx, s, loc, cmd, out, i, x & 15)"]
        body += ["    return reject(MX_STALE)"]
        for t, (_st, kind, _key, _target, _chain) in enumerate(self.trans[p]):
            if kind in ("branch", "timer"):
                body += [f"if x == {t}:", f"    return mx_tr_{p}_{t}(ctx, s, loc, cmd, out, i, 0)"]
        body += self.fire_more(m)                            # Tasks 7, 8
        body.append("return reject(MX_STALE)")
        self.fn(f"mx_fire_{p}", "ctx, s, loc, cmd, out, i, g, op, x", body)

    def fire_more(self, m) -> list[str]:
        return []

    def init(self, m) -> None:
        p = m.name
        body = [f"loc.{p}__ep[i] += 1", f"loc.{p}__dep[i] = dep", f"loc.{p}__par[i] = par",
                f"loc.{p}__pm[i] = pm", f"loc.{p}__pep[i] = pep", f"loc.{p}__ord[i] = ord_",
                f"loc.{p}__kids[i] = 0", f"loc.{p}__jb[i] = 0", f"loc.{p}__jn[i] = 0",
                f"loc.{p}__jl[i] = 0", f"loc.{p}__actor[i] = actor",
                f"loc.{p}__pactor[i] = pactor"]
        body += [f"loc.{p}__{f}[i] = std.NULL" if t == "ref" else f"loc.{p}__{f}[i] = 0"
                 for f, t in m.fields.items()]
        self.fn(f"mx_init_{p}", "loc, i, dep, par, pm, pep, ord_, actor, pactor", body)
        self.fn(f"mx_alloc_{p}", "loc", [
            f"for j in range({m.max_instances}):",
            f"    if loc.{p}__st[j] == 0:",
            "        return j",
            "return -1"])

    def start(self) -> list[str] | None:
        started = [m for m in self.ms if m.start is not None]
        if not started:
            return None
        need = Need()
        body = []
        for m in started:
            need = need.add(self.entry_need(m, m.initial)).add(self.root_need(m))
        body += self.reserve(need)
        for m in started:
            body += [f"i = {0}",
                     *self.root_actor(m),
                     f"mx_init_{m.name}(loc, i, 0, -1, -1, 0, 0, actor, std.NULL)",
                     self.enter_call(m, m.initial)]
        body.append("return COMMIT")
        self.fn(f"mx_start_{self.part}", "ctx, s, loc, cmd, out", body)
        return body

    def root_need(self, m) -> Need:
        return Need()                                        # Task 10: member row creation

    def root_actor(self, m) -> list[str]:
        return ["actor = ctx.self_id"]                       # Task 10: out.add_member_<t>

    def root(self) -> None:
        p = self.part
        body = []
        if any(m.start is not None for m in self.ms):
            body += ["if cmd.kind == START:", f"    return mx_start_{p}(ctx, s, loc, cmd, out)"]
        body += [f"if cmd.kind == MX_FIRE:",
                 "    m_ = (cmd.tag >> 41) & 15",
                 "    i_ = (cmd.tag >> 35) & 63",
                 f"    g_ = (cmd.tag >> 15) & {L.GEN_MASK}",
                 "    op_ = (cmd.tag >> 12) & 7",
                 "    x_ = cmd.tag & 4095"]
        for m in self.ms:
            body += [f"    if m_ == {m.index}:",
                     f"        return mx_fire_{m.name}(ctx, s, loc, cmd, out, i_, g_, op_, x_)"]
        body += ["    return reject(MX_STALE)"]
        body += self.root_more()                              # Task 8: responses
        body.append("return reject(MX_STALE)")
        self.fn(f"mx_{p}", "ctx, s, loc, cmd, out", body)

    def root_more(self) -> list[str]:
        return []

    # ---------------------------------------------------------------- everything
    def generate(self) -> MxProcess:
        self.fn("mx_tag", "m, i, g, op, x",
                [f"return (m << 41) | (i << 35) | ((g & {L.GEN_MASK}) << 15) | (op << 12) | x"])
        for m in self.ms:
            self.init(m)
            self.end(m)
            for st in m.states:
                self.enter(m, st)
        for m in self.ms:                     # transitions after every entry assigned its ids
            for t in range(len(self.trans[m.name])):
                self.transition(m, t)
            self.fire(m)
        self.start()
        self.root()
        text = _HEADER.format(part=self.part) + "\n\n" + "\n\n\n".join(self.funcs + self.copy_src) + "\n"
        return self.process(text)

    def config(self):
        fields, values = [], {}
        for m in self.ms:
            own = m.config if m.config is not None else _Pad()
            x = self.params[m.name] or {"pad": 0}
            X = dataclasses.make_dataclass(f"MxParams_{m.name}", [(k, type(v)) for k, v in x.items()],
                                           frozen=True)
            fields += [(f"c_{m.name}", type(own)), (f"x_{m.name}", X)]
            values[f"c_{m.name}"], values[f"x_{m.name}"] = own, X(**x)
        C = dataclasses.make_dataclass(f"MxConfig_{self.part}", fields, frozen=True)
        return C(**values)

    def process(self, text: str) -> MxProcess:
        if len(self.files) > 1:
            raise PackError(f"partition {self.part}: machine actions come from several files "
                            f"{sorted(self.files)}; keep one kernels file per partition")
        name = f"mx_{self.part}"
        commands = tuple(sorted({L.MX_FIRE, *self.responses.values(),
                                 *([START] if any(m.start for m in self.ms) else [])}))
        kernel = KernelSpec(name=name, func=None,
                            module_file=next(iter(self.files), f"<machines:{self.part}>"),
                            state=self.part, local=Local(**L.local_fields(self.ms)),
                            commands=commands, max=self.need.res(), substep=None,
                            params=VIEWS, source=None)
        reads, refs = {}, {}
        for m in self.ms:
            for d, src in ((reads, m.reads), (refs, m.refs)):
                for k, v in src.items():
                    if d.setdefault(k, v) != v:
                        raise PackError(f"partition {self.part}: machines disagree on {k!r}")
        start = next((m.start for m in self.ms if m.start is not None), None)
        depths = [m.max_spawn_depth for m in self.ms if m.max_spawn_depth is not None]
        return MxProcess(name, self.part, kernel, self.config(), start,
                         MappingProxyType(self.requests()), MappingProxyType(dict(self.responses)),
                         MappingProxyType(reads), MappingProxyType(refs), commands,
                         min(depths) if depths else None, text)

    def requests(self) -> dict[str, str]:
        return {}                                            # Task 8


def compile_machines(plan) -> list[MxProcess]:
    """One `MxProcess` per owner partition that has machines, in partition order; the kernel
    source of each is its actions file followed by every machine text using that file."""
    out = []
    for part in plan.partitions:
        ms = [m for m in plan.machines if m.partition == part.name]
        if ms:
            out.append(_Gen(part.name, sorted(ms, key=lambda m: m.index), plan).generate())
    by_file: dict[str, list[MxProcess]] = {}
    for x in out:
        by_file.setdefault(x.kernel.module_file, []).append(x)
    final = []
    for x in out:
        group = by_file[x.kernel.module_file]
        head = ("" if x.kernel.module_file.startswith("<")
                else Path(x.kernel.module_file).read_text() + "\n\n")
        source = head + "\n\n".join(g.text for g in group)
        final.append(dataclasses.replace(
            x, kernel=dataclasses.replace(x.kernel, source=source)))
    return final
```
Notes for the implementer: (1) `Dist` op parameters are flattened by `flatten_config` to `(code, p1, p2, p3)`, which `ctx.rng.dist_us(site=, d=)` reads; the dataclass field type for a `Dist` value is `Dist`. (2) A machine on a partition with `retire_when_idle` retires when all instances ended and no timer is queued — nothing to add. (3) `test_machines_become_one_generated_process` asserts `kernel.source.endswith(text)`: with one partition the combined text ends with that partition's text. (4) If a lowering error points into generated code, fix the generator, never the lowering contract.

- [ ] **Step 6: Wire the process into the plan, codegen and run stats**

1. `spec/plan.py`: `ProcessDef.machine_partition: str | None = None`; `Plan.machine_sources: Mapping[str, str] = MappingProxyType({})`. At the end of `build_plan`, build `plan0` as today, then:
   ```python
   from neorisk_simkit.machine.compile import compile_machines
   mx = compile_machines(plan0)
   base = len(plan0.processes)
   extra = tuple(ProcessDef(
       name=x.name, partition=x.partition, action_id=base + j, kernel=x.kernel,
       config=x.config, start=x.start, requests=x.requests, messages=_frozen({}),
       on_request=_frozen({}), on_response=x.on_response, on_message=_frozen({}),
       reads=x.reads, refs=x.refs, commands=x.commands, every_us=None, jitter=None,
       max_spawn_depth=x.max_spawn_depth, machine_partition=x.partition)
       for j, x in enumerate(mx))
   return dataclasses.replace(plan0, processes=plan0.processes + extra,
                              machine_sources=_frozen({x.partition: x.text for x in mx}))
   ```
2. `engine/codegen.py` `lowered_kernels`: collect `sources[module_file] = kernel.source` (all non-None sources of one file must be equal, else `LoweringError`) and lower `sources.get(f) or Path(f).read_text()`; `generate()` always emits `_mstat`:
   ```python
   self.fn("_mstat", "out, ctx, i, v", ["ms = out[OUT_MSTAT]", "ms[i] += v"])
   ```
3. `engine/lower.py` `_out_call`: `if m == "mstat": i, v = self._positional(node, what, 2, 2); return _call("_mstat", out, ctx, self.visit(i), self.visit(v))`.
4. `engine/slabs.py`: `OUT_TAIL` += `"mstat"`; `SlabSet` keeps `self.mstat = np.zeros(max(1, n_stats(plan.machines)), np.int64)` and puts it in the tuple. `engine/world.py`:
   ```python
   def take_machine_stats(self) -> dict[str, dict[str, Any]]:
       from neorisk_simkit.machine.layout import stat_layout
       tot = sum(s.mstat for s in self.slabs)
       for s in self.slabs:
           s.mstat[:] = 0
       out = {}
       for m, b in stat_layout(self.plan.machines).items():
           md = next(x for x in self.plan.machines if x.name == m)
           names = [st.name for st in md.states] + list(md.finals)
           out[m] = {"late": int(tot[b]), "rejects": int(tot[b + 1]),
                     "spawned": int(tot[b + 2]),
                     "entries": {n: int(tot[b + 3 + j]) for j, n in enumerate(names)}}
       return out
   ```
   `engine/run.py`: `stats["machines"]` merges each step's `take_machine_stats()` (sum counters); `io/dataset.py` `_run_stats` copies `sim.stats["machines"]` into `run_stats.json["machines"]` (an empty dict for packs without machines).
5. `io/manifest.py`: `_REVISION_DIRS` += `"machine"`.
6. `apps/datagen/src/datagen/cli.py`: `val.add_argument("--dump-machines", default=None, metavar="DIR", help="write each partition's generated machine module")`; `run_cmds.cmd_validate`: after `resolve_run`, when set, `Path(dir).mkdir(parents=True, exist_ok=True)` and write `<dir>/<partition>.py` = `plan.machine_sources[partition]`; print one line per file.

- [ ] **Step 7: Run the tests**

Run: `uv run --all-packages pytest libs/simkit/tests/test_machine_basic.py libs/simkit/tests/test_machine_spec.py -q`
Expected: PASS. Then the full suite in the background — PASS; S1 reduced hash unchanged (the `out` tuple grows by one array; outputs do not change).

- [ ] **Step 8: Lint and commit**

```bash
uv run ruff check $(ls -d libs apps examples/ecommerce_s1 examples/ecommerce_s2 benchmarks 2>/dev/null)
git add libs/simkit/src/neorisk_simkit/machine libs/simkit/src/neorisk_simkit/spec/plan.py \
  libs/simkit/src/neorisk_simkit/engine/codegen.py libs/simkit/src/neorisk_simkit/engine/lower.py \
  libs/simkit/src/neorisk_simkit/engine/slabs.py libs/simkit/src/neorisk_simkit/engine/world.py \
  libs/simkit/src/neorisk_simkit/engine/run.py libs/simkit/src/neorisk_simkit/io/dataset.py \
  libs/simkit/src/neorisk_simkit/io/manifest.py apps/datagen/src/datagen/cli.py \
  apps/datagen/src/datagen/run_cmds.py libs/simkit/tests/test_machine_basic.py
git commit -m "feat(machine): generated machine process; branch, timer, final, then (D62-D68)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 7: Machine compiler II — repeat, until…then, spawn, join, send_parent

**Files:**
- Create: `libs/simkit/tests/fixtures/mx_family/{datagen.toml,specs/pack.py,specs/kernels.py}`
- Modify: `libs/simkit/src/neorisk_simkit/machine/compile.py` (the hooks `entry_need_more`, `enter_more`, `fire_more`, `part_more`, `end_more`, plus leaving-a-join bookkeeping), `machine/spec.py` (validate: `until` needs `repeat=`; a repeat runs one action; `max_repeats` is an int, `std.field`, `std.col` or a `geometric`/`uniform_int`/`categorical` Dist)
- Test: `libs/simkit/tests/test_machine_family.py`

**Interfaces:**
- Consumes: Task 6 `_Gen` (hooks, `site`, `param`, `reserve`, `tid`, `enter_call`, `part`), `layout.OP_REPEAT/OP_SPAWN/OP_NOW`, `EngineError` (importable in kernel modules from `neorisk_simkit.engine`).
- Produces: generated `mx_rep_<m>_<t>` (one repetition), `mx_sp_<m>_<t>` (a delayed spawn op), spawn bodies inside parts, `OP_NOW` handling in `mx_fire_<m>` (x = target code); the instance depth limit `x_<m>.maxdep` (= `max_spawn_depth` or 3, §06 default); run-failure messages `"<machine>: no free <child> instance (max_instances)"` and `"<machine>: spawn depth exceeds max_spawn_depth"`; stats `spawned` and `late` (D82). Task 10 adds member rows to spawn bodies through `_Gen.member_actor(m)`.

- [ ] **Step 1: Write the fixture**

`fixtures/mx_family/datagen.toml`: copy `fixtures/spawn/datagen.toml`; `name = "mx_family"`, `span = "6h"`, `step = "6h"`, `step_max = "1d"`.

`fixtures/mx_family/specs/pack.py`:
```python
"""Spawn, join, repeat and until on one owner (D69, D70): a mother spawns `brood` chicks,
joins on their first call, then feeds once per minute until every chick is fed."""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, dist, std
from neorisk_simkit.spec.types import i32, ref

from . import kernels as k

PACK = "mx_family"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Config:
    nests: int = 4
    brood_lo: int = 0
    brood_hi: int = 2
    wait: str = "20m"                 # the join's timeout
    max_rounds: int = 10
    recurse_p: float = 0.0            # 1.0: every chick spawns a chick (depth limit test)
    chick_slots: int = 8


def define(p: Pack, cfg: Config) -> None:
    nest = p.table("nest", key="nest_id", mutable=True, cols={"brood": i32()})
    p.owner("nest", table=nest, max_live=cfg.nests)
    p.population(nest, n=cfg.nests, initial=1.0,
                 attrs={"brood": dist.uniform_int(cfg.brood_lo, cfg.brood_hi)})
    nid = {"nest_id": ref("nest")}
    p.event("fed", owner="nest", cols={**nid, "meal": i32()})
    p.event("called", owner="nest", cols={**nid, "chick": i32()})
    mother = p.machine("mother", owner="nest", start=p.on_created("nest"), initial="laying",
                       config=cfg, fields={"meals": "i32"})
    mother.state("laying", branch={
        "waiting": (1.0, dist.constant(s=60), std.spawn("chick", n=std.col("brood")))})
    mother.state("waiting", join={"feeding": "hungry"}, timer={"timeout": cfg.wait},
                 late="count")
    mother.state("feeding", repeat=(dist.constant(s=60), 1.0, k.feed),
                 max_repeats=cfg.max_rounds,
                 until=std.cond.ge(std.field("meals"), std.col("brood")), then="full")
    mother.final("full", "timeout")
    chick = p.machine("chick", owner="nest", initial="growing", max_instances=cfg.chick_slots,
                      max_spawn_depth=3)
    chick.state("growing", branch={"calling": (
        1.0, dist.constant(s=300),
        std.emit("called", nest_id=std.actor(), chick=1).then(std.send_parent("hungry")))},
        spawn={"chick": (cfg.recurse_p, dist.constant(s=1), 1)})
    chick.state("calling", branch={"done": (1.0, dist.constant(s=600),
                                            std.send_parent("hungry"))})
    chick.final("done")
```

`fixtures/mx_family/specs/kernels.py`:
```python
from neorisk_simkit.engine import COMMIT, Res, action


@action(state="nest", max=Res(records={"fed": 1}), fields={"meals": "i32"})
def feed(ctx, s, m, cmd, out):
    m.meals += 1
    out.emit_fed(ctx.t, nest_id=m.id, meal=m.meals)
    return COMMIT
```

- [ ] **Step 2: Write the failing tests**

`libs/simkit/tests/test_machine_family.py`:
```python
"""Spawn (same owner), join with timeout / duplicates / late policy, repeat with until (§04,
D69, D70; Review Focus 1-2)."""

import json

import polars as pl
import pytest
from conftest import FIXTURES

from neorisk_simkit.engine import EngineError
from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events

S = 1_000_000


def _run(tmp_path, overrides=()):
    res = run_to_dataset(FIXTURES / "mx_family", "sample", list(overrides),
                         out_dir=tmp_path / "run", threads=2)
    ev = read_events(res.out_dir)
    nests = pl.read_parquet(res.out_dir / "entities" / "nest").select(
        pl.col("id").alias("nest_id"), "brood")
    stats = json.loads((res.out_dir / "run_stats.json").read_text())["machines"]
    return ev, nests, stats


def _fed(ev, nests):
    per = ev["fed"].group_by("nest_id").len()
    return nests.join(per, on="nest_id", how="left").with_columns(pl.col("len").fill_null(0))


def test_join_waits_for_every_child_then_feeds_each(tmp_path):
    ev, nests, st = _run(tmp_path)
    j = _fed(ev, nests)
    assert (j["len"] == j["brood"]).all()
    assert st["mother"]["entries"]["full"] == 4 and st["mother"]["entries"]["timeout"] == 0
    assert st["mother"]["spawned"] == nests["brood"].sum()


def test_zero_children_fire_immediately(tmp_path):
    ev, nests, st = _run(tmp_path, ["brood_lo=0", "brood_hi=0"])
    assert ev["fed"].height == 0 and ev["called"].height == 0
    assert st["mother"]["entries"]["full"] == 4


def test_duplicates_are_suppressed_and_late_messages_counted(tmp_path):
    ev, nests, st = _run(tmp_path, ["brood_lo=2", "brood_hi=2"])
    assert ev["fed"].height == 8                         # second calls never double-count
    assert st["mother"]["late"] == 8                     # each chick's second call is late


def test_join_timeout_leaves_and_counts_every_call_late(tmp_path):
    ev, nests, st = _run(tmp_path, ["brood_lo=1", "brood_hi=1", "wait=4m"])
    assert ev["fed"].height == 0
    assert st["mother"]["entries"]["timeout"] == 4 and st["mother"]["late"] == 8


def test_join_and_timeout_at_one_instant_transition_once(tmp_path):
    _ev, _n, st = _run(tmp_path, ["brood_lo=1", "brood_hi=1", "wait=5m"])   # both at +360 s
    e = st["mother"]["entries"]
    assert e["full"] + e["timeout"] == 4 and e["feeding"] == e["full"]


def test_repeat_stops_at_its_maximum(tmp_path):
    ev, nests, st = _run(tmp_path, ["brood_lo=2", "brood_hi=2", "max_rounds=1"])
    assert ev["fed"].height == 4 and st["mother"]["entries"]["full"] == 4


def test_spawn_beyond_instances_fails_naming_the_machine(tmp_path):
    with pytest.raises(EngineError, match="mother: no free chick instance"):
        _run(tmp_path, ["brood_lo=2", "brood_hi=2", "chick_slots=1"])


def test_spawn_depth_is_bounded_per_machine(tmp_path):
    with pytest.raises(EngineError, match="chick: spawn depth exceeds max_spawn_depth"):
        _run(tmp_path, ["brood_lo=1", "brood_hi=1", "recurse_p=1.0"])
```
(`chick_slots` sets `max_instances`, a structural value: that test compiles its own module once.)

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run --all-packages pytest libs/simkit/tests/test_machine_family.py -q`
Expected: FAIL — `PackError: machine mother: Spawn arrives in a later task` (from `part_more`).

- [ ] **Step 4: Implement the hooks in `machine/compile.py`**

Validation first (`machine/spec.py`, exact texts): `f"{sw}: until needs repeat="` when `until` is set without `repeat`; `f"{sw}: repeat runs one action, not a chain"` when the repeat chain has more than one part; `f"{sw}: max_repeats must be an int, std.field, std.col or a geometric/uniform_int/categorical Dist"`.

Generated code shapes (indices from `layout`; `c = ctx.cfg.x_<m>` is in scope in entry functions; write the same alias at the top of every generated function that reads params):

1. **Leaving a join** — at the top of `mx_enter_<m>_<k>` and `mx_end_<m>`, for each join state `J` of machine `m`: `if loc.<m>__st[i] == <J.code>: loc.<m>__jl[i] = <2 if J.late == "count" else 1>`.
2. **Entering a join state** (`enter_more`): `loc.<m>__jl[i] = 0`, then
   `if loc.<m>__jn[i] >= loc.<m>__kids[i]: out.timer(ctx.t, MX_FIRE, prio=PRIO_CONTINUE, tag=mx_tag(<m.index>, i, g, OP_NOW, <code of the join target>))` — need `+1 timer`.
3. **Repeat state** (`enter_more`): `loc.<m>__mr[i] = <max_repeats src>` (int → `c.s<k>_mr`; `Field`/`Col` → their sources; Dist → `ctx.rng.geometric(site=…, mean=…)`, `ctx.rng.uniform_int(site=…, lo=…, hi=…)` or the categorical-label form of Task 6; none → `32767`), then the first repetition timer `out.timer(ctx.t + dist_us(c.s<k>_rd), MX_FIRE, prio=PRIO_TIMER, tag=mx_tag(m, i, g, OP_REPEAT, t))` with `t = tid(m, st, "repeat", 0, st.then or st.name, chain)`, then, when `until` is set or `max_repeats` is given, `if <cond> or loc.<m>__mr[i] <= 0: out.timer(ctx.t, MX_FIRE, prio=PRIO_CONTINUE, tag=mx_tag(m, i, g, OP_NOW, <code of then>))` (a maximum of 0 ends the state on entry) — need `+2 timers`. A `geometric(mean, max=)` Dist draws `min(ctx.rng.geometric(site=…, mean=…), max)`. `std.field(name)` may also read the implicit fields `rep`, `kids` and `jn` (validate allows those three names, read-only).
4. **One repetition** `mx_rep_<m>_<t>(ctx, s, loc, cmd, out, i)` (called from `mx_fire_<m>` on `op == OP_REPEAT and x == t`):
   ```python
   c = ctx.cfg.x_<m>
   run = ctx.rng.bernoulli(site=<site>, p=c.s<k>_rp)
   nxt = ctx.rng.dist_us(site=<site>, d=c.s<k>_rd)
   if not out.reserve(<action need (∪ fallback) + then-entry need + 1 timer>):
       return RETRY
   loc.<m>__rep[i] += 1
   if run:
       rc = <action call>
       if rc != COMMIT:
           out.mstat(<rejects>, 1)
           [rc = <fallback call>]
   if loc.<m>__rep[i] >= loc.<m>__mr[i] or <until cond, if any>:
       <enter then>
       return COMMIT
   out.timer(ctx.t + nxt, MX_FIRE, prio=PRIO_TIMER, tag=mx_tag(<m.index>, i, loc.<m>__gen[i], OP_REPEAT, <t>))
   return COMMIT
   ```
   Condition sources: `Repeats()` → `loc.<m>__rep[i]`, `Field(f)` → `loc.<m>__<f>[i]`, `Col(c)` → `s.<c>`, ints literal; ops `>=`, `<=`, `==`.
5. **`OP_NOW`** in `fire_more`: for every code `x` some `OP_NOW` targets, `if op == OP_NOW and x == <code>:` reserve that target's entry need, enter it, `return COMMIT`.
6. **Spawn body** (shared by the state op and `std.spawn` parts), for parent machine `m`, child `cm`, count source `n_src`, optional `stagger`:
   ```python
   n = <n_src>
   dep = loc.<m>__dep[i] + 1
   if n > 0 and dep > c.maxdep:
       raise EngineError("<m>: spawn depth exceeds max_spawn_depth")
   for k_ in range(n):
       j = mx_alloc_<cm>(loc)
       if j < 0:
           raise EngineError("<m>: no free <cm> instance (max_instances)")
       actor = <member actor of cm (Task 10) or ctx.self_id>
       mx_init_<cm>(loc, j, dep, i, <m.index>, loc.<m>__ep[i], loc.<m>__kids[i], actor, <actor of m>)
       loc.<m>__kids[i] += 1
       <field initializers of the spawn, each: loc.<cm>__<f>[j] = <value in the parent's context>>
       out.mstat(<spawned of m>, 1)
       <no stagger>: mx_enter_<cm>_<initial code>(ctx, s, loc, cmd, out, j)
       <stagger>:    loc.<cm>__st[j] = -1
                     out.timer(ctx.t + k_ * ctx.rng.dist_us(site=<site>, d=c.<stagger param>), MX_FIRE,
                               prio=PRIO_TIMER, tag=mx_tag(<cm.index>, j, loc.<cm>__gen[j], OP_NOW, <initial code>))
   ```
   (`st = -1` marks a reserved instance: `mx_alloc` skips it; `mx_fire`'s stale check only refuses `st == 0`; ordinals above 63 are refused because `kids` would overflow the bitset: `if loc.<m>__kids[i] >= 63: raise EngineError("<m>: more than 63 children")`.) Need: `n_max × (child initial entry need + 1 timer if stagger)` with `n_max` = the child's `max_instances`. `c.maxdep` is the parameter `maxdep = m.max_spawn_depth or 3` registered with `self.param(m, "maxdep", ...)`; `EngineError` is imported by the generated header (`from neorisk_simkit.engine import EngineError`). A `PickRef` field initializer (with `parent_share`; without it only the first line) generates
   ```python
   loc.<cm>__<f>[j] = ctx.refs.<refs>.pick(ctx.self_id, ctx.rng.uniform(site=<site>))
   if ctx.rng.bernoulli(site=<site>, p=<share param>):
       loc.<cm>__<f>[j] = loc.<m>__<f>[i]
   ```
7. **Spawn op** (`enter_more`): per `(child, p, delay, n)`: `if ctx.rng.bernoulli(site=…, p=c.s<k>_sp<j>): out.timer(<delay>, MX_FIRE, prio=PRIO_TIMER, tag=mx_tag(m, i, g, OP_SPAWN, t))`; `mx_sp_<m>_<t>` reserves the spawn need and runs the spawn body; dispatched from `fire_more` on `op == OP_SPAWN and x == t`.
8. **`send_parent(msg)` part** (`part_more`): for every machine `pm` that spawns `m` (op or `std.spawn` act) and has a join on `msg`:
   ```python
   par = loc.<m>__par[i]
   if par < 0:
       return COMMIT
   if loc.<m>__pm[i] == <pm.index>:
       if loc.<pm>__ep[par] != loc.<m>__pep[i]:
           return COMMIT                                   # the parent slot was reused
       if loc.<pm>__jl[par] != 0 and not (<parent in a join state on msg>):
           if loc.<pm>__jl[par] == 2:
               out.mstat(<late of pm>, 1)
           return COMMIT
       bit = 1 << loc.<m>__ord[i]
       if (loc.<pm>__jb[par] & bit) == 0:
           loc.<pm>__jb[par] |= bit
           loc.<pm>__jn[par] += 1
           if <parent in a join state on msg> and loc.<pm>__jn[par] >= loc.<pm>__kids[par]:
               out.timer(ctx.t, MX_FIRE, prio=PRIO_CONTINUE, tag=mx_tag(<pm.index>, par, loc.<pm>__gen[par], OP_NOW, <join target code>))
   return COMMIT
   ```
   ("parent in a join state on msg" = `loc.<pm>__st[par] == J1 or ...`.) Need: 1 timer. An ended parent keeps its `ep` until the slot is reused, and `mx_end` set its `jl`, so late counting holds for ended parents too.
9. **`set_field` / `add_field` parts**: `loc.<m>__<f>[i] = <v>` / `+= <v>`; `return COMMIT`.

- [ ] **Step 5: Run the tests**

Run: `uv run --all-packages pytest libs/simkit/tests/test_machine_family.py libs/simkit/tests/test_machine_basic.py -q`
Expected: PASS (the `chick_slots=1` test compiles a second module). Full suite in the background — PASS.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check $(ls -d libs apps examples/ecommerce_s1 examples/ecommerce_s2 benchmarks 2>/dev/null)
git add libs/simkit/src/neorisk_simkit/machine libs/simkit/tests/fixtures/mx_family \
  libs/simkit/tests/test_machine_family.py
git commit -m "feat(machine): repeat, until, spawn, join with timeout and late policy (D69, D70)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 8: Machine compiler III — request, create_owner; disputes as spawned children (D51)

**Files:**
- Create: `libs/simkit/tests/fixtures/mx_pay/{datagen.toml,specs/pack.py,specs/kernels.py}`
- Modify: `machine/compile.py` (request entry, response dispatch `root_more`, `requests()`, `create_owner` part), `machine/spec.py` (request local must be a request boundary from the partition or its `acts_for`; `store` keys are response payload fields, values declared fields)
- Test: `libs/simkit/tests/test_machine_request.py`

**Interfaces:**
- Consumes: Tasks 6–7 generator; boundary responses (`BoundaryDef.responses`, `response_payload`); `out.request_<b>`; `ProcessDef.on_response`; Task 1 depth for created owners.
- Produces: response command kinds `FIRST_RESPONSE_KIND + j` for each `(boundary, response)` pair used by request ops, in `(boundary code, response index)` order; `MxProcess.requests = {b: b}`; generated `mx_resp_<b>(ctx, s, loc, cmd, out, r)` and `mx_rq_<m>_<k>(ctx, s, loc, cmd, out, i, r)`; op parameter `s<k>_to` (timeout µs).

- [ ] **Step 1: Write the fixture**

`fixtures/mx_pay/datagen.toml`: copy `fixtures/spawn/datagen.toml`; `name = "mx_pay"`, `span = "4d"`, `step = "1d"`, `step_max = "1d"`.

`fixtures/mx_pay/specs/pack.py`:
```python
"""Request with timeout and rejection branch (D67, D83); a dispute as a spawned child process
the payment joins on (D51); create_owner from a machine (D72)."""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, dist, std
from neorisk_simkit.spec.types import boolean, i64, ref

from . import kernels as k

PACK = "mx_pay"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Config:
    payments: int = 6
    limit: int = 500
    latency_ms: int = 200
    timeout: str = "1s"
    dispute_p: float = 1.0
    dispute_after_s: int = 600
    dispute_len_s: int = 1800


def define(p: Pack, cfg: Config) -> None:
    pay = p.table("payment", key="payment_id", mutable=True, cols={"amount": i64()})
    receipt = p.table("receipt", key="receipt_id", mutable=True,
                      cols={"payment_id": ref("payment"), "amount": i64()})
    p.owner("payment", table=pay, max_live=cfg.payments)
    p.owner("receipt", table=receipt, max_live=cfg.payments)
    p.population(pay, n=cfg.payments, initial=1.0, attrs={"amount": dist.uniform_int(100, 900)})
    bank = p.shard("bank", key="bank", n=1, items=None, state={"captured": "i64"})
    p.request("capture", frm="payment", to=bank, payload={"amount": i64()},
              response_payload={"amount": i64()}, responses=("granted", "rejected"),
              latency=dist.constant(ms=cfg.latency_ms))
    pid = {"payment_id": ref("payment")}
    p.event("captured", owner="payment", cols={**pid, "amount": i64()})
    for name in ("declined", "timed_out", "dispute_resolved", "closed"):
        p.event(name, owner="payment", cols=pid)
    p.event("decided", shard="bank", cols={"amount": i64(), "granted": boolean()})
    p.event("receipt_issued", owner="receipt", cols={
        "receipt_id": ref("receipt"), "payment_id": ref("payment"), "amount": i64()})
    p.process("bank_desk", shard=bank, kernel=k.bank_desk, config=cfg,
              on_request={"capture": k.C_CAPTURE})
    p.process("receipt_main", owner="receipt", kernel=k.receipt_main,
              start=p.on_created("receipt"))
    m = p.machine("pay", owner="payment", start=p.on_created("payment"),
                  initial="authorized", config=cfg, fields={"captured": "i64"})
    m.state("authorized", request={"capturing": std.request(
        "capture", amount=std.col("amount"), store={"amount": "captured"})},
        on_reject="declining", timeout=cfg.timeout, on_timeout="timing_out")
    m.state("capturing", branch={"settled": (1.0, dist.constant(s=3600), std.emit(
        "captured", payment_id=std.actor(), amount=std.field("captured")).then(
        std.create_owner("receipt", payment_id=std.actor(), amount=std.field("captured"))))},
        spawn={"dispute": (cfg.dispute_p, dist.constant(s=cfg.dispute_after_s), 1)})
    m.state("settled", join={"closing": "resolved"}, timer={"closing": "1d"}, late="count")
    m.state("closing", branch={"closed": (1.0, None, std.emit("closed", payment_id=std.actor()))})
    m.state("declining", branch={"declined": (1.0, None, std.emit(
        "declined", payment_id=std.actor()))})
    m.state("timing_out", branch={"timed_out": (1.0, None, std.emit(
        "timed_out", payment_id=std.actor()))})
    m.final("closed", "declined", "timed_out")
    d = p.machine("dispute", owner="payment", initial="open", max_instances=2)
    d.state("open", branch={"done": (1.0, dist.constant(s=cfg.dispute_len_s), std.emit(
        "dispute_resolved", payment_id=std.actor()).then(std.send_parent("resolved")))})
    d.final("done")
```

`fixtures/mx_pay/specs/kernels.py`:
```python
from neorisk_simkit.engine import COMMIT, RETRY, START, Res, kernel

C_CAPTURE = 1


@kernel(state="bank", commands=(C_CAPTURE,), max=Res(records={"decided": 1}, requests=1))
def bank_desk(ctx, s, cmd, out):
    if not out.reserve(records={"decided": 1}, requests=1):
        return RETRY
    ok = cmd.amount <= ctx.cfg.limit
    out.emit_decided(ctx.t, amount=cmd.amount, granted=1 if ok else 0)
    if ok:
        s.captured += cmd.amount
        out.respond(cmd, "granted", amount=cmd.amount)
    else:
        out.respond(cmd, "rejected", amount=0)
    return COMMIT


@kernel(state="receipt", commands=(START,), max=Res(records={"receipt_issued": 1}))
def receipt_main(ctx, s, cmd, out):
    if not out.reserve(records={"receipt_issued": 1}):
        return RETRY
    out.emit_receipt_issued(ctx.t, receipt_id=ctx.self_id, payment_id=s.payment_id,
                            amount=s.amount)
    return COMMIT
```

- [ ] **Step 2: Write the failing tests**

`libs/simkit/tests/test_machine_request.py`:
```python
"""Request op (D67, D83), create_owner, and a dispute as a spawned child the payment joins on
(D51). Review Focus 3: a response exactly at the timeout is in time."""

import json

import polars as pl
from conftest import FIXTURES

from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events

S = 1_000_000


def _run(tmp_path, overrides=()):
    res = run_to_dataset(FIXTURES / "mx_pay", "sample", list(overrides),
                         out_dir=tmp_path / "run", threads=2)
    ev = read_events(res.out_dir)
    pays = pl.read_parquet(res.out_dir / "entities" / "payment").select(
        pl.col("id").alias("payment_id"), "amount", pl.col("created_at").alias("t0"))
    return res, ev, pays


def _t(col):
    return col.cast(pl.Int64)


def test_granted_requests_store_the_response_and_create_receipts(tmp_path):
    res, ev, pays = _run(tmp_path)
    ok = pays.filter(pl.col("amount") <= 500)
    cap = ev["captured"].join(pays, on="payment_id", suffix="_p")
    assert set(cap["payment_id"]) == set(ok["payment_id"])
    assert (cap["amount"] == cap["amount_p"]).all()          # stored from the response
    assert set(ev["declined"]["payment_id"]) == set(pays["payment_id"]) - set(ok["payment_id"])
    assert ev["receipt_issued"].height == ok.height
    m = json.loads((res.out_dir / "manifest.json").read_text())
    assert m["pairing"]["capture"]["requests"] == m["pairing"]["capture"]["responses"] == 6


def test_late_responses_take_the_timeout_branch(tmp_path):
    _res, ev, _p = _run(tmp_path, ["latency_ms=1500"])
    assert ev["timed_out"].height == 6 and ev["captured"].height == 0


def test_timeout_boundary_is_inclusive(tmp_path):
    _res, ev, _p = _run(tmp_path / "a", ["latency_ms=1000", "timeout=1000ms"])
    assert ev["timed_out"].height == 0
    _res, ev, _p = _run(tmp_path / "b", ["latency_ms=1000", "timeout=999999us"])
    assert ev["timed_out"].height == 6


def test_a_dispute_answered_before_the_join_state_is_not_lost(tmp_path):
    _res, ev, pays = _run(tmp_path)
    c = ev["captured"].select("payment_id", _t(pl.col("event_time")).alias("tc"))
    d = ev["closed"].select("payment_id", _t(pl.col("event_time")).alias("td")).join(
        c, on="payment_id")
    assert d.height == ev["captured"].height
    assert (d["td"] == d["tc"]).all()                          # joined at once on entry


def test_the_join_waits_for_a_long_dispute(tmp_path):
    _res, ev, _p = _run(tmp_path, ["dispute_len_s=7200"])
    r = ev["dispute_resolved"].select("payment_id", _t(pl.col("event_time")).alias("tr"))
    d = ev["closed"].select("payment_id", _t(pl.col("event_time")).alias("td")).join(
        r, on="payment_id")
    assert d.height > 0 and (d["td"] == d["tr"]).all()


def test_the_join_times_out_and_counts_the_late_dispute(tmp_path):
    res, ev, _p = _run(tmp_path, ["dispute_len_s=172800"])     # two days > the 1d timer
    st = json.loads((res.out_dir / "run_stats.json").read_text())["machines"]["pay"]
    assert ev["closed"].height == ev["captured"].height
    assert st["late"] == ev["dispute_resolved"].height
```
(`test_a_dispute_answered_before_the_join_state_is_not_lost`: the dispute starts 10 min after capture and resolves 30 min later; the payment enters `settled` one hour after capture with `jn == kids`, so `closed` follows at once.) Note `captured` here is emitted when leaving `capturing` (one hour after the grant); compare against that row's time as written.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run --all-packages pytest libs/simkit/tests/test_machine_request.py -q`
Expected: FAIL — `PackError: machine pay: request ops arrive in a later task` (raise that from `enter_more` until this task implements it).

- [ ] **Step 4: Implement**

1. `requests()` returns `{b: b}` for every boundary named by a request op; response kinds: iterate request boundaries in boundary-code order and their responses in declaration order, `self.responses[(b, r)] = FIRST_RESPONSE_KIND + j`.
2. Request entry (`enter_more`): `out.request_<b>(ctx.t, shard=<shard src>, tag=mx_tag(<m.index>, i, g, OP_REQUEST, 0), <payload kw = value srcs>)` with need `requests=1`; register `self.param(m, f"s{k}_to", st.timeout_us)`.
3. `root_more`: for each `(b, r)`, `if cmd.kind == <kind>: return mx_resp_<b>(ctx, s, loc, cmd, out, <index of r in b.responses>)`. `mx_resp_<b>` decodes `m_`, `i`, `g` from `cmd.tag` like the root does, and for every machine with a request state on `b`: `if m_ == <idx>:` stale check (`st == 0` or generation mismatch → `return reject(MX_STALE)`), then `if loc.<m>__st[i] == <k>: return mx_rq_<m>_<k>(ctx, s, loc, cmd, out, i, r)`; finally `return reject(MX_STALE)`.
4. `mx_rq_<m>_<k>`:
   ```python
   c = ctx.cfg.x_<m>
   if not out.reserve(<union of the entry needs of target, on_reject, on_timeout>):
       return RETRY
   if ctx.t - loc.<m>__t0[i] > c.s<k>_to:
       <enter on_timeout or on_reject>
   elif r == <index of ok>:
       <for resp_field, inst_field in store: loc.<m>__<inst_field>[i] = cmd.<resp_field>>
       <enter target>
   else:
       <enter on_reject>
   return COMMIT
   ```
5. `create_owner` part: `out.create_<table>(<col>=<value src>, ...)`, `return COMMIT`; need `creates={table: 1}` (the creation message unit is added by `_reserve_`, D43).

- [ ] **Step 5: Run the tests** — `uv run --all-packages pytest libs/simkit/tests/test_machine_request.py -q` → PASS; full suite in the background → PASS.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check $(ls -d libs apps examples/ecommerce_s1 examples/ecommerce_s2 benchmarks 2>/dev/null)
git add libs/simkit/src/neorisk_simkit/machine libs/simkit/tests/fixtures/mx_pay \
  libs/simkit/tests/test_machine_request.py
git commit -m "feat(machine): request op with timeout on arrival; create_owner; dispute child (D51, D67)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 9: Machine exit tests — retries, uncompiled identity, invariance, inspectability

The S1 ABI proof and invariance exits, repeated for generated machine processes (no checked-mode run here, D90).

**Files:**
- Test: `libs/simkit/tests/test_exit_machines.py`

**Interfaces:**
- Consumes: fixtures `mx_basic`, `mx_family`, `mx_pay`; `engine.force_capacity` (S1 D-contract: `force_capacity[<resource>]` shrinks a buffer so the reserve fails and the runner retries); `conftest.event_dicts`, `conftest.dataset_tree`.
- Produces: nothing new (tests only); a defect found here is fixed in `machine/compile.py`.

- [ ] **Step 1: Write the tests**

```python
"""Machines keep the engine's guarantees (§05, §12): retries are invisible, compiled and
uncompiled runs agree, and thread, slab and step changes leave logical records identical."""

import os
import subprocess
import sys

import pytest
from conftest import FIXTURES, event_dicts

from neorisk_simkit.io.dataset import run_to_dataset

CASES = [("mx_basic", []), ("mx_family", []), ("mx_pay", ["latency_ms=300"])]


def _events(tmp_path, name, overrides, threads=2, **eng):
    res = run_to_dataset(FIXTURES / name, "sample", overrides, out_dir=tmp_path / "run",
                         threads=threads, engine_overrides=eng or None)
    return event_dicts(res.out_dir)


@pytest.mark.parametrize("name, overrides", CASES)
def test_forced_exhaustion_of_each_resource_is_invisible(tmp_path, name, overrides):
    base = _events(tmp_path / "base", name, overrides)
    for res in ("timers", "requests"):
        forced = _events(tmp_path / res, name, overrides,
                         force_capacity={res: 2 if res == "timers" else 1})
        assert forced == base, res


@pytest.mark.parametrize("name, overrides", CASES)
def test_threads_slabs_and_steps_do_not_change_records(tmp_path, name, overrides):
    base = _events(tmp_path / "a", name, overrides, threads=1)
    assert _events(tmp_path / "b", name, overrides, threads=4) == base
    assert _events(tmp_path / "c", name, overrides, slab_bytes=16 * 1024) == base
    assert _events(tmp_path / "d", name, overrides, step_us=2 * 3_600_000_000) == base


@pytest.mark.parametrize("name, overrides", CASES[:2])
def test_uncompiled_run_equals_compiled(tmp_path, name, overrides):
    compiled = _events(tmp_path / "jit", name, overrides)
    out = tmp_path / "nojit"
    env = {**os.environ, "NUMBA_DISABLE_JIT": "1"}
    r = subprocess.run([sys.executable, "-m", "datagen.cli", "run", str(FIXTURES / name),
                        "--out", str(out), "--threads", "2", *sum((["--set", o]
                                                                   for o in overrides), [])],
                       env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert event_dicts(out) == compiled
```
(Adjust the `force_capacity` minimums to the smallest values the fixtures' declared maxima allow — validate refuses a forced capacity below a process's declared maximum, so read `plan.process("mx_<p>").kernel.max` and use exactly that value; the point is that every reserve of the machine process fails at least once. If `step_us` must stay within `[step_min, step_max]` of a fixture, pick a value inside it.)

- [ ] **Step 2: Run** — `uv run --all-packages pytest libs/simkit/tests/test_exit_machines.py -q` → PASS (uncompiled runs take minutes; run in the background). If the uncompiled run fails inside `std.checked_mul` under `NUMBA_DISABLE_JIT` (S2 Task 15 parked minor), fix `std/checked.py` so the guard works on Python ints too, with its own test in `libs/simkit/tests/test_std_rows.py`, in this task.

- [ ] **Step 3: Lint and commit**

```bash
uv run ruff check $(ls -d libs apps examples/ecommerce_s1 examples/ecommerce_s2 benchmarks 2>/dev/null)
git add libs/simkit/tests/test_exit_machines.py
git commit -m "test(machine): retries, uncompiled identity and invariance of machine processes

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```
(Stage any fix made in Step 2 by name as well.)

---

### Task 10: Overlay API — expose, cohorts with an execution owner, member machines, labels, project loading

**Files:**
- Create: `libs/simkit/src/neorisk_simkit/spec/overlay.py`
- Create: `libs/simkit/tests/fixtures/ring/{datagen.toml,specs/pack.py,specs/kernels.py,specs/overlays/ring.py}`
- Modify: `spec/pack.py` (`expose`, `expose_param`; `exposed`, `exposed_params` registries), `spec/plan.py` (`Plan.overlays`, `Plan.cohorts`, `Plan.exposed`; `build_plan(..., overlays=())`), `machine/spec.py` (`MachineDef.root_init`; cohort machines get `labels`/`label_delay` at build), `machine/compile.py` (root member rows, member rows of spawned children, `std.label` parts, spawn counts as parameters), `spec/dist.py` (`BURST`, `burst(start_day, span_days)`), `engine/world.py` (`arrival_times(..., origin)` handles `BURST`; recipes append rows after earlier recipes of the same table, D94), `std/sources.py` (`DevicesRecipe.generate(..., row_offset=0)`), `spec/project.py` (overlays in `[project]`, profiles, `--set <overlay>.<param>`; `RunSpec.overlays`; run name), `io/dataset.py` + `io/manifest.py` (`overlays` in the manifest; `run_to_dataset(..., overlays=())`), `apps/datagen/src/datagen/cli.py` + `run_cmds.py` + `schema_cmd.py` (`--overlay NAME`, repeatable)
- Test: `libs/simkit/tests/test_overlay_api.py`

**Interfaces:**
- Consumes: Tasks 3 (acts_for, members), 4 (labels), 5–8 (machines).
- Produces (Tasks 11, 16, 17, 20 rely on these names):
  - `Pack.expose(**named)` (values: `ActionRef`, `Chain` or `helpers.Request`); `Pack.expose_param(path: str, value)`; `Plan.exposed: Mapping[str, Any]`.
  - `spec.overlay.Overlay(pack, name)`: `.base.<name>` (exposed object; `AttributeError("base pack exposes no 'x'")`), `.param(path)`, `.cohort(name, *, table, size=None, share=None, rate=None, arrivals=None, execution_owner=None, suppress=(), attrs=None, refs=None) -> Cohort`, `.machine(name, *, members, initial, fields=None, init=None, member=None, max_instances=1, config=None, reads=None, max_spawn_depth=None) -> Machine`, `.label(cohort, *, roles, outcomes, available_after: Dist)`. No `event`, `table`, `process`, `request`, `message` or `shard` methods (D74: overlays add no schema).
  - `Cohort(name, table, partition, base_partition, size, suppress, attrs, refs, labels)` with `.spawned(machine) -> Spawned`; `CohortDef` (same fields, frozen) in `Plan.cohorts`.
  - `spec.dist.burst(start_day: float, span_days: float) -> Dist` (kind `BURST`): arrivals uniform in `[start + start_day·1d, + span_days·1d)`; arrivals at or after the run end never happen.
  - `resolve_run(project, profile, overrides=(), seed=None, overlays=None)`; `RunSpec.overlays: tuple[tuple[str, Mapping[str, Any]], ...] = ()`; run name `<profile>-s<seed>+<o1>+...`; `run_to_dataset(..., overlays=())`; manifest key `overlays: {name: params}`; CLI `--overlay NAME` on `validate`, `run`, `schema` (and `check`, Task 19).
  - Generated: `out.add_member_<table>(...)` at a cohort machine's START (root member) and in spawns of member machines; `std.label(role, outcome)` → `out.emit_labels_<cohort>(ctx.t, target_id=<actor>, campaign_id=ctx.self_id, role=…, outcome=…, final_label=1, label_available_at=ctx.t + <draw of available_after>)`.
  - **D95** (schema): an overlay never changes event tables (names, columns, `schema_version`); `schema.json` gains the cohort's entity table and its label table, marked `"overlay": "<name>"`; `datagen schema` (SQL) emits only base tables unless `--overlay` is given.

- [ ] **Step 1: Write the fixture**

`fixtures/ring/datagen.toml`: copy `fixtures/spawn/datagen.toml`; `name = "ring"`, `span = "1d"`, `step = "6h"`, `step_max = "1d"`, and add
```toml
[project]
name = "ring"
pack = "specs/pack.py"
overlays = "specs/overlays"

[profiles.gang]
overlays = ["ring"]

[profiles.gang.overlay.ring]
size = 3
```
(keep `[profiles.sample]`).

`fixtures/ring/specs/pack.py`:
```python
"""Overlay API fixture: a base pack with an exposed owner, exposed actions and a capped pot
that base users and overlay members both claim from."""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, dist, std
from neorisk_simkit.spec.types import cat, i64, opt, ref, ts

from . import kernels as k

PACK = "ring"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Config:
    users: int = 6
    pot: int = 5_000
    bonus: int = 1_000


def define(p: Pack, cfg: Config) -> None:
    device = p.table("device", key="device_id", doc="Devices", cols={
        "os": cat("ios", "android", "windows", "macos", "linux"),
        "kind": cat("phone", "tablet", "desktop"), "first_seen": ts()})
    user = p.table("user", key="user_id", mutable=True,
                   cols={"tier": cat("a", "b"), "invited_by": opt(ref("user"))})
    p.owner("user", table=user, max_live=cfg.users)
    p.population(user, n=cfg.users, initial=1.0,
                 attrs={"tier": dist.categorical({"a": 0.5, "b": 0.5})},
                 refs={"device": std.devices(per_user=dist.categorical({1: 1.0}), table=device,
                                             share=0.0)})
    p.expose_owner("user")
    pot = p.shard("pot", key="pot_id", n=1, items=None,
                  state={"remaining": "i64", "granted": "i64"},
                  init=std.capped_pool.init(cfg.pot))
    claim = p.request("claim", frm="user", to=pot, payload={"who": ref("user"), "amount": i64()},
                      response_payload={"amount": i64()}, responses=("granted", "rejected"),
                      latency=dist.constant(ms=500))
    u = {"user_id": ref("user")}
    p.event("signed_up", owner="user", cols={**u, "device_id": ref("device"),
                                             "invited_by": opt(ref("user"))})
    p.event("bonus_paid", owner="user", cols={**u, "amount": i64()})
    p.event("granted", shard="pot", cols={"who": ref("user"), "amount": i64()})
    p.event("refused", shard="pot", cols={"who": ref("user"), "amount": i64()})
    p.process("user_main", owner="user", kernel=k.user_main, config=cfg,
              start=p.on_created("user"), requests={"claim": claim},
              on_response={("claim", "granted"): k.R_OK, ("claim", "rejected"): k.R_NO},
              refs={"device": "device"}, commands=k.USER_COMMANDS)
    p.process("pot_desk", shard="pot", kernel=k.pot_desk, on_request={"claim": k.C_CLAIM})
    p.expose(signup=k.signup, signup_invited=k.signup_invited, pay_bonus=k.pay_bonus,
             claim=std.request("claim", who=std.actor(), amount=cfg.bonus,
                               store={"amount": "paid"}))
    p.expose_param("bonus", cfg.bonus)
```

`fixtures/ring/specs/kernels.py`:
```python
from neorisk_simkit import std
from neorisk_simkit.engine import COMMIT, RETRY, START, Res, action, kernel, reject

R_OK, R_NO, C_CLAIM = 1, 2, 1
USER_COMMANDS = (START, R_OK, R_NO)


@kernel(state="user", commands=USER_COMMANDS,
        max=Res(records={"signed_up": 1, "bonus_paid": 1}, requests=1))
def user_main(ctx, s, cmd, out):
    if cmd.kind == START:
        if not out.reserve(records={"signed_up": 1}, requests=1):
            return RETRY
        out.emit_signed_up(ctx.t, user_id=ctx.self_id,
                           device_id=ctx.refs.device.get(ctx.self_id, 0), invited_by=std.NULL)
        out.request_claim(ctx.t, shard=0, who=ctx.self_id, amount=ctx.cfg.bonus)
        return COMMIT
    if cmd.kind == R_OK:
        if not out.reserve(records={"bonus_paid": 1}):
            return RETRY
        out.emit_bonus_paid(ctx.t, user_id=ctx.self_id, amount=cmd.amount)
        return COMMIT
    return reject(0)


@kernel(state="pot", commands=(C_CLAIM,),
        max=Res(records={"granted": 1, "refused": 1}, requests=1))
def pot_desk(ctx, s, cmd, out):
    if not out.reserve(records={"granted": 1, "refused": 1}, requests=1):
        return RETRY
    g = std.capped_pool.take(s.remaining, cmd.amount)
    if g > 0:
        s.remaining = std.checked_sub(s.remaining, g)
        s.granted = std.checked_add(s.granted, g)
        out.emit_granted(ctx.t, who=cmd.who, amount=g)
        out.respond(cmd, "granted", amount=g)
    else:
        out.emit_refused(ctx.t, who=cmd.who, amount=cmd.amount)
        out.respond(cmd, "rejected", amount=0)
    return COMMIT


@action(state="user", max=Res(records={"signed_up": 1}), fields={"device": "ref"})
def signup(ctx, s, m, cmd, out):
    out.emit_signed_up(ctx.t, user_id=m.id, device_id=m.device, invited_by=std.NULL)
    return COMMIT


@action(state="user", max=Res(records={"signed_up": 1}), fields={"device": "ref"})
def signup_invited(ctx, s, m, cmd, out):
    out.emit_signed_up(ctx.t, user_id=m.id, device_id=m.device, invited_by=m.parent_id)
    return COMMIT


@action(state="user", max=Res(records={"bonus_paid": 1}), fields={"paid": "i64"})
def pay_bonus(ctx, s, m, cmd, out):
    out.emit_bonus_paid(ctx.t, user_id=m.id, amount=m.paid)
    return COMMIT
```

`fixtures/ring/specs/overlays/ring.py`:
```python
"""A gang: one boss and its minions under one gang owner (execution owner, D74). Minions sign
up through the boss and claim from the base pot; the boss joins on their payouts."""

from neorisk_simkit.spec import Overlay, dist, std


def apply(o: Overlay, size: int = 2, minions: int = 2, arrive_day: float = 0.0,
          share_device: float = 0.5, wait: str = "2h") -> None:
    gang = o.cohort("gang", table="user", size=size,
                    arrivals=dist.burst(start_day=arrive_day, span_days=0.01),
                    execution_owner="gang_id", suppress=["user_main"], attrs={"tier": "b"},
                    refs={"device": std.devices(per_user=dist.categorical({2: 1.0}),
                                                table="device", share=0.0)})
    boss = o.machine("boss", members=gang, initial="new", fields={"device": "ref"},
                     init={"device": std.pick_ref("device")})
    boss.state("new", branch={"recruiting": (1.0, dist.constant(s=60), o.base.signup.then(
        std.label("boss", "attempted")).then(std.spawn(
            "minion", n=minions,
            fields={"device": std.pick_ref("device", parent_share=share_device)})))})
    boss.state("recruiting", join={"done": "paid"}, timer={"done": wait}, late="count")
    boss.final("done")
    minion = o.machine("minion", members=gang.spawned("minion"), initial="invited",
                       max_instances=8, fields={"device": "ref", "paid": "i64"},
                       member={"invited_by": std.parent()})
    minion.state("invited", branch={"claiming": (1.0, dist.constant(s=300), o.base.signup_invited
                                                 .then(std.label("minion", "attempted")))})
    minion.state("claiming", request={"paid": o.base.claim}, on_reject="gone", timeout="1m")
    minion.state("paid", branch={"gone": (1.0, None, o.base.pay_bonus.then(
        std.label("minion", "paid")).then(std.send_parent("paid")))})
    minion.final("gone")
    o.label(gang, roles=("boss", "minion"), outcomes=("attempted", "paid"),
            available_after=dist.constant(s=86_400))
```

- [ ] **Step 2: Write the failing tests**

`libs/simkit/tests/test_overlay_api.py`:
```python
"""The overlay contract's engine side (§08, D74-D77, D94, D95; Review Focus 5)."""

import json

import numpy as np
import polars as pl
import pytest
from conftest import FIXTURES

from neorisk_simkit.engine.world import arrival_times
from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events
from neorisk_simkit.spec import Overlay, Pack, PackError, dist
from neorisk_simkit.spec.project import load_project, resolve_run
from neorisk_simkit.spec.validate import validate

RING = FIXTURES / "ring"
DAY = 86_400_000_000


def _run(profile="sample", overrides=(), overlays=None):
    return resolve_run(load_project(RING), profile, list(overrides), overlays=overlays)


def _data(tmp_path, overrides=(), overlays=("ring",)):
    res = run_to_dataset(RING, "sample", list(overrides), overlays=list(overlays),
                         out_dir=tmp_path / "run", threads=2)
    return res, read_events(res.out_dir)


def test_overlay_adds_a_cohort_without_touching_the_base():
    base, plan = _run(overlays=[]).plan, _run(overlays=["ring"]).plan
    assert plan.overlays == ("ring",) and plan.partition("gang").acts_for == "user"
    assert {m.name for m in plan.machines} == {"boss", "minion"}
    ev = lambda p: [(e.name, e.cols) for e in p.events if e.group == "events"]   # noqa: E731
    assert ev(plan) == ev(base)
    assert all(plan.process(p.name).action_id == p.action_id for p in base.processes)
    assert plan.namespaces[:len(base.namespaces)] == base.namespaces
    assert validate(_run(overlays=["ring"])).ok


def test_run_name_and_profile_parameters():
    assert _run(overlays=["ring"]).name == "sample-s7+ring"
    run = _run("gang")
    assert run.overlays == (("ring", {"size": 3, "minions": 2, "arrive_day": 0.0,
                                       "share_device": 0.5, "wait": "2h"}),)
    assert next(c for c in run.plan.cohorts if c.name == "gang").size == 3
    assert next(c for c in _run("gang", ["ring.size=1"]).plan.cohorts).size == 1


def test_members_emit_base_events_and_labels(tmp_path):
    res, ev = _data(tmp_path)
    d = res.out_dir
    users = pl.read_parquet(d / "entities" / "user")
    members = users.filter(pl.col("origin") == "member")
    assert members.height == 2 * (1 + 2)                     # two gangs: boss + 2 minions
    su = ev["signed_up"].join(members.select(pl.col("id").alias("user_id")), on="user_id")
    assert su.height == members.height
    minions = su.filter(pl.col("invited_by").is_not_null())
    assert minions.height == 4 and set(minions["invited_by"]) <= set(su["user_id"])
    m = json.loads((d / "manifest.json").read_text())
    assert m["label_counts"]["labels_gang"] >= 2 + 4
    labels = pl.read_parquet(sorted((d / "labels" / "labels_gang").rglob("*.parquet")))
    assert set(labels["role"]) == {"boss", "minion"}
    assert (labels["label_available_at"] - labels["event_time"]).dt.total_seconds().min() == 86_400
    assert m["overlays"] == {"ring": {"size": 2, "minions": 2, "arrive_day": 0.0,
                                       "share_device": 0.5, "wait": "2h"}}


def test_cohort_devices_are_appended_after_base_devices(tmp_path):
    res_b, _ = _data(tmp_path / "b", overlays=())
    res_o, ev = _data(tmp_path / "o")
    base = pl.read_parquet(res_b.out_dir / "entities" / "device")
    full = pl.read_parquet(res_o.out_dir / "entities" / "device")
    assert full.height == base.height + 2 * 2
    assert full.head(base.height).equals(base)


def test_a_zero_size_cohort_changes_nothing_in_the_base(tmp_path):
    _rb, base = _data(tmp_path / "b", overlays=())
    ro, ovl = _data(tmp_path / "o", ["ring.size=0"])
    for name, t in base.items():
        assert t.drop("event_id").equals(ovl[name].drop("event_id")), name
    m = json.loads((ro.out_dir / "manifest.json").read_text())
    assert m["label_counts"] == {"labels_gang": 0}


def test_a_cohort_arriving_after_the_end_never_acts(tmp_path):
    _rb, base = _data(tmp_path / "b", overlays=())
    _ro, ovl = _data(tmp_path / "o", ["ring.arrive_day=5.0"])
    for name, t in base.items():
        assert t.drop("event_id").equals(ovl[name].drop("event_id")), name


def test_suppress_names_base_processes():
    p = Pack("x", 1)
    from neorisk_simkit.spec.types import i64
    t = p.table("user", key="user_id", mutable=True, cols={"n": i64()})
    p.owner("user", table=t, max_live=2)
    p.population(t, n=2, initial=1.0)
    p.expose_owner("user")
    with pytest.raises(PackError, match="suppress names unknown process 'nope'"):
        Overlay(p, "o").cohort("c", table="user", size=1, suppress=["nope"])


def test_overlays_cannot_declare_schema():
    for name in ("event", "table", "process", "request", "message", "shard"):
        assert not hasattr(Overlay, name), name


def test_burst_arrivals_fall_in_their_window():
    u = np.linspace(0, 1, 101, endpoint=False)
    start = 10 * DAY
    t = arrival_times(dist.burst(start_day=1.0, span_days=0.5), u, start - DAY, start + 3 * DAY,
                      origin=start)
    assert t.min() >= start + DAY and t.max() < start + DAY + DAY // 2
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run --all-packages pytest libs/simkit/tests/test_overlay_api.py -q`
Expected: FAIL — `ImportError: cannot import name 'Overlay' from 'neorisk_simkit.spec'`.

- [ ] **Step 4: Implement**

1. `spec/dist.py`: `BURST = 14` (append to the kind tuple), `burst(start_day, span_days)` (`_finite` both, `span_days > 0`), and make `encode`/`min_us` refuse it ("burst is an arrival schedule only"). `engine/world.py` `arrival_times(d, u, t0, t1, origin=None)`: for `BURST`, `lo = origin + start_day·DAY`, `t = lo + floor(u · span_days·DAY)`, `t = max(t, t0)` (no clamp at `t1`: owners at or after `t1` are never admitted); `_build_populations` passes `origin=self.run.start_us`.
2. `spec/overlay.py`:
   ```python
   """Overlays (spec §08): add a configurable group of actors to a base pack without editing it.
   An overlay sees the base only through `p.expose(...)`, `p.expose_param(...)` and
   `p.expose_owner(...)`; it adds cohorts, machines on them and labels, never events, tables,
   processes or boundaries (D74, D95)."""

   from __future__ import annotations

   from dataclasses import dataclass, field
   from typing import Any

   from neorisk_simkit.spec.dist import BURST, Dist
   from neorisk_simkit.spec.pack import Pack, PackError
   from neorisk_simkit.spec.types import boolean, cat, i16, ref, ts


   @dataclass(frozen=True)
   class CohortDef:
       name: str
       table: str                 # the base table its members are rows of
       partition: str             # its own owner partition (= name)
       base_partition: str
       size: int
       suppress: tuple[str, ...]
       attrs: tuple[tuple[str, Any], ...]
       refs: tuple[str, ...]
       labels: str | None
       overlay: str


   @dataclass
   class Cohort:
       name: str
       table: str
       base_partition: str
       size: int
       suppress: tuple[str, ...]
       attrs: dict
       refs: dict
       overlay: str
       labels: str | None = None
       label_delay: Dist | None = None
       machines: list = field(default_factory=list)

       @property
       def partition(self) -> str:
           return self.name

       def spawned(self, machine: str) -> Spawned:
           return Spawned(self, machine)

       def define(self) -> CohortDef:
           return CohortDef(self.name, self.table, self.name, self.base_partition, self.size,
                            self.suppress, tuple(self.attrs.items()), tuple(self.refs),
                            self.labels, self.overlay)


   @dataclass(frozen=True)
   class Spawned:
       cohort: Cohort
       machine: str


   class _Base:
       def __init__(self, exposed: dict):
           self._exposed = exposed

       def __getattr__(self, name: str):
           try:
               return self._exposed[name]
           except KeyError:
               raise AttributeError(f"base pack exposes no {name!r}") from None


   class Overlay:
       def __init__(self, pack: Pack, name: str):
           self._p, self.name = pack, name
           self.base = _Base(pack.exposed)

       def param(self, path: str):
           if path not in self._p.exposed_params:
               raise PackError(f"overlay {self.name}: base pack exposes no parameter {path!r}")
           return self._p.exposed_params[path]

       def cohort(self, name: str, *, table: str, size: int | None = None,
                  share: float | None = None, rate: float | None = None,
                  arrivals: Dist | None = None, execution_owner: str | None = None,
                  suppress=(), attrs: dict | None = None, refs: dict | None = None) -> Cohort:
           p = self._p
           base = next((q for q in p.partitions.values()
                        if q["kind"] == "owner" and q["table"] == table), None)
           if base is None or base["name"] not in p.exposed_owners:
               raise PackError(f"cohort {name}: table {table!r} has no exposed owner partition")
           if sum(x is not None for x in (size, share, rate)) != 1:
               raise PackError(f"cohort {name}: give exactly one of size=, share=, rate=")
           if size is not None:
               n = int(size)
           elif share is not None:
               n = round(share * p.populations[table]["n"])
           else:
               if arrivals is None or arrivals.kind != BURST:
                   raise PackError(f"cohort {name}: rate= needs arrivals=dist.burst(...)")
               n = round(rate * arrivals.params[1])
           if n < 0:
               raise PackError(f"cohort {name}: size must be >= 0")
           known = {q["name"] for q in p.processes.values() if q["partition"] == base["name"]}
           known |= {m.name for m in p.machines.values() if m.partition == base["name"]}
           for s in suppress:
               if s not in known:
                   raise PackError(f"cohort {name}: suppress names unknown process {s!r} of "
                                   f"partition {base['name']!r}")
           t = p.table(name, key=execution_owner or f"{name}_id", mutable=True,
                       cols={"members": i16()},
                       doc=f"Execution owner of overlay {self.name} cohort {name}")
           p.owner(name, table=t, max_live=max(1, n), acts_for=base["name"])
           p.population(t, n=n, initial=0.0 if arrivals is not None else 1.0,
                        arrivals=arrivals, refs=refs)
           c = Cohort(name, table, base["name"], n, tuple(suppress), dict(attrs or {}),
                      dict(refs or {}), self.name)
           p.cohorts[name] = c
           return c

       def machine(self, name: str, *, members, initial: str, fields=None, init=None,
                   member=None, max_instances: int = 1, config=None, reads=None,
                   max_spawn_depth=None):
           cohort = members.cohort if isinstance(members, Spawned) else members
           if not isinstance(cohort, Cohort):
               raise PackError(f"machine {name}: members= must be a cohort or cohort.spawned(...)")
           root = isinstance(members, Cohort)
           m = self._p.machine(
               name, owner=cohort.partition, initial=initial,
               start=self._p.on_created(cohort.name) if root else None, config=config,
               max_instances=max_instances, fields=fields, reads=reads,
               refs={r: r for r in cohort.refs}, max_spawn_depth=max_spawn_depth,
               member_table=cohort.table, root_member=root,
               member_values=tuple({**cohort.attrs, **(member or {})}.items()),
               root_init=tuple((init or {}).items()), overlay=self.name)
           cohort.machines.append(m)
           return m

       def label(self, cohort: Cohort, *, roles, outcomes, available_after: Dist) -> None:
           name = f"labels_{cohort.name}"
           self._p.labels(name, owner=cohort.partition, cols={
               "target_id": ref(cohort.table), "campaign_id": ref(cohort.name),
               "role": cat(*roles), "outcome": cat(*outcomes), "final_label": boolean(),
               "label_available_at": ts()})
           cohort.labels, cohort.label_delay = name, available_after
           for m in cohort.machines:
               m.extra.update(labels=name, label_delay=available_after)
   ```
   Export `Overlay` from `spec/__init__.py`. `Pack.__init__` gains `self.exposed: dict = {}`, `self.exposed_params: dict = {}`, `self.cohorts: dict = {}`; `expose(**named)` refuses names already exposed and values that are not `ActionRef`, `Chain` or `Request`; `expose_param(path, value)`. A machine built after `o.label` inherits the label table: `Overlay.machine` also sets `labels`/`label_delay` when `cohort.labels` is already known.
3. `machine/spec.py`: `MachineDef.root_init: tuple[tuple[str, Any], ...] = ()`; validation: `std.label` in a machine without `labels` → `f"{w}: std.label needs o.label(...) on its cohort"`.
4. `machine/compile.py`:
   - `_Gen.member_values(m, ctx_parent: bool) -> tuple[str, Need]`: the source of `out.add_member_<table>(...)` with every non-nullable column of the member table given — from `m.member_values` (values; `std.parent()` in a spawned child's member values means the spawning instance's actor), else `0` (ints, amounts, bools), the first category for `cat`, `ctx.t` for `ts`; nullable columns not given are left out (`std.NULL`). Need: `creates={table: 1}`.
   - `root_need(m)` / `root_actor(m)` (Task 6 hooks): for `m.root_member`, `actor = out.add_member_<table>(...)`; after `mx_init_<m>(...)` assign every `root_init` field (`PickRef` → `ctx.refs.<refs>.pick(ctx.self_id, ctx.rng.uniform(site=…))`).
   - Spawn body (Task 7): when the child is a member machine, `actor = out.add_member_<table>(...)` and the child's `pactor` is the parent's actor; the need adds `creates={table: n_max}`.
   - `n=` of `std.spawn` and of spawn ops: an int becomes the parameter `c.s<k>_n<j>` (so overlay params never change the source).
   - `std.label(role, outcome)` part: as in the Interfaces block; the delay draw uses parameter `label_delay`; need `records={labels: 1}`.
5. `engine/world.py` `_build_recipes` / `_build_tables` (D94): walk populations in plan order; for each refs recipe pass `row_offset` = rows already built for its table by earlier recipes; `_build_tables` concatenates every recipe's `table_rows(t)` in that order. `std/sources.py` `DevicesRecipe.generate(..., row_offset=0)` adds `row_offset` to its CSR indices. `spec/caps.py` sums `max_table_rows` over recipes of a table.
6. `spec/project.py`: `[project] overlays` (default `"specs/overlays"`); `resolve_run(..., overlays=None)`: enabled = profile `overlays` + `overlays` (order kept, duplicates dropped); profile keys `overlays`/`overlay` are popped before the `_RUN_KEYS` check; an override whose head is an enabled overlay sets that overlay's parameter (`_coerce` against the `apply` default; a `Dist` default → `ProjectError(f"overlay {o}: parameter {k!r} is a Dist and fixed in code")`; unknown → `ProjectError(f"overlay {o}: unknown parameter {k!r}")`); the overlay module is imported as `<pack package>.overlays.<name>` (an implicit namespace subpackage of the synthetic specs package) and must define `apply`; `build_plan(module, cfg, specs_dir, overlays=((name, apply, params), ...))` calls each `apply(Overlay(p, name), **params)` after `define`, then sets `Plan.overlays`, `Plan.cohorts` (`CohortDef`s) and `Plan.exposed`; `RunSpec.overlays` keeps `(name, params)`; the run name appends `+<name>` per overlay.
7. `io/manifest.py`: `overlays` key (`{name: params}`, `{}` when none). `io/schema/schema_json.py`: entity and label tables of cohorts carry `"overlay": "<name>"` (D95). `apps/datagen`: `--overlay` (append) on `validate`, `run`, `schema`; `run_cmds.cmd_run` passes `overlays=args.overlay`.

- [ ] **Step 5: Run the tests**

Run: `uv run --all-packages pytest libs/simkit/tests/test_overlay_api.py -q`
Expected: PASS (two modules compile: base and base+ring). Full suite in the background — PASS; S1 reduced hash unchanged.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check $(ls -d libs apps examples/ecommerce_s1 examples/ecommerce_s2 benchmarks 2>/dev/null)
git add libs/simkit/src/neorisk_simkit/spec libs/simkit/src/neorisk_simkit/machine \
  libs/simkit/src/neorisk_simkit/engine/world.py libs/simkit/src/neorisk_simkit/std/sources.py \
  libs/simkit/src/neorisk_simkit/io apps/datagen/src/datagen/cli.py \
  apps/datagen/src/datagen/run_cmds.py apps/datagen/src/datagen/schema_cmd.py \
  libs/simkit/tests/fixtures/ring libs/simkit/tests/test_overlay_api.py
git commit -m "feat(spec): overlays: exposed base, cohorts with an execution owner, labels (§08)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 11: Exit test — the §07 campaign trace

A fixture that replays the bounty-hunter trace of §07 with constant latencies and scripted times, and a test that pins every row of it.

**Files:**
- Create: `libs/simkit/tests/fixtures/campaign_trace/{datagen.toml,specs/pack.py,specs/kernels.py,specs/overlays/trace_ring.py}`
- Test: `libs/simkit/tests/test_exit_campaign_trace.py`

**Interfaces:**
- Consumes: Tasks 3, 4, 8, 10.
- Produces: the trace contract: claims at `day 12 09:14:00` from base users `U0`, `U1` and zombie `Z0` are decided by the pool in canonical order (base user partitions first); `Z0`'s `bonus_paid` is at `09:14:00.500`; the campaign partition has no row in `(09:14:00, 09:14:00.500)` (it is suspended); `Z1` (12:57:00) is granted; `Z2`'s claim at `16:40:00` is rejected (cap exhausted) and `Z2` leaves with label outcome `attempted`; the hunter continues (its join times out and it reaches `collecting`).

- [ ] **Step 1: Write the fixture**

`campaign_trace/datagen.toml`: copy `fixtures/spawn/datagen.toml`; `name = "campaign_trace"`, `start = "2026-03-01T00:00:00Z"`, `span = "14d"`, `warmup = "0s"`, `[engine] step = "1d"`, `step_max = "1d"`, `[project] overlays = "specs/overlays"`, and `[profiles.trace] overlays = ["trace_ring"]` (plus `[profiles.sample]`).

`campaign_trace/specs/pack.py`:
```python
"""The §07 campaign trace: two base users and a bounty-hunter campaign claim from one pool."""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, dist, std
from neorisk_simkit.spec.types import i64, opt, ref

from . import kernels as k

PACK = "campaign_trace"
SCHEMA_VERSION = 1
CLAIM_AT_S = 12 * 86_400 + 9 * 3_600 + 14 * 60          # day 12 09:14:00


@dataclass(frozen=True)
class Config:
    users: int = 2
    bonus: int = 2_000
    cap_claims: int = 4
    claim_at_s: int = CLAIM_AT_S


def define(p: Pack, cfg: Config) -> None:
    user = p.table("user", key="user_id", mutable=True, cols={"invited_by": opt(ref("user"))})
    p.owner("user", table=user, max_live=cfg.users)
    p.population(user, n=cfg.users, initial=1.0)
    p.expose_owner("user")
    pool = p.shard("pool", key="pool_id", n=1, items=None,
                   state={"remaining": "i64", "granted": "i64"},
                   init=std.capped_pool.init(cfg.bonus * cfg.cap_claims))
    claim = p.request("claim", frm="user", to=pool, payload={"who": ref("user"), "amount": i64()},
                      response_payload={"amount": i64()}, responses=("granted", "rejected"),
                      latency=dist.constant(ms=500))
    u = {"user_id": ref("user")}
    p.event("order_placed", owner="user", cols={**u, "amount": i64()})
    p.event("bonus_paid", owner="user", cols={**u, "amount": i64()})
    p.event("bonus_granted", shard="pool", cols={"who": ref("user"), "amount": i64()})
    p.event("bonus_rejected", shard="pool", cols={"who": ref("user"), "amount": i64()})
    p.process("user_main", owner="user", kernel=k.user_main, config=cfg,
              start=p.on_created("user"), requests={"claim": claim},
              on_response={("claim", "granted"): k.R_OK, ("claim", "rejected"): k.R_NO},
              commands=k.USER_COMMANDS)
    p.process("pool_desk", shard="pool", kernel=k.pool_desk, on_request={"claim": k.C_CLAIM})
    p.expose(first_order=k.first_order, pay_bonus=k.pay_bonus,
             claim=std.request("claim", who=std.actor(), amount=cfg.bonus,
                               store={"amount": "paid"}))
```

`campaign_trace/specs/kernels.py`:
```python
from neorisk_simkit import std
from neorisk_simkit.engine import (COMMIT, PRIO_TIMER, RETRY, START, Res, action, kernel,
                                   reject)

R_OK, R_NO, C_CLAIM, C_GO = 1, 2, 1, 3
USER_COMMANDS = (START, R_OK, R_NO, C_GO)
S = 1_000_000


@kernel(state="user", commands=USER_COMMANDS,
        max=Res(records={"order_placed": 1, "bonus_paid": 1}, timers=1, requests=1))
def user_main(ctx, s, cmd, out):
    if cmd.kind == START:
        if not out.reserve(timers=1):
            return RETRY
        out.timer(ctx.t + ctx.cfg.claim_at_s * S, C_GO, prio=PRIO_TIMER)
        return COMMIT
    if cmd.kind == C_GO:
        if not out.reserve(records={"order_placed": 1}, requests=1):
            return RETRY
        out.emit_order_placed(ctx.t, user_id=ctx.self_id, amount=3_100)
        out.request_claim(ctx.t, shard=0, who=ctx.self_id, amount=ctx.cfg.bonus)
        return COMMIT
    if cmd.kind == R_OK:
        if not out.reserve(records={"bonus_paid": 1}):
            return RETRY
        out.emit_bonus_paid(ctx.t, user_id=ctx.self_id, amount=cmd.amount)
        return COMMIT
    return reject(0)


@kernel(state="pool", commands=(C_CLAIM,),
        max=Res(records={"bonus_granted": 1, "bonus_rejected": 1}, requests=1))
def pool_desk(ctx, s, cmd, out):
    if not out.reserve(records={"bonus_granted": 1, "bonus_rejected": 1}, requests=1):
        return RETRY
    g = std.capped_pool.take(s.remaining, cmd.amount)
    if g > 0:
        s.remaining = std.checked_sub(s.remaining, g)
        s.granted = std.checked_add(s.granted, g)
        out.emit_bonus_granted(ctx.t, who=cmd.who, amount=g)
        out.respond(cmd, "granted", amount=g)
    else:
        out.emit_bonus_rejected(ctx.t, who=cmd.who, amount=cmd.amount)
        out.respond(cmd, "rejected", amount=0)
    return COMMIT


@action(state="user", max=Res(records={"order_placed": 1}))
def first_order(ctx, s, m, cmd, out):
    out.emit_order_placed(ctx.t, user_id=m.id, amount=3_100)
    return COMMIT


@action(state="user", max=Res(records={"bonus_paid": 1}), fields={"paid": "i64"})
def pay_bonus(ctx, s, m, cmd, out):
    out.emit_bonus_paid(ctx.t, user_id=m.id, amount=m.paid)
    return COMMIT
```

`campaign_trace/specs/overlays/trace_ring.py`:
```python
"""One campaign: a hunter spawns three zombies 3h43m apart from day 12 09:14:00; each orders,
claims and reports back; the third finds the cap exhausted."""

from neorisk_simkit.spec import Overlay, dist, std

HUNT_AT_S = 12 * 86_400 + 9 * 3_600 + 14 * 60
STAGGER_S = 3 * 3_600 + 43 * 60


def apply(o: Overlay, zombies: int = 3) -> None:
    camp = o.cohort("campaign", table="user", size=1, execution_owner="campaign_id")
    h = o.machine("hunter", members=camp, initial="new")
    h.state("new", branch={"recruiting": (1.0, dist.constant(s=HUNT_AT_S), std.label(
        "hunter", "attempted").then(std.spawn("zombie", n=zombies,
                                               stagger=dist.constant(s=STAGGER_S))))})
    h.state("recruiting", join={"collecting": "zombie_paid"}, timer={"collecting": "1d"},
            late="count")
    h.state("collecting", branch={"gone": (1.0, None, std.label("hunter", "paid"))})
    h.final("gone")
    z = o.machine("zombie", members=camp.spawned("zombie"), initial="invited",
                  max_instances=4, fields={"paid": "i64"}, member={"invited_by": std.parent()})
    z.state("invited", branch={"claiming": (1.0, None, o.base.first_order.then(
        std.label("zombie", "qualified")))})
    z.state("claiming", request={"paid": o.base.claim}, on_reject="leaving", timeout="1m")
    z.state("paid", branch={"gone": (1.0, None, o.base.pay_bonus.then(
        std.label("zombie", "paid")).then(std.send_parent("zombie_paid")))})
    z.state("leaving", branch={"gone": (1.0, None, std.label("zombie", "attempted"))})
    z.final("gone")
    o.label(camp, roles=("hunter", "zombie"), outcomes=("attempted", "qualified", "paid"),
            available_after=dist.constant(s=30 * 86_400))
```

- [ ] **Step 2: Write the test**

`libs/simkit/tests/test_exit_campaign_trace.py`:
```python
"""§07 trace 2 (M3 exit): a bounty-hunter campaign against a capped bonus pool."""

import json
from datetime import UTC, datetime, timedelta

import polars as pl
from conftest import FIXTURES

from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events

T = datetime(2026, 3, 13, 9, 14, tzinfo=UTC)               # day 12 09:14:00
CAMPAIGN_PTYPE = 3                                         # user 1, pool 2, campaign 3


def test_campaign_trace(tmp_path):
    res = run_to_dataset(FIXTURES / "campaign_trace", "trace", [], out_dir=tmp_path / "t",
                         threads=2)
    ev = read_events(res.out_dir)
    users = pl.read_parquet(res.out_dir / "entities" / "user")
    base = users.filter(pl.col("origin") != "member")["id"].to_list()
    zombies = (ev["order_placed"].filter((pl.col("partition_id") >> 56) == CAMPAIGN_PTYPE)
               .sort("event_time")["user_id"].to_list())
    assert len(zombies) == 3
    z0, z1, z2 = zombies

    # 09:14:00: the pool decides U0, U1 and Z0 in its own heap, in canonical order: the base
    # requests carry the smaller cause lamport, and U0 < U1 by sender key (D61)
    g = ev["bonus_granted"].sort("event_time", "lamport")
    first = g.filter(pl.col("event_time") == T)
    assert first["who"].to_list() == [*base, z0]          # entities are in dense order
    assert first["lamport"].is_sorted()

    # the campaign is suspended between its claim and the response 0.5 s later
    camp = pl.concat([t.filter((pl.col("partition_id") >> 56) == CAMPAIGN_PTYPE)
                      .select("event_time") for t in ev.values() if t.height])
    assert camp.filter((pl.col("event_time") > T)
                       & (pl.col("event_time") < T + timedelta(milliseconds=500))).height == 0
    paid = ev["bonus_paid"].filter(pl.col("user_id") == z0)
    assert paid["event_time"].to_list() == [T + timedelta(milliseconds=500)]

    # Z1 at 12:57 is granted; Z2 at 16:40 finds the cap exhausted and leaves as "attempted"
    assert ev["bonus_granted"].filter(pl.col("who") == z1).height == 1
    rej = ev["bonus_rejected"]
    assert rej["who"].to_list() == [z2]
    assert rej["event_time"].to_list() == [T.replace(hour=16, minute=40)]
    labels = pl.read_parquet(sorted((res.out_dir / "labels" / "labels_campaign").rglob("*.parquet")))
    last = labels.sort("event_time", "lamport").group_by("target_id").last()
    outcome = dict(zip(last["target_id"].to_list(), last["outcome"].to_list(), strict=True))
    assert outcome[z2] == "attempted" and outcome[z0] == outcome[z1] == "paid"

    # the hunter continues: its join times out (Z2 never reports) and it reaches collecting
    st = json.loads((res.out_dir / "run_stats.json").read_text())["machines"]["hunter"]
    assert st["entries"]["collecting"] == 1 and st["late"] == 0
```
(Why base requests come first at 09:14:00: each base user's request is caused by its second commit (lamport 2); the zombie's by the campaign's fifth (hunter START, branch fire, zombie start, first order, label continuation), and routing orders ties by `(time, prio, cause, sender key, src_seq)`. If the fixture's command chain changes, recompute the expectation from that rule; never loosen it to a set comparison.)

- [ ] **Step 3: Run** — `uv run --all-packages pytest libs/simkit/tests/test_exit_campaign_trace.py -q` → PASS. A failure here is a defect in Tasks 3, 8 or 10: fix it there, with a regression test in that task's test file, never by changing this trace.

- [ ] **Step 4: Lint and commit**

```bash
uv run ruff check $(ls -d libs apps examples/ecommerce_s1 examples/ecommerce_s2 benchmarks 2>/dev/null)
git add libs/simkit/tests/fixtures/campaign_trace libs/simkit/tests/test_exit_campaign_trace.py
git commit -m "test(exit): the §07 campaign trace against a capped pool

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 12: `cause_id` (D14 → D80) — the last engine edit of M3

`cause_id` has been null since S1. This task fills it: a command node remembers the commit that queued it, every worker logs its commits, and seal resolves causes to event IDs, carrying resolved IDs on nodes that outlive their step. **This task changes S1 output on purpose** (`cause_id` values; nothing else) and records the new S1 reduced-profile hash.

**Files:**
- Create: `libs/simkit/tests/fixtures/causes/{datagen.toml,specs/pack.py,specs/kernels.py}`
- Modify: `engine/cmdq.py` (`NODE_FIELDS` += `cpid`, `ceid`; `P_CPID, P_CEID = 15, 16`; `NodePool` arrays; `NODE_BYTES` follows), `engine/codegen.py` (`_push` and admission write `cpid`/`ceid`; `run_partitions` logs each commit and returns `NEED_SWAP` when the log is full), `engine/route.py` (deliveries write `cpid = src_pid`, `ceid = UNSET`), `engine/world.py` (`_queue_starts` / periodic starts write `ceid = NULL_CAUSE`; flush moves the log into `StepChunk.commits`), `engine/slabs.py` (`OUT_TAIL` += `"clog"`, `"clog_n"`; `StepChunk.commits`), `io/seal.py` (resolution; `event_table(..., cause_ids=)`), `spec/caps.py` (commit log bytes in `output_slabs`; node bytes from `NODE_BYTES`)
- Modify tests: `libs/simkit/tests/test_engine_seal.py` (the `cause_id` null assertion becomes "null for population starts")
- Test: `libs/simkit/tests/test_engine_cause.py`

**Interfaces:**
- Consumes: S1/S2 node pool, `run_partitions`, `_Remap` (`pid=True`), `event_table`, `SealedStep`.
- Produces: `cmdq.UNSET_CAUSE = -2`, `cmdq.NULL_CAUSE = -1`; node fields `cpid` (partition id of the causing commit as held during its step) and `ceid` (resolved cause event id, `NULL_CAUSE` or `UNSET_CAUSE`); out-tail `clog int64[cap, 5]` rows `(pid, lamport, cpid, clamport, ceid)` with `cap = max(64, slab_bytes // 40)` and `clog_n int64[1]`; `StepChunk.commits: np.ndarray` (k × 5); `seal.resolve_causes(...)`; the exported `cause_id` column (D80).

- [ ] **Step 1: Write the fixture**

`causes/datagen.toml`: copy `fixtures/spawn/datagen.toml`; `name = "causes"`, `span = "6h"`, `warmup = "0s"`, `[engine] step = "1h"`, `step_min = "15m"`, `step_max = "1d"`.

`causes/specs/pack.py`:
```python
"""cause_id (D80): request -> shard record -> response, and a timer chain through a commit
that emits nothing, across step boundaries."""

from neorisk_simkit.spec import Pack, dist
from neorisk_simkit.spec.types import i32, ref

from . import kernels as k

PACK = "causes"
SCHEMA_VERSION = 1


def define(p: Pack, cfg) -> None:
    acct = p.table("acct", key="acct_id", mutable=True, cols={"n": i32()})
    p.owner("acct", table=acct, max_live=2)
    p.population(acct, n=2, initial=1.0)
    desk = p.shard("desk", key="desk", n=1, items=None, state={})
    ask = p.request("ask", frm="acct", to=desk, payload={"who": ref("acct")},
                    responses=("ok",), latency=dist.constant(ms=200))
    a = {"acct_id": ref("acct")}
    for name in ("opened", "ticked", "answered"):
        p.event(name, owner="acct", cols=a)
    p.event("asked", shard="desk", cols={"who": ref("acct")})
    p.process("acct_main", owner="acct", kernel=k.acct_main, start=p.on_created("acct"),
              requests={"ask": ask}, on_response={("ask", "ok"): k.R_OK},
              commands=k.ACCT_COMMANDS)
    p.process("desk_main", shard=desk, kernel=k.desk_main, on_request={"ask": k.C_ASK})
```

`causes/specs/kernels.py`:
```python
from neorisk_simkit.engine import COMMIT, PRIO_TIMER, RETRY, START, Res, kernel

R_OK, C_TICK, C_EMIT, C_ASK = 1, 2, 3, 1
ACCT_COMMANDS = (START, R_OK, C_TICK, C_EMIT)
H = 3_600_000_000


@kernel(state="acct", commands=ACCT_COMMANDS,
        max=Res(records={"opened": 1, "ticked": 1, "answered": 1}, timers=1, requests=1))
def acct_main(ctx, s, cmd, out):
    if cmd.kind == START:
        if not out.reserve(records={"opened": 1}, timers=1, requests=1):
            return RETRY
        out.emit_opened(ctx.t, acct_id=ctx.self_id)
        out.timer(ctx.t + 2 * H, C_TICK, prio=PRIO_TIMER)
        out.request_ask(ctx.t, shard=0, who=ctx.self_id)
        return COMMIT
    if cmd.kind == C_TICK:                         # emits nothing: causes pass through it
        if not out.reserve(timers=1):
            return RETRY
        out.timer(ctx.t + H, C_EMIT, prio=PRIO_TIMER)
        return COMMIT
    if not out.reserve(records={"ticked": 1, "answered": 1}):
        return RETRY
    if cmd.kind == C_EMIT:
        out.emit_ticked(ctx.t, acct_id=ctx.self_id)
    else:
        out.emit_answered(ctx.t, acct_id=ctx.self_id)
    return COMMIT


@kernel(state="desk", commands=(C_ASK,), max=Res(records={"asked": 1}, requests=1))
def desk_main(ctx, s, cmd, out):
    if not out.reserve(records={"asked": 1}, requests=1):
        return RETRY
    out.emit_asked(ctx.t, who=cmd.who)
    out.respond(cmd, "ok")
    return COMMIT
```

- [ ] **Step 2: Write the failing tests**

`libs/simkit/tests/test_engine_cause.py`:
```python
"""D80: cause_id = event_id of the first record of the nearest record-emitting commit in a
command's causal chain."""

import polars as pl
from conftest import FIXTURES

from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events


def _ev(tmp_path, overrides=(), **eng):
    res = run_to_dataset(FIXTURES / "causes", "sample", list(overrides), out_dir=tmp_path / "r",
                         threads=2, engine_overrides=eng or None)
    return read_events(res.out_dir)


def _links(ev):
    opened = ev["opened"].select("acct_id", pl.col("event_id").alias("opened_id"))
    asked = ev["asked"].select(pl.col("who").alias("acct_id"), pl.col("event_id").alias("asked_id"),
                               pl.col("cause_id").alias("asked_cause"))
    j = opened.join(asked, on="acct_id")
    j = j.join(ev["answered"].select("acct_id", pl.col("cause_id").alias("answered_cause")),
               on="acct_id")
    return j.join(ev["ticked"].select("acct_id", pl.col("cause_id").alias("ticked_cause")),
                  on="acct_id")


def test_causes_follow_requests_responses_and_silent_commits(tmp_path):
    ev = _ev(tmp_path)
    assert ev["opened"]["cause_id"].null_count() == 2          # population starts: no cause
    j = _links(ev)
    assert j.height == 2
    assert (j["asked_cause"] == j["opened_id"]).all()          # request -> shard record
    assert (j["answered_cause"] == j["asked_id"]).all()         # response -> owner record
    assert (j["ticked_cause"] == j["opened_id"]).all()          # through C_TICK, 2 steps later


def test_causal_links_do_not_depend_on_step_length(tmp_path):
    for i, step in enumerate((3_600_000_000, 6 * 3_600_000_000)):
        j = _links(_ev(tmp_path / str(i), step_us=step))
        assert (j["asked_cause"] == j["opened_id"]).all()
        assert (j["ticked_cause"] == j["opened_id"]).all()


def test_a_cause_in_warm_up_is_null(tmp_path):
    ev = _ev(tmp_path, ["run.warmup=1h"])                       # opened/asked/answered in warm-up
    assert ev["opened"].height == 0
    assert ev["ticked"]["cause_id"].null_count() == ev["ticked"].height == 2
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run --all-packages pytest libs/simkit/tests/test_engine_cause.py -q`
Expected: FAIL — every `cause_id` is null.

- [ ] **Step 4: Implement**

1. `engine/cmdq.py`: append `("cpid", "int64"), ("ceid", "int64")` to `NODE_FIELDS`, the arrays to `NodePool` (`ceid` filled with `NULL_CAUSE`) and to `with_free_lists` (positions 15, 16); `UNSET_CAUSE, NULL_CAUSE = -2, -1`. Do not change `q_push`/`q_push_from` signatures: every caller writes `P[P_CPID][node]`, `P[P_CEID][node]` right after a successful push.
2. Writers: generated `_push` (timers, continuations): `cpid = ctx[CTX_PID]`, `ceid = UNSET_CAUSE`; periodic re-queue in `run_partitions` and `_queue_starts`: `cpid = 0`, `ceid = NULL_CAUSE`; generated `admit_created` STARTs: `cpid = CQ[CQ_SRC_PID][i]`, `ceid = UNSET_CAUSE`; `route_outbox` and `deliver_owner_messages`: `cpid = ob[_OB_SRC_PID][i]`, `ceid = UNSET_CAUSE`.
3. Commit log: `OUT_TAIL` += `"clog", "clog_n"`; `SlabSet` allocates `clog = np.zeros((max(64, slab_bytes // 40), 5), np.int64)`, `clog_n = np.zeros(1, np.int64)`. In `run_partitions`, before dispatch (next to the node-cap check): `if clog_n[0] >= clog.shape[0]: return _NEED_SWAP, i`; on `COMMIT`:
   ```python
   "            c_ = clog_n[0]",
   "            clog[c_, 0] = pid[g]",
   "            clog[c_, 1] = lamport",
   "            clog[c_, 2] = P[_P_CPID][node]",
   "            clog[c_, 3] = cause",
   "            clog[c_, 4] = P[_P_CEID][node]",
   "            clog_n[0] = c_ + 1",
   ```
   (read the node's fields before `q_remove`/`q_free`). `World._flush` appends `clog[:clog_n]` to the chunk (`StepChunk.commits`) and zeroes `clog_n`; `World.handle_status(NEED_SWAP)` flushes as for full slabs.
4. `io/seal.py`: after merging and **after** the remap of step 3 (apply `remap.apply(commits[:, 0], ..., pid=True)` and `[:, 2]` the same way, and remap `cpid` of every queued node of touched slots), add:
   ```python
   @njit(cache=True, nogil=True)
   def _resolve(kp, kl, first, cpid, clam, ceid, order):
       """Cause event id per commit (rows of the step's commit log sorted by (pid, lamport) in
       kp/kl; `order` = commit rows by lamport). A commit's cause is the resolved ceid it ran
       with, else the first record of the commit (cpid, clam) of this step, else that commit's
       own cause; NULL_CAUSE when nothing emitted a record."""
       n = kp.shape[0]
       cause = np.full(n, -1, np.int64)
       for j in range(n):
           r = order[j]
           if ceid[r] != -2:
               cause[r] = ceid[r]
               continue
           lo, hi = 0, n                                 # binary search (pid, lamport)
           while lo < hi:
               mid = (lo + hi) // 2
               if kp[mid] < cpid[r] or (kp[mid] == cpid[r] and kl[mid] < clam[r]):
                   lo = mid + 1
               else:
                   hi = mid
           if lo < n and kp[lo] == cpid[r] and kl[lo] == clam[r]:
               cause[r] = first[lo] if first[lo] >= 0 else cause[lo]
       return cause
   ```
   with the log sorted by `(pid, lamport)` (`np.lexsort((l, p))`), `first[c]` = the `event_id` of the commit's lowest-`seq` exported record (built from every exported event table's `(partition_id, lamport, seq, event_id)` after `event_table` assigned IDs; warm-up steps give none), and `order` = commit rows sorted by lamport (a cause commit always has a smaller lamport than its effect, so it is resolved first). Then: each event table's `cause_id` = `cause` of its row's commit `(pid, lamport)`; every queued node of a touched slot with `ceid == UNSET_CAUSE` gets the cause resolved the same way from its `(cpid, cause lamport)`. `event_table(e, rows, id_bases, seed, cause_ids=None)` writes `pa.array(cause_ids, mask=cause_ids < 0)` (else the S1 nulls). Postings and labels get `cause_id` the same way.
5. `spec/caps.py`: per worker `output_slabs` += `clog` bytes; `timer_heaps` uses `NODE_BYTES` (now 90).
6. `test_engine_seal.py`: the assertion `t["cause_id"].null_count == t.num_rows` becomes: non-null `cause_id` values are event IDs of the same dataset, and population-start rows are null.

- [ ] **Step 5: Run the tests and record the new S1 hash**

Run: `uv run --all-packages pytest libs/simkit/tests/test_engine_cause.py libs/simkit/tests/test_engine_seal.py -q` → PASS. Full suite in the background → PASS. Run the S1 reduced-profile hash procedure (Global Constraints): the hash changes (expected: `cause_id` values only). Verify that claim before recording it: compare the BASE and HEAD datasets with `cause_id` dropped from every events file —
```python
import polars as pl, pathlib
a, b = pathlib.Path("/tmp/s1r_base"), pathlib.Path("/tmp/s1r")
for f in sorted((a / "events").rglob("*.parquet")):
    g = b / f.relative_to(a)
    assert pl.read_parquet(f).drop("cause_id").equals(pl.read_parquet(g).drop("cause_id")), f
```
(produce `/tmp/s1r_base` with the same command from a checkout of the previous commit) — then record the new hash in `benchmarks/README.md` (S1 section, one line: "M3 Task 12: S1 reduced-profile hash `<new>` (cause_id populated, D80; every other column identical)") and in the commit message. Also time the S1 reduced profile warm (median of 3 after one warm-up run) before and after; report both in the commit message (Task 23 re-measures the gate).

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check $(ls -d libs apps examples/ecommerce_s1 examples/ecommerce_s2 benchmarks 2>/dev/null)
git add libs/simkit/src/neorisk_simkit/engine libs/simkit/src/neorisk_simkit/io/seal.py \
  libs/simkit/src/neorisk_simkit/spec/caps.py libs/simkit/tests/fixtures/causes \
  libs/simkit/tests/test_engine_cause.py libs/simkit/tests/test_engine_seal.py benchmarks/README.md
git commit -m "feat(engine): populate cause_id through a per-worker commit log (D14, D80)

S1 reduced-profile hash: <old> -> <new> (cause_id only).
S1 reduced warm: <before> s -> <after> s (median of 3).

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```
From this commit on, every later task compares against the new S1 hash.

---

### Task 13: Laws for M3 — `sum_le` against state (F-07), periodic `total_le`, `lifecycle`

**Files:**
- Create: `libs/simkit/tests/fixtures/refunds/{datagen.toml,specs/pack.py,specs/kernels.py}`
- Modify: `libs/simkit/src/neorisk_simkit/spec/law.py` (`total_le(..., per=None)`, `lifecycle(key, edges)`), `checks/laws.py` (`_SumLeState`, periodic `_TotalLe`, `_Lifecycle`; `LawBook` builds them), `spec/validate.py` (`_law_reason` accepts the new forms)
- Test: `libs/simkit/tests/test_checks_laws_m3.py`

**Interfaces:**
- Consumes: `LawBook.step(sealed, world, exported=)`, `_Law` base (`warm`, `judge(rows, world, retired)`, `_fail`, `reserve`), `resolve_path`, world `state`/`hidden`/`slot_base` (as `_NeverNegativeState` reads them).
- Produces: `law.sum_le(lhs, "<owner table>.<column>", by=<that table's key>)` (D81); `law.total_le(lhs, limit, per="30d")` — windows `event_time // per` (epoch-aligned), a violation when one window's total exceeds `limit`; `law.lifecycle(key, edges: dict[str, tuple[str, ...]])` — per key, each row of a listed event type must follow (as that key's previous listed row, canonical order) a type whose edge list contains it; the first row of a key must be a type that is no edge's target. Task 14 uses all three.

- [ ] **Step 1: Write the fixture**

`refunds/datagen.toml`: copy `fixtures/spawn/datagen.toml`; `name = "refunds"`, `span = "4h"`, `step = "1h"`.

`refunds/specs/pack.py`:
```python
"""sum_le with a state column on the right (F-07, D81)."""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, dist, law
from neorisk_simkit.spec.types import i64, ref

from . import kernels as k

PACK = "refunds"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Config:
    extra: int = 0                    # 1: the second refund exceeds the order amount


def define(p: Pack, cfg: Config) -> None:
    order = p.table("order", key="order_id", mutable=True, cols={"amount": i64()})
    p.owner("order", table=order, max_live=3)
    p.population(order, n=3, initial=1.0, attrs={"amount": dist.uniform_int(100, 300)})
    p.event("refund_issued", owner="order", cols={"order_id": ref("order"), "amount": i64()})
    p.process("order_main", owner="order", kernel=k.order_main, config=cfg,
              start=p.on_created("order"), commands=k.ORDER_COMMANDS)
    p.check("chk.refund_le_paid",
            law.sum_le("refund_issued.amount", "order.amount", by="order_id"), required=True)
```

`refunds/specs/kernels.py`:
```python
from neorisk_simkit.engine import COMMIT, PRIO_TIMER, RETRY, START, Res, kernel

C_AGAIN = 1
ORDER_COMMANDS = (START, C_AGAIN)
H = 3_600_000_000


@kernel(state="order", commands=ORDER_COMMANDS, max=Res(records={"refund_issued": 1}, timers=1))
def order_main(ctx, s, cmd, out):
    if not out.reserve(records={"refund_issued": 1}, timers=1):
        return RETRY
    half = s.amount // 2
    if cmd.kind == START:
        out.emit_refund_issued(ctx.t, order_id=ctx.self_id, amount=half)
        out.timer(ctx.t + 2 * H, C_AGAIN, prio=PRIO_TIMER)
    else:
        out.emit_refund_issued(ctx.t, order_id=ctx.self_id,
                               amount=s.amount - half + ctx.cfg.extra)
    return COMMIT
```

- [ ] **Step 2: Write the failing tests**

`libs/simkit/tests/test_checks_laws_m3.py`:
```python
"""M3 laws: sum_le against owner state (D81), periodic total_le, lifecycle."""

import dataclasses
from types import SimpleNamespace

import pyarrow as pa
import pytest
from conftest import FIXTURES, make_run

from neorisk_simkit.checks.laws import LawBook
from neorisk_simkit.engine.errors import LawViolation
from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.spec import law
from neorisk_simkit.spec.plan import CheckDef

TS = pa.timestamp("us", tz="UTC")


def test_refunds_up_to_the_order_amount_pass(tmp_path):
    res = run_to_dataset(FIXTURES / "refunds", "sample", [], out_dir=tmp_path / "a", threads=1)
    assert res.manifest["laws"]["chk.refund_le_paid"]["checked"] == 6


def test_a_refund_beyond_the_order_amount_violates(tmp_path):
    with pytest.raises(LawViolation, match="order_id .*refund_issued.amount total .* exceeds "
                                           "order.amount"):
        run_to_dataset(FIXTURES / "refunds", "sample", ["extra=1"], out_dir=tmp_path / "b",
                       threads=1)


def _table(rows, cols=("acct_id", "amount")):
    n = len(rows)
    out = {"event_id": pa.array(range(1, n + 1), pa.int64()),
           "event_type": pa.array(["x"] * n, pa.string()),
           "event_time": pa.array([r["t"] for r in rows], pa.int64()).cast(TS),
           "lamport": pa.array([r.get("lamport", i + 1) for i, r in enumerate(rows)], pa.int64()),
           "partition_id": pa.array([r.get("pid", 1) for r in rows], pa.int64()),
           "seq": pa.array([r.get("seq", i) for i, r in enumerate(rows)], pa.int32()),
           "cause_id": pa.nulls(n, pa.int64()),
           "action_id": pa.array([0] * n, pa.int16())}
    for c in cols:
        out[c] = pa.array([r[c] for r in rows], pa.int64())
    return pa.table(out)


def _book(cid, lw):
    run = make_run("ledger")
    plan = dataclasses.replace(run.plan, checks=(CheckDef(cid, lw, True),))
    return LawBook(plan, max_keys=100)


def _sealed(events=None, postings=None):
    return SimpleNamespace(step=0, t_start=0, t_end=10**12, exported=True, events=events or {},
                           postings=postings or {}, history={}, entities={}, stats={},
                           warmup_rows={})


def test_total_le_per_period_resets_each_window():
    book = _book("chk.t", law.total_le("opened.amount", 5, per="10us"))
    book.step(_sealed({"opened": _table([{"t": 1, "acct_id": 1, "amount": 5},
                                         {"t": 11, "acct_id": 1, "amount": 5}])}), None)
    with pytest.raises(LawViolation, match="window"):
        book.step(_sealed({"opened": _table([{"t": 12, "acct_id": 1, "amount": 1}])}), None)


def test_lifecycle_follows_its_edges():
    lw = law.lifecycle("acct_id", edges={"opened": ("entry",)})
    book = _book("chk.l", lw)
    book.step(_sealed({"opened": _table([{"t": 1, "acct_id": 1, "amount": 0}])},
                      {"entry": _table([{"t": 2, "acct_id": 1, "amount": 0}])}), None)
    with pytest.raises(LawViolation, match="entry after entry"):
        book.step(_sealed(postings={"entry": _table([{"t": 3, "acct_id": 1, "amount": 0}])}),
                  None)
    book2 = _book("chk.l2", lw)
    with pytest.raises(LawViolation, match="entry cannot start"):
        book2.step(_sealed(postings={"entry": _table([{"t": 3, "acct_id": 2, "amount": 0}])}),
                   None)
```
(The `ledger` fixture's posting table is `entry` and its event `opened`, both keyed by `acct_id` with an `amount` column — confirm in `fixtures/ledger/specs/pack.py`; if a column differs, adapt `_table`'s `cols`, never the law.)

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run --all-packages pytest libs/simkit/tests/test_checks_laws_m3.py -q`
Expected: FAIL — validate refuses `sum_le` with a state right side; `total_le()` has no `per`; `law.lifecycle` does not exist.

- [ ] **Step 4: Implement**

1. `spec/law.py`: `total_le(lhs, limit, per=None)` stores `("per", per)`; `lifecycle(key, edges)` → `LawSpec("lifecycle", (("key", key), ("edges", tuple((a, tuple(b)) for a, b in edges.items()))))`.
2. `checks/laws.py`:
   - `_SumLeState(_Law)`: `tables = (lhs table,)`; keeps sorted `rkeys`/`rlast` (the right side's last value per key) and the left running sums like `_SumLe`. `_refresh(world, retired)`: for the owner partition of the right table, the slots alive now plus `retired` → `self_id` (dense after the seal's remap) and the column value; update `rlast` (insert new keys, overwrite old). `warm(rows)` feeds left sums; `step` order: refresh first (warm-up steps too — `LawBook.step` passes `world` for warm-up steps; extend it if it does not), then judge exported left rows: running Σ lhs per key > `rlast[key]` (0 when unknown) is a violation with the message `f"{by} {key}: {lhs} total {sum} exceeds {table}.{col} {value}"`.
   - `_TotalLe` with `per`: the running total restarts when `event_time // per` changes (rows are in canonical order, so windows only advance); the message names the window: `f"{lhs} total {x} exceeds {limit} in window {w}"`.
   - `_Lifecycle(_Law)`: per key the last listed type code (sorted key arrays, like `_AtMostOnce`); every exported row of a listed table is judged: the first row of a key must not be any edge's target (`f"{key_col} {k}: {t} cannot start a lifecycle"`), a later row's type must be in `edges[previous]` (`f"{key_col} {k}: {t} after {prev}"`); warm-up rows only update the state.
   - `LawBook` maps `sum_le` with a state right side (resolved by `resolve_path`) to `_SumLeState`, `lifecycle` to `_Lifecycle`. `checker_state` reservation: `_SumLeState` keys × 24 B, `_Lifecycle` keys × 16 B.
3. `spec/validate.py` `_law_reason`: `sum_le` accepts `<owner table>.<column>` on the right when `by` is that table's key; `lifecycle` needs every edge table to be an event or posting table with the key column.

- [ ] **Step 5: Run the tests** — `uv run --all-packages pytest libs/simkit/tests/test_checks_laws_m3.py libs/simkit/tests/test_checks_laws.py libs/simkit/tests/test_checks_laws_keyed.py -q` → PASS; full suite in the background → PASS; S1 hash = the Task 12 hash.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check $(ls -d libs apps examples/ecommerce_s1 examples/ecommerce_s2 benchmarks 2>/dev/null)
git add libs/simkit/src/neorisk_simkit/spec/law.py libs/simkit/src/neorisk_simkit/checks/laws.py \
  libs/simkit/src/neorisk_simkit/spec/validate.py libs/simkit/tests/fixtures/refunds \
  libs/simkit/tests/test_checks_laws_m3.py
git commit -m "feat(checks): sum_le against owner state, periodic total_le, lifecycle (F-07, D81)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 14: `examples/ecommerce` I — the real pack: shoppers, carts, inventory, orders, fulfillment machine

The current `examples/ecommerce/specs/{pack,kernels}.py` are a design sketch written before S1 against an API that does not exist. This task replaces them with a pack that runs, keeping the brief, the model and the event vocabulary (D91). All kernels, actions (including the ones Task 15 tests and Task 16 calls) and laws land here in one go, so the 45–90 min compile of this module happens once for Tasks 14–16.

**Files:**
- Rewrite: `examples/ecommerce/specs/pack.py`, `examples/ecommerce/specs/kernels.py`, `examples/ecommerce/datagen.toml`
- Delete: `examples/ecommerce/specs/overlays/flash_sale.py` (D93), `examples/ecommerce/specs/overlays/bounty_hunters.py` (rewritten in Task 16)
- Create: `examples/ecommerce/{out,reports,logs}/.gitkeep` if missing
- Test: `apps/datagen/tests/test_example_ecom.py`

**Interfaces:**
- Consumes: S2 patterns (`examples/ecommerce_s2/specs/kernels.py`: hold table, join over reserve responses, restock), Tasks 2, 3, 5–8, 10, 13.
- Produces (Tasks 15–22 rely on these names): partitions `user` (population, exposed owner), `order` (created owner), `inventory` (shard), `referral_pool` (shard, n = 1); events listed in `pack.py` below; change group `address`; processes `shopper`, `inventory_desk`, `restock`, `pool_desk`, machine `fulfillment` (process `mx_order`); exposed actions `signup`, `signup_invited`, `quick_order`, `pay_referral`, request `claim_bonus`, parameter `referral.min_order`; laws `chk.stock_never_negative`, `chk.reserved_never_negative`, `chk.holds_resolved`, `chk.refund_le_paid`, `chk.order_lifecycle`, `chk.referral_once_per_invitee`, `chk.referral_budget`, `chk.credit_never_negative`, `chk.hold_never_negative`, `chk.pool_never_negative`; profiles `sample`, `legacy`, `full`, `abuse` (the last two with overlays from Task 16 — `legacy` and `abuse` validate only after Task 16).

- [ ] **Step 1: Write `examples/ecommerce/specs/pack.py`**

```python
"""E-commerce marketplace pack (see brief.md).

Partitions
    owner  user           one shopper: profile, credit and its hold, region, cart scratch
    owner  order          one placed order (created at checkout); runs the fulfillment machine
    shard  inventory      one inventory group: on_hand / reserved per SKU and a 64-slot hold table
    shard  referral_pool  the referral program's budget, reset every `referral.period`

Boundaries (immutable, latency >= delta)
    user -> inventory      reserve (request), commit / release (messages)    delta 150 ms
    user -> referral_pool  claim (request)                                    delta 300 ms
    user -> user           inviter_credit (owner-to-owner, D73)               delta 1 day

Overlays reach the base only through p.expose / p.expose_param / p.expose_owner (§08).
"""

from dataclasses import dataclass, field

from neorisk_simkit.spec import Pack, dist, law, std
from neorisk_simkit.spec.types import amount, boolean, cat, i16, i32, i64, opt, ref, ts

from . import kernels as k

PACK = "ecommerce"
SCHEMA_VERSION = 1

CATEGORIES = (
    "apparel", "shoes", "beauty", "home", "kitchen", "garden", "toys", "baby", "books",
    "music", "video_games", "electronics", "phones", "computers", "office", "pets", "sports",
    "outdoors", "auto", "tools", "grocery", "health", "jewelry", "luggage",
)
CHANNELS = ("web", "app")
ACQUISITION = ("organic", "search_ad", "social_ad", "affiliate", "invite")
REGIONS = tuple(f"r{i:02d}" for i in range(k.N_REGIONS))
CARRIERS = ("ups", "fedex", "usps", "dhl")
RETURN_REASONS = ("size", "damaged", "not_as_described", "changed_mind", "late")
HOLD_SLACK_S = 300


@dataclass(frozen=True)
class Journey:
    """Shopper behavior; consumed by kernels.shopper (ctx.cfg.journey)."""
    signup_delay: dist.Dist = dist.exp(mean_s=3600)
    session_gap_alpha: float = 1.2
    session_gap_min_h: float = 30.0
    views_mean: float = 6.0
    view_gap: dist.Dist = dist.exp(mean_s=40)
    add_to_cart_p: float = 0.18
    checkout_p: float = 0.5                 # per session end with a non-empty cart
    checkout_delay: dist.Dist = dist.exp(mean_s=25)
    substitute_p: float = 0.45
    auth_latency: dist.Dist = dist.lognormal(median_s=2.5, sigma=0.6)
    auth_fail_p: float = 0.03
    credit_use_p: float = 0.9
    move_gap: dist.Dist = dist.exp(mean_days=45)   # address changes (user_state downstream)


@dataclass(frozen=True)
class Referral:
    referred_share: float = 0.06            # population users who arrived through an invite
    inviter_share: float = 0.04             # invitees name an inviter among the first 4%
    min_order: int = 3_000                  # cents; a first order from $30 qualifies
    bonus_each: int = 1_000                 # cents; invitee and inviter
    monthly_budget: int = 25_000_000        # cents per period
    period: str = "30d"


@dataclass(frozen=True)
class Fulfil:
    """Fulfillment machine parameters (branch probabilities are config, not code)."""
    ship_p: float = 0.985
    return_apparel_p: float = 0.18
    return_shoes_p: float = 0.14
    return_p: float = 0.045


@dataclass(frozen=True)
class Desk:
    hold_ttl_s: int = 600


@dataclass(frozen=True)
class PoolCfg:
    budget: int = 25_000_000
    period_us: int = 30 * 86_400_000_000


@dataclass(frozen=True)
class Config:
    users: int = 200_000
    initial_share: float = 0.6
    skus: int = 50_000
    sku_groups: int = 512
    restock_period: str = "7d"
    household_share_device: float = 0.12
    orders_live_ratio: float = 0.5
    journey: Journey = field(default_factory=Journey)
    referral: Referral = field(default_factory=Referral)
    fulfil: Fulfil = field(default_factory=Fulfil)
    desk: Desk = field(default_factory=Desk)


def define(p: Pack, cfg: Config) -> None:
    from neorisk_simkit.spec.project import parse_duration
    r = cfg.referral
    # ---------------------------------------------------------------- read tables
    sku = p.table("sku", key="sku_id", doc="Catalog, fixed for the run", cols={
        "category": cat(*CATEGORIES), "price": amount(asset="USD"), "sku_group": i16()},
        source=std.catalog(n=cfg.skus, category=dist.categorical(
            {c: 1 / len(CATEGORIES) for c in CATEGORIES}),
            price=dist.lognormal_minor(median=2_500, sigma=0.9, min=199, max=200_000),
            group=dist.uniform_int(0, cfg.sku_groups - 1), weight=dist.zipf(s=1.07)))
    device = p.table("device", key="device_id", doc="Shopper devices", cols={
        "os": cat("ios", "android", "windows", "macos", "linux"),
        "kind": cat("phone", "tablet", "desktop"), "first_seen": ts()})
    # ---------------------------------------------------------------- shoppers
    user = p.table("user", key="user_id", mutable=True, doc="A shopper and their wallet", cols={
        "age_band": cat("18-24", "25-34", "35-44", "45-54", "55+"),
        "acquisition": cat(*ACQUISITION), "region": cat(*REGIONS), "referred": boolean(),
        "invited_by": opt(ref("user")), "credit": amount(asset="USD"),
        "held": amount(asset="USD")})
    p.ids("session", "checkout", "hold", "claim")
    p.owner("user", table=user, max_live=cfg.users, retire_when_idle=False)
    n_inviters = max(1, int(cfg.users * cfg.initial_share * r.inviter_share))
    p.population(
        user, n=cfg.users, initial=cfg.initial_share,
        arrivals=dist.poisson_daily(weekly=(1.0, 0.95, 0.95, 1.0, 1.1, 1.3, 1.25), trend=0.002),
        attrs={"age_band": dist.categorical({"18-24": .17, "25-34": .31, "35-44": .24,
                                             "45-54": .16, "55+": .12}),
               "acquisition": dist.categorical({"organic": .55, "search_ad": .2,
                                                "social_ad": .15, "affiliate": .1}),
               "region": dist.categorical({x: 1 / len(REGIONS) for x in REGIONS}),
               "referred": dist.categorical({0: 1 - r.referred_share, 1: r.referred_share}),
               # inviters are among the first users, who exist from the start (D91)
               "invited_by": dist.uniform_int(0, n_inviters - 1)},
        refs={"device": std.devices(per_user=dist.categorical({1: .6, 2: .3, 3: .1}),
                                    table=device, share=cfg.household_share_device)})
    p.change_group("address", table="user", cols=("region",))
    p.expose_owner("user")
    # ---------------------------------------------------------------- orders (created owners)
    order = p.table("order", key="order_id", mutable=True, doc="A placed order", cols={
        "user_id": ref("user"), "amount": amount(asset="USD"), "lines": i16(),
        "category": cat(*CATEGORIES), "credit_used": amount(asset="USD"),
        "refunded": amount(asset="USD"),
        "status": cat("placed", "shipped", "delivered", "lost", "returned")})
    p.owner("order", table=order, max_live=max(1_000, int(cfg.users * cfg.orders_live_ratio)))
    # ---------------------------------------------------------------- inventory
    inventory = p.shard("inventory", key="sku_group", n=cfg.sku_groups, items=sku,
                        doc="Stock per inventory group",
                        state={"on_hand": "i32[sku]", "reserved": "i32[sku]"},
                        init=std.stock(initial=dist.negbinom(mean=40, disp=0.7), by_weight=8.0))
    lat = dist.shifted_lognormal(min_ms=150, median_ms=240)
    reserve = p.request("reserve", frm="user", to=inventory,
                        payload={"sku_id": ref("sku"), "quantity": i16(), "line": i16()},
                        response_payload={"hold_id": opt(ref("hold")), "slot": i32(),
                                          "line": i16()},
                        responses=("granted", "rejected"), latency=lat)
    held = {"sku_id": ref("sku"), "quantity": i16(), "hold_id": ref("hold"), "slot": i32()}
    commit = p.message("commit", frm="user", to=inventory, payload=held, latency=lat)
    release = p.message("release", frm="user", to=inventory, payload=held, latency=lat)
    # ---------------------------------------------------------------- referral pool
    period_us = parse_duration(r.period)
    pool = p.shard("referral_pool", key="pool_id", n=1, items=None,
                   doc="The referral budget; claims are whole or rejected; reset each period",
                   state={"remaining": "i64", "granted": "i64", "window": "i64"},
                   init={"remaining": [r.monthly_budget], "granted": [0], "window": [-1]})
    usd = amount(asset="USD")
    claim = p.request("claim", frm="user", to=pool,
                      payload={"claim_id": ref("claim"), "amount": usd},
                      response_payload={"amount": usd}, responses=("granted", "rejected"),
                      latency=dist.shifted_lognormal(min_ms=300, median_ms=450))
    inviter_credit = p.message("inviter_credit", frm="user", to="user",
                               payload={"invitee": ref("user"), "amount": usd},
                               latency=dist.shifted_lognormal(min_ms=86_400_000,
                                                              median_ms=100_000_000))
    # ---------------------------------------------------------------- events
    u = {"user_id": ref("user")}
    p.event("user_signed_up", owner="user", doc="A shopper creates an account", cols={
        **u, "device_id": ref("device"), "acquisition": cat(*ACQUISITION),
        "referred": boolean(), "invited_by": opt(ref("user"))})
    p.event("session_started", owner="user", cols={
        **u, "session_id": ref("session"), "device_id": ref("device"), "channel": cat(*CHANNELS)})
    p.event("product_viewed", owner="user", cols={
        **u, "session_id": ref("session"), "sku_id": ref("sku"), "device_id": ref("device"),
        "position": i16(), "category": cat(*CATEGORIES), "price": usd})
    p.event("cart_item_added", owner="user", cols={
        **u, "session_id": ref("session"), "sku_id": ref("sku"), "quantity": i16(),
        "unit_price": usd})
    p.event("checkout_started", owner="user", doc="Credit held; one reserve per cart line",
            cols={**u, "session_id": ref("session"), "checkout_id": ref("checkout"),
                  "lines": i16(), "subtotal": usd, "credit_applied": usd})
    p.event("checkout_failed", owner="user", cols={
        **u, "checkout_id": ref("checkout"), "reason": cat("out_of_stock", "payment_declined"),
        "sku_id": opt(ref("sku"))})
    p.event("payment_authorized", owner="user", cols={
        **u, "checkout_id": ref("checkout"), "amount": usd,
        "method": cat("card", "wallet", "bnpl")})
    p.event("payment_failed", owner="user", cols={
        **u, "checkout_id": ref("checkout"), "amount": usd,
        "decline_code": cat("insufficient_funds", "do_not_honor", "expired_card",
                            "fraud_suspected")})
    p.event("order_placed", owner="user", doc="Stock committed and payment authorized", cols={
        **u, "order_id": ref("order"), "checkout_id": ref("checkout"),
        "device_id": ref("device"), "sku_id": ref("sku"), "lines": i16(), "amount": usd,
        "credit_used": usd, "category": cat(*CATEGORIES)})          # largest line
    p.event("referral_bonus_paid", owner="user", cols={
        **u, "invitee_id": ref("user"), "role": cat("inviter", "invitee"), "amount": usd})
    p.event("referral_bonus_rejected", owner="user", cols={
        **u, "reason": cat("budget_exhausted")})
    o = {"user_id": ref("user"), "order_id": ref("order")}
    p.event("order_shipped", owner="order", cols={**o, "carrier": cat(*CARRIERS)})
    p.event("order_delivered", owner="order", cols={**o, "category": cat(*CATEGORIES)})
    p.event("order_lost", owner="order", cols=o)
    p.event("return_requested", owner="order", cols={**o, "reason": cat(*RETURN_REASONS)})
    p.event("refund_issued", owner="order", cols={**o, "amount": usd})
    stock = {"sku_group": i16(), "sku_id": ref("sku"), "checkout_id": ref("checkout")}
    p.event("stock_reserved", shard="inventory", cols={**stock, "hold_id": ref("hold"),
                                                       "quantity": i16()})
    p.event("stock_rejected", shard="inventory", cols={
        **stock, "quantity": i16(), "reason": cat("out_of_stock", "busy")})
    p.event("stock_committed", shard="inventory", cols={
        **stock, "hold_id": ref("hold"), "quantity": i16(), "on_hand_after": i32()})
    for name in ("stock_released", "stock_expired", "stock_commit_late"):
        p.event(name, shard="inventory", cols={**stock, "hold_id": ref("hold"),
                                               "quantity": i16()})
    p.event("restocked", shard="inventory", doc="Supplier delivery to an inventory group", cols={
        "sku_group": i16(), "sku_id": ref("sku"), "quantity": i32(min=1), "on_hand_after": i32()})
    p.event("bonus_granted", shard="referral_pool", cols={
        "claim_id": ref("claim"), "amount": usd, "remaining_after": i64()})
    p.event("bonus_rejected", shard="referral_pool", cols={"claim_id": ref("claim"),
                                                           "amount": usd})
    # ---------------------------------------------------------------- processes
    p.process("shopper", owner="user", kernel=k.shopper, config=cfg,
              start=p.on_created("user"),
              requests={"reserve": reserve, "claim": claim},
              messages={"commit": commit, "release": release, "inviter_credit": inviter_credit},
              on_response={("reserve", "granted"): k.R_GRANTED,
                           ("reserve", "rejected"): k.R_REJECTED,
                           ("claim", "granted"): k.R_BONUS, ("claim", "rejected"): k.R_NO_BONUS},
              on_message={"inviter_credit": k.M_CREDIT},
              reads={"sku": sku, "device": device}, refs={"device": "device"},
              commands=k.SHOPPER_COMMANDS)
    p.process("inventory_desk", shard=inventory, kernel=k.inventory_desk, config=cfg.desk,
              on_request={"reserve": k.C_RESERVE},
              on_message={"commit": k.C_COMMIT, "release": k.C_RELEASE},
              reads={"sku": sku}, commands=k.DESK_COMMANDS)
    p.process("restock", shard=inventory, kernel=k.restock, every=cfg.restock_period,
              jitter=dist.normal(mean_h=0, sd_h=18), reads={"sku": sku})
    p.process("pool_desk", shard=pool, kernel=k.pool_desk,
              config=PoolCfg(budget=r.monthly_budget, period_us=period_us),
              on_request={"claim": k.C_CLAIM})
    # ---------------------------------------------------------------- fulfillment (a machine)
    fc = cfg.fulfil
    f = p.machine("fulfillment", owner="order", start=p.on_created("order"), initial="placed",
                  config=fc)
    f.state("placed", branch={
        "shipped": (fc.ship_p, dist.gamma(mean_days=1.8, shape=2.0), k.ship),
        "lost": (None, dist.gamma(mean_days=14, shape=4.0), k.lose)})
    f.state("shipped", branch={
        "delivered": (1.0, dist.gamma(mean_days=3.6, shape=3.0), k.deliver)})
    f.state("delivered", branch={
        "returning": (std.p_by("category", {"apparel": fc.return_apparel_p,
                                            "shoes": fc.return_shoes_p},
                               otherwise=fc.return_p),
                      dist.gamma(mean_days=9, shape=1.6, max_days=30), k.request_return),
        "kept": (None, None, None)})
    f.state("returning", branch={
        "returned": (1.0, dist.gamma(mean_days=6, shape=2.5), k.refund_return)})
    f.final("kept", "returned", "lost")
    # ---------------------------------------------------------------- laws (§11)
    p.check("chk.stock_never_negative", law.never_negative("inventory.on_hand"), required=True)
    p.check("chk.reserved_never_negative", law.never_negative("inventory.reserved"),
            required=True)
    p.check("chk.holds_resolved", law.resolved(
        "stock_reserved", by=("stock_committed", "stock_released", "stock_expired"),
        key="hold_id", within=f"{cfg.desk.hold_ttl_s + HOLD_SLACK_S}s"), required=True)
    p.check("chk.refund_le_paid",
            law.sum_le("refund_issued.amount", "order.amount", by="order_id"), required=True)
    p.check("chk.order_lifecycle", law.lifecycle("order_id", edges={
        "order_placed": ("order_shipped", "order_lost"),
        "order_shipped": ("order_delivered",),
        "order_delivered": ("return_requested",),
        "return_requested": ("refund_issued",)}), required=True)
    p.check("chk.referral_once_per_invitee",
            law.at_most_once("referral_bonus_paid", key=("invitee_id", "role")), required=True)
    p.check("chk.referral_budget",
            law.total_le("bonus_granted.amount", r.monthly_budget, per=r.period), required=True)
    p.check("chk.credit_never_negative", law.never_negative("user.credit"), required=True)
    p.check("chk.hold_never_negative", law.never_negative("user.held"), required=True)
    p.check("chk.pool_never_negative", law.never_negative("referral_pool.remaining"),
            required=True)
    # ---------------------------------------------------------------- extension points (§08)
    p.expose(signup=k.signup, signup_invited=k.signup_invited, quick_order=k.quick_order,
             pay_referral=k.pay_referral,
             claim_bonus=std.request("claim", claim_id=std.new_id("claim"),
                                     amount=2 * r.bonus_each, store={"amount": "paid"}))
    p.expose_param("referral.min_order", r.min_order)
```

- [ ] **Step 2: Write `examples/ecommerce/specs/kernels.py`**

```python
"""Handwritten kernels and machine actions of the ecommerce pack.

Kernels: validate (draws allowed, no writes) -> out.reserve(...) -> commit. Actions (@action)
never reserve: the calling machine reserves their max (D65). Each draw site is used once per
process. Exposed actions (signup, signup_invited, quick_order, pay_referral) never read `s`, so
overlay cohorts can run them for member rows (D74).
"""

from neorisk_simkit import std
from neorisk_simkit.engine import (COMMIT, PRIO_TIMER, RETRY, START, Local, Res, action,
                                   kernel, reject)

CART = 5                                  # cart lines (Local array width)
HOLD_SLOTS = 64                           # holds per inventory shard
N_REGIONS = 50
C_SESSION, C_VIEW, C_CHECKOUT, R_GRANTED, R_REJECTED, C_AUTH = 1, 2, 3, 4, 5, 6
R_BONUS, R_NO_BONUS, C_MOVE, M_CREDIT = 7, 8, 9, 10
SHOPPER_COMMANDS = (START, C_SESSION, C_VIEW, C_CHECKOUT, R_GRANTED, R_REJECTED, C_AUTH,
                    R_BONUS, R_NO_BONUS, C_MOVE, M_CREDIT)
C_RESERVE, C_COMMIT, C_RELEASE, C_HOLD_EXPIRE = 1, 2, 3, 4
DESK_COMMANDS = (C_RESERVE, C_COMMIT, C_RELEASE, C_HOLD_EXPIRE)
C_CLAIM = 1
REJ_NO_CART, REJ_STALE, REJ_NOTHING_TO_REFUND = 1, 2, 3
WHY_STOCK, WHY_BUSY = 0, 1

SHOPPER_LOCAL = Local(session="ref", device="ref", views_left="i16", cart_n="i8",
                      cart_sku="ref[5]", cart_qty="i16[5]", cart_price="i64[5]",
                      checkout="ref", subtotal="i64", hold="i64", pending="i8", granted="u8",
                      rejected_sku="ref", holds="ref[5]", slot="i32[5]", ordered="u8")
DESK_LOCAL = Local(**std.reservations.fields(HOLD_SLOTS))


# ================================================================== shopper
@kernel(state="user", local=SHOPPER_LOCAL, commands=SHOPPER_COMMANDS,
        max=Res(records={"user_signed_up": 1, "session_started": 1, "product_viewed": 1,
                         "cart_item_added": 1, "checkout_started": 1, "checkout_failed": 1,
                         "payment_authorized": 1, "payment_failed": 1, "order_placed": 1,
                         "referral_bonus_paid": 1, "referral_bonus_rejected": 1, "address": 1},
                creates={"session": 1, "checkout": 1, "order": 1, "claim": 1}, timers=2,
                requests=CART + 1))
def shopper(ctx, s, loc, cmd, out):
    cfg = ctx.cfg
    if cmd.kind == START:
        return _signup(ctx, s, out, cfg)
    if cmd.kind == C_SESSION:
        return _session(ctx, loc, out, cfg)
    if cmd.kind == C_VIEW:
        return _view(ctx, loc, out, cfg)
    if cmd.kind == C_CHECKOUT:
        return _checkout(ctx, s, loc, out, cfg)
    if cmd.kind == C_AUTH:
        return _auth(ctx, s, loc, cmd, out, cfg)
    if cmd.kind == R_BONUS or cmd.kind == R_NO_BONUS:
        return _bonus(ctx, s, cmd, out)
    if cmd.kind == C_MOVE:
        return _move(ctx, out, cfg)
    if cmd.kind == M_CREDIT:
        return _credit(ctx, s, cmd, out)
    return _answer(ctx, s, loc, cmd, out, cfg)


def _signup(ctx, s, out, cfg):
    delay = ctx.rng.dist_us(site=1, d=cfg.journey.signup_delay)
    move = ctx.rng.dist_us(site=2, d=cfg.journey.move_gap)
    if not out.reserve(records={"user_signed_up": 1}, timers=2):
        return RETRY
    inviter = std.NULL
    if s.referred:
        s.acquisition = "invite"
        inviter = s.invited_by
    out.emit_user_signed_up(ctx.t, user_id=ctx.self_id,
                            device_id=ctx.refs.device.get(ctx.self_id, 0),
                            acquisition=s.acquisition, referred=s.referred, invited_by=inviter)
    out.timer(ctx.t + delay, C_SESSION, prio=PRIO_TIMER)
    out.timer(ctx.t + move, C_MOVE, prio=PRIO_TIMER)
    return COMMIT


def _channel(ctx, device):
    if ctx.reads.device.kind[device] == "desktop":
        return 0                                           # web
    return 1                                               # app


def _session(ctx, loc, out, cfg):
    j = cfg.journey
    n_dev = ctx.refs.device.count(ctx.self_id)
    dev = ctx.refs.device.get(ctx.self_id, ctx.rng.uniform_int(site=3, lo=0, hi=n_dev - 1))
    views = min(ctx.rng.geometric(site=4, mean=j.views_mean), 30)
    gap = ctx.rng.pareto_us(site=5, alpha=j.session_gap_alpha, min_h=j.session_gap_min_h)
    first = ctx.rng.dist_us(site=6, d=j.view_gap)
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
    j = cfg.journey
    if loc.views_left <= 0:                                # session over: maybe check out
        if loc.cart_n == 0 or loc.checkout != std.NULL:
            return reject(REJ_NO_CART)
        if not ctx.rng.bernoulli(site=10, p=j.checkout_p):
            return reject(REJ_NO_CART)
        delay = ctx.rng.dist_us(site=11, d=j.checkout_delay)
        if not out.reserve(timers=1):
            return RETRY
        out.timer(ctx.t + delay, C_CHECKOUT, prio=PRIO_TIMER)
        return COMMIT
    sku = ctx.reads.sku.sample_by_weight(ctx.rng.uniform(site=12))
    add = ctx.rng.bernoulli(site=13, p=j.add_to_cart_p)
    qty = 1 + ctx.rng.geometric(site=14, mean=0.25)
    pos = ctx.rng.geometric(site=15, mean=5.0)
    nxt = ctx.rng.dist_us(site=16, d=j.view_gap)
    if not out.reserve(records={"product_viewed": 1, "cart_item_added": 1}, timers=1):
        return RETRY
    price = ctx.reads.sku.price[sku]
    out.emit_product_viewed(ctx.t, user_id=ctx.self_id, session_id=loc.session, sku_id=sku,
                            device_id=loc.device, position=pos,
                            category=ctx.reads.sku.category[sku], price=price)
    if add and loc.checkout == std.NULL and loc.cart_n < CART:
        n = loc.cart_n
        loc.cart_sku[n] = sku
        loc.cart_qty[n] = qty
        loc.cart_price[n] = price
        loc.cart_n = n + 1
        out.emit_cart_item_added(ctx.t, user_id=ctx.self_id, session_id=loc.session,
                                 sku_id=sku, quantity=qty, unit_price=price)
    loc.views_left -= 1
    out.timer(ctx.t + nxt, C_VIEW, prio=PRIO_TIMER)
    return COMMIT


def _checkout(ctx, s, loc, out, cfg):
    """Hold credit on the owner, then reserve every line in its inventory shard (§07)."""
    if loc.cart_n == 0 or loc.checkout != std.NULL:
        return reject(REJ_NO_CART)
    use = ctx.rng.bernoulli(site=20, p=cfg.journey.credit_use_p)
    total = 0
    for i in range(loc.cart_n):
        total = std.checked_add(total, std.checked_mul(loc.cart_price[i], loc.cart_qty[i]))
    if not out.reserve(records={"checkout_started": 1}, creates={"checkout": 1}, requests=CART):
        return RETRY
    hold = 0
    if use:
        hold = std.checked_min(s.credit - s.held, total)
    s.held = std.checked_add(s.held, hold)
    loc.checkout = out.new_id("checkout")
    loc.subtotal = total
    loc.hold = hold
    loc.pending = loc.cart_n
    loc.granted = 0
    loc.rejected_sku = std.NULL
    out.emit_checkout_started(ctx.t, user_id=ctx.self_id, session_id=loc.session,
                              checkout_id=loc.checkout, lines=loc.cart_n, subtotal=total,
                              credit_applied=hold)
    for i in range(loc.cart_n):                            # one immutable request per line
        out.request_reserve(ctx.t, shard=ctx.reads.sku.sku_group[loc.cart_sku[i]],
                            tag=loc.checkout, sku_id=loc.cart_sku[i], quantity=loc.cart_qty[i],
                            line=i)
    return COMMIT                                          # suspends: join of cart_n answers


def _release_all(ctx, s, loc, out):
    for i in range(loc.cart_n):
        if loc.granted & (1 << i):
            out.send_release(ctx.t, to=ctx.reads.sku.sku_group[loc.cart_sku[i]],
                             tag=loc.checkout, sku_id=loc.cart_sku[i], quantity=loc.cart_qty[i],
                             hold_id=loc.holds[i], slot=loc.slot[i])
    s.held = std.checked_sub(s.held, loc.hold)


def _clear(loc):
    loc.checkout = std.NULL
    loc.cart_n = 0
    loc.pending = 0
    loc.granted = 0
    loc.hold = 0


def _answer(ctx, s, loc, cmd, out, cfg):
    if cmd.tag != loc.checkout or loc.pending <= 0:
        return reject(REJ_STALE)
    j = cfg.journey
    substitute = ctx.rng.bernoulli(site=21, p=j.substitute_p)
    more = ctx.rng.geometric(site=22, mean=3.0)
    nxt = ctx.rng.dist_us(site=23, d=j.view_gap)
    auth = ctx.rng.dist_us(site=24, d=j.auth_latency)
    if not out.reserve(records={"checkout_failed": 1}, timers=1, requests=CART):
        return RETRY
    line = cmd.line
    if cmd.kind == R_GRANTED:
        loc.granted |= 1 << line
        loc.holds[line] = cmd.hold_id
        loc.slot[line] = cmd.slot
    else:
        loc.rejected_sku = loc.cart_sku[line]
    loc.pending -= 1
    if loc.pending > 0:
        return COMMIT                                      # join: wait for the other lines
    if loc.granted == (1 << loc.cart_n) - 1:               # every line held: authorize
        out.timer(ctx.t + auth, C_AUTH, prio=PRIO_TIMER, tag=loc.checkout)
        return COMMIT
    _release_all(ctx, s, loc, out)
    out.emit_checkout_failed(ctx.t, user_id=ctx.self_id, checkout_id=loc.checkout,
                             reason="out_of_stock", sku_id=loc.rejected_sku)
    if substitute:
        loc.views_left = more
        out.timer(ctx.t + nxt, C_VIEW, prio=PRIO_TIMER)
    _clear(loc)
    return COMMIT


def _largest(loc):
    best, value = 0, -1
    for i in range(loc.cart_n):
        v = loc.cart_price[i] * loc.cart_qty[i]
        if v > value:
            best, value = i, v
    return best


def _auth(ctx, s, loc, cmd, out, cfg):
    if cmd.tag != loc.checkout or loc.checkout == std.NULL or loc.pending != 0:
        return reject(REJ_STALE)
    r = cfg.referral
    fail = ctx.rng.bernoulli(site=30, p=cfg.journey.auth_fail_p)
    code = ctx.rng.categorical(site=31, p=(0.45, 0.3, 0.15, 0.1))
    method = ctx.rng.categorical(site=32, p=(0.7, 0.22, 0.08))
    if not out.reserve(records={"payment_authorized": 1, "payment_failed": 1,
                                "order_placed": 1, "checkout_failed": 1},
                       creates={"order": 1, "claim": 1}, requests=CART + 1):
        return RETRY
    charge = loc.subtotal - loc.hold
    if fail:
        out.emit_payment_failed(ctx.t, user_id=ctx.self_id, checkout_id=loc.checkout,
                                amount=charge, decline_code=code)
        _release_all(ctx, s, loc, out)
        out.emit_checkout_failed(ctx.t, user_id=ctx.self_id, checkout_id=loc.checkout,
                                 reason="payment_declined", sku_id=std.NULL)
        _clear(loc)
        return COMMIT
    out.emit_payment_authorized(ctx.t, user_id=ctx.self_id, checkout_id=loc.checkout,
                                amount=charge, method=method)
    for i in range(loc.cart_n):                            # commit every reservation
        out.send_commit(ctx.t, to=ctx.reads.sku.sku_group[loc.cart_sku[i]], tag=loc.checkout,
                        sku_id=loc.cart_sku[i], quantity=loc.cart_qty[i], hold_id=loc.holds[i],
                        slot=loc.slot[i])
    s.credit = std.checked_sub(s.credit, loc.hold)          # the owner commits its hold
    s.held = std.checked_sub(s.held, loc.hold)
    big = loc.cart_sku[_largest(loc)]
    category = ctx.reads.sku.category[big]
    order = out.create_order(user_id=ctx.self_id, amount=loc.subtotal, lines=loc.cart_n,
                             category=category, credit_used=loc.hold, refunded=0,
                             status="placed")
    out.emit_order_placed(ctx.t, user_id=ctx.self_id, order_id=order, checkout_id=loc.checkout,
                          device_id=loc.device, sku_id=big, lines=loc.cart_n,
                          amount=loc.subtotal, credit_used=loc.hold, category=category)
    if loc.ordered == 0:                                   # a referral's first order
        loc.ordered = 1
        if s.referred and loc.subtotal >= r.min_order:
            out.request_claim(ctx.t, shard=0, claim_id=out.new_id("claim"),
                              amount=2 * r.bonus_each)
    _clear(loc)
    return COMMIT


def _bonus(ctx, s, cmd, out):
    if not out.reserve(records={"referral_bonus_paid": 1, "referral_bonus_rejected": 1},
                       requests=1):
        return RETRY
    if cmd.kind == R_BONUS:
        half = cmd.amount // 2
        s.credit = std.checked_add(s.credit, half)
        out.emit_referral_bonus_paid(ctx.t, user_id=ctx.self_id, invitee_id=ctx.self_id,
                                     role="invitee", amount=half)
        if s.invited_by != std.NULL:                       # owner-to-owner, a day later (D73)
            out.send_inviter_credit(ctx.t, to=s.invited_by, invitee=ctx.self_id,
                                    amount=cmd.amount - half)
    else:
        out.emit_referral_bonus_rejected(ctx.t, user_id=ctx.self_id, reason="budget_exhausted")
    return COMMIT


def _credit(ctx, s, cmd, out):
    if not out.reserve(records={"referral_bonus_paid": 1}):
        return RETRY
    s.credit = std.checked_add(s.credit, cmd.amount)
    out.emit_referral_bonus_paid(ctx.t, user_id=ctx.self_id, invitee_id=cmd.invitee,
                                 role="inviter", amount=cmd.amount)
    return COMMIT


def _move(ctx, out, cfg):
    region = ctx.rng.uniform_int(site=40, lo=0, hi=N_REGIONS - 1)
    nxt = ctx.rng.dist_us(site=41, d=cfg.journey.move_gap)
    if not out.reserve(records={"address": 1}, timers=1):
        return RETRY
    out.change_address(ctx.t, region=region)
    out.timer(ctx.t + nxt, C_MOVE, prio=PRIO_TIMER)
    return COMMIT


# ================================================================== inventory (S2 desk, D49)
@kernel(state="inventory", local=DESK_LOCAL, commands=DESK_COMMANDS,
        max=Res(records={"stock_reserved": 1, "stock_rejected": 1, "stock_committed": 1,
                         "stock_released": 1, "stock_expired": 1, "stock_commit_late": 1},
                creates={"hold": 1}, timers=1, requests=1))
def inventory_desk(ctx, s, loc, cmd, out):
    if cmd.kind == C_RESERVE:
        return _reserve(ctx, s, loc, cmd, out)
    if cmd.kind == C_HOLD_EXPIRE:
        return _expire(ctx, s, loc, cmd, out)
    return _settle_hold(ctx, s, loc, cmd, out)
```
Then copy `_reserve`, `_settle_hold`, `_expire` and `restock` **verbatim** from `examples/ecommerce_s2/specs/kernels.py` (lines `def _reserve` … end of `restock`), and add:

```python
# ================================================================== referral pool
@kernel(state="referral_pool", commands=(C_CLAIM,),
        max=Res(records={"bonus_granted": 1, "bonus_rejected": 1}, requests=1))
def pool_desk(ctx, s, cmd, out):
    """Claims are whole or rejected; the budget resets lazily on the first claim of a new
    period window (`ctx.t // period`, epoch-aligned like law.total_le(per=), D91)."""
    if not out.reserve(records={"bonus_granted": 1, "bonus_rejected": 1}, requests=1):
        return RETRY
    w = ctx.t // ctx.cfg.period_us
    if w != s.window:
        s.window = w
        s.remaining = ctx.cfg.budget
    g = std.capped_pool.take(s.remaining, cmd.amount)
    if g > 0:
        s.remaining = std.checked_sub(s.remaining, g)
        s.granted = std.checked_add(s.granted, g)
        out.emit_bonus_granted(ctx.t, claim_id=cmd.claim_id, amount=g,
                               remaining_after=s.remaining)
        out.respond(cmd, "granted", amount=g)
    else:
        out.emit_bonus_rejected(ctx.t, claim_id=cmd.claim_id, amount=cmd.amount)
        out.respond(cmd, "rejected", amount=0)
    return COMMIT


# ================================================================== fulfillment actions
@action(state="order", max=Res(records={"order_shipped": 1}))
def ship(ctx, s, m, cmd, out):
    s.status = "shipped"
    out.emit_order_shipped(ctx.t, user_id=s.user_id, order_id=m.id,
                           carrier=ctx.rng.categorical(site=1, p=(0.4, 0.3, 0.2, 0.1)))
    return COMMIT


@action(state="order", max=Res(records={"order_delivered": 1}))
def deliver(ctx, s, m, cmd, out):
    s.status = "delivered"
    out.emit_order_delivered(ctx.t, user_id=s.user_id, order_id=m.id, category=s.category)
    return COMMIT


@action(state="order", max=Res(records={"order_lost": 1}))
def lose(ctx, s, m, cmd, out):
    s.status = "lost"
    out.emit_order_lost(ctx.t, user_id=s.user_id, order_id=m.id)
    return COMMIT


@action(state="order", max=Res(records={"return_requested": 1}))
def request_return(ctx, s, m, cmd, out):
    out.emit_return_requested(ctx.t, user_id=s.user_id, order_id=m.id,
                              reason=ctx.rng.categorical(site=1, p=(0.3, 0.15, 0.2, 0.3, 0.05)))
    return COMMIT


@action(state="order", max=Res(records={"refund_issued": 1}))
def refund_return(ctx, s, m, cmd, out):
    left = s.amount - s.refunded
    if left <= 0:
        return reject(REJ_NOTHING_TO_REFUND)
    s.refunded = std.checked_add(s.refunded, left)
    s.status = "returned"
    out.emit_refund_issued(ctx.t, user_id=s.user_id, order_id=m.id, amount=left)
    return COMMIT


# ================================================================== exposed to overlays (§08)
@action(state="user", max=Res(records={"user_signed_up": 1}), fields={"device": "ref"})
def signup(ctx, s, m, cmd, out):
    out.emit_user_signed_up(ctx.t, user_id=m.id, device_id=m.device, acquisition="social_ad",
                            referred=0, invited_by=std.NULL)
    return COMMIT


@action(state="user", max=Res(records={"user_signed_up": 1}), fields={"device": "ref"})
def signup_invited(ctx, s, m, cmd, out):
    out.emit_user_signed_up(ctx.t, user_id=m.id, device_id=m.device, acquisition="invite",
                            referred=1, invited_by=m.parent_id)
    return COMMIT


@action(state="user", max=Res(records={"order_placed": 1}, creates={"order": 1, "checkout": 1}),
        fields={"device": "ref", "amount": "i64"})
def quick_order(ctx, s, m, cmd, out):
    """A one-line order of `m.amount` without a cart or stock reservation (the order still
    runs the fulfillment machine)."""
    sku = ctx.reads.sku.sample_by_weight(ctx.rng.uniform(site=1))
    category = ctx.reads.sku.category[sku]
    order = out.create_order(user_id=m.id, amount=m.amount, lines=1, category=category,
                             credit_used=0, refunded=0, status="placed")
    out.emit_order_placed(ctx.t, user_id=m.id, order_id=order,
                          checkout_id=out.new_id("checkout"), device_id=m.device, sku_id=sku,
                          lines=1, amount=m.amount, credit_used=0, category=category)
    return COMMIT


@action(state="user", max=Res(records={"referral_bonus_paid": 2}), fields={"paid": "i64"})
def pay_referral(ctx, s, m, cmd, out):
    """Both halves of a granted referral claim: the invitee and its inviter (the parent)."""
    half = m.paid // 2
    out.emit_referral_bonus_paid(ctx.t, user_id=m.id, invitee_id=m.id, role="invitee",
                                 amount=half)
    out.emit_referral_bonus_paid(ctx.t, user_id=m.parent_id, invitee_id=m.id, role="inviter",
                                 amount=m.paid - half)
    return COMMIT
```
(Fulfillment actions run in machine `fulfillment` on `order`, where `ctx.cfg` is `Fulfil`; they read no config. Two actions use `site=1` — each action copy gets its own site block (D65), so that is legal. `quick_order` reads `ctx.reads.sku`: an overlay machine calling it declares `reads={"sku": "sku"}`.)

- [ ] **Step 3: Write `examples/ecommerce/datagen.toml`**

```toml
# datagen project file. Paths are relative to this file.
# `datagen run examples/ecommerce --profile <name>` merges [defaults] <- [profiles.<name>] <- --set.

[project]
name = "ecommerce"
pack = "specs/pack.py"
expectations = "specs/expectations.yaml"
overlays = "specs/overlays"

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
max_admissions_per_step = 500_000
max_checker_keys = 20_000_000

[writer]                               # pinned: affects bytes
compression = "zstd"
compression_level = 3
row_group_rows = 131_072

[engine]
step = "1d"
step_min = "1h"
step_max = "1d"                        # inviter_credit needs latency >= step_max (D73)
adapt = true
slab_bytes = "4MB"
timer_nodes = 20_000_000
payload_slots = 2_000_000
max_messages_per_step = 4_000_000
parallel_min_partitions = 2_048

[profiles.sample]                      # the authoring loop: minutes, not hours
span = "21d"
warmup = "3d"

[profiles.sample.set]
users = 20_000
skus = 5_000
sku_groups = 64
"engine.timer_nodes" = 2_000_000
"engine.payload_slots" = 200_000
"engine.max_messages_per_step" = 500_000
"budget.max_admissions_per_step" = 100_000
"budget.max_checker_keys" = 2_000_000

[profiles.legacy]                      # the fraud-benchmark dataset (Task 20, D87/D88)
span = "60d"
warmup = "7d"
overlays = ["bounty_hunters"]

[profiles.legacy.set]
users = 5_000
skus = 2_000
sku_groups = 16
"engine.timer_nodes" = 600_000
"engine.payload_slots" = 100_000
"engine.max_messages_per_step" = 300_000
"budget.max_admissions_per_step" = 50_000
"budget.max_checker_keys" = 1_000_000

[profiles.legacy.overlay.bounty_hunters]
size = 12

[profiles.full]                        # 2M users, 90 days
[profiles.full.set]
users = 2_000_000
skus = 50_000
sku_groups = 512

[profiles.abuse]                       # base + bounty hunters at scale
overlays = ["bounty_hunters"]

[profiles.abuse.set]
users = 2_000_000

[profiles.abuse.overlay.bounty_hunters]
size = 500

[replay.presets.peek]
first = 100
sink = "stdout:?format=table"

[replay.presets.last_json]
last = 100
sink = "file:last100.json?format=json-array"
```
(`[export]` and the kafka preset are gone: `p.feature`/`golden/` is deferred (see Deferred) and the Kafka sink is M4.)

- [ ] **Step 4: Write the failing tests**

`apps/datagen/tests/test_example_ecom.py`:
```python
"""examples/ecommerce: the real pack runs; carts, holds, orders, fulfillment and laws (D91)."""

import json
from pathlib import Path

import polars as pl
import pytest

from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events
from neorisk_simkit.spec.project import load_project, resolve_run
from neorisk_simkit.spec.validate import validate

EX = Path(__file__).resolve().parents[3] / "examples" / "ecommerce"
POOLS = ["engine.timer_nodes=600_000", "engine.payload_slots=100_000",
         "engine.max_messages_per_step=300_000", "budget.max_admissions_per_step=50_000",
         "budget.max_checker_keys=1_000_000"]
SMALL = ["users=3000", "skus=1200", "sku_groups=8", "run.span=14d", "run.warmup=1d", *POOLS]


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    return run_to_dataset(EX, "sample", SMALL, out_dir=tmp_path_factory.mktemp("ecom") / "run",
                          threads=4)


@pytest.fixture(scope="module")
def ev(run):
    return read_events(run.out_dir)


def test_base_profiles_validate():
    for profile in ("sample", "full"):
        rep = validate(resolve_run(load_project(EX), profile, []))
        assert rep.ok, (profile, rep.errors)


def test_carts_have_several_lines_and_every_line_is_decided(ev):
    started = ev["checkout_started"]
    assert started["lines"].max() >= 3 and started.height > 100
    decided = pl.concat([ev["stock_reserved"].select("checkout_id"),
                         ev["stock_rejected"].select("checkout_id")]).group_by("checkout_id").len()
    j = started.select("checkout_id", "lines").join(decided, on="checkout_id")
    assert j.height == started.height and (j["len"] == j["lines"].cast(pl.UInt32)).all()


def test_orders_commit_every_hold_and_failures_release_them(ev):
    holds = ev["stock_reserved"].select("checkout_id", "hold_id")
    fate = pl.concat([ev[n].select("hold_id", pl.lit(n).alias("fate"))
                      for n in ("stock_committed", "stock_released", "stock_expired")])
    j = holds.join(fate, on="hold_id")
    placed = set(ev["order_placed"]["checkout_id"])
    ok = j.filter(pl.col("checkout_id").is_in(list(placed)))
    assert ok.height > 0 and (ok["fate"] == "stock_committed").all()
    bad = j.filter(~pl.col("checkout_id").is_in(list(placed)))
    assert (bad["fate"] != "stock_committed").all()


def test_each_order_is_a_created_owner_running_fulfillment(run, ev):
    orders = pl.read_parquet(run.out_dir / "entities" / "order")
    assert orders.height == ev["order_placed"].height > 50
    shipped = set(ev["order_shipped"]["order_id"]) | set(ev["order_lost"]["order_id"])
    assert shipped <= set(orders["id"])
    st = json.loads((run.out_dir / "run_stats.json").read_text())["machines"]["fulfillment"]
    assert st["entries"]["placed"] == orders.height
    assert st["entries"]["shipped"] == ev["order_shipped"].height


def test_required_laws_were_checked(run):
    laws = run.manifest["laws"]
    for cid in ("chk.order_lifecycle", "chk.refund_le_paid", "chk.holds_resolved",
                "chk.credit_never_negative"):
        assert laws[cid]["checked"] > 0 and laws[cid]["violations"] == 0, cid


def test_addresses_change_slowly(run):
    hist = pl.read_parquet(sorted((run.out_dir / "history" / "address").rglob("*.parquet")))
    assert hist.height > 0
    per = hist.group_by("entity_id").len()
    assert per["len"].max() <= 3                        # ~ every 45 days over 15 days
```

- [ ] **Step 5: Run the tests**

Run (cold compile 45–90 min: run it in the background and wait): `uv run --all-packages pytest apps/datagen/tests/test_example_ecom.py -q`
Expected after the implementation of Steps 1–3: PASS. A failure inside generated machine code or the engine is a defect of Tasks 1–13: stop, report it, and fix it in the owning module with a regression test there (an engine edit recompiles everything: batch fixes).

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check $(ls -d libs apps examples/ecommerce_s1 examples/ecommerce_s2 examples/ecommerce benchmarks 2>/dev/null)
git rm examples/ecommerce/specs/overlays/flash_sale.py examples/ecommerce/specs/overlays/bounty_hunters.py
git add examples/ecommerce/specs/pack.py examples/ecommerce/specs/kernels.py \
  examples/ecommerce/datagen.toml apps/datagen/tests/test_example_ecom.py
git commit -m "feat(examples): ecommerce pack on the real API; fulfillment as a machine (D91)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```
(Add `examples/ecommerce/{out,reports,logs}/.gitkeep` to the `git add` line if you created them.)

---

### Task 15: `examples/ecommerce` II — referrals, owner-to-owner credit, extension points, expectations, docs

No kernel edits (Task 14 wrote them; an edit here would recompile the module): this task pins the referral flow, the owner-to-owner inviter credit and the exposed extension points with tests, and writes `expectations.yaml`, the README and the authoring guide.

**Files:**
- Rewrite: `examples/ecommerce/specs/expectations.yaml`, `examples/ecommerce/README.md`
- Modify: `examples/ecommerce/specs/brief.md` (only the "Abuse" paragraph: drop the flash sale, which is deferred, D93 — say so in one sentence), `examples/AGENTS.md` (machines, actions, overlays as they really are), `examples/README.md` (ecommerce row: "M3 pack; legacy fraud dataset via `datagen export --legacy-fraud`")
- Test: `apps/datagen/tests/test_example_ecom_referral.py`

**Interfaces:**
- Consumes: Task 14's pack; Task 2 (D73), Task 13 (`total_le(per=)`).
- Produces: `expectations.yaml` in the D84 grammar (Task 18 parses it, Task 22 calibrates against it): ids `exp.session_to_checkout`, `exp.checkout_to_order`, `exp.auth_failure_rate`, `exp.return_rate`, `exp.return_rate_apparel`, `exp.orders_per_shopper`, `exp.oos_failures`, `exp.sku_view_concentration`, `exp.delivery_lag`, and under `overlays.bounty_hunters`: `exp.bh.campaigns`, `exp.bh.min_order_hugging`, `exp.bh.interference_reported`.

- [ ] **Step 1: Write the failing tests**

`apps/datagen/tests/test_example_ecom_referral.py`:
```python
"""Referral program: first qualifying orders claim once; the pool budget resets per period;
inviters are credited one day later by an owner-to-owner message (D73); extension points."""

from datetime import timedelta
from pathlib import Path

import polars as pl
import pytest

from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events
from neorisk_simkit.spec.project import load_project, resolve_run

EX = Path(__file__).resolve().parents[3] / "examples" / "ecommerce"
POOLS = ["engine.timer_nodes=600_000", "engine.payload_slots=100_000",
         "engine.max_messages_per_step=300_000", "budget.max_admissions_per_step=50_000",
         "budget.max_checker_keys=1_000_000"]
REF = ["users=3000", "skus=1200", "sku_groups=8", "run.span=21d", "run.warmup=0s",
       "referral.referred_share=0.3", "referral.inviter_share=0.1", "referral.min_order=1000",
       *POOLS]


def _run(tmp, extra=()):
    res = run_to_dataset(EX, "sample", [*REF, *extra], out_dir=tmp / "run", threads=4)
    return res, read_events(res.out_dir), pl.read_parquet(res.out_dir / "entities" / "user")


@pytest.fixture(scope="module")
def data(tmp_path_factory):
    return _run(tmp_path_factory.mktemp("ref"))


def test_qualifying_first_orders_claim_once(data):
    _res, ev, users = data
    referred = set(users.filter(pl.col("referred"))["id"])
    first = ev["order_placed"].sort("event_time", "lamport").group_by("user_id").first()
    want = set(first.filter((pl.col("amount") >= 1000)
                            & pl.col("user_id").is_in(list(referred)))["user_id"])
    paid = set(ev["referral_bonus_paid"].filter(pl.col("role") == "invitee")["user_id"])
    rejected = set(ev["referral_bonus_rejected"]["user_id"])
    assert paid | rejected <= want and len(paid | rejected) >= len(want) - 2
    assert not paid & rejected and len(paid) > 10


def test_inviters_are_credited_a_day_later_by_message(data):
    _res, ev, users = data
    rb = ev["referral_bonus_paid"]
    inv = rb.filter(pl.col("role") == "invitee").select(
        pl.col("user_id").alias("invitee_id"), pl.col("event_time").alias("t0"))
    cr = rb.filter(pl.col("role") == "inviter").select("invitee_id", "user_id", "event_time")
    j = cr.join(inv, on="invitee_id")
    assert j.height == cr.height > 0
    assert (j["event_time"] - j["t0"] >= timedelta(days=1)).all()
    inviter_of = users.select(pl.col("id").alias("invitee_id"),
                              pl.col("invited_by").alias("expected"))
    k = j.join(inviter_of, on="invitee_id")
    assert (k["user_id"] == k["expected"]).all()


def test_the_budget_resets_each_period(tmp_path):
    _res, ev, _u = _run(tmp_path, ["referral.monthly_budget=4000", "referral.period=2d"])
    g = ev["bonus_granted"].with_columns(
        (pl.col("event_time").cast(pl.Int64) // (2 * 86_400_000_000)).alias("w"))
    per = g.group_by("w").agg(pl.col("amount").sum())
    assert per["amount"].max() <= 4000 and per.height >= 2
    assert ev["bonus_rejected"].height > 0


def test_extension_points_are_exposed():
    plan = resolve_run(load_project(EX), "sample", []).plan
    assert set(plan.exposed) == {"signup", "signup_invited", "quick_order", "pay_referral",
                                 "claim_bonus"}
    assert plan.exposed_owners == ("user",)
```

- [ ] **Step 2: Run** — `uv run --all-packages pytest apps/datagen/tests/test_example_ecom_referral.py -q` (warm module from Task 14) → PASS. If a test fails because of the pack, fix `pack.py`/`kernels.py` (one recompile) and re-run Task 14's tests too.

- [ ] **Step 3: Write `examples/ecommerce/specs/expectations.yaml`**

```yaml
# Statistical expectations and laws for the ecommerce pack (D84).
# Every entry cites where its target comes from (`source:`); required entries fail CI when they
# fail, are missing, inconclusive or unanchored. Laws are declared in pack.py with p.check and
# listed here by id, so the report shows one table. Changes need a second reviewer.
pack: ecommerce
schema_version: 1

defaults:
  min_sample: 2000          # cases; fewer makes a metric inconclusive
  confidence: 0.95
  sample_rate: 1.0          # owner-hash sampling rate per stratum (raised to reach min_sample)

laws:
  - {id: chk.stock_never_negative,      required: true}
  - {id: chk.reserved_never_negative,   required: true}
  - {id: chk.holds_resolved,            required: true}
  - {id: chk.refund_le_paid,            required: true}
  - {id: chk.order_lifecycle,           required: true}
  - {id: chk.referral_once_per_invitee, required: true}
  - {id: chk.referral_budget,           required: true}
  - {id: chk.credit_never_negative,     required: true}
  - {id: chk.hold_never_negative,       required: true}
  - {id: chk.pool_never_negative,       required: true}

expectations:
  - id: exp.session_to_checkout
    metric: stat.funnel(start="session_started", step="checkout_started", unit="session_id")
    target: {between: [0.06, 0.10]}
    source: "brief: Rates we know, row 1"
    required: true
  - id: exp.checkout_to_order
    metric: stat.funnel(start="checkout_started", step="order_placed", unit="checkout_id")
    target: {between: [0.70, 0.85]}
    source: "brief: Rates we know, row 2"
    required: true
  - id: exp.auth_failure_rate
    metric: stat.share("payment_failed", of=["payment_authorized", "payment_failed"])
    target: {between: [0.02, 0.04]}
    source: "brief: Rates we know, row 3"
    required: true
  - id: exp.return_rate
    metric: stat.funnel(start="order_delivered", step="return_requested", unit="order_id", within="30d")
    target: {between: [0.05, 0.08]}
    source: "brief: Rates we know, row 4"
    required: true
  - id: exp.return_rate_apparel
    metric: stat.funnel(start="order_delivered", step="return_requested", unit="order_id", within="30d", where={"category": "apparel"})
    target: {between: [0.15, 0.20]}
    source: "brief: Rates we know, row 4"
  - id: exp.orders_per_shopper
    metric: stat.quantiles("order_placed", per="user_id")
    target: {p50: {between: [1, 1]}, p90: {between: [4, 6]}}
    source: "brief: Rates we know, row 5"
  - id: exp.oos_failures
    metric: stat.share("checkout_failed", of=["checkout_started"], where={"reason": "out_of_stock"})
    target: {between: [0.01, 0.03]}
    source: "brief: Rates we know, row 6"
    required: true
  - id: exp.sku_view_concentration
    metric: stat.top_share("product_viewed", by="sku_id", top=0.01)
    target: {between: [0.17, 0.23]}
    source: "brief: Catalog"
  - id: exp.delivery_lag
    metric: stat.distribution(between=["order_shipped", "order_delivered"], unit="order_id")
    target: {median_days: {between: [3, 4.5]}, p99_days: {lt: 14}}
    source: "brief: Flows 4"

overlays:                   # applied only when the overlay is enabled
  bounty_hunters:
    - id: exp.bh.campaigns
      metric: stat.cohort_size("campaign")
      target: {around: "${bounty_hunters.size}", tolerance: 0.0}
      source: "overlay config"
      required: true
    - id: exp.bh.min_order_hugging
      metric: stat.quantiles("order_placed.amount", cohort="campaign", role="zombie")
      target: {p50: {between: [3000, 3150]}}
      source: "brief: Abuse, bounty hunters (orders just above the $30 minimum)"
    - id: exp.bh.interference_reported
      metric: stat.interference(base="referral_bonus_paid", cause="referral_pool")
      target: {reported: true}
      source: "design §08: the overlay regression rule"
      required: true
```

- [ ] **Step 4: Docs**

`examples/ecommerce/README.md`: rewrite the Model table (partitions `user`, `order`, `inventory`, `referral_pool`; the `fulfillment` machine on `order`), the event list exactly as declared in `pack.py`, the Overlays table with only `bounty_hunters` (parameters `size`, `zombies_mean`, `share_device`, `arrive_day`, `arrive_span_days`, `qualify_timeout`, `order_above_min`, `zombie_order_p`) and a "Deferred" line for the flash sale (D93), and the Run block:
```bash
datagen validate examples/ecommerce
datagen run      examples/ecommerce --profile sample
datagen check    examples/ecommerce --profile sample            # -> reports/sample-s42/report.html
datagen run      examples/ecommerce --profile legacy            # 5k users + bounty_hunters
datagen export   examples/ecommerce/out/legacy-s42+bounty_hunters --legacy-fraud --out data/fraud
datagen validate examples/ecommerce --dump-machines /tmp/machines   # the generated machine code
datagen schema   examples/ecommerce --format sql --dialect postgres --with-fks
datagen replay   examples/ecommerce/out/sample-s42 --preset peek
```
`examples/AGENTS.md`: replace the machine/overlay bullets with the real vocabulary: `p.machine(...).state(branch=, timer=, repeat=, max_repeats=, until=, then=, join=, late=, request=, on_reject=, on_timeout=, timeout=, spawn=)` / `.final(...)`; `@action(state=, max=Res(...), fields=)` with `(ctx, s, m, cmd, out)`, no `out.reserve` inside; `std.emit/spawn/send_parent/label/request/create_owner/set_field/add_field`; values `std.actor/parent/col/field/new_id/now/after/near/pick_ref`; `std.cond.*`; `std.p_by`; overlays `o.cohort/o.machine/o.label/o.base/o.param`; base `p.expose/expose_param/expose_owner`; `datagen validate --dump-machines DIR`; `datagen check`.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check $(ls -d libs apps examples/ecommerce_s1 examples/ecommerce_s2 examples/ecommerce benchmarks 2>/dev/null)
git add examples/ecommerce/specs/expectations.yaml examples/ecommerce/README.md \
  examples/ecommerce/specs/brief.md examples/AGENTS.md examples/README.md \
  apps/datagen/tests/test_example_ecom_referral.py
git commit -m "feat(examples): ecommerce referrals, inviter credit by message, expectations (D73, D84)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 16: The `bounty_hunters` overlay

**Files:**
- Create: `examples/ecommerce/specs/overlays/bounty_hunters.py`
- Test: `apps/datagen/tests/test_example_ecom_bounty.py`

**Interfaces:**
- Consumes: Task 10 (`Overlay`), Task 14 exposed actions (`signup`, `signup_invited`, `quick_order`, `pay_referral`, `claim_bonus`, param `referral.min_order`).
- Produces: cohort `campaign` (partition and table `campaign`, key `campaign_id`, acts for `user`), machines `hunter` and `zombie` (process `mx_campaign`), label table `labels_campaign` (roles `hunter`, `zombie`; outcomes `attempted`, `qualified`, `paid`). Tasks 17, 20, 22 read these names.

- [ ] **Step 1: Write the overlay**

```python
"""Bounty hunters (brief: Abuse): rings that farm the referral program, then go dormant.

A ring is one hunter plus the zombie accounts it invites, all executed by one campaign owner
(execution owner, D74): the hunter waits on its zombies with a join, without cross-owner
messages, and campaigns run in parallel. Zombies claim from the same capped referral_pool shard
as every shopper, so rings that arrive when the budget is low drain it and ordinary claims are
rejected (interference, D79). Members are user rows (entities/user, origin "member"); they emit
only base events through the actions the base pack exposes; hidden labels go to labels/.

    datagen run examples/ecommerce --profile full --overlay bounty_hunters \
        --set bounty_hunters.size=500 --set bounty_hunters.share_device=0.8
"""

from neorisk_simkit.spec import Overlay, dist, std

AGE = {"18-24": 0.5, "25-34": 0.5}


def apply(o: Overlay, size: int = 300, zombies_mean: float = 12.0, share_device: float = 0.7,
          arrive_day: float = 10.0, arrive_span_days: float = 30.0, qualify_timeout: str = "14d",
          order_above_min: float = 0.05, zombie_order_p: float = 0.85) -> None:
    min_order = o.param("referral.min_order")
    camp = o.cohort("campaign", table="user", size=size,
                    arrivals=dist.burst(start_day=arrive_day, span_days=arrive_span_days),
                    execution_owner="campaign_id", suppress=["shopper"],
                    attrs={"age_band": dist.categorical(AGE),
                           "region": dist.uniform_int(0, 49)},
                    refs={"device": std.devices(
                        per_user=dist.categorical({1: .25, 2: .25, 3: .25, 4: .25}),
                        table="device", share=0.0)})

    # ---------------------------------------------------------------- hunter
    h = o.machine("hunter", members=camp, initial="new", reads={"sku": "sku"},
                  fields={"device": "ref", "amount": "i64", "paid": "i64"},
                  init={"device": std.pick_ref("device"),
                        "amount": std.near(3 * min_order, above=1.0)},
                  member={"acquisition": "social_ad"})
    h.state("new", branch={"inviting": (
        1.0, dist.lognormal(median_s=900),
        o.base.signup.then(std.label("hunter", "attempted")).then(std.spawn(
            "zombie", n=dist.geometric(mean=zombies_mean, max=30),
            stagger=dist.exp(mean_s=240),
            fields={"device": std.pick_ref("device", parent_share=share_device),
                    "amount": std.near(min_order, above=order_above_min)})))})
    h.state("inviting", join={"collecting": "zombie_paid"}, timer={"collecting": qualify_timeout},
            late="count")
    h.state("collecting", repeat=(dist.exp(mean_s=3600), 1.0, o.base.quick_order),
            max_repeats=std.field("jn"), then="done")     # one cash-out order per paid zombie
    h.state("done", branch={"gone": (1.0, None, std.label("hunter", "qualified"))})
    h.final("gone")

    # ---------------------------------------------------------------- zombie
    z = o.machine("zombie", members=camp.spawned("zombie"), initial="invited",
                  max_instances=32, reads={"sku": "sku"},
                  fields={"device": "ref", "amount": "i64", "paid": "i64"},
                  member={"acquisition": "invite", "referred": 1, "invited_by": std.parent()})
    z.state("invited", branch={
        "ordered": (zombie_order_p, dist.lognormal(median_s=600),
                    o.base.signup_invited.then(std.label("zombie", "attempted"))
                    .then(o.base.quick_order).then(std.label("zombie", "qualified"))),
        "dormant": (None, dist.lognormal(median_s=600),
                    o.base.signup_invited.then(std.label("zombie", "attempted")))})
    z.state("ordered", request={"paid": o.base.claim_bonus}, on_reject="gone", timeout="1m")
    z.state("paid", branch={"gone": (1.0, dist.exp(mean_s=300), o.base.pay_referral.then(
        std.label("zombie", "paid")).then(std.send_parent("zombie_paid")))})
    z.final("gone", "dormant")

    # ---------------------------------------------------------------- labels (hidden)
    o.label(camp, roles=("hunter", "zombie"), outcomes=("attempted", "qualified", "paid"),
            available_after=dist.gamma(mean_days=30))
```

- [ ] **Step 2: Write the tests**

`apps/datagen/tests/test_example_ecom_bounty.py`:
```python
"""The bounty_hunters overlay: members are user rows executed by a campaign owner, emitting
only base events; zombies hug the minimum order, share the hunter's devices and claim from the
base pool; labels are hidden (§08 contract)."""

import json
from pathlib import Path

import polars as pl
import pytest

from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events
from neorisk_simkit.spec.project import load_project, resolve_run
from neorisk_simkit.spec.validate import validate

EX = Path(__file__).resolve().parents[3] / "examples" / "ecommerce"
POOLS = ["engine.timer_nodes=600_000", "engine.payload_slots=100_000",
         "engine.max_messages_per_step=300_000", "budget.max_admissions_per_step=50_000",
         "budget.max_checker_keys=1_000_000"]
SMALL = ["users=3000", "skus=1200", "sku_groups=8", "run.span=21d", "run.warmup=0s", *POOLS,
         "bounty_hunters.size=8", "bounty_hunters.arrive_day=1.0",
         "bounty_hunters.arrive_span_days=3.0", "bounty_hunters.qualify_timeout=7d"]


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    return run_to_dataset(EX, "sample", SMALL, overlays=["bounty_hunters"],
                          out_dir=tmp_path_factory.mktemp("bh") / "run", threads=4)


@pytest.fixture(scope="module")
def ev(run):
    return read_events(run.out_dir)


@pytest.fixture(scope="module")
def members(run):
    u = pl.read_parquet(run.out_dir / "entities" / "user")
    return u.filter(pl.col("origin") == "member")


def test_overlay_profiles_validate_and_keep_the_schema():
    base = resolve_run(load_project(EX), "sample", []).plan
    for profile in ("legacy", "abuse"):
        run = resolve_run(load_project(EX), profile, [])
        assert validate(run).ok, (profile, validate(run).errors)
        ev = [(e.name, e.cols) for e in run.plan.events if e.group == "events"]
        assert ev == [(e.name, e.cols) for e in base.events if e.group == "events"]


def test_members_are_hunters_and_their_zombies(ev, members):
    su = ev["user_signed_up"].join(members.select(pl.col("id").alias("user_id")), on="user_id")
    hunters = su.filter(pl.col("invited_by").is_null())
    zombies = su.filter(pl.col("invited_by").is_not_null())
    assert hunters.height == 8 and zombies.height >= 8 * 3
    assert set(zombies["invited_by"]) <= set(hunters["user_id"])
    assert ev["session_started"].join(members.select(pl.col("id").alias("user_id")),
                                      on="user_id").height == 0          # suppress=["shopper"]


def test_zombies_hug_the_minimum_and_share_devices(ev, members):
    su = ev["user_signed_up"].join(members.select(pl.col("id").alias("user_id")), on="user_id")
    zombies = su.filter(pl.col("invited_by").is_not_null())
    orders = ev["order_placed"].join(zombies.select("user_id"), on="user_id")
    assert orders.height > 0
    assert orders["amount"].min() >= 3000 and orders["amount"].max() <= 3150
    dev = zombies.join(su.select(pl.col("user_id").alias("invited_by"),
                                 pl.col("device_id").alias("hunter_device")), on="invited_by")
    assert (dev["device_id"] == dev["hunter_device"]).mean() >= 0.5


def test_labels_are_hidden_and_final_per_target(run, members):
    d = run.out_dir
    assert not (d / "events" / "labels_campaign").exists()
    labels = pl.read_parquet(sorted((d / "labels" / "labels_campaign").rglob("*.parquet")))
    last = labels.sort("event_time", "lamport").group_by("target_id").last()
    assert set(last["target_id"]) == set(members["id"])
    assert set(last["role"]) == {"hunter", "zombie"}
    assert (last["label_available_at"] > last["event_time"]).all()
    assert json.loads((d / "manifest.json").read_text())["label_counts"]["labels_campaign"] \
        == labels.height


def test_zombie_claims_reach_the_base_pool(ev, members):
    paid = ev["referral_bonus_paid"].join(members.select(pl.col("id").alias("invitee_id")),
                                          on="invitee_id")
    assert set(paid["role"]) == {"invitee", "inviter"}
    assert ev["bonus_granted"].height > paid.height // 2
```

- [ ] **Step 3: Run** — `uv run --all-packages pytest apps/datagen/tests/test_example_ecom_bounty.py -q` (compiles the base+overlay module once, 45–90 min; background) → PASS. Defects in generated code go to `machine/compile.py` (Tasks 6–10) with a regression test on the smallest fixture that shows them.

- [ ] **Step 4: Lint and commit**

```bash
uv run ruff check $(ls -d libs apps examples/ecommerce_s1 examples/ecommerce_s2 examples/ecommerce benchmarks 2>/dev/null)
git add examples/ecommerce/specs/overlays/bounty_hunters.py \
  apps/datagen/tests/test_example_ecom_bounty.py
git commit -m "feat(examples): bounty_hunters overlay on the real ecommerce pack (§08)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 17: The regression rule and the interference report (§08, D78, D79)

**Files:**
- Create: `libs/simkit/src/neorisk_simkit/checks/interference.py`
- Create: `libs/simkit/tests/fixtures/ring/specs/overlays/quiet.py` (a cohort that shares nothing)
- Test: `apps/datagen/tests/test_example_ecom_interference.py`, `libs/simkit/tests/test_checks_interference.py`

**Interfaces:**
- Consumes: `Plan.cohorts`, boundaries, `read_events`, entity folders.
- Produces:
  - `shared_partitions(plan) -> tuple[str, ...]`: base partitions that a cohort process sends a boundary to (request or message targets), plan order.
  - `base_ptypes(plan) -> frozenset[int]`: ptype codes of non-cohort partitions.
  - `compare(base_dir: Path, overlay_dir: Path, plan) -> dict` with keys `shared` (list), `identical_base_rows` (bool, or None when shared), `exogenous_identical` (bool), `first_contact` (ISO time of the first cohort row of a boundary to a shared partition, or None), `events` (`{name: {"base": n, "with": n}}` over base partitions), `changed_owners` (`{name: n}`: base owners — the `user_id` column when present, else `partition_id` — whose rows of that type differ as multisets), `laws_ok` (`{"base": bool, "with": bool}` from both manifests).
  - `canonical_rows(t: pl.DataFrame, created: set[str]) -> pl.DataFrame`: drop `event_id`; rename the values of every column referencing a created namespace by first appearance in canonical order (D37); sort by all columns.

- [ ] **Step 1: Write the quiet overlay** (`fixtures/ring/specs/overlays/quiet.py`)

```python
"""A cohort that signs up and does nothing else: it shares no decision state with the base."""

from neorisk_simkit.spec import Overlay, dist, std


def apply(o: Overlay, size: int = 2) -> None:
    c = o.cohort("loners", table="user", size=size, execution_owner="loner_id",
                 attrs={"tier": "a"}, refs={"device": std.devices(
                     per_user=dist.categorical({1: 1.0}), table="device", share=0.0)})
    m = o.machine("loner", members=c, initial="new", fields={"device": "ref"},
                  init={"device": std.pick_ref("device")})
    m.state("new", branch={"gone": (1.0, dist.constant(s=60), o.base.signup)})
    m.final("gone")
```

- [ ] **Step 2: Write the failing tests**

`libs/simkit/tests/test_checks_interference.py`:
```python
"""D78: base rows are identical with and without an overlay that shares nothing."""

from conftest import FIXTURES

from neorisk_simkit.checks.interference import compare, shared_partitions
from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.spec.project import load_project, resolve_run

RING = FIXTURES / "ring"


def _plan(overlays):
    return resolve_run(load_project(RING), "sample", [], overlays=overlays).plan


def test_access_declarations_decide_sharing():
    assert shared_partitions(_plan(["ring"])) == ("pot",)
    assert shared_partitions(_plan(["quiet"])) == ()


def test_a_quiet_overlay_leaves_base_rows_identical(tmp_path):
    a = run_to_dataset(RING, "sample", [], out_dir=tmp_path / "a", threads=2).out_dir
    b = run_to_dataset(RING, "sample", [], overlays=["quiet"], out_dir=tmp_path / "b",
                       threads=2).out_dir
    rep = compare(a, b, _plan(["quiet"]))
    assert rep["shared"] == [] and rep["identical_base_rows"] is True
    assert rep["exogenous_identical"] is True


def test_a_sharing_overlay_reports_interference(tmp_path):
    a = run_to_dataset(RING, "sample", [], out_dir=tmp_path / "a", threads=2).out_dir
    b = run_to_dataset(RING, "sample", [], overlays=["ring"], out_dir=tmp_path / "b",
                       threads=2).out_dir
    rep = compare(a, b, _plan(["ring"]))
    assert rep["shared"] == ["pot"] and rep["identical_base_rows"] is None
    assert rep["exogenous_identical"] is True and rep["laws_ok"] == {"base": True, "with": True}
    assert set(rep["events"]) >= {"signed_up", "bonus_paid"}
```

`apps/datagen/tests/test_example_ecom_interference.py`:
```python
"""Hunters drain the referral budget: base claims are rejected more often with the overlay
(§08 regression rule, interference report)."""

from pathlib import Path

import pytest

from neorisk_simkit.checks.interference import compare, shared_partitions
from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.spec.project import load_project, resolve_run

EX = Path(__file__).resolve().parents[3] / "examples" / "ecommerce"
POOLS = ["engine.timer_nodes=600_000", "engine.payload_slots=100_000",
         "engine.max_messages_per_step=300_000", "budget.max_admissions_per_step=50_000",
         "budget.max_checker_keys=1_000_000"]
BASE = ["users=3000", "skus=1200", "sku_groups=8", "run.span=21d", "run.warmup=0s", *POOLS,
        "referral.referred_share=0.3", "referral.inviter_share=0.1", "referral.min_order=1000",
        "referral.monthly_budget=60000"]
OVL = ["bounty_hunters.size=10", "bounty_hunters.arrive_day=1.0",
       "bounty_hunters.arrive_span_days=1.0", "bounty_hunters.qualify_timeout=7d"]


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("intf")
    a = run_to_dataset(EX, "sample", BASE, out_dir=tmp / "base", threads=4).out_dir
    b = run_to_dataset(EX, "sample", [*BASE, *OVL], overlays=["bounty_hunters"],
                       out_dir=tmp / "with", threads=4).out_dir
    plan = resolve_run(load_project(EX), "sample", [*BASE, *OVL],
                       overlays=["bounty_hunters"]).plan
    return compare(a, b, plan)


def test_the_overlay_shares_only_the_pool():
    plan = resolve_run(load_project(EX), "sample", [], overlays=["bounty_hunters"]).plan
    assert shared_partitions(plan) == ("referral_pool",)


def test_exogenous_draws_and_laws_hold(report):
    assert report["exogenous_identical"] is True
    assert report["laws_ok"] == {"base": True, "with": True}


def test_base_claims_are_crowded_out(report):
    rej = report["events"]["referral_bonus_rejected"]
    assert rej["with"] > rej["base"]
    assert report["changed_owners"]["referral_bonus_paid"] > 0
```

- [ ] **Step 3: Run the tests to verify they fail** (`ModuleNotFoundError: neorisk_simkit.checks.interference`), then **implement** `checks/interference.py` as specified in Interfaces: base rows = rows whose `partition_id >> 56` is a base ptype; `exogenous_identical` = every population entity table of a base partition (and every static table's base rows) is equal in both runs, and the base rows strictly before `first_contact` are equal under `canonical_rows` (all base rows when `first_contact` is None); `identical_base_rows` = equality of all base rows under `canonical_rows` when nothing is shared; created namespaces are `plan.namespaces` that are tables or ids; `laws_ok` from `manifest.json["laws"]` (no violations of required laws). Read events with `read_events`, entities with `pl.read_parquet`.

- [ ] **Step 4: Run** — both test files → PASS (the ecommerce file reuses the cached base and base+overlay modules). If `test_base_claims_are_crowded_out` does not show crowding with these parameters, raise `bounty_hunters.size` or lower `referral.monthly_budget` in the test (never the assertion) and say so in the commit message.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check $(ls -d libs apps examples/ecommerce_s1 examples/ecommerce_s2 examples/ecommerce benchmarks 2>/dev/null)
git add libs/simkit/src/neorisk_simkit/checks/interference.py \
  libs/simkit/tests/fixtures/ring/specs/overlays/quiet.py \
  libs/simkit/tests/test_checks_interference.py apps/datagen/tests/test_example_ecom_interference.py
git commit -m "feat(checks): overlay regression rule and interference report (D78, D79)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 18: Statistical checks and `expectations.yaml` (§11, D84, D85)

**Files:**
- Create: `libs/simkit/src/neorisk_simkit/spec/expectations.py`, `libs/simkit/src/neorisk_simkit/checks/stats.py`
- Modify: `libs/simkit/pyproject.toml` (`pyyaml>=6` in dependencies; then `uv lock`), `uv.lock`
- Test: `libs/simkit/tests/test_checks_stats.py`

**Interfaces:**
- Consumes: `read_events`, entity folders, `labels/` folders, `Plan.cohorts`, manifest laws, `checks.interference.compare` (Task 17).
- Produces:
  - `spec.expectations.load(path: Path, *, overlays: dict[str, dict], cfg) -> Expectations` where `Expectations(defaults: dict, laws: tuple[LawRef, ...], items: tuple[Expectation, ...])`, `LawRef(id, required)`, `Expectation(id, metric: str, kwargs: dict, args: tuple, target: dict, source: str | None, required: bool, overlay: str | None)`. Metric strings parse with `ast.parse(text, mode="eval")` into exactly one `stat.<name>(...)` call with literal arguments (`ast.literal_eval` per argument); anything else → `ExpectationError(f"{id}: metric must be one stat.<name>(...) call with literal arguments")`. `${<overlay>.<param>}` and `${<config path>}` inside targets are substituted. Overlay sections apply only to enabled overlays.
  - `checks.stats.evaluate(exp: Expectations, run_dir: Path, plan, *, baseline: Path | None) -> list[dict]` — one result per law and expectation: `{"id", "kind": "law"|"expectation", "metric", "value", "ci": [lo, hi] | None, "n_cases", "censored_share", "target", "status": "pass"|"fail"|"inconclusive"|"missing"|"unanchored", "required", "source"}`.
  - Metrics (exact definitions; cases are owners = `partition_id`, sampled per D85):
    - `funnel(start, step, unit, within=None, where=None)`: cases = distinct `unit` values of `start` rows (filtered by `where` equality on start columns); converted when a `step` row with the same `unit` has `event_time ≥` the first start time and, with `within`, `≤ start + within`; with `within`, cases starting after `end − within` are censored (excluded; `censored_share` reported). Wilson 95% CI.
    - `share(event, of, where=None)`: rows of `event` (filtered) ÷ rows of the `of` events; cluster-robust CI over owners (delta method on per-owner sums).
    - `quantiles(event_or_column, per=None, where=None, cohort=None, role=None)`: with `per`, the row count per `per` value; else the column's values; `cohort=` keeps rows whose partition is that cohort; `role=` keeps rows whose `user_id` is a label target with that role (last label row); binomial order-statistic CI.
    - `top_share(event, by, top)`: exact share of rows whose `by` value is among the top `ceil(top · distinct)` values by count.
    - `distribution(between=[a, b], unit)`: per unit, first `b` after first `a`; `median_days`, `p99_days`.
    - `cohort_size(cohort)`: number of the cohort's owners with at least one row (exact).
    - `interference(base, cause)`: `compare(baseline, run_dir, plan)`; value = the report; `reported: true` passes when the comparison ran and `cause` is in `shared`; no baseline → `missing`.
  - Status: `missing` when a metric names an unknown event/column/cohort or a law id is absent from the manifest; `unanchored` when `source` is empty; `inconclusive` when `n_cases < min_sample` (laws: `checked == 0`); else `pass`/`fail` by the point value against the target (`between`, `lt`, `gt`, `around`+`tolerance` relative, per-key maps for quantiles/distribution, `reported`).

- [ ] **Step 1: Write the failing tests**

`libs/simkit/tests/test_checks_stats.py` builds small datasets in a temp folder with `pyarrow` (one `events/<type>/date=2026-01-01/step-000000.parquet` per type plus `manifest.json`), mirroring what the writer lays out, and asserts metric values exactly:
```python
"""D84/D85: expectations grammar and statistical metrics on tiny hand-made datasets."""

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from neorisk_simkit.checks.stats import evaluate
from neorisk_simkit.spec.expectations import ExpectationError, load

TS = pa.timestamp("us", tz="UTC")
DAY = 86_400_000_000


def _write(d: Path, name: str, rows: list[dict]) -> None:
    n = len(rows)
    cols = {"event_id": pa.array(range(1, n + 1), pa.int64()),
            "event_type": pa.array([name] * n, pa.string()),
            "event_time": pa.array([r["t"] for r in rows], pa.int64()).cast(TS),
            "lamport": pa.array(range(1, n + 1), pa.int64()),
            "partition_id": pa.array([(1 << 56) | r["o"] for r in rows], pa.int64()),
            "seq": pa.array([0] * n, pa.int32()),
            "cause_id": pa.nulls(n, pa.int64()),
            "action_id": pa.array([0] * n, pa.int16())}
    for k in sorted({k for r in rows for k in r} - {"t", "o"}):
        vals = [r.get(k) for r in rows]
        cols[k] = pa.array(vals, pa.string() if isinstance(vals[0], str) else pa.int64())
    f = d / "events" / name / "date=2026-01-01" / "step-000000.parquet"
    f.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table(cols), f)


def _exp(tmp: Path, text: str):
    p = tmp / "expectations.yaml"
    p.write_text(text)
    return load(p, overlays={}, cfg=None)


@pytest.fixture
def data(tmp_path):
    d = tmp_path / "run"
    starts = [{"t": i * DAY, "o": i, "session_id": i} for i in range(10)]
    _write(d, "session_started", starts)
    _write(d, "checkout_started", [{"t": i * DAY + 5, "o": i, "session_id": i} for i in (1, 3)])
    _write(d, "product_viewed", [{"t": 1, "o": 0, "sku_id": s} for s in [1] * 8 + [2, 3]])
    (d / "manifest.json").write_text(json.dumps({"laws": {"chk.a": {"checked": 3,
                                                                   "violations": 0}}}))
    return d


def test_funnel_share_and_top_share(tmp_path, data):
    exp = _exp(tmp_path, """
defaults: {min_sample: 2}
laws: [{id: chk.a, required: true}, {id: chk.gone, required: true}]
expectations:
  - id: f
    metric: stat.funnel(start="session_started", step="checkout_started", unit="session_id")
    target: {between: [0.15, 0.25]}
    source: "x"
    required: true
  - id: t
    metric: stat.top_share("product_viewed", by="sku_id", top=0.34)
    target: {gt: 0.7}
    source: "x"
  - id: u
    metric: stat.share("checkout_started", of=["session_started"])
    target: {lt: 0.5}
""")
    res = {r["id"]: r for r in evaluate(exp, data, plan=None, baseline=None)}
    assert res["f"]["value"] == pytest.approx(0.2) and res["f"]["status"] == "pass"
    assert res["t"]["value"] == pytest.approx(0.8) and res["t"]["status"] == "pass"
    assert res["u"]["status"] == "unanchored"
    assert res["chk.a"]["status"] == "pass" and res["chk.gone"]["status"] == "missing"


def test_small_samples_are_inconclusive(tmp_path, data):
    exp = _exp(tmp_path, """
defaults: {min_sample: 100}
expectations:
  - id: f
    metric: stat.funnel(start="session_started", step="checkout_started", unit="session_id")
    target: {between: [0.0, 1.0]}
    source: "x"
""")
    (r,) = evaluate(exp, data, plan=None, baseline=None)
    assert r["status"] == "inconclusive" and r["n_cases"] == 10


def test_within_censors_late_starts(tmp_path, data):
    exp = _exp(tmp_path, """
defaults: {min_sample: 1}
expectations:
  - id: f
    metric: stat.funnel(start="session_started", step="checkout_started", unit="session_id", within="5d")
    target: {between: [0.0, 1.0]}
    source: "x"
""")
    (r,) = evaluate(exp, data, plan=None, baseline=None)
    assert r["censored_share"] == pytest.approx(0.5) and r["n_cases"] == 5


def test_metrics_are_calls_not_expressions(tmp_path):
    with pytest.raises(ExpectationError, match="one stat.<name>"):
        _exp(tmp_path, """
expectations:
  - id: bad
    metric: stat.share("a", of=["b"]) + 1
    target: {lt: 1}
    source: "x"
""")
```
(The run's end for censoring is the last `event_time` of the dataset when the manifest has no `end_us`; read the real manifest key the writer uses for the run end — add one (`"end_us"`) in `write_manifest` if it does not exist, and use `max event_time` only as the fallback for hand-made datasets.)

- [ ] **Step 2: Run them to verify they fail** — `ModuleNotFoundError: neorisk_simkit.checks.stats`.

- [ ] **Step 3: Implement** both modules per the Interfaces block (polars for the metrics; `mix64` from `checks.laws._mix64` for the owner hash; per-stratum rates `max(sample_rate, min(1, min_sample / owners))`; weights `1 / rate`; strata keyed by `partition_id >> 56`). Add `pyyaml>=6` to `libs/simkit/pyproject.toml` and run `uv lock`.

- [ ] **Step 4: Run** — `uv run --all-packages pytest libs/simkit/tests/test_checks_stats.py -q` → PASS; full suite in the background → PASS.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check $(ls -d libs apps examples/ecommerce_s1 examples/ecommerce_s2 examples/ecommerce benchmarks 2>/dev/null)
git add libs/simkit/src/neorisk_simkit/spec/expectations.py \
  libs/simkit/src/neorisk_simkit/checks/stats.py libs/simkit/src/neorisk_simkit/io/manifest.py \
  libs/simkit/pyproject.toml uv.lock libs/simkit/tests/test_checks_stats.py
git commit -m "feat(checks): expectations.yaml and statistical metrics with sampling and CIs (D84, D85)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 19: `datagen check`, `report.html` and `checks.json` (§02, §16, D86)

**Files:**
- Create: `libs/simkit/src/neorisk_simkit/report/__init__.py`, `libs/simkit/src/neorisk_simkit/report/html.py`, `apps/datagen/src/datagen/check_cmd.py`
- Modify: `apps/datagen/src/datagen/cli.py` (`check` subcommand)
- Test: `apps/datagen/tests/test_datagen_check_cli.py`

**Interfaces:**
- Consumes: Task 18 (`load`, `evaluate`), Task 17 (`compare`), manifest, `run_stats.json` (`machines`, `rejects`, `pairing`), `Plan.cohorts`.
- Produces:
  - `datagen check <project> --profile P [--set K=V ...] [--overlay N ...] [--seed S] [--run-dir DIR] [--baseline DIR] [--out DIR]`: run dir default `<project>/<paths.out>/<run name>`; baseline default: when overlays are enabled and `<paths.out>/<profile>-s<seed>` exists, that folder; output default `<project>/<paths.reports>/<run name>/` with `report.html` and `checks.json`; exit 0 when every required check passes, **5** otherwise (failed, missing, inconclusive or unanchored), 2 on usage errors (D86).
  - `checks.json` = `{"run": name, "pack": ..., "revision": ..., "overlays": {...}, "ok": bool, "results": [evaluate rows], "interference": compare report | null}`.
  - `report.render(run_dir, results, *, interference, plan) -> str`: one self-contained HTML page (inline CSS, no scripts, no network) with sections in this order: **Counts** (events, postings, labels, entities, history from the manifest), **Linkages** (pairing per request boundary, late messages), **Transitions** (per machine: state entries; rejects; late), **Concentration** (for each event type, the top-1% share of rows by its first `ref` column other than the common columns, exact), **Rejections** (`run_stats.rejects` per process), **Cohorts** (per cohort: owners, members, label rows by role and outcome), **Interference** (the compare report, when present), **Checks** (laws and expectations: id, value, CI, cases, censored share, target, status, required, source).

- [ ] **Step 1: Write the failing tests**

```python
"""datagen check: report.html + checks.json, exit 5 on a failing required check (D86)."""

import json
from pathlib import Path

from datagen.cli import main
from neorisk_simkit.io.dataset import run_to_dataset

FIX = Path(__file__).resolve().parents[3] / "libs" / "simkit" / "tests" / "fixtures"


def _ring(tmp_path):
    proj = tmp_path / "ring"
    import shutil
    shutil.copytree(FIX / "ring", proj, ignore=shutil.ignore_patterns("out", "__pycache__"))
    (proj / "specs" / "expectations.yaml").write_text("""
pack: ring
defaults: {min_sample: 1}
laws: []
expectations:
  - id: exp.signups
    metric: stat.share("bonus_paid", of=["signed_up"])
    target: {between: [0.0, 1.0]}
    source: "test"
    required: true
overlays:
  ring:
    - id: exp.gangs
      metric: stat.cohort_size("gang")
      target: {around: "${ring.size}", tolerance: 0.0}
      source: "overlay config"
      required: true
    - id: exp.intf
      metric: stat.interference(base="bonus_paid", cause="pot")
      target: {reported: true}
      source: "§08"
      required: true
""")
    return proj


def test_check_writes_the_report_and_passes(tmp_path):
    proj = _ring(tmp_path)
    run_to_dataset(proj, "sample", [], threads=2)
    run_to_dataset(proj, "sample", [], overlays=["ring"], threads=2)
    rc = main(["check", str(proj), "--profile", "sample", "--overlay", "ring"])
    assert rc == 0
    out = proj / "reports" / "sample-s7+ring"
    html = (out / "report.html").read_text()
    for section in ("Counts", "Linkages", "Transitions", "Concentration", "Rejections",
                    "Cohorts", "Interference", "Checks"):
        assert f">{section}<" in html, section
    checks = json.loads((out / "checks.json").read_text())
    assert checks["ok"] is True and checks["interference"]["shared"] == ["pot"]


def test_a_missing_baseline_fails_the_required_interference_check(tmp_path):
    proj = _ring(tmp_path)
    run_to_dataset(proj, "sample", [], overlays=["ring"], threads=2)
    assert main(["check", str(proj), "--profile", "sample", "--overlay", "ring"]) == 5
    checks = json.loads((proj / "reports" / "sample-s7+ring" / "checks.json").read_text())
    st = {r["id"]: r["status"] for r in checks["results"]}
    assert st["exp.intf"] == "missing" and checks["ok"] is False
```
(The ring fixture's `datagen.toml` needs `reports = "reports"` under `[paths]`; add it in the copy if Task 10 did not.)

- [ ] **Step 2–4: Run to fail, implement, run to pass** — `uv run --all-packages pytest apps/datagen/tests/test_datagen_check_cli.py -q`.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check $(ls -d libs apps examples/ecommerce_s1 examples/ecommerce_s2 examples/ecommerce benchmarks 2>/dev/null)
git add libs/simkit/src/neorisk_simkit/report apps/datagen/src/datagen/check_cmd.py \
  apps/datagen/src/datagen/cli.py apps/datagen/tests/test_datagen_check_cli.py
git commit -m "feat(datagen): check command, report.html and checks.json (D86)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 20: Legacy adapter `datagen export --legacy-fraud` and the parity suite (D87, D88)

**Files:**
- Create: `libs/simkit/src/neorisk_simkit/io/legacy.py`, `apps/datagen/src/datagen/export_cmd.py`
- Modify: `apps/datagen/src/datagen/cli.py` (`export` subcommand)
- Test: `apps/datagen/tests/test_legacy_fraud_parity.py`

**Interfaces:**
- Consumes: an ecommerce dataset with the `bounty_hunters` overlay (Tasks 14–16): events `order_placed`, `referral_bonus_paid`, `user_signed_up`; `entities/{user,device,sku}`; `history/address`; `labels/labels_*`; `schema/schema.json` (category orders); `neorisk_simkit.export.{Dataset, export}`; `neorisk_simkit.features.{rolling, rolling_asof}`.
- Produces: `io.legacy.legacy_fraud(run_dir: Path) -> Dataset` and `datagen export <run_dir> --legacy-fraud --out DIR` (exit 2 without `--legacy-fraud`: "datagen export: only --legacy-fraud exists in M3 (single-file export is M4)"). Output columns of `events.parquet`, in order: `event_id` (str `"<type>:<engine event_id>"`), `event_time`, `event_type` (0 = `order_placed`, 1 = inviter `referral_bonus_paid`), `user_id`, `device_id`, `product_id`, `inviter_id`, `amount` (float64 dollars; null on invites), `currency` (int 0 on orders, null on invites), `referral_bonus` (float64 dollars on invites, null on orders), `user_age_bucket`, `user_segment`, `user_state` (as-of event time from `history/address`), `device_os`, `device_model` (the device `kind` code), `product_category`, `product_price` (dollars), then `label`. Category codes are the value's index in its declared category list. `golden.parquet`: `event_id`, `u_amt_{count,sum,mean,max,min}_{7,14,30}d`, `dev_users_n_unique_7d`, `inv_bonus_{count,sum,mean,max}_{7,14,30}d`, `invr_bonus_{count,sum,mean,max}_{7,14,30}d`, `amt_ratio_30d`, `invitee_is_zombie`, `actor_role` (0 none, else 1 + role index of the labels table), `score` (= label as float64), rows in events order. `meta.json`: `scenario = "ecommerce+bounty_hunters"`, `seed`, `source = {pack, revision, overlays, run}`, `feature_allowlist` (numeric event columns that are not `label` or `*_id`).

- [ ] **Step 1: Write the parity suite** (`apps/datagen/tests/test_legacy_fraud_parity.py`) — the properties `test_datagen_fraud.py` pins, on the adapter output, plus bench consuming it:
```python
"""D88: the e-commerce pack + bounty_hunters overlay, exported through the legacy adapter, has
the properties today's fraud dataset has, and bench runs on it."""

from pathlib import Path

import numpy as np
import polars as pl
import pytest

from bench.allowlist import resolve_allowlist
from bench.features import build_features
from bench.runner import load_events, run
from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.legacy import legacy_fraud

EX = Path(__file__).resolve().parents[3] / "examples" / "ecommerce"
SMALL = ["users=3000", "run.span=40d"]


@pytest.fixture(scope="module")
def dirs(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("legacy")
    res = run_to_dataset(EX, "legacy", SMALL, out_dir=tmp / "run", threads=4)
    from datagen.cli import main
    assert main(["export", str(res.out_dir), "--legacy-fraud", "--out", str(tmp / "fraud")]) == 0
    return res.out_dir, tmp / "fraud"


@pytest.fixture(scope="module")
def ds(dirs):
    return legacy_fraud(dirs[0])


def test_export_is_deterministic(dirs, ds):
    again = legacy_fraud(dirs[0])
    assert again.events.equals(ds.events) and again.golden.equals(ds.golden)


def test_shape_and_no_golden_in_events(ds):
    golden_cols = set(ds.golden.columns) - {"event_id"}
    assert not golden_cols & set(ds.events.columns)
    assert set(ds.events["event_id"]) == set(ds.golden["event_id"])
    for c in ("event_time", "event_type", "user_id", "device_id", "amount", "label",
              "inviter_id", "referral_bonus", "user_state"):
        assert c in ds.events.columns, c


def test_bad_rate_in_band(ds):
    assert 0.003 < ds.events["label"].mean() < 0.08


def test_attributes_are_stable(ds):
    txn = ds.events.filter(pl.col("event_type") == 0)
    assert txn.group_by("device_id").agg(pl.col("device_os").n_unique())["device_os"].max() == 1
    chg = txn.sort("event_time").group_by("user_id").agg(
        (pl.col("user_state").diff().fill_null(0) != 0).sum().alias("c"), pl.len().alias("n"))
    assert chg.filter(pl.col("n") > 5)["c"].mean() < 3


def test_invites_reference_other_users(ds):
    inv = ds.events.filter(pl.col("event_type") == 1)
    assert inv.height > 0 and (inv["inviter_id"] != inv["user_id"]).all()
    txn = ds.events.filter(pl.col("event_type") == 0)
    assert txn["inviter_id"].null_count() == txn.height


def test_bounty_hunter_signature_is_planted(ds):
    g = ds.golden.join(ds.events.select("event_id", "event_type"), on="event_id")
    inv = g.filter(pl.col("event_type") == 1)
    z, n = inv.filter(pl.col("invitee_is_zombie") == 1), inv.filter(pl.col("invitee_is_zombie") == 0)
    assert z.height > 0 and n.height > 0
    assert z["inv_bonus_count_30d"].mean() > 2 * n["inv_bonus_count_30d"].mean()


def test_rolling_features_have_no_future_leakage(ds):
    first = ds.events.filter(pl.col("event_type") == 0).sort("event_time").group_by(
        "user_id").first()
    g = ds.golden.filter(pl.col("event_id").is_in(first["event_id"].implode()))
    assert (g["u_amt_count_30d"] == 0).all()


def test_golden_rows_align_with_events(ds):
    assert ds.golden["event_id"].equals(ds.events["event_id"])


def test_bench_consumes_the_export(dirs):
    events, meta = load_events(dirs[1])
    assert meta["_allowlist"] == resolve_allowlist(meta, events)
    feats = build_features(events, meta["_allowlist"])
    assert feats.height == events.height
    rows = run(dirs[1])
    aucs = [r["auc"] for r in rows if r["model"] == "xgb_raw" and r["split"] == "test"]
    assert aucs and np.isfinite(aucs[0]) and aucs[0] > 0.5
```

- [ ] **Step 2: Run to verify it fails** (`ModuleNotFoundError: neorisk_simkit.io.legacy`), **implement** `io/legacy.py` per the Interfaces block (polars; the rolling features use exactly the legacy names and windows of `datagen/scenarios/fraud.py:_golden`, computed with `neorisk_simkit.features.rolling` / `rolling_asof` over the adapter's events; `invitee_is_zombie` = the invite row's user is a label target with role `zombie`; `export(ds, out)` validates and writes), then `export_cmd.py` and the CLI. **Run** → PASS (the `legacy` profile reuses the base+overlay module; the run takes about a minute).

- [ ] **Step 3: Lint and commit**

```bash
uv run ruff check $(ls -d libs apps examples/ecommerce_s1 examples/ecommerce_s2 examples/ecommerce benchmarks 2>/dev/null)
git add libs/simkit/src/neorisk_simkit/io/legacy.py apps/datagen/src/datagen/export_cmd.py \
  apps/datagen/src/datagen/cli.py apps/datagen/tests/test_legacy_fraud_parity.py
git commit -m "feat(io): datagen export --legacy-fraud; parity suite on ecommerce + bounty_hunters (D87, D88)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 21: Retire the hand-coded fraud scenario (D89)

**Files:**
- Delete: `apps/datagen/src/datagen/scenarios/__init__.py`, `apps/datagen/src/datagen/scenarios/fraud.py`, `apps/datagen/src/datagen/config.py`, `apps/datagen/tests/test_datagen_fraud.py`
- Modify: `apps/datagen/src/datagen/cli.py` (`generate` prints the replacement and returns 2), `apps/datagen/tests/test_datagen_cli.py` (generate tests → replacement-message test + an `export` usage test), `apps/datagen/README.md` (the project commands; `generate` removed), `apps/datagen/pyproject.toml` (description; drop `xgboost` if nothing in `datagen` imports it any more), `apps/bench/tests/conftest.py` (new: a session fixture building one legacy export), `apps/bench/tests/{test_bench_allowlist,test_bench_runner,test_bench_compare,test_bench_features}.py` (use the fixture), `apps/bench/src/bench/datagen_section.py` (describe the pack + overlay from `meta["source"]`, both languages), `apps/bench/README.md`
- Test: the bench and datagen suites

**Interfaces:**
- Consumes: Task 20 (`legacy_fraud`, `datagen export`).
- Produces: `apps/bench/tests/conftest.py` fixture `legacy_dir(tmp_path_factory)` (session scope) returning a folder with `events.parquet`, `golden.parquet`, `meta.json` built from `examples/ecommerce --profile legacy --set users=2000 --set run.span=30d`.

- [ ] **Step 1: Bench fixture and tests** — `apps/bench/tests/conftest.py`:
```python
from pathlib import Path

import pytest

EX = Path(__file__).resolve().parents[3] / "examples" / "ecommerce"


@pytest.fixture(scope="session")
def legacy_dir(tmp_path_factory):
    from datagen.cli import main
    from neorisk_simkit.io.dataset import run_to_dataset

    tmp = tmp_path_factory.mktemp("legacy")
    res = run_to_dataset(EX, "legacy", ["users=2000", "run.span=30d"], out_dir=tmp / "run",
                         threads=4)
    out = tmp / "fraud"
    assert main(["export", str(res.out_dir), "--legacy-fraud", "--out", str(out)]) == 0
    return out
```
Rewrite every `datagen_main(["generate", ...])` / `generate(FraudConfig(...))` use in `test_bench_allowlist.py`, `test_bench_runner.py`, `test_bench_compare.py`, `test_bench_features.py` to read `legacy_dir` (`pl.read_parquet(legacy_dir / "events.parquet")`). Assertions that pinned planted properties of the old generator (for example "generated invitees' invite is always their first event" in `test_bench_features.py`) are replaced by the same property stated on the new data when it holds, else removed with a one-line comment naming the old property. `test_legacy_dataset_carries_an_allowlist_equal_to_todays_raw_set` keeps its name and checks the adapter's `feature_allowlist` the same way.

- [ ] **Step 2: Retire** — delete the files listed; `cli.py` keeps a `generate` subparser that accepts any arguments (`argparse.REMAINDER`) and prints `"datagen generate was replaced (M3): datagen run examples/ecommerce --profile legacy && datagen export <run dir> --legacy-fraud --out <dir>"` to stderr, returning 2. `test_datagen_cli.py`: `test_generate_points_to_the_replacement` (exit 2, message names both commands) and `test_export_needs_legacy_fraud` (exit 2). `datagen_section.py`: the intro, steps and behaviors describe the e-commerce pack (sessions, carts, inventory, orders, referrals) and the bounty-hunter overlay (rings, zombies at the minimum order, shared devices, pool draining), labels from the overlay's ground truth, and read counts/config from `meta["source"]` and `meta`; keep the `zh`/`en` structure and the existing tests' section ids. README lines that mention `datagen generate` are updated.

- [ ] **Step 3: Run** — `uv run --all-packages pytest apps/bench apps/datagen -q` → PASS; full suite in the background → PASS; `grep -rn "scenarios\|FraudConfig\|datagen generate" apps libs examples --include=*.py --include=*.md` finds only the replacement message and its test.

- [ ] **Step 4: Lint and commit**

```bash
uv run ruff check $(ls -d libs apps examples/ecommerce_s1 examples/ecommerce_s2 examples/ecommerce benchmarks 2>/dev/null)
git rm apps/datagen/src/datagen/scenarios/__init__.py apps/datagen/src/datagen/scenarios/fraud.py \
  apps/datagen/src/datagen/config.py apps/datagen/tests/test_datagen_fraud.py
git add apps/datagen/src/datagen/cli.py apps/datagen/tests/test_datagen_cli.py \
  apps/datagen/README.md apps/datagen/pyproject.toml apps/bench/tests/conftest.py \
  apps/bench/tests/test_bench_allowlist.py apps/bench/tests/test_bench_runner.py \
  apps/bench/tests/test_bench_compare.py apps/bench/tests/test_bench_features.py \
  apps/bench/src/bench/datagen_section.py apps/bench/README.md uv.lock
git commit -m "refactor(datagen): retire the hand-coded fraud scenario; bench reads the legacy export (D89)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```
(Stage `uv.lock` only if the dependency change modified it.)

---

### Task 22: Calibrate `examples/ecommerce` against the brief with `datagen check`

Config-only: `pack.py`/`kernels.py` code does not change (a code change recompiles the module); the calibration moves `Config` defaults and profile `set` values.

**Files:**
- Modify: `examples/ecommerce/specs/pack.py` (only `Journey`, `Referral`, `Fulfil` default values), `examples/ecommerce/datagen.toml` (profile values)
- Test: `apps/datagen/tests/test_example_ecom_calibration.py`

**Interfaces:**
- Consumes: Tasks 15 (expectations), 18–19 (`datagen check`).
- Produces: `sample` and `legacy` profiles whose `datagen check` passes every required check (base expectations for `sample`; base + `bounty_hunters` for `legacy`, with the base run as baseline).

- [ ] **Step 1: Write the test**

```python
"""The sample and legacy profiles meet the brief (datagen check exits 0)."""

import json
from pathlib import Path

import pytest

from datagen.cli import main
from neorisk_simkit.io.dataset import run_to_dataset

EX = Path(__file__).resolve().parents[3] / "examples" / "ecommerce"


@pytest.mark.parametrize("profile, overlays", [("sample", []), ("legacy", ["bounty_hunters"])])
def test_profile_passes_its_required_checks(tmp_path, profile, overlays):
    base = run_to_dataset(EX, profile, [], overlays=[], out_dir=tmp_path / "base", threads=8)
    run = (run_to_dataset(EX, profile, [], out_dir=tmp_path / "with", threads=8)
           if overlays else base)
    args = ["check", str(EX), "--profile", profile, "--run-dir", str(run.out_dir),
            "--out", str(tmp_path / "rep")]
    if overlays:
        args += ["--baseline", str(base.out_dir)]
    rc = main(args)
    checks = json.loads((tmp_path / "rep" / "checks.json").read_text())
    failing = [r for r in checks["results"] if r["required"] and r["status"] != "pass"]
    assert rc == 0, failing
```
(For `legacy`, the "base" run must disable the profile's overlays: pass `overlays=[]` explicitly and give `run_to_dataset`/`resolve_run` an `overlays=` that **replaces** the profile list when given as `[]` — implement that switch in `resolve_run` if Task 10 made it additive; `datagen run --no-overlays` exposes it on the CLI.)

- [ ] **Step 2: Calibrate** — run the test; read `checks.json`; adjust config defaults one at a time (`checkout_p` and `views_mean` for session→checkout, `add_to_cart_p` for cart sizes, initial stock/`by_weight` in `std.stock(...)` via the pack constants for out-of-stock failures, `auth_fail_p`, `return_*_p`, fulfillment delays, zipf `s` for SKU concentration, session gap Pareto for orders per shopper). Never edit `expectations.yaml` targets: if a brief rate cannot be reached by the model, stop and report it (spec §16 "fix the spec, not the expectations, unless the brief was wrong"). Record the final values and the measured metric values in `examples/ecommerce/README.md` ("Calibration" section, one table: metric, target, measured, profile).

- [ ] **Step 3: Lint and commit**

```bash
uv run ruff check $(ls -d libs apps examples/ecommerce_s1 examples/ecommerce_s2 examples/ecommerce benchmarks 2>/dev/null)
git add examples/ecommerce/specs/pack.py examples/ecommerce/datagen.toml \
  examples/ecommerce/README.md apps/datagen/tests/test_example_ecom_calibration.py
git commit -m "feat(examples): calibrate ecommerce sample and legacy profiles to the brief

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```
(Also stage `libs/simkit/src/neorisk_simkit/spec/project.py`, `apps/datagen/src/datagen/cli.py` and `run_cmds.py` if the overlay-replacement switch was added here.)

---

### Task 23: M3 exit — invariance of the pack with its overlay, and the gates re-measured

**Files:**
- Create: `libs/simkit/tests/test_exit_invariance_m3.py` (in `libs/simkit/tests` so it can use `conftest.canonicalize_ids`, like `test_exit_invariance_s2.py`)
- Modify: `benchmarks/README.md` (M3 section)

**Interfaces:**
- Consumes: everything above; `conftest.canonicalize_ids(d, created, owner_codes)` (D37 comparison: created IDs and created owners' `partition_id`s renamed, partition-free order).
- Produces: the M3 measurement table in `benchmarks/README.md`.

- [ ] **Step 1: Write the invariance exit test** — `ecommerce` + `bounty_hunters` at the Task 16 sizes: 1 vs 4 threads, `slab_bytes` 4MB vs 64KB, `step` 1d vs 12h (with `adapt=false`) give identical canonicalized events, identical label counts by role and outcome, identical machine statistics and identical `late_messages`.

```python
"""M3 exit: ecommerce + bounty_hunters is thread-, slab- and step-invariant (§10, §12)."""

import json
from pathlib import Path

import polars as pl
import pytest
from conftest import canonicalize_ids

from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.spec.project import load_project, resolve_run

EX = Path(__file__).resolve().parents[3] / "examples" / "ecommerce"
POOLS = ["engine.timer_nodes=600_000", "engine.payload_slots=100_000",
         "engine.max_messages_per_step=300_000", "budget.max_admissions_per_step=50_000",
         "budget.max_checker_keys=1_000_000"]
SMALL = ["users=3000", "skus=1200", "sku_groups=8", "run.span=14d", "run.warmup=1d", *POOLS,
         "bounty_hunters.size=8", "bounty_hunters.arrive_day=1.0",
         "bounty_hunters.arrive_span_days=3.0", "engine.adapt=false"]


def _run(tmp: Path, name: str, threads: int = 4, extra: tuple = ()):
    overrides = [*SMALL, *extra]
    res = run_to_dataset(EX, "sample", overrides, overlays=["bounty_hunters"],
                         out_dir=tmp / name, threads=threads)
    plan = resolve_run(load_project(EX), "sample", overrides,
                       overlays=["bounty_hunters"]).plan
    created = frozenset(plan.namespaces)
    codes = frozenset(p.ptype_code for p in plan.partitions if p.kind == "owner"
                      and p.table in created and p.table not in plan.member_tables)
    events = canonicalize_ids(res.out_dir, created, codes)
    labels = (pl.read_parquet(sorted((res.out_dir / "labels" / "labels_campaign")
                                     .rglob("*.parquet")))
              .group_by("role", "outcome").len().sort("role", "outcome"))
    machines = json.loads((res.out_dir / "run_stats.json").read_text())["machines"]
    return events, labels, machines, res.manifest["late_messages"]


@pytest.fixture(scope="module")
def ref(tmp_path_factory):
    return _run(tmp_path_factory.mktemp("m3inv"), "ref")


@pytest.mark.parametrize("name, threads, extra", [
    ("threads1", 1, ()),
    ("slab64k", 4, ("engine.slab_bytes=64KB",)),
    ("step12h", 4, ("engine.step=12h", "engine.step_min=1h")),
])
def test_logical_records_are_invariant(tmp_path, ref, name, threads, extra):
    events, labels, machines, late = _run(tmp_path, name, threads, extra)
    assert events == ref[0]
    assert labels.equals(ref[1])
    assert machines == ref[2] and late == ref[3]
```

- [ ] **Step 2: Gates on this machine** (D92) — warm each module first, then:
```bash
uv run --all-packages datagen benchmark benchmarks/s1.toml --out /tmp/m3_s1.json
uv run --all-packages datagen benchmark benchmarks/s2_pool.toml --out /tmp/m3_pool.json --no-gate
uv run --all-packages datagen validate examples/ecommerce_s2 --profile full   # caps only
```
Report in `benchmarks/README.md` → new section "M3 (this machine, 14 cores / 36 GiB)": S1 warm seconds and peak RSS against ≤ 60 s / ≤ 16 GB with the verdict; s2_pool `events_per_second`, `shard_events_per_second`, `shard_command_share` with the D55 verdicts exactly as S2 worded them (part (1) stays UNMET pending the user's decision — open item); s2 full "not measured — needs the 64 GB reference machine" with the caps total from validate; the S1 reduced-profile hash after Task 12 and its warm time; for each, the change from the S2 numbers and the stage that moved (generate, merge, checks, export) when one did. Never relax a gate or shrink a workload; a failing S1 gate is reported with its stage and left failing for the milestone review.

- [ ] **Step 3: Lint and commit**

```bash
uv run ruff check $(ls -d libs apps examples/ecommerce_s1 examples/ecommerce_s2 examples/ecommerce benchmarks 2>/dev/null)
git add libs/simkit/tests/test_exit_invariance_m3.py benchmarks/README.md
git commit -m "test(exit): M3 invariance of ecommerce + bounty_hunters; gates re-measured (D92)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

**Milestone final review (not a task; D90):** once, after Task 23, run the checked engine on the machine fixtures (`mx_basic`, `mx_family`, `mx_pay`), `campaign_trace`, and the Task 16 `SMALL` ecommerce + overlay run, and compare them with the plain runs (identical logical records); budget a night for the checked cold compile of the ecommerce module (S2 measured ~8 h for ecommerce_s2).

---

## Gates (M3)

| Gate | Source | Where measured | Verdict rule |
|---|---|---|---|
| None new | §18 sets no M3 gate | — | — |
| S1 `benchmarks/s1.toml` ≤ 60 s warm, ≤ 16 GB | §18 S1 | Task 23 | pass/fail as measured; never relaxed |
| s2_pool shard path ≥ 80k events/s; end to end ≥ 80k with `shard_command_share ≥ 0.5` (D55) | §18 S2 | Task 23 | as S2 worded it; part (1) stays an open user decision |
| s2 ≤ 10 min warm | §18 S2 | not on this machine | "not measured — needs the 64 GB reference machine" |
| S1 reduced-profile hash | process | after every task | unchanged except Task 12 (new hash recorded) |

## Open items carried (user decisions; M3 does not resolve them)

- **s2_pool D55 part (1):** `shard_command_share ≥ 0.5` is unreachable with the S2 kernel shape (CART = 4: ~0.46 at most; measured 0.17). Options recorded at S2: accept a lower share threshold, or a shard-heavier pool workload. M3 does not change `examples/ecommerce_s2` (D36); a shard-heavier workload could later reuse the `bounty_hunters` overlay on `examples/ecommerce`, which M3 makes possible but does not gate.
- **s2 full:** unmeasured here (caps ~35 GiB > ~30 GiB usable of 36 GiB), and its expectations conflict (`exported_events` 10⁸ ± 5% vs `payments` 3·10⁷ ⇒ ≥ ~115M events; `postings_per_payment_event` 2.374 vs 2.4–2.6). Needs the 64 GB machine and new bands from the user.

## Deferred

Every item S2 and S1 deferred to M3, with its fate; then new deferrals.

**S2 → M3 (S2 plan "Deferred", M3 bullet)**
- Spawn as a machine operation (same-owner children and new owners) → Tasks 7, 8 (`spawn` op, `std.spawn`, `std.create_owner`).
- `join` with timeout → Task 7 (D69: a join requires a `timer=`; duplicates, late policy, zero children).
- Owner-to-owner messages (D57) → Task 2 (D73) and Task 15 (`inviter_credit`).
- Dispute child kernels via `spawn` (D51) → Task 8 (`mx_pay`: the payment spawns a `dispute` child and joins on it). `examples/ecommerce_s2` keeps its in-kernel dispute (frozen slice, D36); `examples/payments` adopts the machine form in M4.
- Bounty-hunter overlay with base-schema parity, cohorts, `suppress`, labels and the interference report (D52, F-08) → Tasks 10, 11, 16, 17. S2's "1% of users" approximation is gone: cohort members are user rows (entities/user, `origin = "member"`).
- Per-process `max_spawn_depth` with a runtime counter (F-04) → Task 1 (D72); machine instances: Task 7.
- `law.sum_le` with a state column on the right (F-07) → Task 13 (D81).
- Request and join timeouts → Task 8 (request, D67) and Task 7 (join).
- Statistical checks and `expectations.yaml` → Task 18; `datagen check`, `report.html`, `checks.json` → Task 19.
- `cause_id` population (D14) → Task 12 (D80).

**S1 → M3 (S1 plan "Deferred", M3 bullets) not listed above**
- State machines and the generated dispatch module → Tasks 5–9 (`datagen validate --dump-machines`).
- `p.expose` / `expose_param` → Task 10; `p.expose_owner` (the execution-owner extension point) → Task 3.
- The full `examples/ecommerce` pack at parity → Tasks 14–16, 20, 22; legacy adapter `datagen export --legacy-fraud` → Task 20; replacing `scenarios/fraud.generate` → Task 21.
- Instance kernels over child rows (D16) → **re-deferred to Later**: M3 models per-item lifecycles as created owners (`order`) with machines, and per-instance data as machine instance fields; reading child rows back is not needed by any M3 consumer.
- Flash-sale overlay → **Later** (D93): needs `existing=True` cohorts of base owners and shard-state hooks (`pick_skus`, `adjust_stock`); not in §18's M3 row.
- CODEOWNERS rule (§16) → **left to the user**: the repo records no GitHub team or reviewer handle to name. The one line to add, with the handle filled in: `examples/*/specs/expectations.yaml libs/simkit/src/neorisk_simkit/checks/domains/ @<reviewer-or-team>` in `.github/CODEOWNERS`.
- Cross-owner enrichment (`p.feature`, rolling reducers on merged step output) and `golden/` → **re-deferred to M4** (with the bench generic loader that reads native datasets): in M3 the only golden consumer is the legacy adapter, which computes its golden columns in batch from the exported events (D87). `p.feature` keeps raising "arrives in M4".
- Scorer changes (frozen sample-fit model) and `attributes.sample_timeline` rework → **Later**: M3 labels are the overlay's ground truth, so no scorer runs; engine attributes come from population draws and change groups.

**New deferrals**
- **M4**: label maturity in the legacy adapter and in bench splits (D87 ignores `label_available_at`); `labels/` as `labels/part-*.parquet` if the user prefers the §13 layout over per-step files (D76); machines handling owner-to-owner messages directly (`on_message` on a machine; kernels handle them in M3).
- **Later**: machines on shards (D62); `existing=True` cohorts; held-out-seed confidence intervals (D85); exact 2^20 generation wrap guard (D64); more than 16 machines per partition, 32 states per machine or 64 instances per machine (D63–D65 bounds); request timers that fire while suspended (blocking suspension, D67).

## Self-review notes (planner)

- **Spec coverage (§18 M3):** state machine with all operations → Tasks 5–9 (branch/timer/then: 6; repeat/until/spawn/join: 7; request/create_owner: 8; exits: 9); e-commerce pack at parity through the legacy adapter → Tasks 14–16, 20, 22; bounty-hunter overlay replaces the fraud scenario → Tasks 16, 21; overlay contract → Tasks 3, 4, 10, 17 (all nine rows: size/share/rate + own namespace (10, D75), same schema (10, D95), suppress (10), extension points (3, 10), join (7), no cross-owner cycle (10, campaign owner), pool (14–16), labels (4, 10), regression (17)); campaign trace → Task 11; interference report → Tasks 17, 19.
- **Interfaces checked across tasks:** `KernelSpec.source` (5 → 6), `ActionSpec`/`ActionRef` (5 → 6, 14), `MachineDef` fields incl. `member_table`, `root_member`, `member_values`, `root_init`, `labels`, `label_delay` (5, 10), `_Gen` hooks (6 → 7, 8, 10), tag layout and ops (6 → 7, 8), `Plan.cohorts`/`overlays`/`exposed`/`exposed_owners`/`member_tables` (3, 10 → 17–20), `ref_bounds` tuple form (3), `label_counts` (4 → 10, 16, 19), `run_stats.json["machines"]` (6 → 7, 8, 11, 14, 19, 23), `RT_O2O`/`RT_BND_O2O` (2 → 12), node `cpid`/`ceid` (12), `compare` keys (17 → 18, 19), `evaluate` rows (18 → 19, 22), `legacy_fraud` (20 → 21).
- **Known risks during execution:** (1) compile time — the ecommerce module (base and base+overlay) compiles twice per engine change; engine work is front-loaded into Tasks 1–12 and examples tasks do not touch the engine. (2) Generated code size of `mx_campaign` (two machines, ~12 transitions) is far below S2's hand kernels; if lowering hits a Numba typing limit (e.g. heterogeneous returns in `mx_enter_*`), make every generated function return `COMMIT`/`None` consistently. (3) The adapter's bad rate depends on cohort size vs base activity; `legacy` profile's `bounty_hunters.size` is the knob (Task 22). (4) `test_legacy_fraud_parity.py` and the bench conftest each run the `legacy` profile once per session (~1–2 min each warm).
