"""`_index/steps.parquet`: one row per step with the first and last canonical key and the
number of rows per event type."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from neorisk_simkit.io.seal import SealedStep

_TS = pa.timestamp("us", tz="UTC")
_KEY = (("time", _TS), ("lamport", pa.int64()), ("partition", pa.int64()), ("seq", pa.int32()))
_KEY_COLS = ("event_time", "lamport", "partition_id", "seq")
INDEX_PATH = "_index/steps.parquet"


def _key_at(table: pa.Table, i: int) -> tuple:
    return tuple(table[c][i].cast(pa.int64()).as_py() if c == "event_time"
                 else table[c][i].as_py() for c in _KEY_COLS)


def step_index_row(sealed: SealedStep, plan: Any) -> dict:
    """The index row of one sealed step (keys are null when the step holds no event rows)."""
    row: dict[str, Any] = {"step": sealed.step, "t_start": sealed.t_start,
                           "t_end": sealed.t_end}
    keys_first, keys_last = [], []
    for e in plan.events:
        t = sealed.events.get(e.name)
        n = 0 if t is None else t.num_rows
        row[f"rows__{e.name}"] = n
        if n:
            keys_first.append(_key_at(t, 0))
            keys_last.append(_key_at(t, n - 1))
    row["rows"] = sum(row[f"rows__{e.name}"] for e in plan.events)
    for prefix, keys, pick in (("first", keys_first, min), ("last", keys_last, max)):
        key = pick(keys) if keys else (None,) * 4
        for (name, _), v in zip(_KEY, key, strict=True):
            row[f"{prefix}_{name}"] = v
    return row


def write_step_index(run_dir: Path, rows: list[dict], options: dict | None = None):
    """Write the index (columns: step, t_start, t_end, rows, first_*, last_*, rows__<type>...)
    and return the written file's path."""
    names = list(rows[0]) if rows else ["step", "t_start", "t_end", "rows"]
    head = ["step", "t_start", "t_end", "rows"]
    first = [f"first_{n}" for n, _ in _KEY]
    last = [f"last_{n}" for n, _ in _KEY]
    per_type = [n for n in names if n.startswith("rows__")]
    types = {"step": pa.int32(), "t_start": _TS, "t_end": _TS, "rows": pa.int64(),
             **{f"first_{n}": t for n, t in _KEY}, **{f"last_{n}": t for n, t in _KEY},
             **{n: pa.int64() for n in per_type}}
    cols = [*head, *first, *last, *per_type]
    schema = pa.schema([pa.field(c, types[c]) for c in cols])
    arrays = [pa.array([r.get(c) for r in rows], types[c]) for c in cols]
    path = Path(run_dir) / INDEX_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_arrays(arrays, schema=schema), path, **(options or {}))
    return path


def read_step_index(run_dir: Path) -> pa.Table:
    return pq.read_table(Path(run_dir) / INDEX_PATH)
