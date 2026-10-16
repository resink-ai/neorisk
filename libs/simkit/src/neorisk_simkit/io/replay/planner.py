"""Replay request validation and planning: which steps, which types, which Arrow schema."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from neorisk_simkit.io.schema.schema_json import load_schema
from neorisk_simkit.io.step_index import read_step_index
from neorisk_simkit.spec.types import COMMON_COLUMNS, LType, arrow_type

CanonicalKey = tuple[int, int, int, int]  # (event_time µs, lamport, partition_id, seq)
MAX_BATCH_ROWS = 65_536


class ReplayError(Exception):
    pass


@dataclass(frozen=True)
class ReplayRequest:
    first: int | None = None
    last: int | None = None
    t_from: int | None = None      # int µs since the epoch, inclusive
    t_to: int | None = None        # int µs since the epoch, exclusive
    types: tuple[str, ...] | None = None
    batch_rows: int = MAX_BATCH_ROWS


@dataclass
class ReplayPlan:
    dataset_dir: Path
    req: ReplayRequest
    steps: list[int]
    types: list[str]
    schema: pa.Schema
    doc: dict
    skip: int = 0                  # rows dropped from the front of the stream (`--last`)
    limit: int | None = None       # rows emitted at most (`--first` / `--last`)
    files_opened: int = field(default=0)


def _unified_type(kind: str) -> pa.DataType:
    t = arrow_type(LType(kind))
    return pa.string() if pa.types.is_dictionary(t) else t


_INT_WIDTH = {pa.int16(): 16, pa.int32(): 32, pa.int64(): 64}


def _common_type(name: str, a: pa.DataType, b: pa.DataType) -> pa.DataType:
    """Widest of two integer types; any other mismatch has no common type."""
    if a in _INT_WIDTH and b in _INT_WIDTH:
        return a if _INT_WIDTH[a] >= _INT_WIDTH[b] else b
    raise ReplayError(f"column {name!r} has incompatible types across the selected event "
                      f"types ({a} vs {b}); narrow --types")


def unified_schema(doc: dict, types: list[str]) -> pa.Schema:
    """Common columns, then the union of the selected types' columns (all nullable, D23)."""
    tables = {t["name"]: t for t in doc["tables"] if t["kind"] == "event"}
    fields: dict[str, pa.DataType] = {}
    if tables:
        for c in next(iter(tables.values()))["columns"][:len(COMMON_COLUMNS)]:
            fields[c["name"]] = _unified_type(c["type"])
    for tname in types:
        for c in tables[tname]["columns"]:
            ty = _unified_type(c["type"])
            have = fields.setdefault(c["name"], ty)
            if have != ty:
                fields[c["name"]] = _common_type(c["name"], have, ty)
    return pa.schema([pa.field(n, t, nullable=True) for n, t in fields.items()])


def _validate(req: ReplayRequest) -> None:
    if req.first is not None and req.last is not None:
        raise ReplayError("use either --first or --last, not both")
    for name, n in (("--first", req.first), ("--last", req.last)):
        if n is not None and n <= 0:
            raise ReplayError(f"{name} must be a positive number, got {n}")
    if req.t_from is not None and req.t_to is not None and req.t_from >= req.t_to:
        raise ReplayError(f"--from must be before --to (got {req.t_from} >= {req.t_to})")
    if not 0 < req.batch_rows <= MAX_BATCH_ROWS:
        raise ReplayError(f"batch_rows must be in 1..{MAX_BATCH_ROWS}, got {req.batch_rows}")


def time_mask(times: pa.Array | pa.ChunkedArray, req: ReplayRequest):
    """Boolean mask of `t_from <= event_time < t_to`, or None when no time filter is set."""
    if req.t_from is None and req.t_to is None:
        return None
    t = pc.cast(times, pa.int64())
    mask = None
    if req.t_from is not None:
        mask = pc.greater_equal(t, req.t_from)
    if req.t_to is not None:
        m2 = pc.less(t, req.t_to)
        mask = m2 if mask is None else pc.and_(mask, m2)
    return mask


def step_files(dataset_dir: Path, types: list[str], steps: list[int] | None = None
               ) -> dict[tuple[str, int], list[Path]]:
    """`{(type, step): files}` with a step's files in `date=` order (a step that crosses
    midnight has one file per day, and the earlier day holds the earlier events)."""
    want = None if steps is None else set(steps)
    out: dict[tuple[str, int], list[Path]] = {}
    for t in types:
        for p in sorted((Path(dataset_dir) / "events" / t).glob("date=*/step-*.parquet"),
                        key=lambda p: (p.parent.name, p.name)):
            n = int(p.stem.split("-")[1])
            if want is None or n in want:
                out.setdefault((t, n), []).append(p)
    return out


def _count_in_window(plan: ReplayPlan, step: int, files: dict) -> int:
    """Exact rows of one step inside the time window (reads only `event_time`)."""
    total = 0
    for t in plan.types:
        for f in files.get((t, step), ()):
            plan.files_opened += 1
            col = pq.read_table(f, columns=["event_time"]).column("event_time")
            mask = time_mask(col, plan.req)
            total += col.length() if mask is None else pc.sum(pc.cast(mask, pa.int64())).as_py() or 0
    return total


def plan_replay(dataset_dir: Path, req: ReplayRequest) -> ReplayPlan:
    _validate(req)
    d = Path(dataset_dir)
    doc = load_schema(d)
    known = [t["name"] for t in doc["tables"] if t["kind"] == "event"]
    if req.types is not None:
        for t in req.types:
            if t not in known:
                raise ReplayError(f"unknown event type {t!r} (known: {', '.join(known)})")
        types = [t for t in known if t in set(req.types)]
    else:
        types = known
    plan = ReplayPlan(d, req, [], types, unified_schema(doc, types), doc)
    if not types:
        return plan
    idx = read_step_index(d)
    rows = [0] * idx.num_rows
    for t in types:
        col = idx.column(f"rows__{t}").to_pylist()
        rows = [a + (b or 0) for a, b in zip(rows, col, strict=True)]
    first_t = pc.cast(idx.column("first_time"), pa.int64()).to_pylist()
    last_t = pc.cast(idx.column("last_time"), pa.int64()).to_pylist()
    step_no = idx.column("step").to_pylist()
    # (step, rows of the selected types, whether the window may cut the step)
    cand: list[tuple[int, int, bool]] = []
    for s, n, lo, hi in zip(step_no, rows, first_t, last_t, strict=True):
        if n == 0:
            continue
        if (req.t_from is not None and hi < req.t_from) or (req.t_to is not None and lo >= req.t_to):
            continue
        cut = (req.t_from is not None and lo < req.t_from) or (
            req.t_to is not None and hi >= req.t_to)
        cand.append((s, n, cut))
    if req.first is not None:
        plan.limit = req.first
    if req.last is None:
        plan.steps = [s for s, _, _ in cand]
        return plan
    # --last N: walk the steps backwards until N rows are covered (exact counts where the
    # window may cut a step or the index counts every type), then emit forward.
    files = step_files(d, types, [s for s, _, _ in cand]) if any(c for _, _, c in cand) else {}
    chosen: list[int] = []
    have = 0
    for s, n, cut in reversed(cand):
        have += _count_in_window(plan, s, files) if cut else n
        chosen.append(s)
        if have >= req.last:
            break
    plan.steps = chosen[::-1]
    plan.skip = max(0, have - req.last)
    plan.limit = req.last
    return plan

