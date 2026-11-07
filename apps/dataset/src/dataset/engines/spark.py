"""The Spark engine: PySpark in local mode over the log Parquet, running `engines/spark/`.

The session runs `local[4]` in UTC with a 3 GB driver and writes timestamps as UTC micros.
Each view of `views.spark_views` is a temp view; a synthetic design's tables are read back
from their Parquet as temp views, so later blocks of the design may read them. Spark is
lazy, so reading the log is part of each table's build: only `build` is timed.
"""

from __future__ import annotations

import json
import shutil
import time

from dataset.engines import Built, Job, Timings
from dataset.engines.views import spark_views

CONF = {"spark.sql.session.timeZone": "UTC", "spark.driver.memory": "3g",
        "spark.ui.enabled": "false", "spark.sql.shuffle.partitions": "4",
        "spark.sql.parquet.outputTimestampType": "TIMESTAMP_MICROS"}


def session():
    from pyspark.sql import SparkSession
    b = SparkSession.builder.master("local[4]").appName("dataset")
    for k, v in CONF.items():
        b = b.config(k, v)
    s = b.getOrCreate()
    s.sparkContext.setLogLevel("ERROR")
    return s


def _why(e: Exception) -> str:
    text = str(e).strip().splitlines()
    return f"{type(e).__name__}: {text[0][:500] if text else ''}"


class Spark:
    name = "spark"
    containers = ()

    def check(self) -> str | None:
        try:
            import pyspark  # noqa: F401
        except ImportError:
            return "pyspark is not installed; run: uv sync --all-packages --extra engines"
        if not shutil.which("java"):
            return "no java on PATH; Spark needs Java 17"
        return None

    def build(self, job: Job) -> Built:
        s = session()
        schema = json.loads((job.root / "schema" / "events.json").read_text())
        s.read.parquet(str(job.root / "log")).createOrReplaceTempView("log")
        for name, sql in spark_views(schema):
            s.sql(f"CREATE OR REPLACE TEMP VIEW `{name}` AS {sql}")
        errors: dict[str, str] = {}
        t0 = time.perf_counter()
        for blocks in job.blocks.values():
            for table, sql in blocks.items():
                d = job.table_dir(table)
                try:
                    s.sql(sql.rstrip().rstrip(";")).coalesce(1).write.mode(
                        "overwrite").parquet(str(d))
                except Exception as e:  # noqa: BLE001 — AnalysisException, ParseException, Py4J
                    errors[table] = f"the block fails: {_why(e)}"
                    continue
                if job.cfg.kind == "synthetic":   # Spider2 tables share the log's names
                    s.read.parquet(str(d)).createOrReplaceTempView(table)
        return Built(Timings(build=time.perf_counter() - t0), errors)
