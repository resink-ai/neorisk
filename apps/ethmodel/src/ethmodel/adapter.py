"""The model as a `bench discover` Method, so its review rounds run on the same loop as the
graph, behaviour and vote methods there.

For v0 the reviewer is simulated by held-out labels: bench's Oracle says "bad" exactly for
the held-out high-trust addresses and "not bad" for everything else (which really means
"not known bad"). A human or LLM analyst replaces it later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

import numpy as np
import polars as pl

from bench.discover.methods.baseline import Random
from bench.discover.protocol import Ranker, run_method
from ethmodel.data import Sample, Split
from ethmodel.head import blend, graph_scores, pu_scores


@dataclass(frozen=True)
class EthWorld:
    """What bench's loop reads: `user_ids`, the index of every score array."""

    addresses: list[str]
    x: np.ndarray
    transfers: pl.DataFrame
    trust: dict[str, float]
    user_ids: np.ndarray = field(init=False)

    def __post_init__(self):
        object.__setattr__(self, "user_ids", np.arange(len(self.addresses), dtype=np.int64))


class EthMethod(Ranker):
    def __init__(self, key: str, graph_weight: float = 0.3):
        self.key = key
        self.graph_weight = graph_weight

    def score(self, world: EthWorld, known: dict[int, int]) -> np.ndarray:
        n = len(world.addresses)
        positive = np.zeros(n, dtype=bool)
        negative = np.zeros(n, dtype=bool)
        for i, v in known.items():
            (positive if v else negative)[i] = True
        weight = np.array([world.trust.get(a, 1.0) for a in world.addresses])
        head = pu_scores(world.x, positive, weight, negative)
        bad = {world.addresses[i] for i in np.flatnonzero(positive)}
        g = graph_scores(world.transfers, bad)
        return blend(head, np.array([g.get(a, 0.0) for a in world.addresses]),
                     self.graph_weight)


def run(reps: dict[str, dict[str, np.ndarray]], sample: Sample, split: Split, *,
        rounds: int = 3, k: int = 20, seed: int = 7) -> pl.DataFrame:
    """One trace per representation plus bench's Random floor: hits per round."""
    names = sorted(set.intersection(*(set(r) for r in reps.values())))
    truth = SimpleNamespace(bad=np.array([a in split.holdout for a in names]),
                            stealth=np.zeros(len(names), dtype=bool),
                            cohort=np.array(["none"] * len(names)))
    seeds = [i for i, a in enumerate(names) if a in split.train]
    rows = []
    methods = [(key, EthMethod(key), reps[key]) for key in sorted(reps)]
    methods.append(("random", Random(seed), next(iter(reps.values()))))
    for key, method, rep in methods:
        world = EthWorld(names, np.stack([rep[a] for a in names]), sample.transfers,
                         split.train)
        trace = run_method(method, world, truth, seeds=seeds, k=k, rounds=rounds)
        for r, hits in enumerate(trace.hits, 1):
            rows.append({"method": key, "round": r, "reviewed": len(trace.reviewed[r - 1]),
                         "held_out_found": hits})
    return pl.DataFrame(rows)
