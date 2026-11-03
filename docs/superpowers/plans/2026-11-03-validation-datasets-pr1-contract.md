# Validation datasets, PR 1 (contract and layout): Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every Spider2 dataset is built as a single ordered JSON event log plus expected tables, under a central data root, and `dataset verify` proves that the reference build over the log reproduces them exactly.

**Architecture:**
- The 13 Spider2 projects move to `datasets/<p>/`, and `views.sql` becomes `build.sql`.
- A log writer in `neorisk_simkit.io.log` turns a simkit dataset (`RunData`) into the log. Entity rows become `<entity>_created` events, and business events keep their columns in a JSON payload.
- A DuckDB decoder in `refdata.logviews` turns the log back into views with the same names and columns as today's Parquet files, so `build.sql` runs over the log only.
- A new app, `apps/dataset`, with CLI `dataset`, adds the name resolver, `dataset.toml`, the results writer, the comparator, the manifest and lock, and the commands `build`, `verify`, `list` and `resolve`.

**Tech Stack:** Python 3.12, Polars, PyArrow, DuckDB, sqlite3, pytest, uv workspace.

**Spec:** `docs/superpowers/specs/2026-11-03-validation-datasets-design.md` (sections "The dataset contract", "In the repo", "Tooling", "Delivery" item 1). PRs 2 to 4 each get their own plan after this one merges.

## Global Constraints

- **Names:** a data file is named `<dataset>/<version>/<path>` and resolved against `NEORISK_DATA_ROOT`, default `<repo>/data/datasets`. Versions match `v[1-9][0-9]*`. All code resolves names through `dataset.names.resolve`.
- **Root layout:** under the root, `<dataset>/<version>/` holds `manifest.json`, `schema/events.json`, `log/part-NNNNN.parquet`, `results/<table>.parquet` and `expected/…`.
- **Log columns,** in this order:

  | Column | Type |
  |---|---|
  | `seq` | int64, from 1, contiguous |
  | `event_time` | timestamp µs UTC |
  | `event_type` | string |
  | `entity_type` | string |
  | `entity_key` | string |
  | `schema_version` | int32 |
  | `payload` | string, a JSON object |

- **Payload JSON:**
  - i64, ref and amount values are JSON strings; i32 values are JSON numbers.
  - ts values are `YYYY-MM-DDTHH:MM:SS.ffffffZ`.
  - f64 values are JSON numbers in shortest round-trip form. NaN and ±inf are refused with an error.
  - bool values are `true` and `false`; null is `null`.
  - Text is carried byte for byte, encoded with `ensure_ascii=False`.
- **Entities:**
  - An entity row becomes an event named `<entity>_created`, at its `created_at`.
  - Its payload holds the key column and every pack column, `created_at` excepted.
  - Its envelope has `entity_type` = the entity table name and `entity_key` = the key, as text.
- **Business events:**
  - The payload holds `event_id`, `sim_seq` (simkit's own `seq`), `partition_id`, `cause_id`, `action_id` and the event's pack columns.
  - The envelope's owner is `entity_type` = the owner column's ref target (or the column name if it is not a ref) and `entity_key` = its value as text.
  - Without an owner mapping, the owner is `entity_type = "partition"` and `entity_key = str(partition_id)`.
- **Log order:** rows sort by `(event_time, kind, rank)`.
  - `kind` is 0 for entity events and 1 for business events.
  - `rank` is the pack's entity order, then the key, for entities; for business events it is simkit's `seq`.
  - The log's `seq` is the 1-based position in that order.
- **Comparison:**
  - Tables compare as multisets of rows.
  - Integers and floats compare by value (62 == 62.0).
  - Text compares byte for byte. NULL, `''` and `'\N'` are distinct.
  - The only tolerance is 1e-9 relative, on float64 results columns.
- **Data:** no data is committed. Sources are opened read-only.
- **Writer settings** are simkit's `WRITER` (zstd 3, row group 131072, statistics), so builds are byte-deterministic.
- **Exit codes,** as in `refdata`: 0 success, 1 a difference, 2 a usage error, a missing input or a refusal.

## Review Focus

1. **Awkward text:** quotes, backslashes, newlines, NUL and other control characters, emoji, `\N`, `''`, and leading or trailing spaces must survive log → views byte for byte. Test: Task 3, `test_text_survives_json`.
2. **f64 at the edges:** 0.1, 5e-324, 1.7976931348623157e308, -0.0 and 123456789.12345679 must come back bit for bit through JSON in DuckDB. Test: Task 3, `test_floats_bit_exact`.
3. **int64 limits:** 2⁶³−1, −2⁶³ and 2⁵³+1 must round-trip, both in i64 payloads and in int64 results columns. Tests: Task 3, `test_int64_limits`; Task 6, `test_int64_column_exact`.
4. **An entity and an event at the same instant:** the creation comes first in the log, and an event type with zero rows still yields a typed empty view. Tests: Task 2, `test_entity_precedes_event_at_same_time`; Task 3, `test_empty_event_type_typed_view`.
5. **Bad names and roots:** a relative or trailing-slash `NEORISK_DATA_ROOT` resolves correctly; a name with `..`, an absolute path or a bad version is refused. Tests: Task 5, `test_root_relative_and_trailing_slash`, `test_bad_names_refused`.

---

### Task 1: Move the 13 Spider2 projects to `datasets/` and rename `views.sql` to `build.sql`

**Files:**
- Move, with `git mv`: `examples/{databank,cliquebait,olist,delivery_center,airlines,sakila,bitcoin,weblog,pizzarunner,chinook,northwind,oraclesh,adventureworks}/` to `datasets/<p>/`
- Rename: `datasets/<p>/specs/views.sql` to `datasets/<p>/specs/build.sql` (13 files)
- Modify: `apps/refdata/src/refdata/rebuild.py` (reads `specs/build.sql`), `apps/refdata/tests/conftest.py` (fixture writes `build.sql`; `roundtrip()` uses `REPO / "datasets"`)
- Modify docs: `examples/README.md` (drop the Spider2 section and point to `datasets/README.md`), `README.md`, `apps/refdata/README.md` (paths and the `views.sql` name), and `pyproject.toml` (the ruff per-file-ignores gain `"datasets/**" = ["B008", "RUF009"]`)
- Create: `datasets/README.md`, a stub catalogue that lists the 13 names; it is filled in Task 9
- Test: the existing `apps/refdata/tests/*`

**Interfaces:**
- Produces: projects live at `datasets/<p>/specs/{pack.py,source.toml,ingest.sql,build.sql,queries/}` and `datasets/<p>/datagen.toml`. `refdata rebuild` reads `build.sql`, and the parse error messages say `build.sql`.

- [ ] **Step 1:** Run the full suite once before moving anything, and save the pass count.

Run: `uv run pytest -q 2>&1 | tail -3`
Expected: `461 passed` (with the 13 roundtrips not skipped, because `data/spider2` is present).

- [ ] **Step 2:** Do the `git mv` of the 13 folders and the 13 renames. Update `rebuild.py`, `conftest.py`, the docs and `pyproject.toml`. Grep for leftover references:

Run: `rg -n "examples/(databank|cliquebait|olist|delivery_center|airlines|sakila|bitcoin|weblog|pizzarunner|chinook|northwind|oraclesh|adventureworks)|views\.sql" --glob '!docs/superpowers/**' --glob '!docs/research/**'`
Expected: no output. Historical plans, specs and research reports keep their old paths.

- [ ] **Step 3:** Run the suite again.

Run: `uv run pytest -q 2>&1 | tail -3 && uv run ruff check .`
Expected: the same pass count as Step 1, and `All checks passed!`

- [ ] **Step 4:** Commit: `refactor: move the Spider2 projects to datasets/, views.sql → build.sql`

---

### Task 2: The log writer, `neorisk_simkit.io.log`

**Files:**
- Create: `libs/simkit/src/neorisk_simkit/io/log.py`
- Test: `libs/simkit/tests/test_log.py`

**Interfaces:**
- Consumes: `neorisk_simkit.io.read.RunData` (frames plus `schema`, whose tables have `name`, `group` in {`event`, `entity`}, and `columns` of `{name, type, nullable, ref?}`), `neorisk_simkit.io.writer.WRITER` and `_write`, and `neorisk_simkit.spec.types.COMMON`.
- Produces:
  - `class LogError(ValueError)`
  - `ENVELOPE: tuple[str, ...]`, the seven log columns in order
  - `log_frame(run: RunData, *, owners: dict[str, str] | None = None) -> pl.DataFrame`, the whole log in `seq` order with the envelope columns only. `owners` maps an event type to its owner column.
  - `events_schema(run: RunData) -> dict` returns:

    ```text
    {"format": 1, "schema_version": int,
     "events": [{"name", "kind": "entity_created" | "event", "entity": str | None,
                 "key": str | None, "fields": [{"name", "type", "nullable", "ref"?}]}]}
    ```

    Entity events come first, in pack order, then business events in pack order. `fields` lists the payload fields in payload order, with `type` the simkit kind. For business events, `fields` starts with `event_id` (i64), `sim_seq` (i64), `partition_id` (i64), `cause_id` (i64, nullable) and `action_id` (i32).
  - `write_log(run: RunData, out_dir: Path, *, owners: dict[str, str] | None = None, part_rows: int = 1_000_000) -> list[Path]` writes `out_dir/log/part-00000.parquet`, … and `out_dir/schema/events.json`, and returns the part paths.

- [ ] **Step 1: Write the failing tests.** The tests build a small `RunData` by hand: one entity `customers` (key `customer_id`, columns `ext_id` text and `vip` bool) and one event `order_placed` (`customer_id` ref, `total` amount, `rate` f64, `note` opt text, `at` ts). Its `schema` dict has the shape of `schema/schema.json`.
  - `test_envelope_columns_and_types`: the columns equal `ENVELOPE`. `event_time` is `Datetime("us", "UTC")` and `schema_version` is `Int32`.
  - `test_entity_precedes_event_at_same_time`: a customer created at T and an order at T give `event_type` == `["customers_created", "order_placed"]` and `seq` == `[1, 2]`.
  - `test_payload_encoding`: one order's `json.loads(payload)` has `total` and `customer_id` as `str`, `rate == 0.1` as a float, `note is None`, `at` matching `r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z$"`, plus `event_id`, `sim_seq`, `partition_id`, `cause_id` and `action_id`. The entity payload has `vip is True` and the key, but no `created_at`.
  - `test_owner_mapping`: `owners={"order_placed": "customer_id"}` gives `entity_type == "customers"` and `entity_key == str(customer key)`. Without a mapping, the owner is `("partition", str(partition_id))`.
  - `test_nan_refused`: `rate = float("nan")` raises `LogError`, and the message names `order_placed.rate`.
  - `test_parts_split_consecutive`: with 5 rows and `part_rows=2`, there are 3 parts. Their concatenated `seq` is `[1..5]`, and each part's `seq` is a consecutive range.
  - `test_events_schema_lists_every_type`: a zero-row event type is still listed, and its `fields` match the order above.
  - `test_write_is_deterministic`: two writes to two directories give identical sha256 for every file.

- [ ] **Step 2: Run them.**

Run: `uv run pytest libs/simkit/tests/test_log.py -q`
Expected: they fail with `ModuleNotFoundError: neorisk_simkit.io.log`.

- [ ] **Step 3: Implement `log.py`.**
  - Build payloads by reusing `neorisk_simkit.replay.encode(rows, big)`, with `big` = the i64, ref and amount columns.
  - Call `json.dumps(..., ensure_ascii=False, allow_nan=False, separators=(",", ":"))`, and convert its `ValueError` into a `LogError` that names `<table>.<column>`.
  - Sort with Polars on the key `(event_time, kind, rank)` (stable).
  - Write the parts with `_write`.

- [ ] **Step 4: Run them.**

Run: `uv run pytest libs/simkit/tests/test_log.py -q && uv run pytest libs/simkit -q -m "not checked and not large" 2>&1 | tail -2`
Expected: all pass.

- [ ] **Step 5:** Commit: `feat(simkit): single ordered JSON event log writer`

---

### Task 3: The DuckDB log decoder, `refdata.logviews`

**Files:**
- Create: `apps/refdata/src/refdata/logviews.py`
- Test: `apps/refdata/tests/test_logviews.py`

**Interfaces:**
- Consumes: `write_log` and `events_schema` from Task 2, and the `shop` fixture in `conftest.py`.
- Produces: `attach_log(con: duckdb.DuckDBPyConnection, root: Path) -> list[str]`. It reads `root/log/*.parquet` and `root/schema/events.json`, creates the view `log`, and creates one view per schema entry. It returns the view names.
  - A **business event** view is named after the event. Its columns, in this order, are `event_id`, `event_type`, `event_time`, `seq` (from `sim_seq`), `partition_id`, `cause_id`, `action_id`, then the pack columns.
  - An **entity_created** view is named after the entity table. Its columns, in this order, are the key column (BIGINT, from `entity_key`), `created_at` (= `event_time`), then the pack columns.
  - **Types:** i32 → INTEGER; i64, ref and amount → BIGINT; f64 → DOUBLE; bool → BOOLEAN; text and cat → VARCHAR; ts → TIMESTAMPTZ. The connection's TimeZone is UTC.
  - **Decoding:** parse each payload once per row, with `json_transform` into a struct typed from the schema (strings for i64), then cast. A zero-row type is still a typed view.

- [ ] **Step 1: Write the failing tests.**
  - `test_views_equal_run_frames`: ingest the shop fixture, `write_log` it, `attach_log`, then for each event and entity table, `con.sql(f'SELECT * FROM "{t}"').pl()` equals the `RunData` frame. Columns, dtypes and values are all compared, with rows sorted by key or `event_id`.
  - `test_text_survives_json`: an entity `ext_id` column holding `['a"b', "back\\slash", "nl\nx", "nul\x00x", "\x01\x1f", "😀", "\\N", "", " pad "]` comes back equal.
  - `test_floats_bit_exact`: f64 values `[0.1, 5e-324, 1.7976931348623157e308, -0.0, 123456789.12345679]` come back with an equal `struct.pack("<d", v)` for each value.
  - `test_int64_limits`: i64 values `[2**63 - 1, -(2**63), 2**53 + 1]` come back equal.
  - `test_empty_event_type_typed_view`: a zero-row event type's view has 0 rows and the declared column types.

- [ ] **Step 2: Run them.**

Run: `uv run pytest apps/refdata/tests/test_logviews.py -q`
Expected: they fail with `ModuleNotFoundError: refdata.logviews`.

- [ ] **Step 3: Implement `attach_log`.**

- [ ] **Step 4: Run them.**

Run: `uv run pytest apps/refdata/tests/test_logviews.py -q`
Expected: all pass. If `nul\x00x` cannot survive DuckDB's JSON, don't silently drop it. Record a ruling, reject NUL in the writer with a `LogError`, check the 13 sources for NUL with `instr(col, char(0))`, and adjust the test.

- [ ] **Step 5:** Commit: `feat(refdata): decode the event log into the pack's views`

---

### Task 4: `refdata rebuild` and `roundtrip` over the log

**Files:**
- Modify: `apps/refdata/src/refdata/rebuild.py`, `apps/refdata/src/refdata/cli.py`, `apps/refdata/src/refdata/ingest.py` (export `owners`)
- Test: `apps/refdata/tests/test_rebuild.py`, plus the 13 `test_project_*.py` files (unchanged; they exercise this)

**Interfaces:**
- Consumes: `write_log` (Task 2) and `attach_log` (Task 3).
- Produces:
  - `refdata.ingest.owners(project: Path) -> dict[str, str]`: the event name and its `owner=` column, read from `ingest.sql`.
  - `refdata.rebuild.build_tables(log_root: Path, project: Path) -> tuple[duckdb.DuckDBPyConnection, dict[str, str]]`: a connection with the log attached, and each table's `build.sql` block SQL.
  - `rebuild(log_root: Path, project: Path, src_db: Path, out: Path, *, force=False) -> Path` reads only `log_root`, never `events/` or `entities/`.
  - `refdata roundtrip` runs ingest → `write_log(ds, ds_log, owners=owners(project))` → rebuild → compare. The log goes to `<out-dir>/<p>.log/`.

- [ ] **Step 1: Write the failing test.** `test_rebuild_reads_only_the_log`: ingest shop, write its log, delete the ingested `events/` and `entities/` folders, then rebuild from the log root. The rebuilt `orders` rows must equal the source's.

- [ ] **Step 2: Run it.**

Run: `uv run pytest apps/refdata/tests/test_rebuild.py -q`
Expected: it fails, because `rebuild` still globs `events/`.

- [ ] **Step 3:** Implement the changes above, and update the remaining `test_rebuild.py` tests to rebuild from a written log.

- [ ] **Step 4: Run the whole refdata suite.** It includes the 13 real round trips, now through JSON.

Run: `uv run pytest apps/refdata -q 2>&1 | tail -3`
Expected: all pass, no skips. Any failing round trip is a decoder or encoder bug: find it with superpowers:systematic-debugging. Never fix it by editing a `build.sql`.

- [ ] **Step 5:** Commit: `feat(refdata): rebuild and roundtrip read the event log only`

---

### Task 5: The `dataset` app: names, root and `dataset.toml`

**Files:**
- Create: `apps/dataset/pyproject.toml` (name `dataset`, script `dataset = "dataset.cli:main"`, dependencies `neorisk-simkit`, `refdata`, `polars`, `pyarrow`, `duckdb`, and workspace sources for both)
- Create: `apps/dataset/README.md`, `apps/dataset/src/dataset/__init__.py`, `names.py`, `config.py`
- Test: `apps/dataset/tests/test_names.py`, `apps/dataset/tests/test_config.py`

**Interfaces:**
- Produces:
  - `dataset.names.REPO: Path`
  - `data_root() -> Path`: `$NEORISK_DATA_ROOT` resolved to an absolute path against the current directory, else `REPO/"data"/"datasets"`.
  - `resolve(name: str) -> Path`. A name is `<dataset>/<version>[/<path>]`, where `<dataset>` matches `[a-z0-9][a-z0-9_-]*` and the version matches `v[1-9][0-9]*`. Absolute paths, `..`, empty parts and backslashes raise `BadName` (a `ValueError` subclass).
  - `dataset.config.DatasetConfig` is a frozen dataclass with `name: str`, `version: str`, `kind: str` (`spider2` or `synthetic`), `dir: Path`, `mixed: dict[str, list[str]]` and `recipe: dict`.
  - `load(name_or_dir: str | Path) -> DatasetConfig` reads `datasets/<name>/dataset.toml`, or a directory holding one.
  - `all_configs() -> list[DatasetConfig]` returns every `REPO/datasets/*/dataset.toml`, sorted by name.
  - `dataset.toml` keys are `name`, `version`, `kind`, `[recipe]` (free-form) and `[results.mixed]` (table = [columns]). For spider2, `[recipe]` is empty: the specs sit beside the file. `name` must equal the folder name, or loading raises `ValueError`.

- [ ] **Step 1: Write the failing tests.**
  - `test_default_root`: with no env var, `data_root() == REPO / "data" / "datasets"`.
  - `test_root_relative_and_trailing_slash`: with `NEORISK_DATA_ROOT="rel/dir/"` and the working directory set to `tmp_path`, `resolve("olist/v1/log/part-00000.parquet") == tmp_path / "rel/dir/olist/v1/log/part-00000.parquet"`.
  - `test_bad_names_refused`: each of `"../x/v1"`, `"/abs/v1"`, `"olist/1"`, `"olist/v0"`, `"Olist/v1"`, `"olist//v1"`, `"olist/v1/../../etc"` and `"olist\\v1"` raises `BadName`.
  - `test_load_and_mixed`: a `tmp_path` `dataset.toml` with `[results.mixed] t = ["a"]` loads as `cfg.mixed == {"t": ["a"]}`.
  - `test_name_must_match_folder`: a mismatched name raises `ValueError`.

- [ ] **Step 2: Run them.**

Run: `uv sync --all-packages -q && uv run pytest apps/dataset -q`
Expected: they fail on the missing modules.

- [ ] **Step 3:** Implement `names.py` and `config.py`.

- [ ] **Step 4: Run them.**

Run: `uv run pytest apps/dataset -q`
Expected: all pass.

- [ ] **Step 5:** Commit: `feat(dataset): data names, data root and dataset.toml`

---

### Task 6: Results tables and the comparator, `dataset.tables`

**Files:**
- Create: `apps/dataset/src/dataset/tables.py`
- Test: `apps/dataset/tests/test_tables.py`

**Interfaces:**
- Consumes: `refdata.compare.norm`.
- Produces:
  - `affinity(decl: str) -> str` follows SQLite's rules, in order:
    1. `INT` → INTEGER;
    2. `CHAR`, `CLOB` or `TEXT` → TEXT;
    3. `BLOB` or empty → BLOB;
    4. `REAL`, `FLOA` or `DOUB` → REAL;
    5. otherwise NUMERIC.
  - `column_types(con: sqlite3.Connection, table: str) -> dict[str, str]` maps each column to an Arrow type name:
    - INTEGER → `int64`;
    - REAL → `float64`;
    - NUMERIC → `int64` if every non-null value is an integer, else `float64`;
    - TEXT or BLOB → `string`.
  - `detect_mixed(con, table) -> set[str]`, using `typeof()`:
    - a numeric column holding any text value is mixed;
    - a TEXT or BLOB column holding any non-text value is mixed;
    - a blob value anywhere raises `ValueError`.
  - `sqlite_table(con, table, mixed: set[str]) -> pa.Table`: columns in source order. A mixed column is `string`, holding `CAST(x AS TEXT)` with NULL kept as null. Rows come in rowid order.
  - `answer_table(con, sql) -> pa.Table`: a saved query's answer, typed by its values:
    - all integers → int64;
    - integers and floats → float64;
    - any text → string, with each cell rendered through SQLite's `CAST(? AS TEXT)`;
    - all null → string.
  - `TableResult` is a dataclass with `name`, `ok`, `rows_expected`, `rows_got`, `missing: list[tuple]`, `extra: list[tuple]` and `detail: str`.
  - `compare_tables(name: str, expected: pa.Table, got: pa.Table, *, ordered: bool = False) -> TableResult`:
    - The column names must be equal as sets; otherwise `ok` is False and `detail` names the difference. `got` is reordered to `expected`'s columns.
    - Cells pass through `norm`.
    - float64 columns of `expected` compare with relative tolerance 1e-9. Other columns compare exactly, as multisets, or as lists when `ordered`.
    - `missing` and `extra` carry up to 5 sample rows each.

- [ ] **Step 1: Write the failing tests.**
  - `test_affinity_rules`: `INTEGER`, `BIGINT` and `INT2` give INTEGER. `VARCHAR(10)` and `TEXT` give TEXT. `""` gives BLOB. `REAL` and `DOUBLE PRECISION` give REAL. `DECIMAL(10,2)`, `NUMERIC` and `DATE` give NUMERIC.
  - `test_mixed_column_becomes_sqlite_text`: in an INTEGER column holding `274`, `''`, NULL and `'12a'`, `detect_mixed == {"c"}`, and `sqlite_table(...)` gives the column `["274", "", None, "12a"]`.
  - `test_decimal_62_and_62_7_is_float_not_mixed`: the column is not mixed, its type is float64, and the values are `[62.0, 62.7]`.
  - `test_int64_column_exact`: an INTEGER column holding `2**63 - 1` stays int64 and equal.
  - `test_compare_int_equals_float`: an expected int64 `[62]` against a got float64 `[62.0]` is ok.
  - `test_compare_null_empty_backslash_n_distinct`: `[None, "", "\\N"]` against `["", "", "\\N"]` fails with one row missing and one extra.
  - `test_float_tolerance_only_on_float_columns`: float64 `1.0` against `1.0 + 1e-12` is ok, but string `"1.0"` against `"1.0000000000001"` fails.
  - `test_ordered_answer`: the same rows in another order fail with `ordered=True` and pass without it.
  - `test_columns_must_match`: an extra column in `got` fails, and `detail` names it.

- [ ] **Step 2: Run them.**

Run: `uv run pytest apps/dataset/tests/test_tables.py -q`
Expected: they fail on the missing module.

- [ ] **Step 3:** Implement `tables.py`.

- [ ] **Step 4: Run them.**

Run: `uv run pytest apps/dataset/tests/test_tables.py -q`
Expected: all pass.

- [ ] **Step 5:** Commit: `feat(dataset): results tables from SQLite and the exact comparator`

---

### Task 7: Building and verifying a Spider2 dataset, `dataset.spider2`

**Files:**
- Create: `apps/dataset/src/dataset/spider2.py`, `apps/dataset/src/dataset/manifest.py`
- Modify: `apps/refdata/src/refdata/rebuild.py`, splitting out `fill_sqlite(duck, blocks: dict[str, str], ddl: dict[str, str], cols: dict[str, list[str]], dst: sqlite3.Connection) -> None` so both `rebuild` and `verify` use it
- Test: `apps/dataset/tests/test_spider2.py`, plus a `shop_dataset` fixture in `apps/dataset/tests/conftest.py`. The fixture reuses `refdata`'s `make_db`, `PACK`, `SOURCE`, `INGEST` and `VIEWS` (as `build.sql`), plus a `dataset.toml` and one saved query, `q1.sql`, with an ORDER BY.

**Interfaces:**
- Consumes: Tasks 2 to 6.
- Produces:
  - `class BuildError(ValueError)`.
  - `build_spider2(cfg: DatasetConfig, db: Path, *, record: bool = False) -> dict` returns the manifest. It writes `resolve(f"{cfg.name}/{cfg.version}")` in this order:
    1. ingest into a temporary directory;
    2. `write_log(..., owners=owners(cfg.dir))`;
    3. for each `source.toml` table: check that `detect_mixed` equals `set(cfg.mixed.get(t, []))`, else raise `BuildError` naming the table and both sets; then write `results/<t>.parquet` from `sqlite_table`;
    4. write `schema/results.json` = `{"tables": {t: {"ddl": str, "columns": [...], "key": [...], "mixed": [...]}}, "queries": {id: {"ordered": bool}}}`;
    5. write `expected/queries/<id>.parquet` from `answer_table` on the indexed in-memory source (`refdata.compare.open_indexed`);
    6. write `manifest.json`.

    It writes into `<root>/<name>/.<version>.tmp` and renames that to the final directory, replacing any earlier one.
  - The manifest holds:

    ```text
    {"name", "version", "kind", "recipe_sha256", "source_sha256",
     "counts": {"log": int, "results/<t>": int, "queries": int},
     "files": {"<relative path>": {"sha256": str, "rows": int}}}
    ```

    `recipe_sha256` is a sha256 over the sorted `(relative path, file sha256)` pairs of `cfg.dir/specs/**`, `dataset.toml` and `datagen.toml`. It never covers `CONTEXT.md` or the lock files.
  - **Lock:** `cfg.dir/f"{version}.lock.json"` holds the manifest without `counts`.
    - If it exists, `build_spider2` raises `BuildError` when the new manifest differs from it in `recipe_sha256`, `source_sha256` or any file's sha256 or rows. The message lists up to 10 differing paths.
    - `record=True` writes the lock when none exists, and refuses with `BuildError` when an existing lock differs.
  - `verify(cfg: DatasetConfig) -> dict` returns `{"ok": bool, "tables": [TableResult…], "queries": [TableResult…]}`. It reads only the version directory and `cfg.dir/specs`:
    1. attach the log to DuckDB and take the `build.sql` blocks;
    2. `fill_sqlite` into an in-memory SQLite database created from `schema/results.json`'s DDL;
    3. for each table, compare `compare_tables(t, results/<t>.parquet, sqlite_table(mem, t, mixed))`;
    4. for each query, compare `compare_tables(id, expected, answer_table(indexed mem, sql), ordered=...)`.

- [ ] **Step 1: Write the failing tests.**
  - `test_build_then_verify_ok`: `build_spider2` on the shop dataset, then `verify(...)["ok"] is True`. The data root holds `manifest.json`, `schema/events.json`, `schema/results.json`, `log/part-00000.parquet`, `results/customers.parquet`, `results/orders.parquet` and `expected/queries/q1.parquet`.
  - `test_verify_catches_changed_results`: overwrite `results/orders.parquet` with one cell changed. `verify` is then not ok, and the failing entry is `orders`.
  - `test_verify_reads_no_source`: after a build, delete the source `.sqlite`. `verify` still passes.
  - `test_mixed_declaration_must_match`: declare `[results.mixed] orders = ["note"]`. `BuildError` is raised, and its message names `orders`.
  - `test_build_is_deterministic`: two builds give equal `files` maps.
  - `test_lock_record_and_mismatch`: `record=True` writes `v1.lock.json`. Then change a row in the source. The next build raises `BuildError` naming `results/orders.parquet`.

- [ ] **Step 2: Run them.**

Run: `uv run pytest apps/dataset/tests/test_spider2.py -q`
Expected: they fail on the missing module.

- [ ] **Step 3:** Implement `manifest.py` (file sha256 and rows, `recipe_sha256`, the lock check and writing the lock) and `spider2.py`. Then refactor `refdata.rebuild` around `fill_sqlite`.

- [ ] **Step 4: Run them.**

Run: `uv run pytest apps/dataset apps/refdata -q 2>&1 | tail -3`
Expected: all pass.

- [ ] **Step 5:** Commit: `feat(dataset): build and verify a Spider2 dataset from its event log`

---

### Task 8: The `dataset` CLI

**Files:**
- Create: `apps/dataset/src/dataset/cli.py`
- Test: `apps/dataset/tests/test_cli.py`

**Interfaces:**
- Consumes: Tasks 5 to 7.
- Produces `main(argv) -> int`, with these commands:

  | Command | Prints | Exit |
  |---|---|---|
  | `dataset list [--json]` | One row per config: name, kind, version and `built`. `built` is `yes` when the manifest's files match the lock, `unrecorded` when files exist but there is no lock, `stale` when they differ, and `no` when there are no files | 0 |
  | `dataset build NAME [--db SRC] [--record]` | A JSON summary of the counts | 0; 1 on a `BuildError`; 2 on a missing source (pointing to `uv run refdata fetch`) or an unknown name |
  | `dataset verify NAME [--json FILE]` | One JSON summary line: `{"name","tables","queries","failed":[…]}`, with failures on stderr | 0 or 1 |
  | `dataset resolve NAME_PATH` | The absolute path | 0; 2 on a bad name |

  `--db` defaults to `data/spider2/<source.toml file>`. A synthetic config makes `build` exit 2 with `"synthetic datasets arrive in PR 3"`.

- [ ] **Step 1: Write the failing tests.**
  - `test_cli_build_verify_shop`: `main(["build", …])` then `main(["verify", …])` both return 0, and the last stdout line of `verify` has `"failed": []`.
  - `test_cli_resolve_bad_name_exit_2`.
  - `test_cli_list_states`: before a build, `built` is `no`; after a build, `unrecorded`; after `--record`, `yes`. All of this runs on the shop fixture, with the configs directory pointed at the fixture through a module-level `DATASETS` path that the test monkeypatches.

- [ ] **Step 2: Run them.**

Run: `uv run pytest apps/dataset/tests/test_cli.py -q`
Expected: they fail on the missing module.

- [ ] **Step 3:** Implement `cli.py`.

- [ ] **Step 4: Run them.**

Run: `uv run pytest apps/dataset/tests/test_cli.py -q && uv run dataset --help`
Expected: they pass, and the help lists the four commands.

- [ ] **Step 5:** Commit: `feat(dataset): list, build, verify and resolve commands`

---

### Task 9: The 13 Spider2 datasets: `dataset.toml`, `CONTEXT.md`, tests and the catalogue

**Files:**
- Create: `datasets/<p>/dataset.toml` and `datasets/<p>/CONTEXT.md` for each of the 13
- Modify: `datasets/README.md` (the catalogue), `apps/dataset/README.md`, `apps/refdata/README.md`
- Move: `apps/refdata/tests/test_project_<p>.py` to `apps/dataset/tests/test_dataset_<p>.py`, with a `built(name, tmp_path, monkeypatch)` helper in `apps/dataset/tests/conftest.py`. The helper sets `NEORISK_DATA_ROOT=tmp_path`, runs `build`, then `verify`, and skips when the source is not fetched.

**Interfaces:**
- Consumes: the `dataset` CLI.

- [ ] **Step 1: Write the 13 `dataset.toml` files.** Each has the name, `version = "v1"`, `kind = "spider2"`, an empty `[recipe]`, and no `[results.mixed]` yet. Then convert the 13 project tests. Each test asserts:
  - verify passes, with `failed == []`;
  - the same table and query counts as before;
  - the manifest's `counts["log"]` equals the old event total plus the entity row total.

- [ ] **Step 2: Run them.**

Run: `uv run pytest apps/dataset/tests -q -k test_dataset_ 2>&1 | tail -15`
Expected: every dataset with a mixed column fails with a `BuildError` naming the table and the detected columns.

- [ ] **Step 3: Declare the mixed columns.** For each `BuildError`, add the detected columns to that dataset's `[results.mixed]`. Before declaring a column, read why it is mixed in the research report, so that a detection bug is not hidden. Then make `build.sql` produce SQLite's text for it, only if verify says it doesn't already.

- [ ] **Step 4: Run them.**

Run: `uv run pytest apps/dataset/tests -q -k test_dataset_ 2>&1 | tail -3`
Expected: 13 passed.

- [ ] **Step 5: Write the 13 `CONTEXT.md` files.** Each uses exactly these sections:
  - What this is
  - Raw data
  - How the log was made
  - Event catalogue
  - Times set by rule
  - Snapshot columns
  - Expected output
  - Regenerate
  - Extend

  Fill them from the dataset's research report (link to it, don't copy it), `source.toml` and the rule-times table in `apps/refdata/README.md`. "Snapshot columns" says "classified in PR 2". "Regenerate" gives the exact commands: `uv run refdata fetch`, `uv run dataset build <p>` and `uv run dataset verify <p>`. "Extend" covers more rows, a new event type, a new attribute, a new results table and a new engine port.

  Then fill in `datasets/README.md`: name, kind, source, licence, tables, log rows, results rows, the `mixed` columns, and the engines that pass (`duckdb` only for now).

- [ ] **Step 6: Run the full suite and the linter.**

Run: `uv run pytest -q 2>&1 | tail -3 && uv run ruff check .`
Expected: all pass, and `All checks passed!`

- [ ] **Step 7:** Commit: `feat(datasets): the 13 Spider2 datasets in the new contract, with context files`
