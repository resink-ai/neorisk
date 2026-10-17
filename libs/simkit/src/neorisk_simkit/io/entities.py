"""Entity tables: `entities/<table>/part-00000.parquet`, one file per table, streamed as the run
goes.

Static rows (read tables and population owners) come first, then the rows created in each step
(in step order); both are already in dense order, so the file is in dense order.

Rows are written in full row groups (`writer.row_group_rows`) as soon as a table has that many
buffered, so at most one partial row group per table stays in memory. A row group is written
from the same Arrow chunks, in the same order, as one `pq.write_table` of the concatenation of
every part would use, so the file bytes are identical to writing the whole table at the end.

The buffered rows are the `entity_buffers` memory item (spec section 10): validate reserves
`spec.caps.entity_buffer_bytes`, and `EntityWriter.add` fails with `CapExceeded` if the bytes
actually buffered ever exceed that reservation.
"""

from __future__ import annotations

import contextlib
import hashlib
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from neorisk_simkit.engine.errors import CapExceeded
from neorisk_simkit.io.writer import FileEntry, plan_columns, writer_options
from neorisk_simkit.spec.caps import entity_buffer_bytes


def _own_buffers(table: pa.Table) -> pa.Table:
    """`table` with every chunk copied, chunk boundaries kept: a slice's tail no longer pins
    the buffers of the whole step table it came from."""
    cols = [pa.chunked_array([pa.concat_arrays([c]) for c in col.chunks], col.type)
            for col in table.columns]
    return pa.Table.from_arrays(cols, schema=table.schema)


class _TableStream:
    def __init__(self, path: Path, schema: pa.Schema, options: dict):
        self.path = path
        self.rows = 0
        self._group = int(options["row_group_size"])
        self._options = {k: v for k, v in options.items() if k != "row_group_size"}
        self._schema = schema
        self._writer: pq.ParquetWriter | None = None
        self._pending: list[pa.Table] = []
        self._pending_rows = 0
        self.buffered_bytes = 0

    @property
    def buffered_rows(self) -> int:
        return self._pending_rows

    def _write(self, table: pa.Table) -> None:
        if self._writer is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._writer = pq.ParquetWriter(self.path, self._schema, **self._options)
        self._writer.write_table(table, row_group_size=self._group)

    def add(self, table: pa.Table) -> None:
        if table.num_rows == 0:
            return
        self.rows += table.num_rows
        self._pending.append(table)
        self._pending_rows += table.num_rows
        self.buffered_bytes += table.nbytes
        if self._pending_rows < self._group:
            return
        joined = pa.concat_tables(self._pending)
        full = self._pending_rows - self._pending_rows % self._group
        self._write(joined.slice(0, full))
        rest = joined.slice(full)
        self._pending = [_own_buffers(rest)] if rest.num_rows else []
        self._pending_rows = rest.num_rows
        self.buffered_bytes = self._pending[0].nbytes if self._pending else 0

    def close(self) -> None:
        if self._pending or self._writer is None:
            # an empty table still gets its (empty) row group, like `pq.write_table`
            self._write(pa.concat_tables(self._pending) if self._pending
                        else self._schema.empty_table())
        self._pending, self._pending_rows, self.buffered_bytes = [], 0, 0
        self._writer.close()

    def abort(self) -> None:
        if self._writer is not None:
            self._writer.close()


class EntityWriter:
    """Streams every entity table to `run_dir/entities/<table>/part-00000.parquet`.

    `cap_bytes` (default: the pending part of the `entity_buffers` cap) bounds the bytes
    buffered across all tables between `add` calls, counted as logical Arrow bytes
    (`Table.nbytes`), not allocator capacity."""

    def __init__(self, run_dir: Path, writer: Any, plan: Any,
                 cap_bytes: int | None = None) -> None:
        self._run_dir = Path(run_dir)
        self._options = writer_options(writer, *plan_columns(plan))
        self._streams: dict[str, _TableStream] = {}
        self._cap = (entity_buffer_bytes(plan, writer.row_group_rows)[0] if cap_bytes is None
                     else int(cap_bytes))

    def add(self, tables: dict[str, pa.Table]) -> None:
        for name, t in tables.items():
            stream = self._streams.get(name)
            if stream is None:                     # the first part fixes the file schema
                stream = self._streams[name] = _TableStream(
                    self._run_dir / self.rel(name), t.schema, self._options)
            stream.add(t)
        used = sum(st.buffered_bytes for st in self._streams.values())
        if used > self._cap:
            raise CapExceeded("entity_buffers", self._cap, used)

    def buffered_rows(self, name: str) -> int:
        return self._streams[name].buffered_rows

    def counts(self) -> dict[str, int]:
        return {n: s.rows for n, s in sorted(self._streams.items())}

    @staticmethod
    def rel(name: str) -> str:
        return f"entities/{name}/part-00000.parquet"

    def close(self) -> list[FileEntry]:
        """Finish every file; entries in table-name order. If one fails, the files not yet
        finished are aborted and the failure is raised."""
        out = []
        streams = sorted(self._streams.items())
        for i, (name, stream) in enumerate(streams):
            try:
                stream.close()
            except BaseException:
                for _, rest in streams[i:]:
                    _quiet_abort(rest)
                raise
            digest = hashlib.sha256()
            with open(stream.path, "rb") as f:
                for block in iter(lambda: f.read(1 << 20), b""):
                    digest.update(block)
            out.append(FileEntry(self.rel(name), stream.rows, digest.hexdigest()))
        return out

    def abort(self) -> None:
        """Close open files after a failure (the run folder is discarded). Tries every stream
        and never raises, so the failure being handled is the one the caller sees."""
        for stream in self._streams.values():
            _quiet_abort(stream)


def _quiet_abort(stream: _TableStream) -> None:
    with contextlib.suppress(Exception):           # best effort: the folder is discarded
        stream.abort()
