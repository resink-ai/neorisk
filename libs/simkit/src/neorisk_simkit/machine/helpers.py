"""The closed vocabulary of machines (re-exported by `neorisk_simkit.std`): std actions, value
helpers, typed conditions, probability helpers and request descriptors. Everything here is inert
frozen data; `machine.compile` turns it into generated kernel source (D62)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from neorisk_simkit.engine.abi import ActionRef, ActionSpec
from neorisk_simkit.spec.dist import Dist
from neorisk_simkit.spec.pack import PackError


# ---------------------------------------------------------------- values
@dataclass(frozen=True)
class Actor:
    """The instance's actor: the owner (base machines) or its member row (cohort machines)."""


@dataclass(frozen=True)
class ParentActor:
    """The actor of the instance that spawned this one (std.NULL for a root instance)."""


@dataclass(frozen=True)
class Col:
    name: str                     # owner state column (read)


@dataclass(frozen=True)
class Field:
    name: str                     # declared instance field


@dataclass(frozen=True)
class NewId:
    ns: str                       # a p.ids namespace; reserves one id


@dataclass(frozen=True)
class Now:
    pass


@dataclass(frozen=True)
class After:
    delay: Dist                   # ctx.t + a draw


@dataclass(frozen=True)
class Near:
    value: int
    above: float                  # value + uniform_int(0, floor(value * above))


@dataclass(frozen=True)
class PickRef:
    refs: str                     # the owner's refs CSR (e.g. "device")
    parent_share: float | None = None   # with this probability copy the parent's field


@dataclass(frozen=True)
class Repeats:
    pass                          # the repeat count of the current state


def actor() -> Actor:
    return Actor()


def parent() -> ParentActor:
    return ParentActor()


def col(name: str) -> Col:
    return Col(name)


def field(name: str) -> Field:
    return Field(name)


def new_id(ns: str) -> NewId:
    return NewId(ns)


def now() -> Now:
    return Now()


def after(delay: Dist) -> After:
    if not isinstance(delay, Dist):
        raise PackError("std.after needs a Dist")
    return After(delay)


def near(value: int, above: float) -> Near:
    if not 0 <= above <= 10:
        raise PackError("std.near: above must be in [0, 10]")
    return Near(int(value), float(above))


def pick_ref(refs: str, parent_share: float | None = None) -> PickRef:
    if parent_share is not None and not 0.0 <= parent_share <= 1.0:
        raise PackError("std.pick_ref: parent_share must be in [0, 1]")
    return PickRef(refs, parent_share)


# ---------------------------------------------------------------- conditions and probabilities
@dataclass(frozen=True)
class Cond:
    op: str                       # "ge" | "le" | "eq"
    a: Any
    b: Any


class _Cond:
    """Typed conditions for until (D70); operands are ints, std.col/std.field or repeats."""

    @staticmethod
    def ge(a, b) -> Cond:
        return Cond("ge", a, b)

    @staticmethod
    def le(a, b) -> Cond:
        return Cond("le", a, b)

    @staticmethod
    def eq(a, b) -> Cond:
        return Cond("eq", a, b)

    @staticmethod
    def repeats_ge(n: int) -> Cond:
        return Cond("ge", Repeats(), int(n))


cond = _Cond()


@dataclass(frozen=True)
class PBy:
    col: str
    probs: tuple[tuple[str, float], ...]
    otherwise: float


def p_by(col: str, probs: dict, otherwise: float = 0.0) -> PBy:
    """A branch probability chosen by an owner state category (D71)."""
    for k, v in probs.items():
        if not isinstance(k, str) or not 0.0 <= float(v) <= 1.0:
            raise PackError(f"std.p_by: {k!r}: probabilities are floats in [0, 1] by category")
    if not 0.0 <= float(otherwise) <= 1.0:
        raise PackError(f"std.p_by: otherwise={otherwise!r} must be a float in [0, 1]")
    return PBy(col, tuple((k, float(v)) for k, v in probs.items()), float(otherwise))


# ---------------------------------------------------------------- actions
@dataclass(frozen=True)
class Emit:
    event: str
    values: tuple[tuple[str, Any], ...]


@dataclass(frozen=True)
class Spawn:
    machine: str
    n: Any                        # int | Dist | Col | Field
    stagger: Dist | None
    fields: tuple[tuple[str, Any], ...]


@dataclass(frozen=True)
class SendParent:
    msg: str


@dataclass(frozen=True)
class LabelAct:
    role: str
    outcome: str


@dataclass(frozen=True)
class CreateOwner:
    table: str
    values: tuple[tuple[str, Any], ...]


@dataclass(frozen=True)
class SetField:
    name: str
    value: Any
    add: bool


@dataclass(frozen=True)
class Part:
    act: Any                      # ActionSpec | Emit | Spawn | SendParent | LabelAct | ...
    fallback: Any = None          # one act, run when `act` rejects (D66)


@dataclass(frozen=True)
class Chain:
    parts: tuple[Part, ...]

    def then(self, other) -> Chain:
        return Chain(self.parts + as_chain(other).parts)

    def otherwise(self, other) -> Chain:
        if len(self.parts) != 1 or self.parts[0].fallback is not None:
            raise PackError(".otherwise() applies to one action; write a.then(b.otherwise(c))")
        alt = as_chain(other)
        if len(alt.parts) != 1:
            raise PackError(".otherwise() takes one action, not a chain")
        return Chain((Part(self.parts[0].act, alt.parts[0].act),))


def as_chain(x) -> Chain:
    if isinstance(x, Chain):
        return x
    if isinstance(x, ActionRef):
        return Chain((Part(x.spec),))
    raise PackError(f"expected an @action or a std action, got {type(x).__name__}")


def _one(act) -> Chain:
    return Chain((Part(act),))


def emit(event: str, **values) -> Chain:
    return _one(Emit(event, tuple(values.items())))


def spawn(machine: str, n=1, stagger: Dist | None = None, fields: dict | None = None) -> Chain:
    return _one(Spawn(machine, n, stagger, tuple((fields or {}).items())))


def send_parent(msg: str) -> Chain:
    return _one(SendParent(msg))


def label(role: str, outcome: str) -> Chain:
    return _one(LabelAct(role, outcome))


def create_owner(table: str, **values) -> Chain:
    return _one(CreateOwner(table, tuple(values.items())))


def set_field(name: str, value) -> Chain:
    return _one(SetField(name, value, False))


def add_field(name: str, value=1) -> Chain:
    return _one(SetField(name, value, True))


# ---------------------------------------------------------------- requests (D83)
@dataclass(frozen=True)
class Request:
    local: str                    # a boundary sent by the machine's partition (or acts_for)
    ok: str
    shard: Any
    store: tuple[tuple[str, str], ...]     # response payload field -> instance field
    payload: tuple[tuple[str, Any], ...]
    release: Any = None           # Chain run when an `ok` response arrives late (D67, F-35)


def request(local: str, *, ok: str = "granted", shard=0, store: dict | None = None,
            release=None, **payload) -> Request:
    return Request(local, ok, shard, tuple((store or {}).items()), tuple(payload.items()),
                   as_chain(release) if release is not None else None)


@dataclass(frozen=True)
class Send:
    local: str                    # a one-way message boundary sent by the machine's partition
    to: Any
    payload: tuple[tuple[str, Any], ...]


def send(local: str, *, to=0, **payload) -> Chain:
    """A one-way message to a shard (e.g. a refund or void that releases a late grant)."""
    return _one(Send(local, to, tuple(payload.items())))


__all__ = [
    "ActionSpec",
    "Actor",
    "After",
    "Chain",
    "Col",
    "Cond",
    "CreateOwner",
    "Emit",
    "Field",
    "LabelAct",
    "Near",
    "NewId",
    "Now",
    "PBy",
    "ParentActor",
    "Part",
    "PickRef",
    "Repeats",
    "Request",
    "Send",
    "SendParent",
    "SetField",
    "Spawn",
    "actor",
    "add_field",
    "after",
    "as_chain",
    "col",
    "cond",
    "create_owner",
    "emit",
    "field",
    "label",
    "near",
    "new_id",
    "now",
    "p_by",
    "parent",
    "pick_ref",
    "request",
    "send",
    "send_parent",
    "set_field",
    "spawn",
]
