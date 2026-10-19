"""Project loading: `datagen.toml`, the pack module, and resolution of a run (`RunSpec`).

`resolve_run` merges `[defaults]` <- `[profiles.<p>]` <- `profiles.<p>.set` <- overrides.
Override keys prefixed `engine.` / `budget.` / `writer.` route to those tables, `run.` to the
run keys (`start`, `span`, `warmup`, `seed`), and everything else walks the pack's `Config`
dataclass by dotted path (D21). Overlays (spec §08, D77) come from the profile's `overlays`
list (or an explicit list); their `apply` parameters from `[profiles.<p>.overlay.<name>]`, then
overrides `<name>.<param>=v`."""

from __future__ import annotations

import dataclasses
import hashlib
import importlib
import importlib.machinery
import importlib.util
import inspect
import re
import sys
import tomllib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MappingProxyType, ModuleType
from typing import Any

from neorisk_simkit.spec.plan import Plan, build_plan


class ProjectError(Exception):
    """The project file, a profile or an override is invalid."""


# ---------------------------------------------------------------------------- units
_DURATION_RE = re.compile(r"^(\d+)(us|ms|s|m|h|d)$")
_DURATION_US = {"us": 1, "ms": 1_000, "s": 1_000_000, "m": 60_000_000, "h": 3_600_000_000,
                "d": 86_400_000_000}
_SIZE_RE = re.compile(r"^(\d+)(B|KB|MB|GB)$")
_SIZE_B = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3}
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def parse_duration(s: str) -> int:
    """`"300ms"` -> 300_000 (µs). Units: us ms s m h d."""
    m = _DURATION_RE.match(s) if isinstance(s, str) else None
    if m is None:
        raise ProjectError(f"invalid duration {s!r} (expected e.g. 300ms, 15m, 90d)")
    return int(m.group(1)) * _DURATION_US[m.group(2)]


def parse_size(s: str | int) -> int:
    """`"8MB"` -> 8 * 1024**2 (bytes). Units: B KB MB GB (powers of 1024); an int is bytes."""
    if isinstance(s, int) and not isinstance(s, bool) and s >= 0:
        return s
    m = _SIZE_RE.match(s) if isinstance(s, str) else None
    if m is None:
        raise ProjectError(f"invalid size {s!r} (expected e.g. 256KB, 64MB, 2GB)")
    return int(m.group(1)) * _SIZE_B[m.group(2)]


def parse_time(v: str | datetime) -> int:
    """RFC 3339 with an offset (e.g. `2026-03-01T00:00:00Z`) -> epoch µs."""
    if isinstance(v, str):
        try:
            v = datetime.fromisoformat(v)
        except ValueError:
            raise ProjectError(f"invalid start time {v!r}") from None
    if not isinstance(v, datetime) or v.tzinfo is None:
        raise ProjectError(f"start time {v!r} must be RFC 3339 with an offset, e.g. ...Z")
    return (v - _EPOCH) // timedelta(microseconds=1)


# ---------------------------------------------------------------------------- settings
@dataclass(frozen=True)
class Budget:
    threads: int
    memory_bytes: int
    max_step_rows: int
    max_step_bytes: int | None
    max_spawn_depth: int
    max_admissions_per_step: int
    max_checker_keys: int = 50_000_000             # keys carried by law reducers (D47)


@dataclass(frozen=True)
class WriterSettings:
    compression: str
    compression_level: int
    row_group_rows: int


@dataclass(frozen=True)
class EngineSettings:
    step_us: int
    step_min_us: int
    step_max_us: int
    adapt: bool
    slab_bytes: int
    timer_nodes: int
    payload_slots: int
    max_messages_per_step: int
    parallel_min_partitions: int
    max_owner_messages_per_step: int = 100_000      # D73: the carried owner-message buffer
    force_capacity: Mapping[str, int] = field(default_factory=lambda: MappingProxyType({}))


@dataclass(frozen=True)
class Project:
    dir: Path
    name: str
    pack_path: Path
    toml: Mapping[str, Any]
    overlays_dir: Path | None = None        # [project] overlays (default specs/overlays)


@dataclass(frozen=True)
class RunSpec:
    name: str
    profile: str
    seed: int
    start_us: int
    span_us: int
    warmup_us: int
    mode: str
    budget: Budget
    writer: WriterSettings
    engine: EngineSettings
    cfg: Any
    plan: Plan
    overrides: tuple[str, ...]
    overlays: tuple[tuple[str, Mapping[str, Any]], ...] = ()   # (name, apply params) in order


def _int(key: str, v: Any) -> int:
    if isinstance(v, bool) or not isinstance(v, int):
        raise ProjectError(f"setting {key!r} expects an integer, got {v!r}")
    return v


def _bool(key: str, v: Any) -> bool:
    if not isinstance(v, bool):
        raise ProjectError(f"setting {key!r} expects true or false, got {v!r}")
    return v


def _str(key: str, v: Any) -> str:
    if not isinstance(v, str):
        raise ProjectError(f"setting {key!r} expects a string, got {v!r}")
    return v


def _dur(key: str, v: Any) -> int:
    return parse_duration(v)


def _size(key: str, v: Any) -> int:
    return parse_size(v)


def _opt_size(key: str, v: Any) -> int | None:
    return None if v is None else parse_size(v)


Conv = Callable[[str, Any], Any]

# toml key -> (dataclass field, converter, default raw value); defaults match the mini fixture
_BUDGET: dict[str, tuple[str, Conv, Any]] = {
    "threads": ("threads", _int, 1),
    "memory": ("memory_bytes", _size, "4GB"),
    "max_step_rows": ("max_step_rows", _int, 1_000_000),
    "max_step_bytes": ("max_step_bytes", _opt_size, None),
    "max_spawn_depth": ("max_spawn_depth", _int, 3),
    "max_admissions_per_step": ("max_admissions_per_step", _int, 100_000),
    "max_checker_keys": ("max_checker_keys", _int, 50_000_000),
}
_WRITER: dict[str, tuple[str, Conv, Any]] = {
    "compression": ("compression", _str, "zstd"),
    "compression_level": ("compression_level", _int, 3),
    "row_group_rows": ("row_group_rows", _int, 131_072),
}
_ENGINE: dict[str, tuple[str, Conv, Any]] = {
    "step": ("step_us", _dur, "1d"),
    "step_min": ("step_min_us", _dur, "1h"),
    "step_max": ("step_max_us", _dur, "7d"),
    "adapt": ("adapt", _bool, False),
    "slab_bytes": ("slab_bytes", _size, "1MB"),
    "timer_nodes": ("timer_nodes", _int, 1_000_000),
    "payload_slots": ("payload_slots", _int, 100_000),
    "max_messages_per_step": ("max_messages_per_step", _int, 1_000_000),
    "parallel_min_partitions": ("parallel_min_partitions", _int, 64),
    "max_owner_messages_per_step": ("max_owner_messages_per_step", _int, 100_000),
}
_TABLES = {"budget": _BUDGET, "writer": _WRITER, "engine": _ENGINE}
_RUN_KEYS = ("seed", "start", "mode", "span", "warmup")
_RUN_OVERRIDABLE = ("start", "span", "warmup", "seed")


def _settings(cls, table: str, spec: dict[str, tuple[str, Conv, Any]], raw: dict[str, Any]):
    for k in raw:
        if k not in spec:
            raise ProjectError(f"unknown setting '{table}.{k}'")
    kw = {f: conv(f"{table}.{k}", raw.get(k, default)) for k, (f, conv, default) in spec.items()}
    return cls(**kw)


# ---------------------------------------------------------------------------- project
def load_project(dir: str | Path) -> Project:
    d = Path(dir).resolve()
    f = d / "datagen.toml"
    if not f.is_file():
        raise ProjectError(f"no datagen.toml in {d}")
    try:
        toml = tomllib.loads(f.read_text())
    except tomllib.TOMLDecodeError as e:
        raise ProjectError(f"{f}: {e}") from None
    proj = toml.get("project", {})
    name = proj.get("name")
    if not isinstance(name, str) or not name:
        raise ProjectError(f"{f}: [project].name is required")
    pack_path = d / proj.get("pack", "specs/pack.py")
    if not pack_path.is_file():
        raise ProjectError(f"pack file {pack_path} not found")
    overlays = proj.get("overlays", "specs/overlays")
    if not isinstance(overlays, str):
        raise ProjectError(f"{f}: [project].overlays must be a folder path")
    return Project(dir=d, name=name, pack_path=pack_path, toml=toml,
                   overlays_dir=d / overlays)


def import_pack(project: Project) -> ModuleType:
    """Import the pack as `<synthetic package>.<stem>`; the specs folder needs no __init__.py."""
    specs_dir = project.pack_path.parent
    tag = hashlib.sha256(str(project.dir).encode()).hexdigest()[:8]
    safe = re.sub(r"\W", "_", project.name)
    pkg = f"neorisk_project_{safe}_{tag}"
    modname = f"{pkg}.{project.pack_path.stem}"
    if modname in sys.modules:
        return sys.modules[modname]
    if pkg not in sys.modules:
        init = specs_dir / "__init__.py"
        if init.is_file():
            spec = importlib.util.spec_from_file_location(
                pkg, init, submodule_search_locations=[str(specs_dir)])
        else:
            spec = importlib.machinery.ModuleSpec(pkg, None, is_package=True)
            spec.submodule_search_locations = [str(specs_dir)]
        mod = importlib.util.module_from_spec(spec)
        sys.modules[pkg] = mod
        if spec.loader is not None:
            spec.loader.exec_module(mod)
    module = importlib.import_module(modname)
    for attr in ("PACK", "SCHEMA_VERSION", "define"):
        if not hasattr(module, attr):
            raise ProjectError(f"pack {project.pack_path} does not define {attr}")
    return module


# ---------------------------------------------------------------------------- overlays
def import_overlay(project: Project, pack_module: ModuleType, name: str) -> Callable:
    """The `apply` function of overlay `name`: `<overlays folder>/<name>.py`, imported as
    `<pack package>.overlays.<name>` (an implicit namespace subpackage of the specs package)."""
    folder = project.overlays_dir or project.pack_path.parent / "overlays"
    path = folder / f"{name}.py"
    if not re.fullmatch(r"[A-Za-z_]\w*", name) or not path.is_file():
        raise ProjectError(f"overlay {name!r}: {path} not found")
    pkg = pack_module.__name__.rpartition(".")[0]
    modname = f"{pkg}.overlays.{name}"
    if modname in sys.modules:
        module = sys.modules[modname]
    elif folder.resolve() == (project.pack_path.parent / "overlays").resolve():
        module = importlib.import_module(modname)
    else:
        spec = importlib.util.spec_from_file_location(modname, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[modname] = module
        spec.loader.exec_module(module)
    apply = getattr(module, "apply", None)
    if not callable(apply):
        raise ProjectError(f"overlay {name!r}: {path} does not define apply(o, ...)")
    return apply


def _overlay_defaults(name: str, apply: Callable) -> dict[str, Any]:
    """`apply(o, **params)`'s keyword defaults (every parameter after `o` needs one)."""
    out = {}
    for k, prm in list(inspect.signature(apply).parameters.items())[1:]:
        if prm.default is inspect.Parameter.empty:
            raise ProjectError(f"overlay {name}: parameter {k!r} needs a default")
        out[k] = prm.default
    return out


def _set_overlay(name: str, params: dict[str, Any], defaults: dict[str, Any], key: str,
                 value: Any) -> None:
    from neorisk_simkit.spec.dist import Dist

    if key not in defaults:
        raise ProjectError(f"overlay {name}: unknown parameter {key!r}")
    cur = defaults[key]
    if isinstance(cur, Dist):
        raise ProjectError(f"overlay {name}: parameter {key!r} is a Dist and fixed in code")
    if not isinstance(cur, int | float | str | bool):
        raise ProjectError(f"overlay {name}: parameter {key!r} is not settable "
                           "(only int, float, str and bool defaults are)")
    params[key] = _coerce(f"{name}.{key}", cur, value)


# ---------------------------------------------------------------------------- resolution
def _parse_value(raw: str) -> Any:
    try:
        return tomllib.loads(f"v = {raw}")["v"]
    except tomllib.TOMLDecodeError:
        return raw


def _flatten(d: Mapping[str, Any], prefix: str = "") -> Iterable[tuple[str, Any]]:
    for k, v in d.items():
        if isinstance(v, Mapping):
            yield from _flatten(v, f"{prefix}{k}.")
        else:
            yield f"{prefix}{k}", v


def _coerce(key: str, cur: Any, value: Any) -> Any:
    if isinstance(cur, bool):
        return _bool(key, value)
    if isinstance(cur, int):
        return _int(key, value)
    if isinstance(cur, float):
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ProjectError(f"setting {key!r} expects a number, got {value!r}")
        return float(value)
    if isinstance(cur, str):
        return _str(key, value)
    return value


def _set_config(cfg: Any, path: list[str], value: Any, key: str) -> Any:
    if not dataclasses.is_dataclass(cfg) or path[0] not in {
            f.name for f in dataclasses.fields(cfg)}:
        raise ProjectError(f"unknown setting {key!r}")
    cur = getattr(cfg, path[0])
    new = (_set_config(cur, path[1:], value, key) if len(path) > 1
           else _coerce(key, cur, value))
    return dataclasses.replace(cfg, **{path[0]: new})


def resolve_run(project: Project, profile: str, overrides: Iterable[str] = (),
                seed: int | None = None, overlays: Iterable[str] | None = None) -> RunSpec:
    """Resolve one run. `overlays=None` enables the profile's `overlays` list; an explicit
    list (`[]` included) replaces it (F-15)."""
    toml = project.toml
    profiles = toml.get("profiles", {})
    if profile not in profiles:
        raise ProjectError(f"unknown profile {profile!r} (have: {', '.join(profiles) or '-'})")
    prof = dict(profiles[profile])

    run_raw = dict(toml.get("defaults", {}))
    for k in run_raw:
        if k not in _RUN_KEYS:
            raise ProjectError(f"unknown setting 'defaults.{k}'")
    tables: dict[str, dict[str, Any]] = {t: dict(toml.get(t, {})) for t in _TABLES}
    sets = prof.pop("set", {})
    prof_overlays = prof.pop("overlays", [])
    prof_params = prof.pop("overlay", {})
    if not isinstance(prof_overlays, list) or not all(isinstance(o, str) for o in prof_overlays):
        raise ProjectError(f"profiles.{profile}.overlays must be a list of overlay names")
    if not isinstance(prof_params, Mapping):
        raise ProjectError(f"profiles.{profile}.overlay must be a table of overlay tables")
    enabled = list(dict.fromkeys(prof_overlays if overlays is None else overlays))
    for k, v in prof.items():
        if k not in _RUN_KEYS:
            raise ProjectError(f"unknown setting 'profiles.{profile}.{k}'")
        run_raw[k] = v

    overrides = tuple(overrides)
    pairs = list(_flatten(sets))
    for item in overrides:
        key, eq, raw = item.partition("=")
        if not eq or not key.strip():
            raise ProjectError(f"expected key=value, got {item!r}")
        pairs.append((key.strip(), _parse_value(raw.strip())))

    module = import_pack(project)
    config_cls = getattr(module, "Config", None)
    cfg = config_cls() if config_cls is not None else None
    applies = {o: import_overlay(project, module, o) for o in enabled}
    defaults = {o: _overlay_defaults(o, a) for o, a in applies.items()}
    params = {o: dict(d) for o, d in defaults.items()}
    for o in enabled:
        given = prof_params.get(o, {})
        if not isinstance(given, Mapping):
            raise ProjectError(f"profiles.{profile}.overlay.{o} must be a table")
        for k, v in given.items():
            _set_overlay(o, params[o], defaults[o], k, v)
    for key, value in pairs:
        head, _, rest = key.partition(".")
        if head in applies and rest:                  # an overlay parameter (D77)
            _set_overlay(head, params[head], defaults[head], rest, value)
        elif head in _TABLES and rest:
            tables[head][rest] = value
        elif head == "run" and rest:
            if rest not in _RUN_OVERRIDABLE:
                raise ProjectError(f"unknown setting {key!r}")
            run_raw[rest] = value
        else:
            cfg = _set_config(cfg, key.split("."), value, key)

    mode = _str("mode", run_raw.get("mode", "time"))
    if mode != "time":
        raise ProjectError(f"mode {mode!r} arrives later")
    for k in ("seed", "start", "span"):
        if k not in run_raw:
            raise ProjectError(f"[defaults].{k} is required")
    seed = _int("seed", run_raw["seed"]) if seed is None else int(seed)

    budget = _settings(Budget, "budget", _BUDGET, tables["budget"])
    plan = build_plan(module, cfg, project.pack_path.parent,
                      default_spawn_depth=budget.max_spawn_depth,   # D72, F-21
                      overlays=tuple((o, applies[o], params[o]) for o in enabled))
    return RunSpec(
        name=f"{profile}-s{seed}" + "".join(f"+{o}" for o in enabled), profile=profile,
        seed=seed,
        start_us=parse_time(run_raw["start"]), span_us=parse_duration(run_raw["span"]),
        warmup_us=parse_duration(run_raw.get("warmup", "0s")), mode=mode,
        budget=budget,
        writer=_settings(WriterSettings, "writer", _WRITER, tables["writer"]),
        engine=_settings(EngineSettings, "engine", _ENGINE, tables["engine"]),
        cfg=cfg, plan=plan, overrides=overrides,
        overlays=tuple((o, params[o]) for o in enabled))
