"""The discovery protocol: a few reported seeds, a budgeted oracle, rounds of review.

A method sees the world and the labels it has earned so far (`known`: world id -> 0/1). Each
round it proposes up to `k` unreviewed users; the oracle reveals their true labels. After the
last round the method scores every user, and that ranking is what the metrics read.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import numpy as np

from bench.discover.world import Truth, World


class Method(Protocol):
    key: str

    def propose(self, world: World, known: dict[int, int], k: int) -> list[int]: ...

    def score(self, world: World, known: dict[int, int]) -> np.ndarray: ...


class Ranker:
    """A method whose proposal is its own top-k unreviewed users; ties go to the lower id."""

    key = "ranker"

    def score(self, world: World, known: dict[int, int]) -> np.ndarray:
        raise NotImplementedError

    def propose(self, world: World, known: dict[int, int], k: int) -> list[int]:
        return top_unknown(world, self.score(world, known), known, k)


def top_unknown(world: World, scores: np.ndarray, known: dict[int, int], k: int) -> list[int]:
    ids = world.user_ids
    free = ~np.isin(ids, np.fromiter(known, dtype=np.int64, count=len(known)))
    order = np.lexsort((ids[free], -scores[free]))
    return [int(x) for x in ids[free][order[:k]]]


class Oracle:
    """The stand-in analyst: true labels, at most `budget` of them, never charged twice."""

    def __init__(self, truth: Truth, world: World, budget: int):
        self._label = dict(zip(world.user_ids.tolist(), truth.bad.astype(int).tolist()))
        self.budget = budget
        self.spent = 0
        self._seen: set[int] = set()

    def review(self, ids: list[int]) -> dict[int, int]:
        out = {}
        for i in ids:
            if self.spent >= self.budget:
                break
            if i in self._seen or i not in self._label:
                continue
            self._seen.add(i)
            self.spent += 1
            out[i] = self._label[i]
        return out


def draw_seeds(truth: Truth, world: World, n: int, t_report_days: float,
               rng: np.random.Generator) -> list[int]:
    """`n` reported cases: bad, not stealth, and with a label known by the report day."""
    start = np.datetime64(world.users["created_at"].min().replace(tzinfo=None), "us")
    limit = start + np.timedelta64(int(t_report_days * 86400e6), "us")
    ok = truth.bad & ~truth.stealth & (truth.available_at <= limit)
    pool = world.user_ids[ok]
    if len(pool) < n:
        raise ValueError(f"only {len(pool)} seed candidates by day {t_report_days}; need {n}")
    return [int(x) for x in rng.choice(np.sort(pool), size=n, replace=False)]


@dataclass
class Trace:
    key: str
    seeds: list[int]
    reviewed: list[list[int]] = field(default_factory=list)   # per round
    hits: list[int] = field(default_factory=list)             # bad found per round
    known: dict[int, int] = field(default_factory=dict)
    scores: np.ndarray | None = None
    snapshots: dict[int, Trace] = field(default_factory=dict)

    def upto(self, rounds: int, scores: np.ndarray, known: dict[int, int]) -> Trace:
        """This trace as it stood after `rounds` rounds."""
        return Trace(self.key, self.seeds, self.reviewed[:rounds], self.hits[:rounds],
                     known, scores)


def run_method(method: Method, world: World, truth: Truth, *, seeds: list[int], k: int,
               rounds: int, checkpoints: tuple[int, ...] = ()) -> Trace:
    """Run the rounds; `checkpoints` (round counts below `rounds`) also keep a scored
    snapshot in `trace.snapshots`, so one run answers several budgets."""
    oracle = Oracle(truth, world, budget=k * rounds)
    known = {s: 1 for s in seeds}
    trace = Trace(method.key, list(seeds))
    snaps: dict[int, Trace] = {}
    for r in range(rounds):
        if r in checkpoints:
            snaps[r] = trace.upto(r, _scores(method, world, known), dict(known))
        got = oracle.review(method.propose(world, dict(known), k))
        known.update(got)
        trace.reviewed.append(list(got))
        trace.hits.append(sum(got.values()))
    trace.known = known
    trace.scores = _scores(method, world, known)
    trace.snapshots = snaps
    return trace


def _scores(method: Method, world: World, known: dict[int, int]) -> np.ndarray:
    return np.asarray(method.score(world, dict(known)), dtype=float)
