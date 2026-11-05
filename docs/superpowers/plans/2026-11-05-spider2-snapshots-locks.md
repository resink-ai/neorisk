# Spider2 snapshot columns and v1 locks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** All 43 Spider2 datasets reach the final event contract:
- snapshot-only columns travel in `<entity>_snapshot` events at N;
- creation events carry a domain name where one fits;
- `CONTEXT.md` is complete;
- `v1.lock.json` is committed.

**Architecture:** There are three small shared changes:
1. A build-time check that snapshot events obey the contract.
2. An `event=` option on `-- entity:` blocks that renames the creation event.
3. A counted "Snapshot columns" section in `dataset context`.

After that, each dataset is re-cut in its own specs, rebuilt, verified exactly and recorded with `dataset build NAME --record`. The lock machinery already exists (`apps/dataset/src/dataset/manifest.py`, `build_spider2(record=)`), and a lock is checked on every later build.

**Tech Stack:** Python 3.12, polars, DuckDB, SQLite, pytest, uv.

**Spec:** `docs/superpowers/specs/2026-11-03-validation-datasets-design.md` (sections "Entities as events", "Tooling", Delivery item 2).

## Global Constraints

- **Scope:** "Snapshot-only attributes … The recipe marks those columns as **snapshot** columns. They leave the creation event and travel in one `<entity>_snapshot` event at the dataset's snapshot time N. That way no event carries a value from its future."
- **Classification:** "which columns are snapshot columns is a per-dataset research call. Each one is listed, with its reason, in the context file. When in doubt, a column is a snapshot column."
- **Naming:** "every entity row becomes one `<entity>_created` event … or a domain name the recipe gives, such as `customer_signed_up`."
- **Locks:** "A version, once built and recorded, is immutable. Changing the log, the schema or the results makes a new version. Changing the context file does not."
- **No invented values** in any event, except times given by a documented rule.
- **Exact round trip:** the rebuilt tables must still equal the source exactly. Never loosen `mixed`, `exact` or the tolerance to make a dataset pass.
- **Scope of datasets:** all 43 Spider2 datasets under `datasets/` (user decision, 2026-11-05).
- **Resources** (user rule):
  - Build **one dataset at a time**, one process. Never run builds in parallel.
  - Every command runs under `timeout`, with a limit sized from the measured or estimated time: about 2–3× the expected time.
  - Measure with `/usr/bin/time -l`.
  - Stop and report if a build goes past its timeout or above 6 GB peak RSS.
  - Never run the whole pytest suite in one process. Run tests one file at a time, each under `timeout`.
- **Git:**
  - Stage explicit paths only.
  - Commit messages end with:
    ```
    Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
    Claude-Session: https://claude.ai/code/session_01WZQSS2mzekVUB4yUaMzNjq
    ```
- **Data:** no data or Parquet in git; the lock files (JSON) are committed. Sources in `data/spider2/` are opened read-only.

## Review Focus

1. **A domain name that collides** with another event type, or with another entity's creation name, must fail ingest by name, not merge two views. Test: `test_created_name_collision_refused` (Task 2).
2. **A `*_snapshot` event whose owner is not a ref to its entity** (so `entity_type` is a column name) must fail the build. Test: `test_snapshot_owner_must_be_its_entity` (Task 1).
3. **Snapshot events at two different times, or earlier than a later business event,** must fail the build. Test: `test_snapshot_time_after_every_event` (Task 1).
4. **Two snapshot events for one entity key** must fail the build. Test: `test_one_snapshot_per_key` (Task 1).
5. **`dataset context` on a dataset with no snapshot events** must say "none", not print an empty table. Test: `test_context_snapshot_section_none` (Task 3).

---

### Task 1: Snapshot contract check at build

**Files:**
- Create: `apps/dataset/src/dataset/snapshots.py`
- Modify: `apps/dataset/src/dataset/spider2.py`. In `build_spider2`, call the check right after `write_log`; a problem becomes a `BuildError`.
- Test: `apps/dataset/tests/test_snapshots.py`

**Interfaces:**
- Produces: `check_snapshots(root: Path) -> list[str]`. It reads `root/schema/events.json` and `root/log/*.parquet`, and returns human-readable problems, empty when fine. Task 3 and PR 3 (synthetic datasets) reuse it.

**Rules:** a snapshot event is any event type named `<x>_snapshot` where `x` is an entity in `events.json` (an entry of kind `entity_created` has `entity == x`). For those events:
- (a) every row's `entity_type` equals `x`;
- (b) all rows of all snapshot events share one `event_time` N;
- (c) N ≥ the max `event_time` of every non-snapshot event;
- (d) `(event_type, entity_key)` is unique;
- (e) `entity_key` is never null.

A `<y>_snapshot` event whose `y` is not an entity is an error too ("snapshot event for unknown entity"), so a typo cannot slip through as a business event.

- [ ] **Step 1:** Write the failing tests in `test_snapshots.py`.
  - Write small log folders with polars, using the envelope columns of `neorisk_simkit.io.log.ENVELOPE` and a minimal `events.json`.
  - Add a helper `make_log(tmp_path, rows, entities)`.
  - The tests:
    - `test_valid_snapshot_passes`: `check_snapshots(...) == []`.
    - `test_snapshot_owner_must_be_its_entity`: `entity_type="company_id"` → one problem naming `companies_snapshot` and `entity_type`.
    - `test_snapshot_time_after_every_event`:
      - a business event one second after N → a problem containing "after the snapshot time";
      - two N values → a problem containing "one snapshot time".
    - `test_one_snapshot_per_key`: two rows for key `"7"` → a problem naming key `7`.
    - `test_snapshot_for_unknown_entity`: `compnies_snapshot` → a problem containing "unknown entity".
    - `test_no_snapshot_events_passes`: `[]`.
- [ ] **Step 2:** Run `timeout 120 uv run pytest apps/dataset/tests/test_snapshots.py -q`. Expected: it fails on import (`dataset.snapshots` has no `check_snapshots`).
- [ ] **Step 3:** Implement `check_snapshots` with DuckDB over `read_parquet(root/'log/*.parquet')`, one query per rule.
- [ ] **Step 4:** Run the tests again. Expected: PASS.
- [ ] **Step 5:** Wire it into `build_spider2` after `write_log`.
  - The failing test is `test_spider2.py::test_build_refuses_bad_snapshot`: in the shop fixture, an extra `orders_snapshot` block with a non-ref owner → `BuildError` mentioning `orders_snapshot`. Add a snapshot event to the fixture pack through `make_shop`'s text, without changing the other shop tests.
  - Watch it fail, wire the check in, and watch it pass.
- [ ] **Step 6:** Re-check the 11 datasets that already have snapshot events, against their current builds (a quick read, no rebuild):
  ```
  timeout 120 uv run python -c "from pathlib import Path; from dataset.snapshots import check_snapshots as c; [print(n, c(Path('data/datasets')/n/'v1')) for n in 'university school oraclesql unicorns cities imdb_movies aliens dbimdb eusoccer nyctrees'.split()]"
  ```
  Expected: every list empty.
- [ ] **Step 7:** Run `uv run ruff check apps/dataset`, then commit `feat(dataset): build checks the snapshot contract`.

### Task 2: Domain names for creation events

**Files:**
- Modify: `libs/simkit/src/neorisk_simkit/io/log.py`:
  - `_entry`, `_entries`, `events_schema`, `log_frame` and `write_log` gain the keyword `created: dict[str, str] | None = None` (entity → event name);
  - the default name stays `f"{entity}_created"`;
  - a duplicate final name across entries raises `LogError`.
- Modify: `apps/refdata/src/refdata/ingest.py`:
  - add `created_names(project: Path) -> dict[str, str]`, built from `-- entity: <name> event=<event_name>` options;
  - `ingest` refuses an `event=` value that is not `^[a-z][a-z0-9_]*$` (`IngestError`).
- Modify: `apps/dataset/src/dataset/spider2.py` and `apps/refdata/src/refdata/cli.py` (the two `write_log` callers): pass `created=created_names(project)`.
- Modify: `apps/refdata/README.md`, at the block-syntax row: document `event=`.
- Test: `libs/simkit/tests/test_log.py` and `apps/refdata/tests/test_ingest.py`.

**Interfaces:**
- Produces: `write_log(run, out_dir, *, owners=None, created=None, part_rows=1_000_000)` and `created_names(project) -> dict[str, str]`.
- The `logviews` view for a creation event stays named after the **entity** (`logviews.py:64`), so no `build.sql` changes when an event is renamed.

- [ ] **Step 1:** Write the failing tests:
  - `test_created_name_renames_event`: with `created={"customers": "customer_signed_up"}`, the log's `event_type` and the `events.json` name are `customer_signed_up`, and `kind` stays `entity_created`.
  - `test_created_name_collision_refused`: a name equal to an existing business event → `LogError` naming both.
  - `test_created_names_from_entity_block` (refdata): parses `-- entity: customers event=customer_signed_up`.
  - `test_bad_created_name_refused`: `event=Customer-Signup` → `IngestError`.
- [ ] **Step 2:** Run each file under `timeout 120 uv run pytest <file> -q`. Expected: FAIL (unexpected keyword `created`; no `created_names`).
- [ ] **Step 3:** Implement as above.
- [ ] **Step 4:** Run the tests again. Expected: PASS.
- [ ] **Step 5:** Run the light suites, each in its own process: `timeout 300 uv run pytest libs/simkit/tests/test_log.py -q` and `timeout 600 uv run pytest apps/refdata/tests -q`. Expected: PASS. Measure the refdata run first with `-x --co -q` to check it doesn't build real datasets.
- [ ] **Step 6:** Ruff, then commit `feat(refdata): domain names for creation events (entity block event=)`.

### Task 3: Snapshot columns in `dataset context`

**Files:**
- Modify: `apps/dataset/src/dataset/context.py`. `render` adds a `## Snapshot columns` section between "Event catalogue" and "Expected output":
  - a table `| Entity | Snapshot event | At | Columns |` (N as `YYYY-MM-DD HH:MM:SS` UTC; columns are the payload fields minus the key field);
  - when there are no snapshot events, the line `None: every entity attribute travels in its creation event.`
- Test: `apps/dataset/tests/test_dataset_cli.py`

**Interfaces:** Consumes Task 1's naming rule (`<entity>_snapshot`, where the entity is in `events.json`).

- [ ] **Step 1:** Write the failing tests:
  - `test_context_snapshot_section_lists_columns`: the shop fixture with the snapshot block from Task 1 Step 5, fixed to a ref owner → the output contains `## Snapshot columns` and the row with its columns.
  - `test_context_snapshot_section_none`: the plain shop → contains `None: every entity attribute travels in its creation event.`
- [ ] **Step 2:** Run `timeout 120 uv run pytest apps/dataset/tests/test_dataset_cli.py -q`. Expected: the 2 new tests FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5:** Ruff, then commit `feat(dataset): context lists snapshot columns`.

### Tasks 4–46: One dataset each

One task per dataset, done **in this order (smallest log first)**, so the slow builds come last and their timeouts can be sized from the measured rates:

pizzarunner, university, staffhours, entertainment, weblog, school, covidstates, oraclesql, bowling, unicorns, northwind, salaries_india, databank, stacking, chinook, music, freshsegments, parchposey, datamart, bitcoin, cliquebait, cities, sakila, imdb_movies, aliens, legislators, wwe, dbimdb, ipl, adventureworks, eusoccer, wordlist, jobpostings, switrs, baseball, f1, veg, atliq, oraclesh, nyctrees, olist, airlines, delivery_center.

(Task 4 = pizzarunner … Task 46 = delivery_center.)

**Files per dataset `<n>`:**
- `datasets/<n>/specs/pack.py`, `ingest.sql`, `build.sql`
- `datasets/<n>/CONTEXT.md`
- `datasets/<n>/v1.lock.json` (new)
- `apps/dataset/tests/test_dataset_<n>.py` (COUNTS)

**Classification rubric.** Apply it to every entity column. Write each verdict, with its reason, in the CONTEXT table.
- **Creation:** a value fixed when the row came into being. This covers:
  - the key and `ext_id`;
  - given names and titles;
  - birth, founding and creation dates;
  - the original category or type the row was created with;
  - immutable refs, such as a film's language or an order line's product.
- **Snapshot:** a value that is only known as of the extract, or that can change after creation. This covers:
  - `last_update` and other modification stamps;
  - current status, active flags, stock, balances, prices, salaries, titles held, addresses, e-mails and phones;
  - ratings, ranks, GPAs, counters and lifetime totals that the log cannot derive.
- **Derived:** a value that `build.sql` can already compute from the log (it was proven derived in the research reports). It stays derived and is neither carried nor snapshotted.
- **When in doubt: snapshot** (spec rule). Do not move a column whose value decides an event's time, if that would make the event carry a time from a snapshot. If a column is both, note it and keep the creation time rule.
- The research reports in `docs/research/spider2/` (batch 3) and `docs/superpowers/specs/2026-10-30-spider2-reference-datasets-design.md` (batches 1–2) already argue many columns. Follow them unless the rubric says otherwise; any difference is a ledger `Ruling:`.

**Domain names:** give a creation event a domain name (`-- entity: customers event=customer_signed_up`) only when the source shows the real-world act: a sign-up, a hire, an enrolment, a listing, a release. Otherwise keep `<entity>_created`.

**N:**
- Use the existing snapshot time when the dataset has one.
- Otherwise use the latest event time in the log (rounded up to the next whole day if that is more natural), documented under "Times set by rule".
- It must pass `check_snapshots`.

**Steps per dataset:**

- [ ] **Step 1:** Re-cut the specs:
  - move the snapshot columns from the `-- entity:` block into one `-- event: <entity>_snapshot owner=<key>` block per entity at N;
  - declare the event in `pack.py` with the key as `ref("<entity>")`;
  - join it back in the table's `-- table:` block in `build.sql`, with a LEFT JOIN on the key, so an entity without a snapshot row keeps NULLs exactly as the source has them;
  - add the domain name if there is one.
- [ ] **Step 2:** Update `COUNTS` in `test_dataset_<n>.py`: the new `<entity>_snapshot` counts, and renamed creation events. Run `timeout <T> uv run pytest apps/dataset/tests/test_dataset_<n>.py -q`. Expected: FAIL on COUNTS (the specs or COUNTS changed, the build doesn't match yet), or PASS if specs and COUNTS already agree. Note which.
- [ ] **Step 3:** Run `/usr/bin/time -l timeout <T> uv run dataset build <n> && timeout <T> uv run dataset verify <n>` until both exit 0.
  - `<T>`: 120 s up to 20k events, 600 s up to 200k, 1800 s up to 1.5M, 3600 s above (Task 38 onward).
  - Record the real time and peak RSS in the ledger line.
  - On a verify failure, fix the specs, never the checks.
- [ ] **Step 4:** Run `timeout <T> uv run dataset build <n> --record`. This writes `datasets/<n>/v1.lock.json`.
- [ ] **Step 5:** Run `timeout <T> uv run pytest apps/dataset/tests/test_dataset_<n>.py -q`. Expected: PASS. This rebuilds into tmp and checks it against the lock, which proves the build is deterministic.
- [ ] **Step 6:** Update `CONTEXT.md`:
  - paste the counted sections from `timeout 120 uv run dataset context <n>`, including the new "Snapshot columns";
  - add a reason column for each snapshot column;
  - replace "Classified in PR 2" or add the missing section in the pizzarunner order;
  - give the N rule under "Times set by rule".
- [ ] **Step 7:** Run `uv run ruff check datasets apps/dataset`, then commit `feat(datasets): <n> snapshot columns and v1 lock`. Stage the dataset folder and its test file.

### Task 47: Catalogue and docs

**Files:**
- `datasets/README.md`: a lock note, and the snapshot and domain-name rules in the "extend" recipe.
- The spec's Delivery item 2: "all 13" → "all 43", noting the user decision of 2026-11-05.
- `apps/refdata/README.md`: done in Task 2. Check it.

- [ ] **Step 1:** Edit the files.
- [ ] **Step 2:** Run `timeout 120 uv run dataset list`. Expected: every Spider2 dataset shows `built` = `yes`. Nothing should show `unrecorded` or `stale`.
- [ ] **Step 3:** Commit `docs: snapshot columns, domain names and v1 locks`.
