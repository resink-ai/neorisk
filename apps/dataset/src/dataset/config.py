"""`datasets/<name>/dataset.toml`: what a dataset is and how it is made.

    name = "olist"              # the folder's name
    version = "v1"
    kind = "spider2"            # or "synthetic"
    [recipe]                    # free-form; empty for spider2 (the specs sit beside it)
    [results.mixed]             # spider2: columns stored as SQLite text, per table
    orders = ["note"]
    [results.exact]             # spider2: float columns compared bit for bit, not within 1e-9
    case_ids = ["case_id"]

A synthetic dataset's recipe names the `datagen` project and run, and its three designs:

    [recipe]
    project = "examples/ecommerce"   # repo-relative
    profile = "sample"
    seed = 7
    overlay = []
    designs = ["star", "dv", "an"]   # each is specs/<design>.sql
    [recipe.owners]                  # event -> payload column that keys its messages
    order_placed = "user_id"
    [[check]]                        # a results table against a simkit table (build time)
    table = "star_dim_sku"
    simkit = "skus"
    columns = { sku_id = "sku_id" }  # results column = simkit column
    where = ""                       # optional, on the results table
    simkit_where = ""                # optional, on the simkit table
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from dataset.names import DATASET, REPO, VERSION

DATASETS = REPO / "datasets"
KINDS = ("spider2", "synthetic")
DESIGNS = ("star", "dv", "an", "act", "obt")


@dataclass(frozen=True)
class DatasetConfig:
    name: str
    version: str
    kind: str
    dir: Path
    mixed: dict[str, list[str]] = field(default_factory=dict)
    recipe: dict = field(default_factory=dict)
    exact: dict[str, list[str]] = field(default_factory=dict)
    designs: list[str] = field(default_factory=list)
    owners: dict[str, str] = field(default_factory=dict)
    checks: list[dict] = field(default_factory=list)


def _synthetic(f: Path, recipe: dict, raw_checks: list) -> tuple[list, dict, list]:
    for k in ("project", "profile", "seed"):
        if k not in recipe:
            raise ValueError(f"{f}: [recipe] needs {k!r} for a synthetic dataset")
    designs = list(recipe.get("designs", []))
    bad = [d for d in designs if d not in DESIGNS]
    if bad:
        raise ValueError(f"{f}: designs {bad} are not among {DESIGNS}")
    if len(designs) != 3 or len(set(designs)) != 3:
        raise ValueError(f"{f}: designs must be three different ids, got {designs}")
    checks = []
    for i, c in enumerate(raw_checks):
        for k in ("table", "simkit", "columns"):
            if k not in c:
                raise ValueError(f"{f}: [[check]] #{i + 1} needs {k!r}")
        checks.append({"table": c["table"], "simkit": c["simkit"], "columns": dict(c["columns"]),
                       "where": c.get("where", ""), "simkit_where": c.get("simkit_where", "")})
    return designs, dict(recipe.get("owners", {})), checks


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
    results = t.get("results", {})
    mixed = {k: list(v) for k, v in results.get("mixed", {}).items()}
    exact = {k: list(v) for k, v in results.get("exact", {}).items()}
    recipe = dict(t.get("recipe", {}))
    designs, owners, checks = ([], {}, []) if kind != "synthetic" else _synthetic(
        f, recipe, t.get("check", []))
    return DatasetConfig(name, version, kind, d, mixed, recipe, exact, designs, owners, checks)


def all_configs(root: Path | None = None) -> list[DatasetConfig]:
    root = root or DATASETS
    return [load(f.parent) for f in sorted(root.glob("*/dataset.toml"))]
