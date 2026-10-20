"""datagen check (filled in by a later milestone)."""

from __future__ import annotations


def add_parser(sub) -> None:
    sub.add_parser("check", help="not implemented yet")


def run(args) -> int:
    from datagen.cli import _err
    return _err("check: not implemented yet")
