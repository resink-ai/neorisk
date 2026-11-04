# Parch & Posey (Spider 2.0-lite, `education_business` `web_*`): reverse-engineered event log

Source: the five `web_*` tables of `data/spider2/education_business.sqlite`, opened read-only. `scripts/parchposey/rq.py` copies the file into an in-memory SQLite and runs named blocks; the file itself is never written. The other catalogs in the file are AtliQ ([atliq.md](atliq.md)), the university ([university.md](university.md)) and `StaffHours` + `SalaryDataset` ([edu_misc.md](edu_misc.md)).

Every number below comes from one of these scripts:
- a named query in `scripts/parchposey/q*.sql`;
- `f1_amounts.py` (Python, money rules);
- `f2_duck_amounts.py` (DuckDB, run with `uv run python -I`).

The raw outputs are in `scripts/parchposey/out_*.txt`. A reference such as `[q3:split_points]` means file `q3_series.sql`, block `-- name: split_points`. Gold CSVs are in `scripts/parchposey/gold/`.

## 0. What this catalog is

- **Dataset.** This is **Parch & Posey**, the fictitious paper company in Mode Analytics' (Derek Steer's) *SQL for Data Analysis* course on Udacity. The course tables are `accounts`, `orders`, `web_events`, `sales_reps` and `region`; Spider prefixes the others with `web_`; `web_events` already has the prefix and keeps its name. The evidence:
  - The counts are the course's familiar ones: 6,912 orders, 351 accounts, 50 sales reps, 4 regions and 9,073 web events [q1:row_counts].
  - The paper types are `standard`, `gloss` and `poster`, at the course's unit prices 4.99, 7.49 and 8.12 [q2:unit_prices].
  - Accounts are big US companies in **Fortune 500 rank order**: Walmart 1001, Exxon Mobil 1011, Apple 1021, Berkshire Hathaway 1031, McKesson 1041 [q4:accounts_rowid_head]. Their ids are 1001..4501 in steps of 10.
  - The channel values are the course's: `direct`, `facebook`, `organic`, `adwords`, `banner` and `twitter` [q2:channel_mix].
- **Row counts** [q1:row_counts]: web_events 9,073; web_orders 6,912; web_accounts 351; web_sales_reps 50; web_region 4. The total is 16,390.
- **Licence.** Unstated. It is course material distributed with the Udacity / Mode lessons.
- **Nature.** **Generated course data.** The company and rep names are real, but the activity is synthetic: two interleaved monthly order series per account, with a direct visit minutes before each order of the first series (§4). The times are full UTC timestamps with a `Z` suffix.

## 0.1 How Spider 2.0 uses it

| id | asks | gold SQL? | gold answer | reproduced |
|---|---|---|---|---|
| local114 | per region: number of orders, total sales, and the top sales rep(s) by sales amount, with ties | no (3 CSVs: _a, _b, _c, which differ only in text formatting) | Midwest 897 / 3,013,486.51 / Charles Bidwell 675,637.19; Northeast 2,357 / 7,744,405.36 / Tia Amato 1,010,690.60; Southeast 2,024 / 6,458,497.00 / Earlie Schleusner 1,098,137.72; West 1,634 / 5,925,122.96 / Georgianna Chisholm 886,244.12 | ✔ exactly [q2:gold_local114]. No region has a tie at the top |

The gold total `7744405.359999999` is the float sum of the stored REALs in source order. The rebuilt amounts must therefore be the same doubles, not just the same cents. §3.2 shows that they are.

## 1. Inventory, keys, joins

No PK or FK is declared. All keys below are verified unique, and all joins resolve with 0 orphans [q1:key_uniqueness, q1:fk_orphans].

| Table | Rows | Key | Kind |
|---|---:|---|---|
| web_orders | 6,912 | id 1..6,912, dense, = rowid [q1:dense_ids, q1:rowid_vs_id] | activity (order with 3 quantities) |
| web_events | 9,073 | id 1..9,073, dense, = rowid | activity (web visit, with channel) |
| web_accounts | 351 | id 1001..4501, step 10; `name` unique too | party (customer company) |
| web_sales_reps | 50 | id 321500..321990, step 10; `name` unique | party (rep) |
| web_region | 4 | id 1..4 (Northeast, Midwest, Southeast, West) | lookup |

Joins and coverage [q1:fk_orphans, q1:parents_without_children]:
- orders → accounts, events → accounts, accounts → reps and reps → region: all 100%.
- **1 account has no orders:** 1731 Goldman Sachs Group. Every account has web events [q1:account_wo_orders_rows].
- Every rep has accounts (3–15 each), and every region has reps (21, 9, 10 and 10) [q1:reps_per_region, q2:accounts_per_rep].
- **A rep's region is geographic.** The accounts' longitudes sit inside their rep's region: West −122.7..−115.1, Northeast −77.5..−71.1, and so on [q4:rep_region_of_accounts].
- **There are no copies or derived tables.** In web_orders, `total` and the four `*_amt_usd` columns are derived *columns* (§3.2).
- **Rowid order.** Reps and accounts are in id order. Accounts have 1 descending pair, out of rank order [q4:accounts_rowid_order]. Orders and events are in id order, which is **not** time order: 572 and 782 descending pairs [q1:id_vs_time_order]. The id order is explained in §4.

## 2. Event catalogue

Both activity tables are natural event logs. Each row has its own second-resolution UTC timestamp.

| # | Event | Owner | Time | Attributes | Source rows | Count |
|---|---|---|---|---|---|---:|
| E1 | `web_visited` | account (ord = id) | `occurred_at` (natural) | event_id (source id, i64), channel | web_events | 9,073 |
| E2 | `order_placed` | account (ord = id) | `occurred_at` (natural) | order_id (source id, i64), standard_qty, gloss_qty, poster_qty | web_orders | 6,912 |

**Total events: 15,985.** The order's `total` and its four money columns are not carried: they are exact functions of the three quantities (§3.2).

Entities (3 tables, 405 rows):
- **region** (4) and **sales_reps** (50, with `region_id` as a ref) are created by rule at the catalog start, 2013-12-04 00:00:00 UTC, the day of the first event [q1:time_formats].
- **accounts** (351) carry name, website, lat (f64), long (f64), primary_poc and `sales_rep_id` (ref). `created_at` is the **first web event** by rule. That is natural in shape, because a web visit precedes the first order for 350 of 350 ordering accounts, and an order never comes first [q2:first_activity].

What is **not** an entity, and why:
- **Paper types** (standard, gloss, poster) are not product entities. They are fixed column names, and their prices are constants (4.99, 7.49 and 8.12) with no price table and no change [q2:unit_prices].
- **Channels** are a category, not an entity.
- **primary_poc** is a text attribute. It is not a contact entity: 330 distinct names over 351 accounts, and several names belong to 2 accounts [q2:account_text, q4:poc_dups].

There are no snapshot columns: the accounts have no lifetime totals or stamps.

Snapshot **N = 2017-01-02T00:02:40Z**, the last order [q2:last_times].

## 3. Rebuild rules and blockers to an exact round trip

1. **Time text.**
   - Every `occurred_at` is `YYYY-MM-DDTHH:MM:SS.000Z`: 24 characters, a `T` separator, and always `.000Z` [q1:time_formats, q2:millis_suffix].
   - SQLite's `datetime()` parses all 15,985 values, but none is in its canonical form [q1:time_parse].
   - Read them as UTC. This time is genuinely UTC, since the suffix says so. Write them back with `strftime(t, '%Y-%m-%dT%H:%M:%S') || '.000Z'`.
2. **Money is a pure function of the quantities.**
   - `total = standard_qty + gloss_qty + poster_qty` holds for 6,912 of 6,912 orders [q2:total_is_sum_qty].
   - Each `*_amt_usd` equals `qty × cents / 100` as a double, with cents = 499, 749 and 812: 6,912 of 6,912 for each column, in Python [f1] and in DuckDB [f2].
   - `total_amt_usd` equals `(qs·499 + qg·749 + qp·812) / 100`: 6,912 of 6,912 in both [f1, f2]. That is the exact cent sum, rounded once to a double.
   - **The naive float forms fail.**
     - In SQLite, `qty * 4.99` equals the stored value in only 5,281 standard, 5,966 gloss and 3,993 poster rows [q2:amt_is_qty_times_price_sqlite].
     - `standard + gloss + poster` reproduces `total_amt_usd` in only 5,163 rows [q2:total_amt_is_sum_sqlite, f2].
     - DuckDB's `qs * 4.99` happens to match 6,912 of 6,912, because DuckDB reads `4.99` as a DECIMAL [f2]. Do not depend on that.

   So E2 carries only the three quantities. `build.sql` uses the integer-cents rule, and every stored double comes back bit for bit. This is the same "cents / 100" pattern as Chinook's invoice totals.
3. **Ids.** The order and event ids are carried verbatim as attributes, because their order is not time order (§4). The account and rep ids are the entities' `ext_id`.
4. **Floats.** `lat` and `long` are f64 verbatim, with up to 8 decimals (11- and 13-character text) [q2:lat_long_precision].
5. **NULLs and empties.** There is no NULL and no `''` in any column of the five tables [q1:nulls_empty].
6. **Duplicates and ties.**
   - 4 accounts have two orders at the **same second** (accounts 1301, 2731, 4161 and 4271). In each case one order is from series A and one from series B [q2:dup_orders_same_account_time].
   - Web events have no same-moment duplicates [q1:dup_rows].
   - With `ord = id`, equal times sort deterministically and every row rebuilds.
7. **Rows without time.** Only region and the reps lack a time, and they get the catalog start by rule.

**Verdict:** an exact round trip is feasible, cleanly. Every column is either verbatim or an integer-exact function, and both natural logs keep their own times.

## 4. Measured quirks

- **Two order series in the id space.**
  - The order ids restart at account 1001 at id 4307; the event ids restart at id 4394 [q3:split_points].
  - **Series A** (orders 1–4,306): 350 accounts, a mean of 462 units and $2,555 an order, mostly standard paper (means of 374 standard, 41 gloss and 47 poster).
  - **Series B** (orders 4,307–6,912): 328 accounts, a mean of 647 units and $4,658, mostly gloss and poster (means of 127, 321 and 200) [q3:order_series_stats, q3:series_b_qty_profile].
  - Inside each series, ids are sorted by (account, time): 0 time descents within an account in the orders [q2:orders_id_order_rule].
- **Monthly rhythm.**
  - A series-A account orders every 28–31 days: 29 days for 1,714 gaps and 30 days for 1,703 [q3:monthly_day_drift].
  - 291 of 350 accounts have a contiguous run of order months [q3:active_months_contiguous].
  - Series B orders fall on the **same day as a series-A order** for 2,537 of 2,606 orders, usually within 10 minutes (1,418) [q3:order_b_vs_a_same_day, q3:order_b_minus_a_minutes].
  - So an account's two orders a month are a generator's "two product mixes per visit", not independent purchases.
- **Visits precede orders.**
  - Events 1–4,393 are all `direct`. Events 4,394–9,073 mix all six channels, including 905 more `direct` [q3:event_series_stats].
  - Paired by rank within an account, each series-A order comes after its series-A visit: 4,306 of 4,306, 3,532 within an hour, and spread evenly over 0–30 minutes [q3:series_a_event_order_pairing, q3:series_a_gap_minutes].
  - 60 accounts have 1–5 more series-A visits than orders, which breaks the pairing for the rest [q3:series_a_extra_events].
  - Every order has a visit by its account in the previous 24 hours: 6,912 of 6,912 [q2:event_before_order].
- **Growth.** Orders by year are 99 (Dec 2013), 1,306, 1,725, 3,757 and 25 (1–2 Jan 2017). The monthly count rises steadily from 99 to 463 [q2:per_year, q2:per_month_orders].
  - Accounts start in 2013 (61), 2014 (20), 2015 (64), 2016 (201) and 2017 (5) [q3:accounts_start_month].
  - 285 of 350 accounts order in Dec 2016 or Jan 2017, so few accounts churn [q3:account_lifespan_ends].
- **No time-of-day or weekday structure.** Hours are flat: 330–424 events and 211–349 orders per hour. Weekdays are flat too [q2:event_hour_mix, q4:weekday_mix]. Times are uniform random seconds.
- **20 empty orders** have all three quantities 0 and $0.00 [q2:zero_qty_orders, q2:zero_total_rows]. 4,355 orders contain all three papers, 2,142 two and 395 one [q4:orders_with_zero_part].
- **Text oddities.**
  - Murphy USA's website is `corporate.murphyusa.com`, the only one without `www.` [q4:odd_website].
  - primary_poc names repeat across accounts [q4:poc_dups].
- **Events after the last order.** 152 accounts have web visits after their last order [q3:events_after_last_order].

## 5. Distributions to fit (stage 2)

| Quantity | Value |
|---|---|
| account arrivals | first visit dates: 61 in Dec 2013, then 20 / 64 / 201 / 5 per year [q3:accounts_start_month] |
| orders per account | 1–71; bands 1–5: 91, 6–10: 63, 11–20: 76, 21–40: 63, 41+: 57 [q2:orders_per_account] |
| order cadence | series A: one order per 28–31 days (mode 29–30 d); a series-B order on the same day for about 60% of A orders (2,606 / 4,306) [q3:monthly_day_drift, q3:order_series_stats] |
| visit → order lag | U(0, 30 min) for paired visits [q3:series_a_gap_minutes] |
| visits per account | 2–101; bands 1–5: 65, 6–10: 51, 11–20: 75, 21–40: 86, 41+: 74 [q2:events_per_account] |
| visit gaps | < 1 h 71, 1–24 h 900, 1–7 d 1,485, 7–31 d 6,132, > 31 d 134 [q4:event_gaps_hours] |
| channel mix | direct 58.4%, facebook 10.7%, organic 10.5%, adwords 10.0%, banner 5.2%, twitter 5.2% [q2:channel_mix]; stable by year [q4:channel_by_year] |
| quantities | standard mean 280 (max 22,591), gloss 147 (max 14,281), poster 105 (max 28,262); A versus B mixes as in §4 |
| order value | p10 740, p25 1,413, p50 2,483, p75 3,362, p90 6,856, p99 13,947, max 232,207 USD [q2:total_amt_quantiles] |
| time of day / week | uniform [q2:event_hour_mix, q4:weekday_mix] |
| accounts per rep | 3–15 [q2:accounts_per_rep] |

## 6. simkit mapping sketch

```python
p.entity("region", key="region_key", cols={"ext_id": i64(), "name": text()})
p.entity("sales_reps", key="rep_key", cols={"ext_id": i64(), "name": text(), "region_id": ref("region")})
p.entity("accounts", key="account_key", doc="created_at = first web visit",
         cols={"ext_id": i64(), "name": text(), "website": text(), "lat": f64(), "long": f64(),
               "primary_poc": text(), "sales_rep_id": ref("sales_reps")})
p.event("web_visited", cols={"account_id": ref("accounts"), "event_id": i64(doc="source id"),
        "channel": cat("direct", "facebook", "organic", "adwords", "banner", "twitter")})
p.event("order_placed", cols={"account_id": ref("accounts"), "order_id": i64(doc="source id"),
        "standard_qty": i64(), "gloss_qty": i64(), "poster_qty": i64()})
```

Ingest:
- `web_visited owner=account_id ord=event_id`, ORDER BY id.
- `order_placed owner=account_id ord=order_id`, ORDER BY id.
- The time is `occurred_at` as ISO text. Region and reps take `created_at = '2013-12-04 00:00:00'`. Accounts take the min `occurred_at` of their web events.

`build.sql`:
- `web_orders`: `order_id AS id`, the account ext_id, the time text (§3.1), the three quantities, `qs+qg+qp AS total`, `qs*499/100.0` and so on, and `(qs*499+qg*749+qp*812)/100.0 AS total_amt_usd`. DuckDB's `/` on integers and `100.0` gives the IEEE double, proven in [f2].
- `web_events`: the id, the account ext_id, the time text and the channel.
- The dimensions come from the entity views.

Stage-2 owners:
- **account**, with a start month, a monthly order clock (28–31 d), and an A mix plus an optional same-day B mix;
- a **visit process**: a direct visit 0–30 minutes before each A order, plus background visits with the channel mix.

The rep and region are static attributes. At about 16k events, no sample profile is needed.

## 7. Open questions and risks

- **Origin and licence.** The Udacity / Mode course origin is inferred from the table set, the counts, the prices and the Fortune-500 account order. The licence is unstated. Fitting statistics is fine; check before redistributing rows.
- **The series split is a generator artefact.** A stage-2 model that treats series A and B as two order kinds reproduces it. A model that pools them gets a bimodal mix and 2 orders a month. Choose one deliberately.
- **Account `created_at`** is the first visit, by rule. The source has no signup time.
- **The catalog-start rule for region and reps** (2013-12-04) is invented.
- **The 87 unpaired series-A visits** (60 accounts) make the rank pairing of visits and orders approximate. A visit → order link is therefore not exact, and should not be carried as a ref.

---

- Exact round trip: **yes**. The order money columns are integer-cent functions of the quantities (6,912 of 6,912 in Python and DuckDB), and the timestamps rebuild as `YYYY-MM-DDTHH:MM:SS.000Z` text.
- Proposed dataset name: **`parchposey`**.
- 2 event types (`web_visited`, `order_placed`; 15,985 events) and 3 entities (region 4, sales_reps 50, accounts 351).
- Event shape: **natural**. Both logs are timestamped per row; only region and the reps get rule times.
- Hardest blocker: none for stage 1. The money must be rebuilt from integer cents (naive float math fails on 1,749 totals), and the id order (two series, not time order) must be kept as carried ids.
