# Oracle SQL / Practical Oracle SQL (Spider 2.0-lite): reverse-engineered event log

Source: `data/spider2/oracle_sql.sqlite`, opened read-only. `scripts/oraclesql/rq.py` copies the file into an in-memory SQLite and runs named blocks, so the file itself is never written.

Every number below comes from one of these scripts:
- a named query in `scripts/oraclesql/q*.sql` or `e1_events.sql`;
- `t1_typeof.py`, which reports storage classes, NULL / `''` / `'\N'` counts and text shapes;
- `u1_upstream.py`, which compares every table with the book's own INSERT script;
- `u2_chapters.py`, which lists the book chapters that use each table;
- `d1_dists.py`, which gives distributions and the broken-view check.

Raw outputs are in `scripts/oraclesql/out_*.txt`. A reference like `[q2:inventory_vs_purchase]` means file `q2_brewery.sql`, block `-- name: inventory_vs_purchase`. Gold CSVs and the question's `calculation_method.md` are in `scripts/oraclesql/gold/`.

The upstream repository was downloaded to a scratch directory outside the repo and is not committed. It is `Apress/practical-oracle-sql`, branch `master` (last push 2020-02-24), and `practical_fill_schema.sql` has sha256 `b28b86ab…f03f` [u1].

## 0. What this catalog is

- **Dataset.** This is the `PRACTICAL` demo schema from Kim Berg Hansen's book ***Practical Oracle SQL*** (Apress, 2020), built from `practical_fill_schema.sql` in `Apress/practical-oracle-sql`. The data is a fictional craft-beer trading company: breweries, beers, purchases, warehouse inventory, customer orders, FIFO picking, a webshop's page counters and visits, server heartbeats, a stock ticker and an org chart.
- **Evidence.**
  - All 33 non-empty tables equal the book script's INSERTs as multisets, row for row: 33 of 38 tables, 0 differing rows [u1].
  - The only differences are in rowid order. The 6 tables with an `INTEGER PRIMARY KEY` (customers, purchases, favorites, reviews, inventory, employees) are stored in key order, not insert order [u1].
  - `locations` is the book's generated grid: 2 warehouses × aisles A–D × positions 1–32, with `id = row_number()`. A rebuild of that grid gives 0 differing rows [q3:locations_is_grid].
  - Every table but 7 is used by a chapter script: ch04 packaging, ch13 FIFO picking, ch15 forecasting, ch16 minimums, ch17 ticker, ch18 heartbeats/visits, ch19 hire periods, and so on [u2]. The 7 unused ones are `product_groups`, `locations`, `web_counter_hist`, `picking_line`, `id_name_type`, `id_name_coll_entries` and `favorite_coll_type`.
- **What Spider's conversion changed:**
  - **Oracle TYPEs became empty tables.** `id_name_type`, `id_name_coll_type`, `favorite_coll_type` and an invented `id_name_coll_entries` are `create type … as object / as table of` upstream. Here they are 4 tables with 0 rows [t1, u1].
  - **`emp_hire_periods.start_date` / `end_date` were renamed `start_` / `end_`.** The copied view `emp_hire_periods_with_name` still names `start_date`, so it fails with `no such column: ehp.start_date` [d1].
  - **`conway_gen_zero` is empty, as it is upstream.** Chapter 6 fills it at run time [u2].
  - **11 views are carried over, rewritten for SQLite.** One example is `customer_order_products_obj`, which builds JSON text with GROUP_CONCAT in place of an Oracle collection, with no ORDER BY [q3:customer_order_products_obj_sample]. 10 of the views run [q3:views_run].
- **Row counts** [t1]:
  - monthly_sales 360, locations 256, purchases 180, web_counter_hist 120, inventory 113, picking_log 63, monthly_budget 48;
  - web_page_visits 23, picking_line 21, orderlines 18, emp_hire_periods 15, ticker 15, employees 14, server_heartbeat 14, packaging_relations 12, packaging 11;
  - orders, products and product_alcohol 10 each; 4 each in customers, product_groups, web_pages, customer_favorites and customer_reviews; breweries 3;
  - 2 each in web_devices, web_demographics, channels_dim, gender_dim, product_minimums and picking_list; stock and web_apps 1 each;
  - 5 empty tables.
  - **Total 1,350 rows in 38 tables.**
- **Licence.** The repository's `LICENSE.txt` is a "Freeware License, some rights reserved", © 2020 Kim Berg Hansen. Personal use is allowed. Commercial reuse, and use in "a user's educational materials such as books or blog articles", needs prior permission. GitHub reports `NOASSERTION`. **Not redistributable**: keep a local copy only.
- **Nature.** This is **hand-made and scripted course data**, not real. It carries generator fingerprints (§4): exactly 5 purchases every month, purchase days set by a formula, and yearly purchase totals in whole hundreds.

### Sub-catalogs

The tables fall into four groups that share no keys [q1:fk_orphans, e1:subcatalog_rows]:

| Group | Tables | Rows | Window |
|---|---|---:|---|
| **Brewery trading** | product_groups, products, product_alcohol, product_minimums, breweries, purchases, locations, inventory, customers, customer_favorites, customer_reviews, orders, orderlines, monthly_sales, monthly_budget, packaging, packaging_relations | 1,049 | 2016-01-01 .. 2019-03-29 (budgets to 2019-12) |
| **Warehouse staff & picking** | employees, emp_hire_periods, picking_list, picking_line, picking_log | 115 | hires from 2010-07-01; picking 2019-01-16..19 |
| **Web analytics** | web_apps, web_pages, web_counter_hist, web_page_visits, server_heartbeat, web_devices, web_demographics, channels_dim, gender_dim | 170 | 2019-04-01 .. 2019-05-02 |
| **Stock ticker** | stock, ticker | 16 | 2019-04-01 .. 04-19 |
| empty | conway_gen_zero, id_name_type, id_name_coll_type, id_name_coll_entries, favorite_coll_type | 0 | – |

Picking joins the brewery group through orders, products and locations. The web and ticker groups are islands.

**Proposal: one dataset, `oraclesql`, holding all 38 tables.** The reasons:
1. It is one source file and one Spider db, and the contract's `results/` holds every source table of the file.
2. All 8 questions fall in the brewery and picking groups. Split off, the web and ticker datasets would be 170 and 16 rows with 0 questions each, which only multiplies files. The same call was made for `weblog`.
3. The groups do not conflict. They have different entity types, ids that never collide inside one type, and windows that can share one log.

The fallback, if stage 2 wants worlds kept apart, is `oraclesql` (brewery + picking, the 8 questions) plus `oraclesql_web` (web + ticker). The cut is clean: 0 FKs cross it [q1:fk_orphans].

## 0.1 How Spider 2.0 uses it

Eight questions use db `oracle_sql`. None has gold SQL; each has 1–3 exec_result CSVs (`gold/`).

| id | asks | gold SQL? | gold value | reproduced |
|---|---|---|---|---|
| local269 | average leaf quantity per top-level packaging after recursive expansion | no (CSV `_a`) | 946.0 | ✔ 946.0 = avg(864, 720, 960, 1240) over the 4 pallets [q4:local269_avg_leaf_total] |
| local270 | top-level containers with an item whose nested total is > 500 | no (`_a`, `_b`) | 4 rows: Pallet of L / Bottle 500cl 864, Pallet Mix SG / 500cl 856, Pallet of M / 330cl 720, Pallet Mix MS / 500cl 600 | ✔ exactly [q4:local270_top_items_over_500] |
| local272 | order 423: FIFO pick locations and quantities "in warehouse 1" | no (`_a`) | 6520 A16 22; 4280 B3 30; 4280 C20 30; 6520 D9 18 | ✔ but only as **`picking_line` for order 423**: 3 of its 4 locations are in **warehouse 2** [q4:local272_order423_from_picking_line]. A literal warehouse-1 FIFO gives 5 other rows [q4:local272_fifo_warehouse1] |
| local273 | average pick percentage per product name, FIFO | no (`_a`) | `4280, 0.0` / `6520, 0.0` (names are ids; a degenerate gold) | not attempted |
| local274 | products picked for order 421 and average units per pick (FIFO) | no (`_a`, `_b`) | Hoppy Crude Oil 36.67 (3 picks, 110), Der Helle Kumpel 23.33 (6 picks, 140) | ✔ exactly, from `picking_line` [q4:local274_order421_avg_picked] |
| local275 | products whose sales/CMA ratio stays > 2 in every month of 2017 | no (`_a`) | empty (header `output` only) | ✔ empty. The best is 3 of 12 months (4160, 7790) [q4:local275_cma_ratio_over_2_all_2017] |
| local277 | average 2018 forecast for 4160 and 7790 (CMA seasonality + regression) | no (`_a`, `_b`, `_c`) | 277.3343 / 266.2247 / 417.4506: three variants | not attempted (ambiguous) |
| local279 | recursive monthly inventory with restock below the minimum; 2019 month of minimum gap | no (`_a`) | 6520 2019-01-01 330.0; 6600 2019-01-01 76.0 | not reproduced (the model is underspecified) |

The questions need packaging verbatim, `picking_line` with `locations` (local272, local274), `monthly_sales` as stored (local275, local277), and inventory, purchases, minimums and budget (local279). All of it is table content, and none depends on tie order.

## 1. Inventory, keys, joins

Every declared PK and UNIQUE holds, and every declared FK resolves: 34 FK checks, 0 orphans [q1:key_uniqueness, q1:fk_orphans]. These implied joins also hold with 0 misses:
- `inventory.product_id` = its purchase's product;
- `picking_line (order, product)` ∈ orderlines;
- a `picking_log` P row's location = its pick line's location [q1:fk_orphans].

| Table | Rows | Key | Kind |
|---|---:|---|---|
| purchases | 180 | id 601..780, dense, in date order (179 of 179) | activity: a brewery delivery [q1:id_ranges, q1:purchase_id_vs_date] |
| inventory | 113 | id 1148..1484, step exactly 3; location_id is unique | **state**: lots on shelves, one lot per location [q1:inventory_id_steps, q1:key_uniqueness] |
| orders / orderlines | 10 / 18 | ids 421..430 / 9120..9299 (gappy); (order, product) unique | activity |
| picking_list / line / log | 2 / 21 / 63 | id; (list, line_no); (list, log_time) | activity, with the log to the second |
| monthly_sales | 360 | (product, mth): 10 products × 36 months, full grid | pre-aggregated [q2:monthly_sales_grid] |
| monthly_budget | 48 | (product, mth): 2 products × 24 months 2018–2019 | plan [q2:monthly_budget_grid] |
| emp_hire_periods | 15 | (emp, start_); 7 open (end_ NULL) | intervals (6 employees) |
| web_counter_hist | 120 | (app, page, day): 4 pages × 30 days, no gaps | cumulative counter snapshot [q3:counter_days_complete] |
| web_page_visits | 23 | none declared; (ip, time) unique | activity |
| server_heartbeat | 14 | (server, beat_time) | activity |
| ticker | 15 | (symbol, day) | daily price |
| web_devices / web_demographics | 2 / 2 | day | pre-aggregated daily |
| products, product_groups, breweries, customers, employees, packaging, packaging_relations, web_apps, web_pages, stock, channels_dim, gender_dim | 10, 4, 3, 4, 14, 11, 12, 1, 4, 1, 2, 2 | id / composite | masters |
| product_alcohol, product_minimums, customer_favorites, customer_reviews | 10, 2, 4, 4 | product or customer id | 1:1 attribute tables (10/10, 2/10, 4/4, 4/4) [e1:one_to_one_folds] |
| locations | 256 | id; (warehouse, aisle, position) | **derived**: a generated grid [q3:locations_is_grid] |

Coverage [q1:coverage, q1:products_by_brewery]:
- Every product is bought from exactly one brewery, 18 times each.
- Only 62 of 180 purchases have inventory, and only 113 of 256 locations hold stock.
- 6 products are ordered. 3 of 4 customers order; customer 51007 has none and NULL lists.
- 3 orders are picked (421–423). Only 6 of 14 employees have hire periods.
- Every packaging takes part in a relation: 9 are containers, 7 are contents.

**Copies and derived tables.**
- `locations` is the only derived table. It is a pure grid with 0 differing rows [q3:locations_is_grid].
- **No other table is a function of another.** The `monthly_orders` view (2019, from orders) shares no month with `monthly_sales`, which ends in 2018 [q2:monthly_orders_view_vs_sales].
- Inventory is not purchases minus sales (§4).
- `web_devices` and `web_demographics` agree on each day's total (3,464 and 4,228), but split it along different axes, so neither rebuilds the other [q3:devices_vs_demographics_totals].
- This catalog is not a copy of any batch-1 or batch-2 dataset.

## 2. Event catalogue

Snapshot **N = 2019-05-02**, the last observed time (`web_devices.day`) [e1:snapshot_N]. Times are dates, or `YYYY-MM-DD HH:MM[:SS]`, read as UTC.

| # | Event | Owner (ord) | Time | Natural? | Attributes | Source | Count |
|---|---|---|---|---|---|---|---:|
| E1 | `purchase_received` | brewery (ord = id) | `purchased` | natural | purchase_id, product_id ref, qty i64, cost amount | purchases | 180 |
| E2 | `lot_stored` | product (ord = id) | its purchase's `purchased` | **rule** | inventory_id, location_id i64, purchase_id i64, qty i64 | inventory | 113 |
| E3 | `monthly_sales_reported` | product (ord = product) | `mth` (period start) | reported, no finer grain | mth, qty | monthly_sales | 360 |
| E4 | `budget_set` | product | Jan 1 of `mth`'s year | **rule** | mth, qty | monthly_budget | 48 |
| E5 | `order_placed` | customer (ord = id) | `ordered` | natural | order_id | orders | 10 |
| E6 | `order_line_added` | customer (ord = orderline id) | = E5 | natural (inherited) | orderline_id, order_id, product ref, qty, amount | orderlines | 18 |
| E7 | `picklist_created` | employee picker (ord = id) | `created` | natural | picklist_id | picking_list | 2 |
| E8 | `pick_line_planned` | picker (ord = line_no) | = E7 | **rule** | picklist_id, line_no, location_id, order_id, product ref, qty | picking_line | 21 |
| E9 | `picker_arrived` | picker | `log_time` | natural | picklist_id, location_id opt | picking_log A | 21 |
| E10 | `line_picked` | picker | `log_time` | natural | picklist_id, location_id, pickline_no | picking_log P | 21 |
| E11 | `picker_departed` | picker | `log_time` | natural | picklist_id, location_id opt | picking_log D | 21 |
| E12 | `hire_period_started` | employee | `start_` | natural | title | emp_hire_periods | 15 |
| E13 | `hire_period_ended` | employee | `end_` | natural | start_ (link) | end_ not NULL | 8 |
| E14 | `page_counter_read` | web_page (ord = day) | `day` | reported (daily cumulative) | counter i64 | web_counter_hist | 120 |
| E15 | `page_visited` | client_ip text (ord = rowid) | `visit_time` | natural | web_page ref | web_page_visits | 23 |
| E16 | `heartbeat_received` | server text | `beat_time` (minute) | natural | – | server_heartbeat | 14 |
| E17 | `device_counts_reported` | web_app 542 (ord = day) | `day` | reported | pc, tablet, phone | web_devices | 2 |
| E18 | `demographics_reported` | web_app 542 (ord = day) | `day` | reported | 8 count/qty columns | web_demographics | 2 |
| E19 | `price_quoted` | stock | `day` | natural (weekday close) | price f64 | ticker | 15 |
| E20 | `customers_snapshot` | customer | N | **rule** | favorite_list opt, review_list opt | favorites + reviews | 4 |
| E21 | `employees_snapshot` | employee | N | **rule** | title, supervisor_id opt ref | employees | 14 |
| E22 | `products_snapshot` | product | N | **rule** | qty_minimum, qty_purchase | product_minimums | 2 |

**22 event types, 1,034 events** [e1:event_counts]:
- **348 natural** (34%);
- **484 reported** at a period date (monthly sales, counters, the 2+2 web aggregates);
- **202 rule-timed**: lots, budgets, planned pick lines and the 20 snapshot rows.

Entities (12 types, 68 rows) [e1:entity_counts]:
- product_groups 4 and products 10, with product_alcohol folded in (10 of 10 rows) as `sales_volume` and `abv`;
- breweries 3;
- customers 4, with the two list tables carried by E20;
- packaging 11;
- packaging_relations 12 (ext_id `"<packaging>:<contains>"`, both ends refs);
- employees 14;
- web_apps 1, web_pages 4 (ext_id `"<app>:<page>"`), stock 1, channels_dim 2 and gender_dim 2.

`created_at` rules:
- employees use their first `start_` (6 of 14: 2010-07-01..2014-10-01) [e1:employee_created_at]. The other 8 take the brewery start, 2016-01-01, by rule;
- every other master takes **2016-01-01**, the first purchase [q2:date_ranges];
- web and ticker masters could take 2019-04-01 instead. The choice is cosmetic.

What is **not** an entity, and why:
- **locations** is derived: build.sql generates the grid. `location_id` travels as a plain i64.
- **purchases, orders and picking lists** are events, not entities. `inventory.purchase_id` and `picking_line.order_id` are i64 links, not refs.
- **employees.title and supervisor_id** are snapshot columns. 142 has been "Managing Director" only since 2012-04-01 but was created 2010-07-01. Employee 145 has two open periods (IT Developer + Scrum Master), and the table keeps one of them. 8 employees have no periods at all [q2:employees_title_vs_open_period]. A creation event would carry a future value.
- **Favourites and reviews** have no time, so they are snapshot lists, not review events.
- **The 5 empty tables and the 11 views** produce no entity and no event.

## 3. Rebuild rules and blockers to an exact round trip

1. **Numbers are clean** [q3:real_columns_integral, t1]:
   - Every REAL column except two is integral: `cost`, `amount`, every `qty`, and the minimums. Carry them as `i64`, or `amount()` for money. They compare by value with the REAL source.
   - The exceptions are `product_alcohol.abv` (halves: 4.0–8.5) and `ticker.price` (tenths: 13.7–15.7). They go as `f64` verbatim; the shortest JSON form reads back exactly.
   - INTEGER columns hold only integers. No mixed columns exist.
2. **Text times** [q2:dates_valid]:
   - Dates are `YYYY-MM-DD`, valid in every row. They are purchased, mth (always day 01), ordered, start_/end_, day.
   - Datetimes are `YYYY-MM-DD HH:MM:SS` (picking, visits).
   - **`server_heartbeat.beat_time` has no seconds** (`YYYY-MM-DD HH:MM`, 14 of 14). Its view must format with `%Y-%m-%d %H:%M`.
   - `web_devices.day` and `web_demographics.day` have **no declared type**, so their results column is string. The value is still `YYYY-MM-DD` text.
3. **NULL vs empty** [t1]:
   - There is no `''` and no `'\N'` anywhere.
   - The NULLs are: `orders.delivery` all 10, `customer_favorites` / `customer_reviews` 1 each (customer 51007), `employees.supervisor_id` 1, `emp_hire_periods.end_` 7, and `picking_log.location_id` 4 / `pickline_no` 42.
   - `orders.delivery` rebuilds as a constant NULL. `end_` rebuilds as a LEFT JOIN on E13.
4. **Derived:** `locations` = `row_number() over (order by w, a, p)` over 2 × {A, B, C, D} × 1..32. This is proven, with 0 rows differing either way [q3:locations_is_grid].
5. **Folded 1:1 tables:**
   - `product_alcohol` rebuilds from the products entity (10 of 10);
   - `product_minimums` from E22 (2 rows);
   - `customer_favorites` / `customer_reviews` from E20, all 4 customers, NULL lists kept [e1:one_to_one_folds].
6. **Duplicates and order.**
   - No table has duplicate rows. The tie-free keys are measured: no two purchases share a day, no two orders share a day, and no two visits share a second [e1:time_ties].
   - Three heartbeat minutes are shared by both servers; they are separate owners.
   - E1 and E2 share a timestamp. E2 sorts after E1 by block position.
   - The P→P pairs in `picking_log` (two lines picked at one location) are 6–8 s apart, never equal [q2:picking_log_gaps].
7. **Rule times.** These rows have no time of their own, and each takes one from a stated rule:
   - inventory lots take their purchase's date;
   - budgets take Jan 1 of their year;
   - pick lines take the picklist's `created`;
   - the 20 snapshot rows take N.
8. **Ordering.** Picking events are carried at their own seconds. No question depends on rowid order, and all 6 INTEGER-PK tables are in key order [u1].

**Verdict: exact, with no real blocker.** Every value is an integer, a halves/tenths f64, verbatim text or a stated rule.

## 4. Measured quirks

- **Inventory is a frozen state, not a ledger.**
  - Every one of the 62 stocked purchases is stocked whole: Σ lot qty = purchase qty in 62 of 62 [q2:inventory_vs_purchase]. These are the purchases of 2017-12-19..2018-12-29 [q2:inventory_purchase_dates]. Older purchases (2016-01-01..2017-12-15) have no stock at all [q2:purchases_without_inventory_dates].
  - Yet 2018 recorded 3,659 units of monthly sales against 4,000 bought, while all 4,000 sit in inventory [q5:sales_2018_vs_lots_2018].
  - Each picklist **on its own** fits the inventory (841: 0 overdrawn, 8 emptied; 842: 0 overdrawn, 8 emptied) [q5:picklist_alone_vs_inventory]. **Both together overdraw 9 of 10 locations** [q5:both_picklists_vs_inventory].
  - So the two picklists are alternative book examples drawn against the same stock. Neither one decremented it.
- **Lot rule:** each purchase is split into ⌊qty/48⌋ cases of 48 plus one remainder lot. This holds for 59 of 62 purchases [q5:lot_split_rule]. The 3 exceptions are all product 6520, the FIFO example's beer [q5:lot_split_misses]:
  - purchase 729 is split 24+20+14+14 (2 of those ids, 1316 and 1433, sit out of the id sequence) [q3:inventory_id_breaks];
  - purchases 749 and 769 are single lots of 70 and 72.
- **Purchase generator fingerprints:**
  - Exactly **5 purchases in each of the 36 months** [d1].
  - Each product is bought every other month, 18 times [q2:purchase_months_per_product].
  - Day of month = product rank (1..10) + 10·(year − 2016), clipped to the month's end. This holds for 176 of 180 purchases; the 4 misses are product 7950's 2018 purchases on the 31st [q5:purchase_day_rule, q5:purchase_day_rule_misses].
  - **Every product-year total is a multiple of 100** (30 of 30) [q5:yearly_purchase_totals_round].
  - Unit cost is near-constant within a product-year and jumps between years: for example, 4040 costs 7.45–7.54 in 2016, 5.85–5.94 in 2017 and 8.00 in 2018 [q2:unit_cost_by_year].
- **monthly_sales has no link to purchases** beyond roughly tracking them: bought − sold per product-year runs −5..90 [q2:purchases_vs_monthly_sales_by_year]. 17 zero months, 13 of them Reindeer Fuel (4160), a winter seasonal with a peak of 247 in 2018-02 [q3:monthly_sales_zero, q5:monthly_sales_zeros_by_product, q5:monthly_sales_max].
- **Budgets are step functions.** 6520 runs 30…50…30 in 2018 and 45…60…40 in 2019. 6600 is 6 every month of 2018 and 20 every month of 2019 [d1].
- **Order prices vary per line.** For example, 4280 costs 21.39–24.67 per unit; 6600 and 7950 are constant [q2:orderline_unit_price]. Amounts are whole numbers.
- **Picking is 2 lists in 4 days.** A list is created 1.6–2.7 days after its orders [d1]. Each log runs `D (no location) → (A P+ D)* → A (no location)`: the walk starts and ends at the dock [q2:picking_log_sequence, q2:picking_log_loc_null]. P events visit lines strictly in line_no order (8 of 8, 11 of 11) [q2:picking_log_line_order].
- **Hire periods overlap and gap.** There are 4 overlaps (for example, 143 is Sys Admin and Code Tester at once) and 3 gaps (for example, 146 has none from 2016-02 to 2017-03) [q2:hire_overlaps, q2:hire_gaps]. Both pickers are Forklift Operators with no hire period [q2:picker_titles].
- **Web.**
  - Counters never decrease: 116 of 116 deltas are ≥ 0, and page 4 has 0-delta days [q3:counter_monotonic].
  - The 2019-04-20 counter deltas (68/42/43/0) do not match that day's 23 visits (3/12/6/2) [q3:counter_delta_on_visit_day]. The two tables are independent examples.
  - Heartbeats are 5-minute beats with gaps of 10–25 min, the ch18 "missing beats" example [q3:heartbeat_gaps].
- **Ticker** trades Mon–Fri only, 3 weeks of one symbol [q3:ticker_weekdays].
- **Broken artefacts.** The view `emp_hire_periods_with_name` errors [d1]. The four Oracle-TYPE tables are empty shells.

## 5. Distributions to fit (stage 2)

| Quantity | Value |
|---|---|
| purchase cadence | every other month per product, gap 61 d median (59–62 for 150 of 170 gaps; tails 41 and 102) [d1] |
| purchase qty | p10 19, p50 64, p90 103, max 127; cost p50 442 [d1] |
| unit cost | 4.78–8.00, nearly flat inside a product-year [q2:unit_cost, q2:unit_cost_by_year] |
| monthly sales | p10 3, p50 21, p90 55, max 247. Season (sum of 3 years): Feb 1,192 high, Oct 665 low [d1] |
| lots | ⌊qty/48⌋ × 48 + remainder; 1–4 lots per purchase (1: 18, 2: 38, 3: 5, 4: 1) [q2:inventory_per_purchase] |
| orders | 10 in 2019-01-15..03-29, gaps 1–20 d; 3–4 per customer; lines per order 1: 3, 2: 6, 3: 1 [d1] |
| order line qty | 16–140, multiples of 2; unit price 9.6–24.7 [d1] |
| picking | 9–12 lines per list; arrive → pick 4–11 s, pick → depart 5–12 s, depart → next arrive 9–109 s (mean 42) [q2:picking_log_gaps] |
| page visits | 2 IPs; in-session gaps 22 s–17 min, one 4.9 h break; page mix 1: 3, 2: 12, 3: 6, 4: 2 [d1] |
| counter daily delta | page 1 median 74, page 2 49, page 3 38, page 4 3, with spikes up to 360 [d1] |
| device mix | phone 47–51%, pc 23–30%, tablet 23–26% (2 days) [d1] |
| ticker | daily change −1.3..+1.5 [d1] |
| conversion | purchase → stocked: 62 of 180 (only the most recent year); order → picked: 3 of 10 |

These are book examples, not a population. The numbers fit a shape, not a realistic process.

## 6. simkit mapping sketch

```python
p.entity("product_groups", key="group_key", cols={"ext_id": i64(), "name": text()})
p.entity("products", key="product_key", cols={"ext_id": i64(), "name": text(), "group_id": ref("product_groups"),
         "sales_volume": i64(), "abv": f64()})                                   # + product_alcohol (10/10)
p.entity("breweries", ...); p.entity("customers", key="customer_key", cols={"ext_id": i64(), "name": text()})
p.entity("packaging", key="packaging_key", cols={"ext_id": i64(), "name": text()})
p.entity("packaging_relations", key="prel_key", cols={"ext_id": text(), "packaging_id": ref("packaging"),
         "contains_id": ref("packaging"), "qty": i64()})
p.entity("employees", key="employee_key", cols={"ext_id": i64(), "name": text()})
p.entity("web_apps", ...); p.entity("web_pages", key="page_key", cols={"ext_id": text(), "app_id": ref("web_apps"),
         "page_no": i64(), "friendly_url": text()})
p.entity("stock", key="stock_key", cols={"ext_id": text(), "company": text()})
p.entity("channels_dim", ...); p.entity("gender_dim", key="gender_key", cols={"ext_id": text(), "name": text()})
p.event("purchase_received", cols={"brewery_id": ref("breweries"), "purchase_id": i64(), "product_id": ref("products"),
        "qty": i64(), "cost": amount("EUR")})
p.event("lot_stored", doc="time = its purchase's date (rule)", cols={"product_id": ref("products"), "inventory_id": i64(),
        "location_id": i64(), "purchase_id": i64(), "qty": i64()})
p.event("monthly_sales_reported", cols={"product_id": ref("products"), "qty": i64()})
p.event("budget_set", doc="time = Jan 1 of the budget year (rule)", cols={"product_id": ref("products"), "mth": text(), "qty": i64()})
p.event("order_placed", cols={"customer_id": ref("customers"), "order_id": i64()})
p.event("order_line_added", cols={"customer_id": ref("customers"), "orderline_id": i64(), "order_id": i64(),
        "product_id": ref("products"), "qty": i64(), "amount": amount("EUR")})
p.event("picklist_created", cols={"picker_emp_id": ref("employees"), "picklist_id": i64()})
p.event("pick_line_planned", cols={"picker_emp_id": ref("employees"), "picklist_id": i64(), "line_no": i64(),
        "location_id": i64(), "order_id": i64(), "product_id": ref("products"), "qty": i64()})
for e in ("picker_arrived", "line_picked", "picker_departed"):
    p.event(e, cols={"picker_emp_id": ref("employees"), "picklist_id": i64(), "location_id": opt(i64()),
            "pickline_no": opt(i64())})
p.event("hire_period_started", cols={"employee_id": ref("employees"), "title": text()})
p.event("hire_period_ended", cols={"employee_id": ref("employees"), "start": text()})
p.event("page_counter_read", cols={"page_id": ref("web_pages"), "counter": i64()})
p.event("page_visited", cols={"client_ip": text(), "page_id": ref("web_pages"), "src_rowid": i64()})
p.event("heartbeat_received", cols={"server": text()})
p.event("device_counts_reported", cols={"app_id": ref("web_apps"), "pc": i64(), "tablet": i64(), "phone": i64()})
p.event("demographics_reported", cols={"app_id": ref("web_apps"), "m_tw_cnt": i64(), ..., "f_fb_qty": i64()})
p.event("price_quoted", cols={"stock_id": ref("stock"), "price": f64()})
p.event("customers_snapshot", cols={"customer_id": ref("customers"), "favorite_list": opt(text()), "review_list": opt(text())})
p.event("employees_snapshot", cols={"employee_id": ref("employees"), "title": text(), "supervisor_id": opt(ref("employees"))})
p.event("products_snapshot", cols={"product_id": ref("products"), "qty_minimum": i64(), "qty_purchase": i64()})
```

Ingest (`-- event: … owner= ord=`; every block ends in an ORDER BY):
- `purchase_received owner=brewery_id ord=purchase_id`, ORDER BY id.
- `lot_stored owner=product_id ord=inventory_id`: JOIN purchases for the time, ORDER BY id. It comes after E1's block, so on a shared date the purchase sorts first.
- `monthly_sales_reported owner=product_id`, ORDER BY mth, product_id.
- `budget_set owner=product_id`, with time `strftime('%Y-01-01', mth)`, ORDER BY product_id, mth.
- `order_placed` / `order_line_added owner=customer_id`, ord = order id / orderline id.
- `picklist_created`, then `pick_line_planned` (ord = line_no) at `created`, then the three picking_log blocks split by `activity`, ord = log_time.
- `hire_period_started` / `hire_period_ended`, ORDER BY emp_id, start_.
- `page_counter_read owner=page_id ord=day`; `page_visited owner=client_ip ord=src_rowid`; `heartbeat_received owner=server`.
- Snapshot blocks at `'2019-05-02 00:00:00'`.

build.sql (DuckDB over the decoded views):
- **Brewery tables:**
  - `purchases` from E1;
  - `inventory` from E2, with qty written as DOUBLE;
  - `monthly_sales` from E3, with `mth = strftime(event_time, '%Y-%m-%d')`;
  - `monthly_budget` from E4's `mth`;
  - `orders` from E5 plus `NULL AS delivery`;
  - `orderlines` from E6.
- **Masters:** `products` and `product_alcohol` both read the products entity; `product_minimums` reads E22.
- **Lists:** `customer_favorites` / `customer_reviews` read E20.
- **Staff:**
  - `employees` is the entity joined to E21;
  - `emp_hire_periods` is E12 LEFT JOIN E13 on (employee, start);
  - `picking_list` / `picking_line` come from E7 and E8;
  - `picking_log` is the UNION ALL of E9–E11 with `activity` re-added ('A', 'P', 'D').
- **Web and ticker:**
  - `web_counter_hist` reads E14 and `web_page_visits` reads E15;
  - `server_heartbeat` reads E16, with `strftime(…, '%Y-%m-%d %H:%M')`;
  - `web_devices` / `web_demographics` read E17 / E18, and `ticker` reads E19.
- **Derived:** `locations` is the generated grid, as in §3.4.
- **Empty:** the 5 empty tables are typed `SELECT … WHERE false`.

Saved queries: local269, local270, local272 (the `picking_line` form that matches gold), local274 and local275 (empty). local273, local277 and local279 are left out: their gold is degenerate, ambiguous or not reproduced.

Stage-2 owners:
- a **brewery** source emits purchases on its every-other-month cadence, with put-away into 48-unit lots;
- a **customer** source emits orders;
- a **picker** machine walks A→P→D;
- the web and ticker parts are independent sources.

The volume is about 1k events, so no sample profile is needed.

## 7. Open questions and risks

- **Licence.** The freeware licence forbids redistribution in "educational materials" and any commercial use. Treat it as local-only. Fitting shapes is fine; shipping rows is not.
- **Inventory semantics.** The table is a frozen state that sales and picking never decrement (§4). Stamping lots at their purchase date is a rule. A stage-2 law such as "stock = purchases − picks" would be **false on this data** and must not be written.
- **Reported-event timing.** E3 and E14 are stamped at the period start, per the brief, so a month's total appears at its first instant. If leakage checks matter, use the period end (the first day of the next month) instead. Both round-trip exactly.
- **Budget rule time** (Jan 1 of the year) is a call. Stamping at `mth` also works, but it moves N to 2019-12-01.
- **local272 contradicts its own text.** Gold picks from warehouse-2 locations (B3, C20, D9 are ids 163, 212 and 233) while the question says "warehouse 1". The gold matches `picking_line`, so keep that form.
- **local277** has three gold variants (277.33 / 266.22 / 417.45), and **local279**'s gold (330, 76) was not reproduced. Both are left out of the saved queries.
- **Locations as derived vs entity.** Deriving them keeps 256 grid rows out of the log, but leaves `location_id` an unchecked i64. If stage 2 wants putaway to choose shelves, make `locations` an entity at 2016-01-01 instead. Both rebuild exactly.
- **Upstream pin.** The repository has no tag beyond `v1.0` as described in its README. I compared against `master`'s fill script (sha256 above); a later commit could differ.

## Summary

- **Exact round trip: yes.** All values are integers, halves/tenths f64 or verbatim text; `locations` is a proven grid; there are no `''` or `'\N'` and no duplicates. The caveat is the minute-precision heartbeat format.
- **Dataset: `oraclesql`**, one dataset over all 38 tables (the 8 questions all hit the brewery and picking group). Fallback split: `oraclesql` + `oraclesql_web`.
- **22 event types (1,034 events); 12 entity types (68 rows).** `locations` is derived; 5 tables are empty.
- **Partly imposed:** 348 events (34%) have natural times, 484 are reported at a period date, and 202 are timed by rule (lots, budgets, pick lines, snapshots).
- **Hardest blocker:** inventory is a frozen state, not a ledger. Its 113 lots are never decremented by sales or by either picklist (both together overdraw 9 of 10 locations), so its event time is a rule and stock laws are false here.
