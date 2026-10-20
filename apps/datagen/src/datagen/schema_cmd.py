"""datagen schema (filled in by a later milestone)."""

from __future__ import annotations


def add_parser(sub) -> None:
    sub.add_parser("schema", help="not implemented yet")


def run(args) -> int:
    from datagen.cli import _err
    return _err("schema: not implemented yet")
