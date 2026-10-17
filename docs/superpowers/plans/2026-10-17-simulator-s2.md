# Agentic Event Simulator — Milestone S2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship milestone S2, the shard slice: payments with refunds and disputes, multi-SKU reservations with a TTL, a hot SKU group and a capped bonus pool; rounds at scale, cross-partition laws, reference kernel tests and mutation tests; and `benchmarks/s2.toml` (≤ 10 min warm) and `benchmarks/s2_pool.toml` (shard path ≥ 80k events/s, gated both end to end and on shard-phase time, D55) measured and reported.

**Architecture:** The engine closes the obligations S1 left open: seal remaps handles held by shards, responses are tagged explicitly and every request is answered exactly once, step length adapts on the rows the cap counts, and created owners are admitted by generated compiled code inside the compiled round loop. The spec layer gains postings, accumulators, evaluated laws (`checks/laws.py`) and static spawn bounds. `std` gains `reservations` and `capped_pool`. A new project `examples/ecommerce_s2/` (users, payments, inventory, a global bonus pool, bounty-hunter campaigns) is the slice the S2 workloads run.

**Tech Stack:** Python 3.12, uv workspace, numba, numpy, pyarrow, polars, duckdb (tests only), pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-10-15-agentic-event-simulator-architecture.html` (binding; §18 defines S2, §17 the module layout). Read §05, §06, §07, §09, §10, §11, §12, §13 before any task. The S1 plan `docs/superpowers/plans/2026-10-16-simulator-s1.md` (Global Constraints, D1–D35, Engine reference) stays binding wherever this plan does not amend it.

## Global Constraints

Every task implicitly includes this section. Values are copied from the spec; do not change them.

**Repo (unchanged from S1 unless stated)**
- Python `>=3.12`; ruff `line-length = 100`. Every task's lint step uses exactly: `uv run ruff check $(ls -d libs apps examples/ecommerce_s1 examples/ecommerce_s2 benchmarks 2>/dev/null)` (`examples/ecommerce_s2` exists from Task 12).
- Run tests with `uv run --all-packages pytest ...`; the full suite `uv run --all-packages pytest` must keep passing after every task.
- Test file basenames are unique across the repo; no `__init__.py` in test dirs. Fixture projects live in `libs/simkit/tests/fixtures/<name>/` (`datagen.toml` + `specs/pack.py` + `specs/kernels.py`).
- Kernel modules (`specs/kernels.py`) import only `from neorisk_simkit import std` and `from neorisk_simkit.engine import ...`; module-level `Local(...)` / `std.<x>(...)` calls are allowed only outside kernel bodies (S1 contract, Task 6).
- No new runtime dependencies. `confluent-kafka` is not added in S2.
- Commit messages end with:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN
  ```

**S2 scope (§18, verbatim)**
- "Shard slice: payments with refunds and disputes, multi-SKU reservations, a hot SKU group, a capped bonus pool. Rounds at scale, reservations with TTL, cross-partition laws, reference kernel tests, mutation tests. Gates: s2.toml ≤ 10 min warm; s2_pool.toml shard path ≥ 80k events/s."

**Execution model (§06, verbatim where quoted)**
- "Multi-shard decisions use reservations, never merging. A cart with three SKUs in three inventory shards sends three reserve requests, joins on the responses, then commits all or releases all. Reservations carry a TTL, so a shard frees units if the commit never arrives. Shards stay small; nothing spreads transitively."
- "Joint constraints use holds. If a decision needs both owner and shard state ..., the owner first places a hold on its own state, the shard decides on its own, and the owner then commits or releases the hold."
- "Creating an owner (checkout creates a payment) is a creation message. The new owner starts at its creation time in the next round of the same step."
- "Spawn bounds. Each process declares max_spawn_depth (default 3), and each step has a max_admissions limit. Exceeding either fails the run with a diagnostic naming the process."
- "Shard-internal processes. Matching, block building and pool accounting run inside their shard, which executes its own heap in canonical order. Requests enter that heap as commands." §07: "Because claims go through the pool's own heap, the cap is exact."
- Every S1 rule stays: blocking suspension, requests dated exactly `ctx.t`, `H = min(step end, min(t_req + δ), min(t_create))` (D5), `lamport = max(partition_clock, cause_lamport) + 1`, canonical key `(event_time, lamport, partition_id, seq)`.

**Domain rows (§09, verbatim)**
- Auth, capture, refund, dispute: "Owner = payment; dispute is a child process | Capture races expiry. Refund holds, then commits or releases, against the remaining amount. Refunds rejected while a dispute is open. Repeated idempotency keys return the first result | Settlement totals accumulate; netting out of scope".
- Multi-SKU checkout: "Owner = user; inventory shard per SKU group | Reserve in each shard, join, commit all or release all; TTL frees units".

**Performance and workloads (§10, verbatim)**
- Rates: owner-dominated end to end ≥ 167k/s (10⁸ ≤ 10 min); shard-dominated end to end 80–300k/s; generation only 0.5–3M/s; merge, enrichment, checks, export (each) 0.25–2M/s.
- "S2: 20M users, 30M payments, 10⁸ exported events, 2.5 postings per payment event, 90-day dispute timers, one hot SKU group taking 5% of checkouts."
- "S2-pool: a global capped bonus pool that every referral claim reaches, with the bounty-hunter overlay at 1% of users."
- "Accounting: exported events, histories, cases, snapshots, postings and labels are counted separately. Timing runs from engine start with a warm JIT cache to manifest.json written; cold compile is timed separately. Numba plus Polars threads are capped at 16."
- "Also verified: identical logical records across 1, 4 and 16 threads, two slab sizes and two step lengths."
- Memory items (names used in code): `output_slabs`, `step_output`, `merge_working_space`, `live_partition_state`, `timer_heaps`, `requests_and_inboxes`, `fanout_bursts`, `read_inputs`, `checker_state` ("keyed aggregates × bytes per key, by dense index"), `scorer`, plus `entity_buffers` (added by the S1 fix round, 6fdb05e: row groups buffered by the streaming entity writer; every S2 caps table and budget check includes it). Every item has a hard cap enforced at runtime; a run whose caps exceed the budget is refused up front; v1 has no spilling.
- Gates are measured on the available machine with `threads = min(16, os.cpu_count())` and the report flags non-reference hardware (S1 D30). A gate is never relaxed and a workload never shrunk to pass; a failing measurement is reported with the stage that misses its §10 band.

**Checks (§11, verbatim)**
- Per-partition laws: "Each partition's records in execution order | ... | Lifecycle legality, refunds ≤ captured, holds resolved, balances never negative, nonce sequence".
- Cross-partition laws: "Merged step stream in canonical order | Keyed reducers carried across steps | Every reservation committed or released by TTL; pool grants ≤ cap; request/response pairing".
- "Failures cite (partition_id, seq) and action ID". "Reference implementations for matching, the L1 envelope and holds run against the real kernels on fixtures in CI. Mutation tests and forced-path fixtures run in CI."
- Structural: "referential integrity uses a bitset over dense indices".

**Output (§13)**
- `postings/` is "optional, kept apart from events (no label leakage)"; postings are counted apart from exported events. Amounts are int64 at a declared per-asset quantum.

**Validate (§16):** "validate reports structural contradictions only: cross-partition writes, δ = 0 boundaries, unbounded spawns, caps over budget. It never claims stochastic feasibility."

## Decisions made by the planner

Where the spec is silent or ambiguous; each line is binding for this plan. Numbering continues from the S1 plan.

- **D36** S2 runs a new slice project `examples/ecommerce_s2/` (owners `user`, `payment` (created), `campaign`; shards `inventory`, `pool`). `examples/ecommerce_s1/` and its S1 gate stay; `examples/ecommerce/` and `examples/payments/` remain the M3/M4 targets, untouched.
- **D37** BASE is `f3a5582`: the S1 final-fix wave (`230a571..4705e40`, contracts "Final-fix" entries) plus the S1 Codex fix round (`f35b683` dense IDs by §12 again, `8f0d693` incremental created-row index, `6fdb05e` `entity_buffers` cap item, `f3a5582` distribution bounds). A created owner's instance key is `mix(creator inst, cause lamport, ns code, k)` with `k` its ordinal within the creating commit (contracts C1); `route.safe_horizon` is gone (`route.horizon` is the formula). The fix wave's creation-key ranking of created-owner dense IDs is reverted at BASE (contracts CX1; `seal._owner_dense`, `World.created_causes` and `World.take_created_causes` no longer exist): spec §12 binds dense indices of **every** table, created owners included, "by prefix sum over partitions in partition_id order, then local ordinal" (`identity.assign_dense(pid, ordinal)`), where a creator that was itself created in the same step ranks by its provisional handle (bit 62 set, so after every dense creator). §12 step invariance is read as **identical logical records as a multiset after ID canonicalization**: created-owner IDs and `partition_id`s may differ across step lengths, and exact `(event_time, lamport)` ties between different created owners may reorder; values must not. The comparison is `canonicalize_ids(d, created, owner_codes)` as landed (moved to `conftest.py` by Task 18).
- **D38** Seal remaps provisional handles in shard state fields typed `ref` / `ref[<items>]`, in `ref` fields of shard processes' `Local`, and in payload column 9 (`src_self_id`, read as `cmd.sender`) of every queued command at a touched slot. Shard state accepts the type `ref` (int64, initial value `std.NULL`). Shard `Local` bytes count toward `live_partition_state`.
- **D39** Explicit response tagging: on delivery `route_outbox` writes the delivered kind (`OB_REQUEST`, `OB_MESSAGE`, `OB_RESPONSE`) into payload column 11 (`cmdq.PAY_KIND`) of the receiver's payload row, after the response's generation check has consumed the generation that column carried in the outbox. `resume_owner(P, pay_rows, qhead, g)` treats a node as a response iff its payload row has `PAY_KIND == OB_RESPONSE`.
- **D40** Request/response pairing is enforced at runtime: a command whose payload row has `PAY_KIND == OB_REQUEST` must COMMIT with exactly one `OB_RESPONSE` row in its outbox; any other command must emit none. A violation raises `EngineError` naming process and boundary. Per request boundary the run reports `{"requests": delivered, "responses": routed}` (`World.stats["pairing"]`, manifest `pairing`). `cause_id` stays null (re-deferred, see Deferred).
- **D41** Step-length adaptation targets 25% of `max_step_rows` on the rows the cap counts: everything flushed in the step (records, created rows and `p.ids` allocations; `SealedStep.stats["counted_rows"]`). S1 step boundaries, hence S1 dataset bytes, change once; Task 21 re-measures the S1 gate.
- **D42** Spawn bounds are static. `validate` builds the owner-creation graph (partition `P` → owner partition `Q` when a process of `P` reserves `creates` of `Q`'s table); a cycle is an "unbounded spawn" error, and the longest chain (in creation edges) must be ≤ `budget.max_spawn_depth`; both errors name the processes on the path. On an acyclic graph the static bound is exact, so there is no runtime depth counter. `max_admissions_per_step` stays a runtime cap naming the creating process. *Spec deviation (F-04):* §06 gives each process its own `max_spawn_depth` (default 3) and fails at runtime on excess; S2 uses one budget-wide static depth and refuses every creation cycle at validate, including recursion that would stay within the depth at runtime (§16 does let validate report "unbounded spawns"; no S2 workload needs a cycle). Per-process depth and a runtime depth counter are Deferred (M3, with `spawn`).
- **D43** A created owner's initial state travels in its `OB_CREATE` payload (user columns 0..6), so admission never reads create slabs: a created owner table has at most 7 columns, none of kind `f64` or `text` (validate). Create rows carry the creator's commit lamport (`slabs.CREATE_HEAD` gains `lamport`). Admission no longer reads create slabs, so S1's incremental create-slab index (`World._created_rows`, `_CreatedIndex`, `World._created_index`, the `World.created_rows_indexed` counter, 8f0d693) is deleted by Task 4. Creation messages are counted in `requests` automatically: `out.reserve(creates={<owner table>: n})` also reserves `n` outbox rows (Task 4; an S1 fixture that forgot the unit overflowed a 4 KiB outbox silently outside checked mode).
- **D44** Admission of created owners is generated compiled code: `admit_created(W, R, CQ, FS, limit_t, out_slots)` (admissions so far and the limit are `R[RT_ADM]`). It admits due creations in Task 4b's sender-key order, all or nothing with respect to command nodes (F-10), with each row's `k` computed by `route_outbox` and stored in `CQ`. Creation rows wait in a compiled pending-creation queue `CQ` (capacity `budget.max_admissions_per_step`); free local slots live in a `FreeSlots` ring per owner type (FIFO, exactly the S1 order). `drain_small_rounds` admits inside the compiled loop (phase `PH_ADMIT`), Python rounds call the same function, and admitted owners join the woken list. CQ bytes count toward `requests_and_inboxes`.
- **D45** Postings: `p.postings(name, *, cols, owner=None, shard=None, doc="")` declares an append-only posting table with the 8 common columns first. Kernels write it with `out.emit_<name>(t, ...)`, reserved under `records`. It is written to `postings/<name>/date=YYYY-MM-DD/step-NNNNNN.parquet`, counted in manifest `posting_counts` (never in `counts` or `exported_events`), typed `"posting"` in `schema.json`, absent from `_index/steps.parquet` and never replayed. One posting transaction is one commit, `(partition_id, lamport)`.
- **D46** Accumulators: `p.accumulator(name, ltype)` with `ltype.kind` in `{"i64", "amount"}`; kernels call `out.add_<name>(value)` (checked int64 add, commit phase only; checked mode treats it as a write). Each worker keeps a partial sum; seal folds them into the step's delta. Kernels cannot read an accumulator. Manifest `accumulators` holds totals over exported steps; `_index/steps.parquet` gets `acc__<name>` per step (0 for warm-up steps).
- **D47** Laws are evaluated at seal by `checks/laws.py` (`LawBook`), in canonical order, with keyed state carried across steps and capped at `budget.max_checker_keys` (default 50,000,000 keys × 24 B = `checker_state`). §11 reducers are "initialized from the opening snapshot" (F-01): every warm-up step is fed too, `LawBook.step(sealed, world, exported=False)`, with the rows of the event and posting tables the checks read (`SealedStep.warmup_rows`, built by seal before D20 drops warm-up rows). A warm-up step updates running totals (`total_le`, `sum_le`), `at_most_once` key sets and open `resolved` keys, but counts nothing in `checked` and never raises or counts a violation; only exported rows are judged and cited. State laws and `balanced` (no carried state) skip warm-up steps. Path forms: `<event or posting>.<column>`, or `<owner table>.<column>` / `<shard>.<state field>` (state is checked at every exported seal over live partitions). `sum_le` takes event columns on both sides (*spec deviation, F-07:* the spec's own example `law.sum_le("refund.amount", "payment.captured", by="payment_id")` has a state column on the right; a state-column right side is Deferred, M3 parity). New laws: `law.total_le(lhs, limit)` and `law.balanced(table, *, amount, side, by)`. A required violation raises `LawViolation` (exit code 4) citing `(partition_id, seq)` and `action_id`; a non-required one is counted in manifest `laws`. A `resolved(..., within=)` key still open at the end of the run whose deadline is at or after the end is censored (reported), not a violation.
- **D48** Referential integrity is a range check on dense values before public IDs are drawn (`ref_in_range`): dense indices are contiguous and rows are never deleted, so `0 ≤ v < rows known for the target` (population owners admitted so far, `pop.next`; static rows; or `id_bases[ns]` after the step) is exact; no bitset is needed. *Spec deviation (F-05):* §11 specifies "a bitset over dense indices"; the range form is equivalent here and is recorded as a deviation. Population refs are bounded by `pop.next`, not by `n`, so a ref to an owner that has not arrived yet is caught.
- **D49** Reservations: each inventory shard keeps a fixed hold table in its process `Local` (`std.reservations.fields(64)`: `res_hold`, `res_item`, `res_qty`, `res_ckt`). Hold IDs come from `p.ids("hold")`, created by the shard; the TTL is a shard timer tagged with the hold ID. A full table rejects the line with reason `busy`. A commit for a hold that already expired emits `stock_commit_late` and leaves stock untouched; a late release is a stale reject. At an equal instant a commit (message priority 1) runs before the TTL timer (priority 5).
- **D50** The join over N reserve responses uses blocking suspension (`pending = N`; all responses run first on resume, S1 Task 10 ruling). Join and request timeouts stay M3.
- **D51** A dispute is a sub-lifecycle inside the payment kernel (its own `Local` fields and commands). Separate child kernels started by `spawn` are an M3 machine operation (§04).
- **D52** Bounty hunters in S2 are a plain `campaign` owner partition with a handwritten kernel: one hunter and its zombie members (`p.ids("member")`) are one owner, the population sized so hunters plus zombies are `hunt.share` (1%) of users. The overlay mechanism and schema parity with base events are M3. *Approximation (F-08, with D51 and D57):* "1% of users" is approximated by (campaigns + members) ÷ users; the S2-pool README section states this next to `campaign_member_share` (Task 21). All three approximations are listed under Deferred, M3.
- **D53** Hot SKU group: `std.catalog(..., hot_rows=K)` puts catalog rows `[0, K)` in SKU group 0 (other rows draw from `group`, which the pack sets to `uniform_int(1, G - 1)`); a view picks a hot SKU with probability `journey.hot_pick_p`. "5% of checkouts" is measured on checkouts (F-02): `hot_share_of_checkouts` = checkouts with at least one line in group 0 ÷ `checkout_started`, both over exported steps. The shopper counts the numerator in the accumulator `hot_checkouts` (Task 12: `out.add_hot_checkouts(1)` when a started checkout sends a reserve to group 0; every line of a started checkout sends one reserve, so this equals "checkouts with at least one reserve to group 0"). Group 0's share of reserve requests (`hot_share_of_reserves`) is reported as information only.
- **D54** "30M payments" with 10⁸ exported events leaves about 3 events per payment, so payments come from checkouts (`origin = "checkout"`) and from bill payments (`origin = "bill"`), both created by users as owners. A payment's lifecycle state lives in its process `Local` (D43 limits the table to 7 columns).
- **D55** (controller ruling F-03) The s2_pool gate is two gates, both ≥ 80,000 and both required: (1) end to end, `events_per_second` (exported events ÷ warm `engine_seconds`, §10's "shard-dominated, end to end" band 80–300k/s) on a workload whose expectation `shard_command_share ≥ 0.5` (shard commands ÷ all commands, whole run) makes it actually shard-dominated — the `pool` profile is calibrated until it reaches that share; (2) the shard path (§18 "s2_pool.toml shard path ≥ 80k events/s"), `shard_events_per_second` = exported events emitted by shard partitions ÷ seconds spent in shard phases of exported steps (Task 19). Both rates are reported in the benchmark output and `benchmarks/README.md`. Gating both never relaxes either reading of the spec.
- **D56** Benchmark expectations add `{ at_least = x }` and `{ at_most = x }`; gates add `min_events_per_second` and `min_shard_events_per_second`. Derived values: `inventory_share_of_proposals` (S1), `payments`, `postings_per_payment_event`, `hot_share_of_checkouts` (gated, F-02), `hot_share_of_reserves` (information), `shard_command_share`, `campaign_member_share`. Each derived value takes numerator and denominator from the same counting window (F-25): exported steps for `payments`, `postings_per_payment_event` and `hot_share_of_checkouts`; the whole run (warm-up included) for `shard_command_share`, `hot_share_of_reserves` and `campaign_member_share`; `benchmarks/README.md` states each window.
- **D57** Owner-to-owner messages are re-deferred to M3: no S2 workload needs them (campaign members share their owner; the pool pays claimants through responses), their first consumer is the M3 overlay ("inviter credited when invitee qualifies"), and they need an owner-id → slot index that M3 owns. validate keeps refusing them, now with "owner-to-owner messages arrive in M3".
- **D58** `datagen run` and the benchmark child exit 4 when a required law is violated (`LawViolation`); D35's 0/1/2/3 are unchanged.
- **D59** Workload spans (the spec fixes actors and counts, not spans): `s2.toml` runs `examples/ecommerce_s2` profile `full` (20M users, 90 days, 14-day warm-up); `s2_pool.toml` runs profile `pool` (2M users, 30 days, 3-day warm-up, ~10⁷ exported events).
- **D61** Shard-side processing results must not depend on step length (the open item of the S1 final fix, under D37's multiset reading). The order in which a shard processes tied commands decides results (which claim takes the pool's last unit, which reserve gets the last item), and routing breaks `(time, prio, cause)` ties by sender. A created owner's `partition_id` is step-dependent (a provisional handle in its creation step, a per-step dense index afterwards), so routing never uses it: routing sorts outbox rows by `(time, prio, cause, sender key, src_seq)` and admission sorts creations the same way. The sender key is step-invariant: for partitions of a non-created type (population owners, shards) `(ptype, 0, pid, 0, 0, 0)`; for a created owner, for its whole life, `(ptype, 1, created_at, creator commit lamport, creator inst, k)` read from a hidden array `ckey int64[G, 4]` written at admission (`creator inst` is the creator's step-invariant instance key; `k` the ordinal within the creating commit, as in the RNG key). Two created senders tie on the key only if two creators with equal instance keys (a 2⁻⁶⁴ hash collision) create at the same instant with the same lamport; `src_seq` then still orders them deterministically.
- **D60** `rng.normal`'s `log(1 - u)` (kernels) vs `dist`'s `log1p(-u)` (pack-time) stays as is: the two sides draw from different streams, each is bit-identical compiled and uncompiled, and changing either alters outputs for no gain (closes the S1 Task 5 minor "decide in S2").

## Review Focus

Inputs the spec implies but no exit test names; each line has a pinning test in the owning task.
1. **Handles that outlive their step inside a shard:** a hold or checkout ID created just before a step boundary and committed, released, expired or echoed after it — the shard must emit the final ID, never fail with "unresolved handle" (Task 1, Task 12).
2. **Carts that are not "all granted or all rejected":** two lines in the same shard, one line rejected while others are granted (release only the granted ones), a full hold table (`busy`), an abandoned checkout (TTL expiry exactly `hold_ttl_s` after the reserve), a commit arriving after the TTL (`stock_commit_late`, stock untouched) (Tasks 12, 16).
3. **Exact cap edges:** a claim equal to the remaining pool is granted, one cent more is rejected, and the total granted never exceeds the cap even when hunters and normal users claim at the same instant (Tasks 15, 16, 17).
4. **Refund edges:** a refund for exactly the remaining amount, a second refund while the first hold is unsettled, a duplicate idempotency key after the first refund settled or failed (returns the first result), a refund while a dispute is open (Tasks 14, 16).
5. **Empty and censored runs:** a run with zero payments or zero claims passes every law vacuously (`checked = 0`), writes `posting_counts` with zeros and accumulators at 0; a hold whose TTL deadline falls after the run's end is censored, not a violation (Tasks 7, 9, 10).

## Engine reference deltas (shared by Tasks 1–5, 19)

Everything in the S1 plan's Engine reference stays except:
- **Payload arena** `pay int64[payload_slots, 12]`: columns 0..6 user payload; 7 `src_g`; 8 `src_gen`; 9 `src_self_id` (remapped at seal, D38); 10 `src_action`; 11 `PAY_KIND` once delivered (D39; in the outbox it still carries the requester generation of a response).
- **Create buffers**: `CREATE_HEAD = (handle, pid, ordinal, created_at, g, lamport)` (D43).
- **Reservations**: `out.reserve(creates={<owner table>: n})` also reserves `n` `requests` outbox rows for the creation messages (Task 4): generated `_reserve_<proc>` checks and records `vec[requests] + Σ vec[creates:<owner table>]`. `requests=` in kernels counts requests, messages and responses only (kernels that still add the creation unit by hand over-reserve, which is harmless). validate refuses a process whose declared `max.requests` plus owner-table `max.creates` exceeds the outbox capacity.
- **`out` tuple tail**: `OUT_TAIL = ("outbox", "lat", "shard_n", "seed", "cmd_kind", "acc")`; `acc` is `int64[max(1, n_accumulators)]` per worker (D46).
- **Route tuple** `R`: appended `RT_BND_RESP` (int64[boundaries], responses routed per boundary), `RT_SHARD_REQ` (int64[max(1, G − shard_lo)], requests delivered per shard slot) and `RT_SHARD_LO` (int64[1] = shard_lo), indices 22, 23, 24 (Task 2); `RT_HID` (tuple view of the hidden `ptype`, `pid`, `ckey`) and `RT_CREATED_TYPE` (uint8[32]), 25 and 26 (Task 4b); `RT_ADM` (int64[2] = admissions this step, limit), 27 (Task 5). `route_order(ob, n, R)` sorts by `(time, prio, cause, sender_keys(src_g), src_seq)` (D61). `route_outbox(R, CQ, ob, n)` replaces `skip_creates`; its statuses are `ROUTED, NEED_MESSAGES, NEED_NODES, NEED_PAYLOAD, NEED_CREATES` (0..4; `NEED_CREATES` replaces `HAS_CREATE`) and it returns `(status, k)` where for `NEED_CREATES` `k` is the outbox row that did not fit.
- **Pending-creation queue** `CQ` (`engine/admit.py`): `(time, prio, cause, src_pid, src_seq, ns, handle, src_g, action, k, pay int64[C, 7], n int64[1])`, `C = budget.max_admissions_per_step`; `k` (the row's ordinal within its creating commit) is computed by `route_outbox` when it queues the row (F-10); `cq_min(CQ)` is its earliest time (I64_MAX when empty).
- **Free slots** `FS` (`engine/admit.py`, `FreeSlots.as_tuple()`): `(buf int32[Σ owner max_live], head int64[T], n int64[T], off int64[T], cap int64[T], base int64[T])`, `T` = owner partition types in plan order.
- **Admission statuses**: `ADM_OK, ADM_CAP, ADM_LIVE, ADM_NODES = 0, 1, 2, 3`; round phase `PH_ADMIT = 4`. `ADM_NODES` admits nothing (all or nothing, F-10).
- **Round state**: `RS_SHARD_NS` (Task 19), nanoseconds spent in shard phases this step (compiled drain and Python rounds), read into `RoundStats.shard_ns`.
- **Hidden arrays**: one addition, `("ckey", "int64", 4)` — a created owner's step-invariant sender key `(created_at, creator commit lamport, creator inst, k)`, written at admission and used for the owner's whole life (D61); zero for population owners and shards. No runtime spawn depth (D42).

## File structure

```
benchmarks/s2.toml  benchmarks/s2_pool.toml  benchmarks/README.md (S2 sections, results)
examples/README.md                              # one row for ecommerce_s2
examples/ecommerce_s2/                          # D36
  README.md  datagen.toml  specs/{brief.md,pack.py,kernels.py}  out/ reports/ logs/ (.gitkeep)
libs/simkit/src/neorisk_simkit/
  spec/{pack,plan,law,validate,caps,project}.py           # postings, accumulators, laws, spawn bounds
  engine/{cmdq,route,slabs,layout,lower,codegen,world,rounds,run,errors,rng}.py
  engine/admit.py                                         # CQ, FreeSlots (D44)
  std/{__init__,sources,reservations,capped_pool}.py
  checks/{structural,laws,reference}.py
  io/{seal,writer,manifest,step_index,dataset,read,consts}.py  io/schema/{schema_json,sql}.py
  io/replay/*                                             # io constants (Task 6)
libs/simkit/tests/
  conftest.py                                  # created_namespaces, canonicalize_ids (Task 18)
  fixtures/{holder,pairing,chain,relay,ledger,mutants}/
  test_engine_seal_shards.py test_engine_pairing.py test_engine_admit.py test_spec_postings.py
  test_spec_accumulators.py test_std_reservations.py test_checks_laws.py
  test_checks_laws_keyed.py test_checks_refs.py test_exit_mutants.py test_exit_invariance_s2.py
  test_engine_shard_stats.py
apps/datagen/src/datagen/{run_cmds,benchmark}.py
apps/datagen/tests/{test_example_ecom_s2.py,test_example_ecom_s2_payments.py,
                    test_example_ecom_s2_refunds.py,test_example_ecom_s2_pool.py,
                    test_reference_kernels_s2.py,test_benchmark_s2.py}
```

Task dependency order: execute in numeric order. Task 4b runs between 4 and 5. Hard dependencies: 1 → 2 → 3 → 4 → 4b → 5 are linear (all touch the seal / route / codegen seams); 6, 7 need 5; 8 needs 1; 9 needs 6; 10 needs 9; 11 needs 9; 12 needs 2, 5, 8, 10; 13 needs 6, 7, 12; 14 needs 13; 15 needs 14; 16, 17, 18 need 15; 19 needs 5; 20 needs 15 and 19; 21 needs 20; 22 runs only if Task 21 reports a gate `fail`.

---

### Task 1: Seal remaps handles held by shards (state, `Local`, payload column 9)

The first engine task (controller ruling of the S1 final review): S1's seal remaps owners only.

**Files:**
- Create: `libs/simkit/tests/fixtures/holder/{datagen.toml,specs/pack.py,specs/kernels.py}`
- Modify: `libs/simkit/src/neorisk_simkit/spec/pack.py` (`_STATE_RE` accepts `ref`), `engine/world.py` (`_shard_state`: a `ref` field without init starts at `std.NULL`), `io/seal.py` (`_remap_world`: shard state, shard locals, payload column 9), `spec/caps.py` (`_live_state` counts shard `Local` bytes)
- Test: `libs/simkit/tests/test_engine_seal_shards.py`

**Interfaces:**
- Consumes: S1 `seal._Remap.apply_copy`, `World.touched`, `World.state[<shard>]`, `World.locals[<process>]`, `World.payload.rows`.
- Produces:
  - Shard state declarations `"ref"` and `"ref[<items>]"` (int64; initial `std.NULL` unless `init` gives values).
  - `seal._remap_world(world, remap)` also remaps, for every touched shard slot: each `ref` state field (scalar fields at the shard index; per-item fields over the shard's item range `offs[i]:offs[i+1]`), each `ref` field of the `Local` of every process of that shard, and column 9 of the payload rows of every queued command at every touched slot (owners and shards). Error locations: `"state <shard>.<field>"`, `"local <process>.<field>"`, `"a queued command sender"`.
  - `caps._live_state` adds `part.n × Σ local bytes` for each shard process with a `Local`.

- [ ] **Step 1: Write the fixture**

`libs/simkit/tests/fixtures/holder/datagen.toml`:
```toml
[project]
name = "holder"
pack = "specs/pack.py"

[paths]
out = "out"

[defaults]
seed = 11
start = "2026-03-02T00:00:00Z"
mode = "time"
span = "6h"
warmup = "0s"

[budget]
threads = 2
memory = "1GB"
max_step_rows = 100_000
max_step_bytes = "64MB"
max_spawn_depth = 3
max_admissions_per_step = 1_000

[writer]
compression = "zstd"
compression_level = 3
row_group_rows = 131_072

[engine]
step = "1h"
step_min = "1h"
step_max = "1d"
adapt = false
slab_bytes = "256KB"
timer_nodes = 10_000
payload_slots = 1_000
max_messages_per_step = 10_000
parallel_min_partitions = 64

[profiles.sample]
set = {}
```

`libs/simkit/tests/fixtures/holder/specs/pack.py`:
```python
"""Handles that outlive their step inside a shard (spec §12; S2 Task 1).

Each `acct` creates a `ticket` ID and a `pay` owner at start. The ticket reaches the desk shard
in a fast message (same step); the desk keeps it in a `ref` state field and a `Local` ref array
and echoes both two hours later (a later step). The pay owner sends `hello` with a 2 h latency,
so the desk reads `cmd.sender` (payload column 9) of a command queued across seals.
"""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, dist
from neorisk_simkit.spec.types import amount, ref

from . import kernels as k

PACK = "holder"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Config:
    accts: int = 3


def define(p: Pack, cfg: Config) -> None:
    acct = p.table("acct", key="acct_id", mutable=True, cols={"bal": amount(asset="USD")})
    pay = p.table("pay", key="pay_id", mutable=True,
                  cols={"acct_id": ref("acct"), "ticket": ref("ticket")})
    p.ids("ticket")
    p.owner("acct", table=acct, max_live=cfg.accts)
    p.owner("pay", table=pay, max_live=cfg.accts)
    p.population(acct, n=cfg.accts, initial=1.0)
    desk = p.shard("desk", key="desk", n=1, items=None, state={"last": "ref"})
    note = p.message("note", frm="acct", to=desk, payload={"ticket": ref("ticket")},
                     latency=dist.constant(ms=10))
    hello = p.message("hello", frm="pay", to=desk, payload={"ticket": ref("ticket")},
                      latency=dist.constant(s=7200))
    p.event("opened", owner="acct", cols={"acct_id": ref("acct"), "ticket_id": ref("ticket"),
                                          "pay_id": ref("pay")})
    p.event("noted", shard="desk", cols={"ticket_id": ref("ticket")})
    p.event("echoed", shard="desk", cols={"last_id": ref("ticket"), "first_id": ref("ticket")})
    p.event("heard", shard="desk", cols={"ticket_id": ref("ticket"), "sender_id": ref("pay")})
    p.process("acct_main", owner="acct", kernel=k.acct_main, start=p.on_created("acct"),
              messages={"note": note}, commands=(0,))
    p.process("pay_main", owner="pay", kernel=k.pay_main, start=p.on_created("pay"),
              messages={"hello": hello}, commands=(0,))
    p.process("desk_main", shard=desk, kernel=k.desk_main,
              on_message={"note": k.C_NOTE, "hello": k.C_HELLO}, commands=k.DESK_COMMANDS)
```

`libs/simkit/tests/fixtures/holder/specs/kernels.py`:
```python
from neorisk_simkit.engine import COMMIT, PRIO_TIMER, RETRY, START, Local, Res, kernel

C_NOTE, C_HELLO, C_ECHO = 1, 2, 3
DESK_COMMANDS = (C_NOTE, C_HELLO, C_ECHO)
HOUR = 3_600_000_000


@kernel(state="acct", commands=(START,),
        max=Res(records={"opened": 1}, creates={"ticket": 1, "pay": 1}, requests=2))
def acct_main(ctx, s, cmd, out):
    if not out.reserve(records={"opened": 1}, creates={"ticket": 1, "pay": 1}, requests=2):
        return RETRY
    t = out.new_id("ticket")
    pay = out.create_pay(acct_id=ctx.self_id, ticket=t)
    out.emit_opened(ctx.t, acct_id=ctx.self_id, ticket_id=t, pay_id=pay)
    out.send_note(ctx.t, to=0, ticket=t)
    return COMMIT


@kernel(state="pay", commands=(START,), max=Res(requests=1))
def pay_main(ctx, s, cmd, out):
    if not out.reserve(requests=1):
        return RETRY
    out.send_hello(ctx.t, to=0, ticket=s.ticket)
    return COMMIT


@kernel(state="desk", local=Local(seen="ref[4]", n="i32"), commands=DESK_COMMANDS,
        max=Res(records={"noted": 1, "echoed": 1, "heard": 1}, timers=1))
def desk_main(ctx, s, loc, cmd, out):
    if cmd.kind == C_NOTE:
        if not out.reserve(records={"noted": 1}, timers=1):
            return RETRY
        s.last = cmd.ticket                       # a provisional handle until the step seals
        if loc.n < 4:
            loc.seen[loc.n] = cmd.ticket
        loc.n += 1
        out.emit_noted(ctx.t, ticket_id=cmd.ticket)
        out.timer(ctx.t + 2 * HOUR, C_ECHO, prio=PRIO_TIMER)
        return COMMIT
    if cmd.kind == C_HELLO:
        if not out.reserve(records={"heard": 1}):
            return RETRY
        out.emit_heard(ctx.t, ticket_id=cmd.ticket, sender_id=cmd.sender)
        return COMMIT
    if not out.reserve(records={"echoed": 1}):
        return RETRY
    out.emit_echoed(ctx.t, last_id=s.last, first_id=loc.seen[0])
    return COMMIT
```

- [ ] **Step 2: Write the failing tests**

`libs/simkit/tests/test_engine_seal_shards.py`:
```python
"""D38: seal remaps handles held by shards: `ref` state, `Local` refs, payload column 9."""

import numpy as np
from conftest import FIXTURES, make_run

from neorisk_simkit import std
from neorisk_simkit.engine.world import World
from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events
from neorisk_simkit.spec.caps import compute_caps, hidden_bytes, row_bytes


def _run(tmp_path, threads=1):
    r = run_to_dataset(FIXTURES / "holder", "sample", out_dir=tmp_path / f"t{threads}",
                       threads=threads)
    return r, read_events(r.out_dir)


def test_ref_state_starts_null():
    w = World.build(make_run("holder"), threads=1)
    assert w.state["desk"][0].tolist() == [std.NULL]


def test_shard_state_and_local_refs_survive_the_seal(tmp_path):
    r, ev = _run(tmp_path)
    opened, noted, echoed = ev["opened"], ev["noted"], ev["echoed"]
    assert opened.height == noted.height == echoed.height == 3
    assert set(noted["ticket_id"]) == set(opened["ticket_id"])
    # the desk echoes two hours (two steps) after it stored the provisional ticket handles
    assert (echoed["event_time"].dt.hour() == 2).all() and (noted["event_time"].dt.hour() == 0).all()
    assert set(echoed["last_id"]) == {noted["ticket_id"][-1]}      # state `last`: last noted
    assert set(echoed["first_id"]) == {noted["ticket_id"][0]}     # Local `seen[0]`: first noted


def test_queued_sender_is_remapped(tmp_path):
    _, ev = _run(tmp_path)
    heard, opened = ev["heard"], ev["opened"]
    assert heard.height == 3 and (heard["event_time"].dt.hour() == 2).all()
    pairs = dict(zip(opened["ticket_id"], opened["pay_id"], strict=True))
    for ticket, sender in zip(heard["ticket_id"], heard["sender_id"], strict=True):
        assert pairs[ticket] == sender                 # cmd.sender = the pay owner's final id


def test_threads_do_not_change_holder(tmp_path):
    from conftest import event_dicts
    a, _ = _run(tmp_path, threads=1)
    b, _ = _run(tmp_path, threads=2)
    assert event_dicts(a.out_dir) == event_dicts(b.out_dir)


def test_shard_locals_count_as_live_state():
    run = make_run("holder")
    plan = run.plan
    caps = {c.name: c for c in compute_caps(run)}
    hid = hidden_bytes(plan)
    owners = (3 * (row_bytes(plan.table("acct").cols) + hid)
              + 3 * (row_bytes(plan.table("pay").cols) + hid))
    desk = 1 * (hid + 8) + 1 * (8 * 4 + 4)            # state `last` + Local seen[4], n
    assert caps["live_partition_state"].hard_bytes == owners + desk
    assert np.dtype(np.int64).itemsize == 8
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run --all-packages pytest libs/simkit/tests/test_engine_seal_shards.py -v`
Expected: FAIL — every test errors with `PackError: shard desk: unknown state type 'ref' for 'last'`.

- [ ] **Step 4: Implement**

- `spec/pack.py`: `_STATE_RE = re.compile(r"^(i8|i16|i32|i64|u8|u32|f64|ref)(?:\[(\w+)\])?$")`.
- `engine/world.py` `_shard_state`: for a field whose base type is `ref` and that has no init value, `np.full(size, std.NULL, np.int64)` instead of zeros.
- `io/seal.py` `_remap_world`: after the owner loop, for each shard partition, take the touched slots in `[base, base + n)`; their shard indices are `hid.lslot[gs]`. For each state field (declaration order, `world.state[part.name][j]`) whose declared base type is `ref`: scalar → `remap.apply_copy(arr, idx, f"state {part.name}.{field}")`; per-item → the index set `np.concatenate([np.arange(offs[i], offs[i + 1]) for i in idx])` with `offs = world.offs[part.name]`. For each process of the shard with a `Local`, each `ref` field: `remap.apply_copy(arr, idx, f"local {p.name}.{fname}")` (2-D arrays remap whole rows, as owners do). Then, beside the existing user-payload remap of queued nodes, remap payload column 9 of the same rows: `remap.apply(col9, "a queued command sender")`, written back.
- `spec/caps.py` `_live_state`: in the shard branch add `part.n * sum(_local_bytes(p.kernel.local) for p in plan.processes if p.partition == part.name)`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run --all-packages pytest libs/simkit/tests/test_engine_seal_shards.py -v`
Expected: PASS (5 tests).

- [ ] **Step 6: Full suite and lint**

Run: `uv run --all-packages pytest -q && uv run ruff check $(ls -d libs apps examples/ecommerce_s1 examples/ecommerce_s2 benchmarks 2>/dev/null)`
Expected: all tests pass; `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add libs/simkit/src/neorisk_simkit/spec/pack.py libs/simkit/src/neorisk_simkit/spec/caps.py libs/simkit/src/neorisk_simkit/engine/world.py libs/simkit/src/neorisk_simkit/io/seal.py libs/simkit/tests/fixtures/holder libs/simkit/tests/test_engine_seal_shards.py
git commit -m "fix(engine): seal remaps handles held by shards and queued senders

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 2: Explicit response tagging and request/response pairing

**Files:**
- Create: `libs/simkit/tests/fixtures/pairing/{datagen.toml,specs/pack.py,specs/kernels.py}`
- Modify: `libs/simkit/src/neorisk_simkit/engine/cmdq.py` (`PAY_KIND = 11`), `engine/route.py` (write `PAY_KIND` on delivery; `resume_owner(P, pay_rows, qhead, g)`; `RT_BND_RESP`, `RT_SHARD_REQ`), `engine/codegen.py` (`run_partitions` pairing check; generated `_unpaired`), `engine/world.py` (route tuple entries; `stats["pairing"]`), `engine/run.py` (carry `pairing` into `Simulation.stats`), `io/dataset.py` + `io/manifest.py` (manifest `pairing`), `spec/validate.py` (owner-to-owner message error text, D57)
- Modify (tests): `libs/simkit/tests/test_engine_rounds.py` (any direct `resume_owner` call gets the payload rows)
- Test: `libs/simkit/tests/test_engine_pairing.py`

**Interfaces:**
- Consumes: S1 `route.route_outbox`, `route.resume_owner`, `cmdq.q_push`, `NodePool`, `PayloadPool`, codegen `run_partitions`.
- Produces:
  - `cmdq.PAY_KIND = 11`.
  - `route.resume_owner(P, pay_rows, qhead, g)`: responses are the nodes with `pay >= 0 and pay_rows[pay, PAY_KIND] == OB_RESPONSE`; everything else follows S1 D7 (blocking resume) unchanged.
  - `route.RT_BND_RESP = 22`, `route.RT_SHARD_REQ = 23`, `route.RT_SHARD_LO = 24` (`int64[1]` holding `shard_lo`). `route_outbox` writes `rows[row, PAY_KIND] = kind` after copying the 12 columns of every delivered row, counts each routed response in `R[RT_BND_RESP][bnd]` and each delivered request in `R[RT_SHARD_REQ][g - shard_lo]` (Task 19 reads it).
  - Generated `run_partitions`: after a command that did not RETRY, `nresp` = `OB_RESPONSE` rows in the outbox written by this command; `PAY_KIND == OB_REQUEST` requires `rc == COMMIT and nresp == 1`, any other command requires `nresp == 0`; otherwise `_unpaired(a, kind, rc, nresp, pid_, seq_)` (called with `pid[g], P[2][node]`: the partition and the command's seq) raises `EngineError("<process>: request <b> must be answered exactly once (answered <n>, returned <rc>) at (partition_id <pid>, seq <seq>), action <a>")` or `EngineError("<process>: <label> answered a request it was not given at (partition_id <pid>, seq <seq>), action <a>")` with `<label>` as in `_out_of_order` (`start`, `request b`, `message b`, `response b.r`, `command <k>`). The citation is §11's "Failures cite (partition_id, seq) and action ID" (F-06); the tests' `match=` patterns are unanchored and stop before it.
  - `World.stats["pairing"] = {boundary: {"requests": int, "responses": int}}` for request boundaries; `Simulation.stats["pairing"]` and manifest `pairing` carry the end-of-run values.

- [ ] **Step 1: Write the fixture**

`libs/simkit/tests/fixtures/pairing/datagen.toml`: a copy of `libs/simkit/tests/fixtures/holder/datagen.toml` (Task 1) with `name = "pairing"`, `seed = 5`, `span = "1h"` and `step = "1h"`.

`libs/simkit/tests/fixtures/pairing/specs/pack.py`:
```python
"""Request/response pairing (D40): the desk answers each request exactly once in mode 0;
mode 1 rejects a request, mode 2 answers twice, mode 3 answers a message."""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, dist
from neorisk_simkit.spec.types import i32, ref

from . import kernels as k

PACK = "pairing"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Config:
    accts: int = 2
    mode: int = 0


def define(p: Pack, cfg: Config) -> None:
    acct = p.table("acct", key="acct_id", mutable=True, cols={"n": i32()})
    p.owner("acct", table=acct, max_live=cfg.accts)
    p.population(acct, n=cfg.accts, initial=1.0)
    desk = p.shard("desk", key="desk", n=1, items=None, state={})
    ask = p.request("ask", frm="acct", to=desk, payload={"v": i32()}, responses=("ok",),
                    latency=dist.constant(ms=100))
    tick = p.message("tick", frm="acct", to=desk, payload={"v": i32()},
                     latency=dist.constant(ms=50))
    p.event("answered", owner="acct", cols={"acct_id": ref("acct")})
    p.event("asked", shard="desk", cols={"v": i32()})
    p.process("acct_main", owner="acct", kernel=k.acct_main, start=p.on_created("acct"),
              requests={"ask": ask}, messages={"tick": tick},
              on_response={("ask", "ok"): k.R_OK}, commands=k.ACCT_COMMANDS)
    p.process("desk_main", shard=desk, kernel=k.desk_main, config=cfg,
              on_request={"ask": k.C_ASK}, on_message={"tick": k.C_TICK})
```

`libs/simkit/tests/fixtures/pairing/specs/kernels.py`:
```python
from neorisk_simkit.engine import COMMIT, RETRY, START, Res, kernel, reject

R_OK = 1
ACCT_COMMANDS = (START, R_OK)
C_ASK, C_TICK = 1, 2


@kernel(state="acct", commands=ACCT_COMMANDS, max=Res(records={"answered": 1}, requests=2))
def acct_main(ctx, s, cmd, out):
    if cmd.kind == START:
        if not out.reserve(requests=2):
            return RETRY
        out.send_tick(ctx.t, to=0, v=ctx.self_id)
        out.request_ask(ctx.t, shard=0, v=ctx.self_id)
        return COMMIT
    if not out.reserve(records={"answered": 1}):
        return RETRY
    out.emit_answered(ctx.t, acct_id=ctx.self_id)
    return COMMIT


@kernel(state="desk", commands=(C_ASK, C_TICK), max=Res(records={"asked": 1}, requests=2))
def desk_main(ctx, s, cmd, out):
    mode = ctx.cfg.mode
    if cmd.kind == C_TICK:
        if mode != 3:
            return COMMIT
        if not out.reserve(requests=1):
            return RETRY
        out.respond(cmd, "ok")                     # answers a message: not a request
        return COMMIT
    if mode == 1:
        return reject(1)                           # a request must be answered, not rejected
    if not out.reserve(records={"asked": 1}, requests=2):
        return RETRY
    out.emit_asked(ctx.t, v=cmd.v)
    out.respond(cmd, "ok")
    if mode == 2:
        out.respond(cmd, "ok")
    return COMMIT
```

- [ ] **Step 2: Write the failing tests**

`libs/simkit/tests/test_engine_pairing.py`:
```python
"""D39 explicit response tagging and D40 request/response pairing."""

import json

import numpy as np
import pytest
from conftest import FIXTURES, make_run, records_of

from neorisk_simkit.engine import EngineError
from neorisk_simkit.engine.cmdq import PAY_KIND, NodePool, PayloadPool, q_push
from neorisk_simkit.engine.rounds import run_step
from neorisk_simkit.engine.route import resume_owner
from neorisk_simkit.engine.slabs import OB_MESSAGE, OB_RESPONSE
from neorisk_simkit.engine.world import World
from neorisk_simkit.io.dataset import run_to_dataset


def _step(overrides=()):
    run = make_run("pairing", overrides)
    w = World.build(run, threads=1)
    t0 = run.start_us - run.warmup_us
    run_step(w, t0, t0 + run.engine.step_us)
    return run, w


def test_resume_owner_reads_the_delivered_kind():
    P, PA = NodePool(8, 1), PayloadPool(8, 1)
    P.refill(0, 8)
    t = P.as_tuple()
    qhead = np.full(1, -1, np.int32)
    q_push(t, 0, qhead, 0, 5, 5, 0, 0, 1, 0, 0, -1)          # a timer at 5 (kind 1)
    PA.rows[0, PAY_KIND] = OB_MESSAGE
    q_push(t, 0, qhead, 0, 7, 1, 0, 1, 2, 0, 0, 0)           # a message at 7 (kind 2)
    PA.rows[1, PAY_KIND] = OB_RESPONSE
    q_push(t, 0, qhead, 0, 9, 1, 0, 2, 3, 0, 0, 1)           # a response at 9 (kind 3)
    resume_owner(t, PA.rows, qhead, 0)
    order, node = [], qhead[0]
    while node >= 0:
        order.append((int(P.kind[node]), int(P.time[node])))
        node = P.next[node]
    # only the response is a response: it runs first, then the earlier commands at T_r = 9
    assert order == [(3, 9), (1, 9), (2, 9)]


def test_answered_requests_pair_up():
    _, w = _step()
    assert len(records_of(w, "answered")["time"]) == 2
    assert w.stats["pairing"] == {"ask": {"requests": 2, "responses": 2}}


@pytest.mark.parametrize("mode,match", [
    (1, r"desk_main: request ask must be answered exactly once \(answered 0, returned 2\)"),
    (2, r"desk_main: request ask must be answered exactly once \(answered 2, returned 0\)"),
    (3, r"desk_main: message tick answered a request it was not given"),
])
def test_unpaired_answers_fail_naming_process_and_boundary(mode, match):
    with pytest.raises(EngineError, match=match):
        _step([f"mode={mode}"])


def test_unpaired_answers_cite_partition_seq_and_action():
    """§11: "Failures cite (partition_id, seq) and action ID" (F-06)."""
    with pytest.raises(EngineError, match=r"\(answered 0, returned 2\) at \(partition_id \d+, "
                                          r"seq \d+\), action \d+$"):
        _step(["mode=1"])


def test_manifest_reports_pairing(tmp_path):
    r = run_to_dataset(FIXTURES / "pairing", "sample", out_dir=tmp_path / "run", threads=1)
    m = json.loads((r.out_dir / "manifest.json").read_text())
    assert m["pairing"] == {"ask": {"requests": 2, "responses": 2}}


def test_existing_fixtures_still_pair():
    for name in ("mini", "spawn", "trace_shopper", "blocking", "ordering"):
        run = make_run(name)
        w = World.build(run, threads=1)
        w.init_shards()
        t0 = run.start_us - run.warmup_us
        run_step(w, t0, t0 + run.engine.step_us)
        for b, c in w.stats["pairing"].items():
            assert c["responses"] <= c["requests"], (name, b)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run --all-packages pytest libs/simkit/tests/test_engine_pairing.py -v`
Expected: FAIL — `ImportError: cannot import name 'PAY_KIND' from 'neorisk_simkit.engine.cmdq'`.

- [ ] **Step 4: Implement**

- `cmdq.py`: `PAY_KIND = 11` with a comment: "payload column 11: in the outbox, a response's requester generation; once delivered, the delivered kind (D39)". Update the `PAYLOAD_W` comment.
- `route.py`:
  - `resume_owner(P, pay_rows, qhead, g)`: replace both `ppay[node] >= 0` tests with `ppay[node] >= 0 and pay_rows[ppay[node], PAY_KIND] == OB_RESPONSE`; update the docstring (drop "In S1 an owner receives only responses ...").
  - `route_outbox`: after copying the row, `rows[row, PAY_KIND] = kind`; `kind == OB_RESPONSE` → `R[RT_BND_RESP][ob[_BND][i]] += 1` (delivered responses only; late ones stay counted as `late_messages`); `kind == OB_REQUEST` → `R[RT_SHARD_REQ][g - R[RT_SHARD_LO][0]] += 1`.
  - Call `resume_owner(P, rows, qhead, g)` with the payload rows already in scope (`PA[0]`).
- `world.py` `_build_route`: append `self._bnd_array(lambda b: 0)` (RT_BND_RESP), `np.zeros(max(1, G - self.shard_lo), np.int64)` (RT_SHARD_REQ) and `np.array([self.shard_lo], np.int64)` (RT_SHARD_LO) to `R` (`self.shard_lo` is computed at the top of `_build_route` already). `stats["pairing"] = {b.name: {"requests": int(R[RT_BND_REQ][b.code]), "responses": int(R[RT_BND_RESP][b.code])} for b in plan.boundaries if b.kind == "request"}`.
- `codegen.py`:
  - `_HEADER` imports `PAY_KIND` from `neorisk_simkit.engine.cmdq` (with `P_FREE_N`, `PAY_CONTINUE`, ...).
  - In `run_partitions`, right after the RETRY branch and the invalid-code check, before `counters[_C_RETRY_STREAK] = 0`:
    ```
    "        nresp = 0",
    "        for r_ in range(ob0, cnt[R_REQUESTS]):",
    "            if obx[OBX_KIND][r_] == OB_RESPONSE:",
    "                nresp += 1",
    "        asked = prow >= 0 and PA[0][prow, PAY_KIND] == OB_REQUEST",
    "        if asked and (rc != COMMIT or nresp != 1):",
    "            _unpaired(a, kind, rc, nresp, pid[g], P[2][node])",
    "        if not asked and nresp != 0:",
    "            _unpaired(a, kind, rc, nresp, pid[g], P[2][node])",
    ```
    (the node is still queued here: `q_remove`/`q_free` run after the check, so `P[2][node]`, the command's seq, is valid.)
  - Generate `_unpaired(a, kind, rc, nresp, pid_, seq_)` (not inlined: add to `_NOT_INLINED`) the way `_out_of_order` is generated, every message ending with the §11 citation `" at (partition_id ", pid_, ", seq ", seq_, "), action ", a` (F-06): per process, per command kind in `on_request` → `raise EngineError("<proc>: request <b> must be answered exactly once (answered ", nresp, ", returned ", rc, ") at (partition_id ", pid_, ", seq ", seq_, "), action ", a)`; every other labelled kind → `raise EngineError("<proc>: <label> answered a request it was not given at (partition_id ", pid_, ", seq ", seq_, "), action ", a)`; fallback `raise EngineError("<proc>: command ", kind, " answered a request it was not given at (partition_id ", pid_, ", seq ", seq_, "), action ", a)`.
- `run.py` `_account`: `st["pairing"] = dict(ws["pairing"])`; `Simulation.stats` initializes `"pairing": {}`.
- `manifest.write_manifest(..., pairing=None)` writes `"pairing": dict(sorted((pairing or {}).items()))`; `dataset._simulate` passes `sim.stats["pairing"]`.
- `validate.py`: the owner-to-owner message error text becomes `f"boundary {b.name}: owner-to-owner messages arrive in M3"` (D57).

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run --all-packages pytest libs/simkit/tests/test_engine_pairing.py libs/simkit/tests/test_engine_rounds.py libs/simkit/tests/test_exit_trace_shopper.py -v`
Expected: PASS (`test_engine_pairing.py`: 8 tests; the existing round and trace tests unchanged).

- [ ] **Step 6: Uncompiled leg, full suite and lint**

Run: `NUMBA_DISABLE_JIT=1 uv run --all-packages pytest libs/simkit/tests/test_engine_pairing.py -q && uv run --all-packages pytest -q && uv run ruff check $(ls -d libs apps examples/ecommerce_s1 examples/ecommerce_s2 benchmarks 2>/dev/null)`
Expected: all pass; `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add libs/simkit/src/neorisk_simkit libs/simkit/tests/fixtures/pairing libs/simkit/tests/test_engine_pairing.py libs/simkit/tests/test_engine_rounds.py
git commit -m "feat(engine): tag delivered kinds and answer every request exactly once

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 3: Step length adapts on the rows the cap counts

**Files:**
- Modify: `libs/simkit/src/neorisk_simkit/io/seal.py` (record `counted_rows` = `world.step_rows` after `flush_all`, before `take_chunks`), `engine/run.py` (adapt on `counted_rows`)
- Test: `libs/simkit/tests/test_engine_seal.py` (append)

**Interfaces:**
- Consumes: S1 `World.step_rows` (rows flushed this step, ids included; reset by `take_chunks`), `next_step_length(prev_len, rows, engine, budget)`.
- Produces: `SealedStep.stats["counted_rows"]: int`; `Simulation.steps()` calls `next_step_length(length, sealed.stats["counted_rows"], eng, budget)` (D41). `stats["rows"]` keeps its S1 meaning (records + created entity rows).

- [ ] **Step 1: Write the failing test**

Append to `libs/simkit/tests/test_engine_seal.py`:
```python
def test_step_length_adapts_on_the_rows_the_cap_counts(monkeypatch):
    """D41: the step cap counts p.ids allocations, so the adaptive length must too."""
    from neorisk_simkit.engine import run as run_mod

    _, sim = _sim(["behavior.take_p=0.0"], adapt=True, step_us=4 * H)
    seen = []
    real = run_mod.next_step_length

    def spy(prev, rows, eng, bud):
        seen.append(rows)
        return real(prev, rows, eng, bud)

    monkeypatch.setattr(run_mod, "next_step_length", spy)
    steps = list(sim.steps())
    assert seen == [s.stats["counted_rows"] for s in steps][:len(seen)] and seen
    for s in steps:
        if s.exported:                       # one `visit` id per ping is counted, not exported
            assert s.stats["counted_rows"] == s.stats["rows"] + s.stats["events"]["ping"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --all-packages pytest libs/simkit/tests/test_engine_seal.py::test_step_length_adapts_on_the_rows_the_cap_counts -v`
Expected: FAIL with `KeyError: 'counted_rows'`.

- [ ] **Step 3: Implement**

- `seal_step`: right after `world.flush_all()`, `counted = int(world.step_rows)`; add `"counted_rows": counted` to `stats`.
- `Simulation.steps()`: `length = next_step_length(length, sealed.stats["counted_rows"], eng, budget)`.
- `next_step_length` docstring: "from the previous step's counted rows (everything the step cap counts, D41)".

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --all-packages pytest libs/simkit/tests/test_engine_seal.py -v`
Expected: PASS.

- [ ] **Step 5: Full suite and lint**

Run: `uv run --all-packages pytest -q && uv run ruff check $(ls -d libs apps examples/ecommerce_s1 examples/ecommerce_s2 benchmarks 2>/dev/null)`
Expected: all pass. `test_exit_invariance.py` and `test_example_ecom_s1*.py` pass unchanged (their runs set `engine.adapt=false` or check rates, not bytes). Note in the commit body that ecommerce_s1 `full` step boundaries move (D41); Task 21 re-measures the S1 gate.

- [ ] **Step 6: Commit**

```bash
git add libs/simkit/src/neorisk_simkit/io/seal.py libs/simkit/src/neorisk_simkit/engine/run.py libs/simkit/tests/test_engine_seal.py
git commit -m "fix(engine): adapt step length on the rows the step cap counts

ecommerce_s1 full-profile step boundaries change once (plan D41).

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 4: Static spawn bounds and creation payloads

The created row's columns ride in the `OB_CREATE` payload (D43) because Task 5's compiled admission cannot read create slabs; S1's incremental create-slab index for Python admission (`World._created_rows`, `_CreatedIndex`, `World._created_index`, the `World.created_rows_indexed` counter; Codex CX3, 8f0d693) becomes unused and is deleted here, with the test that counted its work. Creation messages also start counting toward `requests` automatically (S1 contracts, Task 8 → Task 14: "kernels creating owners must also reserve requests (or Task 14 makes `_reserve_` count them)"; the S1 `creators` fixture forgot the unit and overflowed a 4 KiB outbox silently outside checked mode, codex-fix-report CX3).

**Files:**
- Create: `libs/simkit/tests/fixtures/chain/{datagen.toml,specs/pack.py,specs/kernels.py}`
- Modify: `libs/simkit/src/neorisk_simkit/spec/validate.py` (creation graph, created-owner table rule, outbox fit of declared requests plus creation messages), `engine/slabs.py` (`CREATE_HEAD` + `lamport`), `engine/codegen.py` (`_create_<ns>` writes `lamport` and, for owner tables, the row's columns into the creation payload; `_reserve_<proc>` counts creation messages in `requests`), `engine/world.py` (`_Creation.pay`; admission reads the payload; delete `_CreatedIndex`, `_created_index`, `created_rows_indexed`, `_created_rows` and the `_created_index` reset in `take_chunks`)
- Test: `libs/simkit/tests/test_spec_validate.py` (append), `libs/simkit/tests/test_engine_rounds.py` (append; rewrite `test_admission_indexes_each_created_row_once`)

**Interfaces:**
- Consumes: S1 `plan.namespaces`, `Res.creates`, `budget.max_spawn_depth`; contracts C1 `k` (ordinal within the creating commit) in `World.admit_created`; codegen `reserve(p)` (`_reserve_<proc>(out, vec)`, `vec` in `KernelLayout.resources` order: `records:<n>`, `creates:<ns>`, `timers`, `requests`).
- Produces:
  - `validate.creation_graph(plan) -> dict[str, list[tuple[str, str]]]`: owner/shard partition → `[(created owner partition, process)]`.
  - validate errors (D42, D43):
    - `f"unbounded spawn: owner creation cycle {' -> '.join(parts)} (processes {', '.join(procs)})"`
    - `f"spawn depth {d} exceeds budget.max_spawn_depth {m} (processes {' -> '.join(procs)})"`
    - `f"created owner table {t} has {n} columns; a creation message carries at most 7"`
    - `f"created owner table {t}: column {c} is {kind}; a creation message carries only int64 values"`
    - `f"{p.name}: declared maximum of requests {r} plus {c} creation message(s) exceeds the outbox capacity {cap}"` (`r = max.requests`, `c` = Σ `max.creates` over owner tables, `cap = force_capacity["requests"]` when forced, else `slab_bytes // OUTBOX_ROW_BYTES`; only when `c > 0`)
  - `slabs.CREATE_HEAD = (("handle", i64), ("pid", i64), ("ordinal", i32), ("created_at", i64), ("g", i64), ("lamport", i64))`.
  - Create rows carry `lamport` (consumed by Task 4b/5 through `_Creation.cause` / `CQ.cause`). At BASE `World.created_causes`, `take_created_causes` and `seal._owner_dense` are already gone (contracts CX1) and `seal` ranks every namespace by `assign_dense(pid, ordinal)` (§12; a creator created in the same step ranks by its provisional handle), so `seal` needs no change here.
  - Generated `_reserve_<proc>(out, vec)`: with `q` the index of `requests` and `C` the indices of `creates:<ns>` for owner tables `ns`, the requests need is `nreq = vec[q] + Σ_{i ∈ C} vec[i]`; the check is `nreq > 0 and cap[q] - cnt[q] < nreq` (miss `q`) and the recorded reservation is `resv[q] = nreq`. Kernels' `requests=` from now on counts requests, messages and responses only; kernels that already add the creation unit by hand (S1 `spawn`, `creators`; S2 `holder`) over-reserve one row per created owner, which only moves slab swaps (outputs are slab-invariant).

- [ ] **Step 1: Write the `chain` fixture**

`libs/simkit/tests/fixtures/chain/datagen.toml`: a copy of `fixtures/holder/datagen.toml` with `name = "chain"`, `seed = 13`, `span = "1h"`, `step = "1h"`.

`libs/simkit/tests/fixtures/chain/specs/pack.py`:
```python
"""Owners creating owners creating owners: a -> b -> c, all in one step (D42, D44)."""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack
from neorisk_simkit.spec.types import i32, ref

from . import kernels as k

PACK = "chain"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Config:
    a_n: int = 4
    live: int = 8


def define(p: Pack, cfg: Config) -> None:
    a = p.table("a", key="a_id", mutable=True, cols={"n": i32()})
    b = p.table("b", key="b_id", mutable=True, cols={"a_id": ref("a"), "w": i32()})
    c = p.table("c", key="c_id", mutable=True, cols={"b_id": ref("b"), "w": i32()})
    p.owner("a", table=a, max_live=cfg.a_n)
    p.owner("b", table=b, max_live=cfg.live)
    p.owner("c", table=c, max_live=cfg.live)
    p.population(a, n=cfg.a_n, initial=1.0)
    p.event("a_made", owner="a", cols={"a_id": ref("a"), "b_id": ref("b")})
    p.event("b_made", owner="b", cols={"b_id": ref("b"), "c_id": ref("c"), "w": i32()})
    p.event("c_drew", owner="c", cols={"c_id": ref("c"), "b_id": ref("b"), "w": i32(),
                                       "draw": i32()})
    p.process("a_main", owner="a", kernel=k.a_main, start=p.on_created("a"), commands=(0,))
    p.process("b_main", owner="b", kernel=k.b_main, start=p.on_created("b"), commands=(0,))
    p.process("c_main", owner="c", kernel=k.c_main, start=p.on_created("c"), commands=(0,))
```

`libs/simkit/tests/fixtures/chain/specs/kernels.py`:
```python
from neorisk_simkit.engine import COMMIT, RETRY, START, Res, kernel

# no `requests=`: creating an owner reserves its creation message automatically (Task 4)


@kernel(state="a", commands=(START,), max=Res(records={"a_made": 1}, creates={"b": 1}))
def a_main(ctx, s, cmd, out):
    if not out.reserve(records={"a_made": 1}, creates={"b": 1}):
        return RETRY
    b = out.create_b(a_id=ctx.self_id, w=10 + ctx.self_id)
    out.emit_a_made(ctx.t, a_id=ctx.self_id, b_id=b)
    return COMMIT


@kernel(state="b", commands=(START,), max=Res(records={"b_made": 1}, creates={"c": 1}))
def b_main(ctx, s, cmd, out):
    if not out.reserve(records={"b_made": 1}, creates={"c": 1}):
        return RETRY
    c = out.create_c(b_id=ctx.self_id, w=s.w + 100)
    out.emit_b_made(ctx.t, b_id=ctx.self_id, c_id=c, w=s.w)
    return COMMIT


@kernel(state="c", commands=(START,), max=Res(records={"c_drew": 1}))
def c_main(ctx, s, cmd, out):
    d = ctx.rng.uniform_int(site=1, lo=0, hi=1_000_000)
    if not out.reserve(records={"c_drew": 1}):
        return RETRY
    out.emit_c_drew(ctx.t, c_id=ctx.self_id, b_id=s.b_id, w=s.w, draw=d)
    return COMMIT
```

- [ ] **Step 2: Write the failing tests**

Append to `libs/simkit/tests/test_spec_validate.py`:
```python
def _run_of(fixture_project, name, overrides=()):
    return resolve_run(load_project(fixture_project(name)), "sample", list(overrides))


def test_chain_depth_two_is_valid_and_bounded(fixture_project):
    assert validate(_run_of(fixture_project, "chain")).ok
    errs = validate(_run_of(fixture_project, "chain", ["budget.max_spawn_depth=1"])).errors
    assert "spawn depth 2 exceeds budget.max_spawn_depth 1 (processes a_main -> b_main)" in errs


def test_creation_cycle_is_an_unbounded_spawn(fixture_project):
    from neorisk_simkit.engine import Res
    run = _run_of(fixture_project, "spawn")
    bad = _with_kernel(run, "pay_main", max=Res(records={"paid": 1}, creates={"pay": 1},
                                                 requests=1))
    assert ("unbounded spawn: owner creation cycle pay -> pay (processes pay_main)"
            in validate(bad).errors)


def test_created_owner_tables_fit_a_creation_message(fixture_project):
    from neorisk_simkit.spec.plan import Column
    from neorisk_simkit.spec.types import f64, i64
    run = _run_of(fixture_project, "spawn")
    plan = run.plan

    def with_pay_cols(cols):
        ts = tuple(dataclasses.replace(t, cols=cols) if t.name == "pay" else t
                   for t in plan.tables)
        return dataclasses.replace(run, plan=dataclasses.replace(plan, tables=ts))

    wide = with_pay_cols(plan.table("pay").cols + tuple(Column(f"x{i}", i64()) for i in range(6)))
    assert "created owner table pay has 8 columns; a creation message carries at most 7" \
        in validate(wide).errors
    floaty = with_pay_cols(plan.table("pay").cols + (Column("rate", f64()),))
    assert ("created owner table pay: column rate is f64; a creation message carries only "
            "int64 values") in validate(floaty).errors


def test_creation_messages_count_toward_the_outbox(fixture_project):
    run = _run_of(fixture_project, "spawn")              # acct_main: requests=3, creates pay 1
    small = dataclasses.replace(run, engine=dataclasses.replace(
        run.engine, force_capacity={"requests": 3}))
    assert ("acct_main: declared maximum of requests 3 plus 1 creation message(s) exceeds the "
            "outbox capacity 3") in validate(small).errors
    fits = dataclasses.replace(run, engine=dataclasses.replace(
        run.engine, force_capacity={"requests": 4}))
    assert not any("creation message(s)" in e for e in validate(fits).errors)
```

Append to `libs/simkit/tests/test_engine_rounds.py`:
```python
def test_created_rows_carry_their_commit_lamport():
    run, w, _ = _step("spawn")
    w.flush_all()
    rows = [c.creates["pay"] for chunks in w.chunks for c in chunks if "pay" in c.creates]
    lam = {int(h): int(x) for r in rows for h, x in zip(r["handle"], r["lamport"], strict=True)}
    spawned = _rows(w, "spawned")
    assert lam and {int(h): int(x) for h, x in zip(spawned["pay_id"], spawned["lamport"],
                                                    strict=True)} == lam


def test_a_chain_of_creations_runs_in_one_step():
    run, w, stats = _step("chain")
    t0 = run.start_us - run.warmup_us
    c = _rows(w, "c_drew")
    assert len(c["time"]) == 4 and (c["time"] == t0).all()
    assert sorted(c["w"].tolist()) == [110, 111, 112, 113]       # b's state reached c by payload
    assert stats.owners_run[:3] == [4, 4, 4]                     # a; then b; then c (D5)


def test_creates_reserve_their_creation_messages(monkeypatch):
    """`chain` kernels reserve `creates` but no `requests`: the creation message's outbox row is
    reserved automatically, so a one-row outbox swaps between creators instead of overflowing
    (the S1 `creators` fixture overflowed a 4 KiB outbox silently outside checked mode)."""
    swaps, handle_status = [], World.handle_status

    def spy(self, worker, status):
        swaps.append(int(status))
        return handle_status(self, worker, status)

    monkeypatch.setattr(World, "handle_status", spy)
    _, w, _ = _step("chain", engine={"force_capacity": {"requests": 1}})
    c = _rows(w, "c_drew")
    assert sorted(c["w"].tolist()) == [110, 111, 112, 113]
    assert swaps.count(NEED_SWAP) >= 3                            # 4 creators, 1-row outbox


def test_admission_reads_creation_payloads_in_many_small_batches(monkeypatch):
    """Replaces S1's `test_admission_indexes_each_created_row_once` (Codex CX3): admission reads
    each created row's state from its creation message (D43), so no create-slab index exists;
    many small batches in one step, with slabs flushed mid-step, still admit every row once."""
    calls, flushes = [], []
    admit, flush = World.admit_created, World._flush

    def spy(self, limit_t):
        got = admit(self, limit_t)
        if len(got):
            calls.append(len(got))
        return got

    def spy_flush(self, worker):
        flushes.append(worker)
        return flush(self, worker)

    monkeypatch.setattr(World, "admit_created", spy)
    monkeypatch.setattr(World, "_flush", spy_flush)
    run = make_run("spawn", ["create_on_answer=1", "rounds=60"], slab_bytes=2048)
    sim = Simulation(run, threads=2)
    steps = list(sim.steps())
    assert len(steps) == 1
    created = sum(s.entities["pay"].num_rows for s in steps)
    assert created == 3 * 60
    assert len(calls) >= 60 and max(calls) <= 3 and sum(calls) == created
    assert len(flushes) > 2 * 2                 # slabs flushed mid-step, not only at seal
    assert not hasattr(sim.world, "created_rows_indexed")
    assert not hasattr(World, "_created_rows")
```
`test_admission_reads_creation_payloads_in_many_small_batches` replaces `test_admission_indexes_each_created_row_once` (delete the old test; its `created_rows_indexed` counter is gone). `NEED_SWAP` comes from `neorisk_simkit.engine.codegen` (add it to the module's imports with `World`, `Simulation` and `make_run`, which it already has).

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run --all-packages pytest libs/simkit/tests/test_spec_validate.py libs/simkit/tests/test_engine_rounds.py -k "chain or cycle or creation_message or commit_lamport or small_batches" -v`
Expected: FAIL — the validate tests find no such error message; `test_created_rows_carry_their_commit_lamport` fails with `KeyError: 'lamport'`; `test_creates_reserve_their_creation_messages` fails (the second creator writes past the one-row outbox: an `IndexError` uncompiled, garbage routing or a crash compiled; no `NEED_SWAP`); `test_admission_reads_creation_payloads_in_many_small_batches` fails on `hasattr(sim.world, "created_rows_indexed")`. `test_a_chain_of_creations_runs_in_one_step` already passes on S1's admission (S1 admits chains of creations in one step; it pins that Step 4 keeps doing so).

- [ ] **Step 4: Implement**

- `validate.py`:
  - `creation_graph(plan)`: owner tables `{p.table: p.name for owner partitions}`; for every process `p`, every `ns` in `p.kernel.max.creates` that is an owner table → edge `p.partition → owner partition of ns` labelled `p.name`.
  - Cycle detection by DFS in plan order (report the first cycle found: partitions on it, then the processes on its edges). Depth: longest path in edges from any node (memoized DFS); when it exceeds `budget.max_spawn_depth`, report the processes along the longest path in order.
  - For every owner table that is creatable (`TableDef.creatable` and an owner's table): `len(cols) > 7` → width error; any column of kind `f64` or `text` → type error (first offending column, declaration order).
  - Outbox fit, beside the existing per-process slab checks: `c = sum(k.max.creates.get(t, 0) for t in owner tables)`; when `c > 0` and `k.max.requests + c > cap` (`cap = eng.force_capacity.get("requests", eng.slab_bytes // OUTBOX_ROW_BYTES)`, `OUTBOX_ROW_BYTES` from `spec.caps`) → the outbox-fit error of Interfaces.
- `codegen.py` `reserve(p)`: `q = self.resources.index("requests")`, `C = [i for i, r in enumerate(self.resources) if r.startswith("creates:") and r[8:] in owner_tables]`; emit `nreq = vec[q] + vec[i1] + ...` first, use `cond = f"cap[{q}] - cnt[{q}] < nreq"` with guard `nreq > 0` for the `requests` resource, and `resv[q] = nreq` instead of `resv[q] = vec[q]` (every other resource unchanged). The checked-mode `resv_check("requests", ...)` in `_create_<ns>` already decrements the same counter, so checked mode stays exact.
- `slabs.py`: append `("lamport", _I64)` to `CREATE_HEAD`.
- `codegen.py` `create`/`new_id`: head values become `["h", "ctx[CTX_PID]", "o_", "ctx[CTX_T]", "g", "ctx[CTX_LAMPORT]"]`. For owner tables, after `_outbox_row(...)` returns `i`, write the row's values into the creation payload: `pay = out[OUT_OUTBOX][OBX_PAY]` then `pay[i, j] = c<j>` for each column `j` (a nullable `NULL` stays `NULL`; narrow ints widen to int64).
- `world.py`:
  - `_Creation` gains `pay: tuple[int, ...]` (7 values) and `route()` fills it from `ob["pay"][i, :7]`.
  - `admit_created` writes `arr[ls] = c.pay[j]` for column `j` (cast by numpy) instead of reading `rows[ns](c.handle)`; it keeps the fix wave's `k` (ordinal within the commit) and `inst = mix(creator inst, cause, ns, k)`.
  - Delete `_CreatedIndex`, `World._created_rows`, the attributes `self._created_index` and `self.created_rows_indexed` (set in `World.build`), and the `self._created_index = {}` reset in `take_chunks` (S1 8f0d693). `created_causes`, `take_created_causes` and `seal._owner_dense` are already gone at BASE; `seal.py` is not touched.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run --all-packages pytest libs/simkit/tests/test_spec_validate.py libs/simkit/tests/test_engine_rounds.py libs/simkit/tests/test_exit_invariance.py libs/simkit/tests/test_exit_trace_shopper.py -v`
Expected: PASS (the `creators` invariance tests of `test_exit_invariance.py` still pass: created state now comes from the creation payload instead of the create-slab index, with identical values).

- [ ] **Step 6: Full suite and lint**

Run: `uv run --all-packages pytest -q && uv run ruff check $(ls -d libs apps examples/ecommerce_s1 examples/ecommerce_s2 benchmarks 2>/dev/null)`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add libs/simkit/src/neorisk_simkit libs/simkit/tests/fixtures/chain libs/simkit/tests/test_spec_validate.py libs/simkit/tests/test_engine_rounds.py
git commit -m "feat(spec): static spawn bounds; created owners' state rides the creation message

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 4b: Step-invariant routing order for senders in their creation step

The open item of the S1 final fix (contracts, "Final-fix, NOT fixed"): a created owner's `src_pid` is its provisional handle (bit 62 set) during its creation step and a per-step dense index afterwards, so at an equal `(time, prio, cause)` its requests sort differently under different step lengths. Shards then process tied requests in a step-dependent order, and shard results (who gets the last unit) change — a value difference, not an ID difference, so the multiset reading of §12 (D37) does not excuse it. S2 creates an owner per checkout, so this must be closed before the S2 slice (D61).

**Files:**
- Create: `libs/simkit/tests/fixtures/relay/{datagen.toml,specs/pack.py,specs/kernels.py}`
- Modify: `libs/simkit/src/neorisk_simkit/engine/world.py` (`HIDDEN_DTYPES` + `ckey`; admission writes it), `engine/route.py` (`sender_keys`; `route_order` uses it), `spec/caps.py` (hidden bytes follow the table automatically)
- Modify (tests): `libs/simkit/tests/test_engine_rounds.py` (`test_route_order_sorts_equal_keys_by_partition_id_then_seq` passes `R` and distinct senders)
- Test: `libs/simkit/tests/test_exit_invariance.py` (append)

**Interfaces:**
- Consumes: Task 4 (`CREATE_HEAD.lamport`, `_Creation.cause`, `_Creation.src_g`); fix-wave `k` and creator `inst`; outbox column `src_g`.
- Produces:
  - Hidden array `ckey int64[G, 4]`: admission writes `(created_at, cause lamport, inst[src_g] of the creator, k)`; population owners and shards keep zeros.
  - `@njit route.sender_keys(R, src_g, n) -> (int64[n] x 6)`: per outbox row, from the sender's slot `g = src_g` (the outbox already carries it): `(ptype[g], 0, pid[g], 0, 0, 0)` when the sender's partition type is not created (a population owner type or a shard), else `(ptype[g], 1, ckey[g, 0], ckey[g, 1], ckey[g, 2], ckey[g, 3])`. Whether a type is created is a per-ptype flag `R[RT_CREATED_TYPE]` (`uint8[32]`). `R` gains `RT_HID` (a tuple view: hidden `ptype`, `pid`, `ckey`) and `RT_CREATED_TYPE`, indices 25 and 26 — Task 5 then uses 27 for `RT_ADM`.
  - `route_order(ob, n, R)` sorts by `(time, prio, cause, k0..k5, src_seq)`; every caller passes `R`.
  - Admission (`World.admit_created`, and Task 5's generated version) orders due creations with the same sender keys in place of `src_pid`.

- [ ] **Step 1: Write the `relay` fixture**

`libs/simkit/tests/fixtures/relay/datagen.toml`: a copy of `fixtures/holder/datagen.toml` with `name = "relay"`, `seed = 19`, `span = "2h"`, `warmup = "0s"`, `step = "30m"`, `step_min = "15m"`.

`libs/simkit/tests/fixtures/relay/specs/pack.py`:
```python
"""Created owners send requests that tie with other senders (D61).

`acct` creates a `pay` at 00:50 (commit lamport 2); the pay asks the desk at 01:00 with
lamport 4. A `peer` (declared after `pay`, so a higher partition type) asks at 01:00 with
lamport 4 too, so both requests carry cause 4. With
30m or 1h steps the pay is dense by 01:00; with 6h or 1d steps it is still provisional."""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, dist
from neorisk_simkit.spec.types import i32, ref

from . import kernels as k

PACK = "relay"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Config:
    n: int = 2


def define(p: Pack, cfg: Config) -> None:
    acct = p.table("acct", key="acct_id", mutable=True, cols={"k": i32()})
    pay = p.table("pay", key="pay_id", mutable=True, cols={"acct_id": ref("acct")})
    peer = p.table("peer", key="peer_id", mutable=True, cols={"k": i32()})
    p.owner("acct", table=acct, max_live=cfg.n)
    p.owner("pay", table=pay, max_live=cfg.n)
    p.owner("peer", table=peer, max_live=cfg.n)
    p.population(acct, n=cfg.n, initial=1.0)
    p.population(peer, n=cfg.n, initial=1.0)
    desk = p.shard("desk", key="desk", n=1, items=None, state={})
    ask_pay = p.request("ask_pay", frm="pay", to=desk, payload={"v": i32()},
                        responses=("ok",), latency=dist.constant(ms=100))
    ask_peer = p.request("ask_peer", frm="peer", to=desk, payload={"v": i32()},
                         responses=("ok",), latency=dist.constant(ms=100))
    p.event("asked", shard="desk", cols={"v": i32()})
    p.process("acct_main", owner="acct", kernel=k.acct_main, start=p.on_created("acct"),
              commands=k.ACCT_COMMANDS)
    p.process("pay_main", owner="pay", kernel=k.pay_main, start=p.on_created("pay"),
              requests={"ask": ask_pay}, on_response={("ask_pay", "ok"): k.R_OK},
              commands=k.ASKER_COMMANDS)
    p.process("peer_main", owner="peer", kernel=k.peer_main, start=p.on_created("peer"),
              requests={"ask": ask_peer}, on_response={("ask_peer", "ok"): k.R_OK},
              commands=k.PEER_COMMANDS)
    p.process("desk_pay", shard=desk, kernel=k.desk_pay, on_request={"ask_pay": k.C_ASKED})
    p.process("desk_peer", shard=desk, kernel=k.desk_peer, on_request={"ask_peer": k.C_ASKED})
```

`libs/simkit/tests/fixtures/relay/specs/kernels.py`:
```python
from neorisk_simkit.engine import COMMIT, PRIO_TIMER, RETRY, START, Res, kernel

MINUTE = 60_000_000
C_MAKE = 1
ACCT_COMMANDS = (START, C_MAKE)
C_ASK, R_OK = 1, 2
ASKER_COMMANDS = (START, C_ASK, R_OK)
C_STEP = 3
PEER_COMMANDS = (START, C_ASK, R_OK, C_STEP)
C_ASKED = 1


@kernel(state="acct", commands=ACCT_COMMANDS, max=Res(creates={"pay": 1}, timers=1))
def acct_main(ctx, s, cmd, out):
    if not out.reserve(creates={"pay": 1}, timers=1):     # the creation message: automatic
        return RETRY
    if cmd.kind == START:
        out.timer(ctx.t + 50 * MINUTE, C_MAKE, prio=PRIO_TIMER)
    else:
        out.create_pay(acct_id=ctx.self_id)
    return COMMIT


@kernel(state="pay", commands=ASKER_COMMANDS, max=Res(timers=1, requests=1))
def pay_main(ctx, s, cmd, out):
    if not out.reserve(timers=1, requests=1):
        return RETRY
    if cmd.kind == START:                                 # 00:50, lamport 3 (cause 2)
        out.timer(ctx.t + 10 * MINUTE, C_ASK, prio=PRIO_TIMER)
    elif cmd.kind == C_ASK:                               # 01:00, lamport 4
        out.request_ask(ctx.t, shard=0, v=0)
    return COMMIT


@kernel(state="peer", commands=PEER_COMMANDS, max=Res(timers=1, requests=1))
def peer_main(ctx, s, cmd, out):
    if not out.reserve(timers=1, requests=1):
        return RETRY
    if cmd.kind == START:                                 # 00:00, lamport 1
        out.timer(ctx.t + 20 * MINUTE, C_STEP, prio=PRIO_TIMER)
    elif cmd.kind == C_STEP:                              # 00:20 lamport 2, 00:40 lamport 3
        s.k += 1
        if s.k < 2:
            out.timer(ctx.t + 20 * MINUTE, C_STEP, prio=PRIO_TIMER)
        else:
            out.timer(ctx.t + 20 * MINUTE, C_ASK, prio=PRIO_TIMER)
    elif cmd.kind == C_ASK:                               # 01:00, lamport 4
        out.request_ask(ctx.t, shard=0, v=1)
    return COMMIT


@kernel(state="desk", commands=(C_ASKED,), max=Res(records={"asked": 1}, requests=1))
def desk_pay(ctx, s, cmd, out):
    if not out.reserve(records={"asked": 1}, requests=1):
        return RETRY
    out.emit_asked(ctx.t, v=cmd.v)
    out.respond(cmd, "ok")
    return COMMIT


@kernel(state="desk", commands=(C_ASKED,), max=Res(records={"asked": 1}, requests=1))
def desk_peer(ctx, s, cmd, out):
    if not out.reserve(records={"asked": 1}, requests=1):
        return RETRY
    out.emit_asked(ctx.t, v=cmd.v)
    out.respond(cmd, "ok")
    return COMMIT
```
(The pay and the peer use separate boundaries because a boundary has one sending partition; `requests={"ask": ...}` gives both kernels the local name `out.request_ask`.)

- [ ] **Step 2: Write the failing test**

Append to `libs/simkit/tests/test_exit_invariance.py`:
```python
# ---------------------------------------------------------------------------- D61
RELAY = Path(__file__).resolve().parent / "fixtures" / "relay"


@pytest.fixture(scope="module")
def relay_runs(tmp_path_factory):
    root = tmp_path_factory.mktemp("relay")
    out = {}
    for step in ("30m", "6h", "1d"):
        d = root / step
        run_to_dataset(RELAY, "sample", [f"engine.step={step!r}"], out_dir=d, threads=1)
        out[step] = d
    return out


def test_tied_requests_from_new_owners_route_step_invariantly(relay_runs):
    """A pay asks at 01:00 while provisional (6h, 1d) or dense (30m); its requests tie with
    the peers' at (time, prio, cause) and must reach the desk in the same order."""
    orders = {}
    for step, d in relay_runs.items():
        asked = read_events(d)["asked"].sort("event_time", "lamport", "partition_id", "seq")
        assert asked.height == 4 and asked["event_time"].dt.hour().to_list() == [1] * 4, step
        orders[step] = asked["v"].to_list()
    assert orders["30m"] == orders["6h"] == orders["1d"] == [0, 0, 1, 1]   # pay type first
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run --all-packages pytest libs/simkit/tests/test_exit_invariance.py::test_tied_requests_from_new_owners_route_step_invariantly -v`
Expected: FAIL — `orders["6h"] == [1, 1, 0, 0]` (provisional pays sort after the dense peers).

- [ ] **Step 4: Implement**

- `world.HIDDEN_DTYPES` gains `("ckey", "int64", 4)`; `_reset_slots` zeroes it; `admit_created` writes `(c.time, c.cause, hid.inst[c.src_g], k)` and sorts due creations with the creators' sender keys (`route.sender_keys` over their `src_g`s) in place of `src_pid`. A slot freed at seal and reused keeps no stale key: admission always rewrites `ckey`.
- `route.sender_keys` as in Interfaces; `R[RT_CREATED_TYPE][ptype_code] = 1` for every owner type whose table is creatable.
- `route_order(ob, n, R)`: stable argsorts by `src_seq`, then the six sender keys innermost first, then `cause`, `prio`, `time`. The sender slot is still alive when its outbox is routed (routing runs in the same phase as the commit), so `ptype/pid/ckey[src_g]` describe the sender. Update the call in `route_outbox` and replace the existing unit test in `test_engine_rounds.py` (it leaves `src_g = 0`, so every row would have one sender) with:
  ```python
  def test_route_order_sorts_equal_keys_by_partition_id_then_seq():
      """D61 on dense senders: key (ptype, 0, pid, 0, 0, 0) orders tied rows by partition_id."""
      from neorisk_simkit.engine.route import route_order
      from neorisk_simkit.engine.slabs import OUTBOX_COLS
      run = make_run("mini")
      w = World.build(run, threads=1)
      g = w.admit_population(run.start_us - run.warmup_us, run.start_us)
      senders = g[np.argsort(w.hidden.pid[g], kind="stable")][:10]   # ascending partition_id
      assert len(senders) == 10
      rng_ = np.random.default_rng(3)
      n = 40
      cols = {c: np.zeros(n, np.int64) for c in OUTBOX_COLS}
      cols["time"][:] = rng_.integers(0, 2, n)          # many rows tie on (time, prio, cause)
      cols["prio"][:] = 1
      cols["cause"][:] = rng_.integers(0, 2, n)
      rank = rng_.permutation(n) // 4                   # four rows per partition...
      cols["src_g"][:] = senders[rank]
      cols["src_pid"][:] = w.hidden.pid[senders[rank]]
      cols["src_seq"][:] = rng_.permutation(n)          # ...told apart by seq
      ob = (*cols.values(), np.zeros((n, 12), np.int64))
      want = np.lexsort((cols["src_seq"], rank, cols["cause"], cols["prio"], cols["time"]))
      assert route_order(ob, n, w.R).tolist() == want.tolist()
  ```
  (`senders` are the slots of the 10 lowest-`partition_id` mini users, so the `k`-th sender's `pid` order equals the old test's `src_pid = k` order.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run --all-packages pytest libs/simkit/tests/test_exit_invariance.py libs/simkit/tests/test_engine_rounds.py libs/simkit/tests/test_exit_trace_shopper.py -v`
Expected: PASS; the fix wave's `creators` tests and the trace stay green.

- [ ] **Step 6: Uncompiled leg, full suite, lint, commit**

Run: `NUMBA_DISABLE_JIT=1 uv run --all-packages pytest libs/simkit/tests/test_engine_rounds.py -q && uv run --all-packages pytest -q && uv run ruff check $(ls -d libs apps examples/ecommerce_s1 examples/ecommerce_s2 benchmarks 2>/dev/null)`
```bash
git add libs/simkit/src/neorisk_simkit libs/simkit/tests/fixtures/relay libs/simkit/tests/test_exit_invariance.py libs/simkit/tests/test_engine_rounds.py
git commit -m "fix(engine): break routing ties by step-invariant sender keys

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 5: Compiled admission of created owners (rounds at scale)

S2 creates ~30M payment owners; S1 admits each creation in a Python loop and drops out of the compiled round loop whenever a creation is pending. This task moves admission into generated compiled code (D44) without changing any output.

**Files:**
- Create: `libs/simkit/src/neorisk_simkit/engine/admit.py` (`CreationQueue`, `FreeSlots`, `cq_min`, status constants)
- Modify: `engine/route.py` (`route_outbox(R, CQ, ob, n)` queues `OB_CREATE` rows), `engine/codegen.py` (generated `admit_created`; `drain_small_rounds` admits, phase `PH_ADMIT`; new drain signature), `engine/world.py` (`World.CQ`, `World.FS`, `World.admissions` as `int64[1]`; `admit_created` and `admit_population` use them; `pending_creations()`; `horizon` uses `cq_min`), `engine/rounds.py` (drain no longer waits for an empty creation list; resume from `PH_ADMIT`), `io/seal.py` (`_free_retired` gives slots back through `FS`), `spec/caps.py` (`requests_and_inboxes` + CQ bytes), `engine/rng.py` (`mix4` njit)
- Modify (tests): `libs/simkit/tests/test_engine_rounds.py` (`pending_creates == []` → `pending_creations() == 0` in `test_engine_rounds.py:167` only; delete `test_creations_inside_compiled_rounds_return_to_python` and Task 4's `test_admission_reads_creation_payloads_in_many_small_batches`, both superseded by `test_engine_admit.py`), `libs/simkit/tests/test_spec_validate.py` (`test_caps_formulas`)
- Test: `libs/simkit/tests/test_engine_admit.py`

**Interfaces:**
- Consumes: Task 4 creation payloads and `CREATE_HEAD.lamport`; fix-wave `k` and `inst = mix(creator inst, cause, ns, k)`; S1 `route.mark_touched`, the woken list (`RT_WOKEN`, `RT_WOKEN_N`), `World._reserve_pool()`, `world_state`, `HIDDEN_DTYPES`.
- Produces:
  - `engine/admit.py`:
    - `ADM_OK, ADM_CAP, ADM_LIVE, ADM_NODES = 0, 1, 2, 3`; `CQ_PAY = 7`.
    - `class CreationQueue(capacity: int)` with arrays `time, prio, cause, src_pid, src_seq, ns, handle, src_g, action, k` (int64[capacity]), `pay` (int64[capacity, 7]), `n` (int64[1]); `as_tuple()` in that order; `count() -> int`; `row_bytes = 17 * 8`.
    - `@njit cq_min(CQ) -> int64` (earliest queued time, `I64_MAX` when empty).
    - `class FreeSlots(sizes: list[int], bases: list[int])`: one FIFO ring per owner type `t` (plan order of owner partitions), initially `arange(size)`; `take(t, k) -> np.ndarray[int32]` (front `k`, raises `IndexError` if fewer), `give(t, lslots)` (appends `np.sort(lslots)` at the back), `n(t) -> int`, `as_tuple() -> (buf int32[Σ sizes], head int64[T], n int64[T], off int64[T], cap int64[T], base int64[T])`; `@njit fs_take1(FS, t) -> int32` (−1 when empty).
  - `route.route_outbox(R, CQ, ob, n) -> (status, k)`: `OB_CREATE` rows are appended to `CQ` (all-or-nothing with the other checks, before anything is delivered), each with its `k` (F-10): one commit's outbox rows are contiguous (the kernel reserved them before writing any), so for create row `i` the commit block is the maximal run of rows around `i` with the same `(src_g = pay[·, 7], cause)`, and `k = ordinal(handle_i) − min ordinal(handle_j)` over the `OB_CREATE` rows `j` of that block with the same `ns` (`ordinal = handle & 0xFFFFFF`, the contracts C1 rule); a row that would make `adm + cq_n + 1 > limit` returns `(NEED_CREATES, i)` with `i` the outbox row (`R` gains `RT_ADM = 27`, `int64[2]` = admissions this step, `max_admissions_per_step`; indices 25–26 are Task 4b's). `HAS_CREATE` and `skip_creates` are removed; `NEED_CREATES = 4`.
  - Generated `admit_created(W, R, CQ, FS, limit_t, out_slots) -> (status, value)`: admits every queued creation with `time < limit_t` in Task 4b's order — `(time, prio, cause, sender_keys(src_g), src_seq)`, the creator's six step-invariant sender keys in place of `src_pid` (F-12) — with the records S1 `World.admit_created` produced (fresh hidden fields, `Local` rows reset to `NULL`/0, state columns from the payload, `inst = mix4(creator inst, cause, ns, CQ.k)`, one `START` per process started by `on_created(table)` at the creation time with `PRIO_MESSAGE` and cause `cause`), marks each slot touched and appends it to the woken list and to `out_slots`; removes admitted rows from `CQ`. Node checking is all or nothing (F-10): before admitting any row it sums the `START` nodes of every due row and, if the reserve holds fewer, returns `(ADM_NODES, need)` having admitted nothing and left `CQ` unchanged. `ADM_CAP` / `ADM_LIVE` (fatal) return the `CQ` index of the row that does not fit. `ADM_OK` returns the number admitted.
  - `drain_small_rounds(W, out, R, CQ, FS, run, n_run, t1, min_par, shard_lo, shard_hi, sbuf, log, rs, adm_buf)`: horizon `horizon(R, t1, cq_min(CQ))`; after `PH_ROUTE2` a `PH_ADMIT` phase calls `admit_created(W, R, CQ, FS, t1, adm_buf)`; a non-OK status returns `DR_PYTHON` with `rs[RS_STATUS]` = the admission status; `n_run = take_runnable(R, t1, run)` then includes the admitted owners. `PH_ADMIT = 4`.
  - `World`: `CQ`, `FS`, `owner_type: dict[str, int]`, `pending_creations() -> int`, `admit_created(limit_t) -> np.ndarray` (wraps the generated function: `ADM_NODES` → `_take_reserve_nodes(need)` and retry the whole call; `ADM_CAP` → `CapExceeded("max_admissions_per_step", limit, attempted, process=<creating process>)`; `ADM_LIVE` → `CapExceeded("live_partition_state", max_live, max_live + 1, process=<creating process>)`); `route()` maps `NEED_CREATES` to the same `max_admissions_per_step` error naming the process of outbox row `k` (`ob["pay"][k, 10]`).
  - `rng.mix4(a, b, c, d) -> uint64` (njit): equals `rng.mix(a, b, c, d)` for int64 inputs.
  - `caps`: `requests_and_inboxes` adds `budget.max_admissions_per_step × CreationQueue.row_bytes`.

- [ ] **Step 1: Write the failing tests**

`libs/simkit/tests/test_engine_admit.py`:
```python
"""D44: created owners are admitted by generated compiled code, inside compiled rounds,
with exactly the records the Python admission produced."""

import numpy as np
import pytest
from conftest import make_run, records_of

from neorisk_simkit.engine import CapExceeded, rng
from neorisk_simkit.engine.admit import ADM_NODES, FreeSlots
from neorisk_simkit.engine.codegen import DR_PYTHON, PH_ADMIT, RS_PHASE, RS_STATUS
from neorisk_simkit.engine.rounds import run_step
from neorisk_simkit.engine.route import RT_ADM
from neorisk_simkit.engine.world import World

H = 3_600_000_000


def _steps(name, overrides=(), n=1, **engine):
    run = make_run(name, overrides, **engine)
    w = World.build(run, threads=1)
    w.init_shards()
    t, stats = run.start_us - run.warmup_us, []
    for _ in range(n):
        stats.append(run_step(w, t, t + run.engine.step_us))
        t += run.engine.step_us
    return run, w, stats


def test_mix4_matches_python_mix():
    for parts in [(1, 2, 3, 4), (-5, 2**62, 0, 7), (np.iinfo(np.int64).min, -1, 3, 0)]:
        assert int(rng.mix4(*parts)) == rng.mix(*parts)


def test_free_slots_are_fifo_with_sorted_returns():
    fs = FreeSlots([5, 3], [0, 5])
    assert fs.take(0, 2).tolist() == [0, 1] and fs.n(0) == 3
    fs.give(0, np.array([1, 0], np.int32))
    assert fs.take(0, 5).tolist() == [2, 3, 4, 0, 1]
    with pytest.raises(IndexError):
        fs.take(1, 4)


def test_creations_are_admitted_inside_compiled_rounds(monkeypatch):
    run = make_run("spawn", ["create_on_answer=1"], parallel_min_partitions=10**9)
    w = World.build(run, threads=1)
    real, seen = w.eng.drain_small_rounds, []

    def spy(*args):
        code, n = real(*args)
        seen.append((int(code), int(w.round_state[RS_PHASE])))
        return code, n

    monkeypatch.setattr(w.eng, "drain_small_rounds", spy)
    t0 = run.start_us - run.warmup_us
    stats = run_step(w, t0, t0 + run.engine.step_us)
    assert all(code != DR_PYTHON for code, _ in seen)
    assert stats.compiled_rounds == stats.rounds - 1          # all but the first round
    paid = records_of(w, "paid")
    assert len(paid["time"]) == 3 and (paid["time"] == t0 + 200_000).all()
    assert w.pending_creations() == 0


@pytest.mark.parametrize("name,overrides", [
    ("spawn", ["create_on_answer=1"]), ("spawn", []), ("chain", []), ("creators", []),
    ("trace_shopper", [])])
def test_compiled_and_python_admission_give_identical_records(name, overrides):
    n = 4 if name == "creators" else 1
    _, a, sa = _steps(name, overrides, n=n, parallel_min_partitions=10**9)
    _, b, sb = _steps(name, overrides, n=n, parallel_min_partitions=1)
    assert [(s.rounds, s.owners_run, s.shard_cmds) for s in sa] == \
        [(s.rounds, s.owners_run, s.shard_cmds) for s in sb]
    tables = [e.name for e in a.plan.events]
    for t in tables:
        ra, rb = records_of(a, t), records_of(b, t)
        assert all(np.array_equal(ra[k], rb[k]) for k in ra), t


def test_live_cap_names_the_creating_process():
    with pytest.raises(CapExceeded, match=r"live_partition_state .*in process a_main$"):
        _steps("chain", ["live=2"])


def test_admission_cap_still_names_the_creating_process():
    with pytest.raises(CapExceeded, match=r"max_admissions_per_step .*in process acct_main$"):
        _steps("spawn", ["budget.max_admissions_per_step=2"])


def test_admission_short_of_nodes_admits_nothing_and_retries_identically(monkeypatch):
    """F-10: `ADM_NODES` admits no row and leaves `CQ` (and each row's `k`) as it was; after the
    refill the records equal an unforced run's. The reserve is drained to one node before every
    compiled drain call (its free nodes go to worker 0's list), so admitting 4 b's and 4 c's
    (one START each) always finds the reserve short first."""
    _, base, _ = _steps("chain", parallel_min_partitions=10**9)
    run = make_run("chain", parallel_min_partitions=10**9)
    w = World.build(run, threads=1)
    w.init_shards()
    real, seen = w.eng.drain_small_rounds, []

    def starved(*args):
        spare = int(w.pool.reserve_n[0]) - 1
        if spare > 0:
            w.pool.refill(0, spare)                  # reserve -> worker 0's free list
        code, n = real(*args)
        seen.append((int(code), int(w.round_state[RS_PHASE]), int(w.round_state[RS_STATUS])))
        return code, n

    monkeypatch.setattr(w.eng, "drain_small_rounds", starved)
    t0 = run.start_us - run.warmup_us
    run_step(w, t0, t0 + run.engine.step_us)
    assert (DR_PYTHON, PH_ADMIT, ADM_NODES) in seen   # the forced path really ran
    assert w.pending_creations() == 0
    for t in [e.name for e in w.plan.events]:
        ra, rb = records_of(base, t), records_of(w, t)
        assert all(np.array_equal(ra[k], rb[k]) for k in ra), t


def test_many_small_admission_batches_stay_compiled(monkeypatch):
    """S1 Codex CX3's workload (60 round trips x 3 creations in one step, slabs flushed
    mid-step), replacing S1's `created_rows_indexed` test: every creation is admitted once, and
    admission never leaves the compiled loop."""
    run = make_run("spawn", ["create_on_answer=1", "rounds=60"], slab_bytes=2048,
                   parallel_min_partitions=10**9)
    w = World.build(run, threads=1)
    w.init_shards()
    real, seen = w.eng.drain_small_rounds, []

    def spy(*args):
        code, n = real(*args)
        seen.append((int(code), int(w.round_state[RS_PHASE])))
        return code, n

    monkeypatch.setattr(w.eng, "drain_small_rounds", spy)
    t0 = run.start_us - run.warmup_us
    stats = run_step(w, t0, t0 + run.engine.step_us)
    assert int(w.R[RT_ADM][0]) == 3 * 60 and w.pending_creations() == 0
    assert stats.compiled_rounds >= 60
    assert (DR_PYTHON, PH_ADMIT) not in seen
```
(`NodePool.refill(w, n)` moves `n` reserve nodes to worker `w`'s free list, as Task 2's `resume_owner` test uses it; `_take_reserve_nodes` splices them back.)

In `libs/simkit/tests/test_engine_rounds.py`: replace `w.pending_creates == []` by `w.pending_creations() == 0` at line 167 (the only other occurrence, line 252, is inside the test deleted next), delete `test_creations_inside_compiled_rounds_return_to_python` (superseded by `test_creations_are_admitted_inside_compiled_rounds`) and delete Task 4's `test_admission_reads_creation_payloads_in_many_small_batches` (its spy on `World.admit_created` no longer sees compiled admissions; superseded by `test_many_small_admission_batches_stay_compiled`).

In `libs/simkit/tests/test_spec_validate.py::test_caps_formulas` add:
```python
    from neorisk_simkit.engine.admit import CreationQueue
    from neorisk_simkit.spec.caps import OUTBOX_ROW_BYTES, PAYLOAD_W
    assert caps["requests_and_inboxes"].hard_bytes == (
        run.engine.max_messages_per_step * OUTBOX_ROW_BYTES
        + run.engine.payload_slots * 8 * PAYLOAD_W
        + run.budget.max_admissions_per_step * CreationQueue.row_bytes)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --all-packages pytest libs/simkit/tests/test_engine_admit.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'neorisk_simkit.engine.admit'`.

- [ ] **Step 3: Implement `engine/admit.py` and `rng.mix4`**

`rng.mix4(a, b, c, d)`: `h = mix64(u64(0) ^ u64(a)); h = mix64(h ^ u64(b)); h = mix64(h ^ u64(c)); return mix64(h ^ u64(d))` — `u64` of a negative int64 is its two's-complement value, matching `p & MASK64`.

`FreeSlots`: `buf` is one int32 array of `Σ sizes` with segment `t` at `off[t]:off[t]+cap[t]`; `head[t]` the ring start; `n[t]` the count. `take` reads `n` entries from `head` (wrapping), advances `head`, decrements `n`; `give` writes `np.sort(lslots)` after the last entry (wrapping), increments `n` (a `give` beyond `cap` is an internal error). `fs_take1` is the njit one-slot version used by generated code.

- [ ] **Step 4: Implement the generated `admit_created` and the drain phase**

In `codegen.py`:
- `_Gen.admit()` emits `admit_created(W, R, CQ, FS, limit_t, out_slots)` (not inlined):
  1. collect due rows `i < CQ.n` with `time[i] < limit_t`; order them exactly as Task 4b orders routing: stable argsorts by `src_seq`, then the six `sender_keys` of the creator's `src_g` (innermost first), then `cause`, `prio`, `time`;
  2. `k` is read from `CQ.k` (computed once by `route_outbox` when the row was queued, F-10); it is never recomputed over the remaining due rows, so a retry cannot shift it;
  3. node check, all or nothing (F-10): `need = Σ _NS_NSTART[ns[i]]` over the due rows (`_NS_NSTART`: generated per-namespace tuple, the number of `on_created(ns)` processes); if the reserve is short (`R[RT_POOL][P_FREE_N][0] < need`) return `(ADM_NODES, need)` before touching any row, slot or counter;
  4. per row, in order: `adm = R[RT_ADM]`; if `adm[0] + 1 > adm[1]` → return `(ADM_CAP, i)`; owner type `t` and ptype come from generated per-namespace constants (`_NS_TYPE`, `_NS_PTYPE` tuples; plan-structural, not population-dependent); `ls = fs_take1(FS, t)`, `-1` → `(ADM_LIVE, i)` (both fatal: `World` raises, so a partly admitted `CQ` is never resumed); else `adm[0] += 1`, `g = FS.base[t] + ls`, write the hidden fields as S1 `_reset_slots` does (`pid = self_id = handle`, `alive = 1`, `clock = rseq = cseq = pending = susp_delta = 0`, `occ[g, :] = 0`, `ordn[g, :] = 0`, `retire_at = susp_t = I64_MAX`, `last_t = I64_MIN`, `inst = mix4(inst[src_g], cause, ns, CQ.k[i])` viewed as int64, `ckey[g] = (time, cause, inst[src_g], CQ.k[i])` per Task 4b), reset every `Local` row of the type's processes (`ref` → `NULL`, else 0; 2-D rows whole), copy `pay[i, j]` into state column `j`, `q_push` one `START` per started process (reserve pool, worker 0; step 3 guaranteed the nodes) with `cause`, `mark_touched(R, g)`, append `g` to the woken list and `out_slots`;
  5. compact `CQ` (keep rows not admitted, in their order, with their `k`) and return `(ADM_OK, n_admitted)`.
- `drain_small_rounds`: new parameters `CQ, FS` after `R` and `adm_buf` last; `h = horizon(R, t1, cq_min(CQ))`; after `PH_ROUTE2`:
  ```
  "    rs[_RS_PHASE] = _PH_ADMIT",
  "    st, na_ = admit_created(W, R, CQ, FS, t1, adm_buf)",
  "    if st != 0:", *py,
  ```
  and the no-progress test becomes `n_run == 0 and sc == 0 and na_ == 0`. `route_outbox` calls pass `CQ`.

- [ ] **Step 5: Wire `World` and `rounds`**

- `World.build`: `self.owner_type = {p.name: i for i, p in enumerate(owner partitions)}`; `self.FS = FreeSlots([max_live...], [slot_base...])` (replacing `free_lslots`); `self.CQ = CreationQueue(budget.max_admissions_per_step)`; `R` gains `RT_ADM = np.array([0, budget.max_admissions_per_step], np.int64)`; `self.admit_buf = np.zeros(max(1, budget.max_admissions_per_step), np.int64)`.
- `admit_population` takes slots with `self.FS.take(self.owner_type[part.name], k)` (raising `CapExceeded("live_partition_state", ...)` as before when fewer are free).
- `admit_created(limit_t)` loops on the generated function as listed in Interfaces; `begin_step` resets `R[RT_ADM][0] = 0`; `pending_creations()` is `int(self.CQ.n[0])`; `horizon(t1)` uses `cq_min(self.CQ.as_tuple())`.
- `route()` no longer builds `_Creation`s: it passes `CQ` to `route_outbox` and handles `NEED_CREATES`. Delete `_Creation` and `pending_creates`.
- `rounds.run_step`: enter `_drain` whenever `stats.rounds > 0 and len(runnable) < small` (pass the new arguments `CQ`, `FS` and `adm_buf` in `rounds._drain`'s call); `_closed` tests `world.pending_creations() == 0`; `_python_round` resuming at `PH_ADMIT` first handles the status (`ADM_NODES` → `_take_reserve_nodes(need)` and continue; nothing was admitted), then admits.
- `route.route_outbox`: when queuing `OB_CREATE` row `i`, compute `k` as in Interfaces (scan back and forward from `i` while `pay[j, 7] == pay[i, 7]` and `cause[j] == cause[i]`; min ordinal over that block's `OB_CREATE` rows with `bnd[j] == bnd[i]`, the namespace code) and store it in `CQ.k`.
- `seal._free_retired`: `world.FS.give(world.owner_type[part.name], hid.lslot[mine])`.
- `caps.compute_caps`: `requests_and_inboxes` adds `budget.max_admissions_per_step * CreationQueue.row_bytes` (import lazily, as `hidden_bytes` does).

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run --all-packages pytest libs/simkit/tests/test_engine_admit.py libs/simkit/tests/test_engine_rounds.py libs/simkit/tests/test_spec_validate.py libs/simkit/tests/test_exit_invariance.py libs/simkit/tests/test_exit_trace_shopper.py libs/simkit/tests/test_exit_memory_caps.py -v`
Expected: PASS; `test_exit_trace_shopper.py` keeps its 4 rounds and every lamport.

- [ ] **Step 7: Uncompiled leg, output identity, full suite and lint**

Run: `NUMBA_DISABLE_JIT=1 uv run --all-packages pytest libs/simkit/tests/test_engine_admit.py -q`
Then confirm the S1 reduced profile is unchanged by this task: run `uv run --all-packages datagen run examples/ecommerce_s1 --profile full --seed 42 --set users=400000 --set run.span=30d --out /tmp/s2t5-after --force` on this commit and on the Task 4 commit (`git stash`/worktree), and compare sha256 over every file except `manifest.json` and `run_stats.json` (procedure of `.superpowers/sdd/2026-10-16-simulator-s1/task-24b-report.md`). Expected: identical (ecommerce_s1 creates no owners).
Run: `uv run --all-packages pytest -q && uv run ruff check $(ls -d libs apps examples/ecommerce_s1 examples/ecommerce_s2 benchmarks 2>/dev/null)`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add libs/simkit/src/neorisk_simkit libs/simkit/tests/test_engine_admit.py libs/simkit/tests/test_engine_rounds.py libs/simkit/tests/test_spec_validate.py
git commit -m "perf(engine): admit created owners in compiled code inside compiled rounds

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 6: Postings

**Files:**
- Create: `libs/simkit/tests/fixtures/ledger/{datagen.toml,specs/pack.py,specs/kernels.py}`
- Create: `libs/simkit/src/neorisk_simkit/io/consts.py`
- Modify: `libs/simkit/src/neorisk_simkit/spec/pack.py` (`Pack.postings`), `spec/plan.py` (`EventDef.group`), `io/seal.py` (`SealedStep.postings`), `io/writer.py` (`postings/` directory), `io/step_index.py` (events only), `io/manifest.py` + `io/dataset.py` (`posting_counts`), `io/schema/schema_json.py` (kind `"posting"`), `io/schema/sql.py` (postings get the event DDL treatment), `io/read.py` (`read_postings`), `io/replay/*` (import the io constants from `io/consts.py`), `checks/structural.py` (check postings too), `engine/run.py` (`rows_per_table` includes postings)
- Test: `libs/simkit/tests/test_spec_postings.py`

**Interfaces:**
- Consumes: S1 emitters (`out.emit_<name>`), `seal.event_table`, `writer.write_step`.
- Produces:
  - `Pack.postings(name, *, cols, owner=None, shard=None, doc="") -> str` (same checks as `Pack.event`; names shared with events and change groups).
  - `EventDef.group: str = "events"` (`"postings"` for posting tables). Every `plan.events` consumer that means "exported events" filters `group == "events"`.
  - `SealedStep.postings: dict[str, pa.Table] = field(default_factory=dict)` (a keyword field of the frozen dataclass; a literal `{}` default is not allowed); `SealedStep.events` holds events only.
  - Files `postings/<name>/date=YYYY-MM-DD/step-NNNNNN.parquet`; manifest `posting_counts: {name: rows}` with every declared posting table present (0 when it wrote nothing); `schema.json` table kind `"posting"`; `io.read.read_postings(dir, names=None) -> dict[str, pl.DataFrame]`.

- [ ] **Step 1: Write the `ledger` fixture**

`libs/simkit/tests/fixtures/ledger/datagen.toml`: a copy of `fixtures/holder/datagen.toml` with `name = "ledger"`, `seed = 17`, `span = "2d"`, `warmup = "1d"`, `step = "1d"`.

`libs/simkit/tests/fixtures/ledger/specs/pack.py`:
```python
"""Postings (D45) and accumulators (D46): each account opens with an amount and books two
postings per opening; tasks 7 and 9 extend it."""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, dist
from neorisk_simkit.spec.types import amount, cat, ref

from . import kernels as k

PACK = "ledger"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Config:
    accts: int = 6


def define(p: Pack, cfg: Config) -> None:
    acct = p.table("acct", key="acct_id", mutable=True, cols={"bal": amount(asset="USD")})
    p.owner("acct", table=acct, max_live=cfg.accts)
    p.population(acct, n=cfg.accts, initial=0.5,
                 arrivals=dist.poisson_daily(weekly=(1, 1, 1, 1, 1, 1, 1)))
    p.event("opened", owner="acct", cols={"acct_id": ref("acct"), "amount": amount(asset="USD")})
    p.postings("entry", owner="acct", doc="Double-entry postings of an opening", cols={
        "acct_id": ref("acct"), "account": cat("cash", "revenue"),
        "side": cat("debit", "credit"), "amount": amount(asset="USD")})
    p.process("acct_main", owner="acct", kernel=k.acct_main, config=cfg,
              start=p.on_created("acct"), commands=(0,))
```

`libs/simkit/tests/fixtures/ledger/specs/kernels.py`:
```python
from neorisk_simkit.engine import COMMIT, RETRY, START, Res, kernel


@kernel(state="acct", commands=(START,), max=Res(records={"opened": 1, "entry": 2}))
def acct_main(ctx, s, cmd, out):
    amt = 100 + ctx.self_id
    if not out.reserve(records={"opened": 1, "entry": 2}):
        return RETRY
    s.bal = amt
    out.emit_opened(ctx.t, acct_id=ctx.self_id, amount=amt)
    out.emit_entry(ctx.t, acct_id=ctx.self_id, account="cash", side="debit", amount=amt)
    out.emit_entry(ctx.t, acct_id=ctx.self_id, account="revenue", side="credit", amount=amt)
    return COMMIT
```

- [ ] **Step 2: Write the failing tests**

`libs/simkit/tests/test_spec_postings.py`:
```python
"""D45: postings are typed tables apart from events: own folder, own counts, never replayed."""

import json

import pytest
from conftest import FIXTURES

from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events, read_postings
from neorisk_simkit.io.replay.planner import ReplayError, ReplayRequest, plan_replay
from neorisk_simkit.io.schema.schema_json import load_schema
from neorisk_simkit.io.step_index import read_step_index
from neorisk_simkit.spec.pack import Pack, PackError
from neorisk_simkit.spec.types import amount


@pytest.fixture(scope="module")
def ds(tmp_path_factory):
    return run_to_dataset(FIXTURES / "ledger", "sample",
                          out_dir=tmp_path_factory.mktemp("ledger") / "run", threads=1).out_dir


def test_postings_are_written_apart(ds):
    m = json.loads((ds / "manifest.json").read_text())
    opened = m["counts"]["opened"]
    assert opened > 0 and "entry" not in m["counts"]
    assert m["posting_counts"] == {"entry": 2 * opened}
    assert sorted(ds.glob("postings/entry/date=*/step-*.parquet"))
    assert not (ds / "events" / "entry").exists()
    stats = json.loads((ds / "run_stats.json").read_text())
    assert stats["exported_events"] == opened


def test_postings_read_back_in_canonical_order(ds):
    p = read_postings(ds)["entry"]
    assert p.columns[:8] == ["event_id", "event_type", "event_time", "lamport", "partition_id",
                             "seq", "cause_id", "action_id"]
    assert p.height == 2 * read_events(ds)["opened"].height
    assert p.sort("event_time", "lamport", "partition_id", "seq").equals(p)
    assert set(p["side"]) == {"debit", "credit"}


def test_schema_index_and_replay_leave_postings_out(ds):
    kinds = {t["name"]: t["kind"] for t in load_schema(ds)["tables"]}
    assert kinds["entry"] == "posting" and kinds["opened"] == "event"
    assert "rows__entry" not in read_step_index(ds).column_names
    assert "entry" not in read_events(ds)
    with pytest.raises(ReplayError):
        plan_replay(ds, ReplayRequest(types=("entry",)))


def test_postings_share_the_record_namespace():
    p = Pack("x", 1)
    p.table("t", key="t_id", mutable=True, cols={"a": amount(asset="USD")})
    p.owner("t", table="t", max_live=1)
    p.event("e", owner="t", cols={"a": amount(asset="USD")})
    with pytest.raises(PackError, match="duplicate"):
        p.postings("e", owner="t", cols={"a": amount(asset="USD")})
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run --all-packages pytest libs/simkit/tests/test_spec_postings.py -v`
Expected: FAIL with `ImportError: cannot import name 'read_postings'` (and, once that exists, `AttributeError: 'Pack' object has no attribute 'postings'`).

- [ ] **Step 4: Implement**

- `Pack.postings`: same body as `Pack.event` with `"group": "postings"` stored; `Pack.event` stores `"group": "events"`. `build_plan` passes `group=d["group"]` into `EventDef(group=...)` (dataclass field with default `"events"`).
- `seal_step`: build `event_table` for every `plan.events` entry, then split: `events = {n: t for groups == "events"}`, `postings = {... == "postings"}`; `SealedStep(..., postings=postings)`; `stats["postings"] = {k: rows}`; structural `check_step` runs over both (postings are canonical too).
- `writer.write_step`: iterate `("events", sealed.events, "event_time")`, `("postings", sealed.postings, "event_time")`, `("history", sealed.history, "valid_from")`.
- `step_index.step_index_row`: iterate only `group == "events"`.
- `dataset._simulate`: `counts` over events, `posting_counts` over postings; `write_manifest(..., posting_counts=...)` writes `"posting_counts": dict(sorted(...))`. `exported_events` stays `sum(counts)`.
- `schema_json.schema_document`: `"kind": "posting" if e.group == "postings" else "event"`; `sql.py` treats `kind in ("event", "posting")` wherever it tests `kind == "event"` (primary key on `event_id`, `event_type` check, time index).
- `io.read.read_postings(dataset_dir, names=None)`: as `read_events` over kind `"posting"` and folder `postings/`.
- `run._account`: `rows_per_table` adds postings.
- Consolidate the io constants this task touches (S1 fix re-review minor): create `libs/simkit/src/neorisk_simkit/io/consts.py` with `NULL = std.NULL`, `I64_MAX`, `TS = pa.timestamp("us", tz="UTC")`, and import them in `io/seal.py`, `io/step_index.py`, `io/writer.py`, `io/replay/*`, `checks/structural.py` instead of their local `NULL` / `_I64_MAX` / `_TS` definitions (no behavior change).

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run --all-packages pytest libs/simkit/tests/test_spec_postings.py libs/simkit/tests/test_schema_sql.py libs/simkit/tests/test_replay_core.py -v`
Expected: PASS.

- [ ] **Step 6: Full suite and lint**

Run: `uv run --all-packages pytest -q && uv run ruff check $(ls -d libs apps examples/ecommerce_s1 examples/ecommerce_s2 benchmarks 2>/dev/null)`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add libs/simkit/src/neorisk_simkit libs/simkit/tests/fixtures/ledger libs/simkit/tests/test_spec_postings.py
git commit -m "feat(spec): postings tables, written and counted apart from events

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 7: Accumulators

**Files:**
- Modify: `libs/simkit/src/neorisk_simkit/spec/pack.py` (`Pack.accumulator` replaces the S1 stub), `spec/plan.py` (`AccumulatorDef`, `Plan.accumulators`), `spec/validate.py`, `engine/slabs.py` (`OUT_TAIL` + `acc`; `SlabSet.acc`), `engine/layout.py` (`KernelLayout.accumulators`), `engine/lower.py` (`out.add_<name>(v)`), `engine/codegen.py` (`_add_<name>`; checked dispatch snapshots `acc`), `engine/world.py` (`take_accumulators()`), `io/seal.py` (`SealedStep.accumulators`), `io/step_index.py` (`acc__<name>`), `io/manifest.py` + `io/dataset.py` (manifest `accumulators`), `libs/simkit/tests/fixtures/ledger/specs/{pack.py,kernels.py}`
- Test: `libs/simkit/tests/test_spec_accumulators.py`

**Interfaces:**
- Consumes: Task 6 `ledger` fixture.
- Produces:
  - `Pack.accumulator(name: str, ltype: LType) -> str` (kind `i64` or `amount`; `PackError` otherwise; names unique among accumulators).
  - `AccumulatorDef(name, code, ltype)`; `Plan.accumulators: tuple[AccumulatorDef, ...]` (default `()`).
  - Kernel call `out.add_<name>(value)` → generated `_add_<name>(out, ctx, v)`: `acc = out[OUT_ACC]; acc[code] = std.checked_add(acc[code], v)`.
  - `World.take_accumulators() -> dict[str, int]`: sums every worker's `acc`, zeroes them.
  - `SealedStep.accumulators: dict[str, int] = field(default_factory=dict)` (this step's delta, warm-up steps included); manifest `accumulators: {name: total over exported steps}`; step index `acc__<name>` (delta on exported steps, 0 on warm-up steps).

- [ ] **Step 1: Extend the fixture**

In `fixtures/ledger/specs/pack.py`: `Config` gains `add_then_reject: int = 0`; `define` adds `p.accumulator("fees", amount(asset="USD"))` before the process.

`fixtures/ledger/specs/kernels.py`, `acct_main` becomes:
```python
@kernel(state="acct", commands=(START,), max=Res(records={"opened": 1, "entry": 2}))
def acct_main(ctx, s, cmd, out):
    amt = 100 + ctx.self_id
    if not out.reserve(records={"opened": 1, "entry": 2}):
        return RETRY
    if ctx.cfg.add_then_reject == 1:
        out.add_fees(1)
        return reject(1)                            # a write before reject: checked mode fails
    s.bal = amt
    out.add_fees(ctx.self_id + 1)
    out.emit_opened(ctx.t, acct_id=ctx.self_id, amount=amt)
    out.emit_entry(ctx.t, acct_id=ctx.self_id, account="cash", side="debit", amount=amt)
    out.emit_entry(ctx.t, acct_id=ctx.self_id, account="revenue", side="credit", amount=amt)
    return COMMIT
```
(import `reject` from `neorisk_simkit.engine`).

- [ ] **Step 2: Write the failing tests**

`libs/simkit/tests/test_spec_accumulators.py`:
```python
"""D46: additive accumulators: no decision reads them; totals over exported steps."""

import json

import numpy as np
import pytest
from conftest import FIXTURES

from neorisk_simkit.engine import AbiViolation
from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events
from neorisk_simkit.io.seal import public_ids
from neorisk_simkit.io.step_index import read_step_index
from neorisk_simkit.spec.pack import Pack, PackError
from neorisk_simkit.spec.types import amount, i32, i64


def test_totals_cover_exported_steps_only(tmp_path):
    r = run_to_dataset(FIXTURES / "ledger", "sample", out_dir=tmp_path / "run", threads=1)
    m = json.loads((r.out_dir / "manifest.json").read_text())
    opened = read_events(r.out_dir)["opened"]
    # fees = acct dense id + 1 for every account opened in the exported window
    ids = public_ids(int(m["seed"]), "acct", np.arange(6))
    dense = {int(p): d for d, p in enumerate(ids)}
    assert m["accumulators"] == {"fees": sum(dense[a] + 1 for a in opened["acct_id"])}
    idx = read_step_index(r.out_dir).to_pydict()
    assert sum(idx["acc__fees"]) == m["accumulators"]["fees"]
    assert idx["acc__fees"][0] == 0                     # step 0 is warm-up


def test_an_empty_run_writes_zeros(tmp_path):
    """Review Focus #5: `accts=1` opens its single account in warm-up (initial 0.5 of 1 rounds
    to 1; no arrivals are left), so nothing is exported: zero counts, zero postings and every
    accumulator at 0 (Task 9 adds the laws' `checked = 0`)."""
    r = run_to_dataset(FIXTURES / "ledger", "sample", ["accts=1"], out_dir=tmp_path / "empty",
                       threads=1)
    m = json.loads((r.out_dir / "manifest.json").read_text())
    assert sum(m["counts"].values()) == 0
    assert m["posting_counts"] == {"entry": 0}
    assert m["accumulators"] == {"fees": 0}


def test_an_add_before_reject_is_a_write_in_checked_mode(tmp_path):
    with pytest.raises(AbiViolation, match="process acct_main wrote before returning reject"):
        run_to_dataset(FIXTURES / "ledger", "sample", ["add_then_reject=1"],
                       out_dir=tmp_path / "bad", threads=1, checked=True)


def test_accumulator_types():
    p = Pack("x", 1)
    p.accumulator("a", i64())
    p.accumulator("b", amount(asset="USD"))
    with pytest.raises(PackError, match="accumulator c: type must be i64 or amount"):
        p.accumulator("c", i32())
    with pytest.raises(PackError, match="duplicate accumulator 'a'"):
        p.accumulator("a", i64())
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run --all-packages pytest libs/simkit/tests/test_spec_accumulators.py -v`
Expected: FAIL with `PackError: accumulator arrives in S2`.

- [ ] **Step 4: Implement**

- `Pack.accumulator`: store `{"name", "ltype"}` in `self.accumulators` (dict, declaration order); errors as tested.
- `build_plan`: `accumulators=tuple(AccumulatorDef(name, i, lt) ...)`.
- `slabs.OUT_TAIL = ("outbox", "lat", "shard_n", "seed", "cmd_kind", "acc")`; `SlabSet.acc = np.zeros(max(1, len(plan.accumulators)), np.int64)` appended in `as_tuple`.
- `layout.KernelLayout.accumulators: dict[str, int]` (every accumulator, by code). `lower._out_call`: `m.startswith("add_") and m[4:] in lay.accumulators` → one positional argument → `_add_<name>(out, ctx, v)`.
- `codegen`: `_add_<name>` as in Interfaces (inlined helper). `checked_dispatch` snapshots `acc0 = out[OUT_ACC].copy()` beside `cnt0` and adds `_same(acc0, out[OUT_ACC])` to the unchanged test.
- `World.take_accumulators()`; `seal_step` calls it and stores `accumulators` on the sealed step; `Simulation` sums exported deltas into `stats["accumulators"]`; `step_index_row` adds `acc__<name>` (0 when not exported); `write_step_index` types `acc__*` columns int64; manifest `accumulators`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run --all-packages pytest libs/simkit/tests/test_spec_accumulators.py libs/simkit/tests/test_spec_postings.py -v`
Expected: PASS.

- [ ] **Step 6: Full suite and lint**

Run: `uv run --all-packages pytest -q && uv run ruff check $(ls -d libs apps examples/ecommerce_s1 examples/ecommerce_s2 benchmarks 2>/dev/null)`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add libs/simkit/src/neorisk_simkit libs/simkit/tests/fixtures/ledger libs/simkit/tests/test_spec_accumulators.py
git commit -m "feat(spec): additive accumulators with per-step deltas and exported totals

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 8: `std.reservations`, `std.capped_pool` and the hot catalog group

**Files:**
- Create: `libs/simkit/src/neorisk_simkit/std/reservations.py`, `std/capped_pool.py`
- Modify: `libs/simkit/src/neorisk_simkit/std/__init__.py` (export both modules), `std/sources.py` (`catalog(..., hot_rows=0)`)
- Test: `libs/simkit/tests/test_std_reservations.py`

**Interfaces:**
- Consumes: S1 `std.catalog`, `Local`.
- Produces:
  - `std.reservations.fields(slots: int) -> dict[str, str]` = `{"res_hold": f"ref[{slots}]", "res_item": f"i32[{slots}]", "res_qty": f"i32[{slots}]", "res_ckt": f"ref[{slots}]"}` (`ValueError("reservations need at least 2 slots")` below 2); `NO_SLOT = -1`. A free slot is `res_hold[j] == std.NULL` (the `Local` fill).
  - `std.capped_pool.init(cap: int) -> dict[str, list[int]]` = `{"remaining": [cap], "granted": [0]}` for a one-shard pool with state `{"remaining": "i64", "granted": "i64"}` (`ValueError("pool cap must be >= 0")`); `@njit(cache=True) take(remaining, amount) -> int`: `amount` if `0 < amount <= remaining` else `0` (no partial grants: the cap is exact, §07).
  - `std.catalog(n, category, price, group, weight, hot_rows: int = 0)`: rows `[0, hot_rows)` get `sku_group = 0` (D53); `ValueError("hot_rows must be in [0, n]")`.

- [ ] **Step 1: Write the failing tests**

`libs/simkit/tests/test_std_reservations.py`:
```python
import numpy as np
import pytest

from neorisk_simkit import std
from neorisk_simkit.engine import Local
from neorisk_simkit.engine.rng import name_key
from neorisk_simkit.spec import dist
from neorisk_simkit.spec.plan import Column, TableDef
from neorisk_simkit.spec.types import amount, cat, i16


def test_reservation_fields_fit_a_local():
    f = std.reservations.fields(64)
    assert f == {"res_hold": "ref[64]", "res_item": "i32[64]", "res_qty": "i32[64]",
                 "res_ckt": "ref[64]"}
    assert Local(**f).fields["res_hold"] == ("ref", 64)
    with pytest.raises(ValueError, match="at least 2 slots"):
        std.reservations.fields(1)


def test_capped_pool_grants_whole_claims_only():
    take = std.capped_pool.take
    assert take(300, 100) == 100 and take(100, 100) == 100
    assert take(99, 100) == 0 and take(0, 1) == 0 and take(500, 0) == 0
    assert take.py_func(99, 100) == 0                        # same uncompiled
    assert std.capped_pool.init(300) == {"remaining": [300], "granted": [0]}
    with pytest.raises(ValueError, match="cap must be >= 0"):
        std.capped_pool.init(-1)


def test_catalog_hot_rows_are_group_zero():
    src = std.catalog(n=200, category=dist.categorical({"a": 1.0}),
                      price=dist.uniform_int(100, 200), group=dist.uniform_int(1, 7),
                      weight=dist.zipf(s=1.07), hot_rows=20)
    t = TableDef("sku", 0, "sku_id", (Column("category", cat("a")),
                                      Column("price", amount(asset="USD")),
                                      Column("sku_group", i16())), False, "", None, src, False)
    rows = src.generate(200, t, seed=3, stream=name_key("sku"))
    g = np.asarray(rows["sku_group"])
    assert (g[:20] == 0).all() and (g[20:] >= 1).all()
    with pytest.raises(ValueError, match=r"hot_rows must be in \[0, n\]"):
        std.catalog(n=5, category=dist.categorical({"a": 1.0}), price=dist.uniform_int(1, 2),
                    group=dist.uniform_int(0, 1), weight=dist.zipf(s=1.1), hot_rows=6)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --all-packages pytest libs/simkit/tests/test_std_reservations.py -v`
Expected: FAIL with `AttributeError: module 'neorisk_simkit.std' has no attribute 'reservations'`.

- [ ] **Step 3: Implement** as in Interfaces. `CatalogSource` gains the field `hot_rows: int = 0`; `generate` sets `out["sku_group"][:hot_rows] = 0` after drawing. `std/__init__.py` imports `capped_pool` and `reservations` (module objects) and lists them in `__all__`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --all-packages pytest libs/simkit/tests/test_std_reservations.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Full suite, lint and commit**

Run: `uv run --all-packages pytest -q && uv run ruff check $(ls -d libs apps examples/ecommerce_s1 examples/ecommerce_s2 benchmarks 2>/dev/null)`
```bash
git add libs/simkit/src/neorisk_simkit/std libs/simkit/tests/test_std_reservations.py
git commit -m "feat(std): reservations hold table, capped pool, hot catalog rows

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 9: Laws I — evaluation engine, row laws and state laws

**Files:**
- Create: `libs/simkit/src/neorisk_simkit/checks/laws.py`
- Modify: `libs/simkit/src/neorisk_simkit/spec/law.py` (`total_le`, `balanced`), `spec/validate.py` (law paths; drop the "not evaluated until S2" warning), `spec/project.py` (`budget.max_checker_keys`), `spec/caps.py` (`checker_state`), `engine/errors.py` (`LawViolation`), `engine/run.py` (`Simulation` owns a `LawBook`, feeds it every step; `check_s`), `io/seal.py` (`seal_step(..., law_tables=)`, `SealedStep.warmup_rows`; F-01), `io/dataset.py` + `io/manifest.py` (manifest `laws`; `stage_seconds["check"]`), `checks/__init__.py` (docstring), `apps/datagen/src/datagen/run_cmds.py` + `apps/datagen/src/datagen/benchmark.py` (exit 4, D58), `libs/simkit/tests/fixtures/ledger/specs/{pack.py,kernels.py}`
- Test: `libs/simkit/tests/test_checks_laws.py`, `apps/datagen/tests/test_datagen_run_cli.py` (append)

**Interfaces:**
- Consumes: Tasks 6–7 (`SealedStep.events`, `.postings`, `ledger` fixture); S1 `LawSpec`, `CheckDef`, `World.state`, `World.hidden.alive`, `World.slot_base`.
- Produces:
  - `law.total_le(lhs: str, limit: int) -> LawSpec`; `law.balanced(table: str, *, amount: str = "amount", side: str = "side", by: tuple[str, ...] = ("partition_id", "lamport")) -> LawSpec`.
  - `errors.LawViolation(check_id, table, partition_id, seq, action_id, detail)`; attributes of the same names; message `f"law {check_id} violated in {table} at (partition_id {partition_id}, seq {seq}), action {action_id}: {detail}"` (state laws: `table = "state <path>"`, `seq = -1`, `action_id = -1`).
  - `checks.laws.resolve_path(plan, path) -> tuple[str, str, str]`: `("event", table, column)` for an event or posting column, `("owner", partition, column)` for an owner table column, `("shard", partition, field)` for a shard state field; `ValueError(f"unknown path {path!r}")` otherwise.
  - `checks.laws.LawBook(plan, *, max_keys: int)`: `tables -> frozenset[str]` (the event and posting tables any check reads); `step(sealed, world, *, exported: bool = True) -> dict[str, int]` (rows checked per check this step; raises `LawViolation` for a required law). With `exported=False` (a warm-up step, F-01: §11 reducers start from the opening snapshot) it reads `sealed.warmup_rows` instead of `sealed.events` / `sealed.postings`, updates carried state only — `total_le` running totals, `at_most_once` key sets (Task 10: `sum_le` sums, open `resolved` keys) — and returns `0` for every check: nothing is counted in `checked` or `violations` and nothing raises (a duplicate inside warm-up is not judged); state laws and `balanced` do nothing on warm-up steps. `finish(end_us: int) -> None`; `report() -> dict[str, dict]` = `{id: {"law": kind, "required": bool, "checked": int, "violations": int, "censored": int, "first": None | {"table", "partition_id", "seq", "action_id", "detail"}}}`; `keys -> int` (carried keys; above `max_keys` raises `CapExceeded("checker_state", 24 * max_keys, 24 * keys)`).
  - Laws evaluated here: `never_negative` (event column: each row; owner/shard state: every live value at each exported seal), `total_le` (running total over the run), `at_most_once` (keys seen across the run, carried as a sorted int64 array; multi-column keys are hashed with `rng.mix` per row), `balanced` (per step: Σ debit − Σ credit = 0 per `by` group; `side` values `"debit"`/`"credit"`). Task 10 adds `sum_le` and `resolved`; until then `step` counts them as `checked = 0`.
  - `seal.seal_step(world, step, t0, t1, exported, id_bases, *, law_tables: frozenset[str] = frozenset())`: on a warm-up step it also builds `SealedStep.warmup_rows: dict[str, pa.Table] = field(default_factory=dict)` = `{name: event_table(e, records[name], dict(id_bases), seed)}` for each event or posting table named in `law_tables`, from the full (remapped) rows before D20 empties them; `dict(id_bases)` is a throwaway copy, so exported `event_id`s are unchanged. On exported steps `warmup_rows` stays empty.
  - `Simulation.steps()`: `seal_step(..., law_tables=self.laws.tables)`, then for every step `self.laws.step(sealed, self.world, exported=sealed.exported)`, then `sealed.warmup_rows.clear()` (never written).
  - `Simulation.stats["laws"] = LawBook.report()` after the run; `stats["check_s"]`; `run_stats.json` `stage_seconds["check"]`; manifest `laws`.
  - `Budget.max_checker_keys: int` (toml `budget.max_checker_keys`, default `50_000_000`); `caps` `checker_state` = `24 × max_checker_keys` when the plan declares checks, else 0 (keys carried from warm-up count too). `compute_caps` keeps all 11 `CAP_ITEMS`, `entity_buffers` included (only the `checker_state` entry changes).
  - `datagen run` exits 4 on `LawViolation`; the benchmark child too.

- [ ] **Step 1: Extend the `ledger` fixture**

`fixtures/ledger/specs/pack.py`: `Config` gains `bad: int = 0`; `define` appends:
```python
    p.check("chk.opened_positive", law.never_negative("opened.amount"), required=True)
    p.check("chk.entries_balance", law.balanced("entry"), required=True)
    p.check("chk.bal_positive", law.never_negative("acct.bal"))
```
(`from neorisk_simkit.spec import Pack, dist, law`). In `kernels.py` `acct_main`: `amt = 100 + ctx.self_id - 1000 * ctx.cfg.bad`.

- [ ] **Step 2: Write the failing tests**

`libs/simkit/tests/test_checks_laws.py`:
```python
"""D47: laws evaluated on sealed steps in canonical order; failures cite (partition_id, seq)
and action ID."""

import dataclasses
import json
from types import SimpleNamespace

import pyarrow as pa
import pytest
from conftest import FIXTURES, make_run

from neorisk_simkit.checks.laws import LawBook, resolve_path
from neorisk_simkit.engine import CapExceeded
from neorisk_simkit.engine.errors import LawViolation
from neorisk_simkit.engine.world import World
from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.spec import law
from neorisk_simkit.spec.plan import CheckDef

TS = pa.timestamp("us", tz="UTC")


def _plan(*checks):
    run = make_run("ledger")
    return dataclasses.replace(run.plan, checks=tuple(CheckDef(i, lw, req)
                                                      for i, lw, req in checks))


def _table(rows, cats=()):
    """Rows as an event/posting table: common columns first, then the given ones."""
    n = len(rows)
    cols = {"event_id": pa.array(range(1, n + 1), pa.int64()),
            "event_type": pa.array(["x"] * n, pa.string()),
            "event_time": pa.array([r["t"] for r in rows], pa.int64()).cast(TS),
            "lamport": pa.array([r.get("lamport", i + 1) for i, r in enumerate(rows)], pa.int64()),
            "partition_id": pa.array([r.get("pid", 1) for r in rows], pa.int64()),
            "seq": pa.array([r.get("seq", i) for i, r in enumerate(rows)], pa.int32()),
            "cause_id": pa.nulls(n, pa.int64()),
            "action_id": pa.array([r.get("action", 0) for r in rows], pa.int16())}
    for k in rows[0]:
        if k in ("t", "lamport", "pid", "seq", "action"):
            continue
        if k in cats:
            cols[k] = pa.array([r[k] for r in rows], pa.string()).dictionary_encode()
        else:
            cols[k] = pa.array([r[k] for r in rows], pa.int64())
    return pa.table(cols)


def _sealed(t0, t1, events=None, postings=None):
    return SimpleNamespace(step=0, t_start=t0, t_end=t1, exported=True,
                           events=events or {}, postings=postings or {}, history={},
                           entities={}, stats={}, warmup_rows={})


def _warm(t0, t1, rows):
    """A warm-up step: nothing exported; the law tables' rows ride in `warmup_rows` (F-01)."""
    return SimpleNamespace(step=0, t_start=t0, t_end=t1, exported=False, events={},
                           postings={}, history={}, entities={}, stats={}, warmup_rows=rows)


def test_paths_resolve():
    plan = make_run("ledger").plan
    assert resolve_path(plan, "opened.amount") == ("event", "opened", "amount")
    assert resolve_path(plan, "entry.amount") == ("event", "entry", "amount")
    assert resolve_path(plan, "acct.bal") == ("owner", "acct", "bal")
    with pytest.raises(ValueError, match="unknown path 'acct.nope'"):
        resolve_path(plan, "acct.nope")


def test_never_negative_cites_the_row():
    book = LawBook(_plan(("chk.pos", law.never_negative("opened.amount"), True)), max_keys=10)
    ok = _table([{"t": 1, "acct_id": 1, "amount": 5}])
    assert book.step(_sealed(0, 10, {"opened": ok}), None) == {"chk.pos": 1}
    bad = _table([{"t": 11, "acct_id": 1, "amount": 5},
                  {"t": 12, "acct_id": 2, "amount": -3, "pid": 7, "seq": 3, "action": 0}])
    with pytest.raises(LawViolation, match=r"law chk.pos violated in opened at "
                                           r"\(partition_id 7, seq 3\), action 0: amount = -3"):
        book.step(_sealed(10, 20, {"opened": bad}), None)


def test_non_required_violations_are_counted():
    book = LawBook(_plan(("chk.soft", law.never_negative("opened.amount"), False)), max_keys=10)
    t = _table([{"t": 1, "acct_id": 1, "amount": -1}, {"t": 2, "acct_id": 2, "amount": -2}])
    book.step(_sealed(0, 10, {"opened": t}), None)
    r = book.report()["chk.soft"]
    assert (r["checked"], r["violations"], r["required"]) == (2, 2, False)
    assert r["first"]["detail"] == "amount = -1"


def test_total_le_carries_across_steps():
    book = LawBook(_plan(("chk.cap", law.total_le("opened.amount", 10), True)), max_keys=10)
    book.step(_sealed(0, 10, {"opened": _table([{"t": 1, "acct_id": 1, "amount": 6}])}), None)
    with pytest.raises(LawViolation, match="total 11 exceeds 10"):
        book.step(_sealed(10, 20, {"opened": _table([{"t": 11, "acct_id": 1, "amount": 5}])}),
                  None)


def test_at_most_once_within_and_across_steps():
    book = LawBook(_plan(("chk.once", law.at_most_once("opened", key="acct_id"), True)),
                   max_keys=10)
    book.step(_sealed(0, 10, {"opened": _table([{"t": 1, "acct_id": 4, "amount": 1},
                                                {"t": 2, "acct_id": 5, "amount": 1}])}), None)
    assert book.keys == 2
    with pytest.raises(LawViolation, match="acct_id 4 seen before"):
        book.step(_sealed(10, 20, {"opened": _table([{"t": 11, "acct_id": 4, "amount": 1}])}),
                  None)


def test_warmup_rows_build_state_without_judging():
    """F-01 (§11: reducers start from the opening snapshot): warm-up rows feed running totals
    and key sets but are never counted, cited or judged."""
    book = LawBook(_plan(("chk.cap", law.total_le("opened.amount", 10), True),
                         ("chk.once", law.at_most_once("opened", key="acct_id"), True)),
                   max_keys=10)
    warm = _table([{"t": 1, "acct_id": 4, "amount": 6}, {"t": 2, "acct_id": 4, "amount": 1}])
    assert book.step(_warm(0, 10, {"opened": warm}), None, exported=False) == \
        {"chk.cap": 0, "chk.once": 0}               # the warm-up duplicate of 4 is not judged
    assert book.report()["chk.cap"]["checked"] == book.report()["chk.once"]["checked"] == 0
    with pytest.raises(LawViolation, match="total 11 exceeds 10"):   # 7 from warm-up + 4
        book.step(_sealed(10, 20, {"opened": _table([{"t": 11, "acct_id": 5, "amount": 4}])}),
                  None)


def test_a_key_seen_in_warmup_is_seen_before():
    book = LawBook(_plan(("chk.once", law.at_most_once("opened", key="acct_id"), True)),
                   max_keys=10)
    book.step(_warm(0, 10, {"opened": _table([{"t": 1, "acct_id": 4, "amount": 1}])}), None,
              exported=False)
    with pytest.raises(LawViolation, match="acct_id 4 seen before"):
        book.step(_sealed(10, 20, {"opened": _table([{"t": 11, "acct_id": 4, "amount": 1}])}),
                  None)


def test_balanced_postings_per_commit():
    book = LawBook(_plan(("chk.bal", law.balanced("entry"), True)), max_keys=10)
    good = _table([{"t": 1, "lamport": 3, "pid": 9, "acct_id": 1, "account": "cash",
                    "side": "debit", "amount": 7},
                   {"t": 1, "lamport": 3, "pid": 9, "acct_id": 1, "account": "revenue",
                    "side": "credit", "amount": 7}], cats=("account", "side"))
    assert book.step(_sealed(0, 10, postings={"entry": good}), None) == {"chk.bal": 2}
    bad = _table([{"t": 11, "lamport": 4, "pid": 9, "seq": 5, "acct_id": 1, "account": "cash",
                   "side": "debit", "amount": 7}], cats=("account", "side"))
    with pytest.raises(LawViolation, match=r"\(partition_id 9, seq 5\).*debits 7 != credits 0"):
        book.step(_sealed(10, 20, postings={"entry": bad}), None)


def test_state_law_checks_live_owners():
    run = make_run("ledger")
    run = dataclasses.replace(run, plan=_plan(("chk.bal", law.never_negative("acct.bal"), True)))
    w = World.build(run, threads=1)
    g = w.admit_population(run.start_us - run.warmup_us, run.start_us)
    book = LawBook(run.plan, max_keys=10)
    assert book.step(_sealed(0, 10), w)["chk.bal"] == len(g)
    w.state["acct"][0][w.hidden.lslot[g[0]]] = -4
    with pytest.raises(LawViolation, match=r"in state acct.bal at \(partition_id \d+, seq -1\)"):
        book.step(_sealed(10, 20), w)


def test_checker_keys_are_capped():
    book = LawBook(_plan(("chk.once", law.at_most_once("opened", key="acct_id"), True)),
                   max_keys=1)
    with pytest.raises(CapExceeded, match="checker_state"):
        book.step(_sealed(0, 10, {"opened": _table([{"t": 1, "acct_id": 4, "amount": 1},
                                                    {"t": 2, "acct_id": 5, "amount": 1}])}),
                  None)


def test_a_run_reports_its_laws(tmp_path):
    r = run_to_dataset(FIXTURES / "ledger", "sample", out_dir=tmp_path / "ok", threads=1)
    laws = json.loads((r.out_dir / "manifest.json").read_text())["laws"]
    assert set(laws) == {"chk.opened_positive", "chk.entries_balance", "chk.bal_positive"}
    assert all(v["violations"] == 0 and v["checked"] > 0 for v in laws.values())
    stats = json.loads((r.out_dir / "run_stats.json").read_text())
    assert "check" in stats["stage_seconds"]


def test_a_required_violation_fails_the_run(tmp_path):
    out = tmp_path / "bad"
    with pytest.raises(LawViolation, match="chk.opened_positive"):
        run_to_dataset(FIXTURES / "ledger", "sample", ["bad=1"], out_dir=out, threads=1)
    assert not out.exists() and not out.with_suffix(".partial").exists()


def test_an_empty_run_checks_nothing(tmp_path):
    """Review Focus #5: the single account opens in warm-up (Task 7's `accts=1` run): the row
    laws pass vacuously with `checked = 0`, even though `bad=1` makes the warm-up row negative
    (warm-up rows are never judged, F-01)."""
    r = run_to_dataset(FIXTURES / "ledger", "sample", ["accts=1", "bad=1"],
                       out_dir=tmp_path / "empty", threads=1)
    laws = json.loads((r.out_dir / "manifest.json").read_text())["laws"]
    for k in ("chk.opened_positive", "chk.entries_balance"):
        assert (laws[k]["checked"], laws[k]["violations"]) == (0, 0), k
```

Append to `apps/datagen/tests/test_datagen_run_cli.py`:
```python
def test_required_law_violation_exits_4(tmp_path):
    assert main(["run", str(FIXTURES / "ledger"), "--profile", "sample", "--set", "bad=1",
                 "--out", str(tmp_path / "x")]) == 4
    assert not (tmp_path / "x").exists()
```
(`main` and `FIXTURES` are the module's existing names.)

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run --all-packages pytest libs/simkit/tests/test_checks_laws.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'neorisk_simkit.checks.laws'`.

- [ ] **Step 4: Implement**

- `checks/laws.py`: one evaluator per `CheckDef`, built from `resolve_path`. Tables arrive canonical; evaluators work column-wise with numpy/polars:
  - row laws read `partition_id`, `seq`, `action_id` of the first offending row for the citation; `detail` strings exactly: `f"{col} = {v}"` (never_negative), `f"total {t} exceeds {limit}"` (total_le), `f"{key} {k} seen before"` (at_most_once; multi-column keys print the first column), `f"debits {d} != credits {c}"` (balanced; cite the group's first row).
  - state laws: owners → for each slot `g` in `[slot_base, slot_base + max_live)` with `alive == 1`, value `state[part][j][lslot[g]]`, cite `partition_id = hidden.pid[g]`; shards → every shard, `partition_id = ptype << 56 | index`; `NULL` values of nullable columns are skipped.
  - Checks run in declaration order; within a check, a required violation raises at its first offending row in canonical order; a non-required one increments `violations` and keeps the first citation.
- `law.total_le`, `law.balanced` as in Interfaces.
- `validate.py`: for each check, `resolve_path` every path; per kind: `never_negative` path must resolve; `sum_le`/`total_le` sides must be event columns; `resolved` and `at_most_once` event names must exist with the key columns; `balanced` table must exist with `amount`, `side` (a `cat` holding `"debit"` and `"credit"`) and every `by` column (common columns allowed). Errors are `f"check {id}: {reason}"`. Remove the "checks declared but not evaluated until S2" warning.
- `Simulation`: `self.laws = LawBook(run.plan, max_keys=run.budget.max_checker_keys)`; every `seal_step` call passes `law_tables=self.laws.tables`; after each seal, warm-up or exported, `sealed.stats["laws"] = self.laws.step(sealed, self.world, exported=sealed.exported)` timed into `stats["check_s"]`, then `sealed.warmup_rows.clear()`; after the last step `self.laws.finish(end)` and `self.stats["laws"] = self.laws.report()`.
- `seal_step`: after the remap (step 3) and before `keep()` empties warm-up rows (D20), when `not exported` build `warmup_rows` for the names in `law_tables` as in Interfaces (posting tables included; Task 6's split happens on the same `event_table` outputs).
- `dataset`: manifest `laws=sim.stats["laws"]`; `run_stats.json` `stage_seconds["check"] = sim.stats["check_s"]`.
- `run_cmds.cmd_run` and `benchmark._child_main`: `except LawViolation as e: print(e, file=sys.stderr); return 4`; `benchmark.cmd_benchmark` passes child code 4 through like 2 and 3.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run --all-packages pytest libs/simkit/tests/test_checks_laws.py apps/datagen/tests/test_datagen_run_cli.py libs/simkit/tests/test_spec_validate.py -v`
Expected: PASS (`test_checks_laws.py`: 13 tests). `examples/ecommerce_s1` now evaluates `chk.stock_never_negative` (`inventory.on_hand`, a shard state field) on every exported seal; `apps/datagen/tests/test_example_ecom_s1.py` must stay green.

- [ ] **Step 6: Full suite, lint and commit**

Run: `uv run --all-packages pytest -q && uv run ruff check $(ls -d libs apps examples/ecommerce_s1 examples/ecommerce_s2 benchmarks 2>/dev/null)`
```bash
git add libs/simkit apps/datagen
git commit -m "feat(checks): evaluate declared laws on sealed steps; required failures exit 4

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 10: Laws II — keyed cross-step laws (`sum_le`, `resolved`) and censoring

**Files:**
- Modify: `libs/simkit/src/neorisk_simkit/checks/laws.py`
- Test: `libs/simkit/tests/test_checks_laws_keyed.py`

**Interfaces:**
- Consumes: Task 9 `LawBook`, `_plan`/`_table`/`_sealed` test helpers (re-declared in the new test file; test files do not import each other).
- Produces:
  - `sum_le(lhs, rhs, by)`: both sides `<event>.<column>`; per key (`by`, a column present in both events), in canonical order over the merged stream of both events, the running Σ lhs must stay ≤ the running Σ rhs at every lhs row; sums carried across steps (sorted key arrays). Detail: `f"{by} {k}: {lhs} total {l} exceeds {rhs} total {r}"`.
  - `resolved(event, by, key, within)`: every `event` row opens its key; the first later row of any `by` event with the same key closes it; a key still open when the step that contains `opened_at + within` ends is a violation (`f"{key} {k} opened at {t} not resolved within {within}"`, citing the opening row); a key open at `finish(end_us)` whose deadline is `>= end_us` is censored (`report()[id]["censored"]`), one whose deadline is `< end_us` is a violation. `within=None` means "by the end of the run": still open at the end → censored. Closing rows whose key was never opened (neither in warm-up nor exported) are ignored and counted in `report()[id]["unmatched"]`.
  - Warm-up steps (`exported=False`, F-01): `sum_le` adds warm-up rows of both sides to the carried per-key sums without judging; `resolved` opens keys from warm-up rows and closes them with warm-up or exported closing rows, but a key opened in warm-up is never judged, censored or cited — at its deadline (or at `finish`) it is dropped. An exported close of a warm-up opening is therefore matched, not `unmatched`.
  - Both count toward `keys`.
  - Evaluation order (also binding for Task 9's laws): within a step, checks run in declaration order and the first required check with a violation raises.

- [ ] **Step 1: Write the failing tests**

`libs/simkit/tests/test_checks_laws_keyed.py`:
```python
"""D47: keyed laws carried across steps; open keys at the end are censored, not violations."""

import dataclasses
from types import SimpleNamespace

import pyarrow as pa
import pytest
from conftest import make_run

from neorisk_simkit.checks.laws import LawBook
from neorisk_simkit.engine.errors import LawViolation
from neorisk_simkit.spec import law
from neorisk_simkit.spec.plan import CheckDef

TS = pa.timestamp("us", tz="UTC")
S = 1_000_000


def _plan(*checks):
    run = make_run("ledger")
    return dataclasses.replace(run.plan, checks=tuple(CheckDef(i, lw, req)
                                                      for i, lw, req in checks))


def _table(rows):
    n = len(rows)
    cols = {"event_id": pa.array(range(1, n + 1), pa.int64()),
            "event_type": pa.array(["x"] * n, pa.string()),
            "event_time": pa.array([r["t"] for r in rows], pa.int64()).cast(TS),
            "lamport": pa.array([r.get("lamport", 1) for r in rows], pa.int64()),
            "partition_id": pa.array([r.get("pid", 1) for r in rows], pa.int64()),
            "seq": pa.array([r.get("seq", i) for i, r in enumerate(rows)], pa.int32()),
            "cause_id": pa.nulls(n, pa.int64()),
            "action_id": pa.array([0] * n, pa.int16())}
    for k in ("acct_id", "amount"):
        cols[k] = pa.array([r[k] for r in rows], pa.int64())
    return pa.table(cols)


def _sealed(t0, t1, opened=None, entry=None):
    """`opened` is an event of the ledger fixture, `entry` its posting table."""
    return SimpleNamespace(step=0, t_start=t0, t_end=t1, exported=True,
                           events={} if opened is None else {"opened": opened},
                           postings={} if entry is None else {"entry": entry},
                           history={}, entities={}, stats={}, warmup_rows={})


def _warm(t0, t1, opened=None, entry=None):
    """A warm-up step (F-01): the law tables' rows ride in `warmup_rows`."""
    rows = {k: v for k, v in (("opened", opened), ("entry", entry)) if v is not None}
    return SimpleNamespace(step=0, t_start=t0, t_end=t1, exported=False, events={},
                           postings={}, history={}, entities={}, stats={}, warmup_rows=rows)


def _book(*checks):
    return LawBook(_plan(*checks), max_keys=100)


LE = ("chk.le", law.sum_le("opened.amount", "entry.amount", by="acct_id"), True)


def test_sum_le_runs_per_key_in_canonical_order():
    book = _book(LE)
    book.step(_sealed(0, 10, opened=_table([{"t": 2, "acct_id": 2, "amount": 3}]),
                      entry=_table([{"t": 1, "acct_id": 2, "amount": 5}])), None)
    with pytest.raises(LawViolation, match=r"acct_id 2: opened.amount total 7 exceeds "
                                           r"entry.amount total 5"):
        book.step(_sealed(10, 20, opened=_table([{"t": 13, "acct_id": 2, "amount": 4}])), None)


def test_sum_le_lhs_before_rhs_is_a_violation():
    book = _book(LE)
    with pytest.raises(LawViolation, match="acct_id 4: opened.amount total 1 exceeds "
                                           "entry.amount total 0"):
        book.step(_sealed(0, 10, opened=_table([{"t": 1, "acct_id": 4, "amount": 1}]),
                          entry=_table([{"t": 2, "acct_id": 4, "amount": 9}])), None)


def test_sum_le_carries_sums_across_steps():
    book = _book(LE)
    book.step(_sealed(0, 10, opened=_table([{"t": 2, "acct_id": 5, "amount": 3}]),
                      entry=_table([{"t": 1, "acct_id": 5, "amount": 10}])), None)
    book.step(_sealed(10, 20, opened=_table([{"t": 11, "acct_id": 5, "amount": 6}])), None)
    with pytest.raises(LawViolation, match="acct_id 5: opened.amount total 11 exceeds "
                                           "entry.amount total 10"):
        book.step(_sealed(20, 30, opened=_table([{"t": 21, "acct_id": 5, "amount": 2}])), None)


def test_sum_le_counts_the_right_side_seen_in_warmup():
    """F-01: a capture in warm-up and its refund after `start` (here: an opening in warm-up and
    a matching posting after `start`) pass; without the warm-up sums the posting would exceed 0."""
    book = _book(("chk.le2", law.sum_le("entry.amount", "opened.amount", by="acct_id"), True))
    book.step(_warm(0, 10, opened=_table([{"t": 1, "acct_id": 3, "amount": 5}])), None,
              exported=False)
    assert book.step(_sealed(10, 20, entry=_table([{"t": 11, "acct_id": 3, "amount": 5}])),
                     None) == {"chk.le2": 1}
    with pytest.raises(LawViolation, match="acct_id 3: entry.amount total 6 exceeds "
                                           "opened.amount total 5"):
        book.step(_sealed(20, 30, entry=_table([{"t": 21, "acct_id": 3, "amount": 1}])), None)


def test_a_close_of_a_warmup_opening_is_matched_not_judged():
    book = _book(RES)
    book.step(_warm(0, 10 * S, opened=_table([{"t": 1 * S, "acct_id": 9, "amount": 0},
                                              {"t": 8 * S, "acct_id": 8, "amount": 0}])),
              None, exported=False)          # key 9 misses its 6 s deadline in warm-up: dropped
    book.step(_sealed(10 * S, 20 * S, entry=_table([{"t": 12 * S, "acct_id": 8, "amount": 0}])),
              None)                          # key 8 (deadline 13 s) closes after `start`
    book.finish(20 * S)
    r = book.report()["chk.res"]
    assert (r["violations"], r["censored"], r["unmatched"], r["checked"]) == (0, 0, 0, 0)


RES = ("chk.res", law.resolved("opened", by=("entry",), key="acct_id", within="5s"), True)


def test_resolved_within_a_deadline():
    book = _book(RES)
    book.step(_sealed(0, 10 * S, opened=_table([{"t": 1 * S, "acct_id": 1, "amount": 0},
                                                {"t": 8 * S, "acct_id": 2, "amount": 0}]),
                      entry=_table([{"t": 3 * S, "acct_id": 1, "amount": 0}])), None)
    # key 2's deadline (13 s) lies after this step's end (10 s): not judged yet
    assert book.report()["chk.res"]["violations"] == 0
    with pytest.raises(LawViolation, match=r"acct_id 2 opened at 8000000 not resolved "
                                           r"within 5s"):
        book.step(_sealed(10 * S, 20 * S), None)          # 13 s < 20 s and still open


def test_a_close_before_the_deadline_resolves():
    book = _book(RES)
    book.step(_sealed(0, 10 * S, opened=_table([{"t": 8 * S, "acct_id": 6, "amount": 0}])),
              None)
    book.step(_sealed(10 * S, 20 * S, entry=_table([{"t": 12 * S, "acct_id": 6, "amount": 0}])),
              None)
    book.finish(20 * S)
    r = book.report()["chk.res"]
    assert (r["violations"], r["censored"], r["checked"]) == (0, 0, 1)


def test_open_keys_at_the_end_are_censored():
    book = _book(RES)
    book.step(_sealed(0, 10 * S, opened=_table([{"t": 8 * S, "acct_id": 7, "amount": 0}]),
                      entry=_table([{"t": 9 * S, "acct_id": 99, "amount": 0}])), None)
    book.finish(10 * S)                          # deadline 13 s >= end: censored
    r = book.report()["chk.res"]
    assert (r["violations"], r["censored"], r["unmatched"]) == (0, 1, 1)


def test_resolved_without_deadline_censors_at_the_end():
    book = _book(("chk.res", law.resolved("opened", by=("entry",), key="acct_id"), True))
    book.step(_sealed(0, 10, opened=_table([{"t": 1, "acct_id": 3, "amount": 0}])), None)
    book.finish(10)
    assert book.report()["chk.res"]["censored"] == 1
```

`law.resolved(...)` and `law.sum_le(...)` name `entry`, the ledger fixture's posting table: posting columns resolve like event columns (`resolve_path` returns `"event"` for both, D45).

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --all-packages pytest libs/simkit/tests/test_checks_laws_keyed.py -v`
Expected: FAIL — `sum_le`/`resolved` are still counted as `checked = 0`, so no `LawViolation` is raised and the report has no `censored`/`unmatched` counts.

- [ ] **Step 3: Implement** both evaluators as specified (polars: concatenate the step's rows of the involved tables with a source tag, sort by the canonical key, group-wise cumulative sums plus carried bases; for `resolved`, join opens to the first later close by key, carry the rest as `(key, opened_at, deadline, citation)` arrays). `within` is parsed with `spec.project.parse_duration`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --all-packages pytest libs/simkit/tests/test_checks_laws_keyed.py libs/simkit/tests/test_checks_laws.py -v`
Expected: PASS (`test_checks_laws_keyed.py`: 9 tests).

- [ ] **Step 5: Full suite, lint and commit**

Run: `uv run --all-packages pytest -q && uv run ruff check $(ls -d libs apps examples/ecommerce_s1 examples/ecommerce_s2 benchmarks 2>/dev/null)`
```bash
git add libs/simkit/src/neorisk_simkit/checks/laws.py libs/simkit/tests/test_checks_laws_keyed.py
git commit -m "feat(checks): keyed cross-step laws sum_le and resolved, with censoring

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 11: Referential integrity as a dense range check

**Files:**
- Modify: `libs/simkit/src/neorisk_simkit/checks/structural.py` (`ref_bounds`, `check_ref_range`, check name `ref_in_range`), `io/seal.py` (check every ref column after remap, before public IDs), `libs/simkit/tests/fixtures/spawn/specs/{pack.py,kernels.py}` (`bad_ref` knob)
- Test: `libs/simkit/tests/test_checks_refs.py`

**Interfaces:**
- Consumes: S1 seal remap, `id_bases`, populations, static tables.
- Produces:
  - `structural.ref_bounds(world, id_bases) -> dict[str, int]`: rows known per ref target: population tables → `pop.next` of their `World.populations` entry (owners admitted so far, not `n`: a ref to an owner that has not arrived is caught; F-05); static/recipe tables → their row count; created namespaces → `id_bases[ns]` (after this step's assignment). The range form replaces §11's "bitset over dense indices" (D48, recorded spec deviation).
  - `structural.check_ref_range(where: str, values: np.ndarray, target: str, bound: int) -> int`: rows checked (non-`NULL`); raises `EngineError(f"{where}: ref {v} outside [0, {bound}) of {target}")` for the first value outside.
  - `CHECKS` gains `"ref_in_range"`; manifest `checks["ref_in_range"]` counts checked values (exported steps; events, postings, history and created rows).

- [ ] **Step 1: Add the knob**

`fixtures/spawn/specs/pack.py` `Config`: `bad_ref: int = 0`. `kernels.py` `acct_main` emits `spawned` in two places (`create_on_answer == 0` in the `START` branch, `create_on_answer == 1` in the answer branch); both become `out.emit_spawned(ctx.t, acct_id=ctx.self_id + 1000 * ctx.cfg.bad_ref, pay_id=pay)` (F-18).

- [ ] **Step 2: Write the failing tests**

`libs/simkit/tests/test_checks_refs.py`:
```python
import json

import numpy as np
import pytest
from conftest import FIXTURES, make_run

from neorisk_simkit.checks.structural import check_ref_range, ref_bounds
from neorisk_simkit.engine import EngineError
from neorisk_simkit.engine.world import World
from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.std import NULL


def test_range_check_skips_null_and_names_the_column():
    assert check_ref_range("event e.x", np.array([0, 3, NULL], np.int64), "item", 4) == 2
    with pytest.raises(EngineError, match=r"event e.x: ref 4 outside \[0, 4\) of item"):
        check_ref_range("event e.x", np.array([1, 4], np.int64), "item", 4)


def test_runs_count_checked_refs(tmp_path):
    r = run_to_dataset(FIXTURES / "mini", "sample", out_dir=tmp_path / "ok", threads=1)
    assert json.loads((r.out_dir / "manifest.json").read_text())["checks"]["ref_in_range"] > 0


def test_a_dangling_ref_fails_the_seal(tmp_path):
    with pytest.raises(EngineError, match=r"event spawned.acct_id: ref 1000 outside \[0, 3\) "
                                          r"of acct"):
        run_to_dataset(FIXTURES / "spawn", "sample", ["bad_ref=1"], out_dir=tmp_path / "x",
                       threads=1)


def test_population_refs_are_bounded_by_admitted_owners():
    """F-05: `ledger` has 6 accounts, 3 initial (initial 0.5); before any arrival only dense
    indices 0..2 exist, so the bound is 3, not 6."""
    run = make_run("ledger")
    w = World.build(run, threads=1)
    t0 = run.start_us - run.warmup_us
    w.admit_population(t0, t0 + 1)
    assert ref_bounds(w, {})["acct"] == 3
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run --all-packages pytest libs/simkit/tests/test_checks_refs.py -v`
Expected: FAIL with `ImportError: cannot import name 'check_ref_range'`.

- [ ] **Step 4: Implement**: in `seal_step` after the remap (step 3) and the id-base update, compute `bounds = ref_bounds(world, id_bases)` and, for exported steps, call `check_ref_range` on every ref column of every event, posting, history and created table, accumulating `ref_in_range` into `stats["checks"]` (merged into the structural counts).

- [ ] **Step 5: Run tests, full suite, lint, commit**

Run: `uv run --all-packages pytest libs/simkit/tests/test_checks_refs.py -v && uv run --all-packages pytest -q && uv run ruff check $(ls -d libs apps examples/ecommerce_s1 examples/ecommerce_s2 benchmarks 2>/dev/null)`
Expected: PASS.
```bash
git add libs/simkit/src/neorisk_simkit libs/simkit/tests/fixtures/spawn libs/simkit/tests/test_checks_refs.py
git commit -m "feat(checks): referential integrity as a dense range check at seal

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 12: S2 slice — shoppers, multi-SKU carts, reservations with TTL, the hot group

**Files:**
- Create: `examples/ecommerce_s2/README.md`, `examples/ecommerce_s2/datagen.toml`, `examples/ecommerce_s2/specs/brief.md`, `examples/ecommerce_s2/specs/pack.py`, `examples/ecommerce_s2/specs/kernels.py`, `examples/ecommerce_s2/{out,reports,logs}/.gitkeep`
- Modify: `examples/README.md` (one row: `ecommerce_s2/` — "S2 slice; superseded by `ecommerce/` and `payments/` at M3/M4. Multi-SKU carts with reservations, payments with refunds and disputes, a capped bonus pool, bounty-hunter campaigns" — partitions "owners `user`, `payment`, `campaign` · shards `inventory`, `pool`")
- Test: `apps/datagen/tests/test_example_ecom_s2.py`

**Interfaces:**
- Consumes: Tasks 1–11 (`ref` shard state and shard `Local` remap, pairing, compiled admission, accumulators, laws, `std.reservations`, `std.catalog(hot_rows=)`); S1 `std.devices`, `std.stock`.
- Produces: project `examples/ecommerce_s2`, pack `ecommerce_s2` (`SCHEMA_VERSION = 1`), processes `shopper` (owner `user`), `inventory_desk` and `restock` (shard `inventory`); accumulator `hot_checkouts` (i64: started checkouts with at least one line in group 0, D53/F-02; manifest `accumulators.hot_checkouts` over exported steps); `kernels` constants used by later tasks: `CART = 4`, `HOLD_SLOTS = 64`, command ids `C_SESSION=1, C_VIEW=2, C_CHECKOUT=3, R_GRANTED=4, R_REJECTED=5` (Tasks 13 and 15 add `C_BILL=6, R_BONUS=7, R_NO_BONUS=8`), shard commands `C_RESERVE=1, C_COMMIT=2, C_RELEASE=3, C_HOLD_EXPIRE=4`; `Config` fields `users, initial_share, referred_share, skus, sku_groups, restock_period, household_share_device, journey: Journey, desk: Desk`.

- [ ] **Step 1: Write the project files**

`examples/ecommerce_s2/datagen.toml`:
```toml
# S2 slice (spec §18 S2): shoppers with multi-SKU carts, payments, a capped bonus pool.
[project]
name = "ecommerce_s2"
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
memory = "32GB"
max_step_rows = 4_000_000
max_step_bytes = "1GB"
max_spawn_depth = 3
max_admissions_per_step = 2_000_000
max_checker_keys = 60_000_000

[writer]
compression = "zstd"
compression_level = 3
row_group_rows = 131_072

[engine]
step = "1d"
step_min = "1h"
step_max = "7d"
adapt = true
slab_bytes = "4MB"
timer_nodes = 90_000_000
payload_slots = 4_000_000
max_messages_per_step = 8_000_000
parallel_min_partitions = 2_048

[profiles.sample]
span = "21d"
warmup = "3d"

[profiles.sample.set]
users = 20_000
skus = 5_000
sku_groups = 64
"engine.timer_nodes" = 3_000_000
"engine.payload_slots" = 400_000
"engine.max_messages_per_step" = 1_000_000
"budget.max_admissions_per_step" = 200_000
"budget.max_checker_keys" = 5_000_000
```

`examples/ecommerce_s2/specs/brief.md`:
```markdown
# Brief: e-commerce and payments, S2 slice

The S1 shopper journey (sessions, Pareto session gaps, devices, a Zipf catalog, restocks) with
the shard-heavy parts of `examples/ecommerce` and `examples/payments`, as handwritten kernels.

- **Carts** hold up to four lines. Checkout first holds the cart total on the shopper's credit
  limit, then sends one reserve request per line to the line's inventory group, waits for every
  answer, and commits all lines or releases the granted ones. About 2% of shoppers abandon a
  fully granted checkout; their holds expire after a 10-minute TTL.
- **One hot inventory group** (group 0) holds a small set of SKUs; about 5% of checkouts have
  at least one line in it (spec §10: "one hot SKU group taking 5% of checkouts").
- **Payments** (task 13 onward) are created by checkouts and by bill payments.
```
(Tasks 13–15 append their paragraphs.)

`examples/ecommerce_s2/README.md`: what is simulated (the brief, one paragraph), the partitions and boundaries table of `pack.py`'s docstring, how to run (`uv run --all-packages datagen run examples/ecommerce_s2 --profile sample`), and the profiles (`sample` now; `full` and `pool` from Task 20).

`examples/ecommerce_s2/specs/pack.py`:
```python
"""E-commerce + payments S2 slice (spec §18 S2).

Partitions
    owner  user        one shopper: profile, credit hold, a cart of up to four lines
    shard  inventory   one inventory group: on_hand / reserved per SKU and a 64-slot hold table

Boundaries (immutable, latency >= delta)
    user -> inventory  reserve (request: granted / rejected with hold id and slot)  delta 150 ms
    user -> inventory  commit, release (one-way messages carrying the hold)         delta 150 ms

Payments, the bonus pool and campaigns are added by tasks 13 to 15 of the S2 plan.
"""

from dataclasses import dataclass, field

from neorisk_simkit.spec import Pack, dist, law, std
from neorisk_simkit.spec.types import amount, boolean, cat, i16, i32, i64, opt, ref, ts

from . import kernels as k

PACK = "ecommerce_s2"
SCHEMA_VERSION = 1

CATEGORIES = (
    "apparel", "shoes", "beauty", "home", "kitchen", "garden", "toys", "baby", "books",
    "music", "video_games", "electronics", "phones", "computers", "office", "pets", "sports",
    "outdoors", "auto", "tools", "grocery", "health", "jewelry", "luggage",
)
CHANNELS = ("web", "app")
ACQUISITION = ("organic", "search_ad", "social_ad", "affiliate")


@dataclass(frozen=True)
class Journey:
    """Shopper behavior; consumed by kernels.shopper."""
    signup_delay: dist.Dist = dist.exp(mean_s=3600)
    session_gap_alpha: float = 1.2
    session_gap_min_h: float = 30.0
    views_mean: float = 4.0
    view_gap: dist.Dist = dist.exp(mean_s=40)
    add_to_cart_p: float = 0.25             # per view; a cart holds up to kernels.CART lines
    hot_skus: int = 50                      # catalog rows [0, hot_skus) form SKU group 0
    hot_pick_p: float = 0.05                # per view: look at a hot SKU
    checkout_p: float = 0.5                 # per session end with a non-empty cart
    checkout_delay: dist.Dist = dist.exp(mean_s=25)
    abandon_p: float = 0.02                 # a fully granted checkout is abandoned (TTL frees)
    substitute_p: float = 0.45


@dataclass(frozen=True)
class Desk:
    """Inventory desk; consumed by kernels.inventory_desk."""
    hold_ttl_s: int = 600


@dataclass(frozen=True)
class Config:
    users: int = 20_000
    initial_share: float = 0.6
    referred_share: float = 0.15
    skus: int = 5_000
    sku_groups: int = 64
    restock_period: str = "7d"
    household_share_device: float = 0.12
    journey: Journey = field(default_factory=Journey)
    desk: Desk = field(default_factory=Desk)


def define(p: Pack, cfg: Config) -> None:
    j = cfg.journey
    # ---------------------------------------------------------------- catalog and devices
    sku = p.table("sku", key="sku_id", doc="Catalog, fixed for the run", cols={
        "category": cat(*CATEGORIES), "price": amount(asset="USD"), "sku_group": i16()},
        source=std.catalog(n=cfg.skus, category=dist.categorical(
            {c: 1 / len(CATEGORIES) for c in CATEGORIES}),
            price=dist.lognormal_minor(median=2_500, sigma=0.9, min=199, max=200_000),
            group=dist.uniform_int(1, cfg.sku_groups - 1), weight=dist.zipf(s=1.07),
            hot_rows=j.hot_skus))
    device = p.table("device", key="device_id", doc="Shopper devices", cols={
        "os": cat("ios", "android", "windows", "macos", "linux"),
        "kind": cat("phone", "tablet", "desktop"), "first_seen": ts()})
    # ---------------------------------------------------------------- shoppers
    user = p.table("user", key="user_id", mutable=True, doc="A shopper", cols={
        "age_band": cat("18-24", "25-34", "35-44", "45-54", "55+"),
        "acquisition": cat(*ACQUISITION), "status": cat("active", "dormant"),
        "referred": boolean(), "credit_limit": amount(asset="USD"),
        "held": amount(asset="USD")})
    p.ids("session", "checkout", "hold")
    p.owner("user", table=user, max_live=cfg.users, retire_when_idle=False)
    p.population(
        user, n=cfg.users, initial=cfg.initial_share,
        arrivals=dist.poisson_daily(weekly=(1.0, 0.95, 0.95, 1.0, 1.1, 1.3, 1.25), trend=0.002),
        attrs={"age_band": dist.categorical({"18-24": .17, "25-34": .31, "35-44": .24,
                                             "45-54": .16, "55+": .12}),
               "acquisition": dist.categorical({"organic": .55, "search_ad": .2,
                                                "social_ad": .15, "affiliate": .1}),
               "referred": dist.categorical({0: 1 - cfg.referred_share,
                                             1: cfg.referred_share}),
               "credit_limit": dist.uniform_int(20_000, 400_000)},
        refs={"device": std.devices(per_user=dist.categorical({1: .6, 2: .3, 3: .1}),
                                    table=device, share=cfg.household_share_device)})
    # ---------------------------------------------------------------- inventory
    inventory = p.shard("inventory", key="sku_group", n=cfg.sku_groups, items=sku,
                        doc="Stock per inventory group; group 0 is the hot group",
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
    # ---------------------------------------------------------------- events
    u = {"user_id": ref("user")}
    p.event("user_signed_up", owner="user", cols={
        **u, "device_id": ref("device"), "acquisition": cat(*ACQUISITION),
        "referred": boolean()})
    p.event("session_started", owner="user", cols={
        **u, "session_id": ref("session"), "device_id": ref("device"), "channel": cat(*CHANNELS)})
    p.event("product_viewed", owner="user", cols={
        **u, "session_id": ref("session"), "sku_id": ref("sku"), "device_id": ref("device"),
        "position": i16(), "channel": cat(*CHANNELS), "category": cat(*CATEGORIES),
        "price": amount(asset="USD")})
    p.event("cart_item_added", owner="user", cols={
        **u, "session_id": ref("session"), "sku_id": ref("sku"), "quantity": i16(),
        "unit_price": amount(asset="USD")})
    p.event("checkout_started", owner="user", doc="Credit held; one reserve per cart line",
            cols={**u, "session_id": ref("session"), "checkout_id": ref("checkout"),
                  "lines": i16(), "subtotal": amount(asset="USD"),
                  "hold_after": amount(asset="USD")})
    p.event("checkout_failed", owner="user", cols={
        **u, "checkout_id": ref("checkout"), "reason": cat("out_of_stock", "credit_limit"),
        "sku_id": opt(ref("sku")), "hold_after": amount(asset="USD")})
    p.event("checkout_abandoned", owner="user", doc="Every line granted, never committed",
            cols={**u, "checkout_id": ref("checkout"), "hold_after": amount(asset="USD")})
    p.event("checkout_succeeded", owner="user", cols={
        **u, "checkout_id": ref("checkout"), "amount": amount(asset="USD"),
        "hold_after": amount(asset="USD")})
    stock = {"sku_group": i16(), "sku_id": ref("sku"), "checkout_id": ref("checkout")}
    p.event("stock_reserved", shard="inventory", cols={
        **stock, "hold_id": ref("hold"), "quantity": i16()})
    p.event("stock_rejected", shard="inventory", cols={
        **stock, "quantity": i16(), "reason": cat("out_of_stock", "busy")})
    p.event("stock_committed", shard="inventory", cols={
        **stock, "hold_id": ref("hold"), "quantity": i16(), "on_hand_after": i32()})
    for name in ("stock_released", "stock_expired", "stock_commit_late"):
        p.event(name, shard="inventory", cols={**stock, "hold_id": ref("hold"),
                                               "quantity": i16()})
    p.event("restocked", shard="inventory", doc="Supplier delivery to an inventory group", cols={
        "sku_group": i16(), "sku_id": ref("sku"), "quantity": i32(min=1), "on_hand_after": i32()})
    # §10 "one hot SKU group taking 5% of checkouts": started checkouts with a line in group 0
    p.accumulator("hot_checkouts", i64())
    # ---------------------------------------------------------------- processes
    p.process("shopper", owner="user", kernel=k.shopper, config=j,
              start=p.on_created("user"), requests={"reserve": reserve},
              messages={"commit": commit, "release": release},
              on_response={("reserve", "granted"): k.R_GRANTED,
                           ("reserve", "rejected"): k.R_REJECTED},
              reads={"sku": sku, "device": device}, refs={"device": "device"},
              commands=k.SHOPPER_COMMANDS)
    p.process("inventory_desk", shard=inventory, kernel=k.inventory_desk, config=cfg.desk,
              on_request={"reserve": k.C_RESERVE},
              on_message={"commit": k.C_COMMIT, "release": k.C_RELEASE},
              reads={"sku": sku}, commands=k.DESK_COMMANDS)
    p.process("restock", shard=inventory, kernel=k.restock, every=cfg.restock_period,
              jitter=dist.normal(mean_h=0, sd_h=18), reads={"sku": sku})
    # ---------------------------------------------------------------- laws (§11)
    p.check("chk.stock_never_negative", law.never_negative("inventory.on_hand"), required=True)
    p.check("chk.reserved_never_negative", law.never_negative("inventory.reserved"),
            required=True)
    p.check("chk.user_hold_never_negative", law.never_negative("user.held"), required=True)
    p.check("chk.holds_resolved", law.resolved(
        "stock_reserved", by=("stock_committed", "stock_released", "stock_expired"),
        key="hold_id", within="15m"), required=True)
```

`examples/ecommerce_s2/specs/kernels.py`:
```python
"""Handwritten kernels for the S2 slice (spec §18 S2).

Every kernel: validate (draws allowed, no writes) -> out.reserve(...) -> commit. Each draw has
its own site number within its process.
"""

from neorisk_simkit import std
from neorisk_simkit.engine import (
    COMMIT,
    PRIO_TIMER,
    RETRY,
    START,
    Local,
    Res,
    kernel,
    reject,
)

CART = 4                                  # cart lines (Local array width)
HOLD_SLOTS = 64                           # holds per inventory shard (std.reservations table)
C_SESSION, C_VIEW, C_CHECKOUT, R_GRANTED, R_REJECTED = 1, 2, 3, 4, 5
SHOPPER_COMMANDS = (START, C_SESSION, C_VIEW, C_CHECKOUT, R_GRANTED, R_REJECTED)
C_RESERVE, C_COMMIT, C_RELEASE, C_HOLD_EXPIRE = 1, 2, 3, 4
DESK_COMMANDS = (C_RESERVE, C_COMMIT, C_RELEASE, C_HOLD_EXPIRE)
REJ_DORMANT, REJ_NO_CART, REJ_STALE = 1, 2, 3
WHY_STOCK, WHY_BUSY = 0, 1                # stock_rejected.reason codes

SHOPPER_LOCAL = Local(session="ref", device="ref", views_left="i16", cart_n="i8",
                      cart_sku="ref[4]", cart_qty="i16[4]", cart_price="i64[4]",
                      checkout="ref", subtotal="i64", pending="i8", granted="u8",
                      rejected_sku="ref", hold="ref[4]", slot="i32[4]", ordered="u8")
DESK_LOCAL = Local(**std.reservations.fields(HOLD_SLOTS))


@kernel(state="user", local=SHOPPER_LOCAL, commands=SHOPPER_COMMANDS,
        max=Res(records={"user_signed_up": 1, "session_started": 1, "product_viewed": 1,
                         "cart_item_added": 1, "checkout_started": 1, "checkout_failed": 1,
                         "checkout_abandoned": 1, "checkout_succeeded": 1},
                creates={"session": 1, "checkout": 1}, timers=2, requests=4))
def shopper(ctx, s, loc, cmd, out):
    cfg = ctx.cfg
    if cmd.kind == START:
        return _signup(ctx, s, out, cfg)
    if cmd.kind == C_SESSION:
        return _session(ctx, s, loc, out, cfg)
    if cmd.kind == C_VIEW:
        return _view(ctx, loc, out, cfg)
    if cmd.kind == C_CHECKOUT:
        return _checkout(ctx, s, loc, out)
    return _answer(ctx, s, loc, cmd, out, cfg)


def _signup(ctx, s, out, cfg):
    delay = ctx.rng.dist_us(site=1, d=cfg.signup_delay)
    if not out.reserve(records={"user_signed_up": 1}, timers=1):
        return RETRY
    out.emit_user_signed_up(ctx.t, user_id=ctx.self_id,
                            device_id=ctx.refs.device.get(ctx.self_id, 0),
                            acquisition=s.acquisition, referred=s.referred)
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
    views = min(ctx.rng.geometric(site=3, mean=cfg.views_mean), 30)
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
    hot = ctx.rng.bernoulli(site=12, p=cfg.hot_pick_p)
    sku = ctx.reads.sku.sample_by_weight(ctx.rng.uniform(site=13))
    if hot:                                                # D53: the hot group's SKUs
        sku = ctx.rng.uniform_int(site=14, lo=0, hi=cfg.hot_skus - 1)
    add = ctx.rng.bernoulli(site=15, p=cfg.add_to_cart_p)
    qty = ctx.rng.geometric(site=16, mean=1.25)
    pos = ctx.rng.geometric(site=17, mean=5.0)
    nxt = ctx.rng.dist_us(site=18, d=cfg.view_gap)
    if not out.reserve(records={"product_viewed": 1, "cart_item_added": 1}, timers=1):
        return RETRY
    price = ctx.reads.sku.price[sku]
    out.emit_product_viewed(ctx.t, user_id=ctx.self_id, session_id=loc.session, sku_id=sku,
                            device_id=loc.device, position=pos, channel=_channel(ctx, loc.device),
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


def _checkout(ctx, s, loc, out):
    if loc.cart_n == 0 or loc.checkout != std.NULL:
        return reject(REJ_NO_CART)
    total = 0
    for i in range(loc.cart_n):
        total = std.checked_add(total, std.checked_mul(loc.cart_price[i], loc.cart_qty[i]))
    if not out.reserve(records={"checkout_started": 1, "checkout_failed": 1},
                       creates={"checkout": 1}, requests=CART):
        return RETRY
    loc.checkout = out.new_id("checkout")
    if std.checked_add(s.held, total) > s.credit_limit:    # the owner's side of the hold
        out.emit_checkout_failed(ctx.t, user_id=ctx.self_id, checkout_id=loc.checkout,
                                 reason="credit_limit", hold_after=s.held)
        loc.checkout = std.NULL
        loc.cart_n = 0
        return COMMIT
    s.held = std.checked_add(s.held, total)
    loc.subtotal = total
    loc.pending = loc.cart_n
    loc.granted = 0
    loc.rejected_sku = std.NULL
    out.emit_checkout_started(ctx.t, user_id=ctx.self_id, session_id=loc.session,
                              checkout_id=loc.checkout, lines=loc.cart_n, subtotal=total,
                              hold_after=s.held)
    hot = 0
    for i in range(loc.cart_n):                            # one immutable request per line
        grp = ctx.reads.sku.sku_group[loc.cart_sku[i]]
        if grp == 0:
            hot = 1
        out.request_reserve(ctx.t, shard=grp, tag=loc.checkout, sku_id=loc.cart_sku[i],
                            quantity=loc.cart_qty[i], line=i)
    out.add_hot_checkouts(hot)                             # D53: a checkout reaching group 0
    return COMMIT                                          # suspends: join of cart_n answers


def _answer(ctx, s, loc, cmd, out, cfg):
    if cmd.tag != loc.checkout or loc.pending <= 0:
        return reject(REJ_STALE)
    abandon = ctx.rng.bernoulli(site=20, p=cfg.abandon_p)
    substitute = ctx.rng.bernoulli(site=21, p=cfg.substitute_p)
    more = ctx.rng.geometric(site=22, mean=3.0)
    nxt = ctx.rng.dist_us(site=23, d=cfg.view_gap)
    if not out.reserve(records={"checkout_failed": 1, "checkout_abandoned": 1,
                                "checkout_succeeded": 1}, timers=1, requests=CART):
        return RETRY
    line = cmd.line
    if cmd.kind == R_GRANTED:
        loc.granted |= 1 << line
        loc.hold[line] = cmd.hold_id
        loc.slot[line] = cmd.slot
    else:
        loc.rejected_sku = loc.cart_sku[line]
    loc.pending -= 1
    if loc.pending > 0:
        return COMMIT                                      # join: wait for the other lines
    s.held = std.checked_sub(s.held, loc.subtotal)         # the owner commits or releases
    if loc.granted == (1 << loc.cart_n) - 1:
        if abandon:                                        # holds left to the shards' TTL
            out.emit_checkout_abandoned(ctx.t, user_id=ctx.self_id, checkout_id=loc.checkout,
                                        hold_after=s.held)
        else:
            for i in range(loc.cart_n):
                out.send_commit(ctx.t, to=ctx.reads.sku.sku_group[loc.cart_sku[i]],
                                tag=loc.checkout, sku_id=loc.cart_sku[i],
                                quantity=loc.cart_qty[i], hold_id=loc.hold[i], slot=loc.slot[i])
            out.emit_checkout_succeeded(ctx.t, user_id=ctx.self_id, checkout_id=loc.checkout,
                                        amount=loc.subtotal, hold_after=s.held)
    else:
        for i in range(loc.cart_n):
            if loc.granted & (1 << i):
                out.send_release(ctx.t, to=ctx.reads.sku.sku_group[loc.cart_sku[i]],
                                 tag=loc.checkout, sku_id=loc.cart_sku[i],
                                 quantity=loc.cart_qty[i], hold_id=loc.hold[i],
                                 slot=loc.slot[i])
        out.emit_checkout_failed(ctx.t, user_id=ctx.self_id, checkout_id=loc.checkout,
                                 reason="out_of_stock", sku_id=loc.rejected_sku,
                                 hold_after=s.held)
        if substitute:
            loc.views_left = more
            out.timer(ctx.t + nxt, C_VIEW, prio=PRIO_TIMER)
    loc.checkout = std.NULL
    loc.cart_n = 0
    return COMMIT


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


def _reserve(ctx, s, loc, cmd, out):
    i = ctx.reads.sku.local_index[cmd.sku_id]
    free = -1
    for j in range(HOLD_SLOTS):
        if loc.res_hold[j] == std.NULL:
            free = j
            break
    if not out.reserve(records={"stock_reserved": 1, "stock_rejected": 1}, creates={"hold": 1},
                       timers=1, requests=1):
        return RETRY
    if s.on_hand[i] - s.reserved[i] < cmd.quantity or free < 0:
        why = WHY_STOCK if s.on_hand[i] - s.reserved[i] < cmd.quantity else WHY_BUSY
        out.emit_stock_rejected(ctx.t, sku_group=ctx.self_id, sku_id=cmd.sku_id,
                                checkout_id=cmd.tag, quantity=cmd.quantity, reason=why)
        out.respond(cmd, "rejected", hold_id=std.NULL, slot=-1, line=cmd.line)
        return COMMIT
    hold = out.new_id("hold")
    loc.res_hold[free] = hold
    loc.res_item[free] = i
    loc.res_qty[free] = cmd.quantity
    loc.res_ckt[free] = cmd.tag
    s.reserved[i] = std.checked_add(s.reserved[i], cmd.quantity)
    out.emit_stock_reserved(ctx.t, sku_group=ctx.self_id, sku_id=cmd.sku_id, checkout_id=cmd.tag,
                            hold_id=hold, quantity=cmd.quantity)
    out.timer(ctx.t + ctx.cfg.hold_ttl_s * 1_000_000, C_HOLD_EXPIRE, prio=PRIO_TIMER, tag=hold)
    out.respond(cmd, "granted", hold_id=hold, slot=free, line=cmd.line)
    return COMMIT


def _settle_hold(ctx, s, loc, cmd, out):
    j = cmd.slot
    live = j >= 0 and j < HOLD_SLOTS and loc.res_hold[j] == cmd.hold_id
    if cmd.kind == C_RELEASE and not live:
        return reject(REJ_STALE)                           # the hold expired already
    if not out.reserve(records={"stock_committed": 1, "stock_released": 1,
                                "stock_commit_late": 1}):
        return RETRY
    if not live:                                           # D49: commit after the TTL
        out.emit_stock_commit_late(ctx.t, sku_group=ctx.self_id, sku_id=cmd.sku_id,
                                   checkout_id=cmd.tag, hold_id=cmd.hold_id,
                                   quantity=cmd.quantity)
        return COMMIT
    i = loc.res_item[j]
    q = loc.res_qty[j]
    s.reserved[i] = std.checked_sub(s.reserved[i], q)
    if cmd.kind == C_COMMIT:
        s.on_hand[i] = std.checked_sub(s.on_hand[i], q)
        out.emit_stock_committed(ctx.t, sku_group=ctx.self_id, sku_id=cmd.sku_id,
                                 checkout_id=cmd.tag, hold_id=cmd.hold_id, quantity=q,
                                 on_hand_after=s.on_hand[i])
    else:
        out.emit_stock_released(ctx.t, sku_group=ctx.self_id, sku_id=cmd.sku_id,
                                checkout_id=cmd.tag, hold_id=cmd.hold_id, quantity=q)
    loc.res_hold[j] = std.NULL
    return COMMIT


def _expire(ctx, s, loc, cmd, out):
    j = -1
    for k in range(HOLD_SLOTS):
        if loc.res_hold[k] == cmd.tag:
            j = k
            break
    if j < 0:
        return reject(REJ_STALE)                           # committed or released in time
    if not out.reserve(records={"stock_expired": 1}):
        return RETRY
    i = loc.res_item[j]
    q = loc.res_qty[j]
    s.reserved[i] = std.checked_sub(s.reserved[i], q)
    out.emit_stock_expired(ctx.t, sku_group=ctx.self_id, sku_id=s.sku[i],
                           checkout_id=loc.res_ckt[j], hold_id=cmd.tag, quantity=q)
    loc.res_hold[j] = std.NULL
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
            qty = 1 + ctx.rng.uniform_int(site=1, lo=0, hi=gap - 1)
            s.on_hand[i] = std.checked_add(s.on_hand[i], qty)
            out.emit_restocked(ctx.t, sku_group=ctx.self_id, sku_id=s.sku[i], quantity=qty,
                               on_hand_after=s.on_hand[i])
    if stop < s.n_sku:
        out.continue_at(ctx.t, cursor=stop)
    return COMMIT
```

- [ ] **Step 2: Write the failing tests**

`apps/datagen/tests/test_example_ecom_s2.py`:
```python
import json
from datetime import timedelta
from pathlib import Path

import polars as pl
import pytest

from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events
from neorisk_simkit.spec.project import load_project, resolve_run
from neorisk_simkit.spec.validate import validate

EX = Path(__file__).resolve().parents[3] / "examples" / "ecommerce_s2"
POOLS = ["engine.timer_nodes=600_000", "engine.payload_slots=100_000",
         "engine.max_messages_per_step=300_000", "budget.max_admissions_per_step=50_000",
         "budget.max_checker_keys=2_000_000"]
SMALL = ["users=3000", "skus=1200", "sku_groups=8", "journey.hot_skus=40",
         "journey.abandon_p=0.1", "run.span=7d", "run.warmup=1d", *POOLS]


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    return run_to_dataset(EX, "sample", SMALL, out_dir=tmp_path_factory.mktemp("s2") / "run",
                          threads=4)


@pytest.fixture(scope="module")
def ev(run):
    return read_events(run.out_dir)


def _fates(ev):
    return pl.concat([ev[n].select("hold_id", pl.lit(n).alias("fate"))
                      for n in ("stock_committed", "stock_released", "stock_expired")])


def test_project_validates():
    rep = validate(resolve_run(load_project(EX), "sample", []))
    assert rep.ok, rep.errors


def test_carts_have_several_lines(ev):
    lines = ev["checkout_started"]["lines"]
    assert lines.max() >= 3 and lines.mean() > 1.2


def test_every_line_is_decided_at_request_time(ev):
    started = ev["checkout_started"].select("checkout_id", "lines",
                                            pl.col("event_time").alias("t"))
    decided = pl.concat([ev["stock_reserved"].select("checkout_id", "event_time"),
                         ev["stock_rejected"].select("checkout_id", "event_time")])
    per = decided.group_by("checkout_id").agg(pl.len().alias("n"),
                                              pl.col("event_time").min().alias("t0"),
                                              pl.col("event_time").max().alias("t1"))
    j = started.join(per, on="checkout_id")
    assert j.height == started.height > 100
    assert (j["n"] == j["lines"].cast(pl.UInt32)).all()
    assert (j["t0"] == j["t"]).all() and (j["t1"] == j["t"]).all()


def test_join_commits_all_or_releases_all(ev):
    holds = ev["stock_reserved"].select("checkout_id", "hold_id").join(
        _fates(ev), on="hold_id", how="inner")
    outcome = pl.concat([
        ev["checkout_succeeded"].select("checkout_id", pl.lit("ok").alias("o")),
        ev["checkout_failed"].select("checkout_id", pl.lit("failed").alias("o")),
        ev["checkout_abandoned"].select("checkout_id", pl.lit("abandoned").alias("o"))])
    j = holds.join(outcome, on="checkout_id")
    want = {"ok": "stock_committed", "failed": "stock_released", "abandoned": "stock_expired"}
    for o, fate in want.items():
        sub = j.filter(pl.col("o") == o)
        assert sub.height > 0, o
        assert (sub["fate"] == fate).all(), (o, sub["fate"].value_counts())


def test_holds_expire_exactly_one_ttl_after_the_reserve(ev):
    r = ev["stock_reserved"].select("hold_id", pl.col("event_time").alias("t0"))
    x = ev["stock_expired"].select("hold_id", "event_time").join(r, on="hold_id")
    assert x.height > 0
    assert ((x["event_time"] - x["t0"]) == timedelta(seconds=600)).all()


def test_two_lines_of_one_cart_can_share_a_shard(ev):
    """Review Focus #2: two lines of one cart reserved in the same inventory group."""
    per = ev["stock_reserved"].group_by("checkout_id", "sku_group").len()
    assert (per["len"] >= 2).any()


def test_the_hot_group_takes_a_share_of_checkouts(run, ev):
    """§10 "one hot SKU group taking 5% of checkouts" (D53, F-02): the shopper's accumulator
    equals the checkouts with a reserve to group 0; the reserve share is information only."""
    m = json.loads((run.out_dir / "manifest.json").read_text())
    started = ev["checkout_started"].select("checkout_id")
    hot_ids = pl.concat([ev["stock_reserved"].select("checkout_id", "sku_group"),
                         ev["stock_rejected"].select("checkout_id", "sku_group")]
                        ).filter(pl.col("sku_group") == 0)["checkout_id"].unique()
    n_hot = started.join(hot_ids.to_frame(), on="checkout_id").height
    assert m["accumulators"]["hot_checkouts"] == n_hot > 0
    assert 0.03 <= n_hot / started.height <= 0.25


def test_laws_hold_and_requests_pair(run):
    m = json.loads((run.out_dir / "manifest.json").read_text())
    for k in ("chk.stock_never_negative", "chk.reserved_never_negative",
              "chk.user_hold_never_negative", "chk.holds_resolved"):
        assert m["laws"][k]["violations"] == 0 and m["laws"][k]["checked"] > 0, k
    pr = m["pairing"]["reserve"]
    assert pr["requests"] == pr["responses"] > 0


def test_a_full_hold_table_rejects_as_busy(tmp_path):
    over = ["users=3000", "skus=600", "sku_groups=2", "journey.session_gap_min_h=0.5",
            "journey.checkout_p=1.0", "journey.abandon_p=1.0", "run.span=1d",
            "run.warmup=0s", *POOLS]
    r = run_to_dataset(EX, "sample", over, out_dir=tmp_path / "busy", threads=2)
    rej = read_events(r.out_dir)["stock_rejected"]
    assert (rej["reason"] == "busy").sum() > 0


def test_a_commit_after_the_ttl_is_late_and_moves_no_stock(tmp_path):
    over = ["users=800", "skus=300", "sku_groups=4", "desk.hold_ttl_s=0", "run.span=3d",
            "run.warmup=0s", *POOLS]
    r = run_to_dataset(EX, "sample", over, out_dir=tmp_path / "late", threads=2)
    ev = read_events(r.out_dir)
    assert ev["stock_committed"].height == 0 and ev["stock_released"].height == 0
    late = ev["stock_commit_late"]
    assert late.height > 0
    assert set(late["checkout_id"]) <= set(ev["checkout_succeeded"]["checkout_id"])
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run --all-packages pytest apps/datagen/tests/test_example_ecom_s2.py -v`
Expected: Step 1 already wrote the project, so the tests run; whatever fails names the first behavior the kernels or pack get wrong (a lowering error, a law violation or an assertion), and everything may already pass. The first run compiles the S2 module (several minutes cold). (If Steps 1–2 are done in the other order, the first error is `ProjectError: no datagen.toml in .../examples/ecommerce_s2`.)

- [ ] **Step 4: Make the tests pass**

Fix kernels or pack (never the test bounds) until every test passes. If a lowering error names a construct, rewrite the kernel within the S1 lowering contract (no module imports, views passed by name, one site per draw). If `chk.holds_resolved` fails, the TTL or the commit path is wrong: the law is the specification.

- [ ] **Step 5: Full suite and lint**

Run: `uv run --all-packages pytest -q && uv run ruff check $(ls -d libs apps examples/ecommerce_s1 examples/ecommerce_s2 benchmarks 2>/dev/null)`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add examples/README.md examples/ecommerce_s2 apps/datagen/tests/test_example_ecom_s2.py
git commit -m "examples: ecommerce_s2 slice with multi-SKU carts and reservations with TTL

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 13: Payments — created at checkout and by bills; authorization, capture racing expiry, postings, fees

**Files:**
- Modify: `examples/ecommerce_s2/specs/pack.py`, `examples/ecommerce_s2/specs/kernels.py`, `examples/ecommerce_s2/specs/brief.md` (payments paragraph), `examples/ecommerce_s2/README.md` (partitions table)
- Test: `apps/datagen/tests/test_example_ecom_s2_payments.py`

**Interfaces:**
- Consumes: Task 12 project; Tasks 4–7 (creation payloads, compiled admission, postings, accumulators); Task 9 `balanced`.
- Produces:
  - Owner `payment` (created; table `payment` with columns `user_id ref(user)`, `checkout_id opt(ref(checkout))`, `amount amount(USD)`, `method cat(card, wallet, bnpl)`, `origin cat(checkout, bill)` — 5 columns, D43), `max_live = max(1_000, int(users × payments_live_ratio))`.
  - Process `payment_life` with `PayLife` config; commands `START, C_CAPTURE=1, C_AUTH_EXPIRE=2, C_WINDOW=3` (Task 14 adds `C_REFUND=4, C_REFUND_DUP=5, C_SETTLE=6, C_DISPUTE=7, C_RESOLVE=8`); `PAY_LOCAL` with every lifecycle field Tasks 13–14 use.
  - Events `payment_authorized`, `payment_declined`, `payment_captured`, `payment_expired`, `bill_payment_started`; `checkout_succeeded` gains `payment_id`. Postings `ledger(payment_id, account, side, amount)`; accumulator `platform_fees`.
  - Laws `chk.postings_balanced` (`balanced("ledger")`, required) and `chk.one_capture` (`at_most_once("payment_captured", key="payment_id")`, required).
  - Shopper commands gain `C_BILL = 6`.

- [ ] **Step 1: Extend the pack**

In `pack.py` add:
```python
METHODS = ("card", "wallet", "bnpl")
ACCOUNTS = ("customer_funds", "customer_held", "merchant", "platform_fees", "refunds_payable",
            "dispute_reserve")


@dataclass(frozen=True)
class PayLife:
    """Payment lifecycle; consumed by kernels.payment_life."""
    decline_p: float = 0.03
    capture_p: float = 0.93
    capture_delay: dist.Dist = dist.lognormal(median_s=3600, sigma=1.0)
    auth_expiry_s: int = 7 * 86_400          # capture races this expiry (§09)
    fee_bps: int = 290
    dispute_window_days: int = 90            # the 90-day dispute timer (§10 S2)
```
`Journey` gains `bill_gap: dist.Dist = dist.exp(mean_days=20)`, `bill_median: float = 6_000.0`, `bill_sigma: float = 0.8`. `Config` gains `payments_live_ratio: float = 1.5` and `pay: PayLife = field(default_factory=PayLife)`.

In `define`, right after the user events (see the placement note below):
```python
    # ---------------------------------------------------------------- payments (§09)
    payment = p.table("payment", key="payment_id", mutable=True, doc="A card payment", cols={
        "user_id": ref("user"), "checkout_id": opt(ref("checkout")),
        "amount": amount(asset="USD"), "method": cat(*METHODS),
        "origin": cat("checkout", "bill")})
    p.owner("payment", table=payment, max_live=max(1_000, int(cfg.users * cfg.payments_live_ratio)))
    p.accumulator("platform_fees", amount(asset="USD"))
    pay_id = {"payment_id": ref("payment")}
    p.event("payment_authorized", owner="payment", cols={
        **pay_id, "user_id": ref("user"), "amount": amount(asset="USD"),
        "method": cat(*METHODS), "origin": cat("checkout", "bill")})
    p.event("payment_declined", owner="payment", cols={
        **pay_id, "user_id": ref("user"), "amount": amount(asset="USD")})
    p.event("payment_captured", owner="payment", cols={
        **pay_id, "amount": amount(asset="USD"), "fee": amount(asset="USD")})
    p.event("payment_expired", owner="payment", cols={**pay_id, "amount": amount(asset="USD")})
    p.postings("ledger", owner="payment", doc="Double-entry postings of payment events", cols={
        **pay_id, "account": cat(*ACCOUNTS), "side": cat("debit", "credit"),
        "amount": amount(asset="USD")})
    p.event("bill_payment_started", owner="user", cols={
        **u, "payment_id": ref("payment"), "amount": amount(asset="USD")})
    p.process("payment_life", owner="payment", kernel=k.payment_life, config=cfg.pay,
              start=p.on_created("payment"), commands=k.PAYMENT_COMMANDS)
    p.check("chk.postings_balanced", law.balanced("ledger"), required=True)
    p.check("chk.one_capture", law.at_most_once("payment_captured", key="payment_id"),
            required=True)
```
`checkout_succeeded` gains `"payment_id": ref("payment")`. Place the whole payments block above right after the user events (after `checkout_succeeded`, where `u` is defined) and before the inventory events; refs resolve at plan build, so `checkout_succeeded` may name `payment` before `p.table("payment")` runs, and `p.owner("payment")` only has to follow `p.table("payment")` (F-16).

- [ ] **Step 2: Extend the kernels**

In `kernels.py`:
- constants: `C_BILL = 6`; `SHOPPER_COMMANDS = (START, C_SESSION, C_VIEW, C_CHECKOUT, R_GRANTED, R_REJECTED, C_BILL)`; payment commands and states:
```python
C_CAPTURE, C_AUTH_EXPIRE, C_WINDOW = 1, 2, 3
PAYMENT_COMMANDS = (START, C_CAPTURE, C_AUTH_EXPIRE, C_WINDOW)
P_AUTHORIZED, P_CAPTURED, P_EXPIRED, P_DECLINED = 1, 2, 3, 4
D_NONE, D_OPEN, D_WON, D_LOST = 0, 1, 2, 3
R_REQUESTED, R_SETTLED, R_FAILED, R_REJECTED_IDEM = 0, 1, 2, 3
(A_CUSTOMER_FUNDS, A_CUSTOMER_HELD, A_MERCHANT, A_PLATFORM_FEES, A_REFUNDS_PAYABLE,
 A_DISPUTE_RESERVE) = range(6)
DAY = 86_400_000_000
PAY_LOCAL = Local(status="i8", captured="i64", refunded="i64", refund_hold="i64",
                  refunds="i8", dispute="i8", disputed="i64", window_end="i64",
                  idem_key="ref[4]", idem_result="i8[4]", idem_amount="i64[4]", idem_n="i8")
```
- `shopper` decorator: `records` gains `"bill_payment_started": 1`, `creates` gains `"payment": 1`, `timers=2`, `requests=CART` (unchanged: the payment's creation message is reserved automatically, Task 4); dispatch adds `if cmd.kind == C_BILL: return _bill(ctx, out, cfg)` before the `_answer` fallthrough.
- `_signup`: draw `bill = ctx.rng.dist_us(site=6, d=cfg.bill_gap)` before the reserve, reserve `timers=2`, and add `out.timer(ctx.t + bill, C_BILL, prio=PRIO_TIMER)`.
- `_answer`: draw `method = ctx.rng.categorical(site=24, p=(0.7, 0.22, 0.08))` with the other draws; reserve `creates={"payment": 1}` (its `requests=CART` stays: the creation message is counted automatically); in the commit-all branch, before `emit_checkout_succeeded`:
```python
            pay = out.create_payment(user_id=ctx.self_id, checkout_id=loc.checkout,
                                     amount=loc.subtotal, method=method, origin="checkout")
```
  and pass `payment_id=pay` to `emit_checkout_succeeded`.
- new helper:
```python
def _bill(ctx, out, cfg):
    amt = max(100, ctx.rng.lognormal_minor(site=40, median=cfg.bill_median,
                                           sigma=cfg.bill_sigma))
    method = ctx.rng.categorical(site=41, p=(0.8, 0.2, 0.0))
    nxt = ctx.rng.dist_us(site=42, d=cfg.bill_gap)
    if not out.reserve(records={"bill_payment_started": 1}, creates={"payment": 1}, timers=1):
        return RETRY                                       # + its creation message (automatic)
    pay = out.create_payment(user_id=ctx.self_id, checkout_id=std.NULL, amount=amt,
                             method=method, origin="bill")
    out.emit_bill_payment_started(ctx.t, user_id=ctx.self_id, payment_id=pay, amount=amt)
    out.timer(ctx.t + nxt, C_BILL, prio=PRIO_TIMER)
    return COMMIT
```
- the payment kernel (import `PRIO_EXPIRY` from `neorisk_simkit.engine`):
```python
@kernel(state="payment", local=PAY_LOCAL, commands=PAYMENT_COMMANDS,
        max=Res(records={"payment_authorized": 1, "payment_declined": 1,
                         "payment_captured": 1, "payment_expired": 1, "ledger": 3},
                timers=2))
def payment_life(ctx, s, loc, cmd, out):
    cfg = ctx.cfg
    if cmd.kind == START:
        return _authorize(ctx, s, loc, out, cfg)
    if cmd.kind == C_CAPTURE:
        return _capture(ctx, s, loc, out, cfg)
    if cmd.kind == C_AUTH_EXPIRE:
        return _auth_expire(ctx, s, loc, out)
    return COMMIT                         # C_WINDOW: the dispute window closed; idle -> retire


def _post(ctx, out, debit, credit, amt):
    out.emit_ledger(ctx.t, payment_id=ctx.self_id, account=debit, side="debit", amount=amt)
    out.emit_ledger(ctx.t, payment_id=ctx.self_id, account=credit, side="credit", amount=amt)


def _authorize(ctx, s, loc, out, cfg):
    declined = ctx.rng.bernoulli(site=1, p=cfg.decline_p)
    capture = ctx.rng.bernoulli(site=2, p=cfg.capture_p)
    delay = ctx.rng.dist_us(site=3, d=cfg.capture_delay)
    if not out.reserve(records={"payment_authorized": 1, "payment_declined": 1, "ledger": 2},
                       timers=2):
        return RETRY
    if declined:
        loc.status = P_DECLINED
        out.emit_payment_declined(ctx.t, payment_id=ctx.self_id, user_id=s.user_id,
                                  amount=s.amount)
        return COMMIT                                      # nothing queued: retires
    loc.status = P_AUTHORIZED
    out.emit_payment_authorized(ctx.t, payment_id=ctx.self_id, user_id=s.user_id,
                                amount=s.amount, method=s.method, origin=s.origin)
    _post(ctx, out, A_CUSTOMER_FUNDS, A_CUSTOMER_HELD, s.amount)
    out.timer(ctx.t + cfg.auth_expiry_s * 1_000_000, C_AUTH_EXPIRE, prio=PRIO_EXPIRY)
    if capture:
        out.timer(ctx.t + delay, C_CAPTURE, prio=PRIO_TIMER)
    return COMMIT


def _capture(ctx, s, loc, out, cfg):
    if loc.status != P_AUTHORIZED:
        return reject(REJ_STALE)                           # expiry won the race
    if not out.reserve(records={"payment_captured": 1, "ledger": 3}, timers=1):
        return RETRY
    fee = std.checked_mul(s.amount, cfg.fee_bps) // 10_000
    loc.status = P_CAPTURED
    loc.captured = s.amount
    loc.window_end = ctx.t + cfg.dispute_window_days * DAY
    out.emit_payment_captured(ctx.t, payment_id=ctx.self_id, amount=s.amount, fee=fee)
    out.emit_ledger(ctx.t, payment_id=ctx.self_id, account=A_CUSTOMER_HELD, side="debit",
                    amount=s.amount)
    out.emit_ledger(ctx.t, payment_id=ctx.self_id, account=A_MERCHANT, side="credit",
                    amount=s.amount - fee)
    out.emit_ledger(ctx.t, payment_id=ctx.self_id, account=A_PLATFORM_FEES, side="credit",
                    amount=fee)
    out.add_platform_fees(fee)
    out.timer(loc.window_end, C_WINDOW, prio=PRIO_TIMER)
    return COMMIT


def _auth_expire(ctx, s, loc, out):
    if loc.status != P_AUTHORIZED:
        return reject(REJ_STALE)                           # captured first
    if not out.reserve(records={"payment_expired": 1, "ledger": 2}):
        return RETRY
    loc.status = P_EXPIRED
    out.emit_payment_expired(ctx.t, payment_id=ctx.self_id, amount=s.amount)
    _post(ctx, out, A_CUSTOMER_HELD, A_CUSTOMER_FUNDS, s.amount)
    return COMMIT
```
At an equal instant expiry (`PRIO_EXPIRY = 2`) runs before capture (`PRIO_TIMER = 5`): an authorization captured exactly at its expiry has expired.

- [ ] **Step 3: Write the failing tests**

`apps/datagen/tests/test_example_ecom_s2_payments.py`:
```python
import json
from datetime import timedelta
from pathlib import Path

import polars as pl
import pytest

from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events, read_postings
from neorisk_simkit.spec.project import load_project, resolve_run

EX = Path(__file__).resolve().parents[3] / "examples" / "ecommerce_s2"
POOLS = ["engine.timer_nodes=600_000", "engine.payload_slots=100_000",
         "engine.max_messages_per_step=300_000", "budget.max_admissions_per_step=50_000",
         "budget.max_checker_keys=2_000_000"]
SMALL = ["users=3000", "skus=1200", "sku_groups=8", "run.span=7d", "run.warmup=1d",
         "journey.bill_gap.params=[172_800_000_000.0, 0.0, 0.0]",        # bills every ~2 days
         "pay.auth_expiry_s=7200",                                       # expiry races capture
         *POOLS]


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    return run_to_dataset(EX, "sample", SMALL, out_dir=tmp_path_factory.mktemp("pay") / "run",
                          threads=4)


@pytest.fixture(scope="module")
def ev(run):
    return read_events(run.out_dir)


def test_every_payment_starts_where_it_was_created(ev):
    made = pl.concat([ev["checkout_succeeded"].select("payment_id", "event_time"),
                      ev["bill_payment_started"].select("payment_id", "event_time")])
    first = pl.concat([ev["payment_authorized"].select("payment_id", "event_time"),
                       ev["payment_declined"].select("payment_id", "event_time")])
    assert made.height > 1000 and first["payment_id"].n_unique() == first.height
    j = made.join(first, on="payment_id", suffix="_p")
    assert j.height == made.height and (j["event_time"] == j["event_time_p"]).all()


def test_capture_races_expiry(ev):
    auth = ev["payment_authorized"].select("payment_id", pl.col("event_time").alias("t0"))
    cap = ev["payment_captured"].select("payment_id", "event_time").join(auth, on="payment_id")
    exp = ev["payment_expired"].select("payment_id", "event_time").join(auth, on="payment_id")
    assert cap.height > 0 and exp.height > 0
    assert set(cap["payment_id"]).isdisjoint(set(exp["payment_id"]))
    assert ((exp["event_time"] - exp["t0"]) == timedelta(hours=2)).all()
    assert ((cap["event_time"] - cap["t0"]) < timedelta(hours=2)).all()


def test_postings_balance_per_commit_and_fees_accumulate(run, ev):
    led = read_postings(run.out_dir)["ledger"]
    signed = led.with_columns(pl.when(pl.col("side") == "debit").then(pl.col("amount"))
                              .otherwise(-pl.col("amount")).alias("x"))
    assert (signed.group_by("partition_id", "lamport").agg(pl.col("x").sum())["x"] == 0).all()
    m = json.loads((run.out_dir / "manifest.json").read_text())
    assert m["accumulators"]["platform_fees"] == ev["payment_captured"]["fee"].sum()
    pay_events = sum(ev[n].height for n in ("payment_authorized", "payment_declined",
                                            "payment_captured", "payment_expired"))
    assert 2.0 <= m["posting_counts"]["ledger"] / pay_events <= 2.8
    for k in ("chk.postings_balanced", "chk.one_capture"):
        assert m["laws"][k]["violations"] == 0 and m["laws"][k]["checked"] > 0


def test_payments_are_their_own_partitions(ev):
    plan = resolve_run(load_project(EX), "sample", []).plan
    code = plan.partition("payment").ptype_code
    pids = ev["payment_authorized"]["partition_id"]
    assert ((pids >> 56) == code).all() and pids.n_unique() == pids.len()


def test_payments_retire_after_their_window_and_slots_are_reused(tmp_path):
    # F-11: nothing cancels the auth-expiry timer, so a captured payment lives until it fires;
    # a 2 h expiry and a 1-day window keep a payment alive about a day, and bills every ~2 days
    # keep about 600 payments live at once while more than 5,000 are made over 10 days
    over = ["users=1000", "skus=300", "sku_groups=4", "run.span=10d", "run.warmup=0s",
            "payments_live_ratio=0.001", "pay.dispute_window_days=1", "pay.auth_expiry_s=7200",
            "journey.bill_gap.params=[172_800_000_000.0, 0.0, 0.0]", *POOLS]
    r = run_to_dataset(EX, "sample", over, out_dir=tmp_path / "reuse", threads=2)
    ev = read_events(r.out_dir)
    made = ev["checkout_succeeded"].height + ev["bill_payment_started"].height
    assert made > 1_000                     # more payments than the 1,000 live slots (D43)
```

- [ ] **Step 4: Run tests to verify they fail, then make them pass**

Run: `uv run --all-packages pytest apps/datagen/tests/test_example_ecom_s2_payments.py -v`
Expected first: FAIL (`KeyError: 'payment_authorized'` or `unknown setting 'pay.auth_expiry_s'` before Steps 1–2 are in). After Steps 1–2: PASS (5 tests), and `apps/datagen/tests/test_example_ecom_s2.py` still passes (its `checkout_succeeded` assertions do not read `payment_id`).

- [ ] **Step 5: Full suite, lint, commit**

Run: `uv run --all-packages pytest -q && uv run ruff check $(ls -d libs apps examples/ecommerce_s1 examples/ecommerce_s2 benchmarks 2>/dev/null)`
```bash
git add examples/ecommerce_s2 apps/datagen/tests/test_example_ecom_s2_payments.py
git commit -m "examples(s2): payments created by checkouts and bills, with postings and fees

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 14: Refunds with holds and idempotency keys; disputes

**Files:**
- Modify: `examples/ecommerce_s2/specs/pack.py`, `examples/ecommerce_s2/specs/kernels.py`, `examples/ecommerce_s2/specs/brief.md`
- Test: `apps/datagen/tests/test_example_ecom_s2_refunds.py`

**Interfaces:**
- Consumes: Task 13 `payment_life`, `PAY_LOCAL`, `_post`, account and state constants.
- Produces:
  - `PayLife` fields `refund_p = 0.04`, `refund_gap = dist.exp(mean_days=9)`, `max_refunds = 3`, `refund_median = 2_500.0`, `refund_sigma = 0.9`, `refund_settle = dist.lognormal(median_s=86_400, sigma=0.5)`, `refund_fail_p = 0.02`, `duplicate_p = 0.05`, `duplicate_gap = dist.exp(mean_s=30)`, `dispute_p = 0.006`, `dispute_delay = dist.gamma(mean_days=21)`, `dispute_resolve = dist.gamma(mean_days=30)`, `dispute_win_p = 0.55`.
  - `p.ids("refund")`; events `refund_requested(payment_id, refund_id, amount)`, `refund_settled(payment_id, refund_id, amount, refunded_after)`, `refund_failed(payment_id, refund_id, amount)`, `refund_rejected(payment_id, refund_id, reason cat(nothing_left, dispute_open))`, `refund_replayed(payment_id, refund_id, result cat(requested, rejected))`, `dispute_opened(payment_id, amount)`, `dispute_won(payment_id, amount)`, `dispute_lost(payment_id, amount)`.
  - Commands `C_REFUND=4, C_REFUND_DUP=5, C_SETTLE=6, C_DISPUTE=7, C_RESOLVE=8`.
  - Laws `chk.refunds_le_captured` (`sum_le("refund_settled.amount", "payment_captured.amount", by="payment_id")`, required) and `chk.refund_settles_once` (`at_most_once("refund_settled", key="refund_id")`, required).
  - Semantics (§09): a refund holds `min(left, wanted)` against `left = captured − refunded − refund_hold`, then settles (commit) or fails (release) after the processor's delay; a refund while a dispute is open is rejected `dispute_open`; nothing left (or a lost dispute) → `nothing_left`; a duplicate request with the same refund ID returns the first result (`requested` or `rejected`) without changing state. A dispute opens only on a captured payment before its window ends, for `captured − refunded`.

- [ ] **Step 1: Extend the pack** with the fields, ids, events and laws above (events owned by `payment`; `refund_id: ref("refund")`).

- [ ] **Step 2: Extend the kernels**

`PAYMENT_COMMANDS = (START, C_CAPTURE, C_AUTH_EXPIRE, C_WINDOW, C_REFUND, C_REFUND_DUP, C_SETTLE, C_DISPUTE, C_RESOLVE)`. Decorator `max=Res(records={"payment_authorized": 1, "payment_declined": 1, "payment_captured": 1, "payment_expired": 1, "refund_requested": 1, "refund_rejected": 1, "refund_settled": 1, "refund_failed": 1, "refund_replayed": 1, "dispute_opened": 1, "dispute_won": 1, "dispute_lost": 1, "ledger": 3}, creates={"refund": 1}, timers=3)`. Dispatch adds:
```python
    if cmd.kind == C_REFUND:
        return _refund(ctx, loc, out, cfg)
    if cmd.kind == C_REFUND_DUP:
        return _replay(ctx, loc, cmd, out)
    if cmd.kind == C_SETTLE:
        return _settle(ctx, loc, cmd, out, cfg)
    if cmd.kind == C_DISPUTE:
        return _dispute(ctx, loc, out, cfg)
    if cmd.kind == C_RESOLVE:
        return _resolve(ctx, loc, out, cfg)
```
`_capture` draws, before its reserve, `refund = ctx.rng.bernoulli(site=4, p=cfg.refund_p)`, `rgap = ctx.rng.dist_us(site=5, d=cfg.refund_gap)`, `dispute = ctx.rng.bernoulli(site=6, p=cfg.dispute_p)`, `dgap = ctx.rng.dist_us(site=7, d=cfg.dispute_delay)`; reserves `timers=3`; and after the window timer adds `if refund: out.timer(ctx.t + rgap, C_REFUND, prio=PRIO_TIMER)` and `if dispute and ctx.t + dgap < loc.window_end: out.timer(ctx.t + dgap, C_DISPUTE, prio=PRIO_TIMER)`.

New helpers:
```python
def _find(loc, key):
    for j in range(loc.idem_n):
        if loc.idem_key[j] == key:
            return j
    return -1


def _refund(ctx, loc, out, cfg):
    if loc.status != P_CAPTURED or loc.refunds >= cfg.max_refunds or loc.idem_n >= 4:
        return reject(REJ_STALE)
    want = max(1, ctx.rng.lognormal_minor(site=10, median=cfg.refund_median,
                                          sigma=cfg.refund_sigma))
    settle = ctx.rng.dist_us(site=11, d=cfg.refund_settle)
    dup = ctx.rng.bernoulli(site=12, p=cfg.duplicate_p)
    dup_gap = ctx.rng.dist_us(site=13, d=cfg.duplicate_gap)
    again = ctx.rng.bernoulli(site=14, p=cfg.refund_p)
    gap = ctx.rng.dist_us(site=15, d=cfg.refund_gap)
    if not out.reserve(records={"refund_requested": 1, "refund_rejected": 1},
                       creates={"refund": 1}, timers=3):
        return RETRY
    rid = out.new_id("refund")
    k = loc.idem_n
    loc.idem_key[k] = rid
    loc.idem_n = k + 1
    loc.refunds += 1
    left = loc.captured - loc.refunded - loc.refund_hold
    if loc.dispute == D_OPEN:                              # §09: rejected while disputed
        loc.idem_result[k] = R_REJECTED_IDEM
        out.emit_refund_rejected(ctx.t, payment_id=ctx.self_id, refund_id=rid,
                                 reason="dispute_open")
    elif left <= 0 or loc.dispute == D_LOST:
        loc.idem_result[k] = R_REJECTED_IDEM
        out.emit_refund_rejected(ctx.t, payment_id=ctx.self_id, refund_id=rid,
                                 reason="nothing_left")
    else:
        amt = std.checked_min(left, want)
        loc.refund_hold = std.checked_add(loc.refund_hold, amt)          # the hold
        loc.idem_result[k] = R_REQUESTED
        loc.idem_amount[k] = amt
        out.emit_refund_requested(ctx.t, payment_id=ctx.self_id, refund_id=rid, amount=amt)
        out.timer(ctx.t + settle, C_SETTLE, prio=PRIO_TIMER, tag=rid)
    if dup:                                                # the merchant retries the key
        out.timer(ctx.t + dup_gap, C_REFUND_DUP, prio=PRIO_TIMER, tag=rid)
    if again and loc.refunds < cfg.max_refunds:
        out.timer(ctx.t + gap, C_REFUND, prio=PRIO_TIMER)
    return COMMIT


def _settle(ctx, loc, cmd, out, cfg):
    j = _find(loc, cmd.tag)
    if j < 0 or loc.idem_result[j] != R_REQUESTED:
        return reject(REJ_STALE)
    fail = ctx.rng.bernoulli(site=20, p=cfg.refund_fail_p)
    if not out.reserve(records={"refund_settled": 1, "refund_failed": 1, "ledger": 2}):
        return RETRY
    amt = loc.idem_amount[j]
    loc.refund_hold = std.checked_sub(loc.refund_hold, amt)
    if fail:                                               # release the hold
        loc.idem_result[j] = R_FAILED
        out.emit_refund_failed(ctx.t, payment_id=ctx.self_id, refund_id=cmd.tag, amount=amt)
    else:                                                  # commit the hold
        loc.refunded = std.checked_add(loc.refunded, amt)
        loc.idem_result[j] = R_SETTLED
        out.emit_refund_settled(ctx.t, payment_id=ctx.self_id, refund_id=cmd.tag, amount=amt,
                                refunded_after=loc.refunded)
        _post(ctx, out, A_MERCHANT, A_REFUNDS_PAYABLE, amt)
    return COMMIT


def _replay(ctx, loc, cmd, out):
    j = _find(loc, cmd.tag)
    if j < 0:
        return reject(REJ_STALE)
    if not out.reserve(records={"refund_replayed": 1}):
        return RETRY
    first = 1 if loc.idem_result[j] == R_REJECTED_IDEM else 0     # requested | rejected
    out.emit_refund_replayed(ctx.t, payment_id=ctx.self_id, refund_id=cmd.tag, result=first)
    return COMMIT


def _dispute(ctx, loc, out, cfg):
    if loc.status != P_CAPTURED or loc.dispute != D_NONE or ctx.t >= loc.window_end:
        return reject(REJ_STALE)
    resolve = ctx.rng.dist_us(site=30, d=cfg.dispute_resolve)
    if not out.reserve(records={"dispute_opened": 1, "ledger": 2}, timers=1):
        return RETRY
    amt = loc.captured - loc.refunded
    loc.dispute = D_OPEN
    loc.disputed = amt
    out.emit_dispute_opened(ctx.t, payment_id=ctx.self_id, amount=amt)
    _post(ctx, out, A_MERCHANT, A_DISPUTE_RESERVE, amt)
    out.timer(ctx.t + resolve, C_RESOLVE, prio=PRIO_TIMER)
    return COMMIT


def _resolve(ctx, loc, out, cfg):
    if loc.dispute != D_OPEN:
        return reject(REJ_STALE)
    won = ctx.rng.bernoulli(site=31, p=cfg.dispute_win_p)
    if not out.reserve(records={"dispute_won": 1, "dispute_lost": 1, "ledger": 2}):
        return RETRY
    if won:
        loc.dispute = D_WON
        out.emit_dispute_won(ctx.t, payment_id=ctx.self_id, amount=loc.disputed)
        _post(ctx, out, A_DISPUTE_RESERVE, A_MERCHANT, loc.disputed)
    else:
        loc.dispute = D_LOST
        out.emit_dispute_lost(ctx.t, payment_id=ctx.self_id, amount=loc.disputed)
        _post(ctx, out, A_DISPUTE_RESERVE, A_CUSTOMER_FUNDS, loc.disputed)
    return COMMIT
```

- [ ] **Step 3: Write the failing tests**

`apps/datagen/tests/test_example_ecom_s2_refunds.py`:
```python
import json
from pathlib import Path

import polars as pl
import pytest

from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events

EX = Path(__file__).resolve().parents[3] / "examples" / "ecommerce_s2"
DAY = 86_400_000_000.0
POOLS = ["engine.timer_nodes=600_000", "engine.payload_slots=100_000",
         "engine.max_messages_per_step=300_000", "budget.max_admissions_per_step=50_000",
         "budget.max_checker_keys=2_000_000"]
BUSY = ["users=3000", "skus=1200", "sku_groups=8", "run.span=14d", "run.warmup=0s",
        "pay.refund_p=0.6", "pay.duplicate_p=0.5", "pay.dispute_p=0.3",
        f"pay.refund_gap.params=[{0.5 * DAY}, 0.0, 0.0]",
        f"pay.dispute_delay.params=[{1.0 * DAY}, 2.0, 0.0]",
        f"pay.dispute_resolve.params=[{2.0 * DAY}, 2.0, 0.0]",
        f"pay.refund_settle.params=[{0.25 * DAY}, 0.5, 0.0]", *POOLS]


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    return run_to_dataset(EX, "sample", BUSY, out_dir=tmp_path_factory.mktemp("ref") / "run",
                          threads=4)


@pytest.fixture(scope="module")
def ev(run):
    return read_events(run.out_dir)


def test_settled_refunds_never_exceed_the_capture(ev):
    cap = ev["payment_captured"].select("payment_id", pl.col("amount").alias("captured"))
    tot = ev["refund_settled"].group_by("payment_id").agg(pl.col("amount").sum())
    j = tot.join(cap, on="payment_id")
    assert j.height > 50 and (j["amount"] <= j["captured"]).all()


def test_refunds_are_rejected_while_a_dispute_is_open(ev):
    rej = ev["refund_rejected"].filter(pl.col("reason") == "dispute_open")
    assert rej.height > 0
    opened = ev["dispute_opened"].select("payment_id", pl.col("event_time").alias("t0"))
    closed = pl.concat([ev["dispute_won"].select("payment_id", "event_time"),
                        ev["dispute_lost"].select("payment_id", "event_time")]).rename(
        {"event_time": "t1"})
    j = rej.join(opened, on="payment_id").join(closed, on="payment_id", how="left")
    assert j.height == rej.height
    assert ((j["event_time"] >= j["t0"]) & (j["t1"].is_null() | (j["event_time"] < j["t1"]))).all()


def test_duplicate_keys_return_the_first_result(ev):
    first = pl.concat([ev["refund_requested"].select("refund_id", pl.lit("requested").alias("f")),
                       ev["refund_rejected"].select("refund_id", pl.lit("rejected").alias("f"))])
    rep = ev["refund_replayed"].join(first, on="refund_id")
    assert rep.height > 0 and (rep["result"].cast(pl.String) == rep["f"]).all()
    for t in ("refund_settled", "refund_failed"):          # replays change nothing
        assert ev[t]["refund_id"].n_unique() == ev[t].height


def test_each_refund_settles_or_fails_once(ev):
    done = pl.concat([ev["refund_settled"].select("refund_id"),
                      ev["refund_failed"].select("refund_id")])
    assert done["refund_id"].n_unique() == done.height > 0
    assert set(done["refund_id"]) <= set(ev["refund_requested"]["refund_id"])


def test_disputes_resolve_once_for_the_disputed_amount(ev):
    o = ev["dispute_opened"].select("payment_id", pl.col("amount").alias("a"))
    r = pl.concat([ev["dispute_won"].select("payment_id", "amount"),
                   ev["dispute_lost"].select("payment_id", "amount")])
    assert r["payment_id"].n_unique() == r.height > 0
    j = r.join(o, on="payment_id")
    assert (j["amount"] == j["a"]).all()


def test_payment_laws_hold(run):
    laws = json.loads((run.out_dir / "manifest.json").read_text())["laws"]
    for k in ("chk.refunds_le_captured", "chk.refund_settles_once", "chk.postings_balanced"):
        assert laws[k]["violations"] == 0 and laws[k]["checked"] > 0, k
```

- [ ] **Step 4: Run tests to verify they fail, then make them pass**

Run: `uv run --all-packages pytest apps/datagen/tests/test_example_ecom_s2_refunds.py -v`
Expected first: FAIL (`KeyError: 'refund_settled'` or `unknown setting 'pay.refund_p'`); after Steps 1–2: PASS (6 tests); Tasks 12–13 tests still pass — their runs have a 1-day warm-up, and a refund after `start` of a payment captured in warm-up passes `chk.refunds_le_captured` because the warm-up capture reached the law's carried sums (Task 9 F-01 feed). If it fails there, the warm-up feed is wrong, not the law.

- [ ] **Step 5: Full suite, lint, commit**

Run: `uv run --all-packages pytest -q && uv run ruff check $(ls -d libs apps examples/ecommerce_s1 examples/ecommerce_s2 benchmarks 2>/dev/null)`
```bash
git add examples/ecommerce_s2 apps/datagen/tests/test_example_ecom_s2_refunds.py
git commit -m "examples(s2): refunds hold against the remainder, idempotent keys, disputes

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 15: Referral claims, the capped bonus pool and bounty-hunter campaigns

**Files:**
- Modify: `examples/ecommerce_s2/specs/pack.py`, `examples/ecommerce_s2/specs/kernels.py`, `examples/ecommerce_s2/specs/brief.md`, `examples/ecommerce_s2/README.md`
- Test: `apps/datagen/tests/test_example_ecom_s2_pool.py`

**Interfaces:**
- Consumes: Task 8 `std.capped_pool`; Tasks 12–14 project.
- Produces:
  - `Config.pool_cap: int = 2_000_000`, `Config.hunt: Hunt`; `Journey.min_order: int = 2_000`, `Journey.invitee_bonus: int = 1_000`; `Hunt(share=0.01, zombies_mean=12.0, member_gap=dist.exp(mean_s=900), order_p=0.85, order_amount=2_100, bonus=1_000)`.
  - Shard `pool` (`n=1`, state `{"remaining": "i64", "granted": "i64"}`, `init=std.capped_pool.init(cfg.pool_cap)`); request boundaries `claim` (user → pool) and `campaign_claim` (campaign → pool), payload and response payload `{"amount": amount(USD)}`, responses `granted`/`rejected`, latency `shifted_lognormal(min_ms=200, median_ms=500)`; processes `pool_desk` (claim) and `campaign_desk` (campaign_claim) sharing helper `_grant`.
  - Owner `campaign` (population `n = max(1, round(users × hunt.share / (1 + hunt.zombies_mean)))`, `initial=0.2`, flat arrivals, table `campaign(zombies i16)` with `zombies ~ dist.geometric(mean=hunt.zombies_mean)`); process `hunter` (commands `START, C_MEMBER=1, R_PAID=2, R_DENIED=3`).
  - `p.ids("claim", "member")`. Events: pool `bonus_granted(claim_id, source cat(user, campaign), amount, remaining_after)`, `bonus_rejected(claim_id, source, amount)`; user `referral_bonus_paid(user_id, claim_id, amount)`, `referral_bonus_denied(user_id, claim_id)`; campaign `campaign_started(campaign_id, zombies)`, `member_joined(campaign_id, member_id)`, `member_ordered(campaign_id, member_id, amount)`, `member_bonus_paid(campaign_id, member_id, claim_id, amount)`, `member_bonus_denied(campaign_id, member_id, claim_id)`, `campaign_finished(campaign_id, paid i16, denied i16)`.
  - Shopper commands gain `R_BONUS = 7`, `R_NO_BONUS = 8`; a referred shopper's first successful checkout with `subtotal >= min_order` sends one claim for `invitee_bonus`.
  - Laws (declared in this order): `chk.one_grant_per_claim` (`at_most_once("bonus_granted", key="claim_id")`), `chk.pool_cap` (`total_le("bonus_granted.amount", cfg.pool_cap)`), `chk.pool_never_negative` (`never_negative("pool.remaining")`), all required.

- [ ] **Step 1: Extend the pack** as in Interfaces (shopper process: `requests={"reserve": reserve, "claim": claim}`, `on_response` adds `("claim", "granted"): k.R_BONUS, ("claim", "rejected"): k.R_NO_BONUS`; `hunter` process: `owner="campaign"`, `config=cfg.hunt`, `start=p.on_created("campaign")`, `requests={"campaign_claim": campaign_claim}`, `on_response={("campaign_claim", "granted"): k.R_PAID, ("campaign_claim", "rejected"): k.R_DENIED}`, `commands=k.HUNTER_COMMANDS`; `pool_desk`: `shard="pool"`, `on_request={"claim": k.C_CLAIM}`; `campaign_desk`: `on_request={"campaign_claim": k.C_CLAIM}`).

- [ ] **Step 2: Extend the kernels**

Shopper: `SHOPPER_COMMANDS` adds `R_BONUS, R_NO_BONUS`; decorator `records` adds `"referral_bonus_paid": 1, "referral_bonus_denied": 1`, `creates` adds `"claim": 1`, `requests=CART + 1` (the claim request; the payment's creation message stays automatic); dispatch adds `if cmd.kind == R_BONUS or cmd.kind == R_NO_BONUS: return _bonus(ctx, cmd, out)` before `_answer`; `_answer` reserves `creates={"payment": 1, "claim": 1}`, `requests=CART + 1`, and after `emit_checkout_succeeded`:
```python
            if loc.ordered == 0:                           # the referral's first order
                loc.ordered = 1
                if s.referred and loc.subtotal >= cfg.min_order:
                    claim = out.new_id("claim")
                    out.request_claim(ctx.t, shard=0, tag=claim, amount=cfg.invitee_bonus)
```
```python
def _bonus(ctx, cmd, out):
    if not out.reserve(records={"referral_bonus_paid": 1, "referral_bonus_denied": 1}):
        return RETRY
    if cmd.kind == R_BONUS:
        out.emit_referral_bonus_paid(ctx.t, user_id=ctx.self_id, claim_id=cmd.tag,
                                     amount=cmd.amount)
    else:
        out.emit_referral_bonus_denied(ctx.t, user_id=ctx.self_id, claim_id=cmd.tag)
    return COMMIT
```
Pool and campaigns:
```python
C_CLAIM = 1
SRC_USER, SRC_CAMPAIGN = 0, 1
C_MEMBER, R_PAID, R_DENIED = 1, 2, 3
HUNTER_COMMANDS = (START, C_MEMBER, R_PAID, R_DENIED)
HUNTER_LOCAL = Local(left="i16", member="ref", paid="i16", denied="i16")


def _grant(ctx, s, cmd, out, source):
    g = std.capped_pool.take(s.remaining, cmd.amount)      # whole claims only: exact cap
    if g > 0:
        s.remaining = std.checked_sub(s.remaining, g)
        s.granted = std.checked_add(s.granted, g)
        out.emit_bonus_granted(ctx.t, claim_id=cmd.tag, source=source, amount=g,
                               remaining_after=s.remaining)
    else:
        out.emit_bonus_rejected(ctx.t, claim_id=cmd.tag, source=source, amount=cmd.amount)
    return g


@kernel(state="pool", commands=(C_CLAIM,),
        max=Res(records={"bonus_granted": 1, "bonus_rejected": 1}, requests=1))
def pool_desk(ctx, s, cmd, out):
    if not out.reserve(records={"bonus_granted": 1, "bonus_rejected": 1}, requests=1):
        return RETRY
    if _grant(ctx, s, cmd, out, SRC_USER) > 0:
        out.respond(cmd, "granted", amount=cmd.amount)
    else:
        out.respond(cmd, "rejected", amount=0)
    return COMMIT


@kernel(state="pool", commands=(C_CLAIM,),
        max=Res(records={"bonus_granted": 1, "bonus_rejected": 1}, requests=1))
def campaign_desk(ctx, s, cmd, out):
    if not out.reserve(records={"bonus_granted": 1, "bonus_rejected": 1}, requests=1):
        return RETRY
    if _grant(ctx, s, cmd, out, SRC_CAMPAIGN) > 0:
        out.respond(cmd, "granted", amount=cmd.amount)
    else:
        out.respond(cmd, "rejected", amount=0)
    return COMMIT


@kernel(state="campaign", local=HUNTER_LOCAL, commands=HUNTER_COMMANDS,
        max=Res(records={"campaign_started": 1, "member_joined": 1, "member_ordered": 1,
                         "member_bonus_paid": 1, "member_bonus_denied": 1,
                         "campaign_finished": 1},
                creates={"member": 1, "claim": 1}, timers=1, requests=1))
def hunter(ctx, s, loc, cmd, out):
    cfg = ctx.cfg
    if cmd.kind == START:
        gap = ctx.rng.dist_us(site=1, d=cfg.member_gap)
        if not out.reserve(records={"campaign_started": 1}, timers=1):
            return RETRY
        loc.left = min(s.zombies, 30)
        out.emit_campaign_started(ctx.t, campaign_id=ctx.self_id, zombies=loc.left)
        out.timer(ctx.t + gap, C_MEMBER, prio=PRIO_TIMER)
        return COMMIT
    if cmd.kind == C_MEMBER:
        return _member(ctx, loc, out, cfg)
    return _member_answer(ctx, loc, cmd, out)


def _member(ctx, loc, out, cfg):
    orders = ctx.rng.bernoulli(site=2, p=cfg.order_p)
    gap = ctx.rng.dist_us(site=3, d=cfg.member_gap)
    if not out.reserve(records={"member_joined": 1, "member_ordered": 1, "campaign_finished": 1},
                       creates={"member": 1, "claim": 1}, timers=1, requests=1):
        return RETRY
    if loc.left <= 0:
        out.emit_campaign_finished(ctx.t, campaign_id=ctx.self_id, paid=loc.paid,
                                   denied=loc.denied)
        return COMMIT                                      # nothing queued: retires
    loc.member = out.new_id("member")
    loc.left -= 1
    out.emit_member_joined(ctx.t, campaign_id=ctx.self_id, member_id=loc.member)
    if orders:                                             # a zombie's qualifying order
        out.emit_member_ordered(ctx.t, campaign_id=ctx.self_id, member_id=loc.member,
                                amount=cfg.order_amount)
        claim = out.new_id("claim")
        out.request_campaign_claim(ctx.t, shard=0, tag=claim, amount=cfg.bonus)
    out.timer(ctx.t + gap, C_MEMBER, prio=PRIO_TIMER)
    return COMMIT


def _member_answer(ctx, loc, cmd, out):
    if not out.reserve(records={"member_bonus_paid": 1, "member_bonus_denied": 1}):
        return RETRY
    if cmd.kind == R_PAID:
        loc.paid += 1
        out.emit_member_bonus_paid(ctx.t, campaign_id=ctx.self_id, member_id=loc.member,
                                   claim_id=cmd.tag, amount=cmd.amount)
    else:
        loc.denied += 1
        out.emit_member_bonus_denied(ctx.t, campaign_id=ctx.self_id, member_id=loc.member,
                                     claim_id=cmd.tag)
    return COMMIT
```
(`_grant` is shared by two kernels with the same state and payload slot for `amount`, so it lowers to one source.)

- [ ] **Step 3: Write the failing tests**

`apps/datagen/tests/test_example_ecom_s2_pool.py`:
```python
import json
from pathlib import Path

import polars as pl
import pytest

from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events

EX = Path(__file__).resolve().parents[3] / "examples" / "ecommerce_s2"
POOLS = ["engine.timer_nodes=600_000", "engine.payload_slots=100_000",
         "engine.max_messages_per_step=300_000", "budget.max_admissions_per_step=50_000",
         "budget.max_checker_keys=2_000_000"]
CAP = 60_000
DRAIN = ["users=3000", "skus=1200", "sku_groups=8", "run.span=10d", "run.warmup=0s",
         "referred_share=0.5", f"pool_cap={CAP}", "hunt.share=0.05", *POOLS]


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    return run_to_dataset(EX, "sample", DRAIN, out_dir=tmp_path_factory.mktemp("pool") / "run",
                          threads=4)


@pytest.fixture(scope="module")
def ev(run):
    return read_events(run.out_dir)


def _decisions(ev):
    return pl.concat([ev["bonus_granted"].select("event_time", "lamport", "claim_id", "source",
                                                 "amount", pl.lit(True).alias("ok")),
                      ev["bonus_rejected"].select("event_time", "lamport", "claim_id", "source",
                                                  "amount", pl.lit(False).alias("ok"))]
                     ).sort("event_time", "lamport")


def test_the_cap_is_exact(ev):
    g = ev["bonus_granted"]
    assert g["amount"].sum() == CAP                     # drained to the cent
    assert g.sort("event_time", "lamport")["remaining_after"].to_list()[-1] == 0
    d = _decisions(ev)
    last_grant = d.with_row_index().filter(pl.col("ok"))["index"].max()
    assert not d[: last_grant + 1].filter(~pl.col("ok")).height   # no rejection before drained


def test_each_claim_is_decided_once(ev):
    d = _decisions(ev)
    assert d["claim_id"].n_unique() == d.height > 0


def test_hunters_crowd_out_normal_users(ev):
    d = _decisions(ev)
    assert set(d.filter(pl.col("ok"))["source"]) == {"user", "campaign"}
    assert d.filter(~pl.col("ok") & (pl.col("source") == "user")).height > 0


def test_owners_learn_their_decision(ev):
    paid = pl.concat([ev["referral_bonus_paid"].select("claim_id"),
                      ev["member_bonus_paid"].select("claim_id")])
    granted = ev["bonus_granted"].select("claim_id")
    assert set(paid["claim_id"]) <= set(granted["claim_id"])
    assert paid.height >= 0.95 * granted.height


def test_campaigns_finish_with_their_members(ev):
    fin = ev["campaign_finished"]
    assert fin.height > 0
    orders = ev["member_ordered"].group_by("campaign_id").len()
    j = fin.join(orders, on="campaign_id")
    assert ((j["paid"].cast(pl.UInt32) + j["denied"].cast(pl.UInt32)) == j["len"]).all()


def test_pool_laws_hold(run):
    laws = json.loads((run.out_dir / "manifest.json").read_text())["laws"]
    for k in ("chk.one_grant_per_claim", "chk.pool_cap", "chk.pool_never_negative"):
        assert laws[k]["violations"] == 0 and laws[k]["checked"] > 0, k
```

- [ ] **Step 4: Run tests to verify they fail, then make them pass**

Run: `uv run --all-packages pytest apps/datagen/tests/test_example_ecom_s2_pool.py -v`
Expected first: FAIL (`unknown setting 'pool_cap'`); after Steps 1–2: PASS (6 tests). Tasks 12–14 tests still pass.

- [ ] **Step 5: Full suite, lint, commit**

Run: `uv run --all-packages pytest -q && uv run ruff check $(ls -d libs apps examples/ecommerce_s1 examples/ecommerce_s2 benchmarks 2>/dev/null)`
```bash
git add examples/ecommerce_s2 apps/datagen/tests/test_example_ecom_s2_pool.py
git commit -m "examples(s2): referral claims against a capped pool; bounty-hunter campaigns

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 16: Reference implementations against the real kernels (holds, pool, refunds)

§11: "Reference implementations for ... holds run against the real kernels on fixtures in CI." Each reference is a plain-Python model that replays one shard's or owner's decisions from its own output stream (plus the initial state the world was built with) and must predict every decision the compiled kernel made.

**Files:**
- Create: `libs/simkit/src/neorisk_simkit/checks/reference.py`, `apps/datagen/tests/test_reference_kernels_s2.py`

**Interfaces:**
- Consumes: Tasks 12–15 output schemas; `World.build`, `World.state["inventory"]`, `World.offs`, `World.items`; `io.seal.public_ids`.
- Produces (`checks/reference.py`, pure Python + polars, no engine imports):
  - `replay_inventory(events: dict[str, pl.DataFrame], on_hand0: dict[int, int], slots: int) -> list[str]`: per `sku_group`, in canonical order over `stock_reserved`, `stock_rejected`, `stock_committed`, `stock_released`, `stock_expired`, `stock_commit_late`, `restocked`; tracks `on_hand`, `reserved` per SKU (public id) and the live holds per group; a reserve must be granted iff `on_hand − reserved ≥ quantity` and fewer than `slots` holds are live, a rejection's reason must be `out_of_stock` when stock is short and `busy` otherwise; commits, releases and expiries must name a live hold of that quantity; `stock_commit_late` must name a hold that is not live; `on_hand_after` must match. Returns one line per mismatch (empty when the kernel agrees).
  - `replay_pool(events, cap: int) -> list[str]`: over `bonus_granted` and `bonus_rejected` in canonical order, grant iff `0 < amount <= remaining`; `remaining_after` must match.
  - `replay_refunds(events) -> list[str]`: per `payment_id` in canonical order over the payment events of Tasks 13–14; checks every rule listed in Task 14 Interfaces (hold against the remainder, rejection reasons, settle/fail releases the hold, replay returns the first result, dispute amount).

- [ ] **Step 1: Write the failing tests**

`apps/datagen/tests/test_reference_kernels_s2.py`:
```python
"""§11: reference models replay the real kernels' decisions and agree with every one."""

from pathlib import Path

import numpy as np
import pytest

from neorisk_simkit.checks.reference import replay_inventory, replay_pool, replay_refunds
from neorisk_simkit.engine.world import World
from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events
from neorisk_simkit.io.seal import public_ids
from neorisk_simkit.spec.project import load_project, resolve_run

EX = Path(__file__).resolve().parents[3] / "examples" / "ecommerce_s2"
DAY = 86_400_000_000.0
POOLS = ["engine.timer_nodes=600_000", "engine.payload_slots=100_000",
         "engine.max_messages_per_step=300_000", "budget.max_admissions_per_step=50_000",
         "budget.max_checker_keys=2_000_000"]
# warm-up 0: every decision is exported, so the replay sees the whole history
STRESS = ["users=3000", "skus=600", "sku_groups=4", "run.span=6d", "run.warmup=0s",
          "journey.abandon_p=0.3", "journey.checkout_p=0.9", "journey.session_gap_min_h=6.0",
          "referred_share=0.5", "pool_cap=40_000", "hunt.share=0.05",
          "pay.refund_p=0.6", "pay.duplicate_p=0.5", "pay.dispute_p=0.3",
          f"pay.refund_gap.params=[{0.5 * DAY}, 0.0, 0.0]",
          f"pay.dispute_delay.params=[{1.0 * DAY}, 2.0, 0.0]",
          f"pay.dispute_resolve.params=[{1.0 * DAY}, 2.0, 0.0]", *POOLS]


@pytest.fixture(scope="module")
def ev(tmp_path_factory):
    r = run_to_dataset(EX, "sample", STRESS, out_dir=tmp_path_factory.mktemp("ref") / "run",
                       threads=4)
    return read_events(r.out_dir)


def _on_hand0():
    run = resolve_run(load_project(EX), "sample", STRESS)
    w = World.build(run, threads=1)
    items = w.items["inventory"]                         # dense SKU ids in CSR order
    on_hand = w.state["inventory"][0]                    # initial on_hand, CSR order
    pub = public_ids(int(run.seed), "sku", np.asarray(items, np.int64))
    return {int(p): int(x) for p, x in zip(pub, on_hand, strict=True)}


def test_inventory_reference(ev):
    assert ev["stock_reserved"].height > 500 and ev["stock_expired"].height > 0
    assert replay_inventory(ev, _on_hand0(), slots=64) == []


def test_pool_reference(ev):
    assert ev["bonus_rejected"].height > 0
    assert replay_pool(ev, cap=40_000) == []


def test_refund_reference(ev):
    assert ev["refund_replayed"].height > 0 and ev["dispute_opened"].height > 0
    assert replay_refunds(ev) == []


def test_references_catch_a_wrong_decision(ev):
    import polars as pl
    flipped = dict(ev)
    g = ev["bonus_granted"]
    flipped["bonus_granted"] = g.with_columns(
        pl.when(pl.int_range(pl.len()) == 0).then(pl.col("remaining_after") + 1)
        .otherwise(pl.col("remaining_after")).alias("remaining_after"))
    assert replay_pool(flipped, cap=40_000)          # a tampered stream is caught
```
`slots=64` is `kernels.HOLD_SLOTS` of the S2 pack (a kernel module cannot be imported outside its pack, so the test passes the literal).

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --all-packages pytest apps/datagen/tests/test_reference_kernels_s2.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'neorisk_simkit.checks.reference'`.

- [ ] **Step 3: Implement `checks/reference.py`** as in Interfaces (merge the tables of one partition with a source tag, sort by `event_time, lamport, seq`, and step through rows with Python state; mismatch lines name the event, `partition_id`, `seq` and the expected vs observed value). If a replay disagrees with the kernel, decide from the spec and Task 12/14/15 Interfaces which side is wrong; fix the kernel when it is the kernel.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --all-packages pytest apps/datagen/tests/test_reference_kernels_s2.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Full suite, lint, commit**

Run: `uv run --all-packages pytest -q && uv run ruff check $(ls -d libs apps examples/ecommerce_s1 examples/ecommerce_s2 benchmarks 2>/dev/null)`
```bash
git add libs/simkit/src/neorisk_simkit/checks/reference.py apps/datagen/tests/test_reference_kernels_s2.py
git commit -m "checks: reference models of holds, the capped pool and refunds vs real kernels

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 17: Mutation tests — seeded faults are caught by the laws

§11: "Mutation tests and forced-path fixtures run in CI." A fixture with one switch per seeded fault; each fault must fail the run with the law (or pairing check) that guards it.

**Files:**
- Create: `libs/simkit/tests/fixtures/mutants/{datagen.toml,specs/pack.py,specs/kernels.py}`, `libs/simkit/tests/test_exit_mutants.py`

**Interfaces:**
- Consumes: Tasks 2, 6, 9, 10 (pairing, postings, laws, `LawViolation`); `std.capped_pool`.
- Produces: fixture `mutants` (`Config(accts=4, cap=300, fault=0)`); fault codes: 1 pool ignores the cap, 2 credit exceeds funding, 3 unbalanced posting, 4 a claim granted twice, 5 a hold never freed, 6 a request rejected instead of answered, 7 pool remaining driven negative, 8 a negative (non-required) funding row.

- [ ] **Step 1: Write the fixture**

`libs/simkit/tests/fixtures/mutants/datagen.toml`: a copy of `fixtures/holder/datagen.toml` with `name = "mutants"`, `seed = 23`, `span = "6h"`, `warmup = "0s"`, `step = "1h"`.

`libs/simkit/tests/fixtures/mutants/specs/pack.py`:
```python
"""Seeded faults (spec §11 mutation tests): fault 0 is correct; each other fault breaks one
law, and the run must fail on exactly that law."""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, dist, law, std
from neorisk_simkit.spec.types import amount, cat, i32, ref

from . import kernels as k

PACK = "mutants"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Config:
    accts: int = 4
    cap: int = 300
    fault: int = 0


def define(p: Pack, cfg: Config) -> None:
    acct = p.table("acct", key="acct_id", mutable=True,
                   cols={"hold": ref("hold"), "claims": i32()})
    p.ids("claim", "hold")
    p.owner("acct", table=acct, max_live=cfg.accts)
    p.population(acct, n=cfg.accts, initial=1.0)
    pool = p.shard("pool", key="pool", n=1, items=None,
                   state={"remaining": "i64", "granted": "i64"},
                   init=std.capped_pool.init(cfg.cap))
    usd = amount(asset="USD")
    claim = p.request("claim", frm="acct", to=pool, payload={"amount": usd},
                      response_payload={"amount": usd}, responses=("granted", "rejected"),
                      latency=dist.constant(ms=100))
    a = {"acct_id": ref("acct")}
    p.event("funded", owner="acct", cols={**a, "amount": usd})
    p.event("credited", owner="acct", cols={**a, "claim_id": ref("claim"), "amount": usd})
    p.event("held", owner="acct", cols={**a, "hold_id": ref("hold")})
    p.event("freed", owner="acct", cols={**a, "hold_id": ref("hold")})
    p.event("granted", shard="pool", cols={"claim_id": ref("claim"), "amount": usd,
                                           "remaining_after": usd})
    p.event("denied", shard="pool", cols={"claim_id": ref("claim"), "amount": usd})
    p.postings("entry", owner="acct", cols={**a, "account": cat("cash", "bonus"),
                                            "side": cat("debit", "credit"), "amount": usd})
    p.process("acct_main", owner="acct", kernel=k.acct_main, config=cfg,
              start=p.on_created("acct"), requests={"claim": claim},
              on_response={("claim", "granted"): k.R_GRANTED,
                           ("claim", "rejected"): k.R_REJECTED},
              commands=k.ACCT_COMMANDS)
    p.process("pool_desk", shard=pool, kernel=k.pool_desk, config=cfg,
              on_request={"claim": k.C_CLAIM})
    # declaration order is evaluation order (Task 10): each fault trips its own law first
    p.check("chk.one_grant", law.at_most_once("granted", key="claim_id"), required=True)
    p.check("chk.pool_cap", law.total_le("granted.amount", cfg.cap), required=True)
    p.check("chk.pool_remaining", law.never_negative("pool.remaining"), required=True)
    p.check("chk.credit_le_funded", law.sum_le("credited.amount", "funded.amount",
                                               by="acct_id"), required=True)
    p.check("chk.entries_balance", law.balanced("entry"), required=True)
    p.check("chk.holds_freed", law.resolved("held", by=("freed",), key="hold_id", within="1h"),
            required=True)
    p.check("chk.funded_positive", law.never_negative("funded.amount"))
```

`libs/simkit/tests/fixtures/mutants/specs/kernels.py`:
```python
from neorisk_simkit import std
from neorisk_simkit.engine import COMMIT, RETRY, START, Res, kernel, reject

R_GRANTED, R_REJECTED = 1, 2
ACCT_COMMANDS = (START, R_GRANTED, R_REJECTED)
C_CLAIM = 1
CLAIMS = 3


@kernel(state="acct", commands=ACCT_COMMANDS,
        max=Res(records={"funded": 3, "credited": 1, "held": 1, "freed": 1, "entry": 2},
                creates={"claim": 1, "hold": 1}, requests=1))
def acct_main(ctx, s, cmd, out):
    fault = ctx.cfg.fault
    if not out.reserve(records={"funded": 3, "credited": 1, "held": 1, "freed": 1, "entry": 2},
                       creates={"claim": 1, "hold": 1}, requests=1):
        return RETRY
    if cmd.kind == START:
        out.emit_funded(ctx.t, acct_id=ctx.self_id, amount=1000)
        if fault == 8:                               # a negative row, net zero funding
            out.emit_funded(ctx.t, acct_id=ctx.self_id, amount=-1)
            out.emit_funded(ctx.t, acct_id=ctx.self_id, amount=1)
        s.hold = out.new_id("hold")
        out.emit_held(ctx.t, acct_id=ctx.self_id, hold_id=s.hold)
        out.request_claim(ctx.t, shard=0, tag=out.new_id("claim"), amount=100)
        return COMMIT
    if s.claims == 0 and fault != 5:
        out.emit_freed(ctx.t, acct_id=ctx.self_id, hold_id=s.hold)
    if cmd.kind == R_GRANTED:
        amt = 2000 if fault == 2 else cmd.amount
        out.emit_credited(ctx.t, acct_id=ctx.self_id, claim_id=cmd.tag, amount=amt)
        out.emit_entry(ctx.t, acct_id=ctx.self_id, account="cash", side="debit", amount=amt)
        if fault != 3:
            out.emit_entry(ctx.t, acct_id=ctx.self_id, account="bonus", side="credit",
                           amount=amt)
    s.claims += 1
    if s.claims < CLAIMS:
        out.request_claim(ctx.t, shard=0, tag=out.new_id("claim"), amount=100)
    return COMMIT


@kernel(state="pool", commands=(C_CLAIM,),
        max=Res(records={"granted": 2, "denied": 1}, requests=1))
def pool_desk(ctx, s, cmd, out):
    fault = ctx.cfg.fault
    if fault == 6:
        return reject(1)                             # a request must be answered
    if not out.reserve(records={"granted": 2, "denied": 1}, requests=1):
        return RETRY
    g = std.capped_pool.take(s.remaining, cmd.amount)
    if fault == 1:
        g = cmd.amount                               # ignores the cap
    if g > 0:
        cost = 2 * g if fault == 7 else g
        s.remaining = max(s.remaining - cost, 0) if fault == 1 else s.remaining - cost
        out.emit_granted(ctx.t, claim_id=cmd.tag, amount=g, remaining_after=s.remaining)
        if fault == 4:
            out.emit_granted(ctx.t, claim_id=cmd.tag, amount=g, remaining_after=s.remaining)
        out.respond(cmd, "granted", amount=g)
    else:
        out.emit_denied(ctx.t, claim_id=cmd.tag, amount=cmd.amount)
        out.respond(cmd, "rejected", amount=0)
    return COMMIT
```

- [ ] **Step 2: Write the failing tests**

`libs/simkit/tests/test_exit_mutants.py`:
```python
"""Spec §11 exit test: mutation tests. Every seeded fault is caught by the law guarding it."""

import json

import pytest
from conftest import FIXTURES

from neorisk_simkit.engine import EngineError
from neorisk_simkit.engine.errors import LawViolation
from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events

M = FIXTURES / "mutants"


def test_the_correct_pack_passes_every_law(tmp_path):
    r = run_to_dataset(M, "sample", out_dir=tmp_path / "ok", threads=1)
    laws = json.loads((r.out_dir / "manifest.json").read_text())["laws"]
    assert all(v["violations"] == 0 for v in laws.values())
    assert all(v["checked"] > 0 for k, v in laws.items())


@pytest.mark.parametrize("fault,check", [
    (1, "chk.pool_cap"), (2, "chk.credit_le_funded"), (3, "chk.entries_balance"),
    (4, "chk.one_grant"), (5, "chk.holds_freed"), (7, "chk.pool_remaining")])
def test_each_fault_trips_its_law(tmp_path, fault, check):
    with pytest.raises(LawViolation) as e:
        run_to_dataset(M, "sample", [f"fault={fault}"], out_dir=tmp_path / "x", threads=1)
    assert e.value.check_id == check
    assert not (tmp_path / "x").exists()


def test_an_unanswered_request_trips_pairing(tmp_path):
    with pytest.raises(EngineError, match=r"pool_desk: request claim must be answered exactly "
                                          r"once \(answered 0, returned 2\)"):
        run_to_dataset(M, "sample", ["fault=6"], out_dir=tmp_path / "x", threads=1)


def test_a_soft_law_is_counted_not_fatal(tmp_path):
    r = run_to_dataset(M, "sample", ["fault=8"], out_dir=tmp_path / "soft", threads=1)
    laws = json.loads((r.out_dir / "manifest.json").read_text())["laws"]
    assert laws["chk.funded_positive"]["violations"] == 4
    assert laws["chk.funded_positive"]["first"]["detail"] == "amount = -1"


def test_simultaneous_claims_at_the_cap_grant_exactly_one(tmp_path):
    """Review Focus #3: all four accounts claim 100 at t0 and the claims reach the pool at the
    same instant; with cap 100 exactly one is granted, the other three (and every later claim)
    are denied, and `chk.pool_cap` passes."""
    r = run_to_dataset(M, "sample", ["cap=100"], out_dir=tmp_path / "edge", threads=1)
    ev = read_events(r.out_dir)
    granted, denied = ev["granted"], ev["denied"]
    assert granted.height == 1 and granted["remaining_after"].to_list() == [0]
    t = granted["event_time"][0]
    assert (denied["event_time"] == t).sum() == 3            # tied at the same instant
    laws = json.loads((r.out_dir / "manifest.json").read_text())["laws"]
    assert laws["chk.pool_cap"]["violations"] == 0 and laws["chk.pool_cap"]["checked"] == 1
```

- [ ] **Step 3: Run tests to verify they fail, then make them pass**

Run: `uv run --all-packages pytest libs/simkit/tests/test_exit_mutants.py -v`
Expected first: FAIL (`no datagen.toml in .../fixtures/mutants` until Step 1). After Step 1: PASS (10 tests). A fault that trips a different law than listed means the evaluation order or a law is wrong (Task 10's order rule) — fix the library, not the parametrization.

- [ ] **Step 4: Full suite, lint, commit**

Run: `uv run --all-packages pytest -q && uv run ruff check $(ls -d libs apps examples/ecommerce_s1 examples/ecommerce_s2 benchmarks 2>/dev/null)`
```bash
git add libs/simkit/tests/fixtures/mutants libs/simkit/tests/test_exit_mutants.py
git commit -m "test: mutation tests — seeded faults are caught by their laws

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 18: Exit test — thread, slab and step invariance of the S2 slice

**Files:**
- Create: `libs/simkit/tests/test_exit_invariance_s2.py`
- Modify (tests): `libs/simkit/tests/conftest.py` (gains `KEY`, `created_namespaces`, `created_owner_codes`, `canonicalize_ids`), `libs/simkit/tests/test_exit_invariance.py` (imports them from `conftest`; its local definitions are deleted)

**Interfaces:**
- Consumes: `canonicalize_ids` and `created_namespaces` as left by the S1 Codex fix round in `test_exit_invariance.py` at BASE: `canonicalize_ids(d: Path, created: frozenset[str] | None = None, owner_codes: frozenset[int] = frozenset()) -> dict[str, list[dict]]`. With `owner_codes` (the `ptype_code`s of created owner types) it renames every created ID namespace by first appearance, renames created owners' `partition_id`s, and orders rows partition-free by `(event_time, lamport, type, every other non-ID column)` (non-ID = not `event_id`, not `partition_id`, not a ref to a created namespace), asserting that order is unambiguous; `event_id` becomes the position. So the comparison is a multiset of records after ID canonicalization: only the order among rows that tie on `(event_time, lamport)` across partitions is ignored, and every value is compared exactly. `conftest.event_dicts`, `conftest.dataset_tree`; the S2 project.
- Produces:
  - `conftest.created_namespaces(project: Path, overrides: list[str]) -> frozenset[str]` (no defaults: the S1 defaults `EX`, `SMALL` belong to the S1 test), `conftest.created_owner_codes(project: Path, overrides: list[str], created: frozenset[str]) -> frozenset[int]`, `conftest.canonicalize_ids(d: Path, created: frozenset[str], owner_codes: frozenset[int] = frozenset())` (`created` now required; body otherwise unchanged), `conftest.KEY` (F-09: test files do not import each other, Task 10).
  - The §10/§12 invariance exit test for a workload that creates owners per checkout and per bill, routes tied requests and holds handles in shards.

- [ ] **Step 0: Move the comparison helpers into `conftest.py`**

Append to `libs/simkit/tests/conftest.py`:
```python
KEY = ["event_time", "lamport", "partition_id", "seq"]


def _plan_of(project: Path, overrides: list[str]):
    from neorisk_simkit.spec.project import load_project, resolve_run  # lazy: conftest loads first
    return resolve_run(load_project(project), "sample", list(overrides)).plan


def created_namespaces(project: Path, overrides: list[str]) -> frozenset[str]:
    """The ID namespaces the engine hands out at seal (creatable tables and `ids`): only their
    dense indices legitimately depend on step boundaries (D13)."""
    return frozenset(_plan_of(project, overrides).namespaces)


def created_owner_codes(project: Path, overrides: list[str],
                        created: frozenset[str]) -> frozenset[int]:
    """`ptype_code`s of owner types whose table is created: their `partition_id`s are renamed."""
    return frozenset(p.ptype_code for p in _plan_of(project, overrides).partitions
                     if p.kind == "owner" and p.table in created)
```
and move `canonicalize_ids` from `test_exit_invariance.py` verbatim (docstring and body), with the signature `canonicalize_ids(d: Path, created: frozenset[str], owner_codes: frozenset[int] = frozenset()) -> dict[str, list[dict]]` and its first line (`created = created_namespaces() if created is None else created`) deleted; its imports go inside the function (`import polars as pl` may stay at module top; `load_schema`, `read_events` lazily). In `test_exit_invariance.py`: delete `KEY`, `created_namespaces`, `canonicalize_ids` and `_creators_plan`; import `from conftest import canonicalize_ids, created_namespaces, created_owner_codes, dataset_tree, event_dicts`; `test_step_lengths_give_identical_logical_records` uses `created = created_namespaces(EX, SMALL)` and `canonicalize_ids(d, created)` for both runs; `test_created_owners_identical_across_step_lengths` uses `created_namespaces(CREATORS, [])` and `codes = created_owner_codes(CREATORS, [], created)`. Run `uv run --all-packages pytest libs/simkit/tests/test_exit_invariance.py -q`: PASS, unchanged.

- [ ] **Step 1: Write the test**

`libs/simkit/tests/test_exit_invariance_s2.py`:
```python
"""Spec §10/§12 exit test on the S2 slice: identical logical records across threads, slab
sizes and step lengths, with created payment owners, shard-held handles and a hot shard."""

import itertools
import json
from pathlib import Path

import pytest
from conftest import (
    canonicalize_ids,
    created_namespaces,
    created_owner_codes,
    dataset_tree,
    event_dicts,
)

from neorisk_simkit.io.dataset import run_to_dataset

EX2 = Path(__file__).resolve().parents[3] / "examples" / "ecommerce_s2"
SMALL2 = ["users=1500", "skus=400", "sku_groups=6", "journey.hot_skus=20",
          "journey.abandon_p=0.2", "referred_share=0.5", "pool_cap=20_000", "hunt.share=0.05",
          "run.span=4d", "run.warmup=1d", "engine.adapt=false",
          "engine.timer_nodes=400_000", "engine.payload_slots=100_000",
          "engine.max_messages_per_step=300_000", "budget.max_admissions_per_step=50_000",
          "budget.max_checker_keys=2_000_000"]
THREADS = (1, 4, 16)
SLABS = ("4MB", "16KB")
STEPS = ("6h", "1d")
ENGINE = {"parallel_min_partitions": 1}


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    root = tmp_path_factory.mktemp("inv2")
    out = {}
    for threads, slab, step in itertools.product(THREADS, SLABS, STEPS):
        if threads == 16 and slab == "16KB":
            continue                                       # 10 runs keep CI time bounded
        d = root / f"t{threads}-{slab}-{step}"
        run_to_dataset(EX2, "sample", SMALL2 + [f"engine.slab_bytes={slab!r}",
                                                f"engine.step={step!r}"],
                       out_dir=d, threads=threads, engine_overrides=ENGINE)
        out[(threads, slab, step)] = d
    return out


def test_the_slice_exercises_the_s2_paths(runs):
    d = runs[(1, "4MB", "6h")]
    m = json.loads((d / "manifest.json").read_text())
    c = m["counts"]
    assert c["payment_authorized"] > 200 and c["stock_expired"] > 0
    assert c["bonus_rejected"] > 0 and c["refund_requested"] >= 0
    assert m["entity_counts"]["payment"] > 200


@pytest.mark.parametrize("step", STEPS)
def test_threads_and_slabs_give_identical_records(runs, step):
    base = event_dicts(runs[(1, "4MB", step)])
    for (threads, slab, s), d in runs.items():
        if s == step:
            assert event_dicts(d) == base, (threads, slab, step)


def test_step_lengths_give_identical_logical_records(runs):
    """§12 as read by D37: identical logical records as a multiset after ID canonicalization.
    Created IDs and created payments' `partition_id`s are renamed and rows are compared in the
    partition-free order, so only the order among rows tying on (event_time, lamport) across
    partitions is ignored; every value is compared exactly."""
    created = created_namespaces(EX2, SMALL2)
    assert {"payment", "checkout", "hold", "claim"} <= created
    codes = created_owner_codes(EX2, SMALL2, created)
    assert len(codes) == 1                               # `payment`, the created owner type
    assert canonicalize_ids(runs[(1, "4MB", "6h")], created, codes) == \
        canonicalize_ids(runs[(4, "16KB", "1d")], created, codes)


def test_identical_replay_is_byte_identical(runs, tmp_path):
    again = tmp_path / "again"
    run_to_dataset(EX2, "sample", SMALL2 + ["engine.slab_bytes='4MB'", "engine.step='6h'"],
                   out_dir=again, threads=4, engine_overrides=ENGINE)
    assert dataset_tree(runs[(4, "4MB", "6h")]) == dataset_tree(again)
```

- [ ] **Step 2: Run it**

Run: `uv run --all-packages pytest libs/simkit/tests/test_exit_invariance_s2.py -v`
Expected: PASS (5 tests). A failure here is an engine bug in Tasks 1–5 or 4b (handles, pairing, admission, routing order); find it with `superpowers:systematic-debugging` and fix the engine, never the comparison. If `canonicalize_ids` trips its own `"partition-free order is ambiguous"` assertion, two rows are identical in every non-ID column (`seq` is already in the key, so the preflight's "add the creator's seq" adds nothing); do not weaken the assertion or the comparison: stop and report the two rows to the controller.

- [ ] **Step 3: Lint, commit**

Run: `uv run ruff check $(ls -d libs apps examples/ecommerce_s1 examples/ecommerce_s2 benchmarks 2>/dev/null)`
```bash
git add libs/simkit/tests/conftest.py libs/simkit/tests/test_exit_invariance.py libs/simkit/tests/test_exit_invariance_s2.py
git commit -m "test: thread/slab/step invariance exit test on the S2 slice

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 19: Shard load, round and output accounting in `run_stats.json`

§19: "Hot shards serialize ... the S2-pool workload measures it; shard sizes are reported." §10: "exported events, histories, cases, snapshots, postings and labels are counted separately."

**Files:**
- Modify: `libs/simkit/src/neorisk_simkit/engine/world.py` (`stats["shard_load"]`), `engine/codegen.py` (`RS_SHARD_NS`; the drain times its shard phase), `engine/rounds.py` (`RoundStats.shard_ns`; Python rounds time their shard phase), `engine/run.py` (round, admission and shard-phase totals), `io/dataset.py` (`run_stats.json` fields)
- Test: `libs/simkit/tests/test_engine_shard_stats.py`

**Interfaces:**
- Consumes: Task 2 `RT_SHARD_REQ`; hidden `occ`; Task 5 compiled rounds and admissions; manifest counts and accumulators; `id_bases`.
- Produces, in `run_stats.json` (each value's counting window in brackets, F-25):
  - `shard_load: {shard partition: {"shards": n, "requests": [per shard], "commands": [per shard], "max_share": max(commands) / Σ commands (0 when none)}}` (commands = commits and rejects, from `occ` summed over the partition's processes) [whole run].
  - `commands` (all executed commands), `shard_commands`, `shard_command_share = shard_commands / commands` [whole run].
  - `rounds_total`, `compiled_rounds_total`, `admissions_total` [whole run].
  - `counts` (events per type), `posting_counts`, `entity_counts`, `accumulators` (copied from the manifest) [exported], `events_by_partition: {partition: exported events}` [exported], `populations: {table: n}` [whole run], `ids_allocated: {namespace: id_bases[ns] at the end}` (rows of every created table and `p.ids` namespace, warm-up included) [whole run].
  - Shard-phase rate (D55, F-03) [exported]: `shard_phase_seconds` = Σ `RoundStats.shard_ns` / 1e9 over exported steps; `shard_events` = Σ `events_by_partition[p]` over shard partitions `p`; `shard_events_per_second = shard_events / shard_phase_seconds` (0.0 when no shard time).
  - `RoundStats.shard_ns: int` (default 0): wall nanoseconds spent in shard phases this step. Python rounds wrap the shard `_run_phase` in `time.perf_counter_ns()`; the compiled drain adds `_now_ns() - t_` around its `PH_SHARDS` phase into `rs[RS_SHARD_NS]` (round-state index after `RS_NLOG`; the round-state array grows by one), where generated `_now_ns()` is `with objmode(t="int64"): t = time.perf_counter_ns()` / `return t` (numba `objmode`; two calls per compiled round). `run_step` zeroes `rs[RS_SHARD_NS]` at step start and adds it to `stats.shard_ns` at the end.

- [ ] **Step 1: Write the failing tests**

`libs/simkit/tests/test_engine_shard_stats.py`:
```python
import json

import pytest
from conftest import FIXTURES

from neorisk_simkit.io.dataset import run_to_dataset


@pytest.fixture(scope="module")
def mini(tmp_path_factory):
    r = run_to_dataset(FIXTURES / "mini", "sample", ["behavior.take_p=0.8"],
                       out_dir=tmp_path_factory.mktemp("load") / "run", threads=1)
    return json.loads((r.out_dir / "run_stats.json").read_text()), json.loads(
        (r.out_dir / "manifest.json").read_text())


def test_shard_load_is_reported_per_shard(mini):
    st, m = mini
    load = st["shard_load"]["bin"]
    assert load["shards"] == 4 and len(load["requests"]) == len(load["commands"]) == 4
    assert sum(load["requests"]) == st["requests_by_boundary"]["take"]
    assert sum(load["commands"]) == st["shard_commands"] >= sum(load["requests"])
    assert 0 < load["max_share"] <= 1


def test_command_shares_and_round_totals(mini):
    st, _ = mini
    assert st["commands"] == st["proposals"] + st["shard_commands"]
    assert st["shard_command_share"] == st["shard_commands"] / st["commands"]
    assert st["rounds_total"] == sum(st["rounds_per_step"]) >= st["compiled_rounds_total"]


def test_output_is_counted_by_kind_and_partition(mini):
    st, m = mini
    assert st["counts"] == m["counts"] and st["entity_counts"] == m["entity_counts"]
    assert st["posting_counts"] == m["posting_counts"] == {}
    assert st["accumulators"] == m["accumulators"] == {}
    assert sum(st["events_by_partition"].values()) == st["exported_events"]
    assert set(st["events_by_partition"]) == {"user", "bin"}
    assert st["populations"] == {"user": 200}


def test_shard_phase_rate_is_reported(mini):
    """D55 / F-03: shard-emitted exported events over the seconds spent in shard phases."""
    st, _ = mini
    assert st["shard_phase_seconds"] > 0
    assert st["shard_events"] == st["events_by_partition"]["bin"] > 0
    assert st["shard_events_per_second"] == st["shard_events"] / st["shard_phase_seconds"]


def test_admissions_are_counted(tmp_path):
    r = run_to_dataset(FIXTURES / "chain", "sample", out_dir=tmp_path / "c", threads=1)
    st = json.loads((r.out_dir / "run_stats.json").read_text())
    assert st["admissions_total"] == 8                    # 4 b + 4 c
    assert st["ids_allocated"] == {"b": 4, "c": 4}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --all-packages pytest libs/simkit/tests/test_engine_shard_stats.py -v`
Expected: FAIL with `KeyError: 'shard_load'`.

- [ ] **Step 3: Implement**: `World.stats["shard_load"]` from `R[RT_SHARD_REQ]` and `hidden.occ` over each shard partition's slots and `occ_col`s; `Simulation` keeps running `rounds_total`, `compiled_rounds_total` (from `RoundStats.compiled_rounds`), `admissions_total` (sum of `R[RT_ADM][0]` at each step end), `shard_commands` (Σ `shard_cmds`) and, on exported steps only, `shard_ns` (Σ `RoundStats.shard_ns`); `RS_SHARD_NS`, `_now_ns` and the two timing points as in Interfaces; `dataset._run_stats` adds the fields above (`ids_allocated` from the run's final `id_bases`, namespace keys only, not `event:<n>`). The README (Task 21) states each field's window.

- [ ] **Step 4: Run tests, full suite, lint, commit**

Run: `uv run --all-packages pytest libs/simkit/tests/test_engine_shard_stats.py -v && uv run --all-packages pytest -q && uv run ruff check $(ls -d libs apps examples/ecommerce_s1 examples/ecommerce_s2 benchmarks 2>/dev/null)`
Expected: PASS.
```bash
git add libs/simkit/src/neorisk_simkit libs/simkit/tests/test_engine_shard_stats.py
git commit -m "feat(io): report shard load, command shares, rounds and output by kind

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 20: S2 workload files, profiles and `datagen benchmark` for S2 gates

**Files:**
- Create: `benchmarks/s2.toml`, `benchmarks/s2_pool.toml`, `apps/datagen/tests/test_benchmark_s2.py`
- Modify: `apps/datagen/src/datagen/benchmark.py` (expectation forms, `min_events_per_second`, derived values, summary lines), `examples/ecommerce_s2/datagen.toml` (profiles `full`, `pool`), `examples/ecommerce_s2/README.md`, `apps/datagen/tests/test_example_ecom_s2.py` (`test_project_validates` covers all profiles)

**Interfaces:**
- Consumes: Task 19 stats; S1 `benchmark.Workload`, `evaluate`, `run_benchmark`.
- Produces:
  - Expectations: `{around, tolerance}` (S1), `{at_least = x}`, `{at_most = x}`; checks report `limit` as `[x, null]` / `[null, x]`.
  - Gate keys: `warm_seconds`, `peak_rss_gb` (S1), `min_events_per_second` (check name `events_per_second`, value `stats["events_per_second"]`), `min_shard_events_per_second` (check name `shard_events_per_second`, value `stats["shard_events_per_second"]`, D55/F-03).
  - `benchmark.derived(stats)` adds (window per F-25): `payments = counts.payment_authorized + counts.payment_declined` [exported]; `postings_per_payment_event = posting_counts.ledger / events_by_partition.payment` [exported]; `hot_share_of_checkouts = accumulators.hot_checkouts / counts.checkout_started` [exported; gated, F-02]; `hot_share_of_reserves = shard_load.inventory.requests[0] / Σ requests` [whole run; information only]; `shard_command_share` (from stats) [whole run]; `campaign_member_share = (populations.campaign + ids_allocated.member) / populations.user` [whole run: every campaign and member of the run over every user]. Each is computed only when its inputs exist (S1 reports are unchanged).
  - The benchmark report (`--out` JSON) and `summary` carry both `events_per_second` and `shard_events_per_second` (with `shard_phase_seconds`, `shard_events`) for every workload.
  - Profiles in `examples/ecommerce_s2/datagen.toml`: `full` (the s2 shape, D59) and `pool` (the s2_pool shape, D59); the calibration knobs live in their `set` tables (S1 ruling: calibration in the profile, not pack defaults). `pool` sizes its own engine pools for 2M users (F-23); `full` keeps the base pools.

- [ ] **Step 1: Write the workload files and profiles**

`benchmarks/s2.toml`:
```toml
# S2 benchmark workload (spec §10 and §18):
#   uv run --all-packages datagen benchmark benchmarks/s2.toml
[workload]
name = "s2"
project = "../examples/ecommerce_s2"
profile = "full"
seed = 42
set = []

[workload.shape]                         # what the workload fixes (spec §10)
users = 20_000_000
payments = 30_000_000
exported_events = 100_000_000
postings_per_payment_event = 2.5
dispute_timer_days = 90                  # pay.dispute_window_days
hot_sku_group_share = 0.05
span = "90d"

[expect]
exported_events = { around = 100_000_000, tolerance = 0.05 }
payments = { around = 30_000_000, tolerance = 0.05 }
postings_per_payment_event = { around = 2.5, tolerance = 0.04 }
hot_share_of_checkouts = { around = 0.05, tolerance = 0.01 }   # §10 "5% of checkouts" (F-02)

[gate]
warm_seconds = 600
threads = 16
reference = "16 cores / 64 GB"
```

`benchmarks/s2_pool.toml`:
```toml
# S2-pool workload (spec §10 and §18): a global capped bonus pool every referral claim
# reaches, bounty hunters at 1% of users. Shard-dominated (D55): gated end to end and on the
# shard path (§18 "shard path >= 80k events/s").
[workload]
name = "s2_pool"
project = "../examples/ecommerce_s2"
profile = "pool"
seed = 42
set = []

[workload.shape]
users = 2_000_000
exported_events = 10_000_000
campaign_member_share = 0.01
span = "30d"

[expect]
exported_events = { around = 10_000_000, tolerance = 0.05 }
campaign_member_share = { around = 0.01, tolerance = 0.002 }
shard_command_share = { at_least = 0.5 }         # shard-dominated: at least half the commands

[gate]
min_events_per_second = 80_000                  # end to end (§10 shard-dominated band)
min_shard_events_per_second = 80_000            # shard path: shard events / shard-phase s
threads = 16
reference = "16 cores / 64 GB"
```

Append to `examples/ecommerce_s2/datagen.toml`:
```toml
[profiles.full]                          # benchmarks/s2.toml; calibrated in Task 21
[profiles.full.set]
users = 20_000_000
skus = 100_000
sku_groups = 512
"journey.signup_delay.params" = [604_800_000_000.0, 0.0, 0.0]   # spread first sessions (S1 ruling)
"pay.dispute_window_days" = 90

[profiles.pool]                          # benchmarks/s2_pool.toml; calibrated in Task 21
span = "30d"
warmup = "3d"

[profiles.pool.set]
users = 2_000_000
skus = 20_000
sku_groups = 128
referred_share = 0.5
"hunt.share" = 0.01
"journey.views_mean" = 1.5
"journey.checkout_p" = 0.9
"journey.signup_delay.params" = [259_200_000_000.0, 0.0, 0.0]
# engine pools sized for 2M users (F-23; the base pools are sized for the 20M-user `full`
# profile, which keeps them): one tenth of the base values
"engine.timer_nodes" = 9_000_000
"engine.payload_slots" = 400_000
"engine.max_messages_per_step" = 800_000
"budget.max_admissions_per_step" = 200_000
```

- [ ] **Step 2: Write the failing tests**

`apps/datagen/tests/test_benchmark_s2.py`:
```python
import json
from pathlib import Path

from datagen.benchmark import derived, evaluate, load_workload
from datagen.cli import main

ROOT = Path(__file__).resolve().parents[3] / "benchmarks"
S2, POOL = ROOT / "s2.toml", ROOT / "s2_pool.toml"
GIB = 1024**3


def _stats(**kw):
    base = {"engine_seconds": 500.0, "peak_rss_bytes": 20 * GIB, "exported_events": 101_000_000,
            "events_per_second": 202_000.0, "shard_events_per_second": 120_000.0,
            "shard_phase_seconds": 250.0, "shard_events": 30_000_000,
            "proposals": 300_000_000, "commands": 400_000_000,
            "shard_command_share": 0.25, "requests_by_boundary": {"reserve": 9_000_000},
            "counts": {"payment_authorized": 29_000_000, "payment_declined": 900_000,
                       "checkout_started": 10_000_000},
            "accumulators": {"hot_checkouts": 500_000},
            "posting_counts": {"ledger": 150_000_000},
            "events_by_partition": {"payment": 60_000_000},
            "shard_load": {"inventory": {"requests": [450_000] + [10] * 511}},
            "populations": {"user": 2_000_000, "campaign": 5_000},
            "ids_allocated": {"member": 15_000},
            "threads": 16, "machine": {"arch": "x86_64", "cpus": 16, "ram_bytes": 64 * GIB}}
    return base | kw


def test_workloads_load():
    s2, pool = load_workload(S2), load_workload(POOL)
    assert s2.project.name == pool.project.name == "ecommerce_s2"
    assert (s2.profile, pool.profile) == ("full", "pool")
    assert s2.gate["warm_seconds"] == 600 and pool.gate["min_events_per_second"] == 80_000
    assert pool.gate["min_shard_events_per_second"] == 80_000


def test_derived_values():
    d = derived(_stats())
    assert d["payments"] == 29_900_000
    assert d["postings_per_payment_event"] == 2.5
    assert d["hot_share_of_checkouts"] == 0.05
    assert abs(d["hot_share_of_reserves"] - 450_000 / (450_000 + 5_110)) < 1e-12
    assert d["campaign_member_share"] == (5_000 + 15_000) / 2_000_000
    assert "payments" not in derived({"proposals": 1})           # S1 reports unchanged


def test_s2_gate():
    wl = load_workload(S2)
    ok = _stats()                                    # the reserve share is not an expectation
    assert evaluate(ok, wl, scale=1.0)["verdict"] == "pass"
    assert evaluate(ok | {"engine_seconds": 601.0}, wl, scale=1.0)["verdict"] == "fail"
    cold = evaluate(ok | {"accumulators": {"hot_checkouts": 700_000}}, wl, scale=1.0)
    c = next(c for c in cold["checks"] if c["name"] == "hot_share_of_checkouts")
    assert not c["ok"]                               # 0.07 is outside 0.05 ± 0.01


def test_pool_gate_and_at_least():
    wl = load_workload(POOL)
    ok = _stats(exported_events=10_100_000, events_per_second=90_000.0,
                shard_events_per_second=95_000.0, shard_command_share=0.6)
    r = evaluate(ok, wl, scale=1.0)
    assert r["verdict"] == "pass", r["checks"]
    assert evaluate(ok | {"events_per_second": 79_999.0}, wl, scale=1.0)["verdict"] == "fail"
    assert evaluate(ok | {"shard_events_per_second": 79_999.0}, wl,
                    scale=1.0)["verdict"] == "fail"
    low = evaluate(ok | {"shard_command_share": 0.45}, wl, scale=1.0)
    c = next(c for c in low["checks"] if c["name"] == "shard_command_share")
    assert not c["ok"] and c["limit"] == [0.5, None]


def test_s2_profiles_validate():
    from neorisk_simkit.spec.project import load_project, resolve_run
    from neorisk_simkit.spec.validate import validate
    for wl in (load_workload(S2), load_workload(POOL)):
        rep = validate(resolve_run(load_project(wl.project), wl.profile, []))
        assert rep.ok, (wl.name, rep.errors)


def test_pool_scaled_smoke_run(tmp_path):
    out = tmp_path / "report.json"
    assert main(["benchmark", str(POOL), "--scale", "0.001", "--threads", "4",
                 "--out", str(out)]) == 0
    rep = json.loads(out.read_text())
    assert rep["verdict"] == "skipped" and rep["exported_events"] > 0
    for k in ("shard_command_share", "shard_load", "campaign_member_share", "events_per_second",
              "shard_events_per_second", "hot_share_of_checkouts"):
        assert k in rep, k
```
In `apps/datagen/tests/test_example_ecom_s2.py`, `test_project_validates` iterates `("sample", "full", "pool")`.

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run --all-packages pytest apps/datagen/tests/test_benchmark_s2.py -v`
Expected: FAIL (`FileNotFoundError` for `benchmarks/s2.toml` before Step 1; then `KeyError: 'around'` from `evaluate` on `at_least`, and missing derived keys).

- [ ] **Step 4: Implement** the `benchmark.py` changes in Interfaces; `summary` prints `events/s` and `shard-phase events/s`, every derived value present, and `shard max share` per shard partition. If `test_s2_profiles_validate` fails on the budget, raise engine pools or `budget.memory` in the profile's `set` (never the workload shape), but never set `budget.memory` above `"64GB"` (the reference machine, F-24); the caps table checked includes all 11 items, `checker_state` and `entity_buffers` among them. Record the change in the commit body.

- [ ] **Step 5: Run tests, full suite, lint, commit**

Run: `uv run --all-packages pytest apps/datagen/tests/test_benchmark_s2.py apps/datagen/tests/test_benchmark_s1.py -v && uv run --all-packages pytest -q && uv run ruff check $(ls -d libs apps examples/ecommerce_s1 examples/ecommerce_s2 benchmarks 2>/dev/null)`
Expected: PASS; the S1 benchmark tests are unchanged.
```bash
git add benchmarks/s2.toml benchmarks/s2_pool.toml apps/datagen examples/ecommerce_s2
git commit -m "bench: S2 workloads, profiles, at_least/at_most expectations, rate gate

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 21: Calibrate and measure the S2 gates (and re-measure S1)

Measure honestly. The gate and the workload shape are fixed by spec §10/§18; only profile knobs (behavior rates, engine pools, budget) may change, and a failing measurement is reported, not hidden.

**Files:**
- Modify: `examples/ecommerce_s2/datagen.toml` (`full` and `pool` `set` tables only), `benchmarks/README.md` (S2 sections, calibration tables, results), `benchmarks/results/` (git-ignored JSON reports referenced by the README)

**Interfaces:**
- Consumes: Task 20 (`datagen benchmark`, workload files, derived values).
- Produces: calibrated `full` and `pool` profiles; `benchmarks/README.md` sections for `s2.toml` and `s2_pool.toml` with measured results; a re-measured S1 row (D41 and Tasks 1–5 changed engine code).

- [ ] **Step 1: Calibrate `pool` (the cheaper workload first)**

Run: `uv run --all-packages datagen benchmark benchmarks/s2_pool.toml --no-gate --out /tmp/s2pool-calib.json`
Tune only the `pool` profile's `set` (`journey.session_gap_min_h`, `journey.views_mean`, `journey.checkout_p`, `journey.add_to_cart_p`, `referred_share`, `pool_cap`, `hunt.zombies_mean`, engine pools) until `exported_events` is within 10⁷ ± 5%, `campaign_member_share` within 0.01 ± 0.002 and `shard_command_share ≥ 0.5` (D55/F-03: the workload must actually be shard-dominated; raise the shard work per owner command — more lines per cart, more checkouts and claims per session, fewer views — rather than relaxing the share). Set `pool_cap` so the pool drains in the second half of the span (normal users see rejections after hunters, the §07 interference). Record each calibration run (knobs → exported events, shares) in a README table.

- [ ] **Step 2: Calibrate `full`**

Run: `uv run --all-packages datagen benchmark benchmarks/s2.toml --no-gate --out /tmp/s2-calib.json` (expect tens of minutes for a cold compile plus the run; use `--scale 0.05` to iterate on rates, then confirm at scale 1).
Tune only the `full` profile's `set` (`journey.session_gap_min_h`, `journey.views_mean`, `journey.bill_gap`, `journey.checkout_p`, `journey.hot_pick_p`, `payments_live_ratio`, engine pools, budget) until `exported_events` ≈ 10⁸ ± 5%, `payments` ≈ 3·10⁷ ± 5%, `postings_per_payment_event` ≈ 2.5 ± 4% and `hot_share_of_checkouts` ≈ 0.05 ± 0.01 (F-02: calibrate `journey.hot_pick_p` against the checkout share; `hot_share_of_reserves` is recorded, not targeted). If `postings_per_payment_event` cannot reach 2.5 with behavior knobs alone, report it — do not change the pack's posting rules to hit a number. `budget.memory` may be raised in the profile up to `"64GB"` (the reference machine) and never above (F-24). If validation refuses the budget on this machine, report the caps table (`datagen validate examples/ecommerce_s2 --profile full`: all 11 items, `checker_state` and `entity_buffers` included) against the machine's RAM; do not shrink users or payments.

- [ ] **Step 3: Measure the gates**

Run, in order:
```
uv run --all-packages datagen benchmark benchmarks/s2_pool.toml --cold --out benchmarks/results/s2_pool-cold.json
uv run --all-packages datagen benchmark benchmarks/s2_pool.toml --out benchmarks/results/s2_pool-warm.json
uv run --all-packages datagen benchmark benchmarks/s2.toml --cold --out benchmarks/results/s2-cold.json
uv run --all-packages datagen benchmark benchmarks/s2.toml --out benchmarks/results/s2-warm.json
uv run --all-packages datagen benchmark benchmarks/s1.toml --out benchmarks/results/s1-warm-s2.json
```
Expected: verdicts as measured. `s2` gets its own `--cold` run (F-24): the `full` profile fixes `skus = 100_000`, which lowering may inline, so its module can differ from `pool`'s; the README records both cold compile times and both module hashes. The `s2_pool` verdict is `pass` only if both `events_per_second ≥ 80,000` and `shard_events_per_second ≥ 80,000` (with `shard_command_share ≥ 0.5`). `s1-warm-s2.json` re-measures S1 after D41 and the engine changes (its dataset hash changes once because step boundaries moved; its gate must still pass).

- [ ] **Step 4: Write the README sections**

`benchmarks/README.md` gains, for each S2 workload: what the file fixes (spec quote), the profile's calibrated knobs, the calibration table, the gate (for `s2_pool` both gates of D55 and why both), the counting window of every derived value (F-25: exported steps for `payments`, `postings_per_payment_event`, `hot_share_of_checkouts`, `shard_events_per_second`; the whole run, warm-up included, for `shard_command_share`, `hot_share_of_reserves`, `campaign_member_share`, `shard_load`), the caps table from `datagen validate` (all 11 items with `checker_state` and `entity_buffers`; `checker_state` carries about 28M payment keys per keyed law at S2 scale, F-22) against the machine's RAM, and a results table:

| Code | Date | Machine (cores / RAM) | Threads | Exported events | Payments / postings per payment event / hot share of checkouts (hot share of reserves) (s2) or member share / shard command share (s2_pool) | Warm s | events/s (end to end) | shard-phase events/s (shard events / shard-phase s) | Cold compile s (module hash) | Peak RSS GiB | generate / seal / check / write s | Rounds (total / compiled) | Max shard share | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|

and a new S1 row. Next to `campaign_member_share` the `s2_pool` section states the approximation (F-08, D52): "1% of users" is (campaigns + members) ÷ users, hunters being a campaign owner with zombie members rather than an overlay cohort of user rows (M3). Report numbers exactly as measured. For a `fail`, name the stage that misses its §10 band (generation 0.5–3M/s; merge, checks, export 0.25–2M/s each; shard-dominated end to end 80–300k/s; for `s2_pool`, which of the two D55 rates misses) and the hot shard's `max_share`, and leave the verdict `fail`: Task 22 then runs.

- [ ] **Step 5: Full suite, lint, commit**

Run: `uv run --all-packages pytest -q && uv run ruff check $(ls -d libs apps examples/ecommerce_s1 examples/ecommerce_s2 benchmarks 2>/dev/null)`
```bash
git add examples/ecommerce_s2/datagen.toml benchmarks/README.md
git commit -m "bench: S2 workloads calibrated and measured; S1 re-measured

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

### Task 22: Performance wave (only if a gate in Task 21 fails)

The S1 precedent (Task 24b): measure where time goes, change one lever at a time, keep only levers that are output-identical and faster, and re-measure the unchanged gate.

**Files:** as the chosen levers require (`engine/codegen.py`, `engine/rounds.py`, `io/seal.py`, `io/writer.py`, `checks/laws.py`); `benchmarks/README.md`.

**Interfaces:**
- Consumes: Task 21 reports (stage seconds, rounds, `shard_load`, `admissions_total`, `shard_phase_seconds`, `shard_events_per_second`).
- Produces: a passing re-measurement, or a documented `fail` with every lever tried and its measured effect.

- [ ] **Step 1: Capture the identity hashes before any change**

Run the reduced profiles and hash every file except `manifest.json` and `run_stats.json` (procedure of `.superpowers/sdd/2026-10-16-simulator-s1/task-24b-report.md`):
```
uv run --all-packages datagen run examples/ecommerce_s2 --profile pool --seed 42 --set users=200000 --set run.span=10d --out /tmp/s2p-ref --force
uv run --all-packages datagen run examples/ecommerce_s2 --profile full --seed 42 --set users=1000000 --set run.span=14d --out /tmp/s2f-ref --force
```

- [ ] **Step 2: Profile the failing workload** at its reduced profile (`python -m cProfile` for Python stages; for compiled stages, `stage_seconds`, `rounds_total`, `compiled_rounds_total` and native sampling as in S1 Task 24).

- [ ] **Step 3: Apply levers in this order, re-hashing after each** (a lever whose hashes differ is reverted, not adjusted):
  1. **Write in parallel by table** (§13: "Workers write different types in parallel"): `write_step` submits one table per thread-pool task; file bytes are unchanged because each file is written from the same table with the same options.
  2. **Seal conversions in parallel by table**: `event_table` per type on the pool (pure functions of their inputs).
  3. **Law evaluation by check in parallel**, or in numpy instead of polars for `never_negative`/`total_le`, if `stage_seconds.check` exceeds its §10 band.
  4. **Rounds**: tune `engine.parallel_min_partitions` in the profile (a profile knob, output-identical by the S1 compiled/Python round equivalence) and confirm `compiled_rounds_total / rounds_total`.
  5. **Hot shard**: if `shard_load.pool.max_share` (or inventory group 0) dominates the shard phase and `shard_events_per_second` (the D55 shard-path gate) misses, report the hot shard's share of shard-phase time; the pool is one loop by design (§19), so report it rather than split it.
  For each: one test pinning output identity (the reduced-profile hash in a test is too slow; instead compare `event_dicts` of a small run before and after inside the lever's unit test) plus the measured seconds.

- [ ] **Step 4: Re-measure** with the exact Task 21 commands and update the README results (keep the failing row as "before", add "after").

- [ ] **Step 5: Full suite, lint, commit** each kept lever separately:
```bash
git commit -m "perf(io): write step tables in parallel (output byte-identical)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BKddEJ7kY3XR8oXDK9HriN"
```

---

## Deferred

Every item S1 deferred to S2, with its fate; then new deferrals.

**S1 → S2 items**
- Payments with refunds and disputes → Tasks 13–14. Multi-SKU reservations through `std.reservations` with TTL expiry (`stock_expired`) and join / commit-all / release-all → Tasks 8, 12. Hot SKU group → Tasks 8, 12. Capped bonus pool (`std.capped_pool`) → Tasks 8, 15. `p.accumulator` → Task 7.
- Rounds at scale → Task 5 (compiled admission), Task 19 (round and shard accounting), Task 22 (levers). Parallel shard phases for hot shards: re-deferred to Later — a hot shard is one loop by design (§19) and cannot be split without merging state; the S2-pool workload measures it (Task 21).
- `max_spawn_depth` enforcement → Task 4 (static, D42).
- Spawn as a machine operation and `join` with timeout → re-deferred to M3: they are state-machine operations (§04); S2's join is the blocking N-response join (D50).
- Owner-to-owner messages at the next step boundary → re-deferred to M3 (D57: no S2 consumer; needs an owner-id → slot index; first consumer is the M3 overlay).
- Per-partition and cross-partition law reducers, `law.*` evaluation → Tasks 9–10. Request/response pairing → Task 2 (D40). Reference kernel tests → Task 16. Mutation tests → Task 17. Referential integrity → Task 11 (range check, D48).
- `cause_id` population (D14) → re-deferred to M3: it needs an event-id index that spans steps (a cause can lie any number of steps back, e.g. a 90-day timer), no S2 law reads it, and pairing is enforced without it (D40).
- `benchmarks/s2.toml` and `benchmarks/s2_pool.toml` → Tasks 20–21.
- Created-owner `partition_id` stability across step lengths (D12) → resolved by the controller's reading of §12 (D37): IDs and `partition_id`s of created owners are step-dependent and canonicalized in comparisons; values, including shard-side results of tied requests, are step-invariant through Task 4b (D61); pinned on the S2 slice by Task 18.
- S1 obligations from contracts/rulings: explicit response tagging → Task 2; seal remap of shard state, shard locals and payload column 9 → Task 1; step cap vs adaptation → Task 3 (D41); generate below its §10 band and single-threaded rounds → measured in Task 21, levers in Task 22; cold compile (~470 s for S1) → reported per workload in Task 21 (`--cold`), not gated (spec §10 times it separately); the create-row index made incremental in S1 (8f0d693) is deleted by Task 4 once created state rides the creation payload (D43); "kernels creating owners must also reserve requests (or `_reserve_` counts them)" → Task 4 (automatic); io constant consolidation → Task 6.

**New deferrals**
- **M3**: dispute (and other) child kernels started by `spawn` (D51); the bounty-hunter *overlay* with base-schema parity, cohorts, `suppress`, labels and the interference report (D52; S2 approximates "1% of users" by (campaigns + members) ÷ users, F-08); owner-to-owner messages (D57); per-process `max_spawn_depth` (§06, default 3) and a runtime spawn-depth counter that allows bounded recursion, with `spawn` (D42 is static and refuses every cycle, F-04); `law.sum_le` with a state column on the right side, as in the spec's example `law.sum_le("refund.amount", "payment.captured", by="payment_id")` (S2 takes event columns on both sides, F-07); request and join timeouts; statistical checks and `expectations.yaml`; `datagen check`, `report.html`, `checks.json`.
- **M4**: label delay on payments and `labels/`; a richer `std.ledger` (accounts as a declared chart, netting is out of scope per §09).
- **Later**: compiled law reducers by dense index initialized from opening snapshots (S2 evaluates laws in Python on sealed steps and builds their state from warm-up steps, F-01); dropping a law's keyed state for retired owners (§10 "dropped with the case"; S2 keeps `at_most_once` / `sum_le` keys for the whole run, about 28M payment keys per law at S2 scale against `max_checker_keys`, F-22); a referential-integrity bitset over dense indices (§11; S2 uses the exact range check, D48/F-05); `datagen export --single-file` for postings; replay of postings (§15 replays events only).

## Self-review notes (planner)

- **Spec coverage (§18 S2):** payments with refunds and disputes → Tasks 13–14; multi-SKU reservations with TTL → Tasks 8, 12; hot SKU group → Tasks 8, 12; capped bonus pool → Tasks 8, 15; rounds at scale → Tasks 5, 19, 22; cross-partition laws → Tasks 9–11; reference kernel tests → Task 16; mutation tests → Task 17; gates → Tasks 20–21 (and 22 if needed); invariance (§10 "Also verified") → Task 18.
- **Interfaces checked across tasks:** route tuple indices 22–27 (Tasks 2, 4b, 5); `PAY_KIND` (Tasks 2, 5); `CREATE_HEAD.lamport` (Tasks 4, 4b, 5); `SealedStep.postings` / `.accumulators` (Tasks 6, 7, 9, 11); `LawBook.report()` keys `checked/violations/censored/unmatched/first` (Tasks 9, 10, 12–17); `run_stats.json` keys used by `benchmark.derived` (Tasks 19, 20); S2 kernel command ids (Tasks 12–15).
- **Known risks during execution:** cold compile of the S2 module (more kernels than S1; first test run of Tasks 12–15 compiles for minutes); 20M users × 30M live payments against this machine's RAM (Task 21 reports caps vs RAM rather than shrinking); `postings_per_payment_event` is structural (2 postings per authorization, 3 per capture) and calibrates only through the event mix.

## Preflight amendments

Applied from `.superpowers/sdd/2026-10-17-simulator-s2/preflight.md` section C with the controller's rulings (`progress.md`); every proposed ruling is accepted except F-03, which the controller decided as "gate both". BASE moved to `f3a5582` (S1 Codex fix round landed).

| Finding | Ruling | Applied in |
|---|---|---|
| F-01 laws ignore warm-up state | warm-up steps feed `LawBook.step(exported=False)`: state built, nothing judged | D47; Task 9 (Files, Interfaces `tables` / `step(exported=)` / `seal_step(law_tables=)` / `SealedStep.warmup_rows`, Step 4 `Simulation` and `seal_step`, tests `test_warmup_rows_build_state_without_judging`, `test_a_key_seen_in_warmup_is_seen_before`); Task 10 (Interfaces warm-up rules and `unmatched`, tests `test_sum_le_counts_the_right_side_seen_in_warmup`, `test_a_close_of_a_warmup_opening_is_matched_not_judged`); Task 14 Step 4 note; Deferred (Later) |
| F-02 hot share measured on reserves | gate `hot_share_of_checkouts`; reserve share information only | D53, D56; Task 12 (brief, accumulator `hot_checkouts` in pack and `_checkout`, Interfaces, test `test_the_hot_group_takes_a_share_of_checkouts`); Task 19 (`accumulators` in `run_stats.json`); Task 20 (derived value, `s2.toml` expectation, tests); Task 21 Step 2 |
| F-03 s2_pool gate not the shard path | controller: gate BOTH end-to-end `events_per_second ≥ 80k` with `shard_command_share ≥ 0.5`, AND `shard_events_per_second ≥ 80k`; report both | Goal line; D55, D56; Engine reference (`RS_SHARD_NS`); Task 19 (`RoundStats.shard_ns`, `_now_ns`, `shard_phase_seconds`, `shard_events`, `shard_events_per_second`, test `test_shard_phase_rate_is_reported`); Task 20 (`min_shard_events_per_second`, `s2_pool.toml`, report fields, tests); Task 21 Steps 1, 3, 4; Task 22 lever 5 |
| F-04 static spawn bounds narrow §06 | accept, deviation note | D42; Deferred (M3) |
| F-05 range check weaker for populations | accept; bound population refs by `pop.next` | D48; Task 11 (Interfaces `ref_bounds`, test `test_population_refs_are_bounded_by_admitted_owners`); Deferred (Later) |
| F-06 pairing failures lack the §11 citation | append `(partition_id, seq), action` | Task 2 (Interfaces, Step 4 call sites and `_unpaired`, test `test_unpaired_answers_cite_partition_seq_and_action`, count 8) |
| F-07 `sum_le` event columns only | accept for S2 | D47; Deferred (M3) |
| F-08 dispute, hunters, owner messages approximated | accept; state the approximation in the S2-pool report | D52; Task 21 Step 4; Deferred (M3) |
| F-09 `canonicalize_ids` signature / test imports a test | move helpers to `conftest.py` with the landed signature; never weaken | D37; File structure; Task 18 (Files, Interfaces with the real comparison semantics, new Step 0, imports, `created_owner_codes`, step-length test with `owner_codes`, Step 2 ambiguity rule, `git add`) |
| F-10 partial admission not retry-safe | all-or-nothing node check; `k` computed by `route_outbox`, stored in `CQ`; forced-`ADM_NODES` identity test | D44; Engine reference (`CQ.k`, `ADM_NODES`); Task 5 (Interfaces `CreationQueue`, `route_outbox`, `admit_created`, `World.admit_created`; Step 4 items 2–5; Step 5 `route_outbox` and `_python_round`; test `test_admission_short_of_nodes_admits_nothing_and_retries_identically`) |
| F-11 retire/reuse test cannot pass | test config: `pay.auth_expiry_s=7200`, bills every 2 days | Task 13 test `test_payments_retire_after_their_window_and_slots_are_reused` |
| F-12 admission order and D44 signature | Step 4 and the 6-argument form win | D44; Task 5 Interfaces |
| F-13 D41 names Task 22 | Task 21 | D41 |
| F-14 D61 key has 5 parts | `(ptype, 0, pid, 0, 0, 0)` | D61 |
| F-15 route-order test keeps `src_g = 0` | distinct senders from a mini World; file listed | Task 4b (Files, Step 4 replacement test) |
| F-16 payments block placement contradicts itself | after the user events | Task 13 Step 1 |
| F-17 frozen dataclass defaults; Files | `field(default_factory=dict)`; list `io/replay/*`, `io/consts.py` | Task 6 (Files, Interfaces); Task 7 Interfaces; File structure |
| F-18 two `emit_spawned` sites | knob at both | Task 11 Step 1 |
| F-19 "two places" | only `test_engine_rounds.py:167` | Task 5 Files and test note |
| F-20 inaccurate expected failures | reworded | Task 4 Step 3 and Step 5; Task 12 Step 3 |
| F-21 Review Focus cases without pins | empty run; same-shard lines; simultaneous claims at the cap | Review Focus #5; Task 7 `test_an_empty_run_writes_zeros`; Task 9 `test_an_empty_run_checks_nothing`; Task 12 `test_two_lines_of_one_cart_can_share_a_shard`; Task 17 `test_simultaneous_claims_at_the_cap_grant_exactly_one` (count 10) |
| F-22 checker keys at S2 scale | report `checker_state` in the caps table; Deferred dropping retired keys | Task 9 Interfaces; Task 21 Steps 2, 4; Deferred (Later) |
| F-23 smoke run allocates base pools | `pool` profile sizes its own pools for 2M users | Task 20 Interfaces and `[profiles.pool.set]` |
| F-24 memory without ceiling; no s2 `--cold` | `budget.memory ≤ 64GB`; run `s2 --cold` too | Task 20 Step 4; Task 21 Steps 2, 3, 4 |
| F-25 mixed counting windows | same window per derived value, stated in the README | D56; Task 19 Interfaces (`ids_allocated`, windows); Task 20 derived values; Task 21 Step 4 |

Controller items beyond section C:
- S1 contracts changed (CX1): created owners take §12 prefix-sum dense IDs again (`seal._owner_dense` gone), nested same-step creators rank by provisional handle → D37 (BASE `f3a5582`, assumptions removed), Task 4 Interfaces and Step 4 (no `seal` change; stale "whichever exist" and `_owner_dense` text removed).
- Creation messages counted automatically in `_reserve_` / `requests` → D43, Engine reference "Reservations", Task 4 (intro, Files, Interfaces, validate outbox-fit error, codegen `reserve(p)` change, tests `test_creation_messages_count_toward_the_outbox` and `test_creates_reserve_their_creation_messages`); kernels no longer add the unit by hand: `chain` (Task 4), `relay` `acct_main` (Task 4b), shopper `requests=CART` / `_bill` (Task 13), `CART + 1` (Task 15); Deferred S1 items.
- S1's incremental created-row index (`created_rows_indexed`, 8f0d693) → deleted in Task 4 with `test_admission_indexes_each_created_row_once` rewritten as `test_admission_reads_creation_payloads_in_many_small_batches`; Task 5 replaces that with `test_many_small_admission_batches_stay_compiled` (compiled admission is invisible to a `World.admit_created` spy).
- New cap item `entity_buffers` → Global Constraints memory items; Task 9 Interfaces (caps keep all 11 items); Task 20 Step 4 and Task 21 Steps 2, 4 (caps tables). Task 1's `live_partition_state` test is unaffected (the entity writer is charged to `entity_buffers`, preflight P5).
