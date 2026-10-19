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

    def get(self, name: str, default: Any = None) -> Any:
        return dict(self.args).get(name, default)


def never_negative(path: str) -> LawSpec:
    """`<table|shard>.<column>` never drops below zero."""
    return LawSpec("never_negative", (("path", path),))


def resolved(event: str, *, by: tuple[str, ...], key: str, within: str | None = None) -> LawSpec:
    """Every `event` keyed by `key` is followed by one of `by` (within `within`, if given)."""
    return LawSpec("resolved", (("event", event), ("by", tuple(by)), ("key", key),
                                ("within", within)))


def sum_le(lhs: str, rhs: str, *, by: str) -> LawSpec:
    """Per `by` key, the sum of `lhs` (`event.column`) never exceeds the sum of `rhs`
    (`event.column`), or, when `rhs` is `<owner table>.<column>` and `by` that table's key, the
    owner's last value of that column seen at a seal (0 for a key never seen; D81)."""
    return LawSpec("sum_le", (("lhs", lhs), ("rhs", rhs), ("by", by)))


def at_most_once(event: str, *, key: tuple[str, ...] | str) -> LawSpec:
    """`event` occurs at most once per `key`; a row with a null key column is skipped."""
    key = (key,) if isinstance(key, str) else tuple(key)
    return LawSpec("at_most_once", (("event", event), ("key", key)))


def total_le(lhs: str, limit: int, per: str | None = None) -> LawSpec:
    """The running total of `lhs` (`event.column`) over the whole run never exceeds `limit`;
    with `per` (a duration such as `"30d"`), over each window `event_time // per` (epoch
    aligned) instead: the total restarts at 0 in every window.

    Warm-up rows count toward the total but are never judged. Each exported row that leaves the
    total above `limit` is one violation, so a non-required law that is exceeded keeps
    counting every later row until the total falls back to `limit` (or its window ends)."""
    args = (("lhs", lhs), ("limit", int(limit)))
    return LawSpec("total_le", args if per is None else (*args, ("per", per)))


def balanced(table: str, *, amount: str = "amount", side: str = "side",
             by: tuple[str, ...] = ("partition_id", "lamport")) -> LawSpec:
    """Per `by` group of `table` (default: one commit), Σ `amount` of `side == "debit"` rows
    equals Σ `amount` of `side == "credit"` rows."""
    return LawSpec("balanced", (("table", table), ("amount", amount), ("side", side),
                                ("by", tuple(by))))


def lifecycle(key: str, edges: dict[str, tuple[str, ...]]) -> LawSpec:
    """Per `key`, the rows of the listed event or posting tables (every edge source and target)
    follow `edges` in canonical order: a row's table must be in the edge list of the key's
    previous listed row, and a key's first row must be a table that no edge targets."""
    return LawSpec("lifecycle", (("key", key),
                                 ("edges", tuple((a, tuple(b)) for a, b in edges.items()))))
