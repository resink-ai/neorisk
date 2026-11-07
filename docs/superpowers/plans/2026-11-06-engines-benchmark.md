# Engines and Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PR 4 of the validation-datasets design: Spark, Flink (batch) and Flink-streaming runners next to DuckDB, ports of four datasets to every engine, `dataset run`, `dataset bench` and the comparison report.

**Architecture:** A runner per engine decodes the log into the same views `refdata.logviews` makes (same names, same columns), runs the dataset's port (`-- table:` blocks, as `build.sql`), and writes one Parquet table per results table into a run folder. One grader, shared by every engine, compares the run with `results/` using the existing comparator (Spider2 tables pass through SQLite with the source DDL, as `verify` does). Flink runs in a Docker session cluster; the streaming runner replays the log into one Redpanda topic and folds each table's debezium-json changelog.

**Tech Stack:** Python 3.12, DuckDB, PySpark 4.2.0 (local mode, Java 17), Flink 2.2.1 (SQL client, Docker image `neorisk-flink:2.2.1` with flink-sql-parquet 2.2.1, flink-sql-connector-kafka 5.0.0-2.2, hadoop-client 3.4.2, zstd-jni 1.5.7-3), Redpanda v25.2.1, confluent-kafka, psutil.

**Spec:** docs/superpowers/specs/2026-11-03-validation-datasets-design.md (sections Engines, Tooling, Delivery item 4)

## Global Constraints

- Engine ids: `duckdb`, `spark`, `flink`, `flink-stream`.
- Run folder: `$NEORISK_DATA_ROOT/_runs/<name>/<version>/<engine>/<run-id>/`; run-id is UTC `YYYYMMDDTHHMMSSZ`.
- Comparison: the existing `compare_tables` rule for every engine; expected tables are never loosened. A table an engine cannot build, or has no port block for, fails on that engine and the report says why.
- Ports live in `datasets/<name>/engines/spark/` and `datasets/<name>/engines/flink/`: `build.sql` for Spider2, `<design>.sql` for synthetic, same `-- table:` block format. The Flink port serves both `flink` and `flink-stream`.
- Metrics per run: wall time split load/build/write where the engine allows, peak memory, events per second, per table pass/fail, row count and a sample of differing rows.
- Four datasets on every engine: `pizzarunner`, `sakila`, `olist`, `payments`. Every dataset runs on `duckdb`.
- Resource rules (user, standing): every command has a timeout; one heavy process (or Docker run) at a time; measure each run; the harness never starts or stops Docker itself.
- Install engines with `uv sync --all-packages --extra engines` (never `--package`, which uninstalls the rest of the workspace).
- Tests run one file per pytest process. Spark tests skip without pyspark; Docker tests run only with `NEORISK_DOCKER=1`.

## Review Focus

1. A port block whose columns differ from the results table (missing, extra, renamed): the table fails with the column difference; the run still grades every other table.
2. Engine output types that differ from the results (naive timestamps, int32 vs int64, decimal): graded by value after a declared cast, never failing on representation alone; a cast that loses information (text into int) is a failure, not a coercion.
3. Flink cluster or Redpanda not running: `dataset run` exits 2 with the command that starts them, without writing a run folder.
4. A streaming changelog that retracts a row never inserted (or ends with negative multiplicity): the table fails with "the changelog does not fold", never silently drops the row.
5. A run interrupted halfway: no half run folder is mistaken for a result; `dataset list` reports only completed, graded runs.

---

### Task 1: Run folder, grading and the DuckDB engine

**Files:**
- Create: `apps/dataset/src/dataset/engines/__init__.py` (registry `ENGINES`, `run(cfg, engine, *, root=None) -> dict`)
- Create: `apps/dataset/src/dataset/engines/grade.py`, `apps/dataset/src/dataset/engines/metrics.py`, `apps/dataset/src/dataset/engines/duck.py`
- Modify: `apps/dataset/src/dataset/cli.py` (`run` subcommand; `list` gains `engines`)
- Test: `apps/dataset/tests/test_engines.py`

**Interfaces:**
- Produces: `Engine` protocol: `name: str`; `check() -> str | None` (None = ready, else the fix to print); `build(job: Job) -> Timings`. `Job(cfg, root: Path, out: Path, blocks: dict[str, dict[str, str]], columns: dict[str, list[tuple[str, pa.DataType]]])` where `blocks[file_stem][table] = sql` (Spider2: one stem `build`; synthetic: one per design) and `columns[table]` are the expected results columns. The engine writes `out/tables/<table>/*.parquet`. `Timings(load: float|None, build: float, write: float|None)`.
- Produces: `grade(cfg, root, out) -> list[TableResult]` and `port_blocks(cfg, engine) -> dict[str, dict[str, str]]` (duckdb reads `specs/`, others `engines/<spark|flink>/`).
- Produces: `run.json` = `{"name","version","engine","run_id","ok","events","timings","peak_rss_mb","events_per_s","tables":[TableResult.to_json()...]}`; written last, atomically, so a folder without it is not a run.

- [ ] **Step 1: Failing tests** in `test_engines.py` on the `tiny_synthetic` fixture and on a built pizzarunner (skip if not built): `test_duckdb_run_passes` (`run(cfg,"duckdb")["ok"]`, every table ok, `run.json` exists), `test_missing_block_fails_that_table_only` (drop one block via a monkeypatched `port_blocks`: that table fails with "no port block", others pass), `test_wrong_columns_fail_with_difference`, `test_naive_timestamp_graded_as_utc` (grade casts a naive `timestamp` column to UTC and passes), `test_lossy_cast_fails` (text where int expected fails), `test_interrupted_run_has_no_run_json`, `test_cli_run_and_list_engines` (`dataset run tiny --engine duckdb` exit 0; `list --json` shows `"engines": ["duckdb"]`).
- [ ] **Step 2:** Run `timeout 300 uv run pytest apps/dataset/tests/test_engines.py -q`. Expected: FAIL (no module `dataset.engines`).
- [ ] **Step 3: Implement.** Grading: Spider2 → DuckDB `read_parquet(out/tables/t/*.parquet)` as the block of `refdata.rebuild.fill_table` into an in-memory SQLite with the results DDL, then `sqlite_table` and `compare_tables(exact=...)`; synthetic → read with pyarrow, cast naive timestamps to UTC and each column to the expected type with `safe=True` (a failed cast is that table's failure), `compare_tables(extended=True)`. `metrics.Sampler` samples RSS of the process tree (psutil) and of `neorisk-engines-*` containers (`docker stats --no-stream`) every 0.5 s, peak in MB. The duckdb engine runs the reference blocks (`refdata.logviews.attach_log`, UTC, threads=1, same-design earlier tables registered) and writes each table with pyarrow.
- [ ] **Step 4:** Run the same command. Expected: PASS.
- [ ] **Step 5: Commit** `feat(dataset): engine runs, the shared grader and the duckdb engine`.

### Task 2: Spark engine

**Files:**
- Create: `apps/dataset/src/dataset/engines/spark.py`, `apps/dataset/src/dataset/engines/views.py`
- Test: `apps/dataset/tests/test_engine_spark.py`

**Interfaces:**
- Consumes: `Engine`, `Job` (Task 1).
- Produces: `views.spark_views(schema: dict) -> list[tuple[str, str]]` (view name, Spark SQL over a `log` view) and `views.flink_views(schema) -> list[tuple[str, str]]` (Flink SQL over a `log` table) — same names and columns as `refdata.logviews`.

- [ ] **Step 1: Failing tests** (module skips without pyspark; one SparkSession per module): `test_spark_views_match_duckdb` (for the tiny fixture's log, every view's rows in Spark equal DuckDB's `attach_log` view), `test_spark_run_tiny` (a hand-written tiny Spark port passes), `test_spark_block_error_fails_table` (a block with a syntax error fails only that table, detail carries Spark's message).
- [ ] **Step 2:** `timeout 600 uv run pytest apps/dataset/tests/test_engine_spark.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.** `local[4]`, `spark.sql.session.timeZone=UTC`, `spark.driver.memory=3g`, UI off, `spark.sql.parquet.outputTimestampType=TIMESTAMP_MICROS`. Payload by `from_json` with a struct typed from the schema (i32 INT, f64 DOUBLE, bool BOOLEAN, else STRING), then the `logviews` casts (BIGINT, TIMESTAMP). Each block becomes a temp view, so later blocks may read earlier tables of the same design. Timings: load = reading the log and creating views, build+write = each table's write.
- [ ] **Step 4:** same command. Expected: PASS.
- [ ] **Step 5: Commit** `feat(dataset): the spark engine`.

### Task 3: Flink batch engine and the compose file

**Files:**
- Create: `apps/dataset/docker/compose.yaml`, `apps/dataset/docker/flink.Dockerfile` (spiked; pinned versions above, memory caps: Redpanda 1.5 GB, JobManager 1.5 GB, TaskManager 4 GB)
- Create: `apps/dataset/src/dataset/engines/flink.py`
- Test: `apps/dataset/tests/test_engine_flink.py`

**Interfaces:**
- Consumes: `views.flink_views` (Task 2).
- Produces: `flink.job_sql(job, source_ddl: str, sink: Callable[[str, cols], str], mode: str) -> str` — one SQL-client script: settings, the `log` source, the views, a `TEMPORARY VIEW` per block, a sink table per results table, and one `EXECUTE STATEMENT SET` of the inserts. Reused by Task 4.

- [ ] **Step 1: Failing tests:** `test_job_sql_text` (no Docker: the script for the tiny fixture has `'execution.runtime-mode' = 'batch'`, `'table.dml-sync' = 'true'`, one sink per table with the Flink type of each expected column, and one statement set), `test_check_reports_cluster_down` (with an unreachable REST URL, `check()` returns the compose command), `test_flink_run_tiny` (`NEORISK_DOCKER=1` only: a tiny Flink port passes).
- [ ] **Step 2:** `timeout 600 uv run pytest apps/dataset/tests/test_engine_flink.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.** Submit with `docker exec neorisk-engines-jobmanager-1 ./bin/sql-client.sh -f <run>/job.sql` (the data root is mounted at the same path); read the job's final state and exception from the REST API (`localhost:18081`); a failed job fails every table with Flink's root cause. Sink types: int64 BIGINT, int32 INT, float64 DOUBLE, string STRING, bool BOOLEAN, date32 DATE, timestamp TIMESTAMP_LTZ(6). Timings: build+write = the job's duration from REST; load = None.
- [ ] **Step 4:** same command, with `NEORISK_DOCKER=1` and the cluster up. Expected: PASS.
- [ ] **Step 5: Commit** `feat(dataset): the flink batch engine and the local compose file`.

### Task 4: Flink streaming engine over Redpanda

**Files:**
- Create: `apps/dataset/src/dataset/engines/stream.py`
- Test: `apps/dataset/tests/test_engine_stream.py`

**Interfaces:**
- Produces: `replay_log(root, topic, brokers) -> int` (events sent) and `fold(messages: Iterable[dict], columns) -> pa.Table`.

- [ ] **Step 1: Failing tests:** `test_fold_inserts_and_retractions` (c/d pairs fold to the final multiset), `test_fold_rejects_unmatched_delete` (raises `FoldError("the changelog does not fold ...")`), `test_fold_types` (timestamp strings `2021-01-01 18:05:02Z` → timestamp[us, UTC], DATE strings → date32), `test_stream_run_tiny` (`NEORISK_DOCKER=1` only).
- [ ] **Step 2:** `timeout 600 uv run pytest apps/dataset/tests/test_engine_stream.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.** The log topic `<name>-<version>-log` has one partition and is recreated per run; messages in `seq` order, key `entity_key`, value the envelope as JSON with `payload` kept as its JSON text and `event_time` as `YYYY-MM-DD HH:MM:SS.ffffffZ`. Source: kafka connector, `json` format, `scan.startup.mode=earliest-offset`, `scan.bounded.mode=latest-offset`, so the streaming job finishes when the topic is drained. Each table sinks to topic `<run-id>-<table>` in `debezium-json`; after the job finishes the harness reads each topic to its high watermark and folds (`c` adds `after`, `d` removes `before`). Timings: load = the replay, build = the job, write = the fold.
- [ ] **Step 4:** same command. Expected: PASS.
- [ ] **Step 5: Commit** `feat(dataset): the flink streaming engine over redpanda`.

### Task 5: `dataset bench` and the report

**Files:**
- Create: `apps/dataset/src/dataset/bench.py`
- Modify: `apps/dataset/src/dataset/cli.py`
- Test: `apps/dataset/tests/test_bench.py`

**Interfaces:**
- Produces: `bench(names, engines) -> Path` writing `$NEORISK_DATA_ROOT/_runs/bench/<run-id>/report.json` and `report.html`.

- [ ] **Step 1: Failing tests:** `test_bench_duckdb_two_datasets` (report lists each dataset × engine with ok, timings, peak, events/s), `test_bench_skips_engine_not_ready` (an engine whose `check()` fails is reported "not run: <reason>", the rest still runs, exit 1), `test_bench_cross_engine_agreement` (when a table fails on one engine, the report says which other engines' outputs it equals), `test_report_html_is_self_contained` (no external URLs).
- [ ] **Step 2:** `timeout 300 uv run pytest apps/dataset/tests/test_bench.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.** Runs one at a time, in the order given. Engines without a port for a dataset are "not ported", not failures. Cross-engine comparison only for tables some engine fails (passing outputs agree through the expected table).
- [ ] **Step 4:** same command. Expected: PASS.
- [ ] **Step 5: Commit** `feat(dataset): dataset bench and its report`.

### Tasks 6–9: Ports (one dataset per task, in this order: pizzarunner, sakila, olist, payments)

**Files (each):** `datasets/<n>/engines/spark/<build|design>.sql`, `datasets/<n>/engines/flink/<build|design>.sql`, `apps/dataset/tests/test_engines_<n>.py`, CONTEXT.md "Engines" lines.

- [ ] **Step 1: Failing test** `test_engines_<n>.py`: spark run ok (skip without pyspark); flink and flink-stream runs ok (`NEORISK_DOCKER=1`). Each asserts `run(...)["ok"]` and prints failing tables.
- [ ] **Step 2:** Run it before writing ports. Expected: FAIL, "no port block" for every table.
- [ ] **Step 3: Port** every block; keep the DuckDB block's meaning. Flink ports avoid what the streaming planner rejects (ORDER BY, non-Top-N ROW_NUMBER) where an equivalent exists. A table that cannot be expressed on an engine keeps a `-- table:` block that returns the expected columns, and its failure is recorded in CONTEXT.md with the reason.
- [ ] **Step 4:** Run each engine once, measured, one at a time. Expected: PASS, or failures each explained in CONTEXT.md.
- [ ] **Step 5: Commit** `feat(datasets): <n> on spark, flink and flink-stream`.

### Task 10: Docs and the benchmark

- [ ] `datasets/README.md`: the catalogue's engines column from the bench report; "Add an engine port" extend recipe; how to bring the engines up and down.
- [ ] Spec: Delivery item 4 notes (one Flink port for both modes; the harness never manages Docker; the message format; pinned versions).
- [ ] Run `dataset bench pizzarunner sakila olist payments --engines duckdb,spark,flink,flink-stream` once, measured; commit nothing from `_runs/`.
- [ ] Commit `docs: engines, ports and the benchmark`.
