# Vegetable wholesale (Spider 2.0-lite, `bank_sales_trading`): reverse-engineered event log

Source: the tables `veg_txn_df`, `veg_whsle_df`, `veg_cat` and `veg_loss_rate_df` of `data/spider2/bank_sales_trading.sqlite`, opened read-only.

`scripts/veg/rq.py` copies the file into an in-memory SQLite and runs named blocks; the file itself is never written. Every number below comes from one of these:
- a named block in `scripts/veg/q*.sql`;
- `p1_gold.py` (gold CSV reproduction);
- `f1_duck_rules.py` (DuckDB 1.5.6, the views engine).

Raw outputs are `scripts/veg/out_*.txt`. `[q2:qty_grid]` means file `q2_rules.sql`, block `qty_grid`. Gold CSVs are in `scripts/veg/gold/`.

## 0. What this catalog is

- **Dataset.** This is the data of **Problem C of the 2023 China Undergraduate Mathematical Contest in Modeling (CUMCM, 高教社杯)**: a supermarket's vegetable sales, wholesale prices and loss rates, translated into English. The evidence:
  - The four tables are the problem's four attachments: item/category list, sales detail, wholesale price, loss rate.
  - The period is 2020-07-01..2023-06-30 [q1:date_formats], with **six categories** [q1:categories]. Papers on that problem describe the same span and six categories (e.g. MDPI *Axioms* 13(1):62, 2024).
  - Item names are pinyin or English translations ("Niushou Shengcai", "Wuhu Green Pepper (2)").
  - Item codes are 13–15-digit retail barcodes (233 of 251 start `1029000`) [q4:item_code_prefixes].
  - Wholesale prices are missing on exactly the Chinese New Year's Eve and Spring Festival days: 2021-02-11/12, 2022-01-31 and 2023-01-21 [q3:missing_whsle_days]. The busiest sales day is 2021-02-10, the eve before [q3:busiest_days].

  The exact row counts were not checked against the official attachments.
- **Spider/pandas artefacts.**
  - Every table has a pandas `"index"` column (0..n−1, equal to rowid − 1 in all four) [q1:index_columns].
  - Dates are `YYYY-MM-DD 00:00:00` text [q1:date_formats].
  - Column names keep units (`qty_sold(kg)`, `unit_selling_px_rmb/kg`, `whsle_px_rmb-kg`, `loss_rate_%`).
  - **`discount(%)` is 1 in all 878,503 rows** [q1:discount_values]. The original attachment has a yes/no "sold at a discount" flag; here it is constant.
- **Row counts** [q1:row_counts]: veg_txn_df 878,503; veg_whsle_df 55,982; veg_cat 251; veg_loss_rate_df 251.
- **Licence.** Unstated. It is contest data released by the CUMCM organisers for the competition.
- **Nature.** Real point-of-sale data from one supermarket, by every sign: Spring Festival peaks, business-hour arrivals, odd-gram weights, duplicate scans. It was released anonymised (no store or customer).

## 0.1 How Spider 2.0 uses it

Two of the 15 `bank_sales_trading` questions use these tables. No gold SQL exists for either.

| id | asks | gold | reproduced |
|---|---|---|---|
| local284 | mean item loss rate, and counts of items below, within and above one SD | 2 CSVs | ✔ avg 9.426693227091633; below 35, within 187, above 29. `_b` reports SD 5.200636091718013, the **population** SD (Python's pstdev gives ...015, a 2e-15 difference). The sample SD gives the same counts [p1] |
| local285 | per year 2020–2023 and category: avg/max/min wholesale price, the difference, total wholesale, total selling, avg loss rate, total loss, profit, at 2 dp | 4 CSVs | ✔ **all 4 variants, 24/24 rows in every column** [p1]. They agree on the joined set: sale rows only (returns excluded), joined to that day's wholesale price, the category and the loss rate. total wholesale = Σ qty·whsle; total loss = Σ qty·whsle·loss%; profit = selling − wholesale − loss. They differ on readings: |

How the local285 variants differ [p1]:
- **`_a`:** prices and loss are averaged over joined sale rows; selling = Σ qty·px.
- **`_b` and `_c`:** prices come from `veg_whsle_df` alone (max, min and diff too); the loss is averaged over the distinct items sold that year; selling applies `discount(%)` as **1%**, so Σ qty·px·0.99.
- **`_d`:** price and loss averages are qty-weighted over sale rows; selling has no discount.

So the constant `discount(%) = 1` changes a gold answer: it must be rebuilt as INTEGER 1 exactly.

## 1. Inventory, keys, joins

No PK or FK is declared. Every key below was measured unique.

| Table | Rows | Key | Kind |
|---|---:|---|---|
| veg_txn_df | 878,503 | `index` only. 5,295 rows are exact duplicates of another on every data column [q1:txn_dup_full_rows, q2:txn_full_duplicates] | business events (POS lines) |
| veg_whsle_df | 55,982 | (whsle_date, item_code) [q1:whsle_key] | daily price quote per item |
| veg_cat | 251 | item_code; 6 category codes ↔ 6 names [q1:key_cat] | item master + category |
| veg_loss_rate_df | 251 | item_code [q1:key_loss] | item attribute (one rate per item) |

- **Joins** [q1:orphans, q1:loss_vs_cat_items]:
  - txn → cat, 0 orphans: 246 items are sold, and 5 are never sold (all 5 have 1–6 quotes) [q3:never_sold_items];
  - whsle → cat, 0 orphans: all 251 items are quoted;
  - loss ↔ cat, the same 251 item codes.
- **Every sold item-day has a wholesale quote:** 46,599 of 46,599 [q3:sales_with_whsle_price]. 9,383 quotes have no sale that day [q3:whsle_without_sales].
- **`veg_loss_rate_df.item_name` is a copy** of `veg_cat.item_name`, 251 of 251 [q2:loss_name_is_cat_name]. Item names are not unique: 4 names are used twice [q1:duplicate_item_names_cat].
- **Row order is a sort, so `index` is derived** in 3 of the 4 tables:
  - veg_whsle_df: (whsle_date, item_code), 55,982 / 55,982 [q2:whsle_index_rule];
  - veg_cat: (category_code, item_code), 251 / 251 [q2:cat_index_rule];
  - veg_loss_rate_df: item_code, 251 / 251 [q2:loss_index_rule].
- **veg_txn_df is in time order:** date + time is non-decreasing over all 878,502 pairs [q1:txn_rowid_order]. Within a second, no column explains the order: item code goes up in 57,129 tie pairs and down in 54,868 [q2:txn_tie_order_candidates]. So `index` must ride as `ord`, and is then `row_number() over (order by event_time, ord) − 1` [f1: 878,503 / 878,503].

## 2. Event catalogue

| # | Event / entity | Owner | Time | Attributes | Source rows | Count |
|---|---|---|---|---|---|---:|
| N1 | `categories_created` | category | rule: catalog start 2020-07-01 00:00:00 | ext_id = category_code, category_name | veg_cat (distinct) | 6 |
| N2 | `items_created` | item | rule: the item's first wholesale quote date | ext_id = item_code, item_name, category (ref) | veg_cat | 251 |
| N3 | `items_snapshot` | item | N | loss_rate_bp (i64) | veg_loss_rate_df | 251 |
| E1 | `wholesale_price_quoted` | item | `whsle_date` 00:00 (natural day; the time of day is a rule) | price_fen (amount CNY) | veg_whsle_df | 55,982 |
| E2 | `item_sold` | item (ord = index) | `txn_date` + `txn_time` (natural, to the second) | qty_g (i64 > 0), unit_price_jiao (i64), discount_pct (i64) | veg_txn_df where qty > 0 | 878,042 |
| E3 | `item_returned` | item (ord = index) | same | qty_g (i64 < 0, signed as in the source), unit_price_jiao, discount_pct | veg_txn_df where qty < 0 | 461 |

**Total: 934,485 business events + 508 entity rows (6 + 251 + 251) = 934,993 log rows.**

- **N = 2023-06-30 21:40:48**, the last transaction [q4:last_event].
- **Items are created at their first quote.** The first quote is never after the first sale: 232 on the same day, 14 earlier, 0 later. 36 items are quoted on day 1 [q4:first_quote_vs_first_sale].
  - A quote at 00:00 always precedes that day's sales: the earliest sale time is 08:14:12 [q1:time_formats].
  - So no event references an item before its creation.
- **Loss rate is a snapshot column.** It is one number per item for the whole period, a statistic of the three years, so it travels at N, not at creation.
- **Sale vs return** is the sign of qty (878,503 of 878,503 [q2:sale_return_is_sign]). Two event types keep the lifecycle explicit, while one signed type would be equally exact.
  - Returns are not linked to an earlier sale; the source has no receipt id.
- **Not entities and not events:**
  - `day_of_week` is a function of the date;
  - `sale/return` is the sign;
  - `veg_loss_rate_df.item_name` is a copy;
  - the `index` columns are sort positions;
  - there is no customer, receipt or basket id, so no basket entity can be built. Consecutive lines with the same second (121,520 zero-second gaps [q3:gap_seconds_within_day]) hint at baskets but are not data.

## 3. Rebuild rules and blockers to an exact round trip

Every value is on an integer grid, and DuckDB rebuilds each one exactly [f1]:

| column | carry as | rebuild | exact |
|---|---|---|---|
| `qty_sold(kg)` | grams, i64 | `g / 1000.0` | 878,503 [q2:qty_grid, f1] |
| `unit_selling_px_rmb/kg` | jiao (0.1 RMB), i64 | `j / 10.0`. Every price has a 0 in its 2nd decimal [q3:price_ending] | 878,503 [q2:price_grid, f1] |
| `whsle_px_rmb-kg` | fen, `amount("CNY")` | `f / 100.0` | 55,982 [q2:whsle_grid, f1] |
| `loss_rate_%` | basis points, i64 | `bp / 100.0` | 251 [q2:loss_grid, f1] |
| txn_date / whsle_date | event day | `strftime(ts, '%Y-%m-%d %H:%M:%S')` of the day, always ` 00:00:00` | all [f1] |
| txn_time | event time | `strftime(ts, '%H:%M:%S')`; there are no sub-seconds [q1:subsecond_times] | 878,503 [f1] |
| day_of_week | derived | `strftime(ts, '%A')` | 878,503 [q1:day_of_week_check, f1] |
| sale/return | derived | the event type, or the sign | 878,503 [f1] |
| discount(%) | i64 on E2/E3 | verbatim (always 1) | — |
| `index` (txn) | ord | `row_number() over (order by event_time, ord) − 1` | 878,503 [f1] |
| `index` (whsle, cat, loss) | derived | row_number over the sort keys in §1, − 1 | all [q2:*_index_rule] |
| item_code, category_code | ext_id, i64 | verbatim. Up to 15 digits, below 2⁵³, so JSON-string ints are safe | — |

- **Duplicates.** 4,847 groups of identical transaction rows (up to 6 copies; 5,295 extra rows) [q2:txn_full_duplicates]. In 4,595 of the 4,847 groups the copies are adjacent in `index` [q2:dup_adjacent]. These look like repeated scans. Each is its own event with its own `ord`, and the multiset compare is satisfied.
- **No NULLs** in any column [q1:null_counts]. There is no `''`, and there are no rows without a time.
- **There are no floats in the log.** Every REAL is an integer grid.

**Verdict:** exact. Every value is integer-encoded and verified in DuckDB. The only rule-made times are entity creations, the 00:00 quote time, and the snapshot at N.

## 4. Measured quirks

- **Constant discount flag.** `discount(%) = 1` everywhere. Gold variants of local285 read it as a 1% discount; others ignore it.
- **Closed days.** 10 days have no sales, but only 4 have no quotes [q3:missing_sale_days, q3:missing_whsle_days]:
  - the 4 Spring Festival days;
  - 2022-11-02, 11-04 and 11-30..12-03, which have quotes but no sales. These are a COVID-era closure, as far as the dates suggest.
- **Holiday spikes:** 2021-02-10 has 3,747 lines, against a median of 759 per day; 2023-01-20 has 3,177 [q3:per_day_quantiles, q3:busiest_days].
- **Hours.** Trade runs 09:00–22:00 with two peaks, 10:00 (120,912) and 17:00 (92,771). There is 1 line at 08:xx and 1 at 23:xx [q3:hour_of_day].
- **Weekends** carry 997–1,032 lines a day against 699–786 on weekdays [q3:weekday_mix].
- **Weights.** 673,012 quantities have 3 decimals (scale grams), and 147,277 are whole numbers [q2:qty_decimals].
  - 98 items always sell in whole units (bags and boxes); 132 never do [q3:items_always_whole].
  - Cabbage and Solanum are almost never whole [q3:whole_kg_by_category].
  - The maximum is a single 160 kg line [q3:qty_quantiles].
- **Returns:** 461 lines on 90 items, mean −0.651 kg [q3:returns].
- **Below-cost sales:** 12,660 lines sell under that day's wholesale price; the mean markup is 1.766× [q3:markup, q3:markup_bands].
- **Price noise.** Wholesale prices of 0.01 RMB/kg appear on many items in 2022-08..12 [q3:whsle_extremes], and 315 day-to-day price moves exceed 2× [q3:whsle_daily_change]. These look like data-entry or clearance artefacts.
- **Loss rate 0** for 22 items, all of them sold [q3:zero_loss_items_sold].
- **Item names repeat** across codes (4 names) [q1:duplicate_item_names_cat]; join on code, never on name.

## 5. Distributions to fit (stage 2)

| Quantity | Value |
|---|---|
| lines per day | min 74, p10 474, p50 759, p90 1,180, max 3,747 [q3:per_day_quantiles] |
| lines per year | 185,832 (2020 H2), 298,769 (2021), 263,953 (2022), 129,949 (2023 H1) [q3:rows_per_year] |
| intra-day gaps (s) | 0: 121,520; 1–10: 251,430; 11–60: 269,389; 61–300: 209,246; > 300: 25,833; mean 55.2 [q3:gap_seconds_within_day] |
| hour of day | bimodal, 10:00 and 17:00 [q3:hour_of_day] |
| weekday factor | Sat 1.48×, Sun 1.43× the Thursday rate [q3:weekday_mix] |
| quantity (sales, kg) | p5 0.145, p25 0.29, p50 0.435, p75 0.742, p95 1.0, p99.9 2.647 [q3:qty_quantiles] |
| category mix (lines) | Flower/Leaf 37.79%, Capsicum 23.68, Mushroom 16.90, Cabbage 9.85, Aquatic 6.68, Solanum 5.11 [q3:category_mix] |
| item popularity | top item 69,945 lines; #10 16,644; #50 4,162; #100 870; min 1 [q3:item_popularity] |
| active items per day | 21–62, mean 42.9 [q3:items_per_day] |
| prices per item-day | 1 price: 39,522 item-days; 2: 6,016; 3+: 1,061 [q3:price_points_per_item_day] |
| markup (sell / wholesale) | mean 1.766; 1.4–2.0 for 70% of lines; < 1 for 1.4% [q3:markup_bands] |
| wholesale day-to-day | unchanged 26.5% of consecutive pairs; mean ratio 1.088 [q3:whsle_daily_change] |
| return rate | 461 / 878,503 = 0.052% of lines |
| loss rate | 0: 22 items; 0–5%: 15; 5–10%: 131; 10–15%: 54; 15–20%: 21; ≥ 20%: 8 [q3:loss_rate_dist] |
| item lifetimes | first quotes per year: 94 (2020), 55, 90, 12 (2023) [q4:first_quote_by_year] |

## 6. simkit mapping sketch

```python
p.entity("categories", key="category_key", cols={"ext_id": i64(doc="category_code"), "category_name": text()})
p.entity("items", key="item_key", doc="created at its first wholesale quote (rule)",
         cols={"ext_id": i64(doc="item_code"), "item_name": text(), "category_key": ref("categories")},
         snapshot={"loss_rate_bp": i64(doc="loss_rate_% x 100; one figure for the whole period")})
p.event("wholesale_price_quoted", cols={"item_key": ref("items"), "price": amount("CNY")})
line = {"item_key": ref("items"), "qty_g": i64(), "unit_price_jiao": i64(), "discount_pct": i64(doc="always 1 here")}
p.event("item_sold", cols=line)
p.event("item_returned", doc="qty_g < 0, as in the source", cols=line)
```

Ingest:
- `-- entity: categories`: created_at `'2020-07-01T00:00:00'`, ORDER BY category_code.
- `-- entity: items`: created_at = the first whsle_date of the item, ORDER BY item_code.
- `-- event: wholesale_price_quoted owner=item_key`: time = whsle_date, ORDER BY whsle_date, item_code.
- `-- event: item_sold owner=item_key ord=index` and `-- event: item_returned owner=item_key ord=index`: time = `iso_time(substr(txn_date,1,10) || ' ' || txn_time, '%Y-%m-%d %H:%M:%S')`, ORDER BY "index".
  - `ord = index` keeps the within-second order across both types. Check that simkit's (event_time, ord, block position) sort interleaves two blocks by ord before block position; per the README, ord comes first.
- Integers in = `CAST(round(x*1000) AS INTEGER)` for grams, `round(x*10)` for jiao, `round(x*100)` for fen and bp.

`build.sql`:
- `veg_txn_df`: union of E2 and E3, with the §3 formats; `"index"` = `row_number() over (order by seq) − 1`.
- `veg_whsle_df`: E1, with `"index"` by (date, item_code).
- `veg_cat`: items ⋈ categories, with `"index"` by (category_code, item_code).
- `veg_loss_rate_df`: items + snapshot, with `"index"` by item_code.

Stage 2:
- owner = item (251). Each item gets a daily wholesale quote (a random walk with a seasonal level) and a Poisson stream of sale lines over business hours.
- Intensity comes from item popularity × weekday × hour × holiday factors. Price = quote × a markup drawn around 1.77, rounded to jiao.
- The return hazard is 0.05% of lines.
- Volume is about 0.93 M events; use a sample profile (e.g. 1 year or 50 items) for fast tests.

## 7. Open questions and risks

- **`discount(%)` provenance.** It is constant 1 here. Whether the original yes/no flag was lost (all set to 1) or the store never discounted is unknowable from this file. Gold variants disagree on its meaning (local285 `_b`/`_c` vs `_a`/`_d`); the saved query must pick one CSV.
- **Origin confirmation.** The CUMCM 2023 C attribution rests on structure, dates, categories and holidays. The row counts were not checked against the official attachments, and the redistribution terms are unknown. Fit statistics only until confirmed.
- **Quote time 00:00** is a rule. The source has dates only. Stage 2 must not read quote-before-sale as a measured lag.
- **Item creation by rule.** 5 items are quoted but never sold (1–6 quotes each); 14 are quoted days before their first sale.
- **Two event types interleaved by `ord`.** If the ingest sorts by block before ord, sale/return order within a second changes, and `index` would not rebuild. The fallback is one `item_line_recorded` type with signed qty_g.
- **local285 answers rely on float sums over about 880k products.** Compare at 2 dp, as the CSVs are rounded.

## Summary

- Round trip: **yes, exact**. Every REAL is an integer grid (grams, jiao, fen, basis points), verified in DuckDB. `index`, day_of_week, sale/return and the copied item_name are derived.
- Dataset name: `veg`.
- 3 event types (`wholesale_price_quoted`, `item_sold`, `item_returned`) and 2 entities (`categories`, `items`, with a loss-rate snapshot).
- Event shape: **natural**. These are second-resolution POS lines and daily price quotes; only entity creations and the 00:00 quote time are rules.
- Hardest blocker: the within-second order of 121,520 tie pairs is unexplained by any column, so `index` must ride as `ord` across the sale and return blocks. Separately, the constant `discount(%) = 1` splits the local285 gold readings.
