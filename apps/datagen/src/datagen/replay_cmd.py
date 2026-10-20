"""datagen replay (filled in by a later milestone)."""

from __future__ import annotations


def add_parser(sub) -> None:
    sub.add_parser("replay", help="not implemented yet")


def run(args) -> int:
    from datagen.cli import _err
    return _err("replay: not implemented yet")
