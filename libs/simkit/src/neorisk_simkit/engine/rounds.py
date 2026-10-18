"""Rounds within a frontier step (spec section 06, decisions D4, D5, D7).

`run_step(world, t0, t1)` admits population arrivals, collects owners due in `[t0, t1)` from
the calendar, and repeats rounds until the step closes:

1. owner phase: every runnable owner runs its commands below `t1` until it issues a request
   (thread pool when the round is large, inline otherwise);
2. route the owners' outboxes; `H = safe horizon` over suspended owners and pending creations;
3. shard phase: every shard with a command below `H` runs to `H`; route the shards' outboxes;
4. admit creations (the generated `admit_created`, D44); the next round runs the owners whose
   responses have all been delivered and the newly created owners.

The step closes when no owner is runnable, no shard command lies below `t1` and no creation is
pending. Rounds smaller than `engine.parallel_min_partitions` after the first run inside the
generated `drain_small_rounds` (one compiled loop on the calling thread, D4; creations are
admitted there too) until a round is large or a slab, pool, route or admission status needs
Python; Python then finishes that round from the phase where the compiled loop stopped, so both
paths run the same rounds.

Both paths time their shard phases (D55, F-03): Python rounds wrap the shard `_run_phase` in
`time.perf_counter_ns()`, the compiled loop adds into `round_state[RS_SHARD_NS]`; the step's
total is `RoundStats.shard_ns`.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from neorisk_simkit.engine.codegen import (
    DONE,
    DR_CLOSED,
    DR_NO_PROGRESS,
    DR_PYTHON,
    PH_OWNERS,
    PH_ROUTE1,
    PH_ROUTE2,
    PH_SHARDS,
    RS_C0,
    RS_H,
    RS_NLOG,
    RS_PHASE,
    RS_SHARD_NS,
    RS_STATUS,
)
from neorisk_simkit.engine.errors import EngineError

_NO_SLOTS = np.zeros(0, np.int64)


@dataclass
class RoundStats:
    rounds: int = 0
    owners_run: list[int] = field(default_factory=list)      # per round
    shard_cmds: list[int] = field(default_factory=list)      # per round
    compiled_rounds: int = 0
    python_admissions: int = 0           # created owners admitted by Python rounds this step
    shard_ns: int = 0                    # wall nanoseconds spent in shard phases this step


@dataclass(frozen=True)
class _Resume:
    """Where the compiled loop stopped inside a round."""
    phase: int
    status: int
    h: int
    c0: int


def _run_phase(world: Any, slots: np.ndarray, limit_t: int, owners: bool,
               pool: ThreadPoolExecutor | None) -> None:
    """Run `slots` below `limit_t`: contiguous chunks on the thread pool when the phase is
    large, inline on worker 0 otherwise."""
    if not len(slots):
        return
    if pool is None or len(slots) < world.run.engine.parallel_min_partitions:
        world.run_slots(0, slots, limit_t, owners=owners)
        return
    futures = [pool.submit(world.run_slots, w, chunk, limit_t, owners=owners)
               for w, chunk in enumerate(np.array_split(slots, world.threads)) if len(chunk)]
    for f in futures:
        f.result()


def _python_round(world: Any, runnable: np.ndarray, t1: int, pool: ThreadPoolExecutor | None,
                  stats: RoundStats, resume: _Resume | None) -> np.ndarray:
    """One round (or the rest of one, from `resume`); returns the created owners admitted."""
    phase = PH_OWNERS if resume is None else resume.phase
    if phase == PH_OWNERS:
        if resume is not None and resume.status != DONE:
            world.handle_status(0, resume.status)
        _run_phase(world, runnable, t1, True, pool)
        world.note_suspended(runnable)
    if phase <= PH_ROUTE1:
        world.route()
    if phase <= PH_SHARDS:
        if phase < PH_SHARDS:
            h, c0 = world.horizon(t1), world.command_count()
        else:
            h, c0 = resume.h, resume.c0
            if resume.status != DONE:
                world.handle_status(0, resume.status)
        shards = world.shards_below(h)
        world.mark_touched(shards)
        ts = time.perf_counter_ns()
        _run_phase(world, shards, h, False, pool)
        stats.shard_ns += time.perf_counter_ns() - ts
    else:
        c0 = resume.c0
    if phase <= PH_ROUTE2:
        world.route()
    shard_cmds = world.command_count() - c0
    # from PH_ADMIT the compiled admission changed nothing (all or nothing, F-10): admit again,
    # which refills a short node reserve or raises the cap error itself
    admitted = world.admit_created(t1) if world.pending_creations() else _NO_SLOTS
    stats.python_admissions += len(admitted)
    if not len(runnable) and not shard_cmds and not len(admitted):
        raise EngineError(f"no progress in round {stats.rounds + 1}")
    stats.rounds += 1
    stats.owners_run.append(len(runnable))
    stats.shard_cmds.append(shard_cmds)
    return admitted


def _drain(world: Any, runnable: np.ndarray, t1: int,
           stats: RoundStats) -> tuple[int, np.ndarray, _Resume | None]:
    """Small rounds in the generated compiled loop; finished rounds are added to `stats`."""
    n = len(runnable)
    world.run_buf[:n] = runnable
    rs = world.round_state
    code, n = world.eng.drain_small_rounds(
        world._W, world._outs[0], world.R, world._cq, world._fs, world.run_buf, n, int(t1),
        int(world.run.engine.parallel_min_partitions), world.shard_lo, world.G,
        world.shard_buf, world.round_log, rs, world.admit_buf)
    done = int(rs[RS_NLOG])
    for owners_run, shard_cmds in world.round_log[:done].tolist():
        stats.owners_run.append(owners_run)
        stats.shard_cmds.append(shard_cmds)
    stats.rounds += done
    stats.compiled_rounds += done
    if code == DR_NO_PROGRESS:
        raise EngineError(f"no progress in round {stats.rounds + 1}")
    resume = None
    if code == DR_PYTHON:
        resume = _Resume(int(rs[RS_PHASE]), int(rs[RS_STATUS]), int(rs[RS_H]), int(rs[RS_C0]))
    return int(code), world.run_buf[:n].copy(), resume


def _closed(world: Any, runnable: np.ndarray, t1: int) -> bool:
    return (not len(runnable) and world.pending_creations() == 0
            and not len(world.shards_below(t1)))


def run_step(world: Any, t0: int, t1: int) -> RoundStats:
    """Run every command of the step `[t0, t1)` (see the module docstring)."""
    t0, t1 = int(t0), int(t1)
    world.begin_step(t0, t1)
    admitted = world.admit_population(t0, t1)
    runnable = np.union1d(world.collect(t0, t1), admitted).astype(np.int64)
    small = world.run.engine.parallel_min_partitions
    stats = RoundStats()
    world.round_state[RS_SHARD_NS] = 0            # the compiled loop adds its shard phases here
    pool = ThreadPoolExecutor(world.threads) if world.threads > 1 else None
    try:
        while True:
            resume = None
            if _closed(world, runnable, t1):
                break
            if stats.rounds > 0 and len(runnable) < small:
                code, runnable, resume = _drain(world, runnable, t1, stats)
                if code == DR_CLOSED:
                    break
                if resume is None:           # a large round next, or the round log is full
                    continue
            admitted = _python_round(world, runnable, t1, pool, stats, resume)
            runnable = np.union1d(world.take_runnable(t1), admitted).astype(np.int64)
    finally:
        if pool is not None:
            pool.shutdown()
    stats.shard_ns += int(world.round_state[RS_SHARD_NS])
    world.end_step(t1)
    return stats
