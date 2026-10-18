"""Frontier steps over a whole run (spec sections 06 and 13; decisions D20, D26).

`Simulation(run, threads=…)` builds the `World` and yields one `SealedStep` per frontier step
over `[start − warmup, start + span)`, with a step boundary forced at `start`; steps that end
at or before `start` are warm-up (not exported). With `engine.adapt` the next step length
follows `next_step_length` (deterministic: it depends only on row counts). Every sealed step,
warm-up included (F-01), is fed to the run's `LawBook` (D47); a required law that fails raises
`LawViolation`.

`stats` also keeps the run's shard, round and output accounting (Task 19), each over its own
window: whole run (warm-up included) for commands, rounds, admissions, shard load, populations
and allocated IDs; exported steps only for `events_by_partition` and `shard_ns`.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import numpy as np
import pyarrow as pa

from neorisk_simkit.checks.laws import LawBook
from neorisk_simkit.engine.rounds import run_step
from neorisk_simkit.engine.world import World
from neorisk_simkit.io.seal import SealedStep, entity_table, seal_step

_SECOND = 1_000_000
ENGINE_COUNTERS = ("rejects", "retries", "late_messages", "continuations")   # run_stats keys


def next_step_length(prev_len: int, rows: int, engine: Any, budget: Any) -> int:
    """Step length targeting 25% of `max_step_rows` from the previous step's counted rows
    (everything the step cap counts, D41), clamped to `[step_min, step_max]` and floored to
    whole seconds."""
    target = budget.max_step_rows // 4
    new = engine.step_max_us if rows == 0 else prev_len * target // rows
    new = min(max(new, engine.step_min_us), engine.step_max_us)
    new -= new % _SECOND
    return int(max(new, engine.step_min_us))


class Simulation:
    """One run: the world, its static entities and its sealed frontier steps."""

    def __init__(self, run: Any, *, threads: int, checked: bool = False):
        self.run = run
        self.world = World.build(run, threads=threads, checked=checked)
        plan = run.plan
        self.id_bases: dict[str, int] = {ns: 0 for ns in plan.namespaces}
        self.id_bases.update({f"event:{e.name}": 0 for e in plan.events})
        for t in plan.member_tables:            # D75: member rows follow the population
            self.id_bases[t] = next((pop.n for pop in plan.populations if pop.table == t), 0)
        self.laws = LawBook(plan, max_keys=run.budget.max_checker_keys)
        self._started = False
        self.stats: dict[str, Any] = {
            "steps": 0, "rows_per_table": {}, "late_messages": 0,
            "rejects": {p.name: 0 for p in plan.processes}, "retries": 0, "continuations": 0,
            "rounds_per_step": [], "round_detail": [], "generate_s": 0.0, "seal_s": 0.0,
            "check_s": 0.0, "laws": self.laws.report(),
            "proposals": 0, "requests_by_boundary": {}, "pairing": {},
            "accumulators": {a.name: 0 for a in plan.accumulators},   # exported totals (D46)
            # whole run (warm-up included)
            "commands": 0, "shard_commands": 0, "rounds_total": 0, "compiled_rounds_total": 0,
            "admissions_total": 0, "compiled_admissions_total": 0, "shard_load": {},
            "populations": {}, "ids_allocated": {},
            # exported steps only
            "events_by_partition": {p.name: 0 for p in plan.partitions}, "shard_ns": 0}
        self._event_partition = {e.name: e.partition for e in plan.events
                                 if e.group == "events"}

    # ------------------------------------------------------------------ entities
    def static_entities(self) -> dict[str, pa.Table]:
        """Read tables, from sources or recipes (`origin = "static"`, `created_at` = their
        `first_seen` column when present, else start − warmup) and population owner tables
        (`"initial"` / `"arrival"`): public `id`, `created_at`, `origin`, every column at
        creation."""
        w, run = self.world, self.run
        plan, seed = run.plan, int(run.seed)
        out: dict[str, pa.Table] = {}
        for name, rows in w.tables.items():
            t = plan.table(name)
            n = len(next(iter(rows.values()))) if rows else 0
            created = (np.asarray(rows["first_seen"], np.int64) if "first_seen" in rows
                       else np.full(n, w.sim_start, np.int64))
            out[name] = entity_table(name, t.cols, np.arange(n, dtype=np.int64), created,
                                     "static", rows, seed)
        for pop in w.populations:
            t, part = plan.table(pop.table), pop.part.name
            n = len(pop.times)
            n_init = int(np.floor(n * self._initial(pop.table) + 0.5))
            origin = np.where(np.arange(n) < n_init, "initial", "arrival").astype(object)
            rows, valid = {}, {}
            for c, arr, init in zip(t.cols, w.state[part], w.state_init[part], strict=True):
                given = c.name in pop.attrs
                rows[c.name] = pop.attrs[c.name] if given else np.full(n, init, arr.dtype)
                if c.ltype.nullable and c.ltype.kind != "ref":     # refs: NULL is null
                    valid[c.name] = np.full(n, given, bool)
            out[pop.table] = entity_table(pop.table, t.cols, np.arange(n, dtype=np.int64),
                                          pop.times, origin, rows, seed, valid)
        return out

    def _initial(self, table: str) -> float:
        return next(p.initial for p in self.run.plan.populations if p.table == table)

    # ------------------------------------------------------------------ steps
    def steps(self) -> Iterator[SealedStep]:
        """Run and seal every frontier step in order (single use)."""
        if self._started:
            raise RuntimeError("Simulation.steps() can only run once")
        self._started = True
        run, w = self.run, self.world
        eng, budget = run.engine, run.budget
        start, end = int(run.start_us), int(run.start_us + run.span_us)
        t = start - int(run.warmup_us)
        length = int(eng.step_us)
        w.init_shards()                                  # periodic shard processes (D26)
        step = 0
        while t < end:
            t1 = min(t + length, end)
            if t < start < t1:
                t1 = start                               # boundary forced at start (D20)
            c0 = time.perf_counter()
            rounds = run_step(w, t, t1)
            c1 = time.perf_counter()
            self.stats["admissions_total"] += int(w.admissions[0])   # reset by begin_step
            self.stats["compiled_admissions_total"] += (int(w.admissions[0])
                                                        - rounds.python_admissions)
            sealed = seal_step(w, step, t, t1, t >= start, self.id_bases,
                               law_tables=self.laws.tables)
            c2 = time.perf_counter()
            sealed.stats["laws"] = self.laws.step(sealed, w, exported=sealed.exported)
            sealed.warmup_rows.clear()                   # law input only, never written
            c3 = time.perf_counter()
            self.stats["check_s"] += c3 - c2
            sealed.stats.update(rounds=rounds.rounds, owners_run=list(rounds.owners_run),
                                shard_cmds=list(rounds.shard_cmds), generate_s=c1 - c0,
                                seal_s=c2 - c1, check_s=c3 - c2)
            self._account(sealed, rounds, c1 - c0, c2 - c1)
            yield sealed
            step += 1
            t = t1
            if eng.adapt:
                length = next_step_length(length, sealed.stats["counted_rows"], eng, budget)
        self.laws.finish(end)
        self.stats["laws"] = self.laws.report()
        self.stats["shard_load"] = w.stats["shard_load"]
        self.stats["populations"] = {pop.table: int(pop.next) for pop in w.populations}
        self.stats["ids_allocated"] = {ns: int(self.id_bases[ns]) for ns in run.plan.namespaces}

    def _account(self, sealed: SealedStep, rounds: Any, gen_s: float, seal_s: float) -> None:
        st = self.stats
        st["steps"] += 1
        rows = st["rows_per_table"]
        for name, tbl in (*sealed.events.items(), *sealed.postings.items(),
                          *sealed.labels.items(), *sealed.history.items()):
            rows[name] = rows.get(name, 0) + tbl.num_rows
        if sealed.exported:
            acc = st["accumulators"]
            for name, v in sealed.accumulators.items():
                acc[name] += v
            by_part = st["events_by_partition"]
            for name, tbl in sealed.events.items():
                by_part[self._event_partition[name]] += tbl.num_rows
            st["shard_ns"] += rounds.shard_ns
        st["rounds_per_step"].append(rounds.rounds)
        st["rounds_total"] += rounds.rounds
        st["compiled_rounds_total"] += rounds.compiled_rounds
        st["round_detail"].append({"owners_run": list(rounds.owners_run),
                                   "shard_cmds": list(rounds.shard_cmds)})
        st["generate_s"] += gen_s
        st["seal_s"] += seal_s
        ws = self.world.stats
        for k in ENGINE_COUNTERS:
            st[k] = dict(ws[k]) if isinstance(ws[k], dict) else int(ws[k])
        # proposals: owner commands executed (commits and rejects; retries are not commands)
        st["commands"] = ws["commands"]
        st["shard_commands"] += sum(rounds.shard_cmds)
        st["proposals"] = ws["commands"] - st["shard_commands"]
        st["requests_by_boundary"] = dict(ws["requests_by_boundary"])
        st["pairing"] = dict(ws["pairing"])
