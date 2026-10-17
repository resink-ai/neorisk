"""Law builders for `p.check(...)`: inert specs stored in the plan, evaluated at seal by
`checks.laws.LawBook` (D47)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LawSpec:
    kind: str
    args: tuple[tuple[str, Any], ...]

    def arg(self, name: str) -> Any:
        return dict(self.args)[name]


def never_negative(path: str) -> LawSpec:
    """`<table|shard>.<column>` never drops below zero."""
    return LawSpec("never_negative", (("path", path),))


def resolved(event: str, *, by: tuple[str, ...], key: str, within: str | None = None) -> LawSpec:
    """Every `event` keyed by `key` is followed by one of `by` (within `within`, if given)."""
    return LawSpec("resolved", (("event", event), ("by", tuple(by)), ("key", key),
                                ("within", within)))


def sum_le(lhs: str, rhs: str, *, by: str) -> LawSpec:
    """Per `by` key, the sum of `lhs` (`event.column`) never exceeds the sum of `rhs`."""
    return LawSpec("sum_le", (("lhs", lhs), ("rhs", rhs), ("by", by)))


def at_most_once(event: str, *, key: tuple[str, ...] | str) -> LawSpec:
    """`event` occurs at most once per `key`; a row with a null key column is skipped."""
    key = (key,) if isinstance(key, str) else tuple(key)
    return LawSpec("at_most_once", (("event", event), ("key", key)))


def total_le(lhs: str, limit: int) -> LawSpec:
    """The running total of `lhs` (`event.column`) over the whole run never exceeds `limit`.

    Warm-up rows count toward the total but are never judged. Each exported row that leaves the
    total above `limit` is one violation, so a non-required law that is exceeded keeps
    counting every later row until the total falls back to `limit`."""
    return LawSpec("total_le", (("lhs", lhs), ("limit", int(limit))))


def balanced(table: str, *, amount: str = "amount", side: str = "side",
             by: tuple[str, ...] = ("partition_id", "lamport")) -> LawSpec:
    """Per `by` group of `table` (default: one commit), Σ `amount` of `side == "debit"` rows
    equals Σ `amount` of `side == "credit"` rows."""
    return LawSpec("balanced", (("table", table), ("amount", amount), ("side", side),
                                ("by", tuple(by))))
