"""The discovery methods, by key. `make` hands truth to `perfect` only."""

from __future__ import annotations

from collections.abc import Callable

from bench.discover.methods.active import Active, ActivePlain
from bench.discover.methods.anchored import Anomaly, ReasonHop, ReasonRules, ReasonSim
from bench.discover.methods.baseline import Perfect, Random
from bench.discover.methods.behaviour import PULearn, PULearnPlain, Similarity, Sync
from bench.discover.methods.graph import Connection, MoneyFlow
from bench.discover.methods.vote import Vote, VotePlain
from bench.discover.methods.weak import LabelModel, Rules
from bench.discover.protocol import Method
from bench.discover.world import Truth

# each method anchored on the seeds' anomalies sits after the one it replaces ("before/after")
METHODS: dict[str, Callable] = {
    "random": Random, "perfect": Perfect, "anomaly": Anomaly,
    "connection": Connection, "money_flow": MoneyFlow, "reason_hop": ReasonHop,
    "similarity": Similarity, "reason_sim": ReasonSim,
    "pu_learn_plain": PULearnPlain, "pu_learn": PULearn, "sync": Sync,
    "rules": Rules, "reason_rules": ReasonRules, "label_model": LabelModel,
    "active_plain": ActivePlain, "active": Active,
    "vote_plain": VotePlain, "vote": Vote,
}
# the method each anchored one replaces
BEFORE = {"reason_hop": "connection", "reason_sim": "similarity", "pu_learn": "pu_learn_plain",
          "reason_rules": "rules", "active": "active_plain", "vote": "vote_plain"}
ORDER = list(METHODS)


def make(key: str, seed: int, truth: Truth | None = None) -> Method:
    if key == "perfect":
        if truth is None:
            raise ValueError("perfect needs the truth")
        return Perfect(truth)
    if key not in METHODS:
        raise ValueError(f"unknown method {key!r}; choose from {', '.join(ORDER)}")
    return METHODS[key](seed)
