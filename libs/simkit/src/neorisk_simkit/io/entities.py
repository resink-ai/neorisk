"""Entity tables: `entities/<table>/part-00000.parquet`, one file per table, at the end of a run.

Static rows (read tables and population owners) come first, then the rows created in each step
(in step order); both are already in dense order, so the file is in dense order."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa

from neorisk_simkit.io.writer import FileEntry, plan_columns, write_parquet, writer_options


class EntityCollector:
    def __init__(self) -> None:
        self._parts: dict[str, list[pa.Table]] = {}

    def add(self, tables: dict[str, pa.Table]) -> None:
        for name, t in tables.items():
            if t.num_rows or name not in self._parts:
                self._parts.setdefault(name, []).append(t)

    def counts(self) -> dict[str, int]:
        return {n: sum(t.num_rows for t in ts) for n, ts in sorted(self._parts.items())}

    def write(self, run_dir: Path, writer: Any, plan: Any) -> list[FileEntry]:
        options = writer_options(writer, *plan_columns(plan))
        out = []
        for name, parts in sorted(self._parts.items()):
            table = pa.concat_tables(parts) if len(parts) > 1 else parts[0]
            out.append(write_parquet(run_dir, f"entities/{name}/part-00000.parquet", table,
                                     options))
        return out
