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
1 gate failed or internal error (D35).

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
   `events_per_second`, `peak_rss_bytes` (the child's own `ru_maxrss`), `proposals` (owner
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

**Gate (spec §10, §18):** ≤ 60 s warm and peak RSS ≤ 16 GB on the reference machine, 16 cores /
64 GB, with Numba plus Polars threads capped at 16.

## Results

| Date | Machine (cores / RAM) | Threads | Exported events | Warm s | Cold compile s | Peak RSS GB | generate / seal / write s | Rounds per step (max) | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| 2026-10-17 UTC | arm64 14 / 36 GB (not reference) | 14 | 10,022,123 | 116.67 | 509.18 | 2.77 | 109.14 / 4.38 / 2.38 | 96,955 | **fail** |

Read from `results/s1-warm.json` (warm run) and `results/s1-cold.json` (cold compile; the
cold run's own measured run took 117.84 s, peak RSS 2.88 GB). Both runs: 28 steps, 1,388,003
rounds, 19,247,347 proposals, 1,490,629 reserve requests (share 0.0774).

The gate **fails** on time: 116.7 s against 60 s, 85.9k events/s end to end against the
≥ 167k/s owner-dominated band. Memory passes with a wide margin (2.8 GB of 16 GB). The machine
is not the reference machine (14 cores / 36 GB), but almost all of the time is single-threaded
(below), so two more cores would not close the gap.

The stage that misses its §10 band is **generate**: 109 s for 10⁷ events, 92k events/s
against 0.5–3M/s (3–20 s). Seal (4.4 s) and write (2.4 s) are inside their bands. Profiling
(see the task report) puts the generate time in two places:

- **Small rounds.** Rounds per step follow distinct request windows (D4, D5): each checkout's
  reserve request opens its own 150 ms window, so a step has up to ~97k rounds and the run
  1.39M. Nearly all of them run in the compiled `drain_small_rounds` loop on one thread
  (process CPU ~160% on 14 threads).
- **Per-command overhead in the generated module.** Generated helpers take the whole `out`
  slab tuple and `ctx` by value, and Numba increfs and decrefs every array in them on each call:
  `_emit_product_viewed` compiles to ~1,800 indirect (refcount) calls, `_view` to ~8,100.
  An owner command costs ~10 µs, nearly all in NRT refcounting.

S1 is not exited on this gate until a later change passes it.
