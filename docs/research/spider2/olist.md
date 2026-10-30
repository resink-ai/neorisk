# Olist (Spider 2.0 copies): reverse-engineering the event log behind the tables

Scope: analysis only. All numbers come from queries run read-only against the Spider2-lite SQLite files. The query scripts are in `reveng/scripts/` and their raw outputs in `reveng/out/`. Each section cites the script that backs it (`01_copies.sql` … `09_cancel.sql`, `04_dists.py`). `runsql.py` runs a `.sql` file of `-- name:` blocks with `mode=ro` and ATTACHes `E_commerce` as `e` (and `electronic_sales` as `x`).

Paths: DB folder `data/spider2/` (see `refdata fetch`); scripts [`scripts/`](scripts/).

---

## 0. The three files

| File | Tables | Differs from `Brazilian_E_Commerce`? |
|---|---|---|
| `Brazilian_E_Commerce.sqlite` | `olist_*` (9 + duplicate `olist_products_dataset`) | reference copy |
| `E_commerce.sqlite` | same tables without the `olist_` prefix, **plus `leads_qualified` (8,000) and `leads_closed` (842)** | Content is identical (EXCEPT both ways = 0 and the row counts are equal), and so is the row order: 0 rowid mismatches on `orders` |
| `electronic_sales.sqlite` | same 9 tables (no leads), each with an extra `"index"` column 0..n‑1 | Content is identical (EXCEPT = 0, equal counts); the only addition is the `index` column |

`olist_products_dataset` equals `olist_products` plus an `index` column (0..32950, rowid-aligned). NULLs are real NULLs everywhere, with no empty strings (`01_copies.sql`, `03_quirks.sql`). Datatypes: timestamps are TEXT `YYYY-MM-DD HH:MM:SS`, except `leads_qualified.first_contact_date`, which is `YYYY-MM-DD`. Money is FLOAT and always exact cents: 0 values off the cent grid (`04_dists.py`).

## 1. Table inventory

No FKs or PKs are declared. The keys and joins below are inferred and verified (`02_keys_joins.sql`).

| Table | Rows | Key (verified unique) | Kind | Notes |
|---|---:|---|---|---|
| olist_orders | 99,441 | order_id | activity (order header; 5 timestamps) | `customer_id` is also unique, so orders and customers are 1:1 |
| olist_order_items | 112,650 | (order_id, order_item_id) | activity (cart lines, no own timestamp) | `order_item_id` is always contiguous 1..n (98,666/98,666). Quantity is expressed as repeated rows |
| olist_order_payments | 103,886 | (order_id, payment_sequential) | activity (no timestamp) | 99,440 orders; 80 orders have no `seq=1` row |
| olist_order_reviews | 99,224 | (review_id, order_id) | activity (2 timestamps) | `review_id` alone is NOT unique: 98,410 distinct |
| olist_customers | 99,441 | customer_id | per-order snapshot of the buyer | `customer_unique_id` = the person (96,096 distinct) |
| olist_sellers | 3,095 | seller_id | static dimension | every seller sold at least once |
| olist_products | 32,951 | product_id | static dimension | every product sold at least once |
| olist_geolocation | 1,000,163 | none (zip prefix 19,015 distinct) | static reference | 261,831 exact duplicate rows (738,332 distinct) |
| product_category_name_translation | 71 | product_category_name | static reference | |
| leads_qualified (E only) | 8,000 | mql_id | activity (1 date) | marketing-qualified seller leads |
| leads_closed (E only) | 842 | mql_id (and seller_id unique) | activity (1 timestamp) | won deals |

Join coverage, as the share of child rows that find a parent:

| Join | Coverage |
|---|---|
| orders.customer_id → customers (and back) | 100% / 100% |
| items.order_id → orders; items.product_id → products; items.seller_id → sellers | 100% each |
| payments.order_id → orders; reviews.order_id → orders | 100% |
| products.category (non-null) → translation | 32,328 / 32,341 = 99.96%. `pc_gamer` (3) and `portateis_cozinha_e_preparadores_de_alimentos` (10) are untranslated |
| customers.zip → geolocation | 99,163 / 99,441 = 99.72% |
| sellers.zip → geolocation | 3,088 / 3,095 = 99.77% |
| customers (zip, city) → geolocation (zip, city) | 99,123 / 99,441 = 99.68% |
| leads_closed.mql_id → leads_qualified | 100% |
| leads_closed.seller_id → sellers | **380 / 842 = 45.1%**. The other 462 won leads never sold in the window |

Parents without children: 775 orders have no items (603 unavailable, 164 canceled, 5 created, 2 invoiced, 1 shipped). 1 order has no payment (`bfbd0f9b…`, delivered, 2016-09-15). 768 orders have no review.

The order is the hub. The graph is a star: customers–orders 1:1, and orders–items/payments/reviews 1:N. Items carry seller and product, the dimensions hang off them, and geolocation joins only by zip prefix (a many-to-many reference).

## 2. Event catalog

Notation: `T(col)` is the wall-clock string parsed as a naive timestamp (see quirk Q1, timezone). "Per row" means one event per source row. Every event carries the id(s) listed under Entity.

| # | Event | Entity (partition) | Time source | Attributes | Produces |
|---|---|---|---|---|---|
| E1 | `lead_qualified` | mql_id | `leads_qualified.first_contact_date` (date, 00:00) | landing_page_id, origin | leads_qualified row |
| E2 | `lead_won` | mql_id | `leads_closed.won_date` | seller_id, sdr_id, sr_id, business_segment, lead_type, lead_behaviour_profile, has_company, has_gtin, average_stock, business_type, declared_product_catalog_size, declared_monthly_revenue | leads_closed row |
| E3 | `order_placed` | order_id (owner: customer_unique_id) | `order_purchase_timestamp` | customer_id, customer_unique_id, customer_zip_code_prefix, customer_city, customer_state, order_estimated_delivery_date (a promise set at purchase) | orders row (id, customer_id, purchase ts, estimate); customers row |
| E4 | `order_line_added` | order_id | = E3 time (no own timestamp) | order_item_id, product_id, seller_id, price, freight_value | items row (minus shipping_limit_date) |
| E5 | `payment_recorded` | order_id | = E3 time (no timestamp) | payment_sequential, payment_type, payment_installments, payment_value | payments row |
| E6 | `order_approved` | order_id | `order_approved_at` | – | orders.order_approved_at |
| E7 | `seller_ship_deadline_set` | (order_id, seller_id) | `order_approved_at`, or E3 time if NULL (15 lines, all delivered) | shipping_limit_date (verbatim) | items.shipping_limit_date (constant per (order, seller): 100,010/100,010) |
| E8 | `order_handed_to_carrier` | order_id | `order_delivered_carrier_date` | – | orders.order_delivered_carrier_date |
| E9 | `order_delivered` | order_id | `order_delivered_customer_date` | – | orders.order_delivered_customer_date |
| E10 | `order_status_final` | order_id | **unknown**: imputed (see below) | order_status | orders.order_status, only where the naive rule is wrong |
| E11 | `review_requested` | (review_id, order_id) | `review_creation_date` (date; 85 rows carry a non-midnight time) | customer_unique_id | review row (creation) |
| E12 | `review_answered` | (review_id, order_id) | `review_answer_timestamp` | review_score, review_comment_title, review_comment_message | review row (answer) |

Entity snapshots, which have no timestamps:
- S1 `sellers`: seller_id, zip, city, state. Use E2 time as the creation time for the 380 lead-sourced sellers; otherwise the seller's first E4.
- S2 `products`: all 8 attributes.
- S3 `geolocation`: reference rows, verbatim with duplicates.
- S4 `translation`.

### Derivation rules (table to event log)

```sql
-- E1
SELECT mql_id, first_contact_date||' 00:00:00' AS t, landing_page_id, origin FROM leads_qualified;
-- E2
SELECT mql_id, won_date AS t, seller_id, sdr_id, sr_id, business_segment, lead_type, lead_behaviour_profile,
       has_company, has_gtin, average_stock, business_type, declared_product_catalog_size, declared_monthly_revenue FROM leads_closed;
-- E3
SELECT o.order_id, o.order_purchase_timestamp AS t, o.customer_id, c.customer_unique_id, c.customer_zip_code_prefix,
       c.customer_city, c.customer_state, o.order_estimated_delivery_date
FROM olist_orders o JOIN olist_customers c USING(customer_id);
-- E4
SELECT i.order_id, o.order_purchase_timestamp AS t, i.order_item_id, i.product_id, i.seller_id, i.price, i.freight_value
FROM olist_order_items i JOIN olist_orders o USING(order_id);
-- E5
SELECT p.order_id, o.order_purchase_timestamp AS t, p.payment_sequential, p.payment_type, p.payment_installments, p.payment_value
FROM olist_order_payments p JOIN olist_orders o USING(order_id);
-- E6 / E8 / E9: one event per non-null column
SELECT order_id, order_approved_at AS t FROM olist_orders WHERE order_approved_at IS NOT NULL;               -- 99,281
SELECT order_id, order_delivered_carrier_date AS t FROM olist_orders WHERE order_delivered_carrier_date IS NOT NULL;  -- 97,658
SELECT order_id, order_delivered_customer_date AS t FROM olist_orders WHERE order_delivered_customer_date IS NOT NULL; -- 96,476
-- E7
SELECT DISTINCT i.order_id, i.seller_id, COALESCE(o.order_approved_at, o.order_purchase_timestamp) AS t, i.shipping_limit_date
FROM olist_order_items i JOIN olist_orders o USING(order_id);                                               -- 100,010
-- E10: only where the status differs from the timestamp-implied one (1,857 orders)
WITH n AS (SELECT *, CASE WHEN order_delivered_customer_date IS NOT NULL THEN 'delivered'
                          WHEN order_delivered_carrier_date IS NOT NULL THEN 'shipped'
                          WHEN order_approved_at IS NOT NULL THEN 'approved' ELSE 'created' END AS implied FROM olist_orders)
SELECT order_id, order_status,
       MAX(order_purchase_timestamp, COALESCE(order_approved_at,''), COALESCE(order_delivered_carrier_date,''),
           COALESCE(order_delivered_customer_date,'')) AS t_imputed   -- last known stage; flag time_imputed=1
FROM n WHERE order_status <> implied;
-- E11 / E12 (one per (review_id, order_id) pair; the 789 shared review_ids have identical score/text/dates on every row)
SELECT review_id, order_id, review_creation_date AS t FROM olist_order_reviews;
SELECT review_id, order_id, review_answer_timestamp AS t, review_score, review_comment_title, review_comment_message FROM olist_order_reviews;
```

E10 detail: the naive status matches 97,584 / 99,441 orders (`08_status_rule.sql`). The mismatches are:

| actual | implied by timestamps | n |
|---|---|---:|
| unavailable | approved | 609 |
| canceled | approved | 409 |
| invoiced | approved | 314 |
| processing | approved | 301 |
| canceled | created | 141 |
| canceled | shipped | 69 |
| delivered | shipped | 7 |
| canceled | delivered | 6 |
| delivered | approved | 1 |

The other option is to emit E10 for every order, with the status as an attribute. That is simpler and costs 99,441 events.

## 3. Rebuild rules (event log + snapshots to tables)

| Table | Rule | Exact? |
|---|---|---|
| orders | One row per E3. approved/carrier/customer = the time of E6/E8/E9, else NULL. estimate = the E3 attribute. status = E10 if present, else the implied rule | yes |
| customers | Project E3 (customer_id, unique_id, zip, city, state) | yes. Address is per order: 250 persons have more than one zip and 39 more than one state, so it must stay on E3, not on a person entity |
| order_items | E4 ⋈ E7 on (order_id, seller_id) | yes |
| order_payments | Project E5 verbatim, including sequential gaps, `not_defined`, 0-installment rows and 0-value vouchers | yes |
| order_reviews | E11 ⋈ E12 on (review_id, order_id). creation = E11 time, formatted `YYYY-MM-DD HH:MM:SS` | yes |
| leads_qualified | E1, with t formatted as `YYYY-MM-DD` | yes |
| leads_closed | E2 | yes |
| sellers, products, translation, geolocation | Reference snapshots, copied verbatim | yes (not event-derived) |

What cannot come from events, and how to carry it:
- Static attributes (seller zip/city/state; product category, dimensions and text lengths): put them on entity snapshots. Sellers could be created by an E2 `lead_won` for 380/3,095, but the rest have no creation time.
- Geolocation (1M rows, 26% exact duplicates, 47 points outside Brazil's bounding box, 8,556 zips with several city spellings): a verbatim reference file. Do not simulate it. Spider2 query `local035` sorts it by (state, city, zip, lat, lng), so lat/lng must keep full float64 precision.
- Untimed attributes on timed events: the cart lines and payments are attached to E3, and the shipping deadline is attached to E7.

Things that block or risk an exact round trip:
1. **Row order.** `olist_orders` is in no sorted order: adjacent rows have increasing order_id in 49,830 of 99,440 pairs, which is chance level. `olist_customers` is not rowid-aligned with orders (0 matches). `order_items` is sorted by order_id. Either compare tables as multisets ordered by key, or carry the source rowid as a hidden attribute on E3/E4/E5/E11/E1/E2 if byte-identical files are required.
2. **Timezone.** The timestamps are America/Sao_Paulo local wall clock with DST (proof under Q1). simkit `ts` exports UTC µs, so store the wall-clock string as if it were UTC (seconds since `2016-09-04 00:00:00`). That makes the round trip trivially exact. Converting to true UTC would hit the fall-back ambiguous hour, where 39 timestamps exist (`08_status_rule.sql`: purchase 13, approved 9, answer 11, shipping_limit 6), and would need a fold bit.
3. **E10 time is invented.** The round trip is still exact, because only the status is rebuilt, but the event time carries no information.
4. **Free-text fields.** 3,852 review messages contain CR+LF. Keep them byte-for-byte; a CSV or JSONL sink must not normalise newlines.
5. **Float columns** (products' FLOAT lengths and dimensions, geolocation lat/lng, money) must round-trip as float64. Money is exact cents, so `amount()` in centavos is lossless.
6. **Horizon.** Event times run from 2016-09-04 (first purchase) to 2018-11-14 (last `won_date`), about 801 days. `shipping_limit_date` goes up to 2020-04-09, but it is an attribute, not an event time.

## 4. Data quirks, measured

**Null timestamps by status** (`03_quirks.sql`; columns are counts of NULL):

| status | n | approved | carrier | customer | estimate | has items | has pay | has review |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| delivered | 96,478 | 14 | 2 | 8 | 0 | 96,478 | 96,477 | 95,832 |
| shipped | 1,107 | 0 | 0 | 1,107 | 0 | 1,106 | 1,107 | 1,032 |
| canceled | 625 | 141 | 550 | 619 | 0 | 461 | 625 | 605 |
| unavailable | 609 | 0 | 609 | 609 | 0 | **6** | 609 | 595 |
| invoiced | 314 | 0 | 314 | 314 | 0 | 312 | 314 | 309 |
| processing | 301 | 0 | 301 | 301 | 0 | 301 | 301 | 295 |
| created | 5 | 5 | 5 | 5 | 0 | 0 | 5 | 3 |
| approved | 2 | 0 | 2 | 2 | 0 | 2 | 2 | 2 |

`order_purchase_timestamp` and `order_estimated_delivery_date` are never NULL. The 14 delivered orders without approval all paid by boleto.

**Out-of-order timestamps** (both values non-null):

| check | violations | of |
|---|---:|---:|
| approved < purchase | 0 | 99,281 |
| carrier < approved | **1,359** (1,350 delivered, 9 shipped). Concentrated in 2018-07 (566) and 2018-04 (393) purchases. Gap: <1 h 242, 1–24 h 659, 1–7 d 444, >7 d 14 | 97,644 |
| carrier < purchase | 166 | 97,658 |
| customer < carrier | 23 | 96,475 |
| customer < approved | 61 | 96,462 |
| customer < purchase | 0 | 96,476 |
| estimate < carrier date | 473 | – |
| delivered after estimate (late) | 7,827 (8.1%) | 96,476 |
| carrier handoff after item shipping_limit (seller late) | 10,423 lines | 111,456 |
| review_creation < purchase | 74 (45 are shared review_ids) | 99,224 |
| review_creation < date(delivered) | 5,127 | 96,359 |
| review_answer < review_creation | 0 | 99,224 |
| shipping_limit < purchase | 0. But shipping_limit − approved has min −18.5 d | 112,650 |
| lead won_date < first_contact_date | 1 (2018-03-06 vs 03-08) | 842 |

**Q1 Timezone and DST.** Three facts:
- `shipping_limit − approved` is a whole number of days with an identical hh:mm:ss in 78.8% of lines. Where it is off by −1 h, 1,525/1,582 cases have approval inside Brazilian DST and the limit outside it. Where it is off by +1 h, 1,206/1,208 cases go the other way (`07_dst.sql`).
- So `shipping_limit = approved + N×24 h` in absolute time, rendered in local São Paulo time.
- No timestamp falls in the non-existent spring-forward hour (00:00–00:59 on 2016-10-16, 2017-10-15, 2018-11-04).

**Status values without a timestamp: when did they happen?**
- **canceled** (625). The last known stage is: purchase only 141, approved 409, carrier 69, delivered 6. Canceled-before-approval is mostly voucher (71) or card (53), not boleto (14) (`09_cancel.sql`). The 6 canceled-after-delivery orders are mostly October 2016.
- **unavailable** (609). All were approved; none reached the carrier. 603/609 have no item rows, so the lines were deleted when the order went unavailable. They are still paid (avg R$207.7).
- **invoiced / processing / shipped**. These are stuck states, not end-of-window censoring: shipped orders are spread over 2016 (9), 2017 (530) and 2018 (568), and invoiced/processing appear in every month.
- The only time hint is the review: for non-delivered orders, `review_creation` falls 0–3 days after the estimated date in 62.6–74.8% of cases (by status). The survey goes out when the promise lapses, which gives an upper bound for some orders.

**Duplicates and multiplicities:**
- Reviews: 789 review_ids are attached to 2–3 orders. All 789 belong to the same customer_unique_id and have identical score, text and dates, so one survey covered several orders, and 254 of them share one purchase timestamp. Separately, 547 orders have 2–3 different reviews: 202 with different scores and 392 with different creation dates (re-reviews).
- Payments: 2,961 orders have more than one row (max 29). Extra rows are voucher 61.9% and card 38.1%. 80 orders have no `seq=1` row (52 debit, 29 credit, 1 boleto). Three `not_defined` rows of 0.00 sit on canceled orders. Two credit-card rows have 0 installments.
- Items: 6,968 orders repeat a product. Price and freight are identical across repeats (7,088/7,088 groups), so quantity is implicit. Multi-seller orders: 1,278.
- Payments vs items: the totals agree to the cent in 98,296 / 98,665 orders. Payments exceed items in 286 (89% of those have installments > 1, so interest) and fall short in 83.
- Geolocation: 261,831 duplicate rows; 47 points outside Brazil; 8 zip prefixes in more than one state.
- Products: 610 have a NULL category and NULL text lengths; 2 have NULL dimensions; 4 weigh 0 g.
- `leads_closed`: the questionnaire fields are mostly NULL (has_company 779, average_stock 776, lead_behaviour_profile 177). `declared_monthly_revenue` is 0 in 797/842. `origin` is NULL for 60 leads in `leads_qualified`.

**Timestamps outside the main window:**
- Purchases: 2016-09 has 4 orders, 2016-10 has 324 and 2016-12 has 1, with a 61-day gap of zero orders (2016-10-23..2016-12-22) and 140 empty days in total. The data restarts properly in 2017-01. It thins to 16 orders in 2018-09 and 4 in 2018-10. The usable window is **2017-01-01..2018-08-31**.
- `shipping_limit_date` reaches 2020: 4 lines on 3 orders from 2017-03/05 (about +1,056 d). It looks like a typo, with the year shifted.
- Estimate up to 2018-11-12; review answers up to 2018-10-29; leads won up to 2018-11-14 while MQLs end 2018-05-31.

**Granularity:**
- `order_estimated_delivery_date` is always 00:00:00 (date only).
- `review_creation_date` is 00:00:00 in 99,139/99,224 rows.
- `order_delivered_carrier_date` has :00 seconds in 29.5% of rows (partly minute-precision, likely manual entry). The other timestamps show about 1–1.6%, which is chance.
- `first_contact_date` is a date.

## 5. Distributions to fit (`04_dists.py`)

Stage delays (delivered orders):

| delay | p5 | p25 | p50 | p75 | p90 | p99 |
|---|---:|---:|---:|---:|---:|---:|
| purchase → approved (h) | 0.14 | 0.22 | 0.34 | 14.5 | 34.6 | 89.8 |
| same, card / boleto (h, p50 / p90) | | | 0.27 / 21.5 (card) | | 29.1 / 67.3 (boleto) | |
| approved → carrier (d) | 0.25 | 0.87 | 1.82 | 3.58 | 5.99 | 17.0 |
| carrier → customer (d) | 1.12 | 4.10 | 7.10 | 12.0 | 18.9 | 41.0 |
| purchase → customer (d) | 3.0 | 6.8 | 10.2 | 15.7 | 23.1 | 46.0 |
| purchase → estimate (d) | 10.5 | 18.3 | 23.2 | 28.4 | 34.3 | 50.2 |
| delivered − estimate (d) | −25.9 | −16.2 | −11.9 | −6.4 | −1.1 | 18.9 |
| shipping_limit − approved (d, whole-day part) | 6 d = 43.5%, 4 d = 18.0%, 5 d = 11.1%, 7 d = 9.1%, 2 d = 5.0% | | | | | |
| review_creation − date(delivered) | +1 d = 88.9%, 0 d = 3.3% | | | | | |
| review answer − creation (h) | 14.8 | 24.1 | 40.2 | 74.5 | 116.6 | 529.8 |

Approval timing: 82.5% of approvals land within 24 h. The approval hour shows a batch bump at 02–03 h (7.1% and 5.6% of approvals). Carrier handoffs happen on weekdays (Sat 1.8%, Sun 0.04%). Customer deliveries fall Mon–Fri (Sat 5.7%, Sun 1.3%).

Delivery days by customer state (p50 / p90): SP 7.2 / 15.8, MG 10.3 / 20.2, PR 10.4 / 20.1, RJ 12.0 / 29.1, SC 13.0 / 25.8, RS 13.2 / 25.9.

Estimated days from the purchase date are an integer spread over 18–29 days (22 d is the mode at 6.0%).

Volumes:

| metric | distribution |
|---|---|
| orders per customer_unique_id | 1: 96.88%, 2: 2.86%, 3: 0.21%, 4+: 0.05% (max 17). Repeat gap p50 28.3 d, but 27.5% of repeat gaps are under 1 h (split checkouts) |
| items per order | 1: 90.06%, 2: 7.62%, 3: 1.34%, 4: 0.51%, 5–6: 0.41%, max 21 |
| distinct products per order | 1: 96.72%, 2: 2.88% |
| distinct sellers per order | 1: 98.70%, 2: 1.24%, 3+: 0.06% |
| price (R$) | p5 17.0, p25 39.9, p50 74.99, p75 134.9, p90 229.8, p99 890, max 6,735 |
| freight (R$) | p5 7.78, p50 16.26, p90 34.04, p99 84.5. Zero freight on 383 lines. p50 by weight band: <0.5 kg 15.1, 0.5–2 kg 16.3, 2–10 kg 21.5, ≥10 kg 43.8 |
| order total (items + freight) | p50 105.29, p90 307.69, p99 1,063 |
| payment rows per order | 1: 97.06%, 2: 2.40%, 3: 0.30%, 4+: 0.24% |
| order payment mix | card 74.68%, boleto 19.90%, card + voucher 2.26%, voucher only 1.63%, debit 1.54% |
| card installments (share of all payment rows) | 1: 24.5%, 2: 11.95%, 3: 10.07%, 4: 6.83%, 5: 5.04%, 6: 3.77%, 7: 1.57%, 8: 4.11%, 9: 0.62%, 10: 5.13%, 12: 0.13%, max 24. Boleto, debit and voucher always 1 |
| review score | 1: 11.51%, 2: 3.18%, 3: 8.24%, 4: 19.29%, 5: 57.78%. Late deliveries: 46% are 1-star versus 6.6% on time. Mean 4.16 for delivered, 1.3–2.0 for every other status. Comment present: 76.5% at 1 star, 31–36% at 4–5 stars |

Seasonality:

| scale | facts |
|---|---|
| month | Ramps from 800 (2017-01) to a plateau of about 6.2–7.3k per month in 2018. Peak 7,544 in 2017-11 |
| day | Daily orders (2017-01..2018-08) p50 152, p90 275. Black Friday 2017-11-24 had 1,176 orders, 7.7× the median, with a tail of about 400 per day through 11-28 |
| weekday | Mon 16.3%, Tue 16.1%, Wed 15.6%, Thu 14.8%, Fri 14.2%, Sat 10.9%, Sun 12.0% |
| hour | Trough 03–05 h (about 0.2% per hour); plateau 10–22 h (6–6.7% per hour) |

Concentration and geography:

| aspect | facts |
|---|---|
| sellers | The top 1% of sellers have 25.7% of revenue, the top 10% have 67.5% and the top 20% have 82.7%. Revenue Gini 0.792. Items per seller p50 8, p90 80, max 2,033. New sellers arrive steadily at about 75–230 per month |
| products | Items per product p50 1 (18,117 products sold once), p99 33. The top 1% of products have 22.1% of items. 96.3% of products have a single seller |
| categories | 73 categories. bed_bath_table 9.9%, health_beauty 8.6%, sports_leisure 7.7%, furniture_decor 7.4%, computers_accessories 7.0% |
| customer states (orders) | SP 42.0%, RJ 12.9%, MG 11.7%, RS 5.5%, PR 5.1%, others ≤ 3.7% (27 states) |
| seller states (items) | SP 71.3%, MG 7.8%, PR 7.7%, RJ 4.3%, SC 3.6% |
| same state | Seller and customer share a state on 36.2% of items |

Lead funnel:
- MQLs arrive Jun 2017 to May 2018: about 200–450 per month in 2017, rising to 1,028–1,352 per month in 2018.
- Conversion is 842/8,000 = 10.5%. By origin: organic 11.8%, paid 12.3%, social 5.6%, unknown 16.3%, email 3.0%, direct 11.2%.
- Contact → won: p50 14.7 d, p90 162.7 d.
- Won deals peak in 2018-04 (207).
- 32 SDRs, 22 SRs and 495 landing pages.
- Won → first sale (380 sellers): p50 44.3 d, p90 102.9 d. No seller sold before its won date.

## 6. simkit mapping sketch

Partitions:
- **`customer` owner** (key = customer_unique_id; 96,096). A Source schedules each person's first order. The arrival rate follows the monthly ramp × weekday × hour profile, plus a Black Friday spike. The second order is a branch with p≈0.031: either a near-immediate split checkout (27% under 1 h) or a gap with p50 of about 28 d.
- **`order` owner**, created by the customer with `ctx.create("order")`, one per order (99k). It runs the lifecycle machine below and owns its lines, payments and status.
- **`seller` shard** (3,095, or grouped into about 100 shards by hash). Fulfilment accepts the request or declines it as unavailable, sets the deadline (E7) and hands to the carrier after the approved→carrier delay. Use weekday-only handoff timers. Seller activity is Zipf/lognormal so it reproduces Gini 0.79.
- **`payment_processor` shard**. Approval latency depends on payment type (card ≈ minutes; boleto lognormal, p50 29 h, unpaid → cancel). This is a natural `request` with `timeout` → `on_reject="canceled"`.
- **`carrier` shard** per customer-state region. Delivery delay depends on the region; no Sunday deliveries.
- **`sales` shard** (or `lead` owners) for the funnel. A Source creates 8k `lead_qualified` events. A branch with p≈0.105 per origin leads to `lead_won` after a lognormal delay (p50 15 d), which creates a seller that starts selling after a p50 44 d delay.

Order lifecycle (`order.machine`; events in brackets):

```
placed      on_enter: emit E3, E4×n, E5×k (built in the customer's checkout action)
            request payment_processor.approve  (timeout ~ boleto expiry)
              ok      -> approved
              reject  -> canceled          [E10 canceled; 141 canceled before approval]
approved    on_enter: E6; request seller.fulfil (one per seller; multi-seller 1.3% -> join "all_spawned")
              ok      -> processing/invoiced (untimed; E10 only if stuck there: 301 + 314)
              decline -> unavailable       [E10; lines are removed, so E4 must not be emitted for these orders]
              branch p≈0.5% (484/99,441) -> canceled after approval
            seller emits E7 (deadline) on accept
shipped     on_enter: E8 at handoff; request carrier.deliver
              branch p≈1.1% -> stuck (status 'shipped'; no further events)
delivered   on_enter: E9
review      timer: delivered + 1 d (or estimate + 0–3 d if never delivered) -> E11;
            answer after lognormal p50 40 h -> E12 (score depends on lateness)
```

Mechanics:
- **Holds and reservations.** There is no stock data, so inventory reservations are unnecessary. Multi-seller orders use a `std.reservations`-style join across seller shards. Payment can be a request with a timeout; a full `std.holds` is optional.
- **Latency.** Every cross-partition hop (customer→order create, order↔processor, order↔seller, seller→carrier) needs δ>0. Use sub-second platform latency; the real business delays are timers.
- **"Unavailable" removes lines.** To reproduce 603/609 orders without items, emit the lines after the seller accepts (that is, at approval), not at placement. Otherwise the rebuild needs a "line_removed" event. If the lines are kept at placement, accept a deliberate deviation from the real tables.
- **Labels and overlays.** The data has no fraud labels. Overlays could model seller lateness or boleto non-payment.

Event volume for a full-size run (`08_status_rule.sql` counts):

| event | count |
|---|---:|
| E3 order_placed | 99,441 |
| E4 order_line_added | 112,650 |
| E5 payment_recorded | 103,886 |
| E6 approved | 99,281 |
| E7 ship_deadline | 100,010 |
| E8 carrier | 97,658 |
| E9 delivered | 96,476 |
| E10 status (mismatch only) | 1,857 |
| E11 + E12 reviews | 2 × 99,224 = 198,448 |
| E1 + E2 leads | 8,842 |
| **total business events** | **≈ 918,500** |

Request/reply traffic, about three round trips per order, adds about 0.6M engine messages. Sellers (3,095), products (32,951) and translation (71) are entity inserts. Geolocation (1M rows) should stay an external reference and not be inserted through the engine.

At about 0.9M events the run sits at the top of the 10⁵–10⁶ comfort zone; scaled from the 2.6M ≈ 10 s data point, it should take about 3.5–5 s. A `sample` profile at 5–10% of customers would be about 50–90k events.

## 7. Query-level validation checks (Spider2-lite usage)

12 local questions use these DBs: E_commerce 3, Brazilian_E_Commerce 8, electronic_sales 1. Gold SQL exists only for local003, local004 and local029; exec_result CSVs exist for all 12. I reproduced the values marked ✔ (`05_gold_repro.sql`).

| id | analysis | gold value(s) | use as check |
|---|---|---|---|
| local028 | delivered orders by month × year, **by `order_delivered_customer_date` month** | 2016-10 205, 2016-11 58, 2017-01 283, 2018-08 8,314, 2018-09 56 ✔ | exact round trip; seasonality shape |
| local031 | max monthly delivered in the lowest year | 205 ✔ | exact |
| local029 | top 3 unique customers by delivered orders; avg payment, city | 15 orders, avg 58.62, sao paulo ✔ | exact; repeat-buyer tail |
| local030 | 5 cities with the lowest summed payment (delivered); avg payment and avg count | 22.404 / 1.0 | exact |
| local032 | top seller by distinct customers, profit (price − freight), distinct orders and 5-star count | 1,790 ✔ / 206,968.8 / 1,819 ✔ / 993 ✔ (distinct orders) | exact; seller concentration |
| local034 | avg count of each category's most-used payment type | 1,039.32 | exact; payment × category |
| local037 | top 3 categories by count of top payment type (distinct payment rows) | cama_mesa_banho 7,565 ✔, beleza_saude 6,898 ✔, esporte_lazer 5,923 | exact; category mix |
| local035 | max consecutive-city distance in geolocation sorted by state, city, zip, lat, lng (spherical cosine law) | santa cruz do sul → santa lucia do piai | exact; geolocation must be verbatim |
| local003 | RFM segments (NTILE 5 on delivered, by unique customer); avg sales per order | Champions 301.07 … Recent Users 46.86 | exact; distribution shape (NTILE is tie-sensitive) |
| local004 | top 3 AOV customers, lifespan in weeks | 13,664.08 / 7,274.88 / 6,929.31 ✔ | exact; price tail |
| local002 | linear regression on daily toy sales 2017-01-01..2018-08-29; 5-day SMA | sum 4,340.10 | trend check |
| local286 | seller report (>100 items): sales, avg price, avg review, packing time (h), top category | e.g. 4869f7a5… 1,156 items, 229,472.63, 4.13, 56.19 h | exact; seller delays |

For simulation, the exact values will not match, so turn them into shape checks:
- monthly delivered curve
- top-seller share
- top category × payment shares
- RFM segment ordering
- delivered-order AOV tail
- packing-time p50 for large sellers (≈56 h)

## 8. Open questions and risks

- **Licence.** Olist's Kaggle datasets (e-commerce and marketing funnel) are **CC BY-NC-SA 4.0**: non-commercial, share-alike, attribution required. Using them, or derived fitted parameters, in a commercial product needs legal review. Shipping derived event logs inherits share-alike. I did not check the Spider2 repo's own licence terms here.
- **Cancel, unavailable and stuck-status times are unknowable.** Any simulated timing for them is assumption-driven. The review creation date bounds only some of them.
- **Lines removed for unavailable orders** (603/609 have none). That is good for realism but it means E4 is post-decision. The alternative is to keep E4 at purchase plus a line-removed event and accept extra events.
- **Shared review_id across orders.** Model one survey per person per "batch" (254 of 789 are same-timestamp split checkouts). Otherwise the simulation needs a dedupe step.
- **Timezone.** I recommend treating wall clock as UTC; true-UTC export would shift `ts` by 2–3 h and needs fold handling for 39 ambiguous timestamps.
- **carrier < approved (1,359, clustered in 2018-04 and 2018-07)** looks like an operational backfill. Decide whether simulated data should reproduce it; a `lifecycle` law would flag it.
- **Thin 2016 tail and 2018-09/10 tail.** Fit on 2017-01..2018-08. For the exact round trip, keep everything.
- **Leads.** 462 of 842 won sellers have no seller row, because they never sold before the cut-off. Spider2 has no questions on leads, so validation for the funnel must come from our own checks.
- **Payment seq gaps (80 orders, seq 1 missing)** and payments ≠ items (369 orders) cannot be explained from the data. Carry them verbatim; in simulation, model them as rare noise or ignore them.
- **Customer address per order** (250 persons with several zips) means the simulation needs an "address changed" draw per order, not a fixed person address.
