# Spider2 reference datasets, stage 1 (exact round trip): Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** For five Spider2 SQLite datasets, derive a simkit event log from the real tables and rebuild those tables from it exactly, proven by `refdata roundtrip <project>` exiting 0.

**Architecture:**
- A new app `apps/refdata` does four jobs:
  - fetches the Spider2 SQLite zip;
  - runs each project's `specs/ingest.sql` (SQLite) to write a dataset in simkit's layout that conforms to the project's schema-only `pack.py`;
  - runs `specs/views.sql` (DuckDB over the Parquet files) to rebuild a SQLite file with the source DDL;
  - compares source with rebuilt as row multisets, plus saved benchmark queries.
- Each dataset is an `examples/<project>/` folder that stage 2 later grows into a behavioural pack.

**Tech Stack:** Python 3.12, stdlib `sqlite3`, Polars, DuckDB (≥1.1; move it from the root dev group into `refdata`'s dependencies), `neorisk_simkit` (project loading, `schema_json`, `io.read`, `io.writer._write/_sha`), pytest.

**Spec:** `docs/superpowers/specs/2026-10-30-spider2-reference-datasets-design.md`. Research: `docs/research/spider2/{olist,delivery_center,airlines,bank_clicklog}.md`, with scripts in `docs/research/spider2/scripts/`.

## Global Constraints

- **No change to `libs/simkit`.** If a task seems to need one, stop and report why.
- **Nothing derived from the data goes into git.** No `.sqlite` files, ingested datasets or rebuilt files are committed. Paths:
  - sources: `data/spider2/`
  - datasets: `data/ref/<project>/`
  - rebuilt files: `data/ref/<project>.rebuilt.sqlite`
- **Sources are opened read-only:** `sqlite3.connect(f"file:{p}?mode=ro", uri=True)`.
- Zip URL: `https://drive.usercontent.google.com/download?id=1coEVsCZq-Xvj9p2TnhBFoFTsY-UoYGmG&export=download&authuser=0&confirm=t`. Pin its sha256: compute it once in Task 1 from the copy already downloaded.
- **Time:** source wall clock is stored as if it were UTC (µs). Ingest SQL emits times as ISO text `YYYY-MM-DD HH:MM:SS[.ffffff]`. `views.sql` formats them back into the source's exact text.
- Money that is exact cents becomes `amount()` minor units; other floats stay `f64`; text is byte-exact.
- **Exactness:** compare tables as multisets of rows. INTEGER and REAL values compare by numeric value; NULL, `''` and `'\N'` are three distinct values. Query results compare with float relative tolerance 1e-9, ordered when the SQL has a top-level `ORDER BY`, otherwise as multisets.
- **Exit codes, as in `datagen`:** 0 success; 1 a round trip or comparison differs; 2 a usage error, missing source or refusal.
- Code style follows `apps/datagen`: plain functions, short module docstrings, line length 100, `ruff check` clean.

## Review Focus

1. **Source not fetched yet.** Every command that needs it exits 2 with `data/spider2/<file> not found; run: uv run refdata fetch`. Owner: Task 3.
2. **A ref value with no matching entity.** Ingest fails (exit 1) and names the block, the column and up to 3 unmatched values. It never writes a null. Owner: Task 3.
3. **Re-running ingest or rebuild over existing output.** Both refuse without `--force` (exit 2), as `datagen run` does. Owner: Tasks 3 and 4.
4. **Float aggregates differing in the last bits** because rebuilt rows are in another order. Query comparison uses rel 1e-9, and table comparison never applies a tolerance. Owner: Task 5.
5. **NULL vs `''` vs `'\N'`.** They are distinct in table comparison: Airlines uses `'\N'` text, and a writer that turns it into NULL must fail the check. Owner: Task 5.

---

### Task 1: `apps/refdata` skeleton and `refdata fetch`

**Files:**
- Create: `apps/refdata/pyproject.toml` (name `refdata`, deps `neorisk-simkit`, `polars>=1.0`, `duckdb>=1.1`; script `refdata = "refdata.cli:main"`; workspace source for simkit, the same as `apps/datagen/pyproject.toml`)
- Create: `apps/refdata/src/refdata/__init__.py`, `cli.py`, `fetch.py`
- Create: `apps/refdata/README.md`
- Test: `apps/refdata/tests/test_fetch.py`

**Interfaces:**
- Produces:
  - `fetch.ZIP_URL: str`
  - `fetch.ZIP_SHA256: str`
  - `fetch.DATA = Path("data/spider2")`
  - `fetch.verify(path: Path, sha256: str) -> None` (raises `ValueError` naming expected and actual)
  - `fetch.unpack(zip_path: Path, dest: Path) -> list[Path]` (extracts `*.sqlite` only, skips `__MACOSX/`, returns the sorted paths)
  - `fetch.fetch(dest: Path = DATA, *, force: bool = False) -> list[Path]` (skips the download when every expected file exists, unless `force`)
  - `cli.main(argv: list[str] | None = None) -> int` with subcommands added by later tasks

- [ ] **Step 1: Write the failing tests**
  - `test_verify_rejects_wrong_hash`: write a tmp file and call `verify(p, "0"*64)`. Assert that `ValueError` is raised and its message contains both hashes.
  - `test_unpack_keeps_only_sqlite`: build a tmp zip holding `a.sqlite`, `__MACOSX/._a.sqlite` and `local-map.jsonl`. Assert that `unpack` returns `[dest/"a.sqlite"]`.
  - `test_cli_fetch_skips_when_present`: monkeypatch `fetch.EXPECTED` to `["a.sqlite"]` with that file already present, and monkeypatch `urllib.request.urlopen` to raise. Assert that `main(["fetch","--dest",tmp])` returns 0.
- [ ] **Step 2: Run them and check they fail.** Run `uv run pytest apps/refdata -q`. Expected: import errors.
- [ ] **Step 3: Implement.**
  - `fetch.EXPECTED` lists the 30 database file names from the zip listing in the spec's research.
  - Download with `urllib.request` to `dest/"localdb.zip.part"`, then rename.
  - Compute `ZIP_SHA256` once, using `shasum -a 256` on the zip already in the session scratchpad, or on a fresh download.
- [ ] **Step 4: Run.** `uv sync --all-packages && uv run pytest apps/refdata -q` passes. Then run `uv run refdata fetch` for real: it exits 0 and `ls data/spider2/*.sqlite | wc -l` prints 30.
- [ ] **Step 5: Commit.** Message: `feat(refdata): fetch the Spider2-lite SQLite databases`.

### Task 2: Block files and `source.toml`

**Files:**
- Create: `apps/refdata/src/refdata/blocks.py`, `apps/refdata/src/refdata/source.py`
- Test: `apps/refdata/tests/test_blocks.py`

**Interfaces:**
- Produces:
  - `Block(kind: str, name: str, opts: dict[str, str], sql: str)`, a frozen dataclass. `kind` is one of `event`, `entity` or `table`.
  - `parse_blocks(text: str, allowed: set[str]) -> list[Block]`. A header line is `-- <kind>: <name> [key=value ...]`. The block's SQL runs until the next header. A kind outside `allowed`, a duplicate name or empty SQL raises `ValueError` with the line number.
  - `Source(file: str, tables: dict[str, list[str]], note: str)`.
  - `load_source(project: Path) -> Source`. It reads `specs/source.toml`:

    ```toml
    file = "E_commerce.sqlite"
    note = "São Paulo wall clock, stored as UTC"
    [tables]
    orders = ["order_id"]
    geolocation = []          # no key: report diffs unsorted
    ```

- [ ] **Step 1: Write the failing tests.**
  - `test_parse_two_blocks_with_opts`: parse `"-- event: order_placed owner=order_id ord=o\nSELECT 1;\n-- entity: orders\nSELECT 2;"`. Assert the result is `[Block("event","order_placed",{"owner":"order_id","ord":"o"},"SELECT 1;"), Block("entity","orders",{},"SELECT 2;")]`.
  - `test_duplicate_name_rejected`: assert that a duplicate name raises.
  - `test_kind_not_allowed`: parsing a `table` block with `allowed={"event","entity"}` raises `ValueError` matching `line 1`.
  - `test_load_source`: round-trip the TOML above.
- [ ] **Step 2: Run them and check they fail.**
- [ ] **Step 3: Implement** with a line scanner, `tomllib` and a strip on the SQL text.
- [ ] **Step 4: Run them and check they pass.**
- [ ] **Step 5: Commit.** Message: `feat(refdata): block files and source.toml`.

### Task 3: `refdata ingest`: source tables → a simkit dataset

**Files:**
- Create: `apps/refdata/src/refdata/ingest.py`
- Modify: `apps/refdata/src/refdata/cli.py` (add the `ingest PROJECT [--db PATH] [--out DIR] [--force]` subcommand; the defaults are `data/spider2/<source.file>` and `data/ref/<project name>`)
- Test: `apps/refdata/tests/conftest.py` (a fixture project), `apps/refdata/tests/test_ingest.py`

**Interfaces:**
- Consumes: `parse_blocks`, `load_source` (Task 2); `neorisk_simkit.project.load_project`, `schema_json.build`, `io.writer._write/_sha/WRITER`.
- Produces:
  - `ingest(project: Path, db: Path, out: Path, *, force: bool = False) -> Path`
  - `IngestError(Exception)`
  - The dataset layout and the common-column rules below, which Tasks 4 and 6–10 rely on.

**Rules** (copy these into the module docstring):
1. **Running blocks.**
   - Blocks run in file order on the read-only source connection.
   - That connection has the function `iso_time(text, fmt)`, which returns `datetime.strptime(text, fmt).isoformat(" ")`, or NULL for NULL.
   - Every block must end in an `ORDER BY` that makes its output order deterministic. Ingest checks this by matching a regex on the last clause.
2. **Entity blocks.**
   - Each yields the entity's pack columns except the key, plus `ext_id` (text, unique; ingest checks this).
   - The key is the 1-based row number in `ext_id` order.
3. **Event blocks.**
   - Each yields `event_time` (ISO text), the event's pack columns, and, when `ord=` is set, that column.
   - `owner=<col>` is required.
   - For a pack column typed `ref(T)`, the block yields the source id, which is mapped through `T.ext_id` to `T`'s key. If any value is unmatched, raise `IngestError` naming the block, the column and up to 3 values (Review Focus 2).
4. **Casts:**
   - `ts` columns: `str.to_datetime(time_unit="us", time_zone="UTC")`, accepting an optional fraction.
   - `amount` and `i64`/`i32` columns: integers (the SQL emits minor units).
   - `f64` columns: Float64.
   - `cat` columns: checked against their values.
   - A null in a non-`opt` column raises `IngestError`.
5. **Common columns.**
   - Concatenate the events and sort them stably by `(event_time, ord or 0, block index, owner value, row index)`.
   - `seq` is the 1-based row number in that order, and `event_id = seq`.
   - `partition_id` is the dense rank of the owner value across all events.
   - `cause_id` is null, `action_id` is 0, and `event_type` is the block name.
   - Each event table's column order is `COMMON` followed by the pack's columns.
6. **Writing.**
   - Write `events/`, `entities/`, an empty `labels/labels.parquet` and `cases/cases.parquet` with the schema's columns, `schema/schema.json`, and a `manifest.json`.
   - The manifest holds `pack`, `schema_version`, `provenance: {"source": "ingest", "file": <name>, "sha256": <source sha>}`, `counts` and `files` (sha256).
   - Refuse if `out` exists and is not empty, unless `force` (Review Focus 3).
   - A missing `db` exits 2 with the Review Focus 1 message.
7. **Coverage.** Every pack event and entity must have exactly one block, and vice versa; otherwise raise `IngestError` listing the differences.

- [ ] **Step 1: Write the fixture and the failing tests.**
  - `conftest.py` builds a tmp project `shop`:
    - `pack.py`: entity `customers(ext_id text, city text)`; events `order_placed(customer_id ref customers, total amount, note opt text)` and `order_paid(customer_id ref customers)`.
    - `source.toml`, `ingest.sql` and a tmp SQLite `shop.sqlite`: `customers(cid TEXT, city TEXT)` with 2 rows; `orders(oid TEXT, cid TEXT, placed TEXT, paid TEXT NULL, total REAL, note TEXT)` with 3 rows, one of which has a NULL `paid`.
    - `placed` uses `'M/D/YYYY h:mm:ss AM'` format, so `iso_time` is exercised.
  - `test_ingest_layout`: `io.read(out)` has events `order_placed` (3 rows) and `order_paid` (2 rows), and entities `customers` (2 rows). `manifest["provenance"]["source"] == "ingest"`.
  - `test_common_columns`: `seq` is 1..5 with no gaps and is non-decreasing in `event_time`; `event_id == seq`; `partition_id` has 2 distinct values.
  - `test_structural_checks_pass`: `neorisk_simkit.checks.run_checks(io.read(out))` returns no failed results.
  - `test_unmatched_ref_named`: add an order whose `cid` is `"zz"`. `IngestError` mentions `order_placed`, `customer_id` and `zz`.
  - `test_refuses_existing_out`: a second `ingest` without `force` raises `FileExistsError`, and `cli.main([...])` returns 2.
  - `test_missing_db_exit_2`: `cli.main(["ingest", proj, "--db", tmp/"nope.sqlite"])` returns 2, and stderr contains `run: uv run refdata fetch`.
  - `test_block_without_order_by`: `IngestError` matching `ORDER BY`.
- [ ] **Step 2: Run them and check they fail.**
- [ ] **Step 3: Implement `ingest`** following the rules above.
- [ ] **Step 4: Run them and check they pass.** `uv run pytest apps/refdata -q`.
- [ ] **Step 5: Commit.** Message: `feat(refdata): ingest source tables as a simkit dataset`.

### Task 4: `refdata rebuild`: dataset → SQLite with the source DDL

**Files:**
- Create: `apps/refdata/src/refdata/rebuild.py`
- Modify: `cli.py` (add `rebuild DATASET --project P [--db SRC] [--out FILE] [--force]`; the default out is `data/ref/<project>.rebuilt.sqlite`)
- Test: `apps/refdata/tests/test_rebuild.py` (extends the fixture with `views.sql` for `customers` and `orders`)

**Interfaces:**
- Consumes: the Task 3 dataset layout; `parse_blocks(..., allowed={"table"})`; `load_source`.
- Produces: `rebuild(dataset: Path, project: Path, src_db: Path, out: Path, *, force: bool = False) -> Path`.

**Approach:**
- In an in-memory DuckDB, create one view per Parquet file, named after the file stem: `CREATE VIEW <stem> AS SELECT * FROM read_parquet('<path>')`.
- Run each `table` block, and require a block for every table in `source.toml` and nothing else.
- Create the output SQLite with each table's `sqlite_master.sql` from the source, in source order.
- Insert rows in the order of the source DDL's columns. The block must produce exactly those column names; otherwise raise `ValueError` listing the missing and extra names.
- Use `executemany` in one transaction per table.

- [ ] **Step 1: Write the failing tests.**
  - `test_rebuild_tables_and_ddl`: the rebuilt file's `sqlite_master.sql` for `orders` equals the source's. Row counts are 2 and 3.
  - `test_view_formats_time_back`: the rebuilt `orders.placed` values equal the source's `M/D/YYYY h:mm:ss AM` strings. The view uses DuckDB `strftime(event_time AT TIME ZONE 'UTC', '%-m/%-d/%Y %-I:%M:%S %p')`.
  - `test_missing_column_named`: a view without `note` raises `ValueError` containing `note`.
  - `test_refuses_existing_out`: same as Task 3.
- [ ] **Step 2: Run them and check they fail.**
- [ ] **Step 3: Implement `rebuild`.**
- [ ] **Step 4: Run them and check they pass.**
- [ ] **Step 5: Commit.** Message: `feat(refdata): rebuild source tables from a dataset with views.sql`.

### Task 5: `refdata compare` and `refdata roundtrip`

**Files:**
- Create: `apps/refdata/src/refdata/compare.py`
- Modify: `cli.py` (add `compare SRC REBUILT --project P [--json FILE]` and `roundtrip PROJECT [--force]`)
- Test: `apps/refdata/tests/test_compare.py`, `apps/refdata/tests/test_roundtrip_fixture.py`

**Interfaces:**
- Consumes: `load_source`; `ingest` (Task 3); `rebuild` (Task 4).
- Produces:
  - `TableDiff(name: str, rows_source: int, rows_rebuilt: int, missing: list[tuple], extra: list[tuple])`. Each list is at most 5 sample rows, sorted by the table's key columns when it has a key.
  - `QueryDiff(name: str, ok: bool, detail: str)`.
  - `Report(tables: list[TableDiff], queries: list[QueryDiff])`, with `.ok: bool` and `.to_json() -> dict`.
  - `compare(src_db: Path, rebuilt_db: Path, project: Path) -> Report`. Saved queries are every `specs/queries/*.sql`, run on both files.
  - `norm(v) -> object`: `int`/`float` become `float(v)`; `str`, `bytes` and `None` pass unchanged.
  - The `roundtrip` CLI runs ingest → rebuild → compare to the default paths. It prints a one-line JSON summary `{"project", "tables": n, "rows": n, "queries": n, "failed": [...]}` and returns 0, or 1 on any difference.

- [ ] **Step 1: Write the failing tests.**
  - `test_identical_files_ok`: copy a SQLite file and compare it with the original. `ok` is true.
  - `test_int_vs_real_equal`: a source holding `62` (INTEGER) and a rebuilt file holding `62.0` (REAL) compare equal.
  - `test_null_empty_backslash_n_distinct`: NULL, `''` and `'\N'` in one column; swapping any two makes the table differ (Review Focus 5).
  - `test_multiset_counts_duplicates`: the source has a row twice and the rebuilt file once. `missing == [row]`.
  - `test_row_order_ignored`: the same rows in reverse order compare as `ok`.
  - `test_query_float_tolerance`: query `SELECT sum(x) FROM t` where the rebuilt file's row order changes the float sum in its last bit. The query compares `ok`, while an injected 1e-6 relative change fails it (Review Focus 4).
  - `test_ordered_query_compares_as_list`: with `ORDER BY`, swapped rows fail.
  - `test_roundtrip_fixture_exit_0`: on the Task 3/4 fixture, `main(["roundtrip", proj, ...])` returns 0. Break one view, and it returns 1 and the JSON lists that table.
- [ ] **Step 2: Run them and check they fail.**
- [ ] **Step 3: Implement.**
  - Build a `Counter` of normalised row tuples per table.
  - Detect a top-level `ORDER BY` with a regex on the query text after its last closing parenthesis.
  - Compare floats with `math.isclose(rel_tol=1e-9)` for query cells only.
- [ ] **Step 4: Run them and check they pass.**
- [ ] **Step 5: Commit.** Message: `feat(refdata): compare source and rebuilt tables; roundtrip command`.

---

Tasks 6–10 share a shape. Each creates `examples/<project>/{datagen.toml, specs/pack.py, specs/source.toml, specs/ingest.sql, specs/views.sql, specs/queries/*.sql}` plus one test `apps/refdata/tests/test_project_<project>.py`. That test:
- is skipped when `data/spider2/<file>` is absent (`pytest.mark.skipif`);
- runs `roundtrip` into a tmp dir and asserts exit 0;
- asserts the event counts listed in the task (from the research reports).

Each task follows the same steps:
1. Write the test with the counts, and check it fails because the project doesn't exist yet.
2. Write `pack.py` from the report's event catalog (§2). The pack is schema-only: no owners, processes or sources. Set `SCHEMA_VERSION = 1`, and give every event and column a `doc=`.
3. Write `ingest.sql` from the report's derivation rules, and `views.sql` from its rebuild rules (§3).
4. Copy the queries:
   - For each listed id, fetch the gold SQL: `gh api repos/xlang-ai/Spider2/contents/spider2-lite/evaluation_suite/gold/sql/<id>.sql --jq .content | base64 -d`.
   - When it is absent, take the reproduction from the named research script.
   - Each file starts with `-- <id>: <question, one line>`.
5. Iterate `uv run refdata roundtrip examples/<project> --force` until it exits 0, then run the test.
6. Run `uv run datagen validate examples/<project>` and check it reports `"problems": 0`.
7. Commit with message `feat(examples): <project> reference dataset, exact round trip`.

When a table cannot be made exact, do not loosen `compare`. Stop and report the table, the differing rows and the reason. A stated exception needs the user's approval.

### Task 6: `databank` (bank_sales_trading: customer_regions, customer_nodes, customer_transactions)

- **Report:** `docs/research/spider2/bank_clicklog.md`, part A.
- **Entities:** `customers` (500), `regions` (5), `nodes`, which is keyed by its node number and so must carry `ext_id`.
- **Events:** `account_opened` + `node_reassigned` (3,500 together) and `transaction_posted` (5,868 total, by type: deposit 2,671, purchase 1,617, withdrawal 1,580). `ord` is the source rowid, because times within a day are unknown (396 customer-days have several transactions).
- **Views:** `end_date` = the next period's start − 1 day, else `'9999-12-31'`. Keep the zero-amount deposit.
- **Queries:** local064, local298, local300, plus the other 3 Data Bank questions in `spider2-lite.jsonl` (`db == "bank_sales_trading"`; take those that touch only these three tables). Reproductions are in `scripts/a_databank.py` and `scripts/a_databank2.py`.

### Task 7: `cliquebait` (bank_sales_trading: shopping_cart_*)

- **Report:** `bank_clicklog.md`, part B.
- **Entities:** `users` (from shopping_cart_users), `pages` (13), `campaigns` (3), `event_kinds` (5).
- **Events:** one event table `page_event` (32,734 rows) with `visit_id`, `cookie_id`, `page_id` (ref), `event_kind` (ref) and `sequence_number`, owned by `visit_id`.
- **Views:**
  - `event_time` is written back as microsecond text with trailing zeros stripped, as in the source.
  - `shopping_cart_users` is rebuilt from the `users` entity: its `start_date` is an entity column, because it is not derivable from the events.
- **Query:** local075.

### Task 8: `olist` (E_commerce, all 11 tables)

- **Report:** `docs/research/spider2/olist.md`. Use E1–E12 and S1–S4 exactly as written there.
- **Expected counts:**

  | Event | Count |
  |---|---:|
  | `order_placed` | 99,441 |
  | `order_line_added` | 112,650 |
  | `payment_recorded` | 103,886 |
  | `order_approved` | 99,281 |
  | `seller_ship_deadline_set` | 100,010 |
  | `order_handed_to_carrier` | 97,658 |
  | `order_delivered` | 96,476 |
  | `order_status_final` | 1,857 |
  | `review_requested` | 99,224 |
  | `review_answered` | 99,224 |
  | `lead_qualified` | 8,000 |
  | `lead_won` | 842 |

- **Entities:** sellers 3,095, products 32,951, geolocation 1,000,163 (keyed by row: `ext_id` = the source rowid as text), translation 71.
- **Values:** money is `amount("BRL")`. Review text must keep CR+LF.
- **Queries:** local002, local003, local004, local028–local032, local034, local035, local037, local286. Map each one's table names (`olist_*`, and `electronic_sales`' `index` column) onto `E_commerce` names in the saved SQL, and record the mapping in each file's header comment. Reproductions are in `scripts/05_gold_repro.sql`.

### Task 9: `delivery_center` (all 7 tables)

- **Report:** `docs/research/spider2/delivery_center.md`.
- **Events:**
  - One event per non-null moment, emitted in column order, with a `stage` cat attribute.
  - `order_canceled` (16,979 canceled orders).
  - `payment_recorded` (400,834).
  - `delivery_assigned` (378,843), and `delivery_closed` for every delivery whose status is not DELIVERING.
- **Carried attributes:** the 7 `order_metric_*` values and `order_created_{hour,minute,day,month,year}` (the 3 overriding rows prove this), on `order_created` / `order_finished` as the report assigns them.
- **Times:** the format is `'%m/%d/%Y %I:%M:%S %p'` on ingest (via `iso_time`) and `'%-m/%-d/%Y %-I:%M:%S %p'` in views. The report's `scripts/common.py` `fmt` round-trips every moment.
- **Values:** DECIMAL columns compare by value; Task 5 `norm` already handles this.
- **Queries:** local209, local210, local212 (reproductions in `scripts/13_more.py`).

### Task 10: `airlines` (all 8 tables)

- **Report:** `docs/research/spider2/airlines.md`. Use E1–E10 as written there, with N = `2017-08-15 18:00:00+03`. The log includes events at or before N.
- **Times:**
  - Times are parsed from `+03` text and stored as wall-clock +03 read as UTC, consistent with the other projects.
  - Views write back the `+03` suffix and `\N`.
- **Events:**
  - Cancelled flights still emit E5 and E6 when actuals exist (8 flights), and status projection lets Cancelled override.
  - E10 check-in time follows the report's rule. Only `boarding_no` and `seat_no` are data.
- **Values:** the JSON text columns (`model`, `airport_name`, `city`) are entity text, copied byte-exact.
- **Expected counts:** `booking_created` 262,788; `ticket_issued` 366,733; `segment_sold` 1,045,726; `passenger_checked_in` 579,686; `flight_scheduled` 33,121.
- **Queries:** local009, local010 (reproductions in `scripts/airlines/q6_ids.sql` and `scripts/airlines/q7_spider.sql`).

### Task 11: Documentation and real-data checks

**Files:**
- Modify: `examples/README.md` (a "Reference datasets" table: project, source, nature, licence, the `refdata roundtrip` command)
- Modify: root `README.md` (a short "Spider2 reference datasets" section: `refdata fetch`, `refdata roundtrip examples/olist`; note that `data/` holds every derived file and is git-ignored)
- Modify: `apps/refdata/README.md` (commands, the dataset conventions from Task 3's rules, the exactness rule)
- Delete: the stray `examples/ecommerce_s1/` and `examples/ecommerce_s2/` folders (they hold only `__pycache__` and are untracked). Ask the user before deleting.

- [ ] **Step 1: Run every round trip.** Run `uv run refdata roundtrip examples/<p> --force` for all five projects. Each exits 0. Record the wall time and event count of each in `apps/refdata/README.md`.
- [ ] **Step 2: Run the structural checks on each ingested dataset.** Run `uv run datagen check data/ref/<p> --project examples/<p> --skip-stats`. Record which checks fail on real data, if any, in the README under "Laws on real data". These are findings, not bugs to hide. If `datagen check` cannot read an ingested dataset at all (for example, a manifest field it expects is missing), add that field in `ingest` (Task 3) and its test. Do not change `datagen` or simkit.
- [ ] **Step 3: Run the full suite.** `uv run pytest -q && uv run ruff check .` passes.
- [ ] **Step 4: Commit.** Message: `docs: Spider2 reference datasets and refdata`.
