"""Build (or reuse) the generated engine module of a plan (decision D34).

The source is written once to `$NEORISK_JIT_CACHE/gen_<sha256(source)[:16]>.py` (default
`~/.cache/neorisk-simkit/jit/`) and imported by path, so Numba's `cache=True` keys its on-disk
cache to a stable file and a warm run compiles nothing.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import sys
import types
from pathlib import Path

from neorisk_simkit.engine.codegen import generate_module
from neorisk_simkit.spec.plan import Plan

_MODULES: dict[str, types.ModuleType] = {}


def jit_cache_dir() -> Path:
    env = os.environ.get("NEORISK_JIT_CACHE")
    return Path(env) if env else Path.home() / ".cache" / "neorisk-simkit" / "jit"


def _write_atomic(path: Path, source: str) -> None:
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(source)
    os.replace(tmp, path)


def build_engine(plan: Plan, *, checked: bool = False) -> types.ModuleType:
    """Return the engine module for `plan`; `module.__file__` identifies the generated source."""
    source = generate_module(plan, checked=checked)
    digest = hashlib.sha256(source.encode()).hexdigest()[:16]
    mod = _MODULES.get(digest)
    if mod is not None:
        return mod
    cache = jit_cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f"gen_{digest}.py"
    if not path.is_file() or path.read_text() != source:
        _write_atomic(path, source)
    name = f"neorisk_gen_{digest}"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod                       # Numba resolves globals through the module
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    _MODULES[digest] = mod
    return mod
