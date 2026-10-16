"""Streaming replay: a k-way merge of the sorted step files, in canonical order.

Every step file is sorted by the canonical key `(event_time, lamport, partition_id, seq)` and
the steps are time-disjoint ascending, so per step the selected types' files are merged with a
watermark: each source keeps one buffered batch, everything at or below the smallest buffered
tail key is final and is emitted, the rest stays buffered. Memory is one batch per source."""

from __future__ import annotations

from collections.abc import Iterator

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from neorisk_simkit.io.replay.planner import ReplayPlan, step_files, time_mask

_KEY = ("event_time", "lamport", "partition_id", "seq")


def _unify(batch: pa.RecordBatch | pa.Table, schema: pa.Schema) -> pa.Table:
    """Cast to the unified schema: dictionaries to string, missing columns as nulls."""
    t = pa.Table.from_batches([batch]) if isinstance(batch, pa.RecordBatch) else batch
    cols = []
    for f in schema:
        if f.name in t.column_names:
            c = t.column(f.name)
            cols.append(c if c.type == f.type else pc.cast(c, f.type))
        else:
            cols.append(pa.nulls(t.num_rows, f.type))
    return pa.Table.from_arrays(cols, schema=schema)


def _source(plan: ReplayPlan, files: list) -> Iterator[pa.Table]:
    """Filtered, unified batches of one type's files of one step, in order."""
    for f in files:
        plan.files_opened += 1
        for rb in pq.ParquetFile(f).iter_batches(batch_size=plan.req.batch_rows):
            t = _unify(rb, plan.schema)
            mask = time_mask(t.column("event_time"), plan.req)
            if mask is not None:
                t = t.filter(mask)
            if t.num_rows:
                yield t


def _tail(t: pa.Table) -> tuple[int, ...]:
    i = t.num_rows - 1
    return (t.column("event_time")[i].cast(pa.int64()).as_py(),
            *(t.column(k)[i].as_py() for k in _KEY[1:]))


def _count_le(t: pa.Table, w: tuple[int, ...]) -> int:
    """Rows of the key-sorted `t` with key <= w (a prefix, found with a vectorized compare)."""
    cols = [pc.cast(t.column("event_time"), pa.int64()), *(t.column(k) for k in _KEY[1:])]
    le = pc.less_equal(cols[3], w[3])
    for c, v in zip(reversed(cols[:3]), reversed(w[:3]), strict=True):
        le = pc.or_(pc.less(c, v), pc.and_(pc.equal(c, v), le))
    return pc.sum(pc.cast(le, pa.int64())).as_py() or 0


def _merge_step(plan: ReplayPlan, sources: list[Iterator[pa.Table]]) -> Iterator[pa.Table]:
    bufs: list[pa.Table | None] = [None] * len(sources)
    live = [True] * len(sources)
    while True:
        for i, it in enumerate(sources):
            if live[i] and bufs[i] is None:
                bufs[i] = next(it, None)
                live[i] = bufs[i] is not None
        held = [i for i, b in enumerate(bufs) if b is not None]
        if not held:
            return
        w = min(_tail(bufs[i]) for i in held if live[i]) if any(live) else None
        heads = []
        for i in held:
            b = bufs[i]
            n = b.num_rows if w is None else _count_le(b, w)
            if n:
                heads.append(b.slice(0, n))
            bufs[i] = b.slice(n) if n < b.num_rows else None
        out = heads[0] if len(heads) == 1 else pa.concat_tables(heads).sort_by(
            [(k, "ascending") for k in _KEY])
        yield out


def iter_batches(plan: ReplayPlan) -> Iterator[pa.RecordBatch]:
    """Canonical-order batches of at most `batch_rows` rows, honouring `--first`/`--last`."""
    n = plan.req.batch_rows
    skip, left = plan.skip, plan.limit
    files = step_files(plan.dataset_dir, plan.types, plan.steps)
    for step in plan.steps:
        sources = [_source(plan, files[(t, step)]) for t in plan.types if (t, step) in files]
        for t in _merge_step(plan, sources):
            if skip:
                drop = min(skip, t.num_rows)
                t, skip = t.slice(drop), skip - drop
            for off in range(0, t.num_rows, n):
                piece = t.slice(off, n)
                if left is not None:
                    piece = piece.slice(0, left)
                    left -= piece.num_rows
                if piece.num_rows:
                    yield from piece.combine_chunks().to_batches(max_chunksize=n)
                if left == 0:
                    return
