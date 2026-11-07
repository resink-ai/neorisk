"""Peak memory of a run: this process and its children (a Spark JVM), plus the engine's
Docker containers (Flink, Redpanda), sampled in a background thread."""

from __future__ import annotations

import subprocess
import threading
from typing import Self

import psutil

UNITS = {"B": 1 / 2**20, "KiB": 1 / 1024, "MiB": 1, "GiB": 1024}   # as `docker stats` prints


def _tree_mb() -> float:
    me = psutil.Process()
    total = 0
    for p in [me, *me.children(recursive=True)]:
        try:
            total += p.memory_info().rss
        except psutil.Error:
            pass
    return total / 2**20


def _mb(text: str) -> float:
    num = text.rstrip("BKMGiTkb")
    unit = text[len(num):]
    return float(num) * UNITS.get(unit, 1)


def containers_mb(names: tuple[str, ...]) -> float:
    """The summed memory of the named containers; 0 when Docker does not answer."""
    if not names:
        return 0.0
    try:
        out = subprocess.run(["docker", "stats", "--no-stream", "--format",
                              "{{.Name}} {{.MemUsage}}", *names], capture_output=True,
                             text=True, timeout=20, check=False).stdout
    except (OSError, subprocess.TimeoutExpired):
        return 0.0
    return sum(_mb(line.split()[1]) for line in out.splitlines() if len(line.split()) > 1)


class Sampler:
    """`with Sampler(containers) as s: ...` then `s.peak_mb`."""

    def __init__(self, containers: tuple[str, ...] = (), every: float = 0.5):
        self.containers, self.every = tuple(containers), every
        self.peak_mb = 0.0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def _sample(self) -> None:
        self.peak_mb = max(self.peak_mb, round(_tree_mb() + containers_mb(self.containers), 1))

    def _loop(self) -> None:
        while not self._stop.wait(self.every):
            self._sample()

    def __enter__(self) -> Self:
        self._sample()
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        self._thread.join()
        self._sample()
