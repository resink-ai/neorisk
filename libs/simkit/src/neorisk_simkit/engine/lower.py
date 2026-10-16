"""AST lowering of the kernel authoring surface to plain functions over tuples (decision D2).

`out.emit_x(...)`, `s.col`, `loc.f`, `cmd.x`, `ctx.cfg.f`, `ctx.reads.t.c[i]`, `ctx.rng.m(site=N)`
become tuple indexing and calls to generated helpers (`_emit_<e>`, `_rng_<m>`, ...) whose code
Task 8 generates. Anything outside the contract raises `LoweringError` naming `file:line`.
"""

from __future__ import annotations

import ast
import copy
from collections.abc import Mapping
from typing import Any

from neorisk_simkit.engine import abi
from neorisk_simkit.engine.errors import LoweringError
from neorisk_simkit.engine.layout import (
    CMD_FIELDS,
    CMD_PAY,
    CMD_PAY_ROW,
    CTX_CFG,
    CTX_PID,
    CTX_READS,
    CTX_REFS,
    CTX_SELF_ID,
    CTX_T,
    ENGINE_SITE_BASE,
    SHARD_ITEMS,
    SHARD_N,
    SHARD_OFF,
    KernelLayout,
)
from neorisk_simkit.spec.types import LType

__all__ = ["LoweringError", "lower_module"]

_ABI_CONSTS = ("COMMIT", "RETRY", "START", "PRIO_CONTINUE", "PRIO_MESSAGE", "PRIO_EXPIRY",
               "PRIO_TIMER")
PRELUDE = ("from neorisk_simkit import std\n"
           f"from neorisk_simkit.engine.abi import reject, {', '.join(_ABI_CONSTS)}\n")
_ABI_VALUES = {n: getattr(abi, n) for n in _ABI_CONSTS}
_ENGINE_MODULES = ("neorisk_simkit.engine", "neorisk_simkit.engine.abi")
VIEWS = ("ctx", "s", "loc", "cmd", "out")
_CTX_SCALARS = {"t": CTX_T, "self_id": CTX_SELF_ID, "partition_id": CTX_PID}
RNG_METHODS: dict[str, tuple[str, ...]] = {
    "uniform": (), "bernoulli": ("p",), "geometric": ("mean",), "uniform_int": ("lo", "hi"),
    "categorical": ("p",), "exp_us": ("mean_s",), "pareto_us": ("alpha", "min_h"),
    "dist_us": ("d",), "lognormal_minor": ("median", "sigma"),
}
_REFS_ARGS = {"pick": 2, "count": 1, "get": 2}

_BINOPS = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
           ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b,
           ast.FloorDiv: lambda a, b: a // b, ast.Mod: lambda a, b: a % b,
           ast.Pow: lambda a, b: a ** b, ast.LShift: lambda a, b: a << b,
           ast.RShift: lambda a, b: a >> b, ast.BitOr: lambda a, b: a | b,
           ast.BitAnd: lambda a, b: a & b, ast.BitXor: lambda a, b: a ^ b}
_UNOPS = {ast.USub: lambda a: -a, ast.UAdd: lambda a: +a, ast.Invert: lambda a: ~a,
          ast.Not: lambda a: not a}


class _NotConst(Exception):
    pass


def _const_value(node: ast.AST, env: Mapping[str, Any]) -> Any:
    """Evaluate a module-level constant expression: literals, tuples, arithmetic, names."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float, str, bool,
                                                                  type(None))):
        return node.value
    if isinstance(node, ast.Tuple):
        return tuple(_const_value(e, env) for e in node.elts)
    if isinstance(node, ast.Name) and node.id in env:
        return env[node.id]
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNOPS:
        return _UNOPS[type(node.op)](_const_value(node.operand, env))
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        return _BINOPS[type(node.op)](_const_value(node.left, env),
                                      _const_value(node.right, env))
    raise _NotConst


def _literal(v: Any) -> ast.expr:
    if isinstance(v, tuple):
        return ast.Tuple([_literal(x) for x in v], ast.Load())
    return ast.Constant(v)


def _name(id_: str) -> ast.Name:
    return ast.Name(id_, ast.Load())


def _sub(value: ast.expr, index: int | ast.expr, ctx: ast.expr_context | None = None
         ) -> ast.Subscript:
    idx = ast.Constant(index) if isinstance(index, int) else index
    return ast.Subscript(value, idx, ctx or ast.Load())


def _call(fn: str, *args: ast.expr) -> ast.Call:
    return ast.Call(_name(fn), list(args), [])


def _is_attr(node: ast.AST, base: str, attr: str) -> bool:
    return (isinstance(node, ast.Attribute) and node.attr == attr
            and isinstance(node.value, ast.Name) and node.value.id == base)


class _Module:
    """Module-level scan: constants, mutable/non-constant globals, functions."""

    def __init__(self, tree: ast.Module, filename: str):
        self.filename = filename
        self.consts: dict[str, Any] = {}
        self.mutable: set[str] = set()
        self.funcs: dict[str, ast.FunctionDef] = {}
        env = dict(_ABI_VALUES)
        for i, stmt in enumerate(tree.body):
            if i == 0 and isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
                continue                                           # module docstring
            if isinstance(stmt, ast.ImportFrom):
                ok = (stmt.module == "__future__" or stmt.module in _ENGINE_MODULES
                      or (stmt.module == "neorisk_simkit"
                          and all(a.name == "std" and a.asname is None for a in stmt.names)))
                if not ok:
                    self.err(stmt, f"unsupported import from {stmt.module!r}")
            elif isinstance(stmt, ast.FunctionDef):
                self.funcs[stmt.name] = stmt
            elif isinstance(stmt, (ast.Assign, ast.AnnAssign)) and stmt.value is not None:
                targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
                for tgt in targets:
                    self._bind(tgt, stmt.value, env)
            else:
                self.err(stmt, f"unsupported module-level statement {type(stmt).__name__}")

    def _bind(self, tgt: ast.expr, value: ast.expr, env: dict[str, Any]) -> None:
        if isinstance(tgt, ast.Name):
            try:
                v = _const_value(value, env)
            except _NotConst:
                self.mutable.add(tgt.id)
                self.consts.pop(tgt.id, None)
                env.pop(tgt.id, None)
                return
            self.consts[tgt.id] = env[tgt.id] = v
            self.mutable.discard(tgt.id)
            return
        if isinstance(tgt, ast.Tuple) and all(isinstance(e, ast.Name) for e in tgt.elts):
            if isinstance(value, ast.Tuple) and len(value.elts) == len(tgt.elts):
                for t, v in zip(tgt.elts, value.elts, strict=True):
                    self._bind(t, v, env)
                return
            for t in tgt.elts:
                self.mutable.add(t.id)
            return
        self.err(tgt, "unsupported module-level assignment target")

    def err(self, node: ast.AST, msg: str):
        raise LoweringError(f"{self.filename}:{getattr(node, 'lineno', '?')}: {msg}")


def _params(fn: ast.FunctionDef) -> list[str]:
    return [a.arg for a in fn.args.args]


def _module_calls(fn: ast.FunctionDef, mod: _Module) -> list[ast.Call]:
    return [n for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id in mod.funcs]


class _Analysis:
    """Per-process call graph and config aliases (`x = ctx.cfg`, helper params)."""

    def __init__(self, mod: _Module, layout: KernelLayout, root: str):
        self.mod, self.layout = mod, layout
        self.graph: list[str] = [root]
        i = 0
        while i < len(self.graph):
            for c in _module_calls(mod.funcs[self.graph[i]], mod):
                if c.func.id not in self.graph:
                    self.graph.append(c.func.id)
            i += 1
        self.param_alias: dict[str, dict[str, tuple[str, ...]]] = {f: {} for f in self.graph}
        self.aliases: dict[str, dict[str, tuple[str, ...]]] = {}
        for _ in range(len(self.graph) + 2):
            sites = self._sweep()
            new = {f: {} for f in self.graph}
            for h, binds in sites.items():
                for p in _params(mod.funcs[h]):
                    paths = {b.get(p) for b in binds}
                    if len(paths) == 1 and None not in paths:
                        new[h][p] = paths.pop()
            if new == self.param_alias:
                break
            self.param_alias = new
        for h, binds in self._sweep().items():
            for p in _params(mod.funcs[h]):
                paths = {b.get(p) for b in binds}
                if len(paths) > 1 and any(x is not None for x in paths):
                    mod.err(mod.funcs[h], f"helper {h}: parameter {p!r} is a config alias at "
                                          "some call sites but not at others")

    def cfg_path(self, node: ast.AST, aliases: Mapping[str, tuple[str, ...]]
                 ) -> tuple[str, ...] | None:
        """Path of a config sub-tuple the expression denotes (root or nested), else None."""
        if isinstance(node, ast.Name):
            return aliases.get(node.id)
        if _is_attr(node, "ctx", "cfg"):
            return ()
        if isinstance(node, ast.Attribute):
            base = self.cfg_path(node.value, aliases)
            if base is not None and ".".join((*base, node.attr)) in self.layout.cfg_nested:
                return (*base, node.attr)
        return None

    def _local_aliases(self, f: str) -> dict[str, tuple[str, ...]]:
        fn = self.mod.funcs[f]
        aliases = dict(self.param_alias[f])
        changed = True
        while changed:
            changed = False
            for n in ast.walk(fn):
                if (isinstance(n, ast.Assign) and len(n.targets) == 1
                        and isinstance(n.targets[0], ast.Name)
                        and n.targets[0].id not in aliases):
                    p = self.cfg_path(n.value, aliases)
                    if p is not None:
                        aliases[n.targets[0].id] = p
                        changed = True
        for n in ast.walk(fn):
            if isinstance(n, ast.Assign):
                for t in n.targets:
                    if (isinstance(t, ast.Name) and t.id in aliases
                            and self.cfg_path(n.value, aliases) != aliases[t.id]):
                        self.mod.err(n, f"config alias {t.id!r} is reassigned")
            elif isinstance(n, (ast.AugAssign, ast.AnnAssign, ast.For)):
                t = n.target
                if isinstance(t, ast.Name) and t.id in aliases:
                    self.mod.err(n, f"config alias {t.id!r} is reassigned")
        return aliases

    def _sweep(self) -> dict[str, list[dict[str, tuple[str, ...] | None]]]:
        sites: dict[str, list[dict[str, tuple[str, ...] | None]]] = {}
        for f in self.graph:
            aliases = self.aliases[f] = self._local_aliases(f)
            views = set(_params(self.mod.funcs[f])) & set(VIEWS)
            for c in _module_calls(self.mod.funcs[f], self.mod):
                h = c.func.id
                params = _params(self.mod.funcs[h])
                bound: dict[str, ast.expr] = {}
                for i, a in enumerate(c.args):
                    if isinstance(a, ast.Starred) or i >= len(params):
                        self.mod.err(c, f"call of helper {h}: unsupported positional arguments")
                    bound[params[i]] = a
                for k in c.keywords:
                    if k.arg is None or k.arg not in params:
                        self.mod.err(c, f"call of helper {h}: unsupported keyword arguments")
                    bound[k.arg] = k.value
                for p, a in bound.items():
                    if isinstance(a, ast.Name) and a.id in views and p != a.id:
                        self.mod.err(c, f"helper {h}: pass {a.id!r} as the parameter named "
                                        f"{a.id!r} (got {p!r})")
                sites.setdefault(h, []).append(
                    {p: self.cfg_path(a, aliases) for p, a in bound.items()})
        return sites


class _Lowerer(ast.NodeTransformer):
    def __init__(self, mod: _Module, an: _Analysis, layout: KernelLayout, fn: ast.FunctionDef,
                 sites: dict[int, int]):
        self.mod, self.an, self.lay, self.fn, self.sites = mod, an, layout, fn, sites
        self.proc = layout.name
        self.aliases = an.aliases[fn.name]
        self.views = set(_params(fn)) & set(VIEWS)
        self.locals = set(_params(fn)) | {
            n.id for n in ast.walk(fn) if isinstance(n, ast.Name)
            and isinstance(n.ctx, ast.Store)}

    def err(self, node: ast.AST, msg: str):
        self.mod.err(node, msg)

    def _view(self, node: ast.AST, name: str) -> bool:
        return isinstance(node, ast.Name) and node.id == name and name in self.views

    def _need(self, node: ast.AST, *names: str) -> None:
        for n in names:
            if n not in self.views:
                self.err(node, f"{n!r} must be in scope (a parameter named {n!r})")

    # ------------------------------------------------------------------ names and categories
    def visit_Name(self, node: ast.Name) -> ast.AST:
        if (isinstance(node.ctx, ast.Load) and node.id not in self.locals
                and node.id in self.mod.mutable):
            self.err(node, f"mutable module global {node.id!r} used in {self.proc}")
        return node

    def _cats(self, node: ast.AST) -> tuple[str, tuple[str, ...]] | None:
        if (isinstance(node, ast.Attribute) and self._view(node.value, "s")
                and node.attr in self.lay.state_cats):
            return f"s.{node.attr}", self.lay.state_cats[node.attr]
        if isinstance(node, ast.Subscript):
            v = node.value
            if (isinstance(v, ast.Attribute) and isinstance(v.value, ast.Attribute)
                    and self._is_reads(v.value.value)):
                cats = self.lay.read_cats.get(v.value.attr, {}).get(v.attr)
                if cats is not None:
                    return f"ctx.reads.{v.value.attr}.{v.attr}", cats
        return None

    def _code(self, node: ast.Constant, what: str, cats: tuple[str, ...]) -> ast.Constant:
        if node.value not in cats:
            self.err(node, f"{node.value!r} is not a category of {what} {cats}")
        return ast.copy_location(ast.Constant(cats.index(node.value)), node)

    @staticmethod
    def _is_str(node: ast.AST) -> bool:
        return isinstance(node, ast.Constant) and isinstance(node.value, str)

    def visit_Compare(self, node: ast.Compare) -> ast.AST:
        ops = [node.left, *node.comparators]
        for i, op in enumerate(node.ops):
            if not isinstance(op, (ast.Eq, ast.NotEq)):
                continue
            for a, b in ((i, i + 1), (i + 1, i)):
                c = self._cats(ops[a])
                if c is not None and self._is_str(ops[b]):
                    ops[b] = self._code(ops[b], *c)
        node.left, node.comparators = ops[0], ops[1:]
        return self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> ast.AST:
        if self._is_str(node.value):
            for t in node.targets:
                c = self._cats(t)
                if c is not None:
                    node.value = self._code(node.value, *c)
        return self.generic_visit(node)

    # ------------------------------------------------------------------ attribute access
    def _is_reads(self, node: ast.AST) -> bool:
        return _is_attr(node, "ctx", "reads") and "ctx" in self.views

    def _cfg(self, node: ast.AST) -> tuple[ast.expr, tuple[str, ...]] | None:
        if isinstance(node, ast.Name) and node.id in self.aliases:
            return node, self.aliases[node.id]
        if _is_attr(node, "ctx", "cfg") and "ctx" in self.views:
            return _sub(_name("ctx"), CTX_CFG), ()
        if isinstance(node, ast.Attribute):
            base = self._cfg(node.value)
            if base is None:
                return None
            expr, path = base
            key = ".".join(path)
            if path and key not in self.lay.cfg_nested:
                self.err(node, f"config field {key!r} has no field {node.attr!r}")
            fields = self.lay.cfg_nested[key] if path else self.lay.cfg_fields
            if node.attr not in fields:
                self.err(node, f"unknown config field {node.attr!r} in {self.proc}")
            return _sub(expr, fields[node.attr]), (*path, node.attr)
        return None

    def _read(self, node: ast.Attribute) -> ast.expr:
        t, col = node.value.attr, node.attr
        if t not in self.lay.reads:
            self.err(node, f"unknown read table {t!r} in {self.proc}")
        cols = self.lay.reads[t]
        if not isinstance(node.ctx, ast.Load):
            self.err(node, f"ctx.reads.{t} is read-only")
        reads = _sub(_name("ctx"), CTX_READS)
        if col == "n" and "n" not in cols:
            if self.lay.read_n.get(t) is not None:
                return ast.Constant(self.lay.read_n[t])
            if not cols:
                self.err(node, f"ctx.reads.{t} has no column to take the row count from")
            first = _sub(reads, min(cols.values()))
            return _sub(ast.Attribute(first, "shape", ast.Load()), 0)
        if col not in cols:
            self.err(node, f"unknown column {col!r} of ctx.reads.{t}")
        return _sub(reads, cols[col])

    def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
        v = node.value
        if isinstance(v, ast.Name) and v.id in self.views and v.id not in self.aliases:
            return ast.copy_location(self._view_attr(node), node)
        if isinstance(v, ast.Attribute) and self._is_reads(v.value):
            return ast.copy_location(self._read(node), node)
        cfg = self._cfg(node)
        if cfg is not None:
            if not isinstance(node.ctx, ast.Load):
                self.err(node, "the process config is read-only")
            return ast.copy_location(cfg[0], node)
        return self.generic_visit(node)

    def _view_attr(self, node: ast.Attribute) -> ast.expr:
        view, a, lay, store = node.value.id, node.attr, self.lay, node.ctx
        if view == "ctx":
            if a in _CTX_SCALARS:
                if not isinstance(store, ast.Load):
                    self.err(node, f"ctx.{a} is read-only")
                return _sub(_name("ctx"), _CTX_SCALARS[a])
            if a == "cfg":
                return _sub(_name("ctx"), CTX_CFG)
            if a in ("rng", "reads", "refs"):
                self.err(node, f"ctx.{a} can only be used as ctx.{a}.<name>...")
            self.err(node, f"unknown ctx attribute {a!r}")
        if view == "s":
            if a in lay.state_fields:
                i = lay.state_fields[a]
                return _sub(_sub(_name("s"), i), _sub(_name("s"), 0), store)
            if lay.items_name is not None and a == f"n_{lay.items_name}":
                if not isinstance(store, ast.Load):
                    self.err(node, f"s.{a} is read-only")
                return _sub(_name("s"), SHARD_N)
            if a in lay.array_fields or (a == lay.items_name and a is not None):
                self.err(node, f"s.{a} is per item and must be indexed: s.{a}[i]")
            self.err(node, f"unknown state field {a!r} in {self.proc}")
        if view == "loc":
            if not lay.local_fields:
                self.err(node, f"process {self.proc} has no local state")
            if a not in lay.local_fields:
                self.err(node, f"unknown local field {a!r} in {self.proc}")
            j, width = lay.local_fields[a]
            if width > 1:
                self.err(node, f"loc.{a} has {width} slots and must be indexed: loc.{a}[i]")
            return _sub(_sub(_name("loc"), j), _sub(_name("loc"), 0), store)
        if view == "cmd":
            if not isinstance(store, ast.Load):
                self.err(node, "cmd is read-only")
            if a in CMD_FIELDS:
                return _sub(_name("cmd"), CMD_FIELDS.index(a))
            if a in lay.payload_slots:
                row = ast.Tuple([_sub(_name("cmd"), CMD_PAY_ROW),
                                 ast.Constant(lay.payload_slots[a])], ast.Load())
                return _sub(_sub(_name("cmd"), CMD_PAY), row)
            self.err(node, f"unknown cmd field {a!r} in {self.proc}")
        self.err(node, f"out.{a} must be called")
        raise AssertionError  # unreachable

    def visit_Subscript(self, node: ast.Subscript) -> ast.AST:
        v = node.value
        if isinstance(v, ast.Attribute) and self._view(v.value, "s") and (
                v.attr in self.lay.array_fields
                or (v.attr == self.lay.items_name and v.attr is not None)):
            col = (SHARD_ITEMS if v.attr == self.lay.items_name
                   else self.lay.array_fields[v.attr])
            if col == SHARD_ITEMS and not isinstance(node.ctx, ast.Load):
                self.err(node, f"s.{v.attr} is read-only")
            idx = ast.BinOp(_sub(_name("s"), SHARD_OFF), ast.Add(), self.visit(node.slice))
            return ast.copy_location(_sub(_sub(_name("s"), col), idx, node.ctx), node)
        if (isinstance(v, ast.Attribute) and self._view(v.value, "loc")
                and v.attr in self.lay.local_fields and self.lay.local_fields[v.attr][1] > 1):
            j = self.lay.local_fields[v.attr][0]
            idx = ast.Tuple([_sub(_name("loc"), 0), self.visit(node.slice)], ast.Load())
            return ast.copy_location(_sub(_sub(_name("loc"), j), idx, node.ctx), node)
        return self.generic_visit(node)

    # ------------------------------------------------------------------ calls
    def visit_Call(self, node: ast.Call) -> ast.AST:
        f = node.func
        if isinstance(f, ast.Attribute):
            if self._view(f.value, "out"):
                return ast.copy_location(self._out_call(node, f.attr), node)
            if _is_attr(f.value, "ctx", "rng") and "ctx" in self.views:
                return ast.copy_location(self._rng_call(node, f.attr), node)
            if isinstance(f.value, ast.Attribute) and self._is_reads(f.value.value) \
                    and f.attr == "sample_by_weight":
                return ast.copy_location(self._sample_by_weight(node, f.value.attr), node)
            if isinstance(f.value, ast.Attribute) and _is_attr(f.value.value, "ctx", "refs") \
                    and "ctx" in self.views:
                return ast.copy_location(self._refs_call(node, f.value.attr, f.attr), node)
        return self.generic_visit(node)

    def _kwargs(self, node: ast.Call, what: str) -> dict[str, ast.expr]:
        out: dict[str, ast.expr] = {}
        for k in node.keywords:
            if k.arg is None:
                self.err(node, f"{what}: **kwargs are not supported")
            out[k.arg] = k.value
        return out

    def _positional(self, node: ast.Call, what: str, n_min: int, n_max: int) -> list[ast.expr]:
        if any(isinstance(a, ast.Starred) for a in node.args):
            self.err(node, f"{what}: *args are not supported")
        if not n_min <= len(node.args) <= n_max:
            want = str(n_min) if n_min == n_max else f"{n_min} to {n_max}"
            self.err(node, f"{what} takes {want} positional argument(s), got {len(node.args)}")
        return list(node.args)

    def _rng_call(self, node: ast.Call, m: str) -> ast.expr:
        if m not in RNG_METHODS:
            self.err(node, f"unknown rng method {m!r}")
        what = f"ctx.rng.{m}"
        self._positional(node, what, 0, 0)
        kw = self._kwargs(node, what)
        site = kw.pop("site", None)
        if not (isinstance(site, ast.Constant) and type(site.value) is int):
            self.err(node, f"{what}: site= must be an int literal")
        if not 0 <= site.value < ENGINE_SITE_BASE:
            self.err(node, f"site {site.value} must be in [0, {ENGINE_SITE_BASE}) (higher sites "
                           "are reserved for engine draws)")
        if site.value in self.sites:
            self.err(node, f"site {site.value} used twice in {self.proc}")
        self.sites[site.value] = node.lineno
        args = [_name("ctx"), ast.Constant(site.value)]
        for p in RNG_METHODS[m]:
            if p not in kw:
                self.err(node, f"{what}: missing argument {p!r}")
            args.append(self.visit(kw.pop(p)))
        if kw:
            self.err(node, f"{what}: unknown argument {min(kw)!r}")
        return ast.Call(_name(f"_rng_{m}"), args, [])

    def _sample_by_weight(self, node: ast.Call, t: str) -> ast.expr:
        if t not in self.lay.reads:
            self.err(node, f"unknown read table {t!r} in {self.proc}")
        if "cumw" not in self.lay.reads[t]:
            self.err(node, f"ctx.reads.{t} has no weights (cumw) for sample_by_weight")
        (u,) = self._positional(node, f"ctx.reads.{t}.sample_by_weight", 1, 1)
        if node.keywords:
            self.err(node, "sample_by_weight takes no keyword arguments")
        arr = _sub(_sub(_name("ctx"), CTX_READS), self.lay.reads[t]["cumw"])
        return _call("_reads_sample_by_weight", arr, self.visit(u))

    def _refs_call(self, node: ast.Call, r: str, m: str) -> ast.expr:
        if r not in self.lay.refs:
            self.err(node, f"unknown refs {r!r} in {self.proc}")
        if m not in _REFS_ARGS:
            self.err(node, f"unknown refs method {m!r} (pick, count, get)")
        n = _REFS_ARGS[m]
        args = self._positional(node, f"ctx.refs.{r}.{m}", n, n)
        if node.keywords:
            self.err(node, f"ctx.refs.{r}.{m} takes no keyword arguments")
        j = self.lay.refs[r]
        refs = _sub(_name("ctx"), CTX_REFS)
        return _call(f"_refs_{m}", _sub(refs, j), _sub(refs, j + 1),
                     *(self.visit(a) for a in args))

    def _columns(self, node: ast.Call, cols: list[tuple[str, LType]], kw: dict[str, ast.expr],
                 what: str) -> list[ast.expr]:
        names = {c for c, _ in cols}
        for k in kw:
            if k not in names:
                self.err(node, f"{what}: unknown column {k!r}")
        out: list[ast.expr] = []
        for c, lt in cols:
            if c in kw:
                v = kw[c]
                if lt.kind == "cat" and self._is_str(v):
                    out.append(self._code(v, f"column {c!r}", lt.values))
                else:
                    out.append(self.visit(v))
            elif lt.nullable:
                out.append(ast.Attribute(_name("std"), "NULL", ast.Load()))
            else:
                self.err(node, f"{what}: missing required column {c!r}")
        return out

    def _pop_arg(self, node: ast.Call, kw: dict[str, ast.expr], pos: list[ast.expr], i: int,
                 name: str, default: ast.expr | None, what: str) -> ast.expr:
        if i < len(pos):
            if name in kw:
                self.err(node, f"{what}: {name} given twice")
            return self.visit(pos[i])
        if name in kw:
            return self.visit(kw.pop(name))
        if default is None:
            self.err(node, f"{what}: missing argument {name!r}")
        return default

    def _out_call(self, node: ast.Call, m: str) -> ast.expr:
        lay, what = self.lay, f"out.{m}"
        self._need(node, "ctx")
        out, ctx = _name("out"), _name("ctx")
        kw = self._kwargs(node, what)
        if m == "reserve":
            return self._reserve(node, kw)
        if m.startswith("emit_") and m[5:] in lay.events:
            (t,) = self._positional(node, what, 1, 1)
            cols = self._columns(node, lay.events[m[5:]], kw, what)
            return _call(f"_{m}", out, ctx, self.visit(t), *cols)
        if m.startswith("create_") and lay.creates.get(m[7:]) is not None:
            self._positional(node, what, 0, 0)
            return _call(f"_{m}", out, ctx, *self._columns(node, lay.creates[m[7:]], kw, what))
        if m == "new_id":
            (ns,) = self._positional(node, what, 1, 1)
            if not (self._is_str(ns) and ns.value in lay.creates) or kw:
                self.err(node, "out.new_id takes one namespace name as a string literal")
            return _call("_new_id", out, ctx, ast.Constant(list(lay.creates).index(ns.value)))
        if m == "timer":
            pos = self._positional(node, what, 2, 4)
            t, kind = self.visit(pos[0]), self.visit(pos[1])
            prio = self._pop_arg(node, kw, pos, 2, "prio", _name("PRIO_TIMER"), what)
            tag = self._pop_arg(node, kw, pos, 3, "tag", ast.Constant(0), what)
            if kw:
                self.err(node, f"{what}: unknown argument {min(kw)!r}")
            return _call("_timer", out, ctx, t, kind, prio, tag)
        for prefix, table, dest in (("request_", lay.requests, "shard"),
                                    ("send_", lay.messages, "to")):
            if m.startswith(prefix) and m[len(prefix):] in table:
                b = lay.boundary_of[m[len(prefix):]]
                (t,) = self._positional(node, what, 1, 1)
                if dest not in kw:
                    self.err(node, f"{what}: missing argument {dest!r}")
                d = self.visit(kw.pop(dest))
                tag = self.visit(kw.pop("tag")) if "tag" in kw else ast.Constant(0)
                pay = self._columns(node, lay.out_payload[b], kw, what)
                return _call(f"_{prefix}{b}", out, ctx, self.visit(t), d, tag, *pay)
        if m == "respond":
            c, resp = self._positional(node, what, 2, 2)
            if len(lay.responses) != 1:
                self.err(node, f"out.respond needs exactly one handled request boundary in "
                               f"{self.proc}, found {len(lay.responses)}")
            ((b, names),) = lay.responses.items()
            if not (self._is_str(resp) and resp.value in names):
                self.err(node, f"out.respond: response must be one of {names} as a literal")
            pay = self._columns(node, lay.response_payload[b], kw, what)
            return _call(f"_respond_{b}_{resp.value}", out, ctx, self.visit(c), *pay)
        if m == "continue_at":
            pos = self._positional(node, what, 1, 2)
            t = self.visit(pos[0])
            cur = self._pop_arg(node, kw, pos, 1, "cursor", None, what)
            if kw:
                self.err(node, f"{what}: unknown argument {min(kw)!r}")
            return _call("_continue_at", out, ctx, t, cur)
        if m.startswith("change_") and m[7:] in lay.change_groups:
            self._need(node, "s")
            (t,) = self._positional(node, what, 1, 1)
            cols = self._columns(node, lay.change_groups[m[7:]], kw, what)
            return _call(f"_{m}", out, ctx, _name("s"), self.visit(t), *cols)
        self.err(node, f"unknown out method {m!r} in {self.proc}")
        raise AssertionError  # unreachable

    def _reserve(self, node: ast.Call, kw: dict[str, ast.expr]) -> ast.expr:
        self._positional(node, "out.reserve", 0, 0)
        res = self.lay.resources
        vec: list[ast.expr] = [ast.Constant(0) for _ in res]
        seen: dict[str, set[str]] = {}
        for k, v in kw.items():
            if k in ("timers", "requests"):
                vec[res.index(k)] = self.visit(v)
            elif k in ("records", "creates"):
                if not isinstance(v, ast.Dict):
                    self.err(node, f"out.reserve: {k}= must be a dict literal")
                for key, val in zip(v.keys, v.values, strict=True):
                    if not self._is_str(key):
                        self.err(node, f"out.reserve: {k}= keys must be string literals")
                    name = key.value
                    if name in seen.setdefault(k, set()):
                        self.err(node, f"out.reserve: duplicate key {name!r} in {k}=")
                    seen[k].add(name)
                    if k == "records" and name not in self.lay.events \
                            and name not in self.lay.change_groups:
                        self.err(node, f"out.reserve: {self.proc} does not write records "
                                       f"of {name!r}")
                    if k == "creates" and name not in self.lay.creates:
                        self.err(node, f"out.reserve: unknown namespace {name!r}")
                    vec[res.index(f"{k}:{name}")] = self.visit(val)
            else:
                self.err(node, f"out.reserve: unknown argument {k!r}")
        return _call(f"_reserve_{self.proc}", _name("out"), ast.Tuple(vec, ast.Load()))


def _check_strings(mod: _Module, fn: ast.FunctionDef) -> None:
    """After lowering, a str literal may not meet a compare or a state/local store: category
    literals were translated to codes, so any left over would compare int with str silently."""
    def is_str(n: ast.AST) -> bool:
        return isinstance(n, ast.Constant) and isinstance(n.value, str)

    for n in ast.walk(fn):
        if isinstance(n, ast.Compare) and any(
                isinstance(op, (ast.Eq, ast.NotEq)) for op in n.ops) and any(
                is_str(x) for x in (n.left, *n.comparators)):
            mod.err(n, "string literal compared with a non-category expression")
        if isinstance(n, (ast.Assign, ast.AugAssign)) and is_str(n.value):
            targets = n.targets if isinstance(n, ast.Assign) else [n.target]
            for t in targets:
                if isinstance(t, ast.Subscript):
                    mod.err(n, f"string literal assigned to {ast.unparse(t)} "
                               "(not a category column)")


def _lower_function(mod: _Module, an: _Analysis, layout: KernelLayout, name: str,
                    is_kernel: bool, sites: dict[int, int]) -> str:
    fn = mod.funcs[name]
    if fn.decorator_list and not is_kernel:
        mod.err(fn, f"helper {name} must not be decorated")
    new = copy.deepcopy(fn)                    # lowering mutates; the module AST stays pristine
    new.decorator_list = []
    lowered = _Lowerer(mod, an, layout, new, sites).visit(new)
    _check_strings(mod, lowered)
    return ast.unparse(ast.fix_missing_locations(lowered))


def lower_module(source: str, layouts: Mapping[str, KernelLayout],
                 kernel_funcs: Mapping[str, str], filename: str = "<kernels>") -> str:
    """Lower the kernels named in `kernel_funcs` (function -> process) and their helpers."""
    try:
        tree = ast.parse(source, filename)
    except SyntaxError as e:
        raise LoweringError(f"{filename}:{e.lineno}: {e.msg}") from None
    mod = _Module(tree, filename)
    lowered: dict[str, tuple[str, str]] = {}            # function -> (source, first process)
    for fname, proc in kernel_funcs.items():
        if fname not in mod.funcs:
            raise LoweringError(f"{filename}: kernel function {fname!r} not found")
        if proc not in layouts:
            raise LoweringError(f"{filename}: no layout for process {proc!r}")
        layout = layouts[proc]
        an = _Analysis(mod, layout, fname)
        sites: dict[int, int] = {}
        for f in an.graph:
            src = _lower_function(mod, an, layout, f, f in kernel_funcs, sites)
            if f in lowered and lowered[f][0] != src:
                mod.err(mod.funcs[f], f"helper {f} is shared by kernels with different state "
                                      f"({lowered[f][1]} and {proc})")
            lowered.setdefault(f, (src, proc))
    parts = [PRELUDE]
    consts = [f"{n} = {ast.unparse(_literal(v))}" for n, v in mod.consts.items()
              if n not in _ABI_VALUES]
    if consts:
        parts.append("\n".join(consts) + "\n")
    parts += [lowered[f][0] + "\n" for f in mod.funcs if f in lowered]
    return "\n\n".join(parts)
