"""Per-machine copies of @action functions and their helpers (D65): renamed, `m.id` /
`m.parent_id` / `m.<field>` -> instance fields, `ctx.cfg` -> `ctx.cfg.c_<machine>`, and every
`site=N` literal moved into the copy's site block."""

from __future__ import annotations

import ast
import copy as _copy
import functools
from pathlib import Path

from neorisk_simkit.engine.abi import ActionSpec
from neorisk_simkit.machine import layout as L
from neorisk_simkit.spec.pack import PackError


@functools.cache
def _module(path: str) -> dict[str, ast.FunctionDef]:
    tree = ast.parse(Path(path).read_text(), path)
    return {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}


def _sub(base: str, attr: str, idx: str, ctx) -> ast.Subscript:
    return ast.Subscript(ast.Attribute(ast.Name(base, ast.Load()), attr, ast.Load()),
                         ast.Name(idx, ast.Load()), ctx)


class _Rewrite(ast.NodeTransformer):
    def __init__(self, md, copy: int, prefix: str, funcs, where: str):
        self.md, self.copy, self.prefix, self.funcs, self.where = md, copy, prefix, funcs, where
        self.called: list[str] = []

    def visit_Attribute(self, node: ast.Attribute):
        v = node.value
        if isinstance(v, ast.Name) and v.id == "m":
            mm = self.md.name
            if node.attr == "id":
                if self.md.member_table is None:
                    return ast.copy_location(ast.Attribute(ast.Name("ctx", ast.Load()), "self_id",
                                                           node.ctx), node)
                return ast.copy_location(_sub("loc", f"{mm}__actor", "mi", node.ctx), node)
            if node.attr == "parent_id":
                return ast.copy_location(_sub("loc", f"{mm}__pactor", "mi", node.ctx), node)
            if node.attr not in self.md.fields:
                raise PackError(f"{self.where}: m.{node.attr} is not a field of machine {mm}")
            return ast.copy_location(_sub("loc", f"{mm}__{node.attr}", "mi", node.ctx), node)
        if (node.attr == "cfg" and isinstance(v, ast.Name) and v.id == "ctx"):
            return ast.copy_location(ast.Attribute(
                ast.Attribute(ast.Name("ctx", ast.Load()), "cfg", ast.Load()),
                f"c_{self.md.name}", node.ctx), node)
        return self.generic_visit(node)

    def visit_Name(self, node: ast.Name):
        if node.id == "m":
            raise PackError(f"{self.where}: m may only be used as m.<field>")
        return node

    def visit_Call(self, node: ast.Call):
        f = node.func
        if isinstance(f, ast.Name) and f.id in self.funcs:
            self.called.append(f.id)
            node.func = ast.Name(f"{self.prefix}{f.id}", ast.Load())
        if (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Attribute)
                and f.value.attr == "rng"):
            for kw in node.keywords:
                if kw.arg == "site" and isinstance(kw.value, ast.Constant):
                    kw.value = ast.Constant(L.action_site(self.copy, int(kw.value.value)))
        return self.generic_visit(node)


def copy_action(spec: ActionSpec, md, copy: int) -> tuple[str, str]:
    """(name of the copy, source of the copy and of every helper it calls, transitively)."""
    funcs = _module(spec.module_file)
    prefix = f"mx_{md.name}_c{copy}_"
    done: dict[str, str] = {}
    todo = [spec.name]
    while todo:
        name = todo.pop()
        if name in done:
            continue
        fn = _copy.deepcopy(funcs[name])
        fn.decorator_list = []
        if name == spec.name:
            fn.args.args = [ast.arg(a) for a in ("ctx", "s", "loc", "cmd", "out", "mi")]
        elif any(a.arg == "m" for a in fn.args.args):
            raise PackError(f"helper {name} of action {spec.name}: pass m.<field> values, not m")
        rw = _Rewrite(md, copy, prefix, funcs, f"action {spec.name}")
        fn = rw.visit(fn)
        fn.name = f"{prefix}{name}"
        done[name] = ast.unparse(ast.fix_missing_locations(fn))
        todo += rw.called
    return f"{prefix}{spec.name}", "\n\n\n".join(done.values())
