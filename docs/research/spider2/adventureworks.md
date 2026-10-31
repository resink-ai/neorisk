# AdventureWorks (Spider 2.0-lite): reverse-engineered event log

Source: `data/spider2/AdventureWorks.sqlite` (19 MB), opened read-only. `scripts/adventureworks/aw.py` copies the file into an in-memory SQLite and adds indexes (the file has none), then runs the named blocks of a `.sql` file. The Python scripts open the file with `mode=ro`. Every number below comes from a script in [`scripts/adventureworks/`](scripts/adventureworks/), and the raw output of each is saved next to it as `out_<script>.txt`. A reference such as `[q4:lead_times_by_channel]` means file `q4_lifecycle.sql`, block `-- name: lead_times_by_channel`; `[q2]` means the whole output of `q2_money.py`.

## 0. What this catalog is

- **Dataset.** This is a 13-table subset of Microsoft's **AdventureWorks OLTP** sample (the 2012–2014 release, orders 2011-05-31 to 2014-06-30). The company is a fictional bicycle maker that sells online to individuals and through salespeople to resellers. Everything is generated: it is a teaching database, not real or anonymised data.
- **Evidence that it is Microsoft's data** [q9]. `q9_provenance.py` downloads Microsoft's current install CSVs and compares them row by row:
  - `SalesOrderHeader`: 31,465 of 31,465 ids match. rowguid (case-folded), subtotal, taxamt, freight, totaldue, purchase order and account number are all equal on 31,465 of 31,465.
  - `SalesOrderDetail`: rowguid, unit price and quantity are equal on 121,317 of 121,317.
  - `SalesPersonQuotaHistory`: 163 of 163 rowguids and amounts match.
  - Every date is shifted by exactly **4,017 days**, and the revision number is 2 higher (10 and 11 against 8 and 9). The current Microsoft README says the SQL Server 2025 refresh "Dates have been adjusted". Spider's copy is therefore the earlier release, with dates in 2011–2014.
- **Evidence that it went through Postgres.** The file looks like a dump of the community port [lorint/AdventureWorks-for-Postgres](https://github.com/lorint/AdventureWorks-for-Postgres):
  - Identifiers are lower case. Booleans are the text `t` / `f`. GUIDs are lower case without braces.
  - Timestamps have Postgres's text form, with trailing zeros of the fraction dropped: `10:01:36.827`, `10:17:21.51`, `17:39:45.26` [q8:modifieddate_formats].
  - The port's `install.sql` drops exactly the computed columns that are missing here: `SalesOrderDetail.LineTotal` and `SalesOrderHeader.SalesOrderNumber`. It keeps `TotalDue`.
  - SQL NULLs became the empty string `''` (§4).
  - Two tables were loaded another way. `SalesPersonQuotaHistory` keeps CamelCase names, TEXT/REAL types and upper-case GUIDs in braces (`{99109BBF-…}`). `productreview` has a misspelt `modifeddate DATE` column, all NULL, and a separate `modifieddate VARCHAR(19)` column added after it.
- **Row counts** [p1]: salesorderheader 31,465; salesorderdetail 121,317; currencyrate 13,532; productmodelproductdescriptionculture 762; productdescription 762; product 504; SalesPersonQuotaHistory 163; countryregioncurrency 109; productsubcategory 37; salesperson 17; salesterritory 10; productcategory 4; productreview 4. That is 168,486 rows.
- **Absent tables.** Customers, addresses, credit cards, ship methods, special offers, product models and stores are not in the subset. Their ids appear only as bare integers (§1).
- **Licence.**
  - Microsoft's [sql-server-samples](https://github.com/microsoft/sql-server-samples) README says "These samples and templates are all licensed under the MIT license". Its `license.txt` reads "Microsoft SQL Server Sample Code, Copyright (c) Microsoft Corporation … MIT License". The repository holds the data CSVs, and no separate data licence is stated.
  - The Postgres port is also MIT ("Copyright (c) 2020 Polangeles LTD").
  - The Spider2 repository is MIT ("Copyright (c) 2024 bird_sql").
  - So the data is **MIT**. Unlike Olist (CC BY-NC-SA), the source file could legally be redistributed with attribution. The repo's convention of not committing `data/` still applies.

## 0.1 How Spider 2.0 uses it

| id | Analysis | Gold SQL? | Reproduced |
|---|---|---|---|
| local141 | Per salesperson and year: total sales minus the sum of that year's quotas | **No** (404). Two result CSVs: `_a` (62 rows), `_b` (58 rows) | **Yes, exactly** [q7] |

- "Total sales" in the gold is **`sum(totaldue)`** (tax and freight included), by `strftime('%Y', orderdate)`. The quota side is `sum(SalesQuota)` by year of `QuotaDate`.
  - `_b` is the inner join on (salesperson, year): 58 of 58 rows match, for example 274 / 2011: 32,567.9155 − 126,000 = −93,432.0845.
  - `_a` is a left join from sales. It adds 4 rows with an empty salesperson, which are the online orders. Their "difference" is `sum(totaldue)`, so the quota counts as 0: 2011 4,268,747.9012, …, 2014 9,251,977.1208. 62 of 62 match.
  - With `sum(subtotal)`, 0 of 58 match.
- What the round trip must keep for this question: `totaldue` exactly per order, `orderdate`, `salespersonid` (`''` for online orders), `QuotaDate` and `SalesQuota`.

## 1. Inventory, keys, joins

No keys are declared. Every key below was checked for uniqueness [q1:pk_uniqueness].

| Table | Rows | Key (verified unique) | Kind |
|---|---:|---|---|
| salesorderheader | 31,465 | salesorderid (43659..75123, dense) | activity: the order, with 3 dates |
| salesorderdetail | 121,317 | salesorderdetailid (1..121317, dense); also (salesorderid, productid) | activity: order lines, no time of their own |
| currencyrate | 13,532 | currencyrateid (1..13532); also (date, from, to) | exogenous daily input |
| SalesPersonQuotaHistory | 163 | (BusinessEntityID, QuotaDate) | event stream: quota decisions |
| productreview | 4 | productreviewid | activity |
| product | 504 | productid; name and productnumber are also unique | dimension |
| productcategory / productsubcategory | 4 / 37 | their ids | dimension |
| productdescription | 762 | productdescriptionid | dimension (6 languages) |
| productmodelproductdescriptionculture | 762 | (productmodelid, cultureid); also productdescriptionid | link table, 127 models × 6 cultures |
| salesperson | 17 | businessentityid (274..290) | dimension with snapshot counters |
| salesterritory | 10 | territoryid | dimension with snapshot counters |
| countryregioncurrency | 109 | (countryregioncode, currencycode) | static reference |

There are 154,279 GUIDs across 9 tables, and all of them are distinct [q1:pk_uniqueness].

**Join coverage** [q1:fk_coverage]. These resolve at 100%:
- detail → header, and every header has at least one line;
- detail → product; header → territory;
- header.salespersonid (3,806 non-empty) → salesperson;
- header.currencyrateid (13,976 non-empty) → currencyrate;
- product → subcategory → category;
- link table → productdescription, in both directions;
- review → product; quota → salesperson, and every salesperson has quotas;
- territory country → countryregioncurrency.

These do not:
- Only **266 of 504 products are ever sold**. All 266 are finished goods. The 209 products without a subcategory are components that are never sold [q1:product_classes].
- The link table has 127 product models; products use 119; 118 are in both [q1:fk_coverage]. The productmodel table itself is absent.
- Ids with no table [q1:missing_dimension_tables]:
  - customerid: 19,119 distinct; billtoaddressid and shiptoaddressid: 19,119 each;
  - creditcardid: 18,384; shipmethodid: 2; specialofferid: 12.
- Each customer has one account number, one territory, one bill-to address and one channel (0 exceptions each). 210 reseller customers had more than one salesperson.

**Ids follow time.**
- salesorderid = 43,658 + rank by (orderdate, id) for 31,465 of 31,465 [q13], so header ids never decrease with orderdate [q1:header_id_vs_orderdate].
- salesorderdetailid equals the rowid, and it is contiguous within each order, in header order, for 31,465 of 31,465 orders [q1:detailid_contiguous_by_order].
- currencyrateid runs in (date, currency) order for ids 1..12,435. Ids 12,436..13,532 are a USD→USD block appended later [q5:rate_id_order, q5:rate_modifieddate_diff].

The graph is a star centred on the order header. Lines carry the product, and the header carries the salesperson, territory, currency rate and the ids of the absent tables.

## 2. Event catalog

The snapshot time is **N = 2014-07-07 00:00:00**. It is the last shipdate and the last header modifieddate [q4:snapshot_bounds]. Every time below comes from the source, with one exception: the quota event is timed at its own `ModifiedDate`, also a source column. **No time needs to be invented.**

| # | Event | Owner | Time | Attributes | Source rows | Count |
|---|---|---|---|---|---|---:|
| E1 | `order_placed` | salesorderid | orderdate (midnight) | salesorderid, revisionnumber, onlineorderflag, customerid, accountnumber, purchaseordernumber, salesperson (opt ref), territory (ref), billto/shipto address ids, shipmethodid, creditcardid (opt), creditcardapprovalcode, currencyrateid (opt), **taxamt, freight**, due_date, rowguid | header | 31,465 |
| E2 | `order_line_added` | salesorderid | orderdate. The line's own modifieddate equals it for 121,317 of 121,317 [q4:detail_modifieddate_vs_header] | salesorderdetailid, product (ref), orderqty, specialofferid, unitprice, discount, rowguid | detail | 121,317 |
| E3 | `order_shipped` | salesorderid | shipdate | carriertrackingnumber (one per reseller order, `''` online) | header (shipdate, status, modifieddate) and detail (carriertrackingnumber) | 31,465 |
| E4 | `currency_rate_published` | tocurrencycode | currencyratedate | currencyrateid, fromcurrencycode, averagerate, endofdayrate, modifieddate (text) | currencyrate | 13,532 |
| E5 | `quota_set` | BusinessEntityID | ModifiedDate (= QuotaDate − 45 d for 163 of 163) | salesperson (ref), quota_date, SalesQuota, rowguid (braced, upper case) | SalesPersonQuotaHistory | 163 |
| E6 | `product_reviewed` | productreviewid | reviewdate | product (ref), reviewername, emailaddress, rating, comments | productreview | 4 |
| | **total** | | | | | **197,946** |

**Entities** (static snapshots, 1,443 rows):

| Entity | Rows | Notes |
|---|---:|---|
| `product_categories` | 4 | name, rowguid, modifieddate |
| `product_subcategories` | 37 | ref category |
| `products` | 504 | all 25 columns verbatim. `sellstartdate` is a candidate `created_at`. 238 are never sold |
| `product_descriptions` | 762 | description plus the link row (productmodelid, cultureid, link modifieddate). This works because productdescriptionid is unique in the link table, so one entity rebuilds both tables |
| `territories` | 10 | including salesytd, saleslastyear, costytd and costlastyear (all 0) |
| `salespersons` | 17 | including salesquota, bonus, commissionpct, salesytd and saleslastyear, all as snapshot attributes (§3.4) |
| `country_currencies` | 109 | reference pairs, including obsolete currencies (DEM, FRF, …) |

**What is not an entity, and why.**
- **Customers** (19,119), addresses, credit cards, ship methods, special offers and product models have no table in the subset. Their ids ride on E1 and E2 as `i64` attributes. A `customers` entity derived from orders would add nothing to the rebuild: each customer's account number, territory and address are constant (§1), so the attributes repeat exactly.
- **Currencies** (14) are only the owner value of E4. No currency table exists.
- **Order status** is not an event. It is `'5'` (Shipped) on every row, so it is a projection of E3 (§3).

**Projection at N.**
- `salesorderheader`: one row per E1. shipdate and modifieddate come from E3's time, status = `'5'` because E3 exists, duedate = the E1 attribute, subtotal and totaldue are derived from the lines (§3.1), and comment = `''`.
- `salesorderdetail`: one row per E2. modifieddate = the order's E1 time, and carriertrackingnumber comes from the order's E3.

## 3. Rebuild rules and blockers to an exact round trip

`q13_rebuild_rules.py` replays each rule in integer arithmetic and counts exact matches.

1. **Header money is an exact function of the lines, with one exception: reseller tax and freight.**
   - `LineTotal` is `UnitPrice * (1.0 - UnitPriceDiscount) * OrderQty` in SQL Server's DDL, and Microsoft's CSV holds it to 6 dp, exact for 121,317 of 121,317 [q9].
   - `subtotal` equals the line sum rounded **half-up** to 4 dp for 31,465 of 31,465. Other rules miss: the plain sum matches 30,770, half-even rounding 31,437, and summing rounded lines 31,271. The 28 orders that half-even rounding misses are all exact ties at 0.00005 [q2, q3].
   - In integers: `subtotal4 = (Σ up4·qty·(100 − disc100) + 50) div 100`. This holds for 31,465 of 31,465 [q13]. All money is on the 1e-4 grid, and the discount is on the 1e-2 grid (0, 0.02 … 0.40) [q2].
   - `totaldue = subtotal + taxamt + freight` holds in decimal for 31,465 of 31,465, but as **float addition only 20,033** [q2]. For example, 20565.6206 + 1971.5149 + 616.0984 gives 23153.233899999996. The views must add 1e-4 integers and divide once: `(sub4 + tax4 + fr4) / 1e4` is exact for 31,465 of 31,465 [q13].
   - **Online orders (27,659):** taxamt = round_half_up(8% of subtotal) and freight = round_half_up(taxamt × 5/16, i.e. 2.5% of subtotal), each for 27,659 of 27,659 [q13].
   - **Reseller orders (3,806):** only 26 have 8% tax. taxamt / subtotal has p50 0.0960, min 0.0800, max 0.2880, and 0.096 ≈ 1.2 × 8% [q3]. No base from the lines works: 8% of Σ unitprice·qty matches 26, and 8% of the list-price sum matches 0. Freight is round(tax × 0.3125) for 3,495 rows and off by ±0.0001 for 311.
   - So **taxamt and freight are carried as E1 attributes.** The 1.2 factor probably comes from an older price list, because Microsoft repriced reseller lines without recomputing the header (§7).
2. **Dates are a fixed lifecycle.** Every time is midnight [q4:time_of_day].
   - shipdate = orderdate + 7 d (31,456) or + 8 d (9 orders).
   - duedate = shipdate + 5 d (31,465 of 31,465) [q12:due_minus_ship].
   - The 9 orders at + 8 d are all German reseller orders with revisionnumber 9, from 2014-01-28 to 2014-04-30 [q5:plus8_orders].
   - status is the text `'5'` on all 31,465, and there is no other code. So no order is in process, approved, backordered, rejected or cancelled [q4:status_revision].
   - 211 orders ship after the last order date, and all ship by N [q4:snapshot_bounds].
   - E3 can therefore carry nothing but its time. due_date rides on E1 as the promise, and the rule `due = ship + 5` is a law for stage 2, not something the rebuild needs.
3. **`rowguid` / `modifieddate` columns.**
   - rowguids are random UUIDv4 (version nibble `4`; the variant nibble is 8/9/a/b in roughly equal numbers [q8:rowguid_shapes]). They are not derivable, so they are carried verbatim as text. The quota GUIDs keep their `{UPPER}` form.
   - These modifieddates are derived: header = shipdate, detail = orderdate, quota = QuotaDate − 45 d, and review = reviewdate [q13].
   - currencyrate.modifieddate equals the rate date except on the 1,097 USD rows, which all hold `2014-01-02 17:39:45.26` [q13]. The rebuild can use a rule, or carry the text.
   - On the dimension tables, modifieddate is a load stamp: products `2014-02-08 10:01:36.827` (503) and `…10:03:55.51` (1); descriptions `2013-04-30` (636) and `2014-02-08 10:32:17.973` (126) [q8:modifieddate_formats]. These are entity attributes, kept as **text**, because a `ts` round trip would have to re-create Postgres's trimmed fraction (`.51`, not `.510`).
4. **Salesperson and territory counters are stale snapshots, not functions of the orders** [q6].
   - salesperson.salesytd matches no order window. salesytd / window sum is 2.43–9.18 for calendar 2014, and 1.15–1.31 for fiscal 2014 (Jul 2013–Jun 2014) except 285, where it is exactly 1. Calendar 2013 and totaldue match no one either.
   - It equals the all-time subtotal for 3 of 17 (285, 286 and 288, who were hired in 2013). saleslastyear matches 1 of 17.
   - territory.saleslastyear equals Σ salesperson.saleslastyear for 5 territories (1, 7, 8, 9, 10) and differs for the other 5. salesytd equals the salesperson sum for 0 of 10.
   - salesperson.salesquota (250,000 / 300,000, or `''`) is not the latest quota history amount (1,000 – 1,329,000).
   - All of these columns are **carried as entity attributes**. A generator that recomputes them from simulated orders will not match the source. Stage 2 should leave them as reference constants, or redefine them.
5. **NULL is `''`, so storage classes mix.** These INTEGER and FLOAT columns hold integers or reals plus the text `''`: salespersonid, creditcardid, currencyrateid, productsubcategoryid, productmodelid, product.weight, salesperson.territoryid and salesquota [q8:mixed_storage_classes].
   - DuckDB has one type per column, so a view must emit VARCHAR (`''` or the number as text).
   - `rebuild` creates the table with the source DDL, so SQLite's type affinity turns `'274'` back into INTEGER 274 and `'2.12'` into REAL 2.12, while `''` stays TEXT.
   - Simulated with the source DDL: 0 value-or-typeof mismatches in all 8 mixed columns. Every REAL column also survives a text round trip, with 0 differences [q10].
   - productreview.modifeddate is a real NULL (4 of 4), and every other "missing" value is `''`.
6. **Text that must stay byte-exact.**
   - nchar codes keep trailing spaces: `'CM '`, `'LB '`, `'G  '`, `'M '`, `'T '`, `'H '`, `'U '`, `'W '` [q8:trailing_spaces].
   - Booleans are `'t'` / `'f'`, and status is `'5'` as text.
   - The review comments contain LF (4 of 4, no CR) [q8:newlines_in_text].
   - 622 of 762 descriptions are non-ASCII (Arabic, Hebrew, Thai, Chinese). Description text is not unique: 733 distinct values over 762 ids [q8:productdescription_duplicates].
7. **Floats.** Every money and rate value is the nearest double to a decimal with at most 4 places, on 100% of rows of all 16 money and rate columns [q2].
   - This is why `amount()` in 1e-4 units with `CAST(n AS DOUBLE) / 10000` is exact. Prices, tax, freight, salesytd and averagerate all fit.
   - For cents (1e-2) it is not: only 25,531 of 31,465 subtotals and 267 taxamts are on the cent grid. Treat this money as **4-decimal**.
8. **Duplicates and missing times.** No table has duplicate rows (all keys unique). Every row has a time except the static dimensions.

## 4. Measured quirks

- **Two channels with disjoint shapes** [q4:channel_columns, q4:shipmethod_by_channel, q4:carriertracking_by_channel, q4:accountnumber_format]:

  | | Online (`t`) | Reseller (`f`) |
  |---|---:|---:|
  | Orders | 27,659 | 3,806 |
  | salespersonid | `''` on all | set on all |
  | purchaseordernumber | `''` on all | `PO` + 8–11 digits |
  | shipmethodid | 1 | 5 |
  | carriertrackingnumber | `''` on all lines | one per order (3,806 distinct) |
  | accountnumber | `10-4030-` + customerid (6 digits) | `10-4020-` + a 1..701 reseller number |
  | customerid range | 11000–29483 | 29484–30118 |
  | no creditcard | 1,124 | 7 |
  | unitprice = listprice | 57,949 of 60,398 lines | 0 of 60,919 (discounted to 0.45–0.6 of list) |
  | revisionnumber | 8 | 8 (3,776), 9 (30) |

- **Currency-rate attachment is not a clean rule** [q4:rate_presence_by_territory, q5:non_us_orders_rate_by_period, q5:currency_mismatch]:
  - Non-US orders have a rate for 13,955 of 18,840 when the rate day exists.
  - No order dated after 2014-05-31, the last rate day, has a rate (584 non-US online orders).
  - 21 US online orders carry a CAD rate.
  - Of the 81 French online orders with a rate, 59 carry FRF and 22 carry GBP. The 34 French reseller orders with a rate carry EUR.
  - The rate's date always equals the order date (13,976 of 13,976) [q4:rate_vs_order].
  - So currencyrateid is carried, not derived. Only 2,514 of the 13,532 rates are ever used [q5:rate_usage].
- **The rate grid is complete and daily** [q5:rate_grid_completeness, q5:rates_per_currency]:
  - 1,097 days × 12 currencies, plus DEM and FRF for the first 184 days only, up to 2011-11-30. With the 10-year back-shift the release made, that is the end of November 2001, the eve of the euro.
  - There is a USD→USD row at 1.0 every day.
  - averagerate equals endofdayrate on 4–77 days per currency, and the difference is within ±0.7% [q5:eod_vs_avg].
- **Generator fingerprints.**
  - Online quantity is always 1 (60,398 of 60,398 lines) [q11].
  - Reseller orders fall on 1–3 days per month, at or near a month end (the top days are 2013-06-30, 2013-09-30, 2014-05-01 and 2014-03-31). 2011-06, 2011-09, 2011-11 and 2014-06 have none. Each reseller orders at most twice a month. The gap between a reseller's orders is 3 months for 2,517 of 3,171 [q8:reseller_orders_per_month, q11].
  - Quotas are hindsight. A quarter's quota is 1.06–1.34 × (p10–p90) the actual subtotal of that quarter, with corr 0.987 [q6].
  - 35 online customers place 16–28 orders each. The top three order from 2013-07 on, each with one card [q12:max_online_orders_per_customer, q12:heavy_online_customer_example].
  - Online demand jumps from 333 orders (2013-05) and 533 (2013-06) to 1,564 (2013-07), 4.7× the May level. That is when the 2013-05-30 product launch (136 products) reaches the web [q11, q8:product_dates].
- **Sales outside the sell window.** 64 lines sell a product after its `sellenddate`, and 0 sell before `sellstartdate` [q8:product_sold_outside_sell_window]. Products launched 2012-05-30 all sell first on that same day (71 of 71) [q12:product_first_sale_vs_sellstart].
- **Salesperson territory ≠ order territory.** Salesperson 289 is in territory 10, but all of his orders are in territory 6. Salesperson 274 (no territory) sells in 6 territories [q12:salesperson_first_activity].
- **Other constant or empty columns.** `comment` is `''` on all orders; `discontinueddate` is `''` on all products; costytd and costlastyear are 0 on all territories [p1, q8:territory_cost_cols].
- **Special offers without a discount.** Offers 2, 13 and 14 have 0 discount on 2,151 lines, so the offer id does not fix the discount [q8:lines_with_zero_discount_special_offer].

## 5. Distributions to fit

All from `q11_dists.py` unless noted.

1. **Arrivals.**
   - Online orders per day by year: 5.67 (2011), 7.49 (2012), 34.48 (2013), 61.5 (2014, half year). Only 3 days in the range have no online order [q8:online_orders_per_day, q8:online_daily_gap_days].
   - The weekday mix is flat (3,029–3,237 per weekday).
   - New online customers per month ramp from about 150 to 330 until 2013-05, then about 1,050–1,200 from 2013-07 on.
   - Resellers order on month-end batch days.
2. **Online customers.**
   - 18,484 customers: 11,619 order once, 5,454 twice, 1,166 three times, and a tail out to 28.
   - Repeat gap in days: p10 20, p50 254, p90 701.
3. **Basket size.**
   - Online: mean 2.18 lines per order (1: 9,668; 2: 8,163; 3: 5,870; 4: 3,138; 5+: 820), quantity 1.
   - Reseller: mean 16.0 lines (p50 9, p90 41, max 72), quantity mean 3.52 (p50 3, p90 7, p99 15; quantity 1 on 23.9% of lines).
4. **Order value.**
   - Online subtotal: p25 46, p50 595, p75 2,182, p90 2,451, log10 mean 2.47, sd 0.88. The gap between p25 and p75 suggests two modes, accessory-only baskets and baskets with a bike.
   - Reseller: p50 8,258, p90 57,031, log10 mean 3.79, sd 0.89.
   - Totals: online 29.36 M, reseller 80.49 M.
5. **Product mix.**
   - 266 products sell. Top 1 is 3.9% of lines, top 10 is 24.9%, top 50 is 56.5%.
   - Category share of lines: online Accessories 0.60, Bikes 0.25, Clothing 0.15; reseller Bikes 0.41, Components 0.31, Clothing 0.20, Accessories 0.08.
   - Special offer 1 (no discount) is on 95.5% of lines.
6. **Lifecycle conversion.** 100% are shipped; the lag to shipping is 7 d (99.97%), and the lag from shipping to due is 5 d [q4:lead_times_by_channel]. There are no cancellations, so this dataset cannot fit an attrition model.
7. **Resellers.**
   - 635 resellers, with orders per reseller p50 4, p90 12.
   - Reseller orders per salesperson range from 473 (277) to 16 (285).
   - The quarterly cadence dominates, with 3-month gaps for 79%.
8. **Quotas.** 163 events on 12 quarter dates, 45 days ahead. Amounts p10 116k, p50 507k, p90 1.22M, always a multiple of 1,000. A good model is quota = round_1000(k × next-quarter sales) with k ≈ 1.18.
9. **Currency rates** [q11, q5:rate_daily_change]:
   - Daily log-return sd: CNY 0.0002, SAR 0.0001, CAD 0.0029, GBP 0.0042, EUR 0.0059, AUD 0.0062, VEB 0.0101, BRL 0.0117, ARS 0.0207 (ARS goes 1.0 → 3.55, VEB 634 → 1,362).
   - The rate is unchanged from the previous day on 70–766 of 1,096 days, depending on the currency (DEM 11 and FRF 10 of 183; USD always).
   - Fit a random walk with a per-currency drift, volatility and "stale-day" probability, or replay the series as an exogenous input.

## 6. simkit mapping sketch

Project: **`adventureworks`**. Money is `amount("USD")` in **1e-4 units** (see §7), and discounts are `i64` hundredths.

```python
p.entity("product_categories", key="category_key", cols={"ext_id": text(), "name": text(), "rowguid": text(), "modifieddate": text()})
p.entity("product_subcategories", key="subcategory_key", cols={"ext_id": text(), "category_key": ref("product_categories"), "name": text(), "rowguid": text(), "modifieddate": text()})
p.entity("products", key="product_key", cols={"ext_id": text(), "name": text(), "productnumber": text(), "makeflag": text(), "finishedgoodsflag": text(),
         "color": text(), ..., "standardcost": amount(), "listprice": amount(), "weight": text(),          # '' or a number, as text
         "productsubcategoryid": text(), "productmodelid": text(), "sellstartdate": text(), "sellenddate": text(), "discontinueddate": text(), "rowguid": text(), "modifieddate": text()})
p.entity("product_descriptions", key="description_key", cols={"ext_id": text(), "description": text(), "rowguid": text(), "modifieddate": text(),
         "productmodelid": i64(), "cultureid": text(), "link_modifieddate": text()})
p.entity("territories", key="territory_key", cols={"ext_id": text(), "name": text(), "countryregioncode": text(), "group": text(), "salesytd": amount(), "saleslastyear": amount(), "costytd": amount(), "costlastyear": amount(), "rowguid": text(), "modifieddate": text()})
p.entity("salespersons", key="salesperson_key", cols={"ext_id": text(), "territoryid": text(), "salesquota": text(), "bonus": i64(), "commissionpct": f64(), "salesytd": amount(), "saleslastyear": amount(), "rowguid": text(), "modifieddate": text()})
p.entity("country_currencies", key="cc_key", cols={"ext_id": text(), "countryregioncode": text(), "currencycode": text(), "modifieddate": text()})

p.event("order_placed", cols={"salesorderid": i64(), "revisionnumber": i64(), "online": cat("t", "f"), "customerid": i64(), "accountnumber": text(),
        "purchaseordernumber": text(), "salesperson_key": opt(ref("salespersons")), "territory_key": ref("territories"), "billtoaddressid": i64(),
        "shiptoaddressid": i64(), "shipmethodid": i64(), "creditcardid": opt(i64()), "creditcardapprovalcode": text(), "currencyrateid": opt(i64()),
        "taxamt": amount(), "freight": amount(), "due_date": ts(), "rowguid": text()})
p.event("order_line_added", cols={"salesorderid": i64(), "salesorderdetailid": i64(), "product_key": ref("products"), "orderqty": i64(),
        "specialofferid": i64(), "unitprice": amount(), "discount_pct": i64(), "rowguid": text()})
p.event("order_shipped", cols={"salesorderid": i64(), "carriertrackingnumber": text()})
p.event("currency_rate_published", cols={"currencyrateid": i64(), "fromcurrencycode": text(), "tocurrencycode": text(), "averagerate": f64(), "endofdayrate": f64(), "modifieddate": text()})
p.event("quota_set", cols={"salesperson_key": ref("salespersons"), "quota_date": ts(), "salesquota": f64(), "rowguid": text()})
p.event("product_reviewed", cols={"productreviewid": i64(), "product_key": ref("products"), "reviewername": text(), "emailaddress": text(), "rating": i64(), "comments": text()})
```

**ingest.sql.**
- Blocks in this order: entities; then `order_placed owner=salesorderid ord=salesorderid`; `order_line_added owner=salesorderid ord=salesorderid`; `order_shipped owner=salesorderid ord=salesorderid`; `currency_rate_published owner=tocurrencycode ord=currencyrateid`; `quota_set owner=BusinessEntityID`; `product_reviewed owner=productreviewid`.
- Use `NULLIF(col,'')` for the opt refs and ids. Map `unitprice*10000` and `round(unitpricediscount*100)` to integers.
- Events at the same time sort by `ord`, then block position. Detail ids (1..121,317) are smaller than header ids (43,659+), so `ord = salesorderdetailid` on E2 would put lines ahead of headers at the same midnight. Use `ord = salesorderid` on E1, E2 and E3. Then E1 precedes E2 by block position, and lines keep the block's `ORDER BY salesorderdetailid`.

**views.sql.**
- Header: `subtotal = ((sum(up4*qty*(100-disc)) + 50) // 100) / 1e4` and `totaldue = (sub4 + taxamt + freight) / 1e4`. shipdate and modifieddate come from E3's time formatted `%Y-%m-%d %H:%M:%S`. status `'5'`, comment `''`.
- Every nullable id becomes `coalesce(CAST(x AS VARCHAR), '')`.
- Detail: modifieddate = E1's time; carriertrackingnumber from E3.
- Quota: `QuotaDate` from the attribute; `ModifiedDate` = the event time. rowguid verbatim.

**Saved query.** local141, the `_b` reading (inner join, `sum(totaldue)`), with a top-level ORDER BY.

**Stage 2 owners.**
- A `web_store` source of online customers, with a piecewise arrival rate. 2013-07 is a regime change.
- One `reseller` owner per store, with a quarterly cadence on month-end batch days, attached to a salesperson.
- A `pricing` table: online price = list price for 57,949 of 60,398 lines. Reseller price is 0.6 × list on most lines (43,553 of all lines), with 22 other ratios [q2].
- A `currency` owner with a daily timer (random walk) or a replayed exogenous stream.
- A `sales_manager` that emits `quota_set` 45 days before each quarter.
- Order machine: `placed → shipped (timer 7 d) → (due at +12 d)`. Laws: online tax = 8%, freight = tax × 5/16, subtotal = Σ lines half-up, totaldue = sum.

Volume at native size is about 198k events. That is comfortable, and no reduced profile is needed.

## 7. Open questions and risks

- **`amount()` at 4 decimals.** simkit's `amount(asset)` is "integer minor units", and the batch-1 views assume cents (`/ 100`). Here the minor unit has to be 1e-4. Either declare an asset such as `"USD4"`, or document per pack that the minor unit is 1e-4. Something downstream, such as stats or currency formatting, may assume 2 dp. Check before writing the pack.
- **Reseller tax and freight.** These are not derivable from the lines (26 of 3,806 at 8%). The ~1.2 factor looks like a pre-revision subtotal, because Microsoft repriced reseller lines and did not re-run the header. This is unverified. Stage 2 can model tax/subtotal as a mixture around 0.096, but there is no causal rule.
- **Salesperson and territory YTD counters.** They are consistent with neither the orders nor each other (§3.4). Keep them as reference constants. Any law tying them to orders would fail on real data.
- **Currency-rate attachment.** It is noisy: there are US orders with CAD, French orders with GBP, and a quarter of eligible non-US orders have no rate. The rule cannot be learned from this table alone (customer and address tables are absent). Carry `currencyrateid` and treat the attachment as a per-order Bernoulli draw.
- **The status column has one value.** Every order is shipped, so the lifecycle has no failure branches. Stage 2 can generate only the happy path unless it invents rejection or cancellation rates, which this data would not support.
- **Dimension modifieddate as text.** The fractional seconds are in Postgres's trimmed form. Keeping them as text avoids a fragile `ts` format, at the cost of not being typed times. If they should be `ts`, the view needs a "strip trailing zeros" formatter like cliquebait's.
- **Affinity dependence.** The exact round trip of the 8 mixed columns relies on `rebuild` creating tables with the source DDL, as it does today, and on Python's sqlite3 inserting VARCHAR values. If `rebuild` ever builds tables without declared types, those columns would come back as TEXT `'274'`.
- **Missing dimensions.** Customer, address, credit card and special-offer tables are absent. A Spider question that needs them cannot exist on this file. If a fuller AdventureWorks ever appears in Spider2, this pack should grow entities for them rather than id attributes.

## Summary

1. **Feasible for an exact round trip: yes, with caveats.** Every table has a time or is a static dimension. Subtotal, totaldue, status, shipdate/duedate and most modifieddates are exact rules; reseller tax and freight, the YTD counters, the rowguids and the currencyrateid are carried as data.
2. **Project:** `adventureworks` (one project, 13 tables, local141 as the saved query; its gold reproduces exactly with `sum(totaldue)`).
3. **Events:** 6 types, 197,946 events (31,465 order_placed + 121,317 order_line_added + 31,465 order_shipped + 13,532 currency_rate_published + 163 quota_set + 4 product_reviewed), N = 2014-07-07, no invented times.
4. **Entities:** 7 (products, product_categories, product_subcategories, product_descriptions carrying the link table, territories, salespersons, country_currencies), 1,443 rows.
5. **Hardest blocker:** 4-decimal money that must be summed exactly. subtotal is Σ lines rounded half-up, and totaldue fails as float addition on 11,432 orders, so the views need 1e-4 integer arithmetic (and simkit `amount()` at 1e-4). Next is the `''`-as-NULL mixed storage classes, which round-trip only through the source DDL's type affinity.
