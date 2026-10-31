# complex_oracle (Spider 2.0-lite): Oracle Sales History (SH) as an event log

Source: `data/spider2/complex_oracle.sqlite` (52 MB), opened read-only. `scripts/oraclesh/oq.py` copies the file into an in-memory SQLite, adds indexes to the copy only, and runs the `-- name:` blocks of a `.sql` file. A reference such as `[q4:amount_vs_unit_price]` means file `q4_sales.sql`, block `amount_vs_unit_price`; the raw outputs are next to the scripts (`q*_out.txt`, `*_out.txt`). The Python scripts are `upstream_compare.py`, `times_check.py`, `dists.py` and `typeof_all.py`, all run with `python3 -I` and `mode=ro`.

Paths: DB folder `data/spider2/` (see `refdata fetch`); scripts [`scripts/oraclesh/`](scripts/oraclesh/).

---

## 0. What this catalog is

- **Dataset.** It is Oracle's **Sales History (SH) sample schema, release 23.1** (schema version 21; `sh_populate.sql` says release date 06-DEC-2022). The source is `github.com/oracle-samples/db-sample-schemas`, folder `sales_history/`, commit `453bfac571` (2023-04-18, "23.1 sample schema release"). The later commits to that folder change only docs and demographics.
- **Evidence** (`upstream_compare.py`, with the upstream files downloaded into the scratchpad):
  - `sales`, `costs`, `times`, `customers`, `promotions` and `supplementary_demographics` equal the upstream CSVs as multisets after normalisation, with no differences at all: 918,843 / 82,112 / 1,826 / 55,500 / 503 / 4,500 rows.
  - `sales`, `costs` and `times` are also in CSV row order (918,843 / 918,843 rowids in the same position). `customers`, `promotions` and the demographics are in a different order.
  - `countries` (35) equals the upstream INSERTs on (id, ISO code, name). `channels` has the same 5 ids and names.
  - **`products` does not match.** Upstream inserts 72 products. Spider has 24: the **first 21 upstream INSERTs** (14, 21, 22, 46, 47, 127–130, 19, 23, 28, 30, 31, 40–45, 48; names and descriptions identical), plus **3 ids that exist in no upstream version: 49 "Outdoor Cricket Ball", 50 "Cricket Gloves" and 51 "Cricket Bat Pad"**. No sales or costs rows use them. `sh_populate.sql` has had 72 products in every commit since 2023-04.
  - **`currency` is not in SH.** It is a pure function of `countries` (§3.4). Its shape (VARCHAR2(20) country, year, month, `to_us`) looks like the currency table of Oracle's MODEL-clause sales-projection example, which projects France's sales, but I could not find that page (Open questions).
  - Upstream dates are already 2019–2023. Oracle shifted the classic 1998–2002 SH data forward by 21 years in this release, so the date shift is Oracle's, not Spider's (§3.3).
- **Nature: generated.** SH is a synthetic data-warehouse demo; the customer names, addresses and e-mails (`…@company.example.com`) are invented. Generator fingerprints are in §4.
- **Licence.** The repository is **MIT**: `LICENSE.txt` says "Copyright (c) 2023 Oracle and/or its affiliates", and the GitHub API reports `spdx_id: MIT`. The README has a "License" section that points to it. Spider 2.0 redistributes the data, and its own repo is MIT. Of the reference datasets so far, this one has the most permissive terms.
- **Spider changes.**
  - `products` was truncated and padded (above).
  - `currency` was added.
  - Three SQLite views were added: `profits` (sales ⋈ costs, with `TOTAL_COST = unit_cost × quantity_sold`), `cal_month_sales_mv` and `fweek_pscat_sales_mv`. They are Oracle's materialized views written as plain views.
  - Every FK is declared, but none is enforced.
  - Dates are TEXT.

**Row counts** [q1:row_counts]

| Table | Rows |
|---|---:|
| sales | 918,843 |
| costs | 82,112 |
| customers | 55,500 |
| supplementary_demographics | 4,500 |
| times | 1,826 |
| currency | 1,260 |
| promotions | 503 |
| countries | 35 |
| products | 24 |
| channels | 5 |

## 0.1 How Spider 2.0 uses it

There are 6 questions for db `complex_oracle`. **None has gold SQL**: `evaluation_suite/gold/sql/<id>.sql` returns 404 for all six. Every one has `exec_result/<id>_{a,b,c}.csv` variants. I reproduced the values marked ✔ (`q7_spider.sql`).

| id | analysis | gold SQL? | gold CSV vs mine |
|---|---|---|---|
| local060 | US, promo 999, Q4 2019 vs Q4 2020. Cities with sales up ≥ 20%; top 20% of products by sales; share change | no | ✔ `_a` exactly (28 +0.02550, 130 −0.00954, 14 −0.01725, 21 −0.03871) [q7:local060_all_products]. `_b` also lists product 40 (a different top-20% cut, same shares) |
| local063 | same filter; the top-20% product with the smallest share change | no | ✔ `_a` and `_b`: 130 Pro Maple Youth Bat, 0.009545 pp |
| local061 | France, promo_total_id = 1, channel_total_id = 1. Projected 2021 monthly sales = ((s20 − s19)/s19)·s20 + s20, in USD, averaged per month | no (external knowledge `projection_calculation.md`) | ✔ all 12 months of `_a` (Jan 4054.994325…, Dec 3062.664368…) [q7:local061] |
| local050 | median of local061's 12 monthly averages | no | ✔ `_a` 2552.6959807204075 [q7:local050]. `_b` and `_c` (2077.39, 2014.66) use other readings |
| local062 | Italian customers, Dec 2021, profit = qty·(unit_price − unit_cost); 10 equal-width buckets | no | ✔ `_a`: all 10 buckets (29, 17, 5, 3, 4, 1, 1, 2, 2, 4 customers; min −23.56, max 785.15) [q7:local062] |
| local067 | the same customers in 10 NTILE tiers, min/max profit | no | tiers 3–10 of `_a` match exactly. Tiers 1–2 do not (gold min −27.94; mine −23.56) [q7:local067_ntile]. Per-line and per-(cust, prod) variants do not match either |

Consequences for the round trip:
- **local060 and local063 depend on the orphan sales rows.** The shares use the total over all 72 sold prod_ids, including the 51 with no `products` row; only the final name join drops them. So the orphans must be kept exactly.
- local062 and local067 depend on `costs` matching `sales` on all four keys.
- local061 and local050 depend on `currency` and on `promotions.promo_total_id` and `channels.channel_total_id`.

## 1. Inventory, keys, joins

| Table | Rows | Key (verified unique) | Kind |
|---|---:|---|---|
| sales | 918,843 | none declared. **(prod, cust, time, channel, promo) is unique: 918,843 keys, multiplicity 1 everywhere** [q1:sales_key_dups, sales_key_multiplicity] | activity (fact) |
| costs | 82,112 | (prod, time, channel, promo) unique [q1:costs_key_dups] | activity (daily price/cost fact) |
| times | 1,826 | time_id, 2019-01-01..2023-12-31 | calendar dimension |
| customers | 55,500 | cust_id (1..104,500, with gaps) | dimension |
| supplementary_demographics | 4,500 | cust_id (100,001..104,500) | 1:1 extension of customers |
| promotions | 503 | promo_id | dimension |
| products | 24 | prod_id | dimension (truncated) |
| channels | 5 | channel_id (2, 3, 4, 5, 9) | dimension |
| countries | 35 | country_id (52,769..52,803) | dimension |
| currency | 1,260 | (country, year, month) unique [q1:pk_unique] | derived lookup |

**FK coverage** (child rows that find a parent) [q1:fk_coverage]:

| FK | coverage |
|---|---|
| sales.prod_id → products | **304,780 / 918,843 = 33.2%** |
| costs.prod_id → products | **25,792 / 82,112 = 31.4%** |
| sales → customers, times, channels, promotions | 100% each |
| costs → times, channels, promotions | 100% each |
| customers → countries | 100% |
| demographics → customers | 100% |

The product orphans come from **51 prod_ids** (13, 15–18, 20, 24–27, 29, 32–39, 113–126, 131–148). They are the upstream products that Spider dropped [q2:sales_prod_ids].

**Sales vs costs** [q1:sales_to_costs, q1:costs_to_sales, q4:distinct_sales_keys_4, q4:unmatched_*]:
- Every costs row matches at least one sales row on (prod, time, channel, promo): 82,112 / 82,112.
- Sales have 82,249 distinct such keys; 916,039 / 918,843 sales rows find a costs row. So `costs` is **one row per (product, day, channel, promo) that had a sale**, not a price list.
- The 2,804 sales rows without costs are:
  - all 2,074 **Tele Sales** rows (channel 9, promo 33; 67 keys);
  - 730 Internet + promo 350 rows on 70 keys, 2021-01-31..2021-06-30, almost all on month-end days.
- `profits` therefore has 916,039 rows [q7:profits_view_rows].

**Reverse coverage** [q1:reverse_coverage]:
- 21 of 24 products are sold (49–51 never are).
- **7,059 of 55,500 customers** buy.
- 1,459 of 1,826 days have sales. The missing days are all of 2023, plus 2020-02-28 and 2022-04-07 [q4:days_without_sales_list].
- 4 of 503 promotions are used: 999 "NO PROMOTION" 96.63% of lines, 350 1.96%, 351 1.19%, 33 0.23%.
- 4 of 5 channels are used: Catalog (5) never is.
- 19 of 35 countries have customers.
- Only 940 of the 4,500 demographics customers buy [q5:cust_id_ranges].

The graph is a star. `sales` is the fact; `costs` hangs off it on 4 of its 5 keys; the dimensions are static. Buyers are drawn from cust_id ≤ 101,000 [q5:buyers_cust_id_range].

## 2. Event catalog

`T(d)` is the date `d` read as midnight UTC (dates only, no time zone). N = 2022-12-31, the last sale.

| # | Event | Owner (partition) | Time | Attributes | Source rows | Count |
|---|---|---|---|---|---|---:|
| E1 | `price_quoted` | product | T(costs.time_id) | channel_id, promo_id, unit_cost, unit_price | one per costs row | 82,112 |
| E2 | `unit_sold` | customer | T(sales.time_id) | prod_id, channel_id, promo_id, quantity_sold (always 1), amount_sold | one per sales row | 918,843 |

**What a "sale event" is.**
- Each sales row is **one unit** (quantity_sold = 1 on 918,843 / 918,843) [q4:quantity_values].
- No 5-key repeats, so no row has been aggregated from several events and nothing needs splitting [q1:sales_key_multiplicity, sales_exact_dup_multiplicity].
- But the unique 5-key means the generator never sells two units of a product to the same customer on the same day through the same channel and promo, and quantity never exceeds 1. A row is therefore "this customer bought this product on this day through this channel and promo", at day grain. A simulator must enforce that uniqueness, or collapse repeats.
- The same customer does buy the same product on the same day through **different** channels: 189,320 (cust, prod, day) groups [q4:cust_prod_day_multi_channel].

**E1 is a daily quote that sales consume.**
- `amount_sold` = the matching `unit_price` on **914,942 / 916,039** matched rows (99.88%) [q4:amount_vs_unit_price].
- The other 1,097 rows sit in exactly 48 (prod, day, channel, promo) keys. Each of those keys has two amounts, and **neither** equals unit_price [q5:ne_by_key_amounts]. 333 of the 1,097 are in 2019-12 [q5:ne_timing].
- So the price is carried on E2 rather than looked up. E1 comes before E2 within a day: block order in ingest puts costs first.
- `costs` exists only where sales exist (§1), so in stage 2 E1 is emitted on a product's first sale of the day per channel and promo. Tele Sales gets none, and the 70 promo-350 month-end keys are an anomaly to reproduce or drop.

**Entities** (static; no source creation times):

| Entity | Key | Rows | Notes |
|---|---|---:|---|
| `countries` | country_id | 35 | all 9 columns |
| `channels` | channel_id | 5 | all 6 columns |
| `promotions` | promo_id | 503 | all 11 columns. Begin/end dates are attributes (999 has 9999-01-01) |
| `products` | prod_id | **75** = 24 catalogued + 51 ghosts | `catalogued` flag. The ghosts hold only `ext_id`, the other columns are NULL, and the view keeps catalogued rows only |
| `customers` | cust_id | 55,500 | all 23 columns. `created_at` = cust_eff_from (2019-01-01 on all rows [q5:customers_constants]) |
| `demographics` | cust_id (`ref(customers)`) | 4,500 | the 13 non-key columns; a separate entity because only 8.1% of customers have a row |
| `times` | time_id | 1,826 | stored, not generated: 10 columns are not calendar arithmetic (§3.3). Optionally store only those and the view computes the other 28 |

**Not entities, and why:**
- `currency` is a rule over `countries` (§3.4), so the view generates it.
- `profits`, `cal_month_sales_mv` and `fweek_pscat_sales_mv` are views. The rebuild re-creates them from DDL.
- Customer lifecycle has no events: `cust_valid` is static, and A ⊇ buyers (all 7,059 buyers are A, plus 3,562 non-buyers [q5:cust_valid_mix]).
- Promotions have no "started" or "ended" events: sales under a promo happen **outside** its window. Promo 350 has 0 of 18,022 lines inside 2020-01-27..04-27, and 351 has 0 of 10,910 [q5:sales_in_promo_window]. So the dates do not order anything.

## 3. Rebuild rules and blockers to an exact round trip

| Table | Rule | Exact? |
|---|---|---|
| sales | project E2. `time_id` = strftime(event_time, '%Y-%m-%d'); prod_id = the product's `ext_id`, ghosts included | yes |
| costs | project E1 | yes |
| products | entity rows where `catalogued`; text columns verbatim | yes, with the `''` care below |
| customers, promotions, channels, countries | entity rows verbatim | yes |
| supplementary_demographics | entity rows | yes |
| times | entity (stored columns) + the calendar formulas for the derivable ones | yes (§3.3) |
| currency | the rule in §3.4, generated in the view | yes (0 differences both ways) |
| views (profits …) | DDL only | needs DDL copy in `rebuild` |

### 3.1 Products and orphan ids (the main blocker)

- `ref("products")` on E1/E2 would fail on 614,063 sales rows and 56,320 costs rows, because "an unmatched id is an error" in refdata.
- Two options:
  - (a) **Ghost product entities**: 51 rows with only `ext_id` and `catalogued = false`. This keeps a ref, and stage 2 can sell all 72 sold products.
  - (b) Carry prod_id as a plain `i64` on the events and drop the ref.
- I recommend (a). Spider questions local060 and local063 need the orphan rows in their denominators.
- Products 49–51 are catalogued but never sold, so they must exist as entities without events.

### 3.2 Text, NULL and number formats [`typeof_all.py`, q1:time_text_formats]

- **`products.prod_src_id` is `''` (text) in an INTEGER column on all 24 rows, and `prod_eff_to` is `''`.** But `customers.cust_src_id` and `cust_eff_to` are real NULL on all 55,500 rows. Keep `''` and NULL apart: use `opt(text)` for the product columns.
- `prod_eff_from` is `'2019-01-01 00:00:00'` (19 characters). Every other date is `YYYY-MM-DD` (10 characters).
- Real NULLs: `cust_marital_status` 17,506, `cust_income_level` 41, `comments` 205. The upstream CSV has empty fields there, and Spider loaded them as NULL.
- `cust_postal_code` and `household_size` are TEXT (`'44581'`, `'4-5'`, `'9+'`). Do not cast them.
- Money:
  - `amount_sold`, `unit_cost` and `unit_price` are REAL on the exact cent grid: 0 values off the grid [q4:amount_grid, costs_grid], so `amount()` in cents is lossless.
  - **`unit_cost` can be negative** (102 rows, product 120, 2021-11/12, down to −23.74) and exceeds unit_price on 243 rows [q5:negative_costs]. So the amount type must allow negative values.
  - `promo_cost`, `cust_credit_limit` and the list/min prices are REAL with integral or cent values; store them as `f64`, or as `amount` where they are cents.
- No trailing spaces and no CR/LF anywhere [q5:text_trailing_spaces, supp_comments_crlf]. The upstream CSV pads `AMOUNT_SOLD` with spaces, but Spider stored numbers, so nothing carries over.

### 3.3 `times` is not pure calendar arithmetic (`times_check.py`)

The 38 columns split four ways:

| Group | Columns | Derivable? |
|---|---|---|
| A. Pure function of time_id (17 + time_id) | day_name, day_number_in_week (Mon = 1), day_number_in_month, calendar_week_number (Oracle `WW`: ⌊(doy−1)/7⌋+1), fiscal_week_number (= calendar_week_number on 1,826/1,826), week_ending_day (next Sunday), calendar_month_number/desc/name, days_in_cal_month, end_of_cal_month, calendar_quarter_desc/number, end_of_cal_quarter, calendar_year, days_in_cal_year, end_of_cal_year | **yes, 1,826 / 1,826 each** |
| B. Function of (fiscal_year, fiscal_month_number) | fiscal_month_desc, fiscal_month_name, fiscal_quarter_number, fiscal_quarter_desc | yes, 1,826 / 1,826, given group D |
| C. Id lookups | calendar_month_id, fiscal_month_id, calendar_quarter_id, fiscal_quarter_id, calendar_year_id, fiscal_year_id | 1:1 with their descriptions [q3:fd_ids]. They are base + rank up to 2022, then **break in 2023**: calendar_month 2023-01 = 1812, calendar_year 2023 = 1813, fiscal_year 2024 = 2259 [times_check:id columns]. They need a small lookup table (60 + 61 + 20 + 21 + 5 + 6 values) |
| D. Data | fiscal_year, fiscal_month_number, week_ending_day_id, days_in_cal_quarter, days_in_fis_month, days_in_fis_quarter, days_in_fis_year, end_of_fis_month, end_of_fis_quarter, end_of_fis_year | **no** |

Why group D is not derivable:
- **`days_in_cal_quarter` is wrong on 181 rows.** Q1 says 90 in leap-year 2020 (91 rows) and 91 in 2021 (90 rows) [q3:days_in_cal_quarter_mismatch].
- **`week_ending_day_id` is not a function of `week_ending_day`.** All 261 weeks carry 2 ids [q3:fd_ids]. Its 262 groups are mostly 7-day Saturday–Friday runs (4 are not 7 days); no weekday boundary fits all of them [times_check:week_ending_day_id].
- **The fiscal calendar is 4-4-5 weeks** (28/28/35 days) with irregular year ends: fiscal 2019 is 361 days, 2021 has 370 rows but says 371, and 2024 holds 2 rows [q3:fiscal_years].
  - Fiscal months end on Friday 47 times, Saturday 13 and Sunday 1.
  - `days_in_fis_month` disagrees with the actual group size on 58 rows (2020-02 holds 29 days but says 28; 2021-03 holds 27 days but says 28).
  - `days_in_fis_quarter` disagrees on 275 rows; fiscal quarter 2023-01 says 1 day and ends 2022-12-31.
  - `days_in_fis_year` disagrees on 737 rows [times_check:fiscal columns].
- **Reading:** Oracle moved the classic 1998–2002 SH calendar forward by 21 years (7,670 days ≡ 5 mod 7).
  - It recomputed the names and the calendar fields of group A.
  - It carried the year-dependent and week-dependent values over from the old dates. Leap-year 2000 → 2021 explains Q1 = 91 in 2021, and Sunday-ending weeks become Friday-ending.
  - This is inferred from the pattern, not documented.
- **Decision:** store `times` as an entity, either with all 38 columns or with groups C and D only (16 columns, plus the lookup). The view computes A and B. Either way it is a dimension snapshot, not an event, and it extends one year past N (2023, no sales).

### 3.4 `currency` is a rule, so the view generates it [q6:rule_vs_table]

```sql
SELECT substr(country_name, 1, 20) AS country, y AS year, m AS month,
       CASE WHEN country_name = 'Canada' THEN 0.74 ELSE 1.0 END AS to_us
FROM countries, (2019, 2020, 2021) AS y, (1..12) AS m      -- 35 × 3 × 12 = 1,260
```

- The rule gives 1,260 rows, and EXCEPT is 0 both ways.
- `substr(…, 1, 20)` explains `'United States of Ame'`, the one currency country that does not join to `countries` [q2:currency_vs_countries].
- The rows are contiguous per country, in `country_id` order (35/35) [q6:rowid_country_contiguous, country_order_vs_id].
- Every rate is 1.0 except Canada (0.74). No rate varies by month [q2:currency_countries].
- Store nothing. The year range (2019–2021) and the Canada rate are constants in `views.sql`.

### 3.5 Times, ordering, snapshot

- Every event time is a date, so it is midnight. N = 2022-12-31. There are no invented times: E1 and E2 carry their own dates.
- Entity `created_at`:
  - customers: cust_eff_from;
  - products: prod_eff_from (2019-01-01; ghosts the same);
  - the other dimensions: 2019-01-01.
  - Never use the 9999-01-01 promo dates.
- Row order: `sales` and `costs` are in upstream CSV order, which is neither time nor key order.
  - Sales come in 6,960 runs of one prod_id. Within a (prod, day) run, cust_id rises in 823,442 of 823,462 adjacent same-(channel, promo) pairs [q4:rowid_order*]. This looks like Oracle's partitioned load order.
  - Multiset comparison makes the order irrelevant. If byte order mattered, carry `src_rowid`.

## 4. Measured quirks

- **Products truncated to 24 of 72, with 3 invented** (§0, §3.1): 66.8% of sales lines and 68.6% of costs rows are orphans.
- **Tele Sales and 70 promo-350 keys have no costs** (2,804 lines). `profits`-based questions silently drop them.
- **amount_sold ≠ unit_price** on 1,097 lines in 48 keys (two amounts per key, neither the quoted price).
- **Negative unit cost** on 102 rows (product 120, Nov–Dec 2021, all 3 channels). Cost > price on 243 rows, clustered in Nov–Dec 2021 and Feb 2022 [q5:cost_gt_price_detail]. The margin (price − cost)/price has p50 0.179 and max 4.48 [dists].
- **Promotions out of window.** Promo 33: 407 of 2,074 lines inside its window. 350 and 351: 0 inside. 351's sales run 2022-02..12, after its 2021 window [q5:sales_in_promo_window].
- **Customers.**
  - Only 1,706 distinct e-mails and 51,000 phone numbers for 55,500 customers. 4,397 (last, first) name pairs repeat [q5:customers_fd, typeof_all].
  - `cust_valid = 'I'` customers (44,879) never buy.
  - City → city_id, state, country are clean functions (620 cities, 145 states, 0 violations).
  - The first name `'Nan'` exists: a naive CSV/pandas load turns it into NaN. `upstream_compare.py` had to guard against that.
- **Countries.** Chile has `country_region_id` 52798 (its subregion id) instead of the Americas id 52801 [q5:countries_quirk]. Upstream has it too. 16 countries have no customers. South Africa has 88 customers and 0 buyers.
- **times** (§3.3): the wrong leap-year Q1 lengths, the drifting week ids, and the fiscal day counts that disagree with their groups.
- **Day-of-month fingerprint.** Lines per day of month are far from uniform: day 18 has 60,437 lines, day 27 has 54,661, and the median day has 2.96% of lines [dists]. Weekday is flat (13.9–14.9%).
- **Two calendar holes:** 2020-02-28 and 2022-04-07 have no sales.

## 5. Distributions to fit (`dists.py`)

| metric | value |
|---|---|
| lines per year | 2019 178,834 · 2020 247,945 · 2021 232,646 · 2022 259,418 |
| revenue per year | 24.08M · 22.22M · 23.77M · 28.14M |
| lines per month | 11.6k (2019-06) to 24.5k (2022-10); 2021-12 dips to 14.7k |
| lines per selling day | p5 139, p50 512, p90 1,202, p99 2,140, max 2,940 |
| channel mix (lines) | Direct 58.81%, Partners 28.08%, Internet 12.89%, Tele 0.23%, Catalog 0 |
| promo mix (lines) | none 96.63%, 350 1.96%, 351 1.19%, 33 0.23% |
| amount_sold | p5 8.54, p25 17.38, p50 34.24, p75 53.89, p90 176.86, p99 1,487.63, max 1,782.72, mean 106.88 |
| lines per buyer | p25 65, p50 134, p75 218, p90 243, max 283 (n = 7,059) |
| active days per buyer | p50 19, p90 34, p99 117; 14.4% buy on one day only |
| gap between a buyer's active days | p25 2 d, p50 9 d, p75 29 d, p90 61 d, p99 547 d |
| buyer lifespan (first → last day) | p25 183 d, p50 850 d, p90 1,401 d |
| first purchase year | 2019 5,469, 2020 1,026, 2021 525, 2022 39 (the population is mostly acquired in year 1) |
| lines per (buyer, day) | p50 4, p90 15, p99 36, max 86; 1 line in 35,122 of 143,139 baskets |
| channels per (buyer, day) | 1: 81,340; 2: 45,036; 3: 16,763 [q4:cust_day_channels] |
| concentration | buyers: the top 1% have 5.3% of revenue and the top 10% have 31.8%. Products: the top 10 of 72 have 25.3% of lines; lines per product p50 12,429, min 710 (prod 136) |
| buyers by country | US 58.0%, DE 10.6%, UK 7.4%, IT 5.0%, JP 4.9%, FR 4.4%, AU 2.8%, other ≤ 1.5% |
| unit_price | p50 38.12, p90 530.86, max 1,782.72. Distinct prices per (prod, month): p50 3, p90 7. CV within (prod, month): p50 0.008, p90 0.127 |
| unit_price / list price (24 products) | p5 0.936, p50 1.061, p90 1.173, p99 2.44; max 36.1× |
| costs rows per (prod, day) | 1: 7,563 · 2: 12,692 · 3: 14,588 · 4: 1,336 · 5–7: 10 |
| customers (dimension) | M 67.0% / F 33.0% (buyers 65.1 / 34.9). Year of birth 1924–2001. Credit limit 8 levels (1,500 20.4%, 9,000 16.4%, 7,000 15.6% …). Income 12 bands plus 41 NULL |
| promotions (dimension) | 502 real: TV 22.9%, newspaper 21.9%, internet 16.9% …. Cost p50 51,700. Durations 61 d (127), 31 d (118), 91–92 d (167) |

## 6. simkit mapping sketch

```python
p.entity("countries",  key="country_id", cols={"ext_id": text(), "country_iso_code": text(), "country_name": text(), ...})
p.entity("channels",   key="channel_id", cols={"ext_id": text(), "channel_desc": cat(...), "channel_class": cat(...), ...})
p.entity("promotions", key="promo_id",   cols={"ext_id": text(), "promo_name": text(), "promo_category": cat(...),
                                               "promo_cost": f64(), "promo_begin_date": text(), "promo_end_date": text(), ...})
p.entity("products",   key="prod_id",    cols={"ext_id": text(), "catalogued": i64(), "prod_name": opt(text()), ...,
                                               "prod_src_id": opt(text()), "prod_eff_from": opt(text()), "prod_eff_to": opt(text())})
p.entity("customers",  key="cust_id",    cols={"ext_id": text(), "country_id": ref("countries"), "cust_city_id": i64(), ...,
                                               "cust_marital_status": opt(text()), "cust_credit_limit": f64(), "cust_valid": cat("A", "I")})
p.entity("demographics", key="demo_id",  cols={"ext_id": text(), "cust_id": ref("customers"), "education": cat(...), ...,
                                               "comments": opt(text())})
p.entity("times",      key="day_id",     cols={"ext_id": text(), "fiscal_year": i64(), "fiscal_month_number": i64(),
                                               "week_ending_day_id": i64(), ...})   # groups C+D, or all 38
p.event("price_quoted", cols={"prod_id": ref("products"), "channel_id": ref("channels"), "promo_id": ref("promotions"),
                              "unit_cost": amount("USD"), "unit_price": amount("USD")})
p.event("unit_sold",    cols={"cust_id": ref("customers"), "prod_id": ref("products"), "channel_id": ref("channels"),
                              "promo_id": ref("promotions"), "quantity_sold": i64(), "amount_sold": amount("USD")})
```

Ingest:
- `-- event: price_quoted owner=prod_id`, ORDER BY prod_id, time_id, channel_id, promo_id. It is placed **before** `unit_sold`, so that on equal times the block position puts the quote first.
- `-- event: unit_sold owner=cust_id ord=src_rowid` (optional), ORDER BY time_id, cust_id, prod_id, channel_id, promo_id.
- The `products` entity is the UNION of `products` and the distinct prod_ids of sales and costs (75 rows).
- `currency` has no block; `views.sql` generates it (§3.4).

Stage 2 behaviour:
- **Customer owners** (about 7k active of 55.5k). Use a Source with heavy year-1 acquisition (77% of buyers first buy in 2019).
- Each active day draws a basket: lines per basket p50 4, 1–3 channels. Each line is a unique (product, channel, promo) for that day.
- Inter-visit gaps follow the heavy-tailed distribution above, p50 9 d.
- A **product shard** quotes a daily price per channel on first demand (E1); the sale copies it. Add rare overrides (0.12%) if the 48 anomalous keys matter.
- Promo choice is a 3.4% branch, and it is independent of the promo window.
- Reproduce the day-of-month bias, or deliberately do not.
- Volume: 1.0M events (82k + 919k) plus 55.5k + 4.5k + 1.8k + 0.6k entity rows. That sits in the 10⁵–10⁶ comfort zone, at roughly 4–5 s scaled from olist. A `sample` profile at 10% of buyers gives about 100k events.

Checks:
- `unique(unit_sold, [cust_id, prod_id, time, channel_id, promo_id])`.
- `quantity_sold == 1`.
- `amount_sold == price_quoted.unit_price` as a soft law, with a 0.12% violation rate.
- **No `unit_cost ≥ 0` law**: 102 rows break it.
- **No "sale within promo window" law**: 30,599 promo lines break it (all 28,932 lines of 350 and 351, plus 1,667 of 33).

## 7. Open questions and risks

- **Where do products 49–51 come from, and why only 24 products?** They exist in no commit of `oracle-samples/db-sample-schemas`. Perhaps Spider used a third-party port or hand-edited the table. The round trip does not care; stage 2 must decide whether to generate the 51 ghost products as real catalogue rows.
- **Currency provenance.** I believe it comes from the Oracle Data Warehousing Guide's MODEL-clause projection example (a `currency` table with `to_us`, built from `countries × times` with `SUBSTR(country_name, 1, 20)` and Canada = .74, originally for 2000–2002). I could not retrieve that page (searches and the 10g/19c "SQL for Modeling" chapters did not show it), so treat this as unverified. The data-side rule is verified exactly.
- **times group D.** The 21-year-shift explanation is an inference. If stage 2 wants a clean calendar, it must accept differing values in 10 columns. That is safe only if no saved query reads `days_in_*_quarter`, `days_in_fis_*` or `week_ending_day_id`; none of the 6 Spider questions does.
- **local067 tiers 1–2** do not match any reading I tried (per customer, per line, per customer-product). The gold min −27.94 may come from a different profit expression. Keep local067 as a source-vs-rebuilt check, not against gold. local060's `_b` cut includes product 40; NTILE vs PERCENT_RANK readings differ.
- **Licence.** MIT, Oracle 2023. Low risk, but keep the copyright notice with anything that ships the data or derived fitted parameters.
- **Rebuild must re-create the 3 views** (`profits`, `cal_month_sales_mv`, `fweek_pscat_sales_mv`), or saved queries that use `profits` will fail on the rebuilt file. I have not checked whether `refdata rebuild` copies views as well as tables.
- **Sale grain.** The data cannot tell a real one-unit line from a deduplicated day-level fact. Upstream calls it `NUMBER(3)` quantity but never uses more than 1. Stage 2 should keep quantity = 1 and the 5-key uniqueness.

## Summary

- **Feasible for an exact round trip: yes, with caveats.** Every table is either a verbatim projection or an exact rule (currency).
- **Project name:** `oraclesh`, on source `complex_oracle.sqlite`, MIT (Oracle SH 23.1).
- **Events: 2.** `price_quoted` (82,112) and `unit_sold` (918,843), about 1.0M in total. There are no invented times.
- **Entities: 7.** countries, channels, promotions, products (75, with 51 ghosts), customers, demographics, times. `currency` and the 3 views are generated.
- **Hardest blocker:** `products` holds 24 of the 72 sold products (3 of them invented), so 66.8% of sales lines are orphans that the Spider gold answers still count. The pack needs 51 ghost product entities. A second blocker: 10 columns of `times` are not calendar arithmetic, so they must be stored.
