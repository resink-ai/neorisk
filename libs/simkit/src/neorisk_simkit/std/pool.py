"""A capped pool (§07): a shard that grants claims in canonical order until a cap is reached,
optionally per period (a monthly budget). Because every claim goes through the one shard, the
cap is exact.

    @dataclass
    class Budget:
        pool: CappedPool = field(default_factory=lambda: CappedPool(cap=2_000_000, period=30*DAY))

    if not s.pool.take(ctx.now, amount):
        ctx.emit("bonus_rejected", ...)
        return ctx.decline("cap_exhausted")

Law: grants per period ≤ cap (`checks.laws.pool_within_cap`).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CappedPool:
    cap: int
    period: float | None = None                      # seconds; None: one cap for the run
    granted: dict[int, int] = field(default_factory=dict)   # period index -> granted

    def _p(self, now: float) -> int:
        return 0 if self.period is None else int(now // self.period)

    def left(self, now: float) -> int:
        return self.cap - self.granted.get(self._p(now), 0)

    def take(self, now: float, amount: int) -> bool:
        """Grant `amount` if the cap allows it."""
        if amount > self.left(now):
            return False
        k = self._p(now)
        self.granted[k] = self.granted.get(k, 0) + amount
        return True
