"""Keyed random streams: a partition's draws depend on (seed, partition key, process) only.

A partition key is a path hash: who created it (a source, or a parent partition's key), its
kind, and its ordinal among that creator's children of that kind, plus the namespace. It never
uses the global partition id, so adding unrelated partitions or overlays leaves every other
stream unchanged.
"""

from __future__ import annotations

import hashlib

import numpy as np


def key(*parts: object) -> int:
    """A stable 63-bit hash of `parts` (not Python's salted `hash`)."""
    h = hashlib.blake2b(repr(parts).encode(), digest_size=8).digest()
    return int.from_bytes(h, "big") >> 1


def stream(seed: int, *path: int) -> np.random.Generator:
    return np.random.default_rng(np.random.SeedSequence(seed, spawn_key=path))
