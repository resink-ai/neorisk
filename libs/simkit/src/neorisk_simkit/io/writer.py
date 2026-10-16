"""Parquet writer with pinned settings (spec section 13; decisions D19, D20).

Every table of a sealed step is split by the UTC date of its time column and written as
`<kind>/<name>/date=YYYY-MM-DD/step-NNNNNN.parquet`; a step that crosses midnight writes the same
file name under two `date=` directories. Every file is sorted by the canonical key already.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from neorisk_simkit.io.seal import SealedStep

_DAY_US = 86_400_000_000


@dataclass(frozen=True)
class FileEntry:
    path: str                       # relative to the run folder, POSIX separators
    rows: int
    sha256: str


def writer_options(writer: Any, dict_cols: list[str], stat_cols: list[str]) -> dict:
    """The exact `pq.write_table` keyword arguments (pinned in the manifest)."""
    return {"compression": writer.compression, "compression_level": writer.compression_level,
            "row_group_size": writer.row_group_rows, "use_dictionary": dict_cols,
            "write_statistics": stat_cols}


def plan_columns(plan: Any) -> tuple[list[str], list[str]]:
    """`(dict_cols, stat_cols)`: dictionary encoding for `event_type` and every category column;
    statistics on `event_time`, `event_id`, `partition_id`, the ordering columns of history and
    entity tables (`valid_from`, `entity_id`, `id`) and every ref column."""
    groups = [*(e.cols for e in plan.events), *(g.cols for g in plan.change_groups),
              *(t.cols for t in plan.tables)]
    cols = [c for g in groups for c in g]
    dict_cols = {"event_type"} | {c.name for c in cols if c.ltype.kind == "cat"}
    stat_cols = {"event_time", "event_id", "partition_id", "valid_from", "entity_id", "id"}
    stat_cols |= {c.name for c in cols if c.ltype.kind == "ref"}
    return sorted(dict_cols), sorted(stat_cols)


def write_parquet(run_dir: Path, rel: str, table: pa.Table, options: dict) -> FileEntry:
    """Write `table` to `run_dir/rel` and return its entry (rows and sha256 of the bytes)."""
    sink = pa.BufferOutputStream()
    pq.write_table(table, sink, **options)
    data = sink.getvalue().to_pybytes()
    path = run_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return FileEntry(rel, table.num_rows, hashlib.sha256(data).hexdigest())


def _date(day: int) -> str:
    return datetime.fromtimestamp(day * 86_400, UTC).strftime("%Y-%m-%d")


def _by_date(table: pa.Table, time_col: str):
    """`(date string, slice)` for each UTC date of the (time-sorted) table."""
    t = table[time_col].cast(pa.int64()).to_numpy()
    days = t // _DAY_US
    cuts = np.flatnonzero(np.diff(days)) + 1
    starts = np.concatenate([[0], cuts])
    ends = np.concatenate([cuts, [len(t)]])
    for a, b in zip(starts.tolist(), ends.tolist(), strict=True):
        yield _date(int(days[a])), table.slice(a, b - a)


def write_step(run_dir: Path, sealed: SealedStep, writer: Any, plan: Any) -> list[FileEntry]:
    """Write every non-empty event and history table of `sealed`; entities are written at the
    end of the run (`io.entities`)."""
    options = writer_options(writer, *plan_columns(plan))
    out: list[FileEntry] = []
    for kind, tables, time_col in (("events", sealed.events, "event_time"),
                                   ("history", sealed.history, "valid_from")):
        for name, table in sorted(tables.items()):
            if table.num_rows == 0:
                continue
            for day, part in _by_date(table, time_col):
                rel = f"{kind}/{name}/date={day}/step-{sealed.step:06d}.parquet"
                out.append(write_parquet(run_dir, rel, part, options))
    return out
