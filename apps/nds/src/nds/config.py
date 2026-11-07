"""nds.yaml: the per-dataset config, and the include/exclude matching."""

import re
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

import yaml

CONFIG_NAME = "nds.yaml"


class NdsError(Exception):
    pass


@dataclass
class Config:
    root: Path
    dataset: str
    default_remote: str | None = None
    remotes: dict[str, dict] = field(default_factory=dict)
    include: list[str] = field(default_factory=lambda: ["**/*"])
    exclude: list[str] = field(default_factory=list)
    # name -> {path, include, exclude}; when set, this file manages many datasets under `root`
    datasets: dict[str, dict] = field(default_factory=dict)

    @classmethod
    def load(cls, root: Path) -> "Config":
        path = root / CONFIG_NAME
        if not path.exists():
            raise NdsError(f"no {CONFIG_NAME} in {root}; run `nds init`")
        raw = yaml.safe_load(path.read_text()) or {}
        cfg = cls(
            root=root,
            dataset=raw.get("dataset") or root.name,
            default_remote=raw.get("default_remote"),
            remotes=raw.get("remotes") or {},
            include=raw.get("include") or ["**/*"],
            exclude=raw.get("exclude") or [],
            datasets=raw.get("datasets") or {},
        )
        cfg.check_datasets()
        return cfg

    def save(self) -> None:
        raw = {
            "dataset": self.dataset,
            "default_remote": self.default_remote,
            "remotes": self.remotes,
            "include": self.include,
            "exclude": self.exclude,
        }
        if self.datasets:
            raw["datasets"] = self.datasets
            del raw["dataset"]
        (self.root / CONFIG_NAME).write_text(yaml.safe_dump(raw, sort_keys=False))

    def remote(self, name: str | None) -> tuple[str, dict]:
        name = name or self.default_remote
        if not name or name not in self.remotes:
            raise NdsError(f"unknown remote {name!r}; known: {sorted(self.remotes) or 'none'}")
        return name, self.remotes[name]

    def resolve(self, names: list[str], every: bool) -> list["Config"]:
        """The datasets a command acts on: this folder itself, or the named ones from `datasets:`."""
        if not self.datasets:
            if names or every:
                raise NdsError("this nds.yaml has no `datasets:` section; drop the dataset names")
            return [self]
        if every:
            names = list(self.datasets)
        elif not names:
            raise NdsError(f"name a dataset or pass --all; known: {', '.join(self.datasets)}")
        unknown = [n for n in names if n not in self.datasets]
        if unknown:
            raise NdsError(f"unknown dataset {unknown[0]!r}; known: {', '.join(self.datasets)}")
        return [self._view(n) for n in dict.fromkeys(names)]

    def check_datasets(self) -> None:
        paths = {n: Path(d.get("path", n)).parts for n, d in self.datasets.items()}
        for n, parts in paths.items():
            if Path(*parts).is_absolute() or ".." in parts:
                raise NdsError(f"dataset {n!r}: path must be relative and inside this folder")
            for m, other in paths.items():
                if n < m and (parts[: len(other)] == other or other[: len(parts)] == parts):
                    raise NdsError(f"datasets {n!r} and {m!r} overlap")

    def _view(self, name: str) -> "Config":
        spec = self.datasets[name]
        root = self.root / spec.get("path", name)
        if not root.is_dir():
            raise NdsError(f"dataset {name!r}: {root} is not a folder")
        return Config(
            root=root,
            dataset=name,
            default_remote=self.default_remote,
            remotes=self.remotes,
            include=spec.get("include") or self.include,
            exclude=self.exclude + (spec.get("exclude") or []),
        )

    def selects(self, rel: str, include: list[str], exclude: list[str]) -> bool:
        """Exclude wins over include. CLI patterns add to the YAML ones."""
        if rel == CONFIG_NAME:
            return False
        if any(_match(p, rel) for p in self.exclude + exclude):
            return False
        return any(_match(p, rel) for p in self.include + include)


@cache
def _regex(pattern: str) -> re.Pattern:
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


def _match(pattern: str, rel: str) -> bool:
    # like .gitignore: a pattern with no slash matches the file name anywhere
    target = rel if "/" in pattern else rel.rsplit("/", 1)[-1]
    return _regex(pattern).match(target) is not None
