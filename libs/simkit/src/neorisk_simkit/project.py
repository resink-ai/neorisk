"""A datagen project folder: `datagen.toml`, `specs/` (the only folder an agent edits), and
the git-ignored `out/`, `reports/` and `logs/`.

    specs/pack.py            Config dataclass + define(p: Pack)
    specs/overlays/<name>.py apply(o: Overlay, **params)
    specs/expectations.yaml  statistical expectations (checks)

`datagen.toml`:

    [run]       seed, days, warmup_days, mode, max_events       (RunConfig fields)
    [config]    pack Config fields
    [profiles.<name>.run] / [profiles.<name>.config]           override the two above
    [overlays.<name>]                                           overlay parameters

Precedence: defaults, then the profile, then `--set` (`users=500`, `run.days=10`,
`bounty_hunters.size=50`). The result is recorded in the manifest.
"""

from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import importlib
import importlib.util
import itertools
import sys
import tomllib
import types
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from neorisk_simkit.engine.loop import RunConfig
from neorisk_simkit.spec.pack import Pack, PackError
from neorisk_simkit.spec.plan import Plan, build_plan

_load_ids = itertools.count()


def parse_value(raw: str) -> Any:
    try:
        return tomllib.loads(f"v = {raw}")["v"]
    except tomllib.TOMLDecodeError:
        return raw


def _coerce(cls: type, values: dict, what: str) -> Any:
    known = {f.name: f for f in fields(cls)}
    unknown = set(values) - set(known)
    if unknown:
        raise PackError(f"unknown {what} fields {sorted(unknown)}; known: {sorted(known)}")
    base = cls()
    out = {}
    for k, v in values.items():
        default = getattr(base, k)
        out[k] = tuple(v) if isinstance(default, tuple) and isinstance(v, list) else v
    return dataclasses.replace(base, **out)


@dataclass
class Settings:
    """Everything that decides a run, after merging defaults, a profile and --set."""
    profile: str
    run: RunConfig
    config: Any
    overlays: dict[str, dict] = field(default_factory=dict)


class Project:
    def __init__(self, root: Path):
        self.root = root
        self.specs = root / "specs"
        if not (self.specs / "pack.py").exists():
            raise PackError(f"{root}: no specs/pack.py")
        toml = root / "datagen.toml"
        self.toml = tomllib.loads(toml.read_text()) if toml.exists() else {}
        self._pkg = f"_datagen_pack_{next(_load_ids)}"
        spec = importlib.util.spec_from_file_location(
            self._pkg, self.specs / "pack.py", submodule_search_locations=[str(self.specs)])
        mod = importlib.util.module_from_spec(spec)
        sys.modules[self._pkg] = mod
        with _no_bytecode():
            spec.loader.exec_module(mod)
        self.module = mod
        if not hasattr(mod, "define"):
            raise PackError(f"{root}/specs/pack.py has no define(p)")
        self.name = getattr(mod, "NAME", root.name)
        self.Config = getattr(mod, "Config", None)

    # --- overlays -----------------------------------------------------------------------
    def overlay_names(self) -> list[str]:
        d = self.specs / "overlays"
        return sorted(p.stem for p in d.glob("*.py") if not p.stem.startswith("_"))

    def overlay_module(self, name: str) -> types.ModuleType:
        if name not in self.overlay_names():
            raise PackError(f"{self.root}: no overlay {name!r} (have {self.overlay_names()})")
        with _no_bytecode():
            return importlib.import_module(f"{self._pkg}.overlays.{name}")

    # --- settings and plan --------------------------------------------------------------
    def settings(self, profile: str | None = None, sets: list[str] = (),
                 overlays: list[str] = ()) -> Settings:
        t = self.toml
        profiles = t.get("profiles", {})
        if profile is not None and profile not in profiles:
            raise PackError(f"unknown profile {profile!r}; have {sorted(profiles)}")
        prof = profiles.get(profile, {}) if profile else {}
        run = {**t.get("run", {}), **prof.get("run", {})}
        cfg = {**t.get("config", {}), **prof.get("config", {})}
        ovs = {n: {**t.get("overlays", {}).get(n, {}),
                   **prof.get("overlays", {}).get(n, {})} for n in overlays}
        for s in sets:
            k, sep, raw = s.partition("=")
            if not sep:
                raise PackError(f"--set expects key=value, got {s!r}")
            v = parse_value(raw)
            head, dot, rest = k.partition(".")
            if dot and head == "run":
                run[rest] = v
            elif dot:
                if head not in ovs:
                    raise PackError(f"--set {k}: overlay {head!r} is not part of this run")
                ovs[head][rest] = v
            else:
                cfg[k] = v
        config = _coerce(self.Config, cfg, "config") if self.Config else None
        return Settings(profile or "default", _coerce(RunConfig, run, "run"), config, ovs)

    def plan(self, overlays: dict[str, dict] | None = None) -> Plan:
        from neorisk_simkit.spec.overlay import Overlay
        pack = Pack(self.name, config=self.Config, doc=getattr(self.module, "__doc__", "") or "",
                    schema_version=getattr(self.module, "SCHEMA_VERSION", 1))
        self.module.define(pack)
        applied = []
        for name, params in (overlays or {}).items():
            mod = self.overlay_module(name)
            o = Overlay(name, pack, params, ns=1 + len(applied))
            mod.apply(o, **params)
            applied.append(o)
        return build_plan(pack, applied)

    def rerun(self, manifest: dict, *, overlays: bool = True, seed: int | None = None):
        """Simulate a dataset's recorded settings again, in memory (baseline: no overlays;
        held-out seeds: another seed)."""
        from datetime import datetime

        from neorisk_simkit.engine import simulate
        run = {**manifest["run"], "start": datetime.fromisoformat(manifest["run"]["start"])}
        if seed is not None:
            run["seed"] = seed
        rc = dataclasses.replace(RunConfig(), **run)
        cfg = _coerce(self.Config, manifest["config"], "config") if self.Config else None
        return simulate(self.plan(manifest["overlays"] if overlays else {}), cfg, rc)

    def run_name(self, s: Settings, overlays: list[str]) -> str:
        return f"{s.profile}-s{s.run.seed}" + "".join(f"+{o}" for o in overlays)

    # --- provenance ---------------------------------------------------------------------
    def revision(self) -> str:
        h = hashlib.sha256()
        for p in sorted(self.specs.rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts:
                h.update(str(p.relative_to(self.specs)).encode())
                h.update(p.read_bytes())
        return h.hexdigest()[:16]

    def provenance(self) -> dict:
        lock = next((d / "uv.lock" for d in [self.root, *self.root.resolve().parents]
                     if (d / "uv.lock").exists()), None)
        from importlib.metadata import version
        return {"project": self.name, "pack_revision": self.revision(),
                "simkit": version("neorisk-simkit"),
                "uv_lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest()[:16]
                if lock else None}

    def lint(self) -> list[str]:
        """Mutable module globals in pack and overlay code (shared state across partitions)."""
        mods = [self.module] + [self.overlay_module(n) for n in self.overlay_names()]
        for sub in ("actions", "kernels"):
            if (self.specs / f"{sub}.py").exists():
                mods.append(importlib.import_module(f"{self._pkg}.{sub}"))
        errs = []
        for m in mods:
            for k, v in vars(m).items():
                if not k.startswith("__") and isinstance(v, (list, dict, set, bytearray)):
                    errs.append(f"{m.__name__.split('.', 1)[-1]}.{k}: mutable module global "
                                f"({type(v).__name__}); use a tuple or a frozen mapping")
        return errs


@contextlib.contextmanager
def _no_bytecode():
    """Specs change often and fast: never cache them as .pyc, whose mtime+size check misses
    two same-size edits within one second."""
    old, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        yield
    finally:
        sys.dont_write_bytecode = old


def load_project(path: str | Path) -> Project:
    return Project(Path(path))
