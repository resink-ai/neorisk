# modern_data (Spider 2.0-lite), pizza_* tables: reverse-engineering Pizza Runner into an event log

Source: `data/spider2/modern_data.sqlite`, opened read-only (`sqlite3 -readonly`, `python3 -I` with `mode=ro`).
Scripts: [`scripts/pizzarunner/`](scripts/pizzarunner/) (`01_inventory.sql`, `02_derived_exact.sql`, `03_lifecycle.py`, `04_gold.py` with `04_local065_gold.sql`, `04_local066_gold.sql` and the gold CSVs in `gold/`, `05_others.sql`).
All numbers below come from those scripts.

## 0. What this catalog is

`modern_data` is a bundle of unrelated tables. The `pizza_*` group is Danny Ma's **8 Week SQL Challenge, Case #2 Pizza Runner**. Evidence: runners 1–4 registered in the weeks starting 2021-01-01, customers 101–105, pizzas `Meatlovers`/`Vegetarian`, toppings Bacon…Tomato Sauce, and the case's two cancellation texts. It is **hand-written course data**: ten orders typed in by the author, not generated and not real. Licence: unstated (the case study page publishes the data as a DB Fiddle schema without a licence).

| Table | Rows | Role |
|---|---:|---|
| pizza_customer_orders | 14 | raw: one row per pizza ordered |
| pizza_runner_orders | 10 | raw: one row per order: runner, pickup, distance, duration, cancellation |
| pizza_runners | 4 | lookup: runner_id, registration_date |
| pizza_names | 2 | lookup: pizza_id → name |
| pizza_recipes | 2 | lookup: pizza_id → comma list of topping ids |
| pizza_toppings | 12 | lookup: topping_id → name |
| pizza_clean_customer_orders | 14 | derived: "cleaned" copy of customer_orders |
| pizza_clean_runner_orders | 10 | derived: distance and duration parsed to REAL |
| pizza_get_extras | 6 | derived: extras split into one row per (order, topping) |
| pizza_get_exclusions | 4 | derived: exclusions split the same way |

Counts from `01_inventory.sql`. The clean_* and get_* tables are not part of the original case; they look like one solver's helper tables, saved into the Spider2 copy (§3 proves they are exact functions of the raw tables).

**The famous dirt is mostly gone in this copy.** The original case ships `'null'` strings and `''` in `exclusions`/`extras`/`pickup_time`/`distance`/`duration`/`cancellation`. Here, across every text column of the raw and clean tables, there are **0** values equal to `'null'`, `''` or `'\N'` (`01_inventory.sql`, `dirty_tokens`). Missing values are true SQL NULL: exclusions NULL 9/14, extras NULL 10/14, runner_orders pickup/distance/duration NULL 2/10, cancellation NULL 8/10. The import into Spider2 apparently normalised them. What survives is the **unit text** in runner_orders.distance and .duration (§4).

## 0.1 How Spider 2.0 uses it

`db == modern_data` has 7 questions. The 3 pizza ones:

| id | Analysis | Gold SQL? | Reproduced here? |
|---|---|---|---|
| local065 | Income: Meatlovers $12, Vegetarian $10, +$1 per extra, cancelled orders excluded | yes | **Yes**: the gold SQL gives **142** = variant `_b`. 138 from pizzas + 4 delivered extras. Variant `_a` = 144 counts the 2 extras of cancelled order 9 too (`04_gold.py`) |
| local066 | Total quantity of each ingredient in **delivered** pizzas (recipe − exclusions + extras) | yes | **Yes, `_a`**: the per-pizza reading (delivered only, the line's own exclusions, extras added) equals `_a` exactly (total 89, Bacon 12, Cheese 10). The gold SQL does **not** filter cancellations and applies exclusions per order, so it matches **no** accepted CSV (Bacon 14, total 102). `_b` and `_c` are matched by none of the 8 readings tried |
| local073 | One row per pizza line: "Name: 2x A, 2x B, C, …", recipe − own exclusions + own extras, doubles first, then alphabetical | no | **Yes, all 14 rows**: equal to `_a` (with `"2x "`) and to `_b` (with `"2x"`, no space) |

Out of scope: local040 and local041 (trees + income_trees), local049 (companies_*), local201 (word_list).

What the questions need from a rebuild: the comma lists **byte-exact** as text (they are split with `INSTR`/`TRIM`), `pizza_clean_*` present (local065 and local066 read `pizza_clean_customer_orders` and `pizza_clean_runner_orders`), `cancellation IS NULL` as the "delivered" test, and the physical **line order** inside customer_orders (local073's row id is `ROW_NUMBER() OVER ()` or rowid). local066 and local073 are good exact-value regression checks. local065 is a single number.

## 1. Inventory, keys, joins

| Table | Key (verified) | Notes |
|---|---|---|
| customer_orders | **none.** 1 group of fully duplicate rows: order 4's two plain Meatlovers with exclusion `4` (rows 5–6) | 10 orders, 5 customers. Per order: 1 customer and 1 order_time (0 exceptions). Pizzas per order: 1→7, 2→2, 3→1 |
| runner_orders | order_id (10/10 unique) | exactly one row per order |
| runners | runner_id (4) | registration_date `YYYY-MM-DD` text |
| names, recipes | pizza_id (2 each) | 1:1 on pizza_id |
| toppings | topping_id (12) | |
| clean_customer_orders | same as customer_orders | |
| clean_runner_orders | order_id | |
| get_extras, get_exclusions | (order_id, row_id) | row_id restarts at 1 per order |

No foreign keys are declared. Coverage, all measured in `01_inventory.sql`:
- customer_orders.pizza_id → names: 0 orphans.
- runner_orders.order_id → customer_orders: 0 orphans, and every order has a runner row (0 without).
- runner_orders.runner_id → runners: 0 orphans. **Runner 4 has no orders.**
- Every topping token, in recipes, exclusions and extras, is a known topping_id (`02_derived_exact.sql`, `orphan_topping_tokens` = 0).
- Customers have no table: 101 (3 orders), 102 (2), 103 (2), 104 (2), 105 (1).
- Orders per runner: runner 1: 4 orders, all delivered; runner 2: 4, 3 delivered; runner 3: 2, 1 delivered.

Physical order: both raw tables are stored in order_id order, with 0 descents (`physical_order_sorted`). order_id equals the rank of order_time (0 mismatches).

## 2. Event catalog

Hierarchy: **customer → order → pizza line**, with **runner** on the order. Each order follows one of two lifecycles. 8 orders go placed → picked up → delivered, and 2 go placed → cancelled.

| Event | Owner | Time | Attributes | Source rows | Count |
|---|---|---|---|---|---:|
| `pizza_ordered` | order_id | order_time | customer_id, pizza_id, exclusions `opt(text)`, extras `opt(text)`, src_row | customer_orders, one per row | 14 |
| `order_picked_up` | order_id | pickup_time | runner_id | runner_orders rows with pickup_time | 8 |
| `order_delivered` | order_id | **rule:** pickup_time + duration minutes | runner_id, distance `text`, duration `text` (verbatim) | the same 8 rows | 8 |
| `order_cancelled` | order_id | **rule:** the order's order_time | runner_id, cancellation `text` | runner_orders rows with cancellation | 2 |

**32 events.** Owner = order_id gives 10 partitions.

| Entity | Key / ext_id | Columns | created_at | Count |
|---|---|---|---|---:|
| `runners` | runner_id | — | registration_date 00:00:00 | 4 |
| `pizzas` | pizza_id | pizza_name, toppings `text` (verbatim, `"1, 2, 3, …"`) | first event | 2 |
| `toppings` | topping_id | topping_name | first event | 12 |
| `customers` | customer_id | — | first order_time | 5 |

**4 entities.** Not entities:
- **Orders.** An order is just the shared order_id of its lines and its runner row, with no columns of its own except customer and time, which are on the lines. It is the event owner, not a table.
- **Recipe lines and topping tokens.** They stay as the source's comma text, because the questions split that text themselves.
- **The clean_* and get_* tables.** They are views (§3).

The pickup/duration/cancellation columns map onto the lifecycle cleanly:
- The NULL pattern of (pickup, distance, duration, cancellation) is exactly two-valued: (set, set, set, NULL) on 8 rows and (NULL, NULL, NULL, set) on 2 (`03_lifecycle.py`). No row is both picked up and cancelled.
- The pickup always follows the order: 0 pickups before order_time. Order → pickup: min 10.03, median 13.03, max 29.28 minutes.
- Two pickups fall after midnight on the next day (orders 3 and 8).
- No runner picks up an order before its own previous delivery ends (0 overlaps, taking delivery = pickup + duration).
- Neither cancelled order has a pickup, so a cancellation time is not in the data (rule above).
- Both cancelled orders still have a runner (6 → runner 3, "Restaurant Cancellation"; 9 → runner 2, "Customer Cancellation"). So assignment happens before cancellation. No assignment time exists, so there is no separate `runner_assigned` event; runner_id rides on the pickup or cancel event.

Registration dates (`03_lifecycle.py`):
- Runners registered on 2021-01-01, 01-03, 01-08 and 01-15, i.e. days 0, 2, 7 and 14.
- Every assigned order comes after its runner's registration (0 before). Days from registration to first pickup: 0, 1, 0.
- **Runner 4 registers on 2021-01-15, after the last event** (last delivery 2021-01-11 19:00:20). As an entity created_at, that pushes the snapshot time N to at least 2021-01-15 00:00:00.

## 3. Rebuild rules and blockers to an exact round trip

Views (DuckDB over the Parquet):

- **customer_orders** = `pizza_ordered` in event order (order_time, src_row): order_id, customer_id, pizza_id, exclusions, extras, order_time as `%Y-%m-%d %H:%M:%S`. Every time is 19 characters with no fraction (22/22).
- **clean_customer_orders = customer_orders, byte for byte.** 0 row-wise differences by rowid including storage type, and 0 multiset differences (`02_derived_exact.sql`). In this copy, "cleaning" changed nothing, because the `'null'`/`''` dirt it was written to remove is already NULL.
- **runner_orders** = for delivered orders, picked_up ⋈ delivered: (order_id, runner_id, pickup_time, distance, duration, NULL). For cancelled ones: (order_id, runner_id, NULL, NULL, NULL, cancellation). distance and duration are TEXT, kept verbatim.
- **clean_runner_orders = f(runner_orders), proven exact:**
  - `distance = coalesce(CAST(distance AS REAL), 0.0)` and `duration = coalesce(CAST(duration AS REAL), 0.0)`. SQLite's CAST reads the longest numeric prefix: `'13.4km'`→13.4, `'32 minutes'`→32.0, `'23.4 km'`→23.4.
  - pickup_time and cancellation are copied unchanged.
  - Result: 0 row-wise differences, including type REAL on all 10 rows. The "keep NULL" variant without coalesce differs on 2 rows: **the cleaner wrote 0.0, not NULL, for the cancelled orders.**
  - **DuckDB blocker:** `CAST('20km' AS DOUBLE)` is a Conversion Error in DuckDB, and `TRY_CAST` gives NULL (checked with the duckdb CLI). The view must use `CAST(regexp_extract(distance, '^[0-9]+(\.[0-9]+)?') AS DOUBLE)` and coalesce to 0.0. The parsed values are exact (13.4 and 23.4 parse to the same double).
- **get_extras / get_exclusions = f(customer_orders), proven exact** on all 6 + 4 rows (`02_derived_exact.sql`). The rule:
  1. Split every non-NULL list on `,`, trim, and cast to INTEGER, remembering (source row, position).
  2. Output one row per **distinct (order_id, topping)**.
  3. Set `row_id` = the rank of that topping's first appearance within the order.
  4. Set `extras_count` / `total_exclusions` = the number of **token occurrences in the whole order**, not per topping and not distinct.
  - Example: order 4's three lines each exclude `4`. That gives **one** get_exclusions row `(1, 4, 4, 3)`.
  - Example: order 10's `'2,6'` gives `(1,10,2,2)` and `(2,10,6,2)`.
  - The "distinct" step is only visible in exclusions (6 tokens → 4 rows). Extras have 6 tokens and 6 distinct pairs.
  - The rank needs the line order within an order. That is the `src_row` ord, which also gives seq.
- **pizza_names, pizza_recipes** from `pizzas`, **pizza_toppings** from `toppings`, **pizza_runners** from `runners` (`strftime(created_at, '%Y-%m-%d')`).

Blockers and rules:
1. **Comma lists are byte-exact text.** Customer lists use `','` with no space (0 lists contain a space). Recipes use `', '` (7 and 5 separators). Keep both as `text`, never as arrays, or the questions' INSTR/TRIM splitting and the views' byte comparison break.
2. **Unit text is free-form:** distance patterns `Nkm` ×5, `N` ×2, `N km` ×1; duration `N minutes` ×2, `N mins`, `Nmins`, `N minute`, `Nminutes`, `N` ×2. It must be stored verbatim. A stage-2 generator must draw the *format* as a categorical too, or the clean_* rule loses its point.
3. **Delivery time is derived, not given:** pickup + duration minutes. Every duration is a whole number of minutes. The source has no delivery timestamp, so this is a rule. It is also the only place a duration text gets parsed during ingest.
4. **Cancellation time is not in the source.** The rule is the order's order_time, after its lines, by block position. Capped at N.
5. **Duplicate lines** (order 4, rows 5–6) are two events. The tables compare as multisets, so this is fine.
6. **Snapshot N ≥ 2021-01-15** (runner 4's registration). Otherwise an entity is created after N.
7. REAL columns compare by value: 20.0 vs 20 is not an issue.

Expected verdict: **exact round trip feasible**. All 10 tables come from 32 events and 4 entities. 4 tables are pure views of the others.

## 4. Measured quirks

- Missing values are real NULLs (0 `'null'`/`''`/`'\N'`), unlike the original case (§0). `clean_customer_orders` is therefore a no-op copy.
- clean_runner_orders turns the cancelled orders' missing distance and duration into **0.0** (2 rows). Any "average distance" over the clean table that does not filter cancellations is biased: 8 real values plus two zeros.
- **Speed outlier.** Order 8 covers 23.4 km in 15 minutes, which is **93.6 km/h**. The other speeds are 35.1–60.0 km/h, mean 51.36 overall (`03_lifecycle.py`). This is a classic course-data planted anomaly.
- **Extras already in the recipe.** 5 of 6 extra tokens are toppings the pizza already has, which produces local073's "2x" rows: 3 lines. The exception is order 7: a Vegetarian with extra Bacon. All 6 exclusion tokens are in the recipe (`02_derived_exact.sql`, `token_in_recipe`).
- **Fingerprint: about 10 minutes of prep per pizza.** Order → pickup gap ÷ pizzas = 10.53, 10.03, 10.62, 9.76, 10.47, 10.27, 20.48, 7.76 minutes. 6 of 8 fall within 10 ± 0.7.
- Names: `Meatlovers` (one word). local065 says "Meat Lovers", and local073 says to map pizza_id 1 to 'Meatlovers'.
- order_time seconds are never `00`, and times are typed to the second.

## 5. Distributions to fit (stage 2)

n = 10 orders, so nothing here is a fit, only a shape. Measured in `03_lifecycle.py` and `01_inventory.sql`:

- **Arrivals.**
  - 10 orders over 10.02 days (2021-01-01 18:05 → 01-11 18:34).
  - Hours: 11, 13, 18×2, 19, 21×3, 23×2, so evening-heavy. Weekday: Fri 5, Sat 2, Mon 2, Sun 1.
  - Inter-order gaps in hours: 0.93, 28.84, 37.54, 103.61, 0.05, 0.29, 26.57, 11.47, 31.2 (median 26.57). That is bursty: three orders within 20 minutes on 01-08.
- **Basket.** Pizzas per order: 1→7, 2→2, 3→1 (14 lines). Mix: Meatlovers 10, Vegetarian 4. Lines with exclusions: 5/14. With extras: 4/14. Tokens per list: 1–2.
- **Lifecycle.** Delivered 8/10, cancelled 2/10 (1 restaurant, 1 customer).
  - Prep (order → pickup) is about 10 min × pizzas (§4).
  - Duration: 10–40 min, median 22.5, integer. Distance: 10–25 km, median 20.
- **Runners.** Registration is weekly-ish (days 0, 2, 7, 14). Orders go to 3 of 4 runners (4, 4, 2). Registration → first pickup: 0–1 days.
- **Customers.** 5 customers, 1–3 orders each.

## 6. simkit mapping sketch

```python
p.entity("runners", key="runner_id", cols={"ext_id": text(doc="Source runner_id")})   # created_at = registration_date
p.entity("pizzas", key="pizza_id", cols={"ext_id": text(), "pizza_name": text(),
         "toppings": text(doc="Recipe: comma+space list of topping ids, verbatim")})
p.entity("toppings", key="topping_id", cols={"ext_id": text(), "topping_name": text()})
p.entity("customers", key="customer_id", cols={"ext_id": text()})
p.event("pizza_ordered", cols={"order_id": i64(), "customer_id": ref("customers"), "pizza_id": ref("pizzas"),
        "exclusions": opt(text(doc="Comma list, no spaces, verbatim")), "extras": opt(text()),
        "src_row": i64(doc="Source rowid: the line order within an order")})
p.event("order_picked_up", cols={"order_id": i64(), "runner_id": ref("runners")})
p.event("order_delivered", cols={"order_id": i64(), "runner_id": ref("runners"),
        "distance": text(doc="Verbatim, e.g. '20km', '23.4 km'"), "duration": text(doc="Verbatim, e.g. '32 minutes'")})
p.event("order_cancelled", cols={"order_id": i64(), "runner_id": ref("runners"),
        "cancellation": cat("Restaurant Cancellation", "Customer Cancellation")})
```

- Ingest blocks:
  - `-- event: pizza_ordered owner=order_id ord=src_row` … `ORDER BY order_time, rowid`.
  - `order_picked_up owner=order_id` `ORDER BY pickup_time`.
  - `order_delivered owner=order_id` with `datetime(pickup_time, '+' || CAST(duration AS INTEGER) || ' minutes')` `ORDER BY 1`.
  - `order_cancelled owner=order_id` at the order's `min(order_time)`.
  - Block position puts lines before the cancel at equal times.
  - Entities `ORDER BY` the integer id. The `runners` created_at is `registration_date || ' 00:00:00'`.
- Views: as in §3. clean_customer_orders is `SELECT * FROM` the customer_orders view. get_* use `string_split` + `unnest` with the list position, `row_number()` over the first appearance, and `count(*) OVER (PARTITION BY order_id)` on the tokens.
- Saved queries: local065, local066 (the `_a` reading, not the gold SQL), local073. Keep line order: local073's row id is the source row.
- Stage 2:
  - The owner `order` is a short machine: `placed` → timer ≈ 10 min × pizzas → `picked_up` (runner chosen from those registered) → timer = duration → `delivered`. A branch with p ≈ 0.2 goes to `cancelled`.
  - Runners are a Source with weekly registrations.
  - Laws:
    - `lifecycle(order_id, {None: {pizza_ordered}, pizza_ordered: {pizza_ordered, order_picked_up, order_cancelled}, order_picked_up: {order_delivered}})`
    - a runner is registered before its first order
    - a runner does not overlap with itself (holds in the data, 0 overlaps)
  - Do **not** add a speed cap law: order 8 breaks it at 93.6 km/h.
- Volume: 32 events + 23 entity rows; the round trip is instant.

## 7. Open questions and risks

- **Tiny.** Ten orders cannot support any fitted distribution. This dataset is a round-trip and parsing harness test: free-form unit text, comma lists, derived split tables, NULL vs 0.0. It is not a behavioural reference.
- Are the 0 `'null'` strings in this copy stable across Spider2 releases? If a future copy restores the original `'null'`/`''` dirt, clean_customer_orders stops being a copy. The clean rule then needs `NULLIF(NULLIF(x,'null'),'')`, and the events must keep the raw text verbatim. The pack above already does, because exclusions and extras are `text`.
- get_* `row_id` ordering is ambiguous. "First appearance" and "ascending topping id" agree on every multi-token order here: 3 multi-token lists on 2 rows (`'1,5'`, `'2,6'`, `'1,4'`), all ascending. `02_derived_exact.sql` counts the rows as `tokens_ascending_in_list`, and its `get_*_rows` output shows the ranks. Pick one and record it.
- Cancellation and delivery times are rules, not data. Stage 2 must not fit "time to cancel".
- Should `orders` be an entity (owner key + customer + created_at) rather than a bare i64 owner? It would make `ref` checks possible on runner events, at the cost of one more rebuilt-nothing table.
- local066's gold SQL and two of its three accepted CSVs disagree with the natural reading. Use `_a` as the saved query's expected answer.

## Other modern_data tables (out of scope): event-shaped?

From `05_others.sql`:
- **companies_dates** (1 085 rows, 1 074 companies): No. A unicorn snapshot. `date_joined` (2007–2022) is one date per company, at most a single `joined` event, not a log.
- **companies_funding** (1 085): No. A static valuation/funding snapshot per company.
- **companies_industries** (1 085, 15 industries): No. A static dimension.
- **trees** (690 626 rows, 683 788 tree_ids): No. A NYC tree census snapshot with no time column.
- **income_trees** (220 rows, 216 zipcodes): No. A census income lookup by zipcode.
- **statistics** (1 010 rows, 4 states, 285 dates 2020-02-01..11-11): Partly. Daily cumulative COVID cases and deaths per state: an aggregate time series, not events.
- **word_list** (373 804 words): No. A word list.

## Summary

1. **Feasible:** yes. All 10 pizza tables rebuild exactly. clean_customer_orders is a byte-identical copy, and clean_runner_orders, get_extras and get_exclusions are proven exact functions of the raw tables.
2. **Project:** `pizzarunner` (modern_data, the pizza_* tables). Saved queries: local065, local066 (`_a`), local073.
3. **Events:** 4 types, 32 rows: pizza_ordered 14, order_picked_up 8, order_delivered 8 (pickup + duration rule), order_cancelled 2 (order_time rule).
4. **Entities:** 4 tables, 23 rows: runners 4, pizzas 2, toppings 12, customers 5.
5. **Hardest blocker:** the DuckDB views must re-derive the clean and split tables from verbatim free-form text: `'20km'` and `'32 minutes'` (DuckDB cannot CAST them; use a regexp prefix and coalesce to 0.0), and comma lists split into distinct (order, topping) rows ranked by first appearance. Snapshot N must reach runner 4's registration on 2021-01-15.
