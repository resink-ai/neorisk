"""Kernel ABI surface: return codes, priorities, resource vectors, the @kernel decorator."""

from __future__ import annotations

import inspect
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from numba import njit

COMMIT = 0
RETRY = -1
START = 0

PRIO_CONTINUE = 0
PRIO_MESSAGE = 1
PRIO_EXPIRY = 2
PRIO_TIMER = 5

_LOCAL_RE = re.compile(r"^(i8|i16|i32|i64|u8|u32|f64|ref)(?:\[(\d+)\])?$")


@njit(cache=True)
def reject(code):
    """Reject the command with a user code >= 0; the returned value is 1 + code."""
    if code < 0:
        raise ValueError("reject code must be >= 0")
    return 1 + code


def _frozen_counts(name: str, d: Mapping[str, int] | None) -> Mapping[str, int]:
    out = dict(d or {})
    for k, v in out.items():
        if v < 0:
            raise ValueError(f"{name}[{k!r}] must be >= 0")
    return MappingProxyType(out)


@dataclass(frozen=True)
class Res:
    records: Mapping[str, int] | None = None
    creates: Mapping[str, int] | None = None
    timers: int = 0
    requests: int = 0

    def __post_init__(self):
        object.__setattr__(self, "records", _frozen_counts("records", self.records))
        object.__setattr__(self, "creates", _frozen_counts("creates", self.creates))
        for n in ("timers", "requests"):
            if getattr(self, n) < 0:
                raise ValueError(f"{n} must be >= 0")


@dataclass(frozen=True, init=False)
class Local:
    fields: dict[str, tuple[str, int]] = field(default_factory=dict)

    def __init__(self, **fields: str):
        parsed: dict[str, tuple[str, int]] = {}
        for name, decl in fields.items():
            m = _LOCAL_RE.match(decl)
            if m is None:
                raise ValueError(f"unknown local type {decl!r} for field {name!r}")
            if m.group(2) is not None and int(m.group(2)) < 2:
                raise ValueError(f"local array {decl!r} for field {name!r} needs at least 2 "
                                 f"slots; use {m.group(1)!r} for a scalar")
            parsed[name] = (m.group(1), int(m.group(2)) if m.group(2) else 1)
        object.__setattr__(self, "fields", parsed)


@dataclass(frozen=True)
class KernelSpec:
    name: str
    func: Callable[..., Any]
    module_file: str
    state: str
    local: Local | None
    commands: tuple[int, ...]
    max: Res
    substep: int | None
    params: tuple[str, ...]


def kernel(state, local=None, commands=(), max=Res(), substep=None) -> Callable:  # noqa: B008
    if substep is not None and substep < 1:
        raise ValueError("substep must be >= 1")
    commands = tuple(commands)
    seen: set[int] = set()
    for c in commands:
        if c in seen:
            raise ValueError(f"duplicate command id {c}")
        seen.add(c)

    def deco(fn: Callable) -> Callable:
        params = tuple(inspect.signature(fn).parameters)
        want = ("ctx", "s", "loc", "cmd", "out") if local is not None else (
            "ctx", "s", "cmd", "out")
        if params != want:
            raise TypeError(f"kernel {fn.__name__} must take ({', '.join(want)})")
        fn.__kernel__ = KernelSpec(
            name=fn.__name__, func=fn, module_file=inspect.getsourcefile(fn) or "",
            state=state, local=local, commands=commands, max=max, substep=substep,
            params=params,
        )
        return fn

    return deco


def is_kernel(fn: Any) -> bool:
    return isinstance(getattr(fn, "__kernel__", None), KernelSpec)
