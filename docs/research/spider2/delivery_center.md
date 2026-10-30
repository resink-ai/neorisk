# delivery_center: reverse-engineering the event log

The source is Spider 2.0-lite `delivery_center.sqlite`, which is Kaggle "Delivery Center: Food & Goods orders in Brazil" (`nosbielcs/brazilian-delivery-center`, v2, 2021-07-12).
Every number in this report comes from a script in [`scripts/`](scripts/) (named in brackets, e.g. [01]):

- `q.py` runs a `.sql` file against an in-memory copy of the read-only DB, with indexes.
- `common.py` parses the timestamps.
- Run the Python scripts with `python3 -E -P script.py <scripts_dir> <work_dir>`.

Script index:

| # | File | What it measures |
|---|------|------------------|
| 01 | `01_inventory.sql` | Keys and join coverage |
| 02 | `02_status.sql` | Statuses, null patterns, categories |
| 03 | `03_moments.py` | Timestamp format, created_\* redundancy, out-of-order moments, metric formula search |
| 04/05 | `04_metric_resid.py`, `05_metric_exact.py` | Metric residuals and exactness |
| 06/07/08 | `06_subsecond.py`, `07_resid_hist.py`, `08_offsets.py` | Whether hidden sub-second times explain the metrics |
| 09 | `09_children.sql` | Payment and delivery multiplicity and consistency |
| 10 | `10_dists.py` | Delays, volume, id monotonicity |
| 11 | `11_id_timing.py` | Which moment orders the child ids |
| 12 | `12_conc.sql` | Concentration, fees, distance |
| 13 | `13_more.py` | Quantiles, fee rates, driver load, benchmark replicas |
| 14 | `14_misc.sql` | Delivered-moment presence, driver hubs, batching |
| 15 | `15_precision.sql` | Decimal precision, id ranges |

## 1. Table inventory and joins

| Table | Rows | Key | Kind |
|---|---:|---|---|
| hubs | 32 | hub_id (2..91) | Static dimension (4 states: SP 15, RJ 9, PR 4, RS 4) |
| stores | 951 | store_id (3..4679) | Static dimension. Has `hub_id`; segments FOOD/GOOD; 16 stores have null lat/long; 887 names have trailing spaces |
| channels | 40 | channel_id (1..49) | Static dimension (26 MARKETPLACE, 14 OWN CHANNEL) |
| drivers | 4,824 | driver_id (133..66494) | Static dimension (MOTOBOY/BIKER × FREELANCE/LOGISTIC OPERATOR) |
| orders | 368,999 | order_id (68,405,119..93,139,817) | Activity, with 8 lifecycle moments and 7 metrics |
| payments | 400,834 | payment_id (4,427,917..5,540,806) | Activity; no timestamp |
| deliveries | 378,843 | delivery_id (2,174,658..3,144,739) | Activity; no timestamp |

There are no declared foreign keys. The inferred joins, verified in [01]:

- **orders.payment_order_id = orders.delivery_order_id = orders.order_id** in all 368,999 rows. The two extra columns are pure redundancy.
- **payments → orders:** all 400,834 payment rows match an order (100%). 350,334 orders (94.94%) have at least one payment.
- **deliveries → orders:** all 378,843 delivery rows match an order (100%). 358,654 orders (97.20%) have at least one delivery.
- **stores → hubs:** 951/951 match (100%), across all 32 hubs. Every store and every hub has orders.
- **orders → stores, orders → channels:** 100% match. 39 of the 40 channels are used.
- **deliveries → drivers:**
  - 15,886 deliveries (4.19%) have a null `driver_id`.
  - No driver_id is dangling.
  - 4,583 drivers appear in deliveries; 241 drivers never deliver.
- **Drivers are not tied to a hub in the schema.** Behaviourally they are: 3,729 of 4,583 drivers serve only one hub, and 91.3% of driver deliveries happen in that driver's main hub [14].
- The global order_id sequence (68M–93M over 4 months) is sparse: the dataset is a sample. This matches the Kaggle note that the data "does not have the completeness of the whole operation" and is "fictitious/anonymised".

## 2. Event catalog

All timestamps are text `M/D/YYYY h:mm:ss AM|PM`, with whole seconds.

- **Time zone: UTC.** The volume peaks at 14–16h and 22–00h, which is Brazilian lunch and dinner at UTC−3 [10]. Brazil had no DST in 2021.
- **Span:** order_moment_created runs from 2021-01-01 00:01:36 to 2021-04-30 23:59:48 (120 days) [03].

One owning entity per event: the order (`order_id`). Payments and deliveries are children of the order.

| Event | Time source | Attributes | Produces |
|---|---|---|---|
| `order_created` | `order_moment_created` (never null) | order_id, store_id, channel_id, order_amount, order_delivery_fee | orders row skeleton; order_created_{hour,minute,day,month,year} |
| `order_accepted` | `order_moment_accepted` | order_id | orders.order_moment_accepted |
| `order_ready` | `order_moment_ready` | order_id | orders.order_moment_ready |
| `order_collected` | `order_moment_collected` | order_id | orders.order_moment_collected |
| `order_in_expedition` | `order_moment_in_expedition` | order_id | orders.order_moment_in_expedition |
| `order_delivering` | `order_moment_delivering` | order_id | orders.order_moment_delivering |
| `order_delivered` | `order_moment_delivered` (only 5.4% present) | order_id | orders.order_moment_delivered |
| `order_finished` | `order_moment_finished` | order_id, order_delivery_cost, metric values (see §3) | orders.order_moment_finished, order_status=FINISHED, order_delivery_cost |
| `order_canceled` | No source column. Use the last non-null moment, else `created`, plus a tie-break of 0 s | order_id, order_delivery_cost | order_status=CANCELED |
| `payment_recorded` | Tied to `order_moment_created` (+k µs per payment, in payment_id order) | payment_id, order_id, payment_amount, payment_fee, payment_method, payment_status | one payments row |
| `delivery_assigned` | Tied to `order_moment_delivering`. Fallback chain when that is null: in_expedition → collected → ready → accepted → created. Add +k µs in delivery_id order | delivery_id, order_id, driver_id (nullable), delivery_distance_meters | deliveries row (status is set later) |
| `delivery_closed` | Tied to finished, else to the cancel time | delivery_id, delivery_status ∈ {DELIVERED, CANCELLED, DELIVERING} | deliveries.delivery_status. Omit this event when the status is DELIVERING (a still-open delivery) |

Why the children's times are tied this way [11]:

- **Payments follow order creation.** When payment_ids are sorted, the creation time of their order is non-decreasing for 89.3% of consecutive pairs; every other moment scores ≤64.6%.
- **Deliveries follow dispatch.** When delivery_ids are sorted, `order_moment_delivering` is non-decreasing for 93.1% of consecutive pairs; every other moment scores ≤58.7%.

These tied times are a modelling choice: the real times are lost. For an exact rebuild, the ids themselves must be event attributes, since they are not reproducible from times. The order-level `order_delivery_cost` probably reflects the courier cost; it is null on 7,205 orders [09].

**Derivation rule (table → events).**

- For each order: emit `order_created`, then one event per non-null moment, in **column order rather than time order**. 1.24% of orders have out-of-order moments (§4), so sorting by time would lose which column a time came from. The event carries the stage name, so the column is preserved.
- For a CANCELED order: emit `order_canceled` at max(non-null moment).
- For each payment: emit `payment_recorded`.
- For each delivery: emit `delivery_assigned`, then `delivery_closed`.

## 3. Rebuild rules (events + dimension snapshots → tables)

**Dimensions.** hubs, stores, channels and drivers are initial snapshots inserted as-is. They have no time attribute and are never mutated. Keep the original ids, and keep trailing spaces in store_name. Store coordinates either equal their hub's (291 of 935) or lie within 0.01° of it (917 of 935) [12].

**orders.**

- One row per `order_created`.
- `payment_order_id = delivery_order_id = order_id`.
- `order_status` is CANCELED if an `order_canceled` event exists, else FINISHED.
- Each moment = `fmt(time of that stage's event)` or NULL. `fmt` (in common.py) round-trips 100% of the moment strings (0 mismatches over all non-null moments) [03].
- `order_created_{hour,minute,day,month,year}` are derived from the created moment. This matches in every row except 3:
  - 71557811
  - 73891911
  - 87132912

  All three sit exactly on the hour (e.g. moment 11:00:00 PM, created_hour=22, minute=0). This suggests the original timestamp had sub-second precision and was rounded up in the text but truncated for the parts. These 3 rows need an override attribute, e.g. `created_parts` on `order_created`. [05]

**order_metric_\*: formulas.** Times are in minutes, and END = coalesce(delivered, finished) [03][04].

| Metric | Formula | Rows where the value matches `round(diff,2)` exactly [05] |
|---|---|---:|
| collected_time | ready → collected | 75.2% |
| paused_time | in_expedition → delivering | 75.2% |
| production_time | created → ready | 75.0% |
| walking_time | ready → in_expedition | 75.1% |
| expediton_speed_time (sic) | ready → delivering | 75.4% |
| transit_time | delivering → END | 75.3% |
| cycle_time | created → END | 75.2% |

**The metrics are NOT exactly derivable.**

- The residual `metric·60 − Δs` always lies in {0, ±0.2 s} (the rounding grid) or {±0.8, ±1.0, ±1.2 s}. There is never more than 1.2 s of disagreement [07].
- A single per-order set of hidden times cannot explain the values:

  | Hidden-time model (sample [06][08]) | Orders explained |
  |---|---:|
  | Text moments as they are | 27.7% |
  | Integer offsets {0,1} or {−1,0,1} | 58% |
  | Continuous sub-second times within ±0.5 s | 83.6% |

- The metrics were computed upstream from a different (higher-precision or independently rounded) clock.
- **Nullness rule:** a metric is null exactly when one of its endpoints is null, with these exceptions:
  - production_time: 1 extra null.
  - transit_time: 183 extra nulls (181 of them with a negative diff, all with delivered null).
  - cycle_time: 365 extra nulls (153 with Δ=0, 144 with Δ<0, 68 with Δ>0). Yet 211 negative transit values *are* populated [04][06].
- **Rule for an exact round trip:** carry all 7 metric values (nullable) as attributes of `order_finished` / `order_canceled`. For simkit generation, compute them as `round(Δ/60, 2)`; this is statistically indistinguishable.

**payments.** One row per `payment_recorded`, with every column copied from the event. All amounts and fees are whole cents [15]. 329 (order, amount, method) groups repeat within an order, so the rows are not deduplicable on content [09].

**deliveries.** One row per `delivery_assigned`, with delivery_status taken from `delivery_closed` (DELIVERING when no close event). Within an order, `delivery_distance_meters` is identical across its deliveries in 18,722 of 18,724 multi-delivery orders [09]. Distance is therefore an order-level quantity copied onto each delivery.

**What blocks an exact round trip:**

1. The metrics are not a function of the moments (above): they must be carried.
2. The created_\* parts disagree on 3 rows: they must be carried.
3. There is no cancel timestamp, and no payment or delivery timestamps. They are synthesised by the tie rules above (lossless as long as the ids and attributes ride on the events).
4. The ids are sparse and not time-ordered:
   - order_id is increasing with created time for 99.0% of consecutive pairs.
   - payment_id and delivery_id only approximately follow time.

   So ids must be event attributes, not engine-assigned (or the ids are remapped and the checks compare up to the id bijection).
5. Out-of-order moments: the event-time ordering ≠ column ordering.
6. Mixed SQLite storage classes: the same DECIMAL column holds `integer` 0 or 62 and `real` 62.7 [02]. Writing Python floats normalises these through DECIMAL affinity. Compare by value, not by `typeof`.
7. The text timestamp format is non-ISO and 12-hour; `fmt` is required, and so is the UTC assumption.

## 4. Data quirks, measured

**Order status [02]:**

- FINISHED: 352,020
- CANCELED: 16,979 (4.60%)

**Non-null moments by status [02]:**

| Status | n | created | accepted | ready | collected | in_exp | delivering | delivered | finished |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| CANCELED | 16,979 | 16,979 | 8,886 | 2,916 | 1,849 | 1,671 | 1,317 | 598 | 1,383 |
| FINISHED | 352,020 | 352,020 | 350,652 | 340,977 | 324,256 | 299,899 | 342,366 | 19,003 | 352,017 |

**Moment presence patterns [02]:**

- **Patterns are not prefix-shaped.** Moments are skipped in the middle. The flags below follow the order accepted, ready, collected, in_exp, delivering, delivered, finished:

  | Pattern | Count | Share of FINISHED |
  |---|---:|---:|
  | `1111101` (no delivered) | 273,735 | 77.8% |
  | `1110101` | 22,107 | |
  | `1100101` | 18,489 | |
  | `1111111` | 15,419 | |
  | `0000001` | 817 | |

  A generator must model the presence of each stage independently.
- **CANCELED:**
  - 7,952 have only `created`; 5,711 have created+accepted.
  - 1,383 CANCELED orders nevertheless have a finished moment, and 125 have all 8 moments.
- **Delivered moment:** the moment is mostly absent (5.4% of FINISHED). Its presence varies by channel, from 0.5% (channel 21) to 18% (channel 46) [14].
- 3 FINISHED orders have a null finished moment [14].

**Out-of-order moments [03]:**

- 4,572 orders (1.24%) have a later stage before an earlier one.
- The largest cases:
  - accepted > ready: 2,963 (0.86%)
  - collected > in_expedition: 881 (0.29%)
  - delivered > finished: 113 (0.59% of the 19,256 with both)
  - created > finished: 144
- Negative metric values follow from these: paused 176, transit 206, collected 30.

**Payments [09]:**

| Payments per order | Orders |
|---:|---:|
| 0 | 18,665 (16,971 CANCELED, 1,694 FINISHED) |
| 1 | 301,516 |
| 2 | 47,247 |
| 3 | 1,482 |
| 4+ | 89 (max 9) |

- **Split payments** are mostly a voucher plus a card:
  - ONLINE+VOUCHER: 41,157
  - DEBIT+VOUCHER: 2,113
  - ONLINE+VOUCHER+VOUCHER: 944
- **Sum of payments vs. order:** the sum equals order_amount + order_delivery_fee for 340,016 of 350,326 FINISHED orders with payments (97.1%). It equals order_amount alone for 35%, because the fee is 0 for 36% of orders.
- **payment_status:**
  - PAID: 400,334
  - CHARGEBACK: 438 (401 of them VOUCHER)
  - AWAITING: 15
- Only 8 CANCELED orders have any payment.
- 125 payments have amount 0 [15].

**Deliveries [09]:**

| Deliveries per order | Orders |
|---:|---:|
| 0 | 10,345 (7,668 CANCELED, 2,677 FINISHED) |
| 1 | 339,930 |
| 2 | 17,448 |
| 3 | 1,132 |
| 4+ | 144 (max 8) |

- **Multi-delivery orders:** mostly all DELIVERED (17,232 are DELIVERED+DELIVERED). Of the 18,724 multi-delivery orders, 9,549 use a single driver and 8,716 use different drivers. These are re-dispatches or split loads, and they share the same distance.
- **delivery_status:**
  - DELIVERED: 371,367
  - CANCELLED: 7,253 (all have a null driver)
  - DELIVERING: 223
- 8,601 DELIVERED rows have no driver.
- **Status contradictions:**
  - CANCELED orders: 2,501 DELIVERED and 55 DELIVERING delivery rows.
  - FINISHED orders: 144 CANCELLED delivery rows.

**Delivery cost and distance:**

- `order_delivery_cost` is null for 7,205 orders. 3,783 of them nevertheless have a delivery [09].
- Distance [12][13]:
  - 73 null and 11 zero.
  - Maximum 7,251,291 m, a clear outlier. CANCELLED deliveries average 59 km, against 9.8 km for DELIVERED.

**Driver load [13]:**

- Two LOGISTIC OPERATOR "drivers", 25651 and 26223, carry 10,912 and 8,576 deliveries: 5.4% of all driver deliveries.
- The busiest driver-day reaches 608 deliveries. These are pooled or fleet accounts, not people.
- Batching: 9,247 (driver, delivering-second) pairs carry more than one order [14].

## 5. Distributions to fit (numbers from [10][12][13])

**Stage delays, minutes, FINISHED orders, both endpoints non-null:**

| Stage | p5 | p25 | p50 | p75 | p90 | p95 | p99 | mean |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| created→accepted | 0.1 | 0.3 | 0.6 | 0.9 | 2.1 | 6.6 | 1081.9 | 42.5 |
| accepted→ready | 0.1 | 7.3 | 13.7 | 20.4 | 28.3 | 34.9 | 80.9 | 20.1 |
| ready→collected | 0.2 | 0.8 | 1.7 | 3.0 | 5.1 | 7.0 | 14.4 | 2.8 |
| collected→in_exp | 0.0 | 0.1 | 1.5 | 2.9 | 4.4 | 5.5 | 9.8 | 2.1 |
| in_exp→delivering | 0.3 | 1.2 | 2.5 | 5.4 | 11.3 | 19.8 | 102.8 | 9.2 |
| delivering→finished | 6.9 | 11.9 | 17.1 | 26.3 | 46.0 | 90.5 | 1382.1 | 66.3 |
| delivering→delivered | 8.7 | 15.1 | 21.6 | 32.8 | 49.2 | 66.7 | 2888.6 | 251.2 |
| delivered→finished | 5.6 | 23.1 | 53.5 | 149.8 | 1351.6 | 1433.7 | 3118.6 | 396.4 |
| created→finished | 22.7 | 33.3 | 43.0 | 58.1 | 104.9 | 363.2 | 2905.0 | 177.3 |

All of these are heavy-tailed: a lognormal body plus a ~1–5% "stuck until next day" tail of about 1,440 minutes (the end-of-day closing of stuck orders). Model each as a two-component mixture.

**Cancellation:** 53% of CANCELED orders have at least one moment after created. The last moment after created comes at p50 1.1 min and p90 137 min. Cancel rate by segment: GOOD 12.7%, FOOD 3.4%. By month: 4.3%, 4.5%, 4.5%, 5.0%.

**Volume:**

| Month | Orders | FINISHED |
|---|---:|---:|
| Jan | 75,027 | 71,773 |
| Feb | 72,915 | 69,653 |
| Mar | 112,223 | 107,232 |
| Apr | 108,834 | 103,362 |

- Orders per day: min 1,131 (Jan 1), median 2,941.5, max 5,599.
- By weekday: Mon–Thu 11.9–13.4%, Fri–Sun 16.3–16.6%.
- By UTC hour (bimodal): 14h 9.3%, 15h 13.7%, 16h 9.8% … 21h 7.9%, 22h 13.3%, 23h 12.4%, 0h 7.3%. Hours 03–12 are ≤0.3% each.

**Concentration:**

- **Stores** (951, all active): top1 3.8% (store 53, 14,004 orders), top10 23.5%, top50 59.2%, top 10% of stores 76.8%. 300 stores have fewer than 10 orders; 97 have exactly 1.
- **Hubs** (32): top hub 8 (GOLDEN SHOPPING, RJ) has 12.2%, then 6.3%, 6.2%, 5.8%, and so on. Stores per hub: 1–68, mean 29.7.
- **Channels:** channel 5 (FOOD PLACE, MARKETPLACE) has 78.2%. MARKETPLACE overall is 90.3% (333,165 orders).
- **Stores per channel:** 371 stores use one channel; up to 10.
- **Segment:** FOOD 321,775 orders (mean amount 84.0) vs GOOD 47,224 orders (mean amount 249.3).

**Amounts and fees:**

- **order_amount (FINISHED):** p5 23.90, p25 39.90, p50 71.90, p75 122.35, p95 245.50, p99 463.86, mean 100.26. 764 orders have amount 0.
- **order_delivery_fee:** a menu of prices. Most common: 0 (132,304), 11.9 (110,517), 9.9, 6.9, 4.9, 5.9 …
- **order_delivery_cost:** p50 7.19. Mostly integers (5, 6, 0, 8, 7). Null for 7,205.
- **payment_amount:** p50 65.88, mean 93.09.
- **payment_fee ≈ rate × amount.** The fee/amount mode is 1.5% (ONLINE also 2.7% and 2.0%; STORE_DIRECT 2.0%). Fee is 0 for VOUCHER and MEAL_BENEFIT.

**Payment method mix (rows):**

| Method | Rows | Share |
|---|---:|---:|
| ONLINE | 312,377 | 77.9% |
| VOUCHER | 48,570 | 12.1% |
| DEBIT | 12,347 | |
| MEAL_BENEFIT | 6,687 | |
| STORE_DIRECT_PAYMENT | 6,574 | |
| CREDIT | 4,966 | |
| 9 others | each <2,000 | |

Split payments: 13.9% of paid orders (48,818 of 350,334) have more than one payment.

**Delivery distance (m):** p5 408, p25 1,184, p50 2,073, p75 3,507, p95 7,096, p99 18,994. It varies by modal: BIKER averages about 1.1 km, MOTOBOY 3.0–3.7 km.

**Drivers:**

- Deliveries by driver type: BIKER FREELANCE 97,490; MOTOBOY FREELANCE 161,847; MOTOBOY LOGISTIC OPERATOR 103,538.
- Per driver: active days p50 8, p90 51, max 119. Total deliveries p50 20, p90 222, max 10,912.
- Per driver-day: mean 4.39, p50 3, p90 8, p99 14.

**Benchmark (query-level validation checks).** Spider2-lite has 3 tasks on this database. All three are replicated exactly [13]:

- **local209:** the store with the most orders, and its DELIVERED ratio.
  - Gold: store 53 "PAPA SUCIS", 14,004 orders, 13,870 with a DELIVERED delivery, ratio 0.9904.
  - Replica: (53, 14004, 13870).
- **local210:** hubs with more than 20% growth in FINISHED orders from Feb to Mar, using `order_created_month` and a stores→hubs join (the gold SQL is public).
  - Replica: 21 hubs. Gold rows include, for example, hub 8 at 9,568 → 12,034 and hub 27 at 1,426 → 4,008 (+181%).
  - This check depends on order_created_month, so the 3 created_\* overrides matter only at hour or day level.
- **local212:** the top 5 drivers by average daily deliveries.
  - Gold variant c: 25651 at 92.47, 26223 at 72.07, 49258 at 12.68, 357 at 11.22, 41596 at 11.16.
  - Replica: identical, using the order-created UTC date and non-null drivers.
  - Gold variants a and b differ (91.5 or 92.4), depending on the day definition and on counting the delivery_status filter.
  - **This makes the delivery date a check.** The time tied to `delivery_assigned` matters only if the "day" is taken from it. Keep checks on the order-created date.

No task cites external_knowledge, and no gold SQL exists for local209 or local212 (exec CSVs only).

## 6. simkit mapping sketch

**Entities.** hubs, stores, channels and drivers are inserted by a source from fitted marginals:

- store→hub, Zipf-like store weights, a segment flag, and a plan price.
- drivers with a home hub, modal, and type. Include 2 "fleet" pseudo-drivers.

**Owners and shards:**

- **`order` owner, one per order.** It runs a machine:

  `created → (accept | cancel) → accepted → ready → collected → in_expedition → delivering → [delivered] → finished`

  - Each transition is a `branch` with lognormal+tail delays (the §5 table).
  - Per-stage "record moment" probabilities (§4 patterns) are applied as emit flags rather than states. The process continues even when a moment is unrecorded.
  - A cancel branch is available from the created, accepted and ready states (rates by segment). A ~8% post-cancel "ghost" continuation reproduces the CANCELED orders that have later moments.
  - A 1.2% out-of-order jitter overlay or flag covers the reversed moments.
- **`store` shard, one per store** (or one per hub to cut partition count). It owns the production queue and capacity, so accepted→ready can grow with load. Optional for v1.
- **`hub_dispatch` shard, one per hub.** It owns the idle-driver pool. At `ready`, the order does:

  ```
  request(hub_dispatch, "assign", timeout=…)
  ```

  The shard replies with a driver_id, or with `None` 4.2% of the time, and emits `delivery_assigned` at delivering. The driver is returned by message at finished.

  Use `std.holds` on the driver pool: hold the driver at assignment, commit at finished, release on cancel. This gives a `holds_resolved` law and realistic driver-day loads. Re-dispatch (5.1% of orders have more than one delivery) is a second request on decline or timeout.

  Latency: platform δ ≈ 0.1–1 s, far below the minute-scale stages.
- **Payments:** emitted inline by the order at `created`.
  - Number of payments: 1 → 86%, 2 → 13.5%, 3+ → 0.45%.
  - Methods: VOUCHER + primary method.
  - The amounts split so that they sum to amount + fee (97%).
  - fee = rate(method) × amount.
  - Status: CHARGEBACK at ~0.1%, VOUCHER-heavy.

  No shard is needed (there is no balance constraint in the data). Use an `issuer`-style shard only if latency or declines are wanted.

**Sources:**

- Order arrivals per store, from a non-homogeneous Poisson process: hour-of-day × weekday × month ramp (×1.5 from March).
- Dimension population.
- Fleet drivers.

**Laws:**

- Order lifecycle: `lifecycle("order_id", …)`, relaxed for the out-of-order overlay.
- `pairing(delivery_assigned, delivery_closed)`.
- Payments sum = amount + fee (as a cross check with tolerance).
- `holds_resolved()` on drivers.
- `unique(payment_recorded, payment_id)`.

**Size.** One full-size, 120-day run, all 369k orders:

| Event | Count |
|---|---:|
| Order stage events (non-null moments) | 2.42M |
| Cancels | 17k |
| Payments | 401k |
| Delivery assigned + closed | 0.76M |
| Holds/requests | +~0.7M |

That is about 4.3M events. At ~2.6M events per ~10 s, this is roughly 15–20 s: fine.

Profiles:

- `sample`: 10% of stores, or 12 days, about 4×10⁵ events.
- `full`: 1×.

## 7. Open questions and risks

- **Licence.** The Kaggle API says `licenseName: "Data files © Original Authors"`: not an open licence. Creator: Nosbielcs (Cleibson Almeida), 2021-07-12, downloadCount 10,631.
  - The description says the model represents data "de forma fictícia" (fictitiously) and was anonymised under the LGPD.
  - Redistributing the raw tables is unclear. Spider2 redistributes them.
  - **Recommendation:** ship only fitted parameters and synthetic output, not the data.
- **Metric provenance.** The metrics come from a clock other than the text moments (§3). Generated metrics will be "too clean" by ±1 s in ~25% of values. This is acceptable statistically, not for byte-exact tests.
- **Cancel semantics.** There is no cancel time. CANCELED orders with finished, delivered or DELIVERED deliveries suggest that status was overwritten after fulfilment (refund or cancellation after delivery?), or that the export mixes systems.
- **Unclear meanings:**
  - order_delivery_fee vs order_delivery_cost vs payment fee: who pays what.
  - DELIVERING delivery rows on FINISHED orders (168).
  - The delivered moment present for only 5.4% of orders (a channel-specific integration?).
- **Fleet pseudo-drivers** (25651, 26223) distort per-driver stats. Decide whether to model them as entities or exclude them from fits. Benchmark local212 needs them.
- **Distance outliers** (up to 7,251 km) and 11 zeros: clip for fitting, but reproduce them as an overlay if exact tail checks are wanted.
- **Time zone** is inferred (UTC), not documented. The `order_created_day` checks used by the benchmark (local210 monthly) are insensitive to it, but day-level driver stats (local212) depend on UTC days.
- **Id spaces.** Real ids are sparse (only a fraction of the operator's orders are present). A generator using dense ids passes all join and aggregate checks, but not id-equality checks.
