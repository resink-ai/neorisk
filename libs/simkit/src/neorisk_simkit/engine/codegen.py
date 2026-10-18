"""Generate the engine module of a plan: lowered kernels plus typed emitters (decision D2).

The text produced by `generate_module` is self-contained Python that `engine.build` writes to the
JIT cache and imports. Every function in it is `@njit(cache=True, nogil=True, boundscheck=...)`.
Generated helpers index the `out` tuple (`engine.slabs`) with module-level integer constants, so
Numba resolves every buffer access statically. Numba exceptions take constant strings (plus
runtime scalars), so helpers that can be called by several processes branch on `ctx.action` and
raise one constant message per process, prefixed `<process>: `.

`dispatch(action, ctx, cmd, world_state, out)` calls the kernel of `action`. Its `ctx` is the
runner's: `cfg`, `reads` and `refs` are tuples indexed by action id (one process's config, read
arrays and refs CSR pairs each), and dispatch passes the kernel a `ctx` narrowed to its own
entries (process configs differ in type, so one `ctx` type cannot serve every kernel). It also
records `cmd.kind` in `out[OUT_CMD_KIND]` for `_continue_at`. `world_state` holds one entry per
process, in plan (action id) order:
- owner process: `(lslot, state_cols[, local_cols])` — `lslot` is the hidden `lslot` array
  (length G), `state_cols` the owner table's column arrays in table order, `local_cols` the
  process's `Local` arrays in declaration order (present only when the kernel declares `local`).
- shard process: `(lslot, offs, items, state_cols[, local_cols])` — `lslot[g]` is the shard
  index, `offs` the items CSR offsets (length n + 1), `items` the item rows grouped by shard,
  `state_cols` the shard state arrays in declaration order.
"""

from __future__ import annotations

import ast
import functools
import hashlib
from collections.abc import Callable
from pathlib import Path

import numba

from neorisk_simkit.engine import slabs
from neorisk_simkit.engine.admit import ADM_CAP, ADM_DEPTH, ADM_LIVE, ADM_NODES, ADM_OK
from neorisk_simkit.engine.cmdq import NULL_CAUSE, P_CEID, P_CPID, PAYLOAD_W, UNSET_CAUSE
from neorisk_simkit.engine.errors import LoweringError
from neorisk_simkit.engine.layout import (
    CMD_PAY,
    CMD_PAY_ROW,
    CTX_FIELDS,
    ENGINE_SITE_BASE,
    kernel_layouts,
    resource_names,
)
from neorisk_simkit.engine.lower import lower_module
from neorisk_simkit.spec.plan import Plan, ProcessDef

SEND_KEY_BASE = ENGINE_SITE_BASE   # latency: key_uniform(seed, inst, 30000 + b, lamport, j, k)
ORDINAL_LIMIT = 1 << 24        # per-step create ordinal field of a provisional handle (D11)
_PER_ACTION = ("cfg", "reads", "refs")   # dispatch's ctx holds these per action id

# ---------------------------------------------------------------- partition runner contract
# Statuses returned by the generated `run_partitions` (with the slot index to resume from).
# Every commit appends `(pid, lamport, cpid, cause lamport, ceid)` of its command to the worker's
# commit log (`out[OUT_CLOG]`, D80); a full log returns NEED_SWAP with `miss = -1` (a flush).
DONE, NEED_SWAP, NEED_NODES = 0, 1, 2
# The world tuple `W` passed to `run_partitions` (built by `engine.world.World`):
#   hid       every hidden array, in `world.HIDDEN_DTYPES` order
#   pool/pay  `NodePool.as_tuple()` / `PayloadPool.as_tuple()`
#   state     `world_state` (see `dispatch`)
#   args      (cfg, reads, refs): one tuple per action id each (the runner ctx's per-action parts)
#   seed      run seed; counters int64[workers, len(COUNTERS)]; rejects int64[workers, actions]
#   occ_col   int64[actions]: the process's column in `occ` (index within its partition type)
#   retire    uint8[32]: retire_when_idle per ptype code
#   every     int64[actions]: period of a periodic process (0 = not periodic); jitter
#             float64[actions, 4]: encoded jitter Dist (code -1 = none); sim_start int64
#   kc        int64[workers, 33]: rng site counters; nopay int64[1, PAYLOAD_W] (no payload)
#   node_cap  int64: forced size of a worker's node free list (`force_capacity["timers"]`), or
#             -1. A list above it makes the runner return NEED_NODES before the next dispatch,
#             and `World` trims it back to the reserve.
#   bnd_delta int64[boundaries]: minimum latency (delta) of each boundary; a commit that makes
#             requests suspends its owner with susp_t = earliest request time and susp_delta =
#             the smallest delta among those requests (the safe horizon reads both).
#   ostate    one entry per owner partition type (plan order): its state column arrays in table
#             order (admission writes a created owner's columns there, D44)
#   max_depth int64[actions]: the spawn depth a process may create at, its own
#             max_spawn_depth or budget.max_spawn_depth (D72)
WORLD_FIELDS = ("hid", "pool", "pay", "state", "args", "seed", "counters", "rejects", "occ_col",
                "retire", "every", "jitter", "sim_start", "kc", "nopay", "node_cap", "bnd_delta",
                "ostate", "max_depth")
# `commands` counts executed commands (commits and rejects); rounds use it to measure progress.
COUNTERS = ("retries", "continuations", "late_messages", "retry_streak", "commands")

# ---------------------------------------------------------------- compiled rounds contract (D4)
# `drain_small_rounds(W, out, R, CQ, FS, run, n_run, t1, min_par, shard_lo, shard_hi, sbuf, log,
# rs, adm_buf)` runs rounds on worker 0 until one of these (returned with the runnable count left
# in `run`):
DR_CLOSED, DR_LARGE, DR_PYTHON, DR_LOG_FULL, DR_NO_PROGRESS = 0, 1, 2, 3, 4
# On DR_PYTHON the current round stopped in phase rs[RS_PHASE] (one of PH_*); rs[RS_STATUS] is
# the runner, route or admission status that needs Python, rs[RS_H] the round's horizon (shard
# phase and later) and rs[RS_C0] the command count when its shard phase began. rs[RS_NLOG]
# counts the rounds finished in compiled code; log[i] = (owners run, shard commands) of each.
# rs[RS_SHARD_NS] accumulates the wall nanoseconds spent in shard phases (`_now_ns()` around each
# compiled shard phase); `run_step` zeroes it at step start and reads it at step end (Task 19).
# Phase PH_ADMIT admits the round's due creations (`admit_created`, D44) into `adm_buf`; a
# non-OK admission status changed nothing (all or nothing), so Python simply admits again.
PH_OWNERS, PH_ROUTE1, PH_SHARDS, PH_ROUTE2, PH_ADMIT = 0, 1, 2, 3, 4
RS_PHASE, RS_STATUS, RS_H, RS_C0, RS_NLOG, RS_SHARD_NS = 0, 1, 2, 3, 4, 5
MAX_RETRIES = 8                # consecutive RETRYs of one command before the run fails
PERIODIC_QUEUED = 1 << 62      # START tag bit: the next periodic occurrence is already queued
PERIODIC_SITE = ENGINE_SITE_BASE + 10000         # phase draw of a periodic process (D26)
JITTER_SITE = ENGINE_SITE_BASE + 10001           # jitter draws of a periodic process (D26)

_HEADER = '''\
# Generated by neorisk_simkit.engine.codegen -- do not edit.
import math

import numpy as np
from numba import njit

from neorisk_simkit import std
from neorisk_simkit.engine.abi import (
    COMMIT, PRIO_CONTINUE, PRIO_EXPIRY, PRIO_MESSAGE, PRIO_TIMER, RETRY, START, reject,
)
from neorisk_simkit.engine.admit import (
    CQ_ACTION, CQ_CAUSE, CQ_HANDLE, CQ_K, CQ_N, CQ_NS, CQ_PAYLOAD, CQ_SRC_G, CQ_SRC_PID, CQ_TIME,
    FS_BASE, FS_N, cq_due, cq_min, cq_order, cq_remove, fs_take1,
)
from neorisk_simkit.engine.clock import clock_ns as _clock_ns
from neorisk_simkit.engine.cmdq import (
    P_FREE_N, PAY_CONTINUE, PAY_KIND, pay_free, q_free, q_push, q_remove,
)
from neorisk_simkit.engine.errors import AbiViolation, EngineError
from neorisk_simkit.engine.identity import make_handle
from neorisk_simkit.engine.rng import (
    as_i64, bernoulli, categorical, geometric, key_uniform, mix4, next_k, normal, sample_us,
    uniform_int,
)
from neorisk_simkit.engine.route import (
    RT_ADM, RT_POOL, RT_WOKEN, RT_WOKEN_N, command_count, drop_queue, horizon, mark_all,
    mark_touched, note_suspended, only_owner_messages, route_outbox, sender_keys, shards_below,
    take_runnable,
)
from neorisk_simkit.spec.dist import EXP, PARETO
'''

_JIT = "@njit(cache=True, nogil=True, boundscheck=CHECKED)"
# Kernels and the helpers they call take the `out` slab tuple and `ctx` (hundreds of arrays) by
# value. A real call increfs and decrefs every array in them (~10 µs per owner command), so they
# are inlined at the Numba IR level into `dispatch`, where the refcount pairs fold away. The
# runner-level functions (dispatch, run_partitions, ...) stay ordinary calls.
_JIT_INLINE = "@njit(cache=True, nogil=True, boundscheck=CHECKED, inline='always')"
# Generated functions that stay real calls (everything else is inlined into its caller).
_NOT_INLINED = frozenset({"dispatch", "periodic_time", "_out_of_order", "_unpaired",
                          "run_partitions", "drain_small_rounds", "_same", "_checked_dispatch",
                          "admit_created"})
_NOT_INLINED_PREFIXES = ("_snap_", "_unchanged_")

_PKG = Path(__file__).resolve().parents[1]           # neorisk_simkit/
# Library code the generated module runs. Numba's cache=True only notices edits to the file of the
# function it compiles, so the generated source (hence its name and cache) carries this hash.
_RUNTIME_SOURCES = ("engine/*.py", "std/*.py", "spec/dist.py")


@functools.cache
def _library_hash() -> str:
    h = hashlib.sha256(f"numba {numba.__version__}\n".encode())
    for pattern in _RUNTIME_SOURCES:
        for f in sorted(_PKG.glob(pattern)):
            h.update(f.relative_to(_PKG).as_posix().encode() + b"\0" + f.read_bytes() + b"\0")
    return h.hexdigest()[:16]


def runtime_fingerprint() -> str:
    """Hash of the runtime library (engine, std, spec.dist sources) and the Numba version."""
    return _library_hash()


def _q(s: str) -> str:
    return repr(s)


class _Gen:
    def __init__(self, plan: Plan, checked: bool):
        self.plan, self.checked = plan, checked
        self.resources = resource_names(plan)
        self.out_idx = slabs.out_indices(plan)
        self.specs = {s.resource: s for s in slabs.buffer_specs(plan)}
        self.funcs: list[str] = []
        self.names: set[str] = set()

    # ------------------------------------------------------------------ small pieces
    @staticmethod
    def r(resource: str) -> str:
        return f"R_{slabs.const_name(resource)}"

    @staticmethod
    def o(resource: str) -> str:
        return f"OUT_{slabs.const_name(resource)}"

    def fn(self, name: str, params: str, body: list[str]) -> None:
        self.names.add(name)
        inline = name not in _NOT_INLINED and not name.startswith(_NOT_INLINED_PREFIXES)
        self.funcs.append(f"{_JIT_INLINE if inline else _JIT}\ndef {name}({params}):\n" + "\n".join(
            "    " + ln if ln else "" for ln in body) + "\n")

    def by_proc(self, procs: list[ProcessDef], cls: str,
                msg: Callable[[str], list[str]], indent: str = "") -> list[str]:
        """Raise `cls` with a constant message per process (branch on ctx.action).

        `msg(proc)` returns the exception arguments as source fragments.
        """
        lines = [f"{indent}a_ = ctx[CTX_ACTION]"]
        for p in procs:
            lines += [f"{indent}if a_ == {p.action_id}:",
                      f"{indent}    raise {cls}({', '.join(msg(p.name))})"]
        lines.append(f"{indent}raise {cls}({', '.join(msg('process'))})")
        return lines

    def resv_check(self, resource: str, procs: list[ProcessDef], what: str,
                   indent: str = "") -> list[str]:
        if not self.checked:
            return []
        r = self.r(resource)
        return [f"{indent}resv_ = out[OUT_RESV]",
                f"{indent}resv_[{r}] -= 1",
                f"{indent}if resv_[{r}] < 0:",
                *self.by_proc(procs, "AbiViolation", lambda p: [_q(f"{p}: {what}")],
                              indent + "    ")]

    def procs_of_partition(self, part: str) -> list[ProcessDef]:
        return [p for p in self.plan.processes if p.partition == part]

    def procs_acting_as(self, part: str) -> list[ProcessDef]:
        """Processes of `part` and of every owner that acts for it (D74)."""
        actors = {p.name for p in self.plan.partitions
                  if p.name == part or getattr(p, "acts_for", None) == part}
        return [p for p in self.plan.processes if p.partition in actors]

    # ------------------------------------------------------------------ constants
    def constants(self) -> str:
        lines = [f"CHECKED = {self.checked}",
                 f"RESOURCES = {self.resources!r}",
                 f"_NULL = {-(2 ** 63)}",
                 f"PAYLOAD_W = {PAYLOAD_W}",
                 f"SEND_KEY_BASE = {SEND_KEY_BASE}",
                 f"ORDINAL_LIMIT = {ORDINAL_LIMIT}",
                 f"CMD_PAY = {CMD_PAY}",
                 f"CMD_PAY_ROW = {CMD_PAY_ROW}"]
        lines += [f"CTX_{f.upper()} = {i}" for i, f in enumerate(CTX_FIELDS)]
        lines += [f"{self.r(res)} = {i}" for i, res in enumerate(self.resources)]
        lines += [f"OUT_{n.upper()} = {i}" for i, n in enumerate(slabs.OUT_HEAD)]
        for key, i in self.out_idx.items():
            lines.append(f"{self.o(key)} = {i}")
        lines += [f"HID_{n.upper()} = {i}" for i, n in enumerate(slabs.HID_FIELDS)]
        lines += [f"OBX_{n.upper()} = {i}" for i, n in enumerate(slabs.OUTBOX_COLS)]
        lines.append(f"OBX_PAY = {slabs.OUTBOX_PAY}")
        lines += [f"OB_REQUEST = {slabs.OB_REQUEST}", f"OB_MESSAGE = {slabs.OB_MESSAGE}",
                  f"OB_RESPONSE = {slabs.OB_RESPONSE}", f"OB_CREATE = {slabs.OB_CREATE}"]
        from neorisk_simkit.engine.world import HIDDEN_DTYPES  # world imports this module
        # runner constants carry a `_` prefix so kernel module names cannot collide with them
        lines += [f"_W_{n.upper()} = {i}" for i, n in enumerate(WORLD_FIELDS)]
        lines += [f"_WH_{n.upper()} = {i}" for i, (n, _, _) in enumerate(HIDDEN_DTYPES)]
        lines += [f"_C_{n.upper()} = {i}" for i, n in enumerate(COUNTERS)]
        lines += [f"_DONE = {DONE}", f"_NEED_SWAP = {NEED_SWAP}", f"_NEED_NODES = {NEED_NODES}",
                  f"_MAX_RETRIES = {MAX_RETRIES}", f"_PERIODIC_QUEUED = {PERIODIC_QUEUED}",
                  f"_PERIODIC_SITE = {PERIODIC_SITE}", f"_JITTER_SITE = {JITTER_SITE}",
                  f"_CAUSE_MASK = {(1 << 56) - 1}", f"_I64_MAX = {2 ** 63 - 1}",
                  f"_P_CPID = {P_CPID}", f"_P_CEID = {P_CEID}",
                  f"_UNSET_CAUSE = {UNSET_CAUSE}", f"_NULL_CAUSE = {NULL_CAUSE}"]
        lines += [f"_DR_CLOSED = {DR_CLOSED}", f"_DR_LARGE = {DR_LARGE}",
                  f"_DR_PYTHON = {DR_PYTHON}", f"_DR_LOG_FULL = {DR_LOG_FULL}",
                  f"_DR_NO_PROGRESS = {DR_NO_PROGRESS}", f"_PH_OWNERS = {PH_OWNERS}",
                  f"_PH_ROUTE1 = {PH_ROUTE1}", f"_PH_SHARDS = {PH_SHARDS}",
                  f"_PH_ROUTE2 = {PH_ROUTE2}", f"_PH_ADMIT = {PH_ADMIT}",
                  f"_RS_PHASE = {RS_PHASE}",
                  f"_RS_STATUS = {RS_STATUS}", f"_RS_H = {RS_H}", f"_RS_C0 = {RS_C0}",
                  f"_RS_NLOG = {RS_NLOG}", f"_RS_SHARD_NS = {RS_SHARD_NS}",
                  f"_I64_MIN = {-(2 ** 63)}",
                  f"_ADM_OK = {ADM_OK}", f"_ADM_CAP = {ADM_CAP}", f"_ADM_LIVE = {ADM_LIVE}",
                  f"_ADM_NODES = {ADM_NODES}", f"_ADM_DEPTH = {ADM_DEPTH}"]
        ns_type, ns_nstart = self._admission_tables()
        lines += [f"_NS_TYPE = {tuple(ns_type)!r}", f"_NS_NSTART = {tuple(ns_nstart)!r}"]
        return "\n".join(lines) + "\n"

    # ------------------------------------------------------------------ rng / reads / refs
    def rng_helpers(self) -> None:
        self.fn("_draw", "ctx, site", [
            "k = next_k(ctx[CTX_KC], site)",
            ("return key_uniform(ctx[CTX_SEED], ctx[CTX_INST], ctx[CTX_ACTION], ctx[CTX_OCC], "
             "site, k)")])
        self.fn("_rng_uniform", "ctx, site", ["return _draw(ctx, site)"])
        self.fn("_rng_bernoulli", "ctx, site, p", ["return bernoulli(p, _draw(ctx, site))"])
        self.fn("_rng_geometric", "ctx, site, mean", ["return geometric(mean, _draw(ctx, site))"])
        self.fn("_rng_uniform_int", "ctx, site, lo, hi",
                ["return uniform_int(lo, hi, _draw(ctx, site))"])
        self.fn("_rng_categorical", "ctx, site, p", ["return categorical(p, _draw(ctx, site))"])
        self.fn("_rng_exp_us", "ctx, site, mean_s",
                ["return sample_us(EXP, mean_s * 1e6, 0.0, 0.0, _draw(ctx, site), 0.0)"])
        self.fn("_rng_pareto_us", "ctx, site, alpha, min_h",
                ["return sample_us(PARETO, alpha, min_h * 3.6e9, 0.0, _draw(ctx, site), 0.0)"])
        self.fn("_rng_dist_us", "ctx, site, d", [
            "u1 = _draw(ctx, site)",
            "u2 = _draw(ctx, site)",
            "return sample_us(np.int64(d[0]), d[1], d[2], d[3], u1, u2)"])
        self.fn("_rng_lognormal_minor", "ctx, site, median, sigma", [
            "u1 = _draw(ctx, site)",
            "u2 = _draw(ctx, site)",
            "v = median * math.exp(sigma * normal(u1, u2))",
            "return np.int64(np.rint(min(max(v, 0.0), 4.611686018427388e18)))"])
        self.fn("_reads_sample_by_weight", "cumw, u", [
            "i = np.searchsorted(cumw, u, side='right')",
            "return np.int64(min(i, cumw.shape[0] - 1))"])
        self.fn("_refs_count", "offs, idx, id_", ["return offs[id_ + 1] - offs[id_]"])
        self.fn("_refs_get", "offs, idx, id_, k", ["return idx[offs[id_] + k]"])
        self.fn("_refs_pick", "offs, idx, id_, u", [
            "n = offs[id_ + 1] - offs[id_]",
            "if n <= 0:",
            "    return np.int64(_NULL)",
            "return np.int64(idx[offs[id_] + min(np.int64(u * n), n - 1)])"])

    # ------------------------------------------------------------------ reserve
    def _owner_tables(self) -> set[str]:
        return {p.table for p in self.plan.partitions if p.kind == "owner"}

    def reserve(self, p: ProcessDef) -> None:
        """`_reserve_<proc>(out, vec)`: all or nothing over every resource. Creating an owner
        also takes an outbox row for its creation message (D43), so the `requests` need is
        `vec[requests]` plus the `creates:<owner table>` entries. A member table (D74) is an
        owner table too, so reserving member rows also reserves outbox rows that `_member_<t>`
        never writes: a harmless over-reservation."""
        q = self.resources.index("requests")
        owners = self._owner_tables()
        made = [i for i, r in enumerate(self.resources)
                if r.startswith("creates:") and r[len("creates:"):] in owners]
        body = ["cnt = out[OUT_CNT]", "cap = out[OUT_CAP]", "miss = out[OUT_MISS]",
                "nreq = " + " + ".join(f"vec[{i}]" for i in [q, *made])]
        for i, res in enumerate(self.resources):
            need = "nreq" if i == q else f"vec[{i}]"
            if res == "timers":
                cond = f"out[OUT_POOL][P_FREE_N][out[OUT_W]] < {need}"
            else:
                cond = f"cap[{i}] - cnt[{i}] < {need}"
            body += [f"if {need} > 0 and {cond}:", f"    miss[0] = {i}", "    return False"]
        body.append("resv = out[OUT_RESV]")
        body += [f"resv[{i}] = {'nreq' if i == q else f'vec[{i}]'}"
                 for i in range(len(self.resources))]
        body.append("return True")
        self.fn(f"_reserve_{p.name}", "out, vec", body)

    # ------------------------------------------------------------------ records
    def _row(self, spec: slabs.BufferSpec, head_values: list[str], args: list[str]) -> list[str]:
        r = self.r(spec.resource)
        body = ["cnt = out[OUT_CNT]", f"b_ = out[{self.o(spec.resource)}]", f"i = cnt[{r}]"]
        j = 0
        for v in head_values:
            body.append(f"b_[{j}][i] = {v}")
            j += 1
        for c, a in zip(spec.cols, args, strict=True):
            dt = slabs.slab_dtype(c)
            if c.ltype.nullable and dt.kind in "iu" and dt.itemsize < 8:
                # std.NULL does not fit a narrow cell (numpy raises where numba truncates to 0);
                # store 0 explicitly - the valid_<col> byte carries the null
                body.append(f"b_[{j}][i] = {a} if {a} != _NULL else 0")
            else:
                body.append(f"b_[{j}][i] = {a}")
            j += 1
        for c, a in zip(spec.cols, args, strict=True):
            if c.ltype.nullable:
                body.append(f"b_[{j}][i] = 1 if {a} != _NULL else 0")
                j += 1
        body.append(f"cnt[{r}] = i + 1")
        return body

    def _record_head(self) -> list[str]:
        return ["g = ctx[CTX_G]", "rseq = out[OUT_HID][HID_RSEQ]", "seq_ = rseq[g]",
                "rseq[g] = seq_ + 1"]

    def emit(self, e) -> None:
        spec = self.specs[f"records:{e.name}"]
        procs = self.procs_acting_as(e.partition)
        args = [f"c{i}" for i in range(len(spec.cols))]
        body = ["if t != ctx[CTX_T]:",
                *self.by_proc(procs, "EngineError", lambda p: [
                    _q(f"{p}: records must be emitted at ctx.t (emit_{e.name} at "), "t",
                    _q(", ctx.t "), "ctx[CTX_T]", _q(")")], "    ")]
        body += self.resv_check(spec.resource, procs, f"emit beyond reservation: {e.name}")
        body += self._record_head()
        body += self._row(spec, ["t", "ctx[CTX_LAMPORT]", "ctx[CTX_PID]", "seq_",
                                 "ctx[CTX_ACTION]"], args)
        self.fn(f"_emit_{e.name}", ", ".join(["out", "ctx", "t", *args]), body)

    def accumulate(self, a) -> None:
        """`_add_<name>(out, ctx, v)`: checked int64 add into this worker's partial sum (D46)."""
        self.fn(f"_add_{a.name}", "out, ctx, v", [
            "acc = out[OUT_ACC]",
            f"acc[{a.code}] = std.checked_add(acc[{a.code}], v)"])

    def change(self, grp) -> None:
        spec = self.specs[f"records:{grp.name}"]
        table = self.plan.table(grp.table)
        col_pos = {c.name: 1 + i for i, c in enumerate(table.cols)}
        procs = [p for p in self.plan.processes
                 if self.plan.partition(p.partition).table == grp.table]
        args = [f"c{i}" for i in range(len(spec.cols))]
        body = ["if t != ctx[CTX_T]:",
                *self.by_proc(procs, "EngineError", lambda p: [
                    _q(f"{p}: changes must be recorded at ctx.t (change_{grp.name})")], "    ")]
        body += self.resv_check(spec.resource, procs, f"change beyond reservation: {grp.name}")
        body.append("row = s[0]")
        body += [f"s[{col_pos[c.name]}][row] = {a}" for c, a in zip(spec.cols, args, strict=True)]
        body += self._record_head()
        body += self._row(spec, ["t", "ctx[CTX_LAMPORT]", "ctx[CTX_PID]", "seq_",
                                 "ctx[CTX_ACTION]", "ctx[CTX_SELF_ID]"], args)
        self.fn(f"_change_{grp.name}", ", ".join(["out", "ctx", "s", "t", *args]), body)

    # ------------------------------------------------------------------ creates / ids
    def _handle(self, ns: str, code: int, procs: list[ProcessDef]) -> list[str]:
        return ["g = ctx[CTX_G]",
                "ordn = out[OUT_HID][HID_ORDN]",
                f"o_ = np.int64(ordn[g, {code}])",
                "if o_ >= ORDINAL_LIMIT:",
                *self.by_proc(procs, "EngineError", lambda p: [
                    _q(f"{p}: more than {ORDINAL_LIMIT} rows of {ns} created by one partition "
                       "in one step")], "    "),
                f"ordn[g, {code}] = o_ + 1",
                f"h = make_handle({code}, g, o_)"]

    # values of `slabs.CREATE_HEAD`, in order
    CREATE_HEAD_VALUES = ("h", "ctx[CTX_PID]", "o_", "ctx[CTX_T]", "g", "ctx[CTX_LAMPORT]")

    def create(self, ns: str, code: int, outbox: bool = True) -> None:
        """`_create_<ns>(out, ctx, *cols) -> handle`: a created row; an owner row also writes
        its creation message (D43). With `outbox=False` this is `_member_<ns>` (D74): the same
        row in `creates:<ns>`, never a creation message, so the row is never admitted."""
        spec = self.specs[f"creates:{ns}"]
        procs = list(self.plan.processes)
        args = [f"c{i}" for i in range(len(spec.cols))]
        verb = "create" if outbox else "add_member"
        body = self.resv_check(spec.resource, procs, f"{verb} beyond reservation: {ns}")
        body += self._handle(ns, code, procs)
        body += self._row(spec, [*self.CREATE_HEAD_VALUES], args)
        if outbox and ns in self._owner_tables():
            body += self.resv_check("requests", procs, f"create beyond reservation: {ns} "
                                    "(creation message)")
            # the created row's columns ride the creation message (D43; validate keeps them
            # to <= 7 int64-storable values): admission reads them from there
            body += [f"i = _outbox_row(out, ctx, OB_CREATE, {code}, ctx[CTX_T], h, 0, -1, -1)",
                     "pay = out[OUT_OUTBOX][OBX_PAY]"]
            body += [f"pay[i, {j}] = np.int64({a})" for j, a in enumerate(args)]
        body.append("return h")
        self.fn(f"_{'create' if outbox else 'member'}_{ns}", ", ".join(["out", "ctx", *args]),
                body)

    def new_id(self) -> None:
        procs = list(self.plan.processes)
        tables = {t.name for t in self.plan.tables}
        body = []
        for code, ns in enumerate(self.plan.namespaces):
            if ns in tables:
                continue
            spec = self.specs[f"creates:{ns}"]
            sub = self.resv_check(spec.resource, procs, f"new_id beyond reservation: {ns}")
            sub += self._handle(ns, code, procs)
            sub += self._row(spec, [*self.CREATE_HEAD_VALUES], [])
            sub.append("return h")
            self.fn(f"_new_id_{ns}", "out, ctx", sub)
            body += [f"if ns == {code}:", f"    return _new_id_{ns}(out, ctx)"]
        body += self.by_proc(procs, "EngineError", lambda p: [
            _q(f"{p}: out.new_id needs a p.ids namespace, got namespace code "), "ns"])
        self.fn("_new_id", "out, ctx, ns", body)

    # ------------------------------------------------------------------ queue commands
    def _push(self, prio: str, kind: str, tag: str, pay: str, procs, what: str) -> list[str]:
        return ["g = ctx[CTX_G]",
                "hid = out[OUT_HID]",
                "cseq = hid[HID_CSEQ]",
                "seq_ = cseq[g]",
                "cseq[g] = seq_ + 1",
                (f"node = q_push(out[OUT_POOL], out[OUT_W], hid[HID_QHEAD], g, t, {prio}, "
                 f"ctx[CTX_LAMPORT], seq_, {kind}, ctx[CTX_ACTION], {tag}, {pay})"),
                "if node < 0:",
                *self.by_proc(procs, "EngineError", lambda p: [
                    _q(f"{p}: {what} without a free command node (reserve timers first)")],
                    "    "),
                # D80: caused by this commit, resolved to an event id at seal
                "P_ = out[OUT_POOL]",
                "P_[_P_CPID][node] = ctx[CTX_PID]",
                "P_[_P_CEID][node] = _UNSET_CAUSE"]

    def timer(self) -> None:
        procs = list(self.plan.processes)
        body = ["if t < ctx[CTX_T]:",
                *self.by_proc(procs, "EngineError", lambda p: [
                    _q(f"timer scheduled before current time in {p} (at "), "t",
                    _q(", ctx.t "), "ctx[CTX_T]", _q(")")], "    ")]
        body += self.resv_check("timers", procs, "timer beyond reservation")
        body += self._push("prio", "kind", "tag", "-1", procs, "timer")
        self.fn("_timer", "out, ctx, t, kind, prio, tag", body)

    def continue_at(self) -> None:
        procs = list(self.plan.processes)
        body = ["if t != ctx[CTX_T]:",
                *self.by_proc(procs, "EngineError", lambda p: [
                    _q(f"{p}: continue_at must be at ctx.t (got "), "t", _q(", ctx.t "),
                    "ctx[CTX_T]", _q(")")], "    ")]
        body += self.resv_check("timers", procs, "continue_at beyond reservation (timers)")
        body += self._push("PRIO_CONTINUE", "out[OUT_CMD_KIND][0]", "cursor", "PAY_CONTINUE",
                           procs, "continue_at")
        self.fn("_continue_at", "out, ctx, t, cursor", body)

    # ------------------------------------------------------------------ outbox
    def outbox_row(self) -> None:
        self.fn("_outbox_row", "out, ctx, kind, bnd, time, dst, tag, resp_kind, target", [
            "cnt = out[OUT_CNT]",
            "i = cnt[R_REQUESTS]",
            "ob = out[OUT_OUTBOX]",
            "g = ctx[CTX_G]",
            "hid = out[OUT_HID]",
            "cseq = hid[HID_CSEQ]",
            "ob[OBX_KIND][i] = kind",
            "ob[OBX_BND][i] = bnd",
            "ob[OBX_TIME][i] = time",
            "ob[OBX_PRIO][i] = PRIO_MESSAGE",
            "ob[OBX_CAUSE][i] = ctx[CTX_LAMPORT]",
            "ob[OBX_SRC_G][i] = g",
            "ob[OBX_SRC_PID][i] = ctx[CTX_PID]",
            "ob[OBX_SRC_SEQ][i] = cseq[g]",
            "cseq[g] += 1",
            "ob[OBX_DST][i] = dst",
            "ob[OBX_TAG][i] = tag",
            "ob[OBX_RESP_KIND][i] = resp_kind",
            "ob[OBX_TARGET_ACTION][i] = target",
            "pay = ob[OBX_PAY]",
            "for c in range(PAYLOAD_W):",
            "    pay[i, c] = 0",
            "pay[i, 7] = g",
            "pay[i, 8] = hid[HID_GEN][g]",
            "pay[i, 9] = ctx[CTX_SELF_ID]",
            "pay[i, 10] = ctx[CTX_ACTION]",
            "cnt[R_REQUESTS] = i + 1",
            "return i"])
        self.fn("_latency", "out, ctx, b", [
            "j = next_k(ctx[CTX_KC], SEND_KEY_BASE + b)",
            ("u1 = key_uniform(ctx[CTX_SEED], ctx[CTX_INST], SEND_KEY_BASE + b, "
             "ctx[CTX_LAMPORT], j, 0)"),
            ("u2 = key_uniform(ctx[CTX_SEED], ctx[CTX_INST], SEND_KEY_BASE + b, "
             "ctx[CTX_LAMPORT], j, 1)"),
            "lat = out[OUT_LAT]",
            "return sample_us(np.int64(lat[b, 0]), lat[b, 1], lat[b, 2], lat[b, 3], u1, u2)"])

    def _handler(self, b: str) -> tuple[int, int]:
        """(command kind, action) of the one process that receives boundary b."""
        found = [(p.on_request[b] if b in p.on_request else p.on_message[b], p.action_id)
                 for p in self.plan.processes if b in p.on_request or b in p.on_message]
        if len(found) != 1:
            raise LoweringError(f"boundary {b} is handled by {len(found)} processes; "
                                "it needs exactly one")
        return found[0]

    def outbound(self, bd, verb: str) -> None:
        """`_request_<b>` (verb "request") or `_send_<b>` (verb "send")."""
        local = "requests" if verb == "request" else "messages"
        procs = [p for p in self.plan.processes if bd.name in getattr(p, local).values()]
        args = [f"p{i}" for i in range(len(bd.payload))]
        dest = "shard" if verb == "request" else "to"
        to = self.plan.partition(bd.to)
        if verb == "request":           # a delayed request is a timer followed by a request
            body = ["if t != ctx[CTX_T]:",
                    *self.by_proc(procs, "EngineError", lambda p: [
                        _q(f"{p}: request {bd.name} must be dated ctx.t")], "    ")]
        else:
            body = ["if t < ctx[CTX_T]:",
                    *self.by_proc(procs, "EngineError", lambda p: [
                        _q(f"{p}: send {bd.name} scheduled before current time")], "    ")]
        if to.kind == "shard":          # an owner target is judged at delivery (D73)
            body += [f"n_ = out[OUT_SHARD_N][{bd.code}]",
                     f"if {dest} < 0 or {dest} >= n_:",
                     *self.by_proc(procs, "EngineError", lambda p: [
                         _q(f"{p}: {verb} {bd.name} to shard "), dest,
                         _q(f" but {to.name} has "), "n_"], "    ")]
        body += self.resv_check("requests", procs, f"{verb} beyond reservation: {bd.name}")
        kind, target = self._handler(bd.name)
        if verb == "request":
            body.append(f"i = _outbox_row(out, ctx, OB_REQUEST, {bd.code}, t, shard, tag, "
                        f"{kind}, {target})")
        else:
            body.append(f"i = _outbox_row(out, ctx, OB_MESSAGE, {bd.code}, "
                        f"t + _latency(out, ctx, {bd.code}), to, tag, {kind}, {target})")
        body.append("pay = out[OUT_OUTBOX][OBX_PAY]")
        body += [f"pay[i, {j}] = {a}" for j, a in enumerate(args)]
        if verb == "request":
            body.append("out[OUT_REQC][0] += 1")
        self.fn(f"_{verb}_{bd.name}", ", ".join(["out", "ctx", "t", dest, "tag", *args]), body)

    def respond(self, bd, resp: str) -> None:
        procs = [p for p in self.plan.processes if bd.name in p.on_request]
        args = [f"p{i}" for i in range(len(bd.response_payload))]
        body = self.resv_check("requests", procs, f"respond beyond reservation: {bd.name}")
        body += ["src = cmd[CMD_PAY]",
                 "row = cmd[CMD_PAY_ROW]",
                 "target = src[row, 10]"]
        requesters = [p for p in self.plan.processes if bd.name in p.requests.values()]
        body.append("rk = -1")
        for p in requesters:
            k = p.on_response.get((bd.name, resp))
            if k is None:
                raise LoweringError(f"process {p.name} requests {bd.name} but has no "
                                    f"on_response for {bd.name}.{resp}")
            body += [f"if target == {p.action_id}:", f"    rk = {k}"]
        body += [(f"i = _outbox_row(out, ctx, OB_RESPONSE, {bd.code}, "
                  f"ctx[CTX_T] + _latency(out, ctx, {bd.code}), src[row, 7], cmd[1], rk, "
                  "target)"),
                 "pay = out[OUT_OUTBOX][OBX_PAY]",
                 "pay[i, 11] = src[row, 8]"]                 # the requester's slot generation
        body += [f"pay[i, {j}] = {a}" for j, a in enumerate(args)]
        self.fn(f"_respond_{bd.name}_{resp}", ", ".join(["out", "ctx", "cmd", *args]), body)

    # ------------------------------------------------------------------ dispatch
    def dispatch(self) -> None:
        body = ["out[OUT_CMD_KIND][0] = cmd[0]", "g = ctx[CTX_G]"]
        if self.checked:                 # a reservation never outlives the command that made it
            body += ["resv_d = out[OUT_RESV]",
                     "for r_ in range(resv_d.shape[0]):",
                     "    resv_d[r_] = 0"]
        for p in self.plan.processes:
            a = p.action_id
            part = self.plan.partition(p.partition)
            body.append(f"if action == {a}:")
            ws = f"ws{a}"
            body += [f"    {ws} = world_state[{a}]", f"    ls{a} = {ws}[0][g]"]
            if part.kind == "owner":
                n_state, st_i = len(self.plan.table(part.table).cols), 1
                body.append(f"    st{a} = {ws}[1]")
                s = ", ".join([f"ls{a}"] + [f"st{a}[{i}]" for i in range(n_state)])
            else:
                n_state, st_i = len(part.state), 3
                body += [f"    st{a} = {ws}[3]", f"    offs{a} = {ws}[1]",
                         f"    off{a} = offs{a}[ls{a}]"]
                s = ", ".join([f"ls{a}", f"off{a}", f"offs{a}[ls{a} + 1] - off{a}", f"{ws}[2]"]
                              + [f"st{a}[{i}]" for i in range(n_state)])
            body.append(f"    s{a} = ({s},)")
            narrowed = ", ".join(f"ctx[{i}][{a}]" if f in _PER_ACTION else f"ctx[{i}]"
                                 for i, f in enumerate(CTX_FIELDS))
            body.append(f"    c{a} = ({narrowed})")
            call = f"c{a}, s{a}, cmd, out"
            if p.kernel.local is not None:
                n_loc = len(p.kernel.local.fields)
                body.append(f"    lc{a} = {ws}[{st_i + 1}]")
                loc = ", ".join([f"ls{a}"] + [f"lc{a}[{i}]" for i in range(n_loc)])
                body.append(f"    loc{a} = ({loc},)")
                call = f"c{a}, s{a}, loc{a}, cmd, out"
            body.append(f"    return {p.kernel.name}({call})")
        body.append('raise EngineError("dispatch: unknown action ", action)')
        self.fn("dispatch", "action, ctx, cmd, world_state, out", body)

    # ------------------------------------------------------------------ partition runner
    def periodic_time(self) -> None:
        """Time of occurrence j of a periodic process on one shard (D26)."""
        self.fn("periodic_time", "seed, inst, action, j, every, jit, sim_start", [
            "u = key_uniform(seed, inst, action, 0, _PERIODIC_SITE, 0)",
            "t = np.int64(sim_start) + np.int64(u * every) + np.int64(j) * every",
            "if j > 0 and jit[0] >= 0:",
            "    u1 = key_uniform(seed, inst, action, j, _JITTER_SITE, 0)",
            "    u2 = key_uniform(seed, inst, action, j, _JITTER_SITE, 1)",
            "    t += sample_us(np.int64(jit[0]), jit[1], jit[2], jit[3], u1, u2)",
            "return t"])

    def _snap_parts(self, p: ProcessDef) -> list[str]:
        """Expressions (over ws_, ls_, lo_, hi_) of every state/local array a kernel may write."""
        part = self.plan.partition(p.partition)
        parts: list[str] = []
        if part.kind == "owner":
            n_state, loc_i = len(self.plan.table(part.table).cols), 2
            parts += [f"ws_[1][{i}][ls_:ls_ + 1]" for i in range(n_state)]
        else:
            loc_i = 4
            for j, decl in enumerate(part.state.values()):
                per_item = "[" in decl
                parts.append(f"ws_[3][{j}][lo_:hi_]" if per_item else f"ws_[3][{j}][ls_:ls_ + 1]")
        if p.kernel.local is not None:
            for i, (_, width) in enumerate(p.kernel.local.fields.values()):
                parts.append(f"ws_[{loc_i}][{i}][ls_]" if width > 1
                             else f"ws_[{loc_i}][{i}][ls_:ls_ + 1]")
        return parts

    def _snap_head(self, p: ProcessDef) -> list[str]:
        head = [f"ws_ = ws[{p.action_id}]", "ls_ = ws_[0][g]"]
        if self.plan.partition(p.partition).kind == "shard":
            head += ["lo_ = ws_[1][ls_]", "hi_ = ws_[1][ls_ + 1]"]
        return head

    def checked_dispatch(self) -> None:
        """`dispatch` plus the ABI check: reject / RETRY must come before the first write."""
        self.fn("_same", "a, b", [
            "if a.shape[0] != b.shape[0]:",
            "    return False",
            "for i in range(a.shape[0]):",
            "    x = a[i]",
            "    y = b[i]",
            "    if x != y and not (x != x and y != y):",
            "        return False",
            "return True"])
        body = ["g = ctx[CTX_G]",
                "hid = out[OUT_HID]",
                "cnt0 = out[OUT_CNT].copy()",
                "acc0 = out[OUT_ACC].copy()",
                "cseq0 = hid[HID_CSEQ][g]",
                "ordn0 = hid[HID_ORDN][g].copy()"]
        for p in self.plan.processes:
            a = p.action_id
            parts = self._snap_parts(p)
            snap = self._snap_head(p) + [
                "return (" + "".join(f"{x}.copy(), " for x in parts) + ")"]
            self.fn(f"_snap_{a}", "ws, g", snap)
            same = self._snap_head(p) + ["ok = True"]
            same += [f"ok = ok and _same(snap[{i}], {x})" for i, x in enumerate(parts)]
            same.append("return ok")
            self.fn(f"_unchanged_{a}", "ws, g, snap", same)
            body += [f"if action == {a}:",
                     f"    snap = _snap_{a}(ws, g)",
                     "    rc = dispatch(action, ctx, cmd, ws, out)",
                     "    if rc != COMMIT:",
                     (f"        ok = _unchanged_{a}(ws, g, snap) and _same(cnt0, out[OUT_CNT]) "
                      "and _same(acc0, out[OUT_ACC]) and cseq0 == hid[HID_CSEQ][g] "
                      "and _same(ordn0, hid[HID_ORDN][g])"),
                     "        if not ok:",
                     "            if rc == RETRY:",
                     f"                raise AbiViolation({_q(f'process {p.name} wrote before returning RETRY')})",
                     f"            raise AbiViolation({_q(f'process {p.name} wrote before returning reject')})",
                     "    return rc"]
        body.append('raise EngineError("dispatch: unknown action ", action)')
        self.fn("_checked_dispatch", "action, ctx, cmd, ws, out", body)

    @staticmethod
    def command_labels(p: ProcessDef) -> dict[int, str]:
        """Command kind -> label (`start`, `request b`, `message b`, `response b.r`)."""
        labels = {0: "start"}
        labels.update({k: f"request {b}" for b, k in p.on_request.items()})
        labels.update({k: f"message {b}" for b, k in p.on_message.items()})
        labels.update({k: f"response {b}.{r}" for (b, r), k in p.on_response.items()})
        return labels

    def out_of_order(self) -> None:
        """The monotonic-time guard's error: names partition type, process and command."""
        body = []
        for p in self.plan.processes:
            part = self.plan.partition(p.partition)
            labels = self.command_labels(p)
            who = f"{part.kind} {part.name}: {p.name} would run"
            tail = f"{_q(' before its last command at ')}, last)"
            body.append(f"if a == {p.action_id}:")
            for k, label in sorted(labels.items()):
                body += [f"    if kind == {k}:",
                         f"        raise EngineError({_q(f'{who} {label} at ')}, t, {tail}"]
            body.append(f"    raise EngineError({_q(f'{who} command ')}, kind, {_q(' at ')}, t, "
                        f"{tail}")
        body.append('raise EngineError("command out of time order at ", t)')
        self.fn("_out_of_order", "a, kind, t, last", body)

    def unpaired(self) -> None:
        """The pairing guard's error (D40): a request not answered exactly once by a commit, or
        an answer from a command that was not a request. Names process and boundary and cites
        the command by its partition and its sender's (partition_id, seq) (node seq is the
        sender's seq, D61), and the action id (§11, F-06)."""
        def cite(text: str) -> str:
            """`text` then the citation, as EngineError arguments."""
            return (f"{_q(text + ' at (partition_id ')}, pid_, {_q('), sent by (partition_id ')}, "
                    f"spid_, {_q(', seq ')}, seq_, {_q('), action ')}, a)")

        body = []
        for p in self.plan.processes:
            requests = {k: b for b, k in p.on_request.items()}
            body.append(f"if a == {p.action_id}:")
            for k, label in sorted(self.command_labels(p).items()):
                body.append(f"    if kind == {k}:")
                if k in requests:
                    head = f"{p.name}: request {requests[k]} must be answered exactly once"
                    body.append(f"        raise EngineError({_q(head + ' (answered ')}, nresp, "
                                f"{_q(', returned ')}, rc, {cite(')')}")
                else:
                    msg = f"{p.name}: {label} answered a request it was not given"
                    body.append(f"        raise EngineError({cite(msg)}")
            body.append(f"    raise EngineError({_q(f'{p.name}: command ')}, kind, "
                        f"{cite(' answered a request it was not given')}")
        body.append(f"raise EngineError({_q('command ')}, kind, "
                    f"{cite(' answered a request it was not given')}")
        self.fn("_unpaired", "a, kind, rc, nresp, pid_, spid_, seq_", body)

    def run_partitions(self) -> None:
        disp = "_checked_dispatch" if self.checked else "dispatch"
        hid = ["pid", "clock", "occ", "pending", "qhead", "inst", "self_id", "cseq", "retire_at",
               "susp_t", "susp_delta", "ptype", "last_t"]
        body = ["hid = W[_W_HID]"]
        body += [f"{n} = hid[_WH_{n.upper()}]" for n in hid]
        body += [
            "P = W[_W_POOL]",
            "PA = W[_W_PAY]",
            "ws = W[_W_STATE]",
            "args = W[_W_ARGS]",
            "seed = W[_W_SEED]",
            "counters = W[_W_COUNTERS][worker]",
            "rejects = W[_W_REJECTS][worker]",
            "occ_col = W[_W_OCC_COL]",
            "retire = W[_W_RETIRE]",
            "every = W[_W_EVERY]",
            "jitter = W[_W_JITTER]",
            "sim_start = W[_W_SIM_START]",
            "kc = W[_W_KC][worker]",
            "nopay = W[_W_NOPAY]",
            "node_cap = W[_W_NODE_CAP]",
            "bnd_delta = W[_W_BND_DELTA]",
            "reqc = out[OUT_REQC]",
            "cnt = out[OUT_CNT]",
            "obx = out[OUT_OUTBOX]",
            "miss = out[OUT_MISS]",
            "clog = out[OUT_CLOG]",
            "clog_n = out[OUT_CLOG_N]",
            "free_n = P[P_FREE_N]",
            "for i in range(start, slots.shape[0]):",
            "    g = np.int64(slots[i])",
            "    prev_t = np.int64(-1)",
            "    ran = False",
            "    while True:",
            "        node = qhead[g]",
            "        if node < 0:",
            "            break",
            # D73: an owner left with nothing but owner-to-owner messages is idle; it retires
            # (below) and the messages are late, however early they were queued
            ("        if ran and retire[ptype[g]] != 0 and pending[g] == 0 "
             "and only_owner_messages(P, PA[0], qhead, g):"),
            "            counters[_C_LATE_MESSAGES] += drop_queue(P, PA, worker, qhead, g)",
            "            break",
            "        t = P[0][node]",
            "        if t >= limit_t:",
            "            break",
            "        if owners and pending[g] > 0:",
            "            break",
            "        if node_cap >= 0 and free_n[worker] > node_cap:",
            "            return _NEED_NODES, i",
            "        if clog_n[0] >= clog.shape[0]:",          # D80: the commit log is full
            "            miss[0] = -1",
            "            return _NEED_SWAP, i",
            "        a = np.int64(P[6][node])",
            "        kind = np.int64(P[5][node])",
            "        if t < last_t[g]:",
            "            _out_of_order(a, kind, t, last_t[g])",
            "        tag = P[3][node]",
            "        prow = P[7][node]",
            "        cause = P[1][node] & _CAUSE_MASK",
            "        cpid_ = P[_P_CPID][node]",
            "        ceid_ = P[_P_CEID][node]",
            "        cursor = np.int64(0)",
            "        if prow == PAY_CONTINUE:",
            "            cursor = tag",
            "            tag = np.int64(0)",
            "        elif kind == START and every[a] > 0:",
            "            if (tag & _PERIODIC_QUEUED) == 0:",
            "                if free_n[worker] < 1:",
            f"                    miss[0] = {self.r('timers')}",
            "                    return _NEED_NODES, i",
            ("                tn = periodic_time(seed, inst[g], a, tag + 1, every[a], jitter[a], "
             "sim_start)"),
            "                if tn < t:",
            "                    tn = t",
            "                sq = cseq[g]",
            "                cseq[g] = sq + 1",
            ("                nn_ = q_push(P, worker, qhead, g, tn, PRIO_MESSAGE, 0, sq, START, a, "
             "tag + 1, -1)"),
            "                P[_P_CPID][nn_] = 0",                     # D80: no cause
            "                P[_P_CEID][nn_] = _NULL_CAUSE",
            "                P[3][node] = tag | _PERIODIC_QUEUED",
            "            tag = tag & ~_PERIODIC_QUEUED",
            "        pay = nopay",
            "        prw = np.int64(0)",
            "        sender = np.int64(0)",
            "        if prow >= 0:",
            "            pay = PA[0]",
            "            prw = np.int64(prow)",
            "            sender = pay[prw, 9]",
            "        cmd = (kind, tag, t, cursor, sender, pay, prw)",
            "        lamport = max(clock[g], cause) + 1",
            "        kc[0] = 0",
            "        reqc[0] = 0",
            "        miss[0] = -1",
            "        ob0 = cnt[R_REQUESTS]",
            "        oc = occ_col[a]",
            ("        ctx = (t, self_id[g], pid[g], g, inst[g], a, np.int64(occ[g, oc]), kc, seed, "
             "args[0], args[1], args[2], lamport, np.int64(0))"),
            f"        rc = {disp}(a, ctx, cmd, ws, out)",
            "        if rc == RETRY:",
            "            counters[_C_RETRIES] += 1",
            "            counters[_C_RETRY_STREAK] += 1",
            "            if counters[_C_RETRY_STREAK] >= _MAX_RETRIES:",
            '                raise EngineError("command retried 8 times without progress")',
            f"            if miss[0] == {self.r('timers')}:",
            "                return _NEED_NODES, i",
            "            return _NEED_SWAP, i",
            "        if rc < RETRY:",
            '            raise EngineError("kernel returned an invalid code ", rc)',
            "        nresp = 0",
            "        for r_ in range(ob0, cnt[R_REQUESTS]):",
            "            if obx[OBX_KIND][r_] == OB_RESPONSE:",
            "                nresp += 1",
            "        asked = prow >= 0 and PA[0][prow, PAY_KIND] == OB_REQUEST",
            "        if (asked and (rc != COMMIT or nresp != 1)) or (not asked and nresp != 0):",
            # the command's sender: its payload's src_g if delivered, else the partition itself
            "            sg_ = PA[0][prow, 7] if prow >= 0 else g",
            "            _unpaired(a, kind, rc, nresp, pid[g], pid[sg_], P[2][node])",
            "        counters[_C_RETRY_STREAK] = 0",
            "        counters[_C_COMMANDS] += 1",
            "        occ[g, oc] += 1",
            "        q_remove(P, qhead, g, node)",
            "        q_free(P, worker, node)",
            "        if prow >= 0:",
            "            pay_free(PA, worker, prow)",
            "        elif prow == PAY_CONTINUE:",
            "            counters[_C_CONTINUATIONS] += 1",
            "        last_t[g] = t",
            "        prev_t = t",
            "        ran = True",
            "        if rc == COMMIT:",
            "            clock[g] = lamport",
            "            c_ = clog_n[0]",                            # D80: log the commit
            "            clog[c_, 0] = pid[g]",
            "            clog[c_, 1] = lamport",
            "            clog[c_, 2] = cpid_",
            "            clog[c_, 3] = cause",
            "            clog[c_, 4] = ceid_",
            "            clog_n[0] = c_ + 1",
            "            if reqc[0] > 0:",
            "                pending[g] += reqc[0]",
            "                st_ = _I64_MAX",
            "                sd_ = _I64_MAX",
            "                for r_ in range(ob0, cnt[R_REQUESTS]):",
            "                    if obx[OBX_KIND][r_] == OB_REQUEST:",
            "                        st_ = min(st_, obx[OBX_TIME][r_])",
            "                        sd_ = min(sd_, bnd_delta[obx[OBX_BND][r_]])",
            "                susp_t[g] = st_",
            "                susp_delta[g] = sd_",
            "                break",
            "        else:",
            "            rejects[a] += 1",
            ("    if ran and qhead[g] < 0 and pending[g] == 0 and retire[ptype[g]] != 0 "
             "and retire_at[g] == _I64_MAX:"),
            "        retire_at[g] = prev_t",
            "return _DONE, slots.shape[0]"]
        self.fn("run_partitions", "W, out, worker, slots, start, limit_t, owners", body)

    # ------------------------------------------------------------------ admission (D44)
    def _owner_parts(self) -> list:
        return [p for p in self.plan.partitions if p.kind == "owner"]

    def _started(self, part, ns: str) -> list[int]:
        """Actions started by `on_created(ns)` on owner partition `part`, in plan order."""
        return [p.action_id for p in self.plan.processes if p.partition == part.name
                and p.start is not None and p.start.table == ns]

    def _admission_tables(self) -> tuple[list[int], list[int]]:
        """Per namespace code: owner partition type (index in plan order, -1 if the namespace
        is not an owner table) and the number of STARTs an admission queues (at least one
        entry each, so the generated tuples are never empty)."""
        owners = self._owner_parts()
        by_table = {p.table: (t, p) for t, p in enumerate(owners)}
        members = set(self.plan.member_tables)
        ns_type, ns_nstart = [], []
        for ns in self.plan.namespaces:
            # member rows (D74) are never admitted: no creation message names their namespace
            t, part = (-1, None) if ns in members else by_table.get(ns, (-1, None))
            ns_type.append(t)
            ns_nstart.append(0 if part is None else len(self._started(part, ns)))
        return (ns_type or [-1]), (ns_nstart or [0])

    def admit(self) -> None:
        """`admit_created(W, R, CQ, FS, limit_t, out_slots) -> (status, value)` (D44).

        Admits every queued creation with time < limit_t in routing order (time, prio, cause,
        the creator's sender key, src_seq; D61) with the records S1's Python admission made.
        All or nothing: before touching anything it checks the admission limit (`_ADM_CAP`),
        the creating process's spawn depth (`_ADM_DEPTH`, D72: the created owner's depth is its
        creator's + 1), free local slots per owner type (`_ADM_LIVE`; these three return the CQ
        row that does not fit) and the reserve's command nodes for every START (`_ADM_NODES`,
        value = nodes needed), so a retry after any non-OK status sees `CQ` exactly as before
        (F-10)."""
        hid = ["pid", "alive", "clock", "rseq", "cseq", "pending", "susp_delta", "occ", "ordn",
               "retire_at", "susp_t", "last_t", "inst", "self_id", "ckey", "created", "qhead",
               "depth"]
        body = ["if CQ[CQ_N][0] == 0:                 # nothing pending: no allocation",
                "    return np.int64(_ADM_OK), np.int64(0)",
                "due = cq_due(CQ, limit_t)",
                "nd = due.shape[0]",
                "if nd == 0:",
                "    return np.int64(_ADM_OK), np.int64(0)",
                "due = cq_order(CQ, due, sender_keys(R, CQ[CQ_SRC_G][due], nd))",
                "adm = R[RT_ADM]",
                "free = FS[FS_N]",
                "taken = np.zeros(free.shape[0], np.int64)",
                "need = np.int64(0)",
                "hid = W[_W_HID]"]
        body += [f"{n} = hid[_WH_{n.upper()}]" for n in hid]
        body += ["maxdep = W[_W_MAX_DEPTH]",
                "for j in range(nd):",
                "    i = due[j]",
                "    if adm[0] + j + 1 > adm[1]:",
                "        return np.int64(_ADM_CAP), np.int64(i)",
                "    if np.int64(depth[CQ[CQ_SRC_G][i]]) + 1 > maxdep[CQ[CQ_ACTION][i]]:",
                "        return np.int64(_ADM_DEPTH), np.int64(i)",
                "    ns = CQ[CQ_NS][i]",
                "    t = _NS_TYPE[ns]",
                "    taken[t] += 1",
                "    if taken[t] > free[t]:",
                "        return np.int64(_ADM_LIVE), np.int64(i)",
                "    need += _NS_NSTART[ns]",
                "P = R[RT_POOL]",
                "if P[P_FREE_N][0] < need:",
                "    return np.int64(_ADM_NODES), need"]
        body += ["pay = CQ[CQ_PAYLOAD]",
                 "woken = R[RT_WOKEN]",
                 "wn = R[RT_WOKEN_N]",
                 "for j in range(nd):",
                 "    i = due[j]",
                 "    ns = CQ[CQ_NS][i]",
                 "    t = _NS_TYPE[ns]",
                 "    ls = np.int64(fs_take1(FS, t))",
                 "    adm[0] += 1",
                 "    g = FS[FS_BASE][t] + ls",
                 "    h = CQ[CQ_HANDLE][i]",
                 "    cause = CQ[CQ_CAUSE][i]",
                 "    k = CQ[CQ_K][i]",
                 "    ci = inst[CQ[CQ_SRC_G][i]]",
                 # fresh hidden fields, as S1's `World._reset_slots` (pid = self_id = handle)
                 "    pid[g] = h",
                 "    self_id[g] = h",
                 "    alive[g] = 1",
                 "    clock[g] = 0",
                 "    rseq[g] = 0",
                 "    cseq[g] = 0",
                 "    pending[g] = 0",
                 "    susp_delta[g] = 0",
                 "    occ[g, :] = 0",
                 "    ordn[g, :] = 0",
                 "    retire_at[g] = _I64_MAX",
                 "    susp_t[g] = _I64_MAX",
                 "    last_t[g] = _I64_MIN",
                 "    inst[g] = as_i64(mix4(ci, cause, ns, k))",
                 # its sender key for life (D61): (created_at, creator lamport, creator inst, k)
                 "    ckey[g, 0] = CQ[CQ_TIME][i]",
                 "    ckey[g, 1] = cause",
                 "    ckey[g, 2] = ci",
                 "    ckey[g, 3] = k",
                 "    created[g] = 1",
                 "    depth[g] = depth[CQ[CQ_SRC_G][i]] + 1"]
        owners = self._owner_parts()
        for code, ns in enumerate(self.plan.namespaces):
            t = next((t for t, p in enumerate(owners) if p.table == ns), None)
            if t is None or ns in self.plan.member_tables:
                continue
            part = owners[t]
            body += [f"    if ns == {code}:", f"        st_ = W[_W_OSTATE][{t}]"]
            body += [f"        st_[{j}][ls] = pay[i, {j}]"
                     for j in range(len(self.plan.table(part.table).cols))]
            for p in self.procs_of_partition(part.name):
                if p.kernel.local is None:
                    continue
                body.append(f"        lc_ = W[_W_STATE][{p.action_id}][2]")
                for f, (kind, width) in enumerate(p.kernel.local.fields.values()):
                    v = "_NULL" if kind == "ref" else "0"
                    body.append(f"        lc_[{f}][ls] = {v}" if width == 1
                                else f"        lc_[{f}][ls, :] = {v}")
            for a in self._started(part, ns):
                body += ["        sq_ = cseq[g]",
                         "        cseq[g] = sq_ + 1",
                         (f"        nn_ = q_push(P, 0, qhead, g, CQ[CQ_TIME][i], PRIO_MESSAGE, "
                          f"cause, sq_, START, {a}, 0, -1)"),
                         "        P[_P_CPID][nn_] = CQ[CQ_SRC_PID][i]",     # D80
                         "        P[_P_CEID][nn_] = _UNSET_CAUSE"]
        body += ["    mark_touched(R, g)",
                 "    woken[wn[0]] = g",
                 "    wn[0] += 1",
                 "    out_slots[j] = g",
                 "cq_remove(CQ, due, nd)",
                 "return np.int64(_ADM_OK), np.int64(nd)"]
        self.fn("admit_created", "W, R, CQ, FS, limit_t, out_slots", body)

    def now_ns(self) -> None:
        """Nanoseconds of `time.perf_counter_ns`'s clock from compiled code, for the shard-phase
        timer (D55, F-03): `engine.clock.clock_ns`, a direct C call (no objmode; Task 19)."""
        self.fn("_now_ns", "", ["return _clock_ns()"])

    def drain_small_rounds(self) -> None:
        """Whole rounds on worker 0 in compiled code (D4); see the contract at the top."""
        py = ["        rs[_RS_STATUS] = st", "        return _DR_PYTHON, n_run"]
        py2 = ["    " + ln for ln in py]
        self.fn("drain_small_rounds",
                ("W, out, R, CQ, FS, run, n_run, t1, min_par, shard_lo, shard_hi, sbuf, log, rs, "
                 "adm_buf"), [
                    "counters = W[_W_COUNTERS]",
                    "cnt = out[OUT_CNT]",
                    "obx = out[OUT_OUTBOX]",
                    "nlog = np.int64(0)",
                    "while True:",
                    "    rs[_RS_NLOG] = nlog",
                    "    nsh = shards_below(R, shard_lo, shard_hi, t1, sbuf)",
                    "    if n_run == 0 and nsh == 0 and CQ[CQ_N][0] == 0:",
                    "        return _DR_CLOSED, n_run",
                    "    if n_run >= min_par:",
                    "        return _DR_LARGE, n_run",
                    "    if nlog >= log.shape[0]:",
                    "        return _DR_LOG_FULL, n_run",
                    "    rs[_RS_PHASE] = _PH_OWNERS",
                    "    st, i_ = run_partitions(W, out, 0, run[:n_run], 0, t1, True)",
                    "    if st != _DONE:", *py,
                    "    note_suspended(R, run, n_run)",
                    "    rs[_RS_PHASE] = _PH_ROUTE1",
                    "    st, k_ = route_outbox(R, CQ, obx, cnt[R_REQUESTS])",
                    "    if st != 0:", *py,
                    "    cnt[R_REQUESTS] = 0",
                    "    h = horizon(R, t1, cq_min(CQ))",
                    "    c0 = command_count(counters)",
                    "    rs[_RS_H] = h",
                    "    rs[_RS_C0] = c0",
                    "    rs[_RS_PHASE] = _PH_SHARDS",
                    "    nsh = shards_below(R, shard_lo, shard_hi, h, sbuf)",
                    "    mark_all(R, sbuf, nsh)",
                    "    ts_ = _now_ns()",
                    "    st, i_ = run_partitions(W, out, 0, sbuf[:nsh], 0, h, False)",
                    "    rs[_RS_SHARD_NS] += _now_ns() - ts_",
                    "    if st != _DONE:", *py,
                    "    rs[_RS_PHASE] = _PH_ROUTE2",
                    "    st, k_ = route_outbox(R, CQ, obx, cnt[R_REQUESTS])",
                    "    if st != 0:", *py,
                    "    cnt[R_REQUESTS] = 0",
                    "    na_ = np.int64(0)",
                    "    if CQ[CQ_N][0] > 0:                  # no call when nothing is pending",
                    "        rs[_RS_PHASE] = _PH_ADMIT",
                    "        st, na_ = admit_created(W, R, CQ, FS, t1, adm_buf)",
                    "        if st != _ADM_OK:", *py2,
                    "    sc = command_count(counters) - c0",
                    "    if n_run == 0 and sc == 0 and na_ == 0:",
                    "        return _DR_NO_PROGRESS, n_run",
                    "    log[nlog, 0] = n_run",
                    "    log[nlog, 1] = sc",
                    "    nlog += 1",
                    "    n_run = take_runnable(R, t1, run)"])

    # ------------------------------------------------------------------ everything
    def generate(self) -> list[str]:
        self.rng_helpers()
        for p in self.plan.processes:
            self.reserve(p)
        for e in self.plan.events:
            self.emit(e)
        for grp in self.plan.change_groups:
            self.change(grp)
        for a in self.plan.accumulators:
            self.accumulate(a)
        tables = {t.name for t in self.plan.tables}
        members = set(self.plan.member_tables)
        for code, ns in enumerate(self.plan.namespaces):
            if ns in tables:
                self.create(ns, code, outbox=ns not in members)
        self.new_id()
        self.fn("_mstat", "out, ctx, i, v", ["ms = out[OUT_MSTAT]", "ms[i] += v"])   # D82
        self.timer()
        self.continue_at()
        self.outbox_row()
        for bd in self.plan.boundaries:
            if bd.kind == "request":
                self.outbound(bd, "request")
                for resp in bd.responses:
                    self.respond(bd, resp)
            else:
                self.outbound(bd, "send")
        self.dispatch()
        self.periodic_time()
        if self.checked:
            self.checked_dispatch()
        self.out_of_order()
        self.unpaired()
        self.run_partitions()
        self.admit()
        self.now_ns()
        self.drain_small_rounds()
        return self.funcs


def _decorate(lowered: str) -> str:
    """Put the (inlining) JIT decorator on every top-level function of a lowered module."""
    return "\n".join(f"{_JIT_INLINE}\n{ln}" if ln.startswith("def ") else ln
                     for ln in lowered.split("\n"))


def _top_level_names(source: str) -> set[str]:
    names: set[str] = set()
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef):
            names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names |= {(a.asname or a.name).split(".")[0] for a in node.names}
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                names |= {n.id for n in ast.walk(t) if isinstance(n, ast.Name)}
    return names


def lowered_kernels(plan: Plan) -> list[str]:
    """Lower every kernel module of the plan (one module per kernel source file; a machine
    process's `KernelSpec.source`, its file followed by the generated text, replaces it)."""
    layouts = kernel_layouts(plan)
    by_file: dict[str, dict[str, str]] = {}
    for p in plan.processes:
        funcs = by_file.setdefault(p.kernel.module_file, {})
        if funcs.setdefault(p.kernel.name, p.name) != p.name:
            raise LoweringError(f"kernel {p.kernel.name} is used by processes "
                                f"{funcs[p.kernel.name]} and {p.name}; give each its own kernel")
    sources: dict[str, str] = {}          # generated machine text replaces its file (D62)
    for p in plan.processes:
        src = p.kernel.source
        if src is not None and sources.setdefault(p.kernel.module_file, src) != src:
            raise LoweringError(f"{p.kernel.module_file}: processes give different generated "
                                "sources for one kernels file")
    return [lower_module(sources.get(f) or Path(f).read_text(), layouts, funcs, filename=f)
            for f, funcs in by_file.items()]


def generate_module(plan: Plan, *, checked: bool) -> str:
    """Source of the engine module for `plan` (see the module docstring)."""
    gen = _Gen(plan, checked)
    consts = gen.constants()
    funcs = gen.generate()
    reserved = gen.names | _top_level_names(consts) | _top_level_names(_HEADER)
    kernels: list[str] = []
    seen: set[str] = set()
    for src in lowered_kernels(plan):
        names = _top_level_names(src) - {"std", "reject", *_ABI_NAMES}
        clash = sorted((names & reserved) | (names & seen))
        if clash:
            raise LoweringError(f"kernel module name {clash[0]!r} collides with a generated "
                                "engine name or another kernel module")
        seen |= names
        kernels.append(_decorate(src))
    header = f"{_HEADER}# runtime: {runtime_fingerprint()}\n"
    return "\n\n".join([header, consts, *kernels, *funcs])


_ABI_NAMES = ("COMMIT", "RETRY", "START", "PRIO_CONTINUE", "PRIO_MESSAGE", "PRIO_EXPIRY",
              "PRIO_TIMER")
