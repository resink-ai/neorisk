# Pagila / sqlite-sakila (Spider 2.0-lite): reverse-engineered event log

Scope: analysis only. All numbers come from read-only queries (`mode=ro`) against `data/spider2/Pagila.sqlite` and `data/spider2/sqlite-sakila.sqlite`. The scripts are in [`scripts/pagila/`](scripts/pagila/) and their raw outputs sit next to them as `out_<script>.txt`.
- `pq.py DB FILE.sql [names]` runs the `-- name:` blocks of a `.sql` file.
- A reference such as `[p3:payment_date_vs_rental_date]` means file `p3_lifecycle.sql`, block `payment_date_vs_rental_date`.
- `[p5]`, `[p9]` and the like refer to the Python scripts.

## 0. What this catalog is

**The two files are one file.** `Pagila.sqlite` and `sqlite-sakila.sqlite` have the same SHA-256 (`dbca3837…05da88`). All 91 schema objects are identical, and every one of the 16 tables matches in row count, as a multiset (with `typeof` kept) and row by row in rowid order: 0 differences everywhere [`p0_copies.py`]. **Ingest `sqlite-sakila.sqlite`.** Its name says what the data is, 7 of the 9 questions use it, and queries written for `Pagila` run on it unchanged.

**Origin: Sakila, not Pagila.**
- The data is MySQL's **Sakila** sample database: a fictional DVD-rental chain written by Mike Hillyer (MySQL AB documentation team, 2006). It arrives here through a **SQLite port**.
- The schema is the SQLite port's, not Pagila's Postgres one:
  - `AFTER INSERT/UPDATE` triggers set `last_update = DATETIME('NOW')`;
  - the column types are `BLOB SUB_TYPE TEXT` and `numeric`;
  - the 5 views (`customer_list`, `film_list`, `staff_list`, `sales_by_store`, `sales_by_film_category`) are written in SQLite syntax;
  - there are no Postgres partitioned payment tables and no full-text column.
- The business dates are Sakila's: rentals 2005-05-24 .. 2006-02-14 and customers created 2006-02-14 22:04:36/37 [`p1_types.py`]. "Pagila" is only Spider2's label for a second copy.

**It is generated.** The data is a synthetic teaching database, and it shows heavy generator fingerprints (§4):
- rentals arrive only in five 7-day windows, 21 days apart;
- a return happens a whole number of minutes after its rental;
- a payment is stamped at the rental time but carries the late fee of the later return;
- 182 rentals share a single timestamp.

**Licence.** The MySQL docs say the Sakila schema and data files are under the **New BSD licence** ([dev.mysql.com/doc/sakila/en/sakila-license.html](https://dev.mysql.com/doc/sakila/en/sakila-license.html)). A copy of the SQLite port's header ([huggingface.co … sqlite-sakila-delete-data.sql](https://huggingface.co/spaces/arthikrangan/text-to-sql-agent-api/blob/main/data/sqlite-sakila-db/sqlite-sakila-delete-data.sql)) describes it as "a port of the Sakila example database available for MySQL … License: BSD". I did not find the exact upload that Spider2 took.

**Row counts** (46,273 rows in 16 tables) [`p1_types.py`]: payment 16,049 · rental 16,044 · film_actor 5,462 · inventory 4,581 · film 1,000 · film_category 1,000 · address 603 · city 600 · customer 599 · actor 200 · country 109 · category 16 · language 6 · staff 2 · store 2 · **film_text 0**.

## 0.1 How Spider 2.0 uses it

There are 9 questions: 2 on `Pagila` and 7 on `sqlite-sakila`. Gold SQL exists for 4 of them; exec_result CSVs exist for all 9. **I reproduced all 9 gold values** [`p8_spider.sql`].

| id | db | analysis | gold SQL | gold value | reproduced |
|---|---|---|---|---|---|
| local038 | Pagila | actor with the most English Children films, G/PG, ≤120 min, released 2000–2010 | yes | HELEN VOIGHT (3 films; the next four have 2) | ✔ `[p8:local038_gold]` |
| local039 | Pagila | category with the most rental hours, in cities that start with "a" or contain "-" | yes | Sports, 16,858.17 h | ✔ `[p8:local039_hours]` |
| local056 | sqlite-sakila | customer with the highest average absolute month-over-month change in payments | no | STEPHEN QUALLS | ✔ (58.885) `[p8:local056_mine]` |
| local193 | sqlite-sakila | average % of LTV in the first 7 / 30 days (exact hours) and average LTV | no | 9.3796 / 24.7588 / 112.548 | ✔ to 1e-12 `[p8:local193_mine]` |
| local194 | sqlite-sakila | top 3 films per actor by revenue, split equally among the cast | no | e.g. actor 1: GLEAMING JAWBREAKER 136.70, share 17.0875, average 15.0834 | ✔ first 9 rows `[p8:local194_mine]` |
| local195 | sqlite-sakila | % of customers who rented a film with a top-5 actor | no | 99.33 (CSV c; a and b give 99.17 and 99.00) | ✔ 99.332 (top 5 by revenue or by rentals; both give 595/599) `[p8:local195_mine]` |
| local196 | sqlite-sakila | by rating of the first rented film: average spend and average (rentals − 1) | no | G 110.66 / 25.30 … R 111.42 / 25.48 | ✔ all 5 rows `[p8:local196_mine]` |
| local197 | sqlite-sakila | top 10 payers: largest month-to-month change | yes | ELEANOR HUNT, 2005-07, 77.83 | ✔ `[p8:local197_gold]` |
| local199 | sqlite-sakila | month with the most rentals per store (store by the staff member) | yes | store 1: 2005-07, 3,342; store 2: 2005-07, 3,367 | ✔ `[p8:local199_gold]` |

The questions read these columns:
- `payment.amount` and `payment.payment_date`: 056, 193, 194–197;
- `rental.rental_date` and `return_date`: 039, 199;
- the film/actor/category link tables: 038, 194, 195;
- `city` → `address` → `customer`: 039.

No question uses the 5 views, `film_text`, `last_update`, `staff.picture` or the address text columns. For stage 2, local193 is a useful shape check: LTV concentration after the first purchase depends on the window structure.

## 1. Inventory, keys, joins

**Keys.** Every declared primary key is unique [`p2:pk_unique`]. `film_category` is unique on `film_id` alone: each film has exactly 1 category (1,000/1,000), so the "link" table is 1:1 [`p2:film_category_per_film`]. `rental (rental_date, inventory_id, customer_id)` is unique, as the unique index says.

| Table | Rows | Key | Kind | Notes |
|---|---:|---|---|---|
| language | 6 | language_id | lookup | only id 1 (English) is used |
| country | 109 | country_id | lookup | |
| city | 600 | city_id | lookup | `London` appears twice (312, 313: UK and Canada) [`p2:london_countries`]; 1 city has no address |
| address | 603 | address_id (1..605; 257 and 518 missing) | lookup | district and phone are `' '` on every row; postal_code is NULL on the 4 store/staff addresses |
| store | 2 | store_id | lookup | manager_staff_id 1 → 1 and 2 → 2 |
| staff | 2 | staff_id | lookup | picture NULL; both share one SHA-1 password |
| customer | 599 | customer_id | entity | 326 in store 1, 273 in store 2; active `'1'` 584, `'0'` 15 |
| actor | 200 | actor_id | lookup | |
| category | 16 | category_id | lookup | |
| film | 1,000 | film_id | lookup | 958 have stock; 3 have no actors |
| film_actor | 5,462 | (actor_id, film_id) | link | 1–15 actors per film |
| film_category | 1,000 | (film_id, category_id); film_id alone is unique | 1:1 attribute of film | |
| film_text | **0** | film_id | empty duplicate of film (see below) | |
| inventory | 4,581 | inventory_id | entity (one physical copy) | 2–4 copies per (film, store); 1 copy (id 5) never rented |
| rental | 16,044 | rental_id (1..16,049; 321, 2247, 6579, 9426 and 15592 missing) | **log** | |
| payment | 16,049 | payment_id (1..16,049, no gaps) | **log** | rental_id is NULL on 5 rows |

Sources: [`p2:pk_unique`, `p2:missing_ids`, `p2:reverse_coverage`, `p4:copies_per_film_store`, `p7:address_text_fields`, `p7:staff_rows`].

**Join coverage.** All 21 declared foreign keys resolve at 100%, with 0 orphans [`p2:fk_coverage`]. Reverse coverage [`p2:reverse_coverage`]:

| Parent | With children |
|---|---|
| rentals with a payment | 16,044 / 16,044. Every rental has **exactly one** payment: 16,044 distinct non-null payment.rental_id |
| customers with a rental | 599 / 599 |
| inventory ever rented | 4,580 / 4,581 |
| films with inventory | 958 / 1,000 |
| films with actors | 997 / 1,000 |
| addresses used by a customer, staff member or store | 603 / 603: 599 customers + 2 staff + 2 stores, each address used once |
| cities with an address | 599 / 600 |
| languages used | 1 / 6 |

**Payments with no rental: 5 rows, explained.** The 5 payments with `rental_id IS NULL` (payment_id 424, 7011, 10840, 14675, 15458) pair one to one with the 5 missing rental_ids. Each one's `payment_date` falls between the dates of rental_id − 1 and rental_id + 1 of a missing id [`p3:missing_rental_neighbours`]:

| missing rental_id | prev rental | next rental | null-rental payment in the gap |
|---|---|---|---|
| 321 | 05-27 00:09:24 | 05-27 00:47:35 | 15458 (customer 577) 00:46:39 |
| 2247 | 06-18 04:54:29 | 06-18 04:59:48 | 424 (16) 04:56:12 |
| 6579 | 07-12 06:15:41 | 07-12 06:26:10 | 10840 (401) 06:26:10 |
| 9426 | 07-30 21:11:21 | 07-30 21:16:33 | 14675 (546) 21:16:20 |
| 15592 | 08-23 06:11:52 | 08-23 06:15:09 | 7011 (259) 06:13:16 |

The rentals were deleted, and the FK `ON DELETE SET NULL` cleared the payment's link. The customers of these payments have no open rentals [`p2:payments_without_rental_context`]. Their amounts (0.99–3.99) are plain rental rates.

**Cross-entity facts** [`p2:*`]:
- payment.customer_id = rental.customer_id on 16,044/16,044.
- payment.staff_id = rental.staff_id on only 7,966 (49.7%), and the 2×2 table is flat: staff is drawn independently per row.
- The inventory's store vs the rental staff's store and the customer's store vs the inventory's store are both about 50/50. Customers rent from either store, and either clerk serves any store.

**Row order** [`p6:rowid_order_keys`, `p6:rowid_order_composite`]:
- Every table's rowid order is its key order: film_actor by (actor, film), film_category by film, address and rental by id.
- `payment_id` is in (customer_id, payment_date) order on 16,048/16,048 adjacent pairs [`p3:payment_id_order`].
- `rental_id` is in time order except for the 182 rows dated 2006-02-14. Without them, 15,861/15,861 pairs are in order [`p7:rental_id_order_without_2006`].

## 2. Event catalog

The source is two logs (rental, payment) over a set of lookup tables. Times are the source wall clock read as UTC (no zone is stated; Sakila is fictional).

| # | Event | Owner | Time | Attributes | Source rows | Count |
|---|---|---|---|---|---|---:|
| E1 | `rental_started` | customer | `rental_date` | rental_id, inventory (ref), customer (ref), staff (ref), last_update (text) | one per rental row | 16,044 |
| E2 | `payment_taken` | customer | `payment_date` | payment_id, rental_id (opt i64; NULL ×5), customer (ref), staff (ref), amount (USD cents), last_update (text) | one per payment row | 16,049 |
| E3 | `rental_returned` | customer | `return_date` | rental_id | rentals with return_date not NULL | 15,861 |
| | **total** | | | | | **47,954** |

**Notes on the events.**
- E2 shares E1's time on all 16,044 linked rows (`payment_date = rental_date` exactly, 0 before and 0 after) [`p3:payment_date_vs_rental_date`]. Use `ord`: E1 = 0, E2 = 1. The 5 orphans keep their own times.
- No time is invented: every event time is a source column. The snapshot time is N = **2006-02-14 15:16:03**, the latest event; the 183 open rentals have no E3.
- **Owner = customer.** payment_id is ordered by customer, and the Spider questions are customer-centric. The lifecycle checks are per inventory item: an item is never rented again before it is returned (0/11,464 consecutive pairs) [`p3:overlap_same_inventory`].

**Entities (lookup snapshots, no time of their own):**

| Entity | ext_id | Columns | Rows |
|---|---|---|---:|
| language | language_id | name (CHAR(20) text), last_update | 6 |
| country | country_id | country, last_update | 109 |
| city | city_id | city, country (ref), last_update | 600 |
| address | address_id | address, address2 (NULL), district, city (ref), postal_code (opt), phone, last_update | 603 |
| store | store_id | manager (ref staff), address (ref), last_update | 2 |
| staff | staff_id | first/last name, address (ref), picture (NULL), email, store (ref), active, username, password, last_update | 2 |
| customer | customer_id | store (ref), first/last name, email, address (ref), active (text `'0'`/`'1'`), create_date (text), last_update | 599 |
| actor | actor_id | first/last name, last_update | 200 |
| category | category_id | name, last_update | 16 |
| film | film_id | title, description, release_year (text), language (ref), original_language_id (NULL), rental_duration, rental_rate (cents), length, replacement_cost (cents), rating, special_features, last_update, **category (ref) and film_category_last_update** (1:1, folded in) | 1,000 |
| film_actor | `actor_id/film_id` | actor (ref), film (ref), last_update | 5,462 |
| inventory | inventory_id | film (ref), store (ref), last_update | 4,581 |

That is **12 entity tables with 13,180 rows**.

**What is not an entity, and why:**
- **`film_category`** is not its own entity: it is 1:1 with film, so it folds into film.
- **`film_text`** is not an entity. It has the same columns as film's (film_id, title, description) and **0 rows**. In MySQL Sakila it is a MyISAM full-text copy kept in sync by triggers on `film`. The SQLite port defines no such trigger, so it stayed empty. The rebuild is an empty `SELECT … WHERE false`; nothing in it needs data.
- **The 5 views** are not tables and are not rebuilt (`refdata rebuild` copies `type='table'` DDL only). They work on a rebuilt file only if their DDL is replayed.
- **`customer.create_date`** is not a time. All 599 values are 2006-02-14 22:04:36 or :37, split at customer_id 271/272. That is after every rental, so it is a load stamp from the original MySQL build, not a sign-up time [`p6:customer_create_date`, `p6:customer_create_vs_first_rental`]. Keep it as text, and let the entity's `created_at` default to the first event.
- **`customer.active = '0'`** (15) is not an event, because it has no time. Inactive customers still rent until N (4 rentals on 2006-02-14) [`p4:inactive_customer_activity`].

## 3. Rebuild rules and blockers to an exact round trip

| Table | Rule | Exact? |
|---|---|---|
| rental | E1 ⟕ E3 on rental_id. `return_date` = E3 time or NULL. Times formatted `strftime('%Y-%m-%d %H:%M:%S') \|\| '.000'` | yes. Milliseconds are `.000` on 100% of the 4 time columns [`p7:millis_always_zero`] |
| payment | E2 verbatim; rental_id NULL on the 5 orphans | yes |
| lookups | entity snapshots verbatim; integer ids cast back from `ext_id` text | yes |
| film_category | project film (film_id, category, film_category_last_update) | yes |
| film_text | empty, with 3 typed columns | yes |

**Derived columns.**
- **`payment.amount` is a function of other rows for every returned rental:** `amount = film.rental_rate + max(0, (date(return_date) − date(rental_date)) − film.rental_duration) × 1.00`. It holds on **15,861/15,861** rows [`p5_fee_rule.py`].
  - The day count is calendar days, as in MySQL `DATEDIFF`. Elapsed-time variants fail: floor 12,142, round 14,853, ceil 11,471.
  - The 183 payments of open rentals do not follow it [`p5`]:
    - 135 are equal to the rate;
    - 24 are 0 (all on 2006-02-14);
    - 24 are odd multiples such as 1.98 = 2 × 0.99 or 8.97 = 3 × 2.99.
  - So carry `amount` as data, and treat the rule as a check, not a derivation.
- No other column is derived. `customer.email = FIRST.LAST@sakilacustomer.org` holds on 599/599 [`p7:email_rule`], but it is cheap to carry.

**`last_update`: a load clock, not business time** [`p6:*`].
- Every table's `last_update` lies in **2021-03-06 15:51:48 .. 15:58:09**, a 6 min 21 s window.
- It is non-decreasing in rowid on every table (0 violations), at about 120 rows/s (3–139 per second).
- The tables follow FK load order: language → country → city → address → actor → category, staff, store → film → inventory → film_actor → film_category → customer → rental → payment.
- These are the port's `AFTER INSERT` triggers firing `DATETIME('NOW')` during the import. The values say nothing about the business:
  - open and closed rentals have the same load times [`p6:rental_last_update_vs_return`];
  - the 2006 payments are spread through the payment load [`p6:payment_2006_last_update`].
- Constant within a table only for language, country, category, staff and store (1 distinct value each). Elsewhere there are 2–137 distinct seconds.
- **Rule: carry each row's `last_update` verbatim as text** on its event or entity. It cannot be recomputed exactly from rowid, because the per-second counts vary. In stage 2, generate it as "load start + rowid / ~120 per s"; nothing reads it.

**Other blockers and risks:**
1. **Triggers.** The source DDL has 30 triggers [`p2:trigger_count`] that overwrite `last_update` on insert. `refdata rebuild` copies only `type='table'` DDL, so they are not replayed. Any tool that copies the full schema (`.dump`, `sqlite_master` replay) would destroy every `last_update` on insert.
2. **Type affinity.**
   - `TIMESTAMP`, `DECIMAL` and `numeric` columns have NUMERIC affinity. `payment.amount` = 0 is stored as INTEGER (24 rows) and every other amount as REAL [`p4:amount_values`]. Inserting 0.0 through the same DDL reproduces this, and compare matches by value anyway.
   - Gotcha for queries: `rental_date < '2006'` is false on **every** row, because the bare literal becomes the integer 2006. `< '2006-01-01'` works [`p7:affinity_trap`].
   - `release_year` (VARCHAR) is text `'2006'`. local038's `BETWEEN 2000 AND 2010` relies on the text comparison.
   - `customer.active` is text `'0'`/`'1'` in a `CHAR(1) DEFAULT 'Y'` column.
3. **Integer ids through `ext_id`.** ingest stringifies `ext_id`, so the views must `CAST(ext_id AS INTEGER)`. Entity keys rank textually ('10' < '2'), which is harmless.
4. **Money.** All 16,049 amounts and all film prices are exact cents (0 off the grid) [`p4:amount_cent_grid`]. Use `amount()` in cents, and write REAL back.
5. **Blank text.** `address.district` and `phone` are a single space `' '` on all 603 rows, not NULL and not ''. City names have non-ASCII letters dropped ("A Corua (La Corua)", "guas Lindas de Gois") [`p7:city_odd`]. Keep both byte-exact.
6. **Duplicates.** 48 pairs of rentals share a timestamp, plus the 182-row 2006 batch; 25 pairs of returns share one [`p7:same_timestamp_*`]. Ties sort by owner and then rental_id; the order inside a tie does not affect table contents.

## 4. Measured quirks

**The rental → return → payment lifecycle:**
- **Payment at checkout, fee from the future.** payment_date = rental_date on 16,044/16,044, yet the amount includes the late fee that the return later earns (§3). A real system would charge the fee at return. In stage 2, emit E2 at E1's time with the amount drawn from the drawn duration (a look-ahead), or else accept a deliberate deviation.
- **Return = rental + whole minutes.** All 15,861 returns keep the rental's seconds and differ from it by a whole number of minutes [`p7:return_minus_rental_whole_minutes`].
- **Duration = U{1..9} days ± 6 h.**
  - The duration modulo 24 h falls only in 18:00–05:59. Its 6-hour bins come in pairs around each whole day: (18–30 h), (42–54 h) … (210–222 h).
  - Min 1,080 min (18 h), max 13,319 min (221.98 h).
  - Each day 1..9 holds about 1,760 rentals (846 + 917 for day 1) [`p9_dists.py`].
  - The duration is independent of `film.rental_duration`: corr −0.0006, and the mean is 5.0 d for every value 3–7 [`p9`, `p3:return_vs_rental_duration`].
  - So the "late" rate falls mechanically with the allowance: 72% of 3-day films are late versus 29% of 7-day ones.
- **Days late** (calendar rule): 0: 8,592 · 1: 1,782 · 2: 1,833 · 3: 1,439 · 4: 1,077 · 5: 734 · 6: 379 · 7: 25 [`p5`].
- **No double renting.** An item is rented at most once per window (16,044/16,044) [`p7:item_rentals_per_window`], and never before its previous return. The shortest idle time between a return and the next rental of the same item is 120.7 h [`p7:idle_gap_short`].

**Arrival windows: a generator fingerprint** [`p7:windows`, `p7:daily_counts`]:

| window | first | last | rentals | per day | rental_id range |
|---|---|---|---:|---:|---|
| 1 | 2005-05-24 22:53:30 | 05-31 22:47:45 | 1,156 | 165 | 1–1,157 |
| 2 | 2005-06-14 22:53:33 | 06-21 22:48:59 | 2,311 | 330 | 1,158–3,469 |
| 3 | 2005-07-05 22:49:24 | 07-12 22:40:48 | 3,453 | 494 | 3,470–6,923 |
| 4 | 2005-07-26 22:51:53 | 08-02 22:51:23 | 4,570 | 653 | 6,924–11,494 |
| 5 | 2005-08-16 22:51:20 | 08-23 22:50:12 | 4,372 (+182) | 625 | 11,495–16,049 |
| — | 2006-02-14 15:16:03 | (one second) | 182 | — | inside window 5's ids |

- Each window spans 7.00 d and starts at about 22:50; the starts are 21.00 d apart.
- Inside a window, arrivals are Poisson: inter-arrival CV 0.97–1.00 per window. Hour of day is flat (610–705 per hour) and so is weekday (2,200–2,320) [`p7:hour_mix`, `p7:weekday_mix`].
- Returns are flat by hour too [`p7:return_hour_mix`]. **Return dates end 2005-09-02**, so no returns happen between windows 5 and N.

**The 2006-02-14 batch.**
- 182 rentals share `2006-02-14 15:16:03.000`. All 182 are unreturned, on 182 distinct items, from 158 customers [`p7:open_2006_rows_detail`].
- Their rental_ids are scattered through window 5's id range (11,496–15,966), and they break the id/time order 175 times [`p7:rental_id_order_breaks_by_kind`].
- None of their items is rented during window 5 [`p7:items_2006_also_in_window4`], and window 5 plus the batch covers 4,554 distinct items.
- Reading: these were window-5 rentals whose dates were overwritten (and returns cleared), to leave a set of "currently out" rentals at the snapshot. Their payments are also stamped 2006-02-14 and include the 24 zero amounts.
- Separately, 1 rental from 2005 is still open: 14098, item 6, customer 554 [`p3:open_rentals_before_2006`].

**Other fingerprints and dirt:**
- 5 deleted rentals with orphaned payments (§1).
- `customer.create_date` is after every rental (§2).
- `film`: `release_year` = '2006' on all rows; language 1 on all; original_language NULL on all.
- The film mixes are near-uniform:
  - rental_rate 0.99 / 2.99 / 4.99: 341 / 323 / 336;
  - rental_duration 3–7: 191–212 each;
  - replacement_cost 9.99–29.99 in 21 steps;
  - 5 ratings, 178–223 each;
  - 15 special-feature combinations, 49–79 each [`p4:*`].
- Titles are upper case and every description starts with "A …" (1,000/1,000) [`p7:title_description_shape`].
- `staff.picture` is NULL; the MySQL original ships a picture for Mike Hillyer (not checked here).

## 5. Distributions to fit (stage 2)

| quantity | fitted shape / numbers | source |
|---|---|---|
| arrivals | 5 windows × 7 d, 21 d apart; homogeneous Poisson in each window at 165, 330, 494, 653 and 625 per day; flat by hour and weekday | `p9`, `p7:windows` |
| rental duration | U{1..9} days + U(−6 h, +6 h), whole minutes; mean 7,236.5 min, sd 3,732; p50 120.6 h | `p9` |
| payment amount | rental_rate + $1 × calendar days late. Mix: 4.99 3,789 · 2.99 3,542 · 0.99 2,979 · 5.99 1,299 · 6.99 1,119 · 3.99 1,109 … 11.99 10 | `p5`, `p9` |
| customer choice | uniform: rentals per customer mean 26.78, var 26.07 (Poisson), range 12–46; LTV 50.85–221.55, mean 112.55 | `p9`, `p4:revenue_per_customer` |
| re-rental gap per customer | p50 20.0 h, p75 48 h, p95 412 h (between windows) | `p9` |
| item choice | without replacement among free items: at most 1 rental per item per window; per item mean 3.50, var 1.24 (under-dispersed); window 4 used 4,570/4,581 items | `p9`, `p7:windows_per_item` |
| film popularity | rentals per copy p50 3.5 (p5 2.67, p95 4.5), so demand ∝ copies; copies per (film, store) 2, 3 or 4 (507 / 489 / 525) | `p9`, `p4:copies_per_film_store` |
| staff and store | staff 50/50 per row (8,040 / 8,004), independent of the store and of the payment's staff; 50% of rentals cross stores | `p2:*`, `p4:staff_rental_mix` |
| concurrency | rentals a customer has out at a rental start: 1–16, mode 1, p50 about 3 | `p3:customer_concurrent_out` |
| lifecycle conversion | rental → payment 100%; rental → return 98.86% (15,861/16,044; the open ones are the snapshot batch plus 1); deleted rentals 5/16,049 | `p2`, `p3` |
| catalog | 16 categories, 51–74 films each; 1–15 actors per film (mode 5), 14–42 films per actor; length 46–185 min | `p4:*` |

## 6. simkit mapping sketch

```python
p.entity("language", key="language_key", cols={"ext_id": text(), "name": text(), "last_update": text()})
p.entity("country",  key="country_key",  cols={"ext_id": text(), "country": text(), "last_update": text()})
p.entity("city",     key="city_key",     cols={"ext_id": text(), "city": text(), "country_key": ref("country"), "last_update": text()})
p.entity("address",  key="address_key",  cols={"ext_id": text(), "address": text(), "address2": opt(text()), "district": text(),
                                               "city_key": ref("city"), "postal_code": opt(text()), "phone": text(), "last_update": text()})
p.entity("store",    key="store_key",    cols={"ext_id": text(), "manager_staff_key": ref("staff"), "address_key": ref("address"), "last_update": text()})
p.entity("staff",    key="staff_key",    cols={"ext_id": text(), "first_name": text(), "last_name": text(), "address_key": ref("address"),
                                               "email": text(), "store_key": ref("store"), "active": i64(), "username": text(),
                                               "password": text(), "last_update": text()})          # picture: always NULL, written by the view
p.entity("customer", key="customer_key", cols={"ext_id": text(), "store_key": ref("store"), "first_name": text(), "last_name": text(),
                                               "email": text(), "address_key": ref("address"), "active": cat("0", "1"),
                                               "create_date": text(), "last_update": text()})
p.entity("actor",    key="actor_key",    cols={"ext_id": text(), "first_name": text(), "last_name": text(), "last_update": text()})
p.entity("category", key="category_key", cols={"ext_id": text(), "name": text(), "last_update": text()})
p.entity("film",     key="film_key",     cols={"ext_id": text(), "title": text(), "description": text(), "release_year": text(),
                                               "language_key": ref("language"), "rental_duration": i64(), "rental_rate": amount("USD"),
                                               "length": i64(), "replacement_cost": amount("USD"), "rating": cat("G","PG","PG-13","R","NC-17"),
                                               "special_features": text(), "last_update": text(),
                                               "category_key": ref("category"), "film_category_last_update": text()})
p.entity("film_actor", key="film_actor_key", cols={"ext_id": text(), "actor_key": ref("actor"), "film_key": ref("film"), "last_update": text()})
p.entity("inventory",  key="inventory_key",  cols={"ext_id": text(), "film_key": ref("film"), "store_key": ref("store"), "last_update": text()})

p.event("rental_started",  cols={"rental_id": i64(), "inventory_key": ref("inventory"), "customer_key": ref("customer"),
                                 "staff_key": ref("staff"), "last_update": text()})
p.event("payment_taken",   cols={"payment_id": i64(), "rental_id": opt(i64()), "customer_key": ref("customer"),
                                 "staff_key": ref("staff"), "amount": amount("USD"), "last_update": text()})
p.event("rental_returned", cols={"rental_id": i64()})
```

Ingest:
- `-- event: rental_started owner=customer_id ord=k` with k = 0, then `payment_taken … ord=k` with k = 1, then `rental_returned` (k = 0 at its own time). Each block ends `ORDER BY rental_id` (payments by `payment_id`).
- Times: `substr(x, 1, 19)`.
- Entity blocks: `ORDER BY` the integer id. The circular store ↔ staff refs resolve, because refs map over completed entity tables.
- The views write `return_date` as NULL when there is no E3, `'.000'` suffixes, `CAST(ext_id AS INTEGER)`, and the `film_text` empty select.

Stage 2 behaviour:
- **Source**: the catalog, stores, staff, customers and inventory are inserted at t0, with the copy count per film/store drawn from {2, 3, 4}.
- **Arrivals**: 5 open windows driven by timers (7 d on, 14 d off). In each, a Poisson stream at the window's rate picks a uniform customer and a uniform free item: an `inventory` shard reservation with a hold, released on return, so double renting is impossible.
- **On rental**: emit E1, draw the duration from §5, compute the fee from the duration and emit E2 at the same instant, then `ctx.at(return)` → E3.
- **End-of-window snapshot quirk**: optionally replay the 182-row batch, which re-dates about 4% of the last window's rentals to N and clears their returns.

Volume is about 48k events plus about 13k entity rows, under a second.

Checks:
- `lifecycle rental_started → rental_returned` per rental_id;
- no overlap per inventory item;
- one payment per rental;
- amount = fee rule for returned rentals (a custom law; it must not apply to the 183 open ones);
- `payment_taken.rental_id` is NULL only for deleted rentals.

## 7. Open questions and risks

- **Which upload of the SQLite port.** The trigger-based `last_update` (2021-03-06) points to someone importing the port's data script on that date. I did not locate that exact repository or Kaggle page, so the licence chain is BSD by inheritance, not confirmed for the copy itself.
- **What the MySQL original holds.** From general knowledge, the MySQL original has real district and phone values, a staff picture, a populated film_text and its own 2006 last_update values. I did not check this against the upstream files here; if it matters, compare with `sakila-data.sql`. The blanking of district and phone and the stripping of non-ASCII letters happened somewhere in the porting chain.
- **The 2006-02-14 batch.** The "overwritten window-5 rentals" reading rests on the id range and the disjoint items. Their payment amounts (24 zeros, odd multiples) have no rule I could find.
- **Fee look-ahead.** A simulator has to know the return time when it takes payment. Faithful reproduction means E2 carries information from the future, which a causality law would reject. Decide whether stage 2 copies this or moves the fee to E3 and accepts a deviation in the `payment` table.
- **Owner choice.** Customer ownership makes the item-overlap law a cross-partition check. Inventory ownership makes it local but splits a customer's payments across partitions. Either works for stage 1.
- **Wall clock.** No time zone is stated, so treat it as UTC. It has no DST issue, since the data has no real location.
- **Spider usage.** All 9 answers are reproducible. local195's three gold CSVs disagree (99.17 / 99.00 / 99.33), so compare the rebuilt file against the source, not against a gold number.

## Summary

- **Feasible:** yes, exact. Every column is either a source time or carried verbatim, and no time is invented. Keep `last_update` as text, and never replay the 30 triggers.
- **Project:** `sakila`, ingesting `sqlite-sakila.sqlite`. `Pagila.sqlite` is byte-identical (same SHA-256, 0 row differences), so the 9 questions (2 Pagila + 7 sqlite-sakila, all reproduced) run on one file.
- **Events:** 3 types, 47,954 rows: rental_started 16,044, payment_taken 16,049, rental_returned 15,861.
- **Entities:** 12 tables, 13,180 rows. film_category folds into film; film_text is empty and rebuilt as an empty table.
- **Hardest blocker:** `last_update` is an import-time load clock (2021-03-06 15:51:48–15:58:09, monotone in rowid) that must be carried per row. For stage 2 the hard part is that the payment is stamped at checkout but its amount needs the future return (rate + $1 × calendar days late, 15,861/15,861).
