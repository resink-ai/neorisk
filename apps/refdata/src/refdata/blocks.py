"""Block files: SQL split into named blocks by header comments.

    -- event: order_placed owner=order_id ord=src_row
    SELECT ...;
    -- entity: sellers
    SELECT ...;

A header is `-- <kind>: <name> [key=value ...]`. A block's SQL runs to the next header.
Lines before the first header (file comments) are ignored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

HEADER = re.compile(r"^--\s*(event|entity|table)\s*:\s*(\S+)(.*)$")


@dataclass(frozen=True)
class Block:
    kind: str
    name: str
    opts: dict[str, str] = field(default_factory=dict)
    sql: str = ""


def parse_blocks(text: str, allowed: set[str]) -> list[Block]:
    heads: list[tuple[int, str, str, dict[str, str]]] = []
    bodies: list[list[str]] = []
    for i, line in enumerate(text.splitlines(), 1):
        m = HEADER.match(line.strip())
        if m:
            kind, name, rest = m.groups()
            if kind not in allowed:
                raise ValueError(f"line {i}: block kind {kind!r} not allowed here "
                                 f"(allowed: {sorted(allowed)})")
            opts = {}
            for tok in rest.split():
                k, sep, v = tok.partition("=")
                if not sep:
                    raise ValueError(f"line {i}: option {tok!r} is not key=value")
                opts[k] = v
            heads.append((i, kind, name, opts))
            bodies.append([])
        elif bodies:
            bodies[-1].append(line)
    out, seen = [], set()
    for (i, kind, name, opts), body in zip(heads, bodies, strict=True):
        if name in seen:
            raise ValueError(f"line {i}: duplicate block {name!r}")
        seen.add(name)
        sql = "\n".join(body).strip()
        if not sql:
            raise ValueError(f"line {i}: block {name!r} has no SQL")
        out.append(Block(kind, name, opts, sql))
    return out
