"""`datasets/<name>/dataset.toml`: what a dataset is and how it is made.

    name = "olist"              # the folder's name
    version = "v1"
    kind = "spider2"            # or "synthetic"
    [recipe]                    # free-form; empty for spider2 (the specs sit beside it)
    [results.mixed]             # spider2: columns stored as SQLite text, per table
    orders = ["note"]
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from dataset.names import DATASET, REPO, VERSION

DATASETS = REPO / "datasets"
KINDS = ("spider2", "synthetic")


@dataclass(frozen=True)
class DatasetConfig:
    name: str
    version: str
    kind: str
    dir: Path
    mixed: dict[str, list[str]] = field(default_factory=dict)
    recipe: dict = field(default_factory=dict)


def load(name_or_dir: str | Path) -> DatasetConfig:
    d = Path(name_or_dir)
    if not (d / "dataset.toml").exists():
        d = DATASETS / str(name_or_dir)
    f = d / "dataset.toml"
    if not f.exists():
        raise FileNotFoundError(f"no dataset {name_or_dir!r} ({f} not found)")
    t = tomllib.loads(f.read_text())
    name, version, kind = t.get("name"), t.get("version"), t.get("kind")
    if name != d.name or not DATASET.fullmatch(str(name)):
        raise ValueError(f"{f}: name {name!r} must be the folder's name {d.name!r}")
    if not VERSION.fullmatch(str(version)):
        raise ValueError(f"{f}: version {version!r} must be v1, v2, ...")
    if kind not in KINDS:
        raise ValueError(f"{f}: kind {kind!r} must be one of {KINDS}")
    mixed = {k: list(v) for k, v in t.get("results", {}).get("mixed", {}).items()}
    return DatasetConfig(name, version, kind, d, mixed, dict(t.get("recipe", {})))


def all_configs(root: Path | None = None) -> list[DatasetConfig]:
    root = root or DATASETS
    return [load(f.parent) for f in sorted(root.glob("*/dataset.toml"))]
