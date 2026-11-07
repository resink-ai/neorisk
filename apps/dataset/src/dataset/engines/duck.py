"""The reference engine: DuckDB in-process, over `refdata.logviews`, running `specs/`.

It runs the same SQL the build does, but as an engine run: four threads (as Spark gets
`local[4]`), each table written to Parquet, and a block that fails fails only its table.
"""

from __future__ import annotations

import time

import duckdb
import pyarrow.parquet as pq

from dataset.engines import Built, Job, Timings
from refdata.logviews import attach_log


class DuckDB:
    name = "duckdb"
    containers = ()

    def check(self) -> str | None:
        return None

    def build(self, job: Job) -> Built:
        errors: dict[str, str] = {}
        load = build = write = 0.0
        for blocks in job.blocks.values():
            t0 = time.perf_counter()
            con = duckdb.connect()
            con.execute("SET TimeZone = 'UTC'")
            con.execute("SET threads = 4")
            attach_log(con, job.root)
            load += time.perf_counter() - t0
            for table, sql in blocks.items():
                t1 = time.perf_counter()
                try:
                    t = con.sql(sql.rstrip().rstrip(";")).arrow().read_all()
                except duckdb.Error as e:
                    errors[table] = f"the block fails: {type(e).__name__}: {e}"
                    continue
                if job.cfg.kind == "synthetic":   # later blocks of a design may read it
                    con.register(table, t)        # (Spider2 tables share the log's names)
                t2 = time.perf_counter()
                d = job.table_dir(table)
                d.mkdir(parents=True, exist_ok=True)
                pq.write_table(t, d / "part-0.parquet")
                build += t2 - t1
                write += time.perf_counter() - t2
            con.close()
        return Built(Timings(build=build, load=load, write=write),
                     errors)
