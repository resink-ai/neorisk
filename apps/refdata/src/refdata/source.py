"""`specs/source.toml`: which source file a project reads, and each source table's key.

    file = "E_commerce.sqlite"
    note = "São Paulo wall clock, stored as UTC"
    [tables]
    orders = ["order_id"]
    geolocation = []          # no key: diffs are reported unsorted
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Source:
    file: str
    tables: dict[str, list[str]]
    note: str = ""


def load_source(project: Path) -> Source:
    d = tomllib.loads((Path(project) / "specs" / "source.toml").read_text())
    return Source(d["file"], {k: list(v) for k, v in d["tables"].items()}, d.get("note", ""))
