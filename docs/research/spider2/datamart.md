# Data Mart (Spider 2.0-lite, `bank_sales_trading`): reverse-engineered event log

Source: the tables `weekly_sales` and `cleaned_weekly_sales` of `data/spider2/bank_sales_trading.sqlite`, opened read-only. The other table groups in this file (`bitcoin_*`, `customer_*`, `shopping_cart_*`, `veg_*`, `interest_*`) are other catalogs; see `bitcoin.md`, `bank_clicklog.md`, `veg.md` and `freshsegments.md`.

`scripts/datamart/rq.py` copies the file into an in-memory SQLite and runs named blocks; the file itself is never written. It is northwind's runner, changed to allow DDL blocks. Every number below comes from one of these:
- a named block in `scripts/datamart/q*.sql`;
- `f1_duck_rules.py` (DuckDB 1.5.6, the views engine).

Raw outputs are `scripts/datamart/out_*.txt`. `[q2:per_column_matches]` means file `q2_derived.sql`, block `-- name: per_column_matches`. Gold files are in `scripts/datamart/gold/`.

## 0. What this catalog is

- **Dataset.** This is **Case Study #5 "Data Mart"** of Danny Ma's *8 Week SQL Challenge*. The evidence:
  - The schema matches the case study exactly: `week_date`, `region`, `platform` (Retail/Shopify), `segment`, `customer_type` (New/Existing/Guest), `transactions`, `sales` [q1:typeof_weekly_sales].
  - `week_date` is the case study's `d/m/yy` text (`31/8/20`) [q1:week_date_formats].
  - The case study's "sustainable packaging" change date is 2020-06-15. Both Spider questions pivot on 15 June.
  - `cleaned_weekly_sales` is the case study's step-1 "data cleansing" table, and it follows the step-1 rules exactly (§3). It has the same name the published solutions use.
- **Spider changes.** Two things differ from the PostgreSQL original:
  - The missing segment is SQL `NULL` (3,024 rows). The original holds the text `'null'`, and here there are 0 rows of `'null'` and 0 of `''` [q1:null_empty_counts].
  - `cleaned_weekly_sales` adds `week_date_formatted` (`2020-8-31`, no zero padding) next to an ISO `week_date`.
- **Row counts** [q1:row_counts]: `weekly_sales` 17,117; `cleaned_weekly_sales` 17,117.
- **Licence.** Unstated. The 8 Week SQL Challenge publishes its datasets for learning, with no licence file.
- **Nature.** Generated course data. Pre-aggregated weekly totals for a fictional online supermarket (`72 weeks × 7 regions × 2 platforms × 17 segment/type cells` with 19 cells missing). There is no finer grain.

## 0.1 How Spider 2.0 uses it

Two of the 15 `bank_sales_trading` questions use these tables. Both read `cleaned_weekly_sales`.

| id | asks | gold SQL? | reproduced |
|---|---|---|---|
| local301 | % change in sales, the 4 weeks before 15 June vs the 4 weeks after, for 2018, 2019 and 2020 | yes (`gold/local301.sql`) + 3 CSVs | ✔ The gold SQL gives 0.193027 / 0.103849 / −1.146018 % (raw), which is `local301_a.csv` to 6 dp [q4:local301_gold_sql]. Windows are week_dates with `round((d − June 15)/7)+1` ∈ [−3, 0] and [1, 4]: 2018-05-21..06-11 vs 06-18..07-09 [q4:local301_weeks_in_windows]. `local301_c.csv` matches 2018 and 2019 (pre, post); its 2020 post total differs (2,334,905,223 vs 2,318,994,169) |
| local302 | average % change, 12 weeks before vs 12 weeks from 2020-06-15, per attribute value, averaged per attribute type (region, platform, age_band, demographic, customer_type); worst type | no; 2 CSVs | ✔ demographic, −2.008666666667, exactly, **when each value's % is rounded to 3 dp before averaging** [q4:local302_by_attr]. The raw mean is −2.00866186; the 2-dp mean is −2.01. The ranking of types (demographic < age_band < customer_type < region < platform) is the same under all three |

Both questions need `week_date`, the derived `age_band`/`demographic`, and `sales` exactly. local302 also needs the exact per-value totals [q4:local302_values].

## 1. Inventory, keys, joins

No PK or FK is declared.

| Table | Rows | Key (measured unique) | Kind |
|---|---:|---|---|
| weekly_sales | 17,117 | (week_date, region, platform, segment NULL-safe, customer_type) [q1:key_uniqueness] | pre-aggregated fact |
| cleaned_weekly_sales | 17,117 | same key, segment `'unknown'` for NULL [q1:key_uniqueness_cleaned] | **derived**: an exact function of weekly_sales (§3.1) |

- **Dimensions** [q1:dimension_values, q1:segment_by_customer_type]:
  - region: 7 values, 2,436–2,448 rows each;
  - platform: Retail 8,568, Shopify 8,549;
  - segment: C1–C4, F1–F3 and NULL (3,024);
  - customer_type: Existing 8,064, New 8,045, Guest 1,008.
- **Guest is always segment NULL** (1,008 of 1,008). New and Existing have all 8 segment values. So there are 17 (segment, type) combinations.
- **Grid:** 72 weeks × 7 × 2 × 17 = 17,136 cells, of which 17,117 are present [q3:grid_vs_rows]. 53 weeks have 238 rows and 19 have 237 [q1:rows_per_week].
- **The 19 missing cells** are all Shopify × New × {C4, F3}, in EUROPE (12) or SOUTH AMERICA (7) [q3:missing_cells]. These are the smallest cells, where sales run 0–99 when present [q3:low_sales_rows]. Read them as "no sales that week", not as data loss.
- **Rows align by rowid:** cleaned row *i* is weekly_sales row *i* for all 17,117 [q1:rowid_vs_cleaned_rowid]. File order is week_date descending, and unsorted within a week [q1:rowid_order_sample]. Multiset comparison makes the order irrelevant.
- There are no other tables, so there are no joins and no orphans.

## 2. Event catalogue

The catalog is pre-aggregated. The brief's rule applies: **one reported event per row at its period's date. No finer grain exists.**

| # | Event | Owner | Time | Attributes | Source rows | Count |
|---|---|---|---|---|---|---:|
| E1 | `weekly_sales_reported` | region (7 partitions) | `week_date` at 00:00 UTC, a Monday (all 72 week_dates have dow = 1 [q2:weekday_of_week_date]) | platform (cat), segment (opt cat: C1..F3 or null), customer_type (cat), transactions (i64), sales (i64) | weekly_sales | 17,117 |

**Total events: 17,117. Entities: 0.**

- **Time is a rule.** `week_date` is the week's label, the Monday the week starts. A week's totals can only be known after the week closes, but the source gives no reporting time. Using the label keeps `week_date` a pure format of `event_time`.
  - If stage 2 needs "no event knows its own future", stamp E1 at week_date + 7 d and subtract in the view. That is also exact.
- **Snapshot N** = 2020-08-31, the last week_date (or 2020-09-07 under the +7 d rule).
- **Not entities:**
  - region, platform, segment and customer_type are categorical attributes with no attributes of their own. Making them entities would add 4 lookup tables that no source table holds.
  - age_band and demographic are pure functions of segment (§3.1).
- **cleaned_weekly_sales produces no events.** It is derived (§3.1).

## 3. Rebuild rules and blockers to an exact round trip

1. **cleaned_weekly_sales is an exact function of weekly_sales.** 0 differing rows in either direction (`EXCEPT` both ways, 17,117 of 17,117 per column) [q2:multiset_diff_cleaned_minus_rebuilt, q2:multiset_diff_rebuilt_minus_cleaned, q2:per_column_matches]. DuckDB confirms every column [f1].

   | column | rule | match |
   |---|---|---|
   | week_date | `d/m/yy` → `printf('%04d-%02d-%02d')`; DuckDB `strftime(ts,'%Y-%m-%d')` | 17,117 |
   | week_date_formatted | `y-m-d` with no zero padding; DuckDB `strftime(ts,'%Y-%-m-%-d')` | 17,117 |
   | week_number | **ISO week** (SQLite: `(strftime('%j', date(d,'-3 days','weekday 4'))-1)/7+1`; DuckDB `weekofyear`) | 17,117. `%W` matches only 5,698: in 2019 and 2020, `%W` is one less [q2:week_number_candidates, q2:week_number_vs_dates] |
   | month_number, calendar_year | month and year of the date | 17,117 |
   | segment | `coalesce(segment,'unknown')` | 17,117 |
   | age_band | 2nd char: 1 → Young Adults, 2 → Middle Aged, 3/4 → Retirees, else unknown | 17,117 |
   | demographic | 1st char: C → Couples, F → Families, else unknown | 17,117 |
   | avg_transaction | **decimal round-half-up** of sales/transactions to 2 dp: `((200*sales + tx) / (2*tx)) / 100.0` with integer division | 17,117. SQLite `round(1.0*sales/tx, 2)` gets 17,104 (13 misses, all exact `.xx5` ties such as 6803/40 = 170.075 → 170.08) [q2:avg_tx_mismatches]. DuckDB `round` gets 17,114 [f1]. There are 109 exact ties in all [q2:avg_transaction_half_up_ties] |

   **The `build.sql` rule must use the integer half-up form, not `round()`.** It is the only part of the round trip that is not obvious.
2. **weekly_sales.week_date text** is `d/m/yy` with no padding. 5,227 values are 6 characters and 11,890 are 7 [q1:week_date_formats]. DuckDB `strftime(ts, '%-d/%-m/%y')` rebuilds all 17,117 [f1].
3. **NULL segment.** It is NULL in weekly_sales and `'unknown'` in cleaned. E1 carries null; the payload must not write `"null"` or `""`.
4. **Numbers.** transactions and sales are INTEGER in every row [q1:typeof_weekly_sales]; carry them as i64. avg_transaction is the only REAL column, and it is derived. There are no floats in the log.
5. **No duplicates and no rows without a time.** Every row has a week_date, and the key is unique.

**Verdict:** exact, with no real caveat. Times are a rule (the week label), and every derived column is proven.

## 4. Measured quirks

- **Three disjoint 24-week windows:** 2018-03-26..09-03, 2019-03-25..09-02 and 2020-03-23..08-31. Each year covers ISO weeks 13–36, and the gap between windows is 203 days [q2:weeks_per_year, q2:week_gaps].
- **Tiny cells:**
  - 1 row has sales = 0 with transactions = 1 (SOUTH AMERICA Shopify C4 New, 2019-04-15), so avg_transaction = 0.0 [q3:zero_and_small].
  - Shopify New C4/F3 cells in EUROPE and SOUTH AMERICA have 1–2 transactions [q3:low_sales_rows]. They are also the 19 missing cells.
- **Platform scale:**
  - Retail holds 97.33% of sales, with a mean basket of 36.65 pooled;
  - Shopify holds 2.67%, with a mean basket of 183.80 pooled (max 880.33) [q3:platform_share, q3:avg_tx_by_platform].
- **Guest is unsegmented by design.** NULL segment is 40.1% of sales [q3:segment_share].
- **The June 15 effect is weak.** The weekly total falls from 586.3 M (2020-06-08) to 570.0 M (2020-06-15) and then recovers [q3:weekly_totals]. local301 2020: −1.15%. local302 per attribute: platform Shopify +7.18%, Retail −2.43% [q4:local302_values].
- **Generator fingerprint, weak:** small Shopify cells have transactions that are multiples of 40 (139 of 6,722) [q3:tx_mod40_by_platform_small]. Week-to-week cell ratios average 1.0316, 71% within ±10% [q3:week_to_week_cell_change]. These are smooth synthetic series.

## 5. Distributions to fit (stage 2)

| Quantity | Value |
|---|---|
| arrivals | 1 row per cell per Monday. The 19 holes are in Shopify-New-{C4, F3} of EUROPE/SOUTH AMERICA |
| sales per year | 12.90 B (2018), 13.75 B (2019), 14.10 B (2020) [q3:sales_per_year] |
| weekly total | 522–553 M (2018), 549–605 M (2019), 566–638 M (2020) [q3:weekly_totals] |
| cell sales | p5 2,086; p25 25,259; p50 196,439; p75 1,630,041; p95 12,219,442; max 69,763,805 [q3:cell_sales_quantiles] |
| region mix (sales) | OCEANIA 32.74%, AFRICA 24.40, ASIA 22.49, USA 9.64, CANADA 6.08, S. AMERICA 2.99, EUROPE 1.65 [q3:region_share] |
| customer type mix | Existing 49.79%, Guest 37.37, New 12.84 [q3:ctype_share] |
| segment mix | F3 16.57%, C3 11.38, F2 11.18, C1 6.58, C2 4.89, F1 4.66, C4 4.65 [q3:segment_share] |
| basket (avg_transaction) | Retail 20.03–70.17 (mean 41.84); Shopify 0–880.33 (mean 180.23) |
| cell persistence | week-to-week ratio mean 1.032; 71% within ±10%; 151 of 16,389 pairs more than double |

## 6. simkit mapping sketch

```python
p.event("weekly_sales_reported", doc="Pre-aggregated: one row per (week, region, platform, segment, customer_type); no finer grain",
        cols={"region": cat("AFRICA", "ASIA", "CANADA", "EUROPE", "OCEANIA", "SOUTH AMERICA", "USA"),
              "platform": cat("Retail", "Shopify"),
              "segment": opt(cat("C1", "C2", "C3", "C4", "F1", "F2", "F3")),
              "customer_type": cat("New", "Existing", "Guest"),
              "transactions": i64(), "sales": amount("USD", doc="whole units, not cents")})
```

Ingest:
- `-- event: weekly_sales_reported owner=region`.
- The time is `iso_time(week_date, '%d/%m/%y')`. Check that Python's `%d`/`%m` accept the unpadded `1/4/19` (`strptime` does).
- ORDER BY the parsed date, region, platform, segment, customer_type.
- `sales` could be `i64()` instead of `amount`, since it is whole units with no cents.

`build.sql` (DuckDB):
- `weekly_sales`: `strftime(event_time, '%-d/%-m/%y')`, the dims, transactions and sales.
- `cleaned_weekly_sales`: the §3.1 rules over the same view, including `weekofyear(event_time)` and `((200*sales + transactions) // (2*transactions)) / 100.0`.

Stage 2:
- owner = region (7 shards). Each Monday, emit 34 rows (2 platforms × 17 cells), drawing sales from a per-cell lognormal with a slow trend and yearly level shifts.
- Optionally apply a step at 2020-06-15.
- The 19 holes are a "zero-sales cell is omitted" rule.

## 7. Open questions and risks

- **Ingest time parse.** `iso_time(text, '%d/%m/%y')` must accept 1-digit days and months. Python `strptime` does, but confirm in `refdata.ingest`.
- **local301 has three CSV variants.** `_b` (−0.25% for 2019) and `_c` (a different 2020 post total) do not follow the gold SQL. The saved query should be the gold SQL, compared to `_a`.
- **local302 needs 3-dp rounding** per value before averaging. That rounding is not in the question. Save the query with that rounding, or compare with a tolerance of 1e-3.
- **The licence of the 8 Week SQL Challenge data is unstated.** Fitting statistics is fine; confirm before redistributing rows.
- **Report time.** Week-start stamping puts each week's total at the start of the week it summarises. If the stage-2 leakage check objects, switch to week end (+7 d) in both ingest and views.

## Summary

- Round trip: **yes, exact**. cleaned_weekly_sales is proven derived (0 differing rows), with ISO week and decimal half-up avg_transaction.
- Dataset name: `datamart`.
- 1 event type (`weekly_sales_reported`), 0 entities.
- Event shape: **mostly imposed**. These are pre-aggregated weekly cells, one reported event per row at its week's Monday.
- Hardest blocker: `avg_transaction` needs integer half-up rounding. SQLite `round()` misses 13 rows and DuckDB `round()` misses 3.
