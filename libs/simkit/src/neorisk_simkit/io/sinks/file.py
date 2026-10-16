"""File sink: written to PATH.tmp and renamed to PATH only when complete."""

from __future__ import annotations

import contextlib
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from neorisk_simkit.io.replay.planner import CanonicalKey
from neorisk_simkit.io.sinks.base import Progress, SinkOptions, SinkReport, encoded


class FileSink:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.tmp = self.path.with_name(self.path.name + ".tmp")
        self._p = Progress(f"file:{path}")
        self._fh = None
        self._pq: pq.ParquetWriter | None = None
        self._opts: SinkOptions | None = None
        self._any = False

    def open(self, schema: pa.Schema, opts: SinkOptions) -> None:
        self._opts = opts
        self._p = Progress(self._p.name)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if opts.format == "parquet":
            self._pq = pq.ParquetWriter(self.tmp, schema, compression="zstd")
            return
        self._fh = open(self.tmp, "w", encoding="utf-8", newline="")  # noqa: SIM115
        if opts.format == "json-array":
            self._fh.write("[")
        elif opts.format == "csv":
            self._fh.write(",".join(schema.names) + "\n")

    def write(self, batch: pa.RecordBatch) -> None:
        if not batch.num_rows:
            return
        if self._pq is not None:
            self._pq.write_batch(batch)
        else:
            text = encoded(batch, self._opts)
            if self._opts.format == "json-array":
                text = ("," if self._any else "") + text
            self._fh.write(text)
        self._any = True
        self._p.add(batch)

    def checkpoint(self) -> CanonicalKey | None:
        if self._fh is not None:
            self._fh.flush()
        return self._p.last

    def _release(self) -> None:
        fh, writer = self._fh, self._pq
        self._fh = self._pq = None
        if writer is not None:
            writer.close()
        if fh is not None:
            fh.close()

    def close(self) -> SinkReport:
        try:
            if self._fh is not None and self._opts.format == "json-array":
                self._fh.write("]\n")
            self._release()
            os.replace(self.tmp, self.path)
        except BaseException:
            self.abort()
            raise
        return self._p.report()

    def abort(self, error: str | None = None) -> SinkReport:
        """Drop the partial output: no final file is created and no `.tmp` is left."""
        with contextlib.suppress(Exception):   # the output is discarded anyway
            self._release()
        self.tmp.unlink(missing_ok=True)
        return self._p.report(error)
