# Synthetic Datasets (PR 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the six `datagen` examples into datasets: a log in, and three table designs out per dataset, each built from the log by SQL, graded against simkit's own tables and against oracle answers to shared questions.

**Architecture:** A new `dataset.synthetic` module runs the pack (simkit API, `sample` profile, seed 7, no overlay) into a temp dir, writes the log with the existing `write_log`, runs each design's `specs/<design>.sql` over the log views (`refdata.logviews.attach_log`), writes the tables to `results/`, checks them against simkit's tables (`[[check]]` in `dataset.toml`), answers each question with `oracle.sql` over simkit's tables, and records labels, cases and the check report in `expected/`. `verify_synthetic` rebuilds every design from the log alone and compares tables and question answers. The CLI dispatches on `kind`.

**Tech Stack:** Python 3.12, DuckDB, PyArrow, Polars, simkit (`libs/simkit`), pytest.

**Spec:** `docs/superpowers/specs/2026-11-03-validation-datasets-design.md`, sections "Results and expected outputs", "Tooling", "Synthetic table designs" and Delivery item 3.

## Global Constraints

- Every dataset: `sample` profile, no overlay, seed 7; `dataset.toml` records project, profile, overlay and seed.
- Designs per dataset (spec table): ecommerce `star dv an`; payments `star dv obt`; payments_subscriptions `star act an`; crypto_exchange `star dv obt`; layer1 `star act obt`; social `star dv act`.
- Design ids: `star`, `dv`, `an`, `act`, `obt`. Every table of `specs/<design>.sql` is named `<design>_…`.
- Results column types: int32, int64, float64, string, bool, date32, timestamp(µs, UTC). Anything else fails the build.
- `dv` hash keys: `md5(<business key as text>)`; link keys `md5(hk1 || '||' || hk2 …)`; `hashdiff` = `md5` of the attributes joined by `'||'` with nulls as `''`; insert-only; load time = event time.
- `star` SCD2 columns: `<entity>_sk` (BIGINT, `row_number()` over natural key then `valid_from`), `valid_from`, `valid_to` (null = open), `is_current`.
- `act` stream columns, in this order: `activity_id, ts, customer, activity, feature_1, feature_2, feature_3, revenue_impact, link, activity_occurrence, activity_repeated_at`.
- Questions: three per dataset; `oracle.sql` reads simkit tables only (schema `sim`); each `<design>.sql` reads that design's results tables only; answers compare as multisets, floats within 1e-9 relative.
- Labels, golden data and cases never enter the log.
- Builds are deterministic and matched against a committed `v1.lock.json`.
- Resource rules (user, standing): every command gets a timeout; measure `/usr/bin/time -l` on the first build of each dataset; one build process at a time; never the whole pytest suite in one process — one test file or folder per process.

## Review Focus

1. A design's answer SQL that silently reads another design's tables or a simkit table — must fail (connections hold only that design's tables).
2. A SQL `sum()` that yields HUGEINT/DECIMAL — must fail the build with the table and column named, not be written.
3. Two builds of the same dataset in a row — byte-identical files, including `expected/check.json` (no paths, no timings).
4. A `[[check]]` whose results projection differs from the simkit table by one row — must fail the build and name the table.
5. A laws/structural check failing in the run — the build fails; an expectations (stats) miss is only recorded.

---

### Task 1: Synthetic config and wider comparison types

**Files:**
- Modify: `apps/dataset/src/dataset/config.py`
- Modify: `apps/dataset/src/dataset/tables.py` (`compare_tables`)
- Test: `apps/dataset/tests/test_config.py`, `apps/dataset/tests/test_tables.py`

**Interfaces:**
- Produces: `DatasetConfig.designs: list[str]`, `DatasetConfig.owners: dict[str, str]`, `DatasetConfig.checks: list[dict]` (each `{"table", "simkit", "columns": {results_col: simkit_col}, "where": str, "simkit_where": str}`), `config.DESIGNS = ("star", "dv", "an", "act", "obt")`; `compare_tables(..., extended: bool = False)` — with `extended=True` also accepts bool, date32 and timestamp columns.

`dataset.toml` for a synthetic dataset:

```toml
name = "ecommerce"
version = "v1"
kind = "synthetic"

[recipe]
project = "examples/ecommerce"   # repo-relative
profile = "sample"
seed = 7
overlay = []                     # none
designs = ["star", "dv", "an"]

[recipe.owners]                  # event -> payload column whose value keys the message
order_placed = "user_id"

[[check]]
table = "star_dim_sku"
simkit = "skus"
columns = { sku_id = "sku_id", category = "category", price = "price" }
where = ""                       # optional filter on the results table
simkit_where = ""                # optional filter on the simkit table
```

- [ ] **Step 1: Write failing tests**
  - `test_synthetic_config_loads`: the toml above loads; `designs == ["star","dv","an"]`, `owners == {"order_placed": "user_id"}`, `checks[0]["columns"]["price"] == "price"`, `checks[0]["where"] == ""`.
  - `test_synthetic_config_refuses`: a design not in `DESIGNS`, three designs required (two given), a missing `project`/`profile`/`seed`, a check without `table` — each raises `ValueError` naming the field.
  - `test_spider2_config_has_no_designs`: a spider2 toml loads with `designs == []`, `checks == []`.
  - `test_compare_extended_types`: two tables with a bool, a date32 and a timestamp[us, UTC] column compare equal with `extended=True`, unequal on one changed timestamp, and fail with "outside the contract" when `extended=False`.
- [ ] **Step 2: Run them, watch them fail** — `timeout 120 uv run pytest apps/dataset/tests/test_config.py apps/dataset/tests/test_tables.py -q` → FAIL (no attribute `designs`, unexpected keyword `extended`).
- [ ] **Step 3: Implement** in `config.py` (validation only when `kind == "synthetic"`) and `tables.py`.
- [ ] **Step 4: Run them, watch them pass** — same command → PASS.
- [ ] **Step 5: Commit** — `feat(dataset): synthetic dataset config and wider comparison types`.

### Task 2: Build and verify a synthetic dataset

**Files:**
- Create: `apps/dataset/src/dataset/synthetic.py`
- Modify: `apps/dataset/tests/conftest.py` (a `tiny_synthetic` fixture)
- Test: `apps/dataset/tests/test_synthetic.py`

**Interfaces:**
- Consumes: Task 1's config fields; `write_log(run, out, owners=, created=None)`; `attach_log(con, root)`; `parse_blocks(text, {"table"})`; manifest helpers (`files_of`, `lock_of`, `lock_diff`, `recipe_sha256`, `write_json`, `writer`); `compare_tables(..., extended=True)`; `check_snapshots`.
- Produces:
  - `build_synthetic(cfg: DatasetConfig, *, record: bool = False) -> dict` (the manifest; `counts` has `log`, `results/<table>` for every table, `questions`);
  - `verify_synthetic(cfg: DatasetConfig, *, root: Path | None = None) -> dict` → `{"ok", "recipe": TableResult, "tables": [TableResult], "questions": [TableResult]}` (question results named `<qid>/<design>`);
  - `class BuildError(ValueError)` re-exported from `dataset.spider2` (one error type for the CLI);
  - `schema/results.json` = `{"designs": {design: [tables]}, "tables": {t: {"design": d, "columns": [{"name", "type"}]}}, "questions": [qid, ...]}`.

Build order (all into `<root>/.v1.tmp`, renamed at the end like `build_spider2`):
1. Simulate in a temp dir: `load_project(REPO / recipe.project)`, `settings(profile)`, seed from the recipe, `plan(overlays)`, `validate`, `simulate`, `neorisk_simkit.io.write`.
2. `write_log(read(run), tmp, owners=cfg.owners)`; then `check_snapshots(tmp)` must be empty.
3. Per design, every `-- table:` block over a UTC DuckDB connection with `attach_log`; refuse a name without the `<design>_` prefix, a table name used twice, or a column type outside the contract (name table and column). Sort each table by all its columns (stable bytes), write `results/<t>.parquet` with `spider2._write_parquet`.
4. Simkit check: for each `[[check]]`, results projection (`SELECT <results cols> FROM t [WHERE where]`) vs simkit projection (`SELECT <simkit cols> AS <results cols> FROM sim.<simkit> [WHERE simkit_where]`), `compare_tables(extended=True)`; any failure → `BuildError` naming the check's table and the first missing/extra rows. Every `star_dim_*` table and every `star_fact_*` table that is not an accumulating snapshot must be named by at least one check (`BuildError` otherwise; accumulating snapshots are named `star_fact_*_lifecycle` and exempt).
5. Questions: each `specs/questions/<qid>/` holds `oracle.sql` and one `<design>.sql` per design (missing or extra files → `BuildError`). `oracle.sql` runs on a connection holding only `sim.<table>` views over the run's entity and event Parquet; its answer goes to `expected/questions/<qid>.parquet`.
6. Expected ground truth: copy `labels/labels.parquet` → `expected/labels.parquet`, `cases/cases.parquet` → `expected/cases.parquet`, and `golden/**` if present → `expected/golden/**`, re-written with `_write_parquet`.
7. `expected/check.json`: `run_checks(data, plan.checks)` plus `check_expectations(data, expectations.yaml, [])` when the file exists; written as `{"pack", "profile", "seed", "overlays", "checks", "failed", "results": [r.as_dict()]}`, `sort_keys=True`. Any failed result whose kind is not `stat`/`expectation` → `BuildError`. (Read `neorisk_simkit.checks.Result` for the kind field's real name.)
8. `verify_synthetic(cfg, root=tmp)` must be ok, else `BuildError` listing the failures.
9. Manifest `kind = "synthetic"`, `source_sha256 = recipe_sha256(REPO / recipe.project)`; lock check / `--record` exactly as `build_spider2`.

Verify: rebuild every design from the log (same code path as step 3, without writing), compare each with `results/` (`extended=True`); for each question and design, a fresh DuckDB connection holding only that design's tables (registered from the rebuilt Arrow tables) runs `<design>.sql`, compared with `expected/questions/<qid>.parquet`. Recipe drift: `manifest.recipe_sha256` vs `recipe_sha256(cfg.dir)`.

Fixture `tiny_synthetic(tmp_path, monkeypatch)`: writes a project under `tmp_path/examples/tiny/` and a dataset under `tmp_path/datasets/tiny/`, points `dataset.config.DATASETS`, `dataset.names.REPO` (or the module's repo constant) and `NEORISK_DATA_ROOT` at tmp. The pack: entity `users` (`tier: cat("a","b")`), events `tier_changed(user_id ref, tier cat)` and `purchased(user_id ref, amount amount())`, 20 users over 3 days, each purchasing daily and changing tier with p=0.3 once. Designs `star` (SCD2 `star_dim_users`, `star_fact_purchase`), `an` (`an_users`, `an_users_tier`), `obt` (`obt_purchase` with tier as of purchase). One question `q1` (revenue by tier at purchase time) with `oracle.sql` and three answers. Checks for `star_dim_users` (where `valid_from = created_at`-version vs `users`) and `star_fact_purchase` vs `purchased`.

- [ ] **Step 1: Write failing tests** in `test_synthetic.py`:
  - `test_build_and_verify`: build ok; `counts["questions"] == 1`; every results table starts with its design; `verify_synthetic` ok with 5 tables and 3 question results.
  - `test_build_is_deterministic`: build twice (rename the first) → `files_of` equal, including `expected/check.json`.
  - `test_record_then_rebuild_matches_lock`: `record=True` writes `v1.lock.json`; a second build passes; after changing one design's SQL the build fails with "differs from v1.lock.json".
  - `test_refuses_unprefixed_table`, `test_refuses_hugeint` (`SELECT sum(amount) AS s …` with no cast → message names table and column), `test_simkit_check_mismatch` (a `where` that drops a row → `BuildError` naming the table), `test_star_table_without_check`, `test_question_answer_differs` (an answer off by one → verify not ok, `q1/an` failed), `test_answer_cannot_read_other_design` (an `an` answer selecting from `star_fact_purchase` → fails), `test_oracle_cannot_read_results`.
  - `test_verify_detects_tampered_result`: rewrite one results file with a row dropped → verify not ok on that table.
- [ ] **Step 2: Run them, watch them fail** — `timeout 300 uv run pytest apps/dataset/tests/test_synthetic.py -q` → FAIL (no module `dataset.synthetic`).
- [ ] **Step 3: Implement `synthetic.py`** per the build order above.
- [ ] **Step 4: Run them, watch them pass** — same command → PASS; also `timeout 300 uv run pytest apps/dataset/tests/test_spider2.py -q` → PASS.
- [ ] **Step 5: Commit** — `feat(dataset): build and verify synthetic datasets`.

### Task 3: CLI, catalogue and context for synthetic datasets

**Files:**
- Modify: `apps/dataset/src/dataset/cli.py`, `apps/dataset/src/dataset/context.py`
- Test: `apps/dataset/tests/test_dataset_cli.py`

**Interfaces:**
- Consumes: Task 2's `build_synthetic`, `verify_synthetic`.
- Produces: `dataset build|verify|context <synthetic>` work; `verify --json` writes `questions` for synthetic (the `queries` key for spider2 is unchanged); `context.render(cfg, root)` renders synthetic datasets:
  - intro: ``Version `v1`, kind `synthetic`, from `examples/<p>` (profile `sample`, seed 7). The input is one ordered event log of N events; the output is T tables in three designs (`star`, …), and the answers to 3 questions.``
  - Event catalogue (unchanged), Snapshot columns (unchanged, so "None: …"),
  - "## Expected output": one sub-table per design, `| Table | Rows | Columns |`; then "Questions" listing each id; then "Ground truth": labels rows, cases rows, check report (`checks` total, failed names or "none").
  - "## Regenerate": `uv run dataset build <name>` / `uv run dataset verify <name>` (no fetch line).

- [ ] **Step 1: Write failing tests**: `test_cli_builds_and_verifies_synthetic` (with `tiny_synthetic`: `main(["build","tiny"]) == 0`, `main(["verify","tiny","--json",p]) == 0` and the JSON has 3 `questions`), `test_list_shows_synthetic` (`dataset list --json` row `{"kind": "synthetic", "built": "unrecorded"}` after build), `test_context_synthetic` (render contains "kind `synthetic`", "### `star`", "| `star_dim_users` |", "Questions", "Ground truth").
- [ ] **Step 2: Run, watch fail** — `timeout 300 uv run pytest apps/dataset/tests/test_dataset_cli.py -q` → FAIL ("synthetic datasets arrive in PR 3").
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, watch pass** — same command → PASS.
- [ ] **Step 5: Commit** — `feat(dataset): CLI and context for synthetic datasets`.

### Tasks 4–9: One synthetic dataset each

One task per dataset, in this order: **4 ecommerce, 5 payments, 6 payments_subscriptions, 7 crypto_exchange, 8 layer1, 9 social.** Each task is the same procedure; the per-dataset scope is below.

**Files (per dataset `<n>`):**
- Create: `datasets/<n>/dataset.toml`, `datasets/<n>/specs/<design>.sql` ×3, `datasets/<n>/specs/questions/<qid>/{oracle,<d1>,<d2>,<d3>}.sql` ×3, `datasets/<n>/CONTEXT.md`, `datasets/<n>/v1.lock.json`
- Test: `apps/dataset/tests/test_dataset_<n>.py`

**Interfaces:** Consumes Tasks 1–3. Produces a built, locked dataset.

Rules for every dataset:
- **Same scope across designs.** All three designs model the same entities and business events (the scope line below), so every question is answerable by every design. Internal events of `std` recipes (`hold_*`, `reservation_*`) may be left out of every design; say so in CONTEXT.md.
- **Owners:** every business event with a natural owner column gets a `[recipe.owners]` line (the entity whose key a Kafka consumer would partition on); events without one keep the default `partition`.
- **Checks:** every `star_dim_*` and every non-lifecycle `star_fact_*` has a `[[check]]`; add checks for `dv_hub_*` key sets and for any table that is a plain projection of a simkit table.
- **History:** wherever the log carries a change to an entity attribute, `star` versions it (SCD2), `dv` gives it its own satellite, `an` its own historized attribute, `act` an activity, `obt` binds it as of the fact time.
- **CONTEXT.md** sections: What this is; Raw data (the pack, its brief, licence "generated, no third-party data"); How the log was made (profile, seed, owners, creation events); then the output of `uv run dataset context <n>` pasted for Event catalogue / Snapshot columns / Expected output / Regenerate; a **Designs** section with one paragraph per design (grain of each table, how history is kept, what it is good and bad at, citing the *Beyond Facts & Dimensions* atlas by name); a **Questions** section (id, the question in one sentence, why it needs history or lifecycle); **Extend** (more rows via `--set`, an overlay as a new dataset, a new design file, a new question, an engine port).
- **Test** `test_dataset_<n>.py`: builds into `tmp_path` root (fixture like `built` but for synthetic, add it to conftest as `built_synthetic`), asserts build matched the lock, verify ok, the design → table-count map, `len(questions) == 9`, and the log's per-event-type counts (`COUNTS` dict, as in Spider2 tests).

Procedure:
- [ ] **Step 1:** Write `dataset.toml` and the test with `COUNTS` and table counts as the design says; run `timeout 300 uv run pytest apps/dataset/tests/test_dataset_<n>.py -q` → FAIL (no designs yet).
- [ ] **Step 2:** Write the three design files and the three questions. Build with `timeout 300 /usr/bin/time -l uv run dataset build <n>`; record wall time and peak RSS in the commit message. Iterate until build and `timeout 300 uv run dataset verify <n>` pass.
- [ ] **Step 3:** `timeout 300 uv run dataset build <n> --record`; rebuild once more without `--record` (must match the lock).
- [ ] **Step 4:** Write CONTEXT.md (paste `uv run dataset context <n>`). Run the test → PASS.
- [ ] **Step 5: Commit** — `feat(datasets): <n> synthetic dataset, three designs and v1 lock`.

Per-dataset scope, designs and questions (question SQL and exact table lists are the implementer's; the ids and meanings below are fixed):

| Task | Dataset | Scope (every design) | Designs | Questions |
|---|---|---|---|---|
| 4 | ecommerce | users (region history from `address_changed`), devices, skus, orders, order lines, sessions/views, returns, referral bonuses | star, dv, an | `q1_revenue_by_region_at_order`: orders and amount by the user's region in force at order time · `q2_units_by_category`: units and line amount by SKU category · `q3_bonus_by_channel`: referral bonuses paid (count, amount) by the inviter's acquisition channel |
| 5 | payments | customers, cards, merchants, payments with their lifecycle (authorized, captured, replayed, expired, refunded, disputed, resolved), declines, settlements, statements | star (incl. `star_fact_payment_lifecycle`), dv, obt | `q1_money_by_mcc`: authorized count, captured, refunded and chargeback amounts by merchant MCC · `q2_final_status_by_brand`: payments by final status (precedence: charged_back > refunded > captured > expired > authorized; declined separately) and card brand · `q3_settlement_by_country`: settlement net per merchant country and day |
| 6 | payments_subscriptions | subscribers, subscriptions (started, converted, invoices, failed charges, cancellation) | star (incl. lifecycle fact), act, an | `q1_active_at_end_by_plan`: subscribers active at the end of the log, and their price sum, by plan · `q2_paid_by_plan_cycle`: invoices paid (count, amount) by plan and cycle · `q3_churn_by_reason`: cancellations by reason and plan, with mean cycles paid |
| 7 | crypto_exchange | traders, deposits, orders with their lifecycle (accepted, rejected, filled, cancelled, resting at end), trades | star (incl. order lifecycle fact), dv, obt | `q1_volume_by_symbol_day`: trades, quantity and notional (price × qty) per symbol and day · `q2_maker_taker_by_segment`: maker and taker quantity by trader segment · `q3_order_outcomes`: orders by type and final outcome |
| 8 | layer1 | accounts, genesis allocations, transactions (received, included or dropped, transfer logs), blocks | star (incl. tx lifecycle fact), act, obt | `q1_final_balances`: each account's balance at the end (genesis + values in − values out − fees; reverted values excluded) · `q2_daily_chain`: per day, included txs, gas used and fees · `q3_drops_by_kind`: dropped txs by reason and sender account kind |
| 9 | social | users, follows, posts, views, likes, reposts (cascades) | star, dv, act | `q1_engagement_by_tier`: per author tier, posts and the views, likes and reposts their posts received · `q2_cascade_depth`: root posts by the maximum repost depth of their cascade · `q3_follower_buckets`: users by follower-count bucket (0, 1–9, 10–99, 100+) and tier |

### Task 10: Catalogue, docs and the reserved suffix

**Files:**
- Modify: `datasets/README.md`, `examples/README.md`

- [ ] **Step 1:** `datasets/README.md`: a "Synthetic datasets" part of "A dataset" (layout: `specs/<design>.sql`, `specs/questions/`, the `[recipe]` and `[[check]]` keys, `expected/` contents); a "Table designs" section (the five design ids and rules, from the spec); a sentence that `_snapshot` is a reserved event-name suffix (`<entity>_snapshot` events must follow the snapshot rule; no other event may end in `_snapshot`); six catalogue rows (kind `synthetic`, source `examples/<p>`, licence "generated", log events, tables, result rows, questions = 3, engines `duckdb`). Remove the line saying synthetic datasets arrive in PR 3.
- [ ] **Step 2:** `examples/README.md`: one line pointing each project at its dataset.
- [ ] **Step 3:** Run one pytest process per file, each with `timeout 300`: the six `test_dataset_<synthetic>.py`, then `test_synthetic.py`, `test_dataset_cli.py`, `test_config.py`, `test_tables.py`, `test_spider2.py`, `test_snapshots.py` → all PASS. `timeout 120 uv run ruff check apps/dataset` → clean. After `dataset build <n>` for each, `uv run dataset list` shows the six synthetic datasets `yes`.
- [ ] **Step 4: Commit** — `docs: synthetic datasets, table designs and the reserved _snapshot suffix`.
