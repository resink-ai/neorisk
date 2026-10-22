"""The discovery methods, by key. `make` hands truth to `perfect` only."""

from __future__ import annotations

from collections.abc import Callable

from bench.discover.methods.active import Active
from bench.discover.methods.baseline import Perfect, Random
from bench.discover.methods.behaviour import PULearn, Similarity, Sync
from bench.discover.methods.graph import Connection, MoneyFlow
from bench.discover.methods.vote import Vote
from bench.discover.methods.weak import LabelModel, Rules
from bench.discover.protocol import Method
from bench.discover.world import Truth

METHODS: dict[str, Callable] = {
    "random": Random, "perfect": Perfect,
    "connection": Connection, "money_flow": MoneyFlow,
    "similarity": Similarity, "pu_learn": PULearn, "sync": Sync,
    "rules": Rules, "label_model": LabelModel,
    "active": Active, "vote": Vote,
}
ORDER = list(METHODS)


def make(key: str, seed: int, truth: Truth | None = None) -> Method:
    if key == "perfect":
        if truth is None:
            raise ValueError("perfect needs the truth")
        return Perfect(truth)
    if key not in METHODS:
        raise ValueError(f"unknown method {key!r}; choose from {', '.join(ORDER)}")
    return METHODS[key](seed)
