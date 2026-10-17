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
(10⁷ ± 5%), a share (`around ≤ 1`) an absolute one (0.08 ± 0.02).

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
