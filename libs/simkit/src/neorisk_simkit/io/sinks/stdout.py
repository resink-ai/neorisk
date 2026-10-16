"""Stdout sink: jsonl, table or csv. A closed pipe ends the sink quietly."""

from __future__ import annotations

import os
import sys

import pyarrow as pa

from neorisk_simkit.io.replay.planner import CanonicalKey
from neorisk_simkit.io.sinks.base import Progress, SinkOptions, SinkReport, encoded


class StdoutSink:
    def __init__(self) -> None:
        self.stopped = False   # the reader went away (BrokenPipeError)
        self._p = Progress("stdout")
        self._opts: SinkOptions | None = None
        self._first_table_batch = True

    def open(self, schema: pa.Schema, opts: SinkOptions) -> None:
        self._opts = opts
        self._p = Progress("stdout")
        if opts.format == "csv":
            self._emit(",".join(schema.names) + "\n")

    def _emit(self, text: str) -> bool:
        try:
            sys.stdout.write(text)
            sys.stdout.flush()
            return True
        except BrokenPipeError:
            self._detach()
            return False

    def _detach(self) -> None:
        """Point stdout at /dev/null so the interpreter's exit flush cannot fail."""
        self.stopped = True
        try:
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        except (OSError, ValueError):
            pass

    def write(self, batch: pa.RecordBatch) -> None:
        if self.stopped or not batch.num_rows:
            return
        opts = self._opts
        text = encoded(batch, opts)
        if opts.format == "table" and not self._first_table_batch:
            text = text.partition("\n")[2]   # one header line for the whole stream
        self._first_table_batch = False
        if self._emit(text):
            self._p.add(batch)

    def checkpoint(self) -> CanonicalKey | None:
        return self._p.last

    def close(self) -> SinkReport:
        if not self.stopped:
            try:
                sys.stdout.flush()
            except BrokenPipeError:
                self._detach()
        return self._p.report()
