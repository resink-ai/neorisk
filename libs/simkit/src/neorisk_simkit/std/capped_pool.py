"""Capped pool accounting: claims go through the pool shard's own heap, so the cap is exact."""

from numba import njit


def init(cap: int) -> dict[str, list[int]]:
    """Initial state of a one-shard pool with state `{"remaining": "i64", "granted": "i64"}`."""
    if cap < 0:
        raise ValueError("pool cap must be >= 0")
    return {"remaining": [int(cap)], "granted": [0]}


@njit(cache=True)
def take(remaining, amount):
    """`amount` if `0 < amount <= remaining`, else 0 (whole claims only, no partial grants)."""
    if amount > 0 and amount <= remaining:
        return amount
    return 0
