# bank_sales_trading (Spider 2.0-lite): reverse-engineering the Data Bank ledger and the Clique Bait click log into event logs

Source: `data/spider2/bank_sales_trading.sqlite`, opened read-only (`sqlite3 -readonly`, `python3 -I` with `mode=ro`).
Scripts: [`scripts/`](scripts/) (`a_databank.py`, `a_databank2.py`, `a_order*.{sql,py}`, `a_tail.sql`, `b_cliquebait.py`, `b_visits.sql`, `b_more.sql`, `b_order.py`, `c_others.sql`).
All numbers below come from those scripts.

## 0. What this catalog is

It is a bundle of Danny Ma's "8 Week SQL Challenge" case studies plus one Kaggle dataset. Nothing links the groups.

| Tables | Origin | Evidence |
|---|---|---|
| customer_regions / customer_nodes / customer_transactions | 8WSQL **Case #4 Data Bank** | 5 regions (Australia, America, Africa, Asia, Europe), 5 nodes, deposit/purchase/withdrawal, 2020-01-01..2020-04-28 |
| shopping_cart_* | 8WSQL **Case #6 Clique Bait** | Pages Salmon…Oyster, campaigns "BOGOF - Fishing For Compliments", "Half Off - Treat Your Shellf(ish)" |
| weekly_sales, cleaned_weekly_sales | 8WSQL **Case #5 Data Mart** | Retail/Shopify, segments C3/F1, June-15 before/after questions |
| interest_map, interest_metrics | 8WSQL **Case #8 Fresh Segments** | composition, index_value, ranking, percentile_ranking |
| bitcoin_* | Danny Ma's crypto case (Serious SQL / Data With Danny) | members Danny, Vipul, Charlie…; member_id = first 6 hex of md5(n): `c4ca42`=md5("1") |
| veg_* | Kaggle "supermarket vegetable sales" (China, 2020-07..2023-06) | RMB prices, loss rates, `sale/return` |

The md5-prefix ids give the generators away: Clique Bait cookie `c4ca42` is user 1's first cookie, and bitcoin member `c4ca42` is Danny. Every table is synthetic or course data.

Row counts: customer_regions 5, customer_nodes 3 500, customer_transactions 5 868; shopping_cart_users 1 782, shopping_cart_events 32 734, page_hierarchy 13, event_identifier 5, campaign_identifier 3; bitcoin_members 14, bitcoin_transactions 22 918, bitcoin_prices 3 404; weekly_sales 17 117, cleaned_weekly_sales 17 117, interest_map 1 209, interest_metrics 14 273, veg_txn_df 878 503, veg_whsle_df 55 982, veg_cat 251, veg_loss_rate_df 251.

## 0.1 How Spider 2.0 uses it (query-level validation checks)

All 15 questions have `db == bank_sales_trading`, and none has an `external_knowledge` doc. Only local075 has gold SQL. Gold result CSVs exist for every question, often in several accepted variants (`_a`.. `_d`), so the reading of each question is ambiguous.

| id | Group | Analysis | Reproduced here? |
|---|---|---|---|
| local074 | A | Month-end balance per customer, with months that have no activity filled in (monthly change + cumulative) | 4 accepted variants; not re-run |
| local064 | A | Monthly net (deposits − withdrawals) per customer; the months with the most and fewest positive customers; difference of their averages | **Yes**: Jan has 424 positive and avg 557.704. Gold uses May with 0 (a month with no data), so the difference is 557.704 |
| local297 | A | Monthly net → cumulative closing balance; share of customers whose latest month grew by more than 5% | 2 variants (44.87% vs 53.00%) |
| local298 | A | Sum of max(0, balance as of the 1st of each month), first month excluded | **Yes, exact**: 235 595 / 261 508 / 260 971 |
| local299 | A | Daily running balance, 30-day rolling average, per-customer monthly max, summed; first month excluded | Not re-run (gold 286 194.267 / 314 140.852 / 170 303.921) |
| local300 | A | Daily balance carried forward, negatives → 0, monthly max per customer, summed | **Yes, exact**: 356 618 / 409 593 / 386 903 / 206 550 |
| local075 | B | Per product: views, cart adds, adds left in the cart without a purchase, purchases | View and cart counts match the gold (Salmon 1559/938 …). Purchased/abandoned not re-run (gold: 711/227 …) |
| local156, local157 | bitcoin | Yearly average BTC purchase price by region; daily % change in volume ("K"/"M"/"-" parsing) | — |
| local077, local078 | interest_* | Monthly max composition/index, 3-month rolling average; top/bottom 10 | — |
| local284, local285 | veg_* | Loss-rate stats; yearly wholesale/selling/loss/profit by category | — |
| local301, local302 | weekly_sales / cleaned_weekly_sales | Sales change in the 4 or 12 weeks before vs after 2020-06-15, by attribute | — |

Every Data Bank question is a **running-balance** query (by month-end, the 1st of the month, daily, or a rolling 30 days). The rebuilt or simulated ledger must therefore keep the per-customer, per-day multiset of signed amounts exactly. Order within a day does not matter to any of these questions, because they aggregate by day or coarser. local300 and local298 are exact-value regression checks for the round trip. For simulations they are shape checks, for example monthly totals within ±x%.

---

## A. Data Bank ledger

### A1. Inventory, keys, joins

| Table | Rows | Key (verified unique) | Role |
|---|---|---|---|
| customer_regions | 5 | region_id | static lookup |
| customer_nodes | 3 500 | (customer_id, start_date), no duplicates | slowly changing assignment (SCD-2) |
| customer_transactions | 5 868 | **no key.** No duplicate full rows. 396 (customer, day) pairs hold more than one transaction | activity |

- No foreign keys are declared. Coverage measured by query:
  - nodes.region_id → regions: 100%.
  - transactions.customer_id → nodes: 100% (0 orphans).
  - Every node customer has transactions (0 without).
- No nulls anywhere. All dates are ISO `YYYY-MM-DD` text, and the types are clean.
- Customers 1..500. Each has **exactly 7 node rows**, **exactly one open row** (`end_date = '9999-12-31'`, 500 rows) and **exactly one region** for life. Customers per region: 110/105/102/95/88.

### A2. Event catalog

| Event | Owner | Timestamp source | Attributes | Produces |
|---|---|---|---|---|
| `account_opened` | customer | `min(start_date)` = the customer's first transaction date (equal for **500/500**) | region_id, node_id | customer_nodes row #1 (start); implicitly the customer |
| `node_reassigned` | customer | `start_date` of node rows 2..7 | node_id (region fixed) | closes the previous row (`end_date = this.start − 1 day`), opens a new one |
| `deposit` | customer | txn_date (date only) | amount | customer_transactions row, txn_type='deposit' |
| `purchase` | customer | txn_date | amount | row, txn_type='purchase' |
| `withdrawal` | customer | txn_date | amount | row, txn_type='withdrawal' |

Derivation rules (prototype in `a_databank2.py`):

- Each customer_nodes row gives one event at `start_date`. The customer's earliest row becomes `account_opened` and later rows become `node_reassigned`. `end_date` is **not** stored in the event: it is derived as `next.start_date − 1 day`, or `'9999-12-31'` for the last row.
  - This is lossless. For all 3 000 consecutive pairs, `next.start − prev.end = 1 day` exactly, with no gaps and no overlaps (0 overlapping pairs).
- Each customer_transactions row gives one `txn_<type>` event at `txn_date`. Carry `src_rowid` if the physical row order must survive.
- Opening deposit: the first 500 rowids are one deposit per customer, each dated on that customer's first day. Every customer has a deposit on day 1 (0 exceptions).
  - Better to model this as `account_opened` followed by a `deposit` (the opening deposit) in the same instant.
- **Round trip measured:** derive events → replay → the rebuilt customer_nodes multiset equals the original (True), and the rebuilt transactions equal the original including rowid (True). Events: 500 account_opened + 3 000 node_reassigned + 2 671 deposit + 1 617 purchase + 1 580 withdrawal = **9 368**.

### A3. Rebuild rules and blockers to an exact round trip

1. **Date-only timestamps.** 396 customer-days have 2–4 transactions (histogram per customer-day: 1→5 061, 2→382, 3→13, 4→1).
   - Their intraday order is unknown, so any intraday running balance depends on a convention. Customers ever negative: 372 with deposit-first ordering vs 379 with deposit-last.
   - Fix: synthesize event times as `date + tiebreak`, with `src_rowid` as the tiebreak. Declare that only day-or-coarser balances are invariants. All Spider questions satisfy this.
2. **Physical row order is generator-shaped, not time-ordered.**
   - Rowids 1–500 are the opening deposits in a shuffled customer order.
   - Rowids 501–5 868 are grouped by customer in the same customer order, with dates unordered inside each group (2 892 date descents overall).
   - An exact table byte-match needs `src_rowid` in the event, or the comparison must be multiset-only. Recommend multiset plus a sort key.
   - customer_nodes is stored as 7 blocks of 500, each holding customers 1..500 in order, which is the allocation round. That order can be regenerated from (round, customer_id).
3. **`9999-12-31` sentinel.** It is a constant, so the rebuild emits it for the last assignment. In simkit `ts` is seconds since the run start, so the sentinel lives only in the export and the exporter must map "no next event" to it. Also, the node timeline runs **past the transaction horizon**:
   - The open rows start between 2020-02-03 and **2020-07-03**.
   - 214 node rows start after the last transaction date (2020-04-28).
   - For 351 customers, the last transaction is earlier than their open row's start.
   - So the simulation horizon must reach about 2020-07-03 for nodes, while transactions stop at 04-28. Equivalently, reallocations are pre-scheduled and independent of activity.
4. **Zero amount.** One deposit has `txn_amount = 0`. Allow `amount(min=0)`.
5. No derived-summary tables in this group. The monthly balances that the questions use are all derived on the fly.

### A4. Measured quirks

- **Negative balances are normal.** Purchases and withdrawals are not checked against the balance.
  - 372 of 500 customers go negative at some point (deposit-first convention).
  - The closing balance is negative for **56.8%** of customers. Percentiles p10 −3 108, p50 −291, p90 1 796; min −7 953, max 5 338.
  - So `running_nonneg` must **not** be a law here. This is an overdraft-allowed ledger, a bank with no holds.
- No overlapping node periods, no gaps, and no `start > end`. A reassignment to the **same node** happens in 607 / 3 000 = 20.2% ≈ 1/5, so the new node is drawn uniformly from all 5, including the current one.
- Every transaction lies inside a node interval (0 outside, 0 on two intervals).
- `node_id` 1..5 is reused across regions, so the real node key is (region_id, node_id).
- All customers open in January (first dates 2020-01-01..01-30, 30 distinct days, roughly uniform). April is truncated at 04-28, and only 309 customers are active in April.
- Amount range: deposits 0–1000, the others 1–999. Only deposits reach 1000 (3 rows).

### A5. Distributions to fit

- **Amounts.** Uniform integer U{1..1000} for every type, independent of type.
  - deposit mean 508.9, sd 288.2; purchase 498.8 / 290.5; withdrawal 501.9 / 285.3. Uniform(0,1000) gives sd 288.7.
  - Quantiles are linear: deposit p10/p50/p90 = 101/514/902.
  - The per-customer mean amount (n ≥ 10, 308 customers) has sd 75.5, close to 288/√n, so there is no customer-level amount heterogeneity.
- **Type mix.** The opening deposit is forced. After it: deposit 2 171 (40.4%), purchase 1 617 (30.1%), withdrawal 1 580 (29.4%). The per-customer deposit share has mean 0.484 and sd 0.163.
- **Activity.**
  - Transactions per customer: p10 4, p50 11, p90 20, max 22, min 2.
  - Per customer per month, including zeros: Feb mean 3.43, var 5.32, zero share 0.09. Mar mean 3.74, var 6.40, zero share 0.088. That is mildly over-dispersed against Poisson, so use a negative binomial or a gamma-mixed rate.
  - Rate per 30 days over each customer's own active span: p10/p50/p90 1.85/4.38/6.92.
  - Inter-arrival days: p50 5, p90 17, max 87, mean 7.31; 411 same-day gaps.
  - Active months: 1→3, 2→44, 3→183, 4→270 customers.
  - Last activity is spread out (p10 03-16, p50 04-04), which looks like customers quitting.
  - Weekday is flat (792–876 per weekday).
- **Monthly volume.** Jan 1 497 (500 customers), Feb 1 715 (455), Mar 1 869 (456), Apr 787 (309, truncated).
- **Node tenure** for closed periods (`end − start` days): roughly uniform 0..29, mean 14.63, p50 15, plus 16 rows at 30. That means duration ≈ U{1..30} days inclusive. There are 6 reassignments per customer.

### A6. simkit mapping sketch

- Entities:
  - `regions` (5, static via source).
  - `customers` (customer_id, region).
  - Optionally `nodes` (region, node) as 25 entities.
- Events: `account_opened`, `node_reassigned`, `deposit`, `purchase`, `withdrawal` (or one `txn_posted` with `txn_type=cat(...)`, which is closer to the table). `amount(min=0)`.
- Owner: `customer` (state: region, node, balance, alive), with `Latency(0.05, 0.3)`.
  - `life` process: `open` → emit `account_opened` + opening `deposit` → schedule `txn` every Exp(1/rate) with a per-customer gamma rate, plus a churn hazard.
  - `allocation` process, as a machine: a state `on_node` with `timer={"on_node": (dist.uniform("1d","30d"), "reassign")}` and `max_repeats=6`. The engine draws a node uniformly.
  - No holds are needed, since overdraft is allowed. If a "no-overdraft" overlay is wanted later, `std.holds` on purchase and withdrawal plus `running_nonneg` give the realistic variant.
- Source: 500 customers arriving U(Jan 1, Jan 30) at whole-day granularity. The exporter truncates times to dates.
- Laws: `lifecycle("customer_id", {None: {"account_opened"}, ...})`; `unique(node_reassigned, (customer_id, start))`; a custom law that node periods tile (end+1 = next start); a custom law that the first transaction day = the open day.
- Expectations: `stat.share` of the type mix; `quantiles(txn, per=customer)`; `mean(amount)` ≈ 500.
- Events per run at the native size: about 9.4k (3.5k node + 5.9k transactions). Trivial.

### A7. Open questions and risks

- This is classroom synthetic data: uniform amounts, uniform tenures, a uniform node draw, no seasonality, no amount–type dependence, unconstrained overdraft. It is not useful for fitting realistic banking behaviour.
- It is good for:
  1. A **round-trip harness test**. Derive → replay → exact multiset equality is already shown by the prototype. It covers SCD-2 interval reconstruction, the sentinel end date, date-only collapse and rowid preservation.
  2. **Query-level regression**: local298 and local300 reproduce the gold exactly from the raw tables, so they can run on the rebuilt tables.
  3. A sanity target for a balance overlay.
- Open: should intraday order be a seeded random tiebreak or `src_rowid`? Should churn be modelled explicitly, or fall out of the horizon?

---

## B. Clique Bait click log

### B1. Inventory, keys, joins

| Table | Rows | Key | Role |
|---|---|---|---|
| shopping_cart_users | 1 782 | **cookie_id** (unique; one user per cookie). user_id is *not* unique: 1..500, with 1–6 cookies each | really a **cookie** dimension: (cookie_id, user_id, start_date) |
| shopping_cart_events | 32 734 | (visit_id, sequence_number), unique, no duplicates | activity, already an event log |
| shopping_cart_page_hierarchy | 13 | page_id | static: 9 product pages (3..11 ↔ product_id 1..9, stored as REAL), plus Home, All Products, Checkout, Confirmation (product fields null) |
| shopping_cart_event_identifier | 5 | event_type | static: 1 Page View, 2 Add to Cart, 3 Purchase, 4 Ad Impression, 5 Ad Click |
| shopping_cart_campaign_identifier | 3 | campaign_id | static: `products` is a **product_id range text** ("1-3", "4-5", "6-8"), not page_id. Windows 01-01..01-14, 01-15..01-28, 02-01..03-31 |

- Coverage:
  - events.cookie_id → users: 100%.
  - Every user cookie has events.
  - page_id and event_type: 100%.
  - One cookie per visit (0 visits with more).
- event_time is microsecond text, 2020-01-01 07:44:56 .. 2020-05-28 20:17:15.
- Campaigns join only by date range (`event_time` between start and end) and by product range. There is no campaign_id in the events.

Hierarchy: **user (500) → cookie (1 782) → visit (3 564) → event (32 734)**.
- Every cookie has **exactly 2 visits**, both on the cookie's `start_date`. The first visit date equals start_date for 1 782/1 782 cookies, and the two visits are 15 s to 23.6 h apart.
- One visit enters at Home (page 1) and the other at All Products (page 2). Which comes first: home-first 897, products-first 885.
- A user's cookies span 0–98 days (mean 36.1). For 453/500 users, all their cookies fall on distinct dates.

### B2. Event catalog (the table already is the log)

| Event | Owner | Time | Attributes | Row produced |
|---|---|---|---|---|
| `cookie_issued` (implicit) | user | date of the cookie's first event | cookie_id, user_id | shopping_cart_users row (start_date = date of the first event) |
| `visit_started` (implicit) | cookie | time of the first event | visit_id, entry page | none (the visit is the group key) |
| `page_viewed` (type 1) | visit | event_time | page_id | events row |
| `cart_added` (2) | visit | event_time | page_id (product) | events row |
| `purchased` (3) | visit | event_time | page_id = 13 always | events row |
| `ad_impression` (4) | visit | event_time | page_id = 2 always, seq = 2 always | events row |
| `ad_clicked` (5) | visit | event_time | page_id = 2 | events row |

What has to change to make it a proper log:

- `sequence_number` = rank of event_time within the visit. Verified: contiguous 1..n in every visit, 0 gaps, and 0 time inversions or ties within a visit. So it can be **derived** and need not be stored.
- shopping_cart_users is **derived**: one row per cookie, start_date = `date(min(event_time))`. The only fact it adds is the cookie → user mapping, so emit a `cookie_issued(user_id, cookie_id)` event or carry user_id on the visit.
- **Purchase has no product payload.** The purchased items are implicitly "every cart_added in a visit that has a purchase". There is no remove-from-cart event. local075's gold SQL uses exactly this rule (`EXISTS event_type=3 in the same visit`).
  - A simulated log must keep that semantics: purchase = checkout of the whole cart.
  - Optionally add `cart_line_purchased` rows at export. They must not leak into the events table.
- Campaign attribution is a **post-hoc join** (date window × product range). It is not an event, and the impression/click rows carry no campaign id.

### B3. Rebuild rules and blockers to an exact round trip

- Rebuild events: one row per event: `(visit_id, cookie_id, page_id, event_type, rank-in-visit, event_time)`.
  - Rebuild users: `group by cookie_id → (user_id, date(min(event_time)))`.
  - Dimension tables are static seeds.
- Blockers:
  1. **Timestamp text format.** Trailing zeros of the microseconds are stripped. Lengths: 26 chars (29 421 rows), 25 (2 972), 24 (306), 23 (28), 22 (5), 21 (2), e.g. `2020-02-09 11:42:42.9`. simkit exports UTC µs, so the exporter must re-format with "strip trailing zeros" to byte-match. The values themselves round-trip at µs.
  2. **Physical order.** Rows are contiguous per visit and ascend by sequence. Visits are *not* in time order (1 774 time descents across rows) and not grouped by cookie (3 564 cookie runs). The users table is not sorted by user_id, nor in event order. Exact order needs `src_rowid`, otherwise compare as multisets.
  3. **Opaque ids.** cookie_id/visit_id are 6-hex md5 prefixes (`c4ca42` = md5("1")[:6] is user 1's first cookie). A generator can mimic them, but the round trip must carry them as strings.
  4. `product_id` is REAL (1.0) and `products` is free text: cosmetic, but the rebuild must keep those types.

### B4. Measured quirks (strong generator fingerprints)

- **Monotone browsing.** Product page views always move to a strictly higher page_id. The transition matrix is upper-triangular, with 0 backward moves.
  - Visits walk Home → All Products → a subset of products in ascending order → Checkout → Confirmation.
  - No product page is viewed twice in a visit, and every cart add immediately follows the view of the same page (8 451/8 451).
- **Bounce visits.** 906 visits of a single event (All Products view, entered at page 2), plus 2 Home-only visits.
- Ad impressions appear **only** in products-entry visits, always at seq 2 right after the All Products view.
  - All 876 non-bounce products-entry visits have an impression. Clicks: 702, i.e. click | impression = 80.1%.
  - 0 clicks without an impression.
- Purchase is always the last event, at page 13, and always preceded by a Checkout view. 0 purchases without checkout, 0 checkouts without a cart, 326 checkouts abandoned.
- **Campaign windows have no effect.**
  - Purchase rate is 0.483 (campaign 1), 0.500 (2), 0.496 (3), 0.524 (no window).
  - Impression rate is 0.24–0.26 everywhere, including outside the windows: 103 impression visits fall outside any window.
  - 418 of 3 564 visits start outside any window (01-29..01-31, and from April on).
  - There is no campaign-specific product uplift to fit, so treat the campaigns as labels only.
- Event gaps are about U(0, 60) s for every transition type (p10 ≈ 6 s, p50 ≈ 30 s, p90 ≈ 54 s). Visit start hour is flat over 24 h (126–169 per hour).
- Cookie start dates by month: Jan 438, Feb 744, Mar 458, Apr 124, May 18.

### B5. Distributions to fit

- Visit shape by entry and ad exposure:

| Entry | Ads | Visits | Purchase conversion | Cart adds / visit | Product views / visit |
|---|---|---|---|---|---|
| Home, more than 1 event | — | 1 780 | 0.584 | 2.27 | 4.53 |
| All Products, bounce | — | 906 | 0 | 0 | 0 |
| All Products | impression, no click | 174 | 0.649 | 2.31 | 4.62 |
| All Products | impression + click | 702 | 0.889 | 5.72 | 7.13 |

- Overall: 1 777 / 3 564 = 49.9% of visits purchase. Cart → purchase at visit level = 0.708. Checkout → purchase = 1 777/2 103 = 0.845.
- Page-view transitions (counts; rows = from):
  - START → 1: 1 782, START → 2: 1 782.
  - 1 → 2: 1 392; 1 → 3..11 (skipping All Products) 388 in total; 1 → END 2.
  - 2 → END 909 (bounces + 3); 2 → 3: 1 362; 2 → 4: 491; 2 → 5: 201 …
  - From product page k, the next page is k+1 with probability ≈ 0.6 (e.g. 3 → 4: 966/1 559, 6 → 7: 902/1 563), with geometric-like skips beyond that. 11 → 12: 1 312, 11 → END 256. 10 → 12: 473. 12 → END: 2 103 (the Confirmation view is a type 3 row, not a page view).
  - Full matrix in `b_out.txt`. Exit probability rises with page_id: 9 → END 62/1 547, 10 → 142/1 564.
- Per-product page views are about 1 470–1 568 each (Black Truffle lowest at 1 469). P(add | view) ≈ 0.60–0.63 per product, e.g. Salmon 938/1 559, Lobster 968/1 547. Products are close to exchangeable.
- Events per visit: p50 10, p90 18, max 23, mean 9.18. Visit duration: p50 252 s, p90 508 s, max 768 s.
- Cart size per carting visit: p50 3, p90 6, max 9.
- Cookies per user: 1→18, 2→77, 3→138, 4→166, 5→74, 6→27 (mean 3.564). Visits per cookie = 2 always. Purchases per cookie: 0→430, 1→927, 2→425.

### B6. simkit mapping sketch

- Entities: `users` (500), `cookies` (cookie_id, user_id), `pages` (13, static with category/product), `campaigns` (3, static).
  - Event tables:
    - `page_viewed(visit_id, cookie_id, user_id, page_id)`
    - `cart_added(..., page_id)`
    - `purchased(..., visit_id)`
    - `ad_impression(..., page_id)`
    - `ad_clicked(..., page_id)`
  - The exporter unions them into shopping_cart_events, mapping type → event_type int and `seq`-within-visit → sequence_number, and derives shopping_cart_users.
- Owner `user`: `cookie_cycle`. Every Exp(mean about 20–30 d) it issues a new cookie, `cookies_per_user` times (fit to the histogram above).
- Owner `visit`, created by the user via `ctx.create`, a state machine:
  - `entry`: branch home 0.5 / products 0.5.
  - products → `bounce` (906/1 782 ≈ 0.508, retire) | `impression` → branch click 0.801 / no-click.
  - Then `browse`: a loop over ascending product pages with a per-step "next = k+1 w.p. 0.6, skip w.p. …, exit-to-checkout/END" kernel, and add-to-cart w.p. about 0.6 per view.
    - Click visits use a higher view/add kernel (5.7 adds vs 2.3).
  - Then `checkout` (reached w.p. fit by cart>0) → `purchased` w.p. 0.845 → retire.
  - Inter-event delay: `dist.uniform("0s","60s")`. Each cookie spawns its 2 visits the same day; the second follows Exp, clipped to the end of the day.
- No shards are needed. There is no inventory or budget, and nothing is shared between visits. Campaigns could become an exogenous source with a `cfg.campaign_uplift` defaulting to 0, which matches the data.
- Laws:
  - `lifecycle("visit_id", {None: {"page_viewed"}, "cart_added": {...}, "purchased": set()})`
  - `consecutive(events, "visit_id", "seq")`
  - `not_while_open`-style custom law: no `cart_added` without a prior view of the same page in the visit
  - purchase ⇒ checkout viewed
  - impression only at seq 2 on page 2
- Events per run at native size: about 32.7k click events + 3.6k visits + 1.8k cookies, about 38k in total.

### B7. Open questions and risks

- The generator is extremely regular: ascending page walk, U(0,60) s gaps, exactly 2 visits per cookie, deterministic ad placement, and no campaign effect. A simkit pack that reproduces these numbers proves pipeline correctness, **not** realism.
- The impression → conversion lift (0.389 overall without ads vs 0.889 with a click) is mostly *selection by construction*: clicked visits view more products. Report it as an association.
- It is still useful for:
  - funnel and `stat.funnel` expectation tests
  - a **round-trip harness** for a log whose sequence and user tables are derivable (sequence = rank, users = per-cookie aggregate)
  - the local075 product-funnel query as a validation check
  - exercising "purchase = whole cart" semantics
- Open:
  - Should simkit emit one event table with an int `event_type`, to match the source, or five typed tables plus an exporter view?
  - Should the 2-visits-per-cookie and same-day constraints be kept as laws, or relaxed for realism?

---

## C. bitcoin_* as a crypto-trading candidate (brief)

- What it holds:
  - bitcoin_members: 14 members, 6-hex md5 ids, region.
  - bitcoin_transactions: 22 918 rows, txn_id 1..22 918, unique. BUY/SELL × BTC/ETH; quantity; `percentage_fee` (0.3 on 16 166 rows); `txn_date` DD-MM-YYYY plus `txn_time` ISO, always on the same date (0 mismatches). 2017-01-01 .. 2020-12-31.
  - bitcoin_prices: daily OHLC for BTC and ETH, 1 702 days each, 2017-01-01..2021-08-29. `volume` is text with K/M suffixes and one '-'. `change` is text "%".
- Properties:
  - Every transaction has a same-day price row (0 missing).
  - Holdings never go negative per member and ticker (0 rows).
  - Heavily buy-sided: BUY 10 440 / SELL 2 044 for BTC.
  - 28 rows at 00:00:00.000, 50-unit initial buys on 2017-01-01.
- Assessment: a small but usable **owner + exogenous price timeline** case.
  - Members are owners holding positions.
  - Prices become a `src.share`d exogenous series.
  - Fee = percentage. A `running_nonneg` law on holdings fits and holds.
  - There is no order book and no counterparty, so it is a weaker match for `crypto_exchange`'s matching shard than a retail-trading pack.
  - The questions (local156/157) test price-weighted averages and string parsing of volume.

## D. Remaining tables: are they event-shaped?

- **weekly_sales**: No. A weekly aggregate (transactions, sales) by region × platform × segment × customer_type. `week_date` is text `d/m/yy`, 72 weeks.
- **cleaned_weekly_sales**: No. A derived copy of weekly_sales: all 17 117 rows match on (week, region, platform, segment, customer_type, transactions, sales), plus parsed date, week number, age_band, demographic and avg_transaction.
- **interest_map**: No. A static dimension (1 209 interests, created_at/last_modified).
- **interest_metrics**: No. A monthly aggregate snapshot per interest (14 273 rows, 1 202 interests; 1 194 rows have null `_month`). `month_year` is `MM-YYYY` text, so it sorts wrongly as a string.
- **veg_txn_df**: **Yes.** Item-level POS sales and returns (878 503 rows, 2020-07-01..2023-06-30, date + time, qty, unit price, discount flag, 461 returns, 246 items). This is the largest real event table in the catalog. It is a candidate retail pack, but it was not analysed here.
- **veg_whsle_df**: Partly. A daily wholesale price per item (55 982), an exogenous price series.
- **veg_cat, veg_loss_rate_df**: No. Static item dimensions (251 each).
