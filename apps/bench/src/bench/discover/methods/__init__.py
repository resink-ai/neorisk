"""The discovery methods, by key. `make` hands truth to `perfect` only."""

from __future__ import annotations

from collections.abc import Callable

from bench.discover.methods.baseline import Perfect, Random
from bench.discover.protocol import Method
from bench.discover.world import Truth

METHODS: dict[str, Callable[[int], Method]] = {
    "random": Random,
    "perfect": Perfect,
}
ORDER = ["random", "perfect"]


def make(key: str, seed: int, truth: Truth | None = None) -> Method:
    if key == "perfect":
        if truth is None:
            raise ValueError("perfect needs the truth")
        return Perfect(truth)
    if key not in METHODS:
        raise ValueError(f"unknown method {key!r}; choose from {', '.join(ORDER)}")
    return METHODS[key](seed)
