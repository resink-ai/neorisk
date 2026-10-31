# Spider2 reference datasets, batch 2 (exact round trip): Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eight more Spider2 catalogs become simkit event logs. For each, `refdata roundtrip examples/<project>` exits 0: every source table rebuilds exactly and every saved query agrees.

**Architecture:** No new app. Each task adds one `examples/<project>/` folder, laid out like the batch-1 projects:
- `datagen.toml`
- `specs/pack.py`
- `specs/source.toml`
- `specs/ingest.sql`
- `specs/views.sql`
- `specs/queries/*.sql`

Each task also adds `apps/refdata/tests/test_project_<project>.py`. A change to `apps/refdata` itself is made only when a project needs it, under TDD with its own unit test in the existing test files.

**Tech Stack:** as batch 1 (Python 3.12, sqlite3, Polars, DuckDB, `neorisk_simkit`, pytest).

**Spec:** `docs/superpowers/specs/2026-10-30-spider2-reference-datasets-design.md` (section "Batch 2"). Research: `docs/research/spider2/<report>.md`, with scripts in `docs/research/spider2/scripts/<report>/`.

## Global Constraints

- No change to `libs/simkit`, `apps/datagen` or the batch-1 projects.
- Nothing derived from the data goes into git. Sources are in `data/spider2/`; outputs go to `data/ref/` or the test's `tmp_path`.
- Sources are opened read-only.
- Time: source wall clock is stored as if it were UTC. Ingest emits ISO text, and views format it back to the source's exact text.
- Exactness is batch 1's rule: tables compare as multisets of rows, INTEGER and REAL by value, and NULL, `''` and `'\N'` are distinct. No tolerance applies to tables; queries use rel 1e-9.
- Every block in `ingest.sql` ends in an ORDER BY.
- Money that is exact cents is `amount()`. Money of a finer or odd scale is an `i64` of stated units, with the unit in its column comment.
- Each query file's header comment names the Spider2 instance id. It also says whether the SQL is gold SQL or written from the question text, and whether the report reproduced a gold CSV.
- Code style follows `apps/refdata`, and `ruff check` must be clean.

## Review Focus

1. **Text that is not a number in a numeric source column** (Pizza Runner '20km', AdventureWorks `''`). It must come back byte-exact in the raw table and in the cleaned value in the derived table. Owner: Tasks 1 and 7.
2. **Entity `created_at` after the last event** (Pizza Runner runner 4, Sakila customers). Ingest must not reject it, and the manifest run window must cover it, or `datagen check` will flag it. Owner: Task 1 (Task 5 reuses it).
3. **A pack table with zero rows** (Sakila `film_text`, weblog `noisy_action_logged`, the empty Northwind demographics tables). Ingest writes an empty Parquet file with the right schema, and the view rebuilds an empty table. Owner: Task 4.
4. **Float text formats** (Northwind float4 `32.3800011`, Chinook totals, AdventureWorks 4-decimal values). These are rebuilt from integers by a rule, never by float arithmetic in an order that may change. Owner: Tasks 3, 4 and 7.
5. **Ties in time order that a gold query depends on** (weblog `activity_log`, Bitcoin midnight trades). `ord` is set so that `seq` keeps the source order. Owner: Tasks 2 and 6.

---

Every project task has the same five steps:

- [ ] **Step 1: Write the project test** `apps/refdata/tests/test_project_<p>.py`, using `conftest.roundtrip`. Assert `summary["failed"] == []`, the query count, and the event and entity counts listed in the task.
- [ ] **Step 2: Run it and watch it fail.** `uv run pytest apps/refdata/tests/test_project_<p>.py -q`. Expected: FAIL, because the project does not exist yet.
- [ ] **Step 3: Write the project files** from the report's sections 2, 3 and 6, plus the queries.
- [ ] **Step 4: Run it until it passes**, then run `uv run datagen check data/ref/<p> --project examples/<p> --skip-stats`. Expected: 0 problems, or a real-data finding recorded for Task 9.
- [ ] **Step 5: Commit.** Message: `feat(examples): <p> reference dataset, exact round trip`.

### Task 1: `pizzarunner` (modern_data, `pizza_*`)

- **Report:** `pizzarunner.md`.
- **Entities:** runners 4 (`created_at` = registration date), pizzas 2 (name plus the recipe's comma list as text), toppings 12, customers 5.
- **Events:**

  | Event | Count | Time |
  |---|---:|---|
  | `pizza_ordered` | 14 | order time |
  | `order_picked_up` | 8 | pickup time |
  | `order_delivered` | 8 | pickup + duration (rule) |
  | `order_cancelled` | 2 | order time (rule) |

- **Raw columns:** the raw `distance`, `duration` and `cancellation` text is carried byte-exact.
- **Views:**
  - `pizza_customer_orders` and `pizza_clean_customer_orders` are identical.
  - `pizza_clean_runner_orders` = `coalesce(leading number, 0.0)`.
  - `pizza_get_extras` and `pizza_get_exclusions` hold one row per distinct (order, topping), ranked by first appearance, as the report gives.
- **Queries:** local065, local066, local073, plus any other pizza question the report lists.
- **Review Focus 2:** add a unit test to `test_ingest.py` for an entity whose `created_at` is later than every event. The manifest's `run.start + days` must cover it.

### Task 2: `bitcoin` (bank_sales_trading, `bitcoin_*`)

- **Report:** `bitcoin.md`.
- **Entities:** members 14, tickers 2.
- **Events:** `trade` 22,918 (owner `member`, ord `txn_id`) and `price_published` 3,404 (owner `ticker`).
- **Views:** `change` is carried text. `volume` is re-formatted from whole coins as the report's rule gives (`p1_roundtrip.py`).
- **Queries:** local156, local157.

### Task 3: `chinook` (chinook)

- **Report:** `chinook.md`.
- **Entities:** the 9 lookup and catalog tables named in the report. `playlist_track` is either an entity or folded into playlists, whichever the report says.
- **Events:** `invoice_issued` 412, `invoice_line_added` 2,240.
- **Views:** `Total` = Σ(line cents)/100.0. The billing address comes from the customer.
- **Queries:** chinook's 3.

### Task 4: `northwind` (northwind)

- **Report:** `northwind.md`.
- **Entities:** 11 tables.
- **Events:** `order_placed` 830, `order_line_added` 2,155, `order_shipped` 809.
- **Views:** float4 columns are printed from integers with the report's `%.9g` rule. `picture` and `photo` are carried hex text.
- **Review Focus 3:** add a unit test to `test_ingest.py` / `test_rebuild.py` for a block with 0 rows. Ingest writes an empty table, and rebuild writes an empty table.
- **Queries:** northwind's 2.

### Task 5: `sakila` (sqlite-sakila)

- **Report:** `pagila.md`.
- **Entities:** 12 tables, 13,180 rows.
- **Events:** `rental_started` 16,044, `payment_taken` 16,049, `rental_returned` 15,861.
- **Columns:**
  - `last_update` is carried text.
  - The 5 payments with no rental keep `rental_id` NULL.
- **Views:** `film_category` is rebuilt from `film`; `film_text` is rebuilt empty.
- **Queries:** all 9 (Pagila 2 + sqlite-sakila 7). Each query's SQL names its tables as they are in sqlite-sakila.

### Task 6: `weblog` (log)

- **Report:** `weblog.md`.
- **Events:** 15 types, 834 rows, as section 2 lists, including `noisy_action_logged` with 0 rows. `activity_log` uses ord = source rowid.
- **Entities:** app1_users, app2_users, user_cards, product_sales.
- **Times:** the column-shifted `access_log` rows and the untimed rows get the report's rule times.
- **Views:** the two product snapshots are rebuilt from the change events.
- **Queries:** local329, local330, local358, local360. local331 is included too if its source and rebuilt results agree; there is no gold to check it against.

### Task 7: `adventureworks` (AdventureWorks)

- **Report:** `adventureworks.md`.
- **Entities:** 7, holding 1,443 rows.
- **Events:**

  | Event | Count |
  |---|---:|
  | `order_placed` | 31,465 |
  | `order_line_added` | 121,317 |
  | `order_shipped` | 31,465 |
  | `currency_rate_published` | 13,532 |
  | `quota_set` | 163 |
  | `product_reviewed` | 4 |

- **Values:** money is held as integers of 1e-4.
  - `subtotal` = line sum, rounded half-up.
  - `totaldue` = subtotal + tax + freight, computed in integers.
- **Review Focus 1:** `''` in numeric columns must round-trip.
- **Snapshot:** N = 2014-07-07.
- **Query:** local141.

### Task 8: `oraclesh` (complex_oracle)

- **Report:** `oraclesh.md`.
- **Entities:** countries, channels, promotions, products (75: 24 real plus 51 placeholders, with a flag column), customers, demographics, times.
- **Events:** `unit_sold` 918,843 and `price_quoted` 82,112.
- **Views:**
  - `products` rebuilds only the 24 real rows.
  - `currency` is generated by the report's rule.
- **Queries:** local050, local060, local061, local062, local063, and local067 if source and rebuilt agree.

### Task 9: Documentation and real-data checks

- **Files:** modify `examples/README.md` (reference table), `apps/refdata/README.md` (results table, "Laws on real data" and the batch-2 rows of "Times the sources do not have"), and the root `README.md` only if its list of projects names them.
- [ ] **Step 1:** Run every batch-2 round trip with `--force` and record wall time and event count.
- [ ] **Step 2:** Run `datagen check --skip-stats` on each and record the findings.
- [ ] **Step 3:** `uv run pytest -q && uv run ruff check .` passes.
- [ ] **Step 4:** Commit with message `docs: Spider2 batch-2 reference datasets`.
