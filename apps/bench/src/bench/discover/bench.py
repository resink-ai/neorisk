"""Run every method over several seed draws and budgets, and collect the summaries."""

from __future__ import annotations

import time
from collections.abc import Callable

import numpy as np

from bench.discover.explain import anomaly_profile, explain
from bench.discover.methods import ORDER, make
from bench.discover.metrics import aggregate, reason_precision, summarize
from bench.discover.protocol import draw_seeds, run_method
from bench.discover.world import Truth, World


def run_bench(world: World, truth: Truth, *, methods: list[str] = ORDER, k: int = 50,
              rounds: int = 10, sweep: tuple[int, ...] = (0, 2, 5, 10), draws: int = 5,
              n_seeds: int = 5, report_day: float = 45.0, seed: int = 0,
              log: Callable[[str], None] = lambda s: None) -> dict:
    budgets = sorted({r for r in sweep if r <= rounds} | {rounds})
    per: dict[str, dict[int, list[dict]]] = {m: {r: [] for r in budgets} for m in methods}
    secs = {m: 0.0 for m in methods}
    seed_sets, explained = [], []
    size = int(truth.bad.sum())
    for d in range(draws):
        seeds = draw_seeds(truth, world, n_seeds, report_day, np.random.default_rng([seed, d]))
        seed_sets.append(seeds)
        why = explain(world, {s: 1 for s in seeds})
        carries = anomaly_profile(world) @ why.weights > 0
        explained.append({"seeds": seeds, "top": [[n, round(w, 3)] for n, w in why.top()],
                          "reasons": {str(k): v for k, v in why.reasons.items()}})
        for key in methods:
            t0 = time.perf_counter()
            tr = run_method(make(key, seed * 1000 + d, truth), world, truth, seeds=seeds, k=k,
                            rounds=rounds, checkpoints=tuple(r for r in budgets if r < rounds))
            secs[key] += time.perf_counter() - t0
            for r in budgets:
                snap = tr if r == rounds else tr.snapshots[r]
                s = summarize(snap, world.user_ids, truth)
                s["reason_precision"] = reason_precision(snap, world.user_ids, size, carries)
                per[key][r].append(s)
            log(f"draw {d + 1}/{draws}  {key:<12} found {sum(tr.hits):>4} "
                f"in {k * rounds} reviews  ({time.perf_counter() - t0:.1f}s)")
    cohorts, counts = np.unique(truth.cohort, return_counts=True)
    return {
        "config": {"k": k, "rounds": rounds, "budgets": budgets, "draws": draws,
                   "n_seeds": n_seeds, "report_day": report_day, "seed": seed},
        "world": {"users": len(world.user_ids), "bad": int(truth.bad.sum()),
                  "stealth": int(truth.stealth.sum()),
                  "cohorts": {str(c): int(n) for c, n in zip(cohorts, counts)}},
        "seeds": seed_sets,
        "explain": explained,
        "methods": {m: {"seconds": secs[m] / draws,
                        "by_budget": {str(r): aggregate(per[m][r]) for r in budgets}}
                    for m in methods},
    }
