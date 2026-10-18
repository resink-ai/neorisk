"""Instance memory, command tags, draw sites and statistics of machine processes (D63-D65)."""

from __future__ import annotations

from neorisk_simkit.spec.pack import PackError

MX_STALE = 0                      # reject(MX_STALE): a stale command (§04 "drop when popped")
MX_FIRE = 1                       # command kind of every machine timer
FIRST_RESPONSE_KIND = 2           # request-op responses take kinds 2, 3, ... (Task 8)
OP_BRANCH, OP_TIMER, OP_REPEAT, OP_CHAIN, OP_SPAWN, OP_NOW, OP_REQUEST = 1, 2, 3, 4, 5, 6, 7
GEN_MASK = (1 << 20) - 1
IMPLICIT = (("st", "i16"), ("gen", "i64"), ("ep", "i64"), ("rep", "i16"), ("mr", "i16"),
            ("t0", "i64"), ("dep", "i8"), ("par", "i8"), ("pm", "i8"), ("pep", "i64"),
            ("ord", "i8"), ("kids", "i8"), ("jb", "i64"), ("jn", "i8"), ("jl", "i8"),
            ("actor", "ref"), ("pactor", "ref"))
STATE_SITES, MAX_STATES_PER_SITEBLOCK = 16, 32
ACTION_SITE_BASE, ACTION_SITE_SPAN, MAX_COPIES = 9000, 128, 163


def tag(m: int, i: int, g: int, op: int, x: int) -> int:
    return (m << 41) | (i << 35) | ((g & GEN_MASK) << 15) | (op << 12) | x


def width(md) -> int:
    return max(2, md.max_instances)


def local_fields(machines) -> dict[str, str]:
    out: dict[str, str] = {}
    for md in machines:
        w = width(md)
        for f, t in (*IMPLICIT, *md.fields.items()):
            out[f"{md.name}__{f}"] = f"{t}[{w}]"
    return out


def state_site(md, state_index: int, j: int) -> int:
    if j >= STATE_SITES:
        raise PackError(f"machine {md.name}: state {md.states[state_index].name!r} needs more "
                        f"than {STATE_SITES} draw sites")
    return 1 + STATE_SITES * (MAX_STATES_PER_SITEBLOCK * md.index + state_index) + j


ROOT_SITE_BASE = 8193                # root blocks: START-time draws (F-09)


def root_site(md, j: int) -> int:
    if j >= STATE_SITES:
        raise PackError(f"machine {md.name}: START needs more than {STATE_SITES} draw sites")
    return ROOT_SITE_BASE + STATE_SITES * md.index + j


def action_site(copy: int, n: int) -> int:
    if copy >= MAX_COPIES:
        raise PackError(f"more than {MAX_COPIES} action copies in one machine process")
    if not 0 <= n < ACTION_SITE_SPAN:
        raise PackError(f"action draw site {n} must be in [0, {ACTION_SITE_SPAN})")
    return ACTION_SITE_BASE + ACTION_SITE_SPAN * copy + n


STAT_HEAD = ("late", "rejects", "spawned", "late_grants")   # then entries per state/final


def stat_layout(machines) -> dict[str, int]:
    base, n = {}, 0
    for md in machines:
        base[md.name] = n
        n += len(STAT_HEAD) + len(md.states) + len(md.finals)
    return base


def n_stats(machines) -> int:
    return sum(len(STAT_HEAD) + len(md.states) + len(md.finals) for md in machines)
