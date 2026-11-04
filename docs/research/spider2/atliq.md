# AtliQ Hardware (Spider 2.0-lite, `education_business` `hardware_*`): reverse-engineered event log

Source: the six `hardware_*` tables of `data/spider2/education_business.sqlite`, opened read-only. `scripts/atliq/rq.py` copies the file into an in-memory SQLite and runs named blocks; the file itself is never written. The file also holds three unrelated catalogs: Parch & Posey (`web_*`, [parchposey.md](parchposey.md)), Mannino's university (`university_*`, [university.md](university.md)), and `StaffHours` + `SalaryDataset` ([edu_misc.md](edu_misc.md)).

Every number below comes from one of these scripts:
- a named query in `scripts/atliq/q*.sql`;
- `f1_decimals.py` (Python and DuckDB, 4-decimal checks; run with `uv run python -I` so DuckDB is importable).

The raw outputs are in `scripts/atliq/out_*.txt`. A reference such as `[q2:cube_density]` means file `q2_values.sql`, block `-- name: cube_density`. Gold files are in `scripts/atliq/gold/`.

## 0. What this catalog is

- **Dataset.** This is **AtliQ Hardware**, the fictitious computer-hardware maker that the Indian training company **Codebasics** uses in its SQL and Power BI courses. This cut is the one from the **Codebasics Resume Project Challenge #4** ("Provide Insights to Management in Consumer Goods Domain", database `gdb023` / `atliq_hardware_db`). That challenge ships exactly these six tables: `dim_customer`, `dim_product`, `fact_gross_price`, `fact_manufacturing_cost`, `fact_pre_invoice_deductions`, `fact_sales_monthly`. Spider adds the `hardware_` prefix. The evidence:
  - The row counts match the challenge's published dump: 209 customers, 397 products and 971,631 monthly sales rows [q1:row_counts].
  - Only fiscal years 2020 and 2021 are present [q1:years]. The longer course database (`gdb041`) covers more years.
  - local058 is, nearly word for word, the challenge's ad-hoc request: "Which segment had the most increase in unique products in 2021 vs 2020?" (§0.1).
  - The customer and product names are the course's: `Atliq Exclusive`, `Atliq e Store`, `AQ Dracula HDD`, `AQ WereWolf NAS` [q2:customer_head, q2:product_head].
  - I matched the origin by these names, counts and tables. I have not compared the dump file byte for byte, so the exact dump is **unverified**.
- **Row counts** [q1:row_counts]:

  | table | rows |
  |---|---:|
  | fact_sales_monthly | 971,631 |
  | fact_gross_price | 579 |
  | fact_manufacturing_cost | 579 |
  | fact_pre_invoice_deductions | 418 |
  | dim_product | 397 |
  | dim_customer | 209 |

  The total is 973,813.
- **Licence.** Unstated. Codebasics publishes the dump for learners. There is no explicit licence.
- **Nature.** **Generated course data** for a fictitious company. The retailer names are real (Amazon, Croma, BestBuy), but the quantities are synthetic. §4 lists the generator's fingerprints: a 4-way rotation of inactive months, a cost/price ratio band, and product codes that encode a launch year.

## 0.1 How Spider 2.0 uses it

| id | asks | gold SQL? | gold answer | reproduced |
|---|---|---|---|---|
| local058 | hardware segments with their 2020 unique-product counts, ordered by % increase in unique sold products from 2020 to 2021 | yes | Desktop 7, Networking 6, Accessories 69, Storage 12, Peripherals 59, Notebook 92 | ✔ exactly [q3:gold_local058]. The 2021 counts are 22, 9, 103, 17, 75 and 108 (+214%, +50%, +49%, +42%, +27%, +17%). "Year" means `fiscal_year` |
| local059 | calendar 2021: mean total quantity of the top 3 products (by quantity) in each division | no (CSV only) | N & S 397,699.333333; P & A 244,691.0; PC 10,045.666667 | ✔ exactly with `date LIKE '2021%'` [q3:gold_local059]. With `fiscal_year = 2021` the answer differs: 688,540.3 / 422,611.3 / 17,329.7 [q3:gold_local059_fiscal_variant] |

- **local058 needs** `fiscal_year` and the product dimension.
- **local059 needs** the calendar month in `date`.

Both values must therefore rebuild exactly. `fiscal_year` is a pure function of `date` (§3.1).

## 1. Inventory, keys, joins

No PK or FK is declared. All keys below are verified unique, and all joins resolve with 0 orphans [q1:key_uniqueness, q1:fk_orphans].

| Table | Rows | Key | Kind |
|---|---:|---|---|
| hardware_fact_sales_monthly | 971,631 | (date, product_code, customer_code); 0 full-row duplicates | **pre-aggregated fact** (monthly quantity) |
| hardware_fact_gross_price | 579 | (product_code, fiscal_year) | annual attribute (price list) |
| hardware_fact_manufacturing_cost | 579 | (product_code, cost_year) | annual attribute (cost). It has the **same 579 keys** as gross_price [q1:price_cost_same_keys] |
| hardware_fact_pre_invoice_deductions | 418 | (customer_code, fiscal_year); 209 × 2 years | annual attribute (customer discount) |
| hardware_dim_product | 397 | product_code (11 chars, `A` + 10 digits) | master |
| hardware_dim_customer | 209 | customer_code (INTEGER, 8 digits) | master |

Joins and coverage:
- sales → product and customer; price and cost → product; deductions → customer: all 100% [q1:fk_orphans].
- **The annual tables match the sales exactly** [q1:parents_without_children]:
  - every sold (product, fiscal_year) has a price and a cost row;
  - every price row was sold in that year (0 unsold price rows);
  - every sold (customer, fiscal_year) has a deduction, and every deduction row was used.

  So `price rows = sold (product, fy) pairs`: 245 + 334 = 579.
- **50 products are never sold, priced or costed.** The dimension carries them anyway [q1:parents_without_children, q2:unsold_vs_priced]. Every customer buys.
- **The products have two cohorts** [q2:products_by_year_sold]:
  - 232 products are sold in both years;
  - 13 only in fy2020 (they end 2020-08) [q3:product_last_month];
  - 102 only in fy2021 (they start 2020-09-01) [q3:product_first_month].
- **No copies or derived tables** exist inside the catalog. `fiscal_year` is a derived *column* (§3.1).
- **Rowid order.**
  - sales are in (product_code, date, customer_code) order: 0 descending pairs in 971,630 [q2:rowid_order_product_date_cust]. They form 347 product blocks, one per sold product [q2:rowid_product_blocks].
  - The dimensions, prices and deductions are in key order [q1:dim_rowid_order].

## 2. Event catalogue

The sales table is a **pre-aggregated fact**: one row per (month, product, customer) holding the month's `sold_quantity`. The dates are all the 1st of the month, `YYYY-MM-01`, from 2019-09-01 to 2021-08-01, 24 months [q1:date_formats, q1:months]. No finer grain (invoice, order or day) exists, so each row becomes one `monthly_sales_reported` event at its month's first day. The time is the period stamp: natural in the sense that it is the source's own column, but it is a period label, not the moment of a sale.

Prices, costs and deductions are **annual attribute snapshots**, keyed by AtliQ's fiscal year. That year starts in September (§3.1). Each row becomes an update event at the first day of its fiscal year, a **rule** time. The source has only the year.

| # | Event | Owner | Time | Attributes | Source rows | Count |
|---|---|---|---|---|---|---:|
| E1 | `product_priced` | product | rule: (fiscal_year − 1)-09-01 | fiscal_year, gross_price (1e-4 units), manufacturing_cost (1e-4 units) | gross_price ⋈ manufacturing_cost on (product, year) | 579 |
| E2 | `customer_deduction_set` | customer | rule: (fiscal_year − 1)-09-01 | fiscal_year, pre_invoice_discount_pct (1e-4 units) | pre_invoice_deductions | 418 |
| E3 | `monthly_sales_reported` | customer | `date` (month start; natural period stamp) | product_id (ref), sold_quantity | fact_sales_monthly | 971,631 |

**Total events: 972,628.**
- E1 joins two source tables, because their keys are identical (579 of 579).
- Splitting E1 into `gross_price_set` and `manufacturing_cost_set` is the alternative. It gives 973,207 events and 4 event types, and is also exact.

Entities (2 tables, 606 rows):
- **customers** (209):
  - ext_id = customer_code;
  - attributes customer, platform, channel, market, sub_zone (opt) and region (opt);
  - `created_at` = the catalog start, **2019-09-01**, by rule.
- **products** (397):
  - ext_id = product_code;
  - attributes division, segment, category, product and variant;
  - `created_at` = the start of the first fiscal year in which the product has a price (2019-09-01 for 245, 2020-09-01 for 102). That time is natural to the data, since the launch shows in the price list.
  - The **50 never-sold products** get the catalog start, 2019-09-01, by rule.

What is **not** an entity, and why:
- **Fiscal year** is not a calendar entity. It is a pure function of the month (§3.1).
- **Markets, regions, sub-zones, divisions, segments and categories** are flat text attributes. Each `market` maps to exactly one 4-digit block of `customer_code` (§4). No table exists for any of them, so promoting them would add entities the source does not have.
- **A price list per year** is not an entity either. Price and cost are per (product, year), so they are updates on the product.

No **snapshot-only** columns exist. Every dimension attribute is static: there is no stock, no `last_update` and no lifetime total.

Snapshot **N = 2021-08-01**, the last month [q1:months].

## 3. Rebuild rules and blockers to an exact round trip

1. **`fiscal_year` is derived.**
   - `fiscal_year = year(date) + (month(date) >= 9)` holds for 971,631 of 971,631 rows [q1:fiscal_year_rule].
   - Do not carry it on E3. `build.sql` computes it: `CAST(strftime(t,'%Y') AS INT) + (CAST(strftime(t,'%m') AS INT) >= 9)`.
   - The price, cost and deduction years come from E1/E2's `fiscal_year` attribute. The event time encodes it too, but the attribute keeps the views simple.
2. **Four-decimal REALs.**
   - `gross_price` (2.9168–834.9812), `manufacturing_cost` (0.892–240.5364) and `pre_invoice_discount_pct` (0.0531–0.3095) all have at most 4 decimals [q2:price_decimals].
   - Every value rebuilds exactly as `n / 10000` from the integer `n = round(x·10000)`. That is 579, 579 and 418 of 579, 579 and 418, in Python [f1]. In DuckDB, `CAST(round(x*10000) AS BIGINT) / 10000.0` also matches 579, 579 and 418 [f1].
   - So carry them as `i64` in units of 1e-4, the AdventureWorks rule, and divide in the view. Carrying `f64` verbatim is the trivially exact fallback.
   - `CAST(x AS TEXT)` is the short decimal (`16.2323`, `5.718`), with no float noise [q2:price_text_samples, q2:cost_text_samples, q2:ded_text_samples].
3. **Dates.** `date` is TEXT `YYYY-MM-01` in all rows [q1:date_formats]. Read it as UTC midnight, and write it back with `%Y-%m-%d`.
4. **Integers.** `customer_code` (INTEGER), `sold_quantity` (INTEGER, 1–5,832, no zeros, no negatives) and `fiscal_year` are all integer-typed [q1:typeof_columns, q2:qty_stats]. `product_code` is TEXT.
5. **NULLs.** The only NULLs are `sub_zone` and `region` in 26 customers: exactly the USA (15) and Canada (11) rows. The 7 Latin American customers have `LATAM` [q2:customer_null_columns, q2:customer_null_rows, q2:customer_mix]. There is no `''` in any column [q1:nulls_and_empty]. Make both columns `opt(text())`.
6. **Byte-exact text.**
   - 25 customers are named `'Amazon '` with a trailing space, and 4 are `'Amazon'` without one [q3:amazon_trailing_space].
   - 6 products are `'AQ Gamers '` (trailing space), and 4 variants are `'Plus 1 '` [q4:product_whitespace_rows].
   - 7 product names contain an en dash `–`, and the customer `Elkjøp` is UTF-8 [q3:non_ascii_product, q3:non_ascii_customer].
   - Market typos survive: `Philiphines`, `Newzealand` and `Columbia` [q3:typos].

   Carry all of it verbatim and never trim.
7. **Duplicates and untimed rows.** There are no duplicate rows. The only untimed rows are the entities and the annual tables, which get times by rule as described in §2.
8. **Tie order.** E1, E2 and the first E3 rows share 2019-09-01 and 2020-09-01. Give E3 no `ord`, so ties fall to block position: put the E1 and E2 blocks before E3. Then the year's price and deduction come before that year's first sales. The rebuilt row order does not matter, since tables compare as multisets.

**Verdict:** an exact round trip is feasible, with caveats only on representation (1e-4 integers or `f64`). Two choices drive the event count: whether to merge E1, and the volume, which at 972k events is the fourth-largest Spider2 log so far, after delivery_center, airlines and oraclesh.

## 4. Measured quirks

- **A 4-way rotation of inactive months.** This is the clearest generator fingerprint.
  - Every customer buys in exactly 18 of the 24 months [q3:months_active_per_customer].
  - The 6 missing months are always the month indices ≡ g (mod 4) inside each fiscal year, the same in both years. The four groups hold 52, 52, 52 and 53 customers [q3:customer_missing_month_patterns, q3:missing_months_same_both_years].
  - So every month has exactly 157 buying customers out of 209 (156 when the 53-group is out) [q1:months].
  - The group is not `rowid mod 4` (48 of 209) and not `customer_code mod 4` (104 of 209) [q4:missing_month_group_rule], so the assignment rule is unknown.
  - Across channels, the September-missing group takes 9 of 40 Direct, 1 of 5 Distributor and 42 of 164 Retailer customers [q4:missing_group_sizes_by_channel].
- **The (product, customer) cube is dense.**
  - Within a fiscal year, a pair appears in at most 9 months. 91,091 of 116,848 pairs appear in all 9 of their customer's active months, and the rest in fewer [q3:pair_months_vs_customer_months, q2:months_per_pair].
  - Each product is sold to 3–157 customers a month in fy2020 (mean 124), and 81–157 in fy2021 (mean 152) [q4:customers_per_product_month].
- **Products sell all year.** In fy2020, 237 products are sold in all 12 months. The other 8 (7 `AQ Home Allin1` desktops and `AQ Smash 1`) miss only 2020-03 [q4:products_full_year, q2:march_2020_missing_products]. In fy2021, all 334 are sold in all 12 months.
- **The March 2020 dip.** 2020-03 has 20,056 rows and a quantity of 238,961, against 32k rows and about 1.7M in the neighbouring months [q1:months]. This is the generator's COVID-19 shock. April–June 2020 recover gradually (0.82M, 1.02M, 1.56M).
- **fy2021 doubles fy2020.** The quantity is 50.2M against 20.8M. The row count is about 50.5k a month against about 32k [q1:months, q3:qty_by_division_month]. This comes from both more products (334 against 245) and more customers per product.
- **Seasonality.** Sep–Dec is the peak: the mean per row is 65, 80, 108 and 114 for Sep–Dec, against 55–66 in the other months [q3:seasonality_index]. That is a holiday-quarter multiplier on every row.
- **Code structure** [q3:code_prefix_vs_channel, q3:code_market_digits, q3:code_digits67_vs_division, q3:code_year_digits_vs_first_fy]:
  - **customer_code** = channel digit + 4-digit market code + 3 digits.
    - The channel digit is 7 = Direct (40), 8 = Distributor (5) and 9 = Retailer (164).
    - The market code runs `0001` China … `0027` Brazil.
  - **product_code** = `A` + 2-digit model + 2-digit year (18–21) + 2-digit division + 2-digit model sequence + 2-digit variant.
    - The division digits are 11 = PC, 15 = P & A and 16 = N & S.
    - The year digits loosely mark the launch: 41 of the 50 unsold products carry `21`, and 48 of the 91 year-20 products start in fy2021.
- **Annual price and cost changes** (232 products present in both years) [q2:price_change_2020_2021, q2:cost_change_2020_2021]:
  - gross price ratio 2021/2020: mean 1.059, range 0.931–1.182;
  - cost ratio: mean 1.058, range 1.010–1.111. Cost always rises.
- **The cost/price band.** `manufacturing_cost / gross_price` lies in 0.2858–0.3125, mean 0.2993, in all 579 rows [q2:margin]. That is a generator rule (cost = price × about U(0.286, 0.3125)), not real accounting.
- **Deductions** [q2:ded_stats, q2:ded_year_corr, q4:sales_cust_rank_vs_qty]:
  - The mean is about 0.233 in both years (min 0.053, max 0.310).
  - The year-on-year change ranges from −0.118 to +0.120, so the two years look independent.
  - Direct Brick & Mortar (the `Atliq Exclusive` stores) averages 0.083. Every other channel and platform averages 0.24–0.26.
- **Duplicate customer names.** There are 75 distinct names over 209 customers. (name, market) is unique except for 1 collision, and (name, market, channel, platform) is fully unique [q2:customer_names].
  - India has `Atliq Exclusive` as both Direct and Retailer.
  - `Amazon` and `Amazon ` coexist in India, Japan, the USA and Canada [q2:customer_code_vs_market].
  - Keys must be the codes, never the names.

## 5. Distributions to fit (stage 2)

| Quantity | Value |
|---|---|
| monthly arrivals | one report per active (product, customer) per month. 157 of 209 customers are active a month by the mod-4 rotation; 245 / 334 products are live per fiscal year [q1:months] |
| sold_quantity | p05 1, p25 3, p50 14, p75 62, p90 185, p99 888, max 5,832 [q3:qty_quantiles]; heavy-tailed, roughly lognormal |
| quantity by segment | mean per row: Storage 221, Networking 151, Accessories 145, Peripherals 33, Notebook 6.0, Desktop 4.0 [q3:qty_by_segment] |
| quantity by channel | Distributor 310 per row; Retailer E-Commerce 92; Direct B&M 64; Retailer B&M 61; Direct E-Commerce 59 [q3:qty_by_channel] |
| seasonality | Sep–Dec multipliers ≈ 1.0, 1.25, 1.7, 1.8 relative to the off-season, plus the 2020-03 shock (× about 0.15) and the Apr–Jun 2020 recovery [q3:seasonality_index, q1:months] |
| year growth | units ×2.4 from fy2020 to fy2021 [q3:qty_by_division_month] |
| product mix | 15 (division, segment, category) cells; Personal Laptop 61, Keyboard 48, Mouse 48, Gaming Laptop 40 … Wi fi extender 9 [q2:product_mix] |
| customer mix | Retailer 164 / Direct 40 / Distributor 5; Brick & Mortar 155 / E-Commerce 54 over 27 markets [q2:customer_mix] |
| price | gross price 2.92–834.98; cost / price ∈ [0.286, 0.3125]; yearly price drift ×U(0.93, 1.18), cost ×U(1.01, 1.11) [q2:margin, q2:price_change_2020_2021] |
| pre-invoice discount | ~U(0.05, 0.31), mean 0.233; Direct B&M ≈ 0.08 [q2:ded_stats] |
| lifecycle | 13 products retire after fy2020, 102 launch in fy2021, 50 never launch [q2:products_by_year_sold, q1:parents_without_children] |

## 6. simkit mapping sketch

```python
SCALE = "1e-4 units: value = n / 10000"
p.entity("customers", key="customer_key", doc="created by rule at 2019-09-01",
         cols={"ext_id": i64(doc="customer_code"), "customer": text(), "platform": cat("Brick & Mortar", "E-Commerce"),
               "channel": cat("Direct", "Distributor", "Retailer"), "market": text(),
               "sub_zone": opt(text()), "region": opt(text())})
p.entity("products", key="product_key", doc="created at its first priced fiscal year, else 2019-09-01",
         cols={"ext_id": text(doc="product_code"), "division": cat("N & S", "P & A", "PC"), "segment": text(),
               "category": text(), "product": text(), "variant": text()})
p.event("product_priced", cols={"product_id": ref("products"), "fiscal_year": i32(),
        "gross_price": i64(doc=SCALE), "manufacturing_cost": i64(doc=SCALE)})
p.event("customer_deduction_set", cols={"customer_id": ref("customers"), "fiscal_year": i32(),
        "pre_invoice_discount_pct": i64(doc=SCALE)})
p.event("monthly_sales_reported", doc="pre-aggregated: one row per month x product x customer",
        cols={"customer_id": ref("customers"), "product_id": ref("products"), "sold_quantity": i64()})
```

Ingest (block order E1, E2, E3):
- `product_priced owner=product_id`: time `(fiscal_year-1)||'-09-01'`, ORDER BY product_code, fiscal_year. Gross price and cost come from the join on (product_code, fiscal_year = cost_year), each as `CAST(round(x*10000) AS INTEGER)`.
- `customer_deduction_set owner=customer_id`: the same time rule, ORDER BY customer_code, fiscal_year.
- `monthly_sales_reported owner=customer_id`: time `date`, ORDER BY date, product_code, customer_code. It has no `ord`, so on tied times the price and deduction blocks sort first (§3.8).

`build.sql` (DuckDB):
- **dim tables:** select from the entity views (ext_id → code).
- **`hardware_fact_gross_price`:** `SELECT product.ext_id, fiscal_year, gross_price / 10000.0`.
- **`hardware_fact_manufacturing_cost`:** the same with `cost_year`.
- **deductions:** `pct / 10000.0`.
- **`hardware_fact_sales_monthly`:** `strftime(event_time AT TIME ZONE 'UTC', '%Y-%m-%d')`, product ext_id, customer ext_id, `sold_quantity`, and `fiscal_year` from the §3.1 rule.

Stage-2 owners:
- **customer** (209), with a mod-4 inactive-month group;
- **product**, with a launch and retire fiscal year, a price, and a cost at about 0.3 × price.

A monthly tick emits one report per live (customer, product) pair, with a lognormal quantity scaled by segment, channel, season and year. There is no request/reply. The sample profile should be one fiscal year or a product subset, because the full log is about 1M events.

## 7. Open questions and risks

- **Origin and licence.** The Codebasics Challenge #4 origin is inferred from the table names, row counts and local058's wording. I have not done a byte-level comparison with the published dump. The licence is unstated. Fitting statistics is fine; redistributing rows needs a check.
- **The mod-4 group rule** is unexplained (§4). Stage 2 can draw the group at random, about 52 per group, and record that as a modelling choice.
- **Fiscal-year-start times for prices and deductions are invented.** A sim must not read them as change moments. Codebasics' fiscal calendar (September start) is confirmed only through the `fiscal_year` column (§3.1).
- **The 50 unsold products** have no price, cost or sale, and get the catalog start by rule. Their code-year digits suggest "planned for fy2022". That is unverifiable.
- **local059's "calendar year"** reading is confirmed against the CSV. A stage-2 engine that only stores fiscal years would fail it, so the rebuilt `date` must keep the month.
- **Volume.** E3 is 971,631 events. Check the refdata ingest time; olist's 918k events took 41 s for the whole round trip.
- **Merged E1.** It relies on price and cost keys being identical (579 of 579). If a future version of the source breaks that, split E1 into two events.

---

- Exact round trip: **yes**, with caveats: the 4-decimal REALs go through 1e-4 integers (proven 1,576 of 1,576 values), and `fiscal_year` is derived from `date`.
- Proposed dataset name: **`atliq`**.
- 3 event types (`product_priced`, `customer_deduction_set`, `monthly_sales_reported`; 972,628 events) and 2 entities (customers 209, products 397).
- Event shape: **partly imposed**. Sales are a monthly pre-aggregate at period stamps; prices, costs and deductions are annual snapshots at rule times (fiscal-year start).
- Hardest blocker: there is no finer grain than month × product × customer, so stage 2 can only learn monthly totals. Everything else rebuilds exactly.
