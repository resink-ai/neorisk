# Benchmarks

A workload file is an ordinary run of a project and profile, plus the numbers it must hit.
`datagen benchmark` runs it and checks those numbers.

```
uv run --all-packages datagen benchmark benchmarks/s1.toml            # warm gate
uv run --all-packages datagen benchmark benchmarks/s1.toml --cold     # time the compile from empty caches
uv run --all-packages datagen benchmark benchmarks/s1.toml --scale 0.01 --threads 4   # smoke, verdict "skipped"
```

Options: `--scale X` (users × X, nothing else changes; the verdict is `skipped` unless X = 1),
`--cold` (fresh `NEORISK_JIT_CACHE` and `NUMBA_CACHE_DIR`), `--threads N` (default
`min(gate.threads, cores)`, D30), `--out FILE` (default `benchmarks/results/<name>-<utc>.json`,
git-ignored), `--no-gate` (exit 0 even when the gate fails). Exit codes: 0 pass or skipped,
1 gate failed or internal error, and the run's own code when it fails (2 validation, 3
`CapExceeded`; D35).

How a run is measured:

1. **Compile run.** A subprocess runs the same plan shape at `users=1000`, one day, no warm-up.
   Its wall time is `cold_compile_seconds` (a real cold compile only with `--cold`; otherwise
   it is whatever the caches hold).
2. **Warm run.** A second subprocess (`python -m datagen.benchmark --child`) runs the workload
   with the same caches and asserts that it imports the same generated engine module as the
   compile run, so nothing population-dependent was inlined by codegen. `NUMBA_NUM_THREADS=1`,
   `POLARS_MAX_THREADS=<threads>`.
3. **Report.** The child's `run_stats.json` gives `engine_seconds` (from `run_to_dataset` entry to
   `manifest.json` written), `stage_seconds` (build, generate, seal, write), `exported_events`,
   `events_per_second`, `peak_rss_bytes` (the child's own `ru_maxrss`; the gate and the report
   use GiB, 2³⁰ bytes), `proposals` (owner
   commands executed, retries excluded), `requests_by_boundary`, `rounds_per_step`, `threads`
   and `machine`. The report adds `inventory_share_of_proposals = requests_by_boundary.reserve /
   proposals`, the checks and the verdict.

Expectations are `{ around, tolerance }`: a count (`around > 1`) has a relative tolerance
(10⁷ ± 5%), a share (`around ≤ 1`) an absolute one (0.08 ± 0.02). `{ at_least = x }` and
`{ at_most = x }` are one-sided (D56). Gates add `min_events_per_second` and
`min_shard_events_per_second` (lower limits).

## `s1.toml`

Fixes the S1 shape of spec §10: `examples/ecommerce_s1`, profile `full`, seed 42 — 2M users,
90 days (plus the project's 14-day warm-up), ~10⁷ exported events, 12 property columns on
`product_viewed` (~120 B/row), one typed change group (`user_kyc`), Pareto session gaps with
α = 1.2, ~8% of owner commands touching the inventory shards (reserve requests).

The `full` profile in `examples/ecommerce_s1/datagen.toml` carries the calibrated journey:
`session_gap_min_h = 2300`, `views_mean = 4`, `add_to_cart_p = 0.4`, `checkout_p = 0.85`, and
`signup_delay` = exponential with a one-week mean, so the 1.2M initial shoppers' first sessions
spread over the warm-up instead of landing in the first step (with the pack's one-hour default
the first step needs ~14M rows against `budget.max_step_rows = 4M` and the run stops with
`CapExceeded: step_output`). The pack defaults stay as they are for the `sample` profile, whose
tests bound checkouts per session below 0.30; the 8% share needs ~0.6.

Calibration runs (2M users, full span):

| session_gap_min_h | exported events | inventory share |
|---|---|---|
| 2000 | 11,737,926 | 0.0783 |
| 2250 | 10,256,562 | 0.0776 |
| 2300 | 10,022,123 | 0.0774 |
| 2400 | 9,657,514 | 0.0773 |
| 2500 | 9,518,714 | 0.0772 |

**Gate (spec §10, §18):** ≤ 60 s warm and peak RSS ≤ 16 GiB (`peak_rss_gb = 16`, compared in
GiB) on the reference machine, 16 cores / 64 GB, with Numba plus Polars threads capped at 16.

## Results

| Code | Date | Machine (cores / RAM) | Threads | Exported events | Warm s | Cold compile s | Peak RSS GiB | generate / seal / write s | Rounds per step (max) | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| before (f8d9f14) | 2026-10-17 UTC | arm64 14 / 36 GiB (not reference) | 14 | 10,022,123 | 116.67 | 509.18 | 2.77 | 109.14 / 4.38 / 2.38 | 96,955 | **fail** |
| after (task 24b) | 2026-10-17 UTC | arm64 14 / 36 GiB (not reference) | 14 | 10,022,123 | 43.97 | 471.80 | 2.78 | 36.41 / 4.41 / 2.39 | 96,955 | **pass** |
| task 24c (6e352b4) | 2026-10-17 UTC | arm64 14 / 36 GiB (not reference) | 14 | 10,022,123 | 45.1 | — | 2.52 | — | — | **pass** |
| S2 task 21 (`results/s1-warm-s2.json`) | 2026-10-18 UTC | arm64 14 / 36 GiB (not reference) | 14 | 10,022,123 | 54.90 | 1.28 (warm cache) | 2.73 | 47.14 / 4.49 / 2.86 | 96,955 | **pass** |

The S2 task 21 row re-measures S1 after D41 and the S2 engine changes; see "S1 re-measure"
under the S2 results below.

The task 24c row is a plain `datagen run --profile full --seed 42` (not the harness, so no cold
compile, stage split or round counts) after entity tables were streamed per step: engine
seconds 45.1, peak RSS 2.52 GiB (was 2.78), dataset hash unchanged.

The "after" row reads `results/s1-warm.json` (warm run) and `results/s1-cold.json` (`--cold`; its
own measured run took 44.47 s, peak RSS 2.74 GiB). Both runs: 28 steps, 1,388,003 rounds,
19,247,347 proposals, 1,490,629 reserve requests (share 0.0774), 228k events/s end to end. The
dataset is byte-identical to the f8d9f14 run (seed 42; sha256 over every data file, manifest and
`run_stats.json` excluded).

**The gate passes** on this (non-reference) machine: 44.0 s warm against 60 s, 2.8 GiB against
16 GiB.

What changed: the generated module inlines the lowered kernels and every generated helper
(`_emit_*`, `_rng_*`, `_timer`, `_request_*`, ...) into `dispatch` at the Numba IR level
(`inline='always'`). Before, each of those calls took the whole `out` slab tuple and `ctx` (hundreds
of arrays) by value, and Numba increfed and decrefed every array on every call: an owner command
cost ~10 µs, nearly all in NRT refcounting. Generate went from 109 s to 36 s.

Tried and not kept (no measurable gain, same output): a tail pointer for the command queues
(O(1) in-order appends; ±1 s, within noise or slightly slower), and inlining the queue and routing
helpers (`q_push`, `mark_touched`, heap operations). Inlining `dispatch` into `run_partitions` was
abandoned: cold compile went past 30 minutes.

Generate alone runs at ~275k events/s, still under the §10 band of 0.5–3M/s; seal and write
are inside theirs. What is left in generate (36 s): ~1.39M rounds per run, up to 97k per step, almost all in the
single-threaded compiled `drain_small_rounds` loop (D4). Each checkout's reserve request opens its
own 150 ms window, so rounds track distinct request windows. Each command still makes one real
call to `dispatch` with the `out` and `ctx` tuples. Reducing the round count (only with
output-identical horizon changes) or the per-command dispatch call are the next levers.

### Before (f8d9f14)

Read from `results/s1-warm.json` and `results/s1-cold.json` of that commit (the cold run's own
measured run took 117.84 s, peak RSS 2.88 GiB). Both runs: 28 steps, 1,388,003 rounds,
19,247,347 proposals, 1,490,629 reserve requests (share 0.0774).

The gate failed on time: 116.7 s against 60 s, 85.9k events/s end to end against the ≥ 167k/s
owner-dominated band. The stage that missed its §10 band was **generate**: 109 s for 10⁷ events,
92k events/s against 0.5–3M/s. Profiling put the generate time in small rounds (above) and in
per-command refcounting in the generated module: `_emit_product_viewed` compiled to ~1,800
indirect (refcount) calls, `_view` to ~8,100.

## Derived values and their counting windows (S2, D56, F-25)

`datagen benchmark` derives these from `run_stats.json`. Numerator and denominator of each
come from the same window.

| Value | Definition | Window |
|---|---|---|
| `payments` | `payment_authorized + payment_declined` | exported steps |
| `postings_per_payment_event` | `ledger` postings ÷ events emitted by `payment` partitions | exported steps |
| `hot_share_of_checkouts` | accumulator `hot_checkouts` ÷ `checkout_started` (F-02) | exported steps |
| `shard_events_per_second` | events emitted by shard partitions ÷ seconds in shard phases | exported steps |
| `shard_command_share` | shard commands ÷ all commands (rejects included, retries not) | whole run, warm-up included |
| `hot_share_of_reserves` | reserve requests to inventory group 0 ÷ all reserve requests (information only) | whole run, warm-up included |
| `campaign_member_share` | (campaigns + members) ÷ users | whole run, warm-up included |
| `shard_load` | commands and requests per shard, `max_share` of the busiest | whole run, warm-up included |

The engine's own counters: `commands` counts every executed command, rejects included and
retries excluded; a shard command is one a shard partition executes (requests, messages, its
timers and restock sub-steps). `proposals` = commands − shard commands.

## `s2.toml`

Fixes the S2 shape of spec §10: "S2: 20M users, 30M payments, 10⁸ exported events, 2.5
postings per payment event, 90-day dispute timers, one hot SKU group taking 5% of checkouts."
It runs `examples/ecommerce_s2`, profile `full`, seed 42: 90 days plus the project's 14-day
warm-up (D59), `skus = 100_000` in 512 inventory groups, `pay.dispute_window_days = 90`.
Expectations: `exported_events` 10⁸ ± 5%, `payments` 3·10⁷ ± 5%, `postings_per_payment_event`
2.5 ± 4% (2.4–2.6), `hot_share_of_checkouts` 0.05 ± 0.01 (F-02).

**Gate (spec §18):** "s2.toml ≤ 10 min warm" — `warm_seconds = 600` at 16 threads on the
16-core / 64 GB reference machine.

### Calibrated knobs (`[profiles.full.set]`)

| Knob | Pack default | Calibrated | Why |
|---|---|---|---|
| `journey.session_gap_min_h` | 30 | 5000 | one session per shopper in the 104-day run |
| `journey.views_mean` | 4 | 1 | one view per session (geometric, so exactly 1) |
| `journey.checkout_p` | 0.5 | 0.2 | few checkouts: each costs ~7 events per payment |
| `journey.hot_pick_p` | 0.05 | 0.05 | single-line carts, so the checkout share ≈ the pick share |
| `journey.bill_gap` | exp, mean 20 d | exp, mean 50 d | 30M exported payments, nearly all bills |
| `payments_live_ratio` | 1.5 | 1.8 | 1.69 payments per user over the run, every one live to its end |
| `budget.max_checker_keys` | 60M (project) | 80M | the keyed laws peak at 62–70M keys at 20M users |
| `budget.memory` | 32GB (project) | 40GB | the caps total 32.5 GiB; ≤ 64GB (F-24) |

Engine pools keep the project's base values (sized for 20M users).

### Calibration (`--scale 0.05`, 1M users)

The scale-1 estimate is ×20 (payments and events per user do not depend on the user count
here; restock events, 12k per run, do not scale and are under 0.3% of the total).

| Run | Knobs (besides the fixed ones above) | Exported events (×20) | Payments (×20) | Postings / payment event | Hot share of checkouts (of reserves) |
|---|---|---|---|---|---|
| Task 20, uncalibrated | pack defaults, ratio 2.5 | — (`CapExceeded` on payments at scale 0.001: 6.2 payments per user) | — | — | — |
| fA | views 1, gap 5000 h, checkout 0.2, hot 0.05, bill 45 d, ratio 3 | 6,463,939 (129.3M) | 1,658,109 (33.2M) | 2.374 | 0.0497 (0.0485) |
| fB | as fA, bill 60 d | 5,215,765 (104.3M) | 1,248,451 (25.0M) | 2.374 | 0.0499 (0.0487) |
| **final** | as fA, bill 50 d, ratio 1.8 | **5,965,504 (119.3M)** | **1,494,461 (29.9M)** | **2.374** | **0.0498 (0.0486)** |
| keys 2M / 3M | final, `max_checker_keys` 2M / 3M | `CapExceeded: checker_state` (2.17M / 3.10M keys attempted) | | | |
| keys 3.5M / 4M | final, `max_checker_keys` 3.5M / 4M | runs through: the peak is 3.10–3.5M keys at 1M users | | | |

**Two expectations cannot be met by the profile's knobs, and are reported as such:**

- `exported_events` and `payments` together. Each bill payment exports ~3.07 events
  (`bill_payment_started`, `payment_authorized` or `_declined`, `payment_captured` or
  `_expired`, refunds and disputes), so 30M payments are ~90.7M events by themselves. Every
  shopper also has at least one session with at least one view (the shopper's `START` always
  schedules a session, and `views` is geometric ≥ 1), and every arrival in the exported window
  exports `user_signed_up`: ~7.0M sign-ups plus ~8.5M sessions × 2 events at 20M users. The
  floor is therefore ~115M events at 30M payments, and ~110M even at the payment band's lower
  edge (28.5M), against the band's 105M. The calibration keeps payments on target (users and
  payments are never shrunk) and drives everything else to its floor: ~119M events, +19%.
- `postings_per_payment_event` = 2.374 against 2.4–2.6. Authorization (2 postings) plus
  capture (3) is exactly 2.5 per event; declines (0 postings), refund requests (0), failed
  refunds (0), replays (0) and expiries (2) pull it down. Those rates are `pay.*` lifecycle
  values, not journey knobs, and the posting rules stay as they are (brief): reported, not
  tuned.

`hot_share_of_checkouts` lands inside its band (0.0498).

### Caps (`datagen validate examples/ecommerce_s2 --profile full`) against this machine

| Item | Hard cap MiB |
|---|---|
| output_slabs | 3,008.0 |
| step_output | 385.3 |
| merge_working_space | 770.6 |
| live_partition_state | 17,208.5 |
| timer_heaps | 6,351.5 |
| requests_and_inboxes | 2,090.5 |
| fanout_bursts | 0.0 |
| read_inputs | 1,453.0 |
| checker_state | 1,831.1 |
| scorer | 0.0 |
| entity_buffers | 141.6 |
| **total** | **33,240.1 (32.5 GiB)** |

Validation passes against the profile's `40GB` budget. `checker_state` is
`max_checker_keys` × 24 B: one key per payment for each keyed law (`one_capture`,
`refunds_le_captured`), about 28M payment keys per keyed law at S2 scale (F-22), measured at a
62–70M-key peak in total. `live_partition_state` is 20M users plus 36M payment slots.

This machine has 36 GiB of RAM (14 cores), below the 64 GB reference. 32.5 GiB of hard caps
plus the interpreter, Numba and Polars cannot run without swapping, and a swapping run
measures the disk, not the engine. **So the scale-1 `s2` run was not attempted here**
(controller ruling): the `s2` verdict is **not measured — needs the 64 GB reference machine**.
The scaled runs below measure the same module and the same per-user shape at 1M users.

## `s2_pool.toml`

Fixes the S2-pool shape of spec §10: "S2-pool: a global capped bonus pool that every referral
claim reaches, with the bounty-hunter overlay at 1% of users." It runs `examples/ecommerce_s2`,
profile `pool`, seed 42: 2M users, 30 days plus a 3-day warm-up (D59), ~10⁷ exported events,
20,000 SKUs in 128 inventory groups, one `pool` shard (n = 1, so every claim runs in the pool's
own heap and the cap is exact, §07). Expectations: `exported_events` 10⁷ ± 5%,
`campaign_member_share` 0.01 ± 0.002, `shard_command_share` ≥ 0.5.

`campaign_member_share` approximates "1% of users" (F-08, D52): "1% of users" is (campaigns +
members) ÷ users, hunters being a campaign owner with zombie members rather than an overlay
cohort of user rows (M3).

**Gate (spec §18 "s2_pool.toml shard path ≥ 80k events/s", D55/F-03): two gates, both
required.**

1. `min_events_per_second = 80_000`: exported events ÷ warm `engine_seconds`, the §10
   "shard-dominated, end to end" band (80–300k/s). It reads as a shard-path rate only if the
   workload is shard-dominated, hence the expectation `shard_command_share ≥ 0.5`.
2. `min_shard_events_per_second = 80_000`: events emitted by shard partitions in exported
   steps ÷ the seconds spent in shard phases of exported steps (compiled drain and Python
   rounds, Task 19). This is §18's "shard path" read literally.

Each reading of the spec alone could pass a workload the other fails, so both are gated; neither
is relaxed. The verdict is `pass` only if both rates are ≥ 80,000 and every expectation holds.

### Calibrated knobs (`[profiles.pool.set]`)

| Knob | Task 20 value | Calibrated | Why |
|---|---|---|---|
| `journey.session_gap_min_h` | 30 (pack) | 2000 | one session per shopper in the 33-day run |
| `journey.views_mean` | 1.5 | 1.5 | |
| `journey.add_to_cart_p` | 0.25 (pack) | 1.0 | every view adds a cart line (shard work per view) |
| `journey.checkout_p` | 0.9 | 0.5 | sets the volume: 10⁷ exported events |
| `journey.bill_gap` | exp, mean 20 d (pack) | exp, mean 10 years | bills are owner-only work (see below) |
| `referred_share` | 0.5 | 0.05 | normal users' claims ~1 : 2.7 against the hunters' |
| `pool_cap` | 2,000,000 (pack) | 17,000,000 | the pool drains on day 20.6 of 30 |
| `hunt.zombies_mean` | 12 (pack) | 12 | member share 0.0095 already in band |
| `payments_live_ratio` | 4 | 0.5 | 0.105 payments per user over the run |
| `engine.payload_slots` | 400,000 | 2,000,000 | 640,648 payload rows in flight at 2M users |
| `engine.max_messages_per_step` | 800,000 | 2,000,000 | > 800k messages in a step at 2M users |
| `engine.step` | 1d (project) | 6h | the warm-up starts with 1.2M shoppers; 1-day steps overflowed `max_step_rows` |

`engine.timer_nodes` (9M) and `budget.max_admissions_per_step` (200k) are unchanged.
`journey.bill_gap` is not in the brief's list of pool knobs. It is a behavior rate of the
profile (the rule allows only those, engine pools and budget), and it is needed: with the
pack's 20-day gap, bill payments alone would be ~7M of the 10⁷ exported events, each costing
four owner commands and no shard command.

### Calibration

| Run | Scale (users) | Knobs (changes) | Exported events (at 2M) | Shard command share | Member share | Notes |
|---|---|---|---|---|---|---|
| Task 20 profile | 0.1 (200k) | — | 7,126,488 (~71M) | 0.1133 | 0.0095 | pool drained in the warm-up: no exported grant |
| pA | 0.1 | bill 10 y, views 4, add 1, checkout 1, referred 1, gap 300 h | 4,677,163 | 0.3187 | 0.0095 | |
| pB | 0.1 | pA, views 5 | 5,030,497 | 0.3150 | 0.0095 | |
| pC | 0.1 | pA, views 3 | 4,259,046 | 0.3177 | 0.0095 | |
| pE | 0.1 | pA, gap 2000 h | 2,496,973 | 0.3182 | 0.0095 | 61% of reserves out of stock |
| pF | 0.1 | pE, views 2, referred 0.05 | 1,930,241 | 0.2999 | 0.0095 | |
| pG | 0.1 | pF, views 1.5 | 1,737,426 | 0.2827 | 0.0095 | |
| pH | 0.1 | pF, views 2.5 | 2,092,212 | 0.3090 | 0.0095 | |
| pF1 | 1 (2M) | pF | — | — | — | `CapExceeded: requests_and_inboxes` (640,648 payload rows against 400k; with 2M payload rows, 800,002 messages against 800k) |
| pG1 | 1 | pG, payload 2M | — | — | — | `CapExceeded: step_output` (4,064,974 rows in one step, 1-day steps) |
| pF1 | 1 | pF, payload 2M, messages 2M, step 6 h | 19,716,567 | 0.2667 | 0.0095 | |
| pG1 | 1 | pG, same pools | 17,989,532 | 0.2533 | 0.0095 | |
| pK1 | 1 | views 1, checkout 0.7 | 10,841,683 | 0.1828 | 0.0095 | |
| pL1 | 1 | views 2.5, checkout 0.4 | — | — | — | `CapExceeded: step_output` (4.21M rows) |
| pJ1 | 1 | views 1.5, checkout 0.3 | 7,882,323 | 0.1214 | 0.0095 | |
| **pI1 = final** | 1 | views 1.5, checkout 0.5, pool_cap 17M, ratio 0.5 | **9,966,583** | **0.1708** | **0.0095** | |

`pool_cap` comes from a run with an unbounded pool: 21,383 claims of $10 over the run, 6,563 of
them in the warm-up; 17,000 claims' worth ($170,000) runs out on the 21st exported day.

**`shard_command_share ≥ 0.5` cannot be reached with the profile's knobs.** In the slice's
shopper, every cart line costs two owner commands (the view that adds it and the reserve
response) and at most three shard commands (the reserve, then the commit or release and the
hold's TTL timer, both only if the line was granted). Each checkout adds about six owner
commands of its own (the session, the view that ends it, the checkout timer, and the payment's
authorization, capture and expiry timer). With the cart's four lines (`kernels.CART`) all
granted, the share is at most 3·4 ÷ (5·4 + 6) = 0.46. At 2M users the zipf head of the 20,000
SKUs is out of stock between weekly restocks, so only ~25% of reserves are granted, and the
measured share tops out at 0.27 (pF1, at twice the event target). At the workload's 10⁷ events
it is 0.17–0.18. The brief's levers (more lines per cart, more checkouts and claims per session)
are kernel shape: `CART`, one checkout per session, one claim per referred shopper. Raising them
is a pack change, outside this task's files (`full` and `pool` `set` tables only). The
expectation stays `≥ 0.5`, and the verdict is `fail`.

### Pool interference (§07), final profile, exported days

| Source | Granted | Rejected | First rejection |
|---|---|---|---|
| normal users (`claim`) | 3,037 | 999 | 2026-01-21 15:31:23 UTC |
| hunters (`campaign_claim`) | 7,400 | 3,384 | 2026-01-21 15:34:19 UTC |

The last grant (2026-01-21 15:28:49, `remaining_after = 0`) went to a hunter, on day 20.6 of 30
exported days. Hunters take 71% of the exported grants, and every normal user who claims after
that is rejected: 999 normal referrals lose their bonus to the hunters.

### Caps (`datagen validate examples/ecommerce_s2 --profile pool`)

| Item | Hard cap MiB |
|---|---|
| output_slabs | 3,008.0 |
| step_output | 385.3 |
| merge_working_space | 770.6 |
| live_partition_state | 964.8 |
| timer_heaps | 635.1 |
| requests_and_inboxes | 575.3 |
| fanout_bursts | 0.0 |
| read_inputs | 145.6 |
| checker_state | 1,373.3 |
| scorer | 0.0 |
| entity_buffers | 108.5 |
| **total** | **7,966.5 (7.8 GiB)** |

Against this machine's 36 GiB and the project's 32GB budget. `checker_state` is the project's
60M keys × 24 B; the pool run's 0.13M payments need a small fraction of it.

## Results (S2 workloads and the S1 re-measure)

All rows: arm64, 14 cores / 36 GiB (not the reference machine), 14 threads
(`min(16, cores)`, D30), seed 42, BASE 8cfffbd plus this task's profiles. Reports in
`results/` (git-ignored). Every S2 run imports the same engine module, `gen_4ca683764e6339a0`:
the `full` profile's `skus = 100_000` is not inlined, so `s2` and `s2_pool` share it (F-24's
concern does not materialize), and each `--cold` run compiled it from empty caches.

| Code | Date | Machine (cores / RAM) | Threads | Exported events | Payments / postings per payment event / hot share of checkouts (hot share of reserves) (s2) or member share / shard command share (s2_pool) | Warm s | events/s (end to end) | shard-phase events/s (shard events / shard-phase s) | Cold compile s (module hash) | Peak RSS GiB | generate / seal / check / write s | Rounds (total / compiled) | Max shard share | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| s2_pool cold (`s2_pool-cold.json`) | 2026-10-18 UTC | arm64 14 / 36 GiB (not reference) | 14 | 9,966,583 | 0.0095 / 0.1708 | 90.06 | 110,667 | 95,629 (1,525,466 / 15.95) | 4,026.27 (gen_4ca683764e6339a0) | 3.52 | 81.78 / 4.71 / 0.58 / 2.52 | 1,222,197 / 1,222,150 | inventory 0.1176 of 128; pool 1.0 of 1 | **fail** (`shard_command_share`) |
| s2_pool warm (`s2_pool-warm.json`) | 2026-10-18 UTC | arm64 14 / 36 GiB (not reference) | 14 | 9,966,583 | 0.0095 / 0.1708 | 89.82 | 110,956 | 95,433 (1,525,466 / 15.98) | 1.59 (warm cache; gen_4ca683764e6339a0) | 3.51 | 81.56 / 4.71 / 0.58 / 2.51 | 1,222,197 / 1,222,150 | inventory 0.1176 of 128; pool 1.0 of 1 | **fail** (`shard_command_share`) |
| s2 cold, scale 0.05 (`s2-cold-scale0.05.json`) | 2026-10-18 UTC | arm64 14 / 36 GiB (not reference) | 14 | 5,965,504 (1M users) | 1,494,461 / 2.3737 / 0.0498 (0.0486) | 25.33 | 235,525 | 72,946 (59,200 / 0.81) | 3,981.34 (gen_4ca683764e6339a0) | 3.74 | 12.98 / 6.33 / 3.02 / 2.60 | 94,440 / 94,398 | inventory 0.0656 of 512; pool 1.0 of 1 | skipped (scale 0.05) |
| s2 warm, scale 0.05 (`s2-warm-scale0.05.json`) | 2026-10-18 UTC | arm64 14 / 36 GiB (not reference) | 14 | 5,965,504 (1M users) | 1,494,461 / 2.3737 / 0.0498 (0.0486) | 25.15 | 237,168 | 72,050 (59,200 / 0.82) | 1.62 (warm cache; gen_4ca683764e6339a0) | 3.74 | 12.78 / 6.34 / 3.03 / 2.61 | 94,440 / 94,398 | inventory 0.0656 of 512; pool 1.0 of 1 | skipped (scale 0.05) |
| s2 at scale 1 | — | — | — | — | — | — | — | — | — | — | — | — | — | **not measured — needs the 64 GB reference machine** (caps 32.5 GiB) |
| S1 re-measure (`s1-warm-s2.json`) | 2026-10-18 UTC | arm64 14 / 36 GiB (not reference) | 14 | 10,022,123 | — (inventory share of proposals 0.0774) | 54.90 | 182,550 | 191,706 (1,060,936 / 5.53) | 1.28 (warm cache; gen_782c5b94e9346bb8) | 2.73 | 47.14 / 4.49 / 0.00 / 2.86 | 1,388,004 / 1,387,972 | inventory 0.0942 of 512 | **pass** |

The two `--cold` compile times are the same module compiled twice from empty caches
(4,026 s and 3,981 s, ~67 min); the compile run itself is the small shape (1,000 users, one
day), so they time compilation.

### `s2_pool`: fail

Both D55 rates pass on this machine: 110,956 events/s end to end and 95,433 shard-phase
events/s, each against 80,000. The verdict is `fail` on the expectation
`shard_command_share ≥ 0.5`: 0.1708, because the workload is not shard-dominated (see the
`s2_pool.toml` section: a kernel-shape limit of 0.46, measured 0.17 at 10⁷ events). So the
end-to-end rate is not yet a shard-path rate, and the gate is not met. By stage: generate runs at
122k events/s (9.97M in 81.56 s), under §10's generation band of 0.5–3M/s; seal (2.1M/s), checks
(17M/s) and export (4.0M/s) are at or above their 0.25–2M/s bands. The pool shard is the hot
shard (`max_share` 1.0, by design n = 1); the busiest inventory group has 11.8% of inventory
commands.

### `s2`: not measured at scale 1

The scaled runs (1M users, same module, same per-user shape) take 25.2 s warm for 5.97M exported
events, 237k events/s end to end; generate 12.78 s (467k/s), seal 6.34 s (941k/s), check
3.03 s (1.97M/s), write 2.61 s (2.29M/s). `check_s` at 1M users is 3.03 s over 21 steps
(Task 9 measured the `sum_le` rebuild at ~0.21 s per step at 30M keys). A linear ×20 would be
~500 s at 20M users, but neither memory nor round counts are linear in users, so this is no
measurement of the gate. Independently of the time, the expectations `exported_events`
(~119M vs 10⁸ ± 5%) and `postings_per_payment_event` (2.374 vs 2.4–2.6) miss (see above), so a
scale-1 run on the reference machine would report `fail` on those even inside 600 s.

### S1 re-measure

The S1 gate still passes: 54.90 s warm against 60 s, 2.73 GiB against 16 GiB, 10,022,123
exported events and inventory share 0.0774, exactly as before. D41 moved the step boundaries:
29 steps (was 28) and 1,388,004 rounds (was 1,388,003). Warm time rose from 43.97 s (task 24b
row) to 54.90 s, all of it in generate (36.41 → 47.14 s): the S2 engine changes since that row
(D38–D44, D61 sender keys, Task 19 shard-phase timing) cost ~11 s on S1; this task did not
profile which. Its margin to the 60 s gate is now 5 s.
