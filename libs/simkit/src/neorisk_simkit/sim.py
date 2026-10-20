"""A small discrete-event simulation core.

Events are callbacks scheduled at a time on one heap; running them emits rows into named
tables. Cost is O(E log Q) for E scheduled events and a queue of at most Q pending ones, and
memory is linear in the rows emitted. One seeded generator drives every draw, and the heap
breaks time ties by schedule order, so a seed always gives the same output.
"""

from __future__ import annotations

import heapq
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime
from typing import Any

import numpy as np
import polars as pl

DAY = 86_400.0


class Simulation:
    """Schedule callbacks with `at` or `after`, record rows with `emit`, then `run`.

    Time is seconds since `start` (a float). `tables()` returns one DataFrame per emitted table,
    with `event_time` converted to a datetime column.
    """

    def __init__(self, seed: int, start: datetime, days: float):
        self.rng = np.random.default_rng(seed)
        self.start, self.end = start, days * DAY
        self.now = 0.0
        self._heap: list[tuple[float, int, Callable[..., None], tuple]] = []
        self._seq = 0
        self._rows: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
        self._ids: dict[str, int] = defaultdict(int)

    def next_id(self, kind: str) -> int:
        self._ids[kind] += 1
        return self._ids[kind]

    def at(self, t: float, fn: Callable[..., None], *args: Any) -> None:
        if t < self.end:
            heapq.heappush(self._heap, (t, self._seq, fn, args))
            self._seq += 1

    def after(self, delay: float, fn: Callable[..., None], *args: Any) -> None:
        self.at(self.now + delay, fn, *args)

    def emit(self, table: str, **row: Any) -> int:
        """Append one event row stamped with the current time; returns its event_id."""
        eid = self.next_id("event")
        cols = self._rows[table]
        cols["event_id"].append(eid)
        cols["event_time"].append(self.now)
        for k, v in row.items():
            cols[k].append(v)
        return eid

    def run(self) -> None:
        heap = self._heap
        while heap:
            t, _, fn, args = heapq.heappop(heap)
            self.now = t
            fn(*args)

    def tables(self) -> dict[str, pl.DataFrame]:
        out = {}
        for name, cols in self._rows.items():
            df = pl.DataFrame(dict(cols))
            out[name] = df.with_columns(
                (pl.lit(self.start) + pl.duration(microseconds=(pl.col("event_time") * 1e6)
                                                  .cast(pl.Int64))).alias("event_time"))
        return out

