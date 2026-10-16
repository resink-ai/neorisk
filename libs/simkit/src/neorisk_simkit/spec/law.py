"""Inert law builders for `p.check(...)`; stored in the plan, evaluated from S2 on."""

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
    """`event` occurs at most once per `key`."""
    key = (key,) if isinstance(key, str) else tuple(key)
    return LawSpec("at_most_once", (("event", event), ("key", key)))
