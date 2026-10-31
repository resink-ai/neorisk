# bitcoin_* (Spider 2.0-lite, bank_sales_trading): reverse-engineering the crypto trading case into an event log

Source: the tables `bitcoin_members`, `bitcoin_transactions` and `bitcoin_prices` in `data/spider2/bank_sales_trading.sqlite`, opened read-only. The other tables there belong to other reports: Data Bank and Clique Bait are in [`bank_clicklog.md`](bank_clicklog.md), whose section C took a first short look at this group.

Scripts are in [`scripts/bitcoin/`](scripts/bitcoin/):
- `bq.py` runs named SQL blocks on an in-memory copy of the three tables. Its helper views are `tx`, which adds an ISO date `d`, and `pr`, which adds `d`, the parsed volume `vol` and the parsed change `chg`.
- `q1_inventory.sql`, `q2_prices.sql`, `q3_transactions.sql` and `q4_spider.sql` hold the SQL blocks.
- `p1_roundtrip.py` is a prototype ingest plus DuckDB views that rebuilds the three tables and compares them exactly.
- `p2_stats.py` measures fingerprints and distributions.
- `p3_gold.py` checks the q4 results against the gold CSVs in `gold/`.

Raw outputs are in `out_*.txt`. A reference such as [q2:change_vs_close] means file `q2_prices.sql`, block `-- name: change_vs_close`. The Python scripts are cited as [p1], [p2] and [p3].

## 0. What this catalog is

- **Origin.** This is Danny Ma's crypto trading case study ("Serious SQL" / Data With Danny; schema `trading` with `members`, `prices`, `transactions`), loaded into the same Spider file as his 8 Week SQL Challenge cases.
- **Evidence.** The cast is Danny, Vipul, Charlie, Nandita, Rowan, Ayush, Alex, Abe, Ben, Enoch, Vikram, Leah, Pavan and Sonia. Every member_id is the first 6 hex characters of `md5(str(rowid))`, 14 of 14 [p2]: `c4ca42` = md5("1") is Danny, and `aab323` = md5("14") is Sonia. The same id recipe produced the Clique Bait cookie ids.
- **The two halves are different in kind.**
  - **Prices look real.** They are daily OHLC bars for BTC and ETH from 2017-01-01 to 2021-08-29, and the levels match the public market: BTC closes at 995.4 on 2017-01-01 and 48 255.0 on 2021-08-29, ETH at 8.2 and 3 177.84 [p2].
    - The columns `price, open, high, low, volume ("582.04K"), change ("-2.04%")` and the newest-first row order [q1:physical_order_prices] are the layout of an Investing.com "historical data" export: Price, Open, High, Low, Vol., Change %.
    - Which venue's volume this is, is unstated. The BTC volume is far below the market total (§4).
  - **Members and transactions are generated** (§4). There are 28 opening buys of exactly 50 coins, then a Poisson stream of uniformly sized trades. No trade carries a price.
- **Row counts** [q1:row_counts]: bitcoin_members 14, bitcoin_transactions 22 918, bitcoin_prices 3 404 (1 702 days × 2 tickers).
- **Licence.** Unstated. It is course material, and the prices are a third-party market-data export. Treat it like `databank`: commit only the specs and the research.

## 0.1 How Spider 2.0 uses it

Two questions touch bitcoin_*. Neither has gold SQL (`gold/sql/local156.sql` and `local157.sql` both return 404), and neither has `external_knowledge`. Both have several accepted result CSVs.

| id | Analysis | Gold SQL? | Reproduced here? |
|---|---|---|---|
| local156 | Annual average BTC purchase price by region: Σ dollars spent / Σ quantity, BUY rows only, first year (2017) excluded. Rank the regions per year, and give the % change on the previous year | no; CSVs `_a` `_b` `_c` `_d` | **Yes, exact, all 4** [p3]. The dollars are **quantity × the close (`price`) of the transaction's date**, joined on (ticker, date). `_a`/`_d` exclude the fee; `_b`/`_c` include it as `× (1 + percentage_fee/100)`. For 2018, `_a`/`_b` keep the % change against 2017 and `_c`/`_d` blank it. India 2018 is 8 031.110 without the fee and 8 051.366 with it [q4:local156_*] |
| local157 | Daily % change in volume per ticker, 2021-08-01..10. "K"/"M" are expanded, "-" counts as 0, and the previous day is the last earlier **non-zero** volume | no; CSVs `_a` `_b` `_c` | **Yes, exact, all 3** [p3]. They differ only on 08-01: `_c` computes it from 07-31 (BTC +79.91%), `_a` leaves it null, and `_b` drops the row. The BTC spikes −99.65% / +30 369% come from the source row `03-08-2021 0.26K` [q2:local157_window] |

So:
- local156 tests the **implicit trade price**. The trade table has no price, and the analysis must join the daily close.
- local157 tests the **text parsing of volume**. The "-" rule never fires inside the window: the only "-" is ETH 2017-11-26.
- Both are exact regression checks for the round trip. In a simulation they are shape checks:
  - local156: regional averages track the yearly mean close, with a 2021/2020 ratio of about 3.9.
  - local157: local157 is driven by the exogenous series, so a replayed series reproduces it exactly.

## 1. Inventory, keys, joins

| Table | Rows | Key (verified unique) | Role |
|---|---|---|---|
| bitcoin_members | 14 | member_id (14 distinct; first_name is unique too) | static dimension: member, name, region |
| bitcoin_transactions | 22 918 | **txn_id** 1..22 918, no gaps, `rowid = txn_id` on every row; no duplicate full rows | activity log: one trade per row |
| bitcoin_prices | 3 404 | (ticker, market_date); 0 duplicates; 1 702 days per ticker with no calendar gaps (every step is 1 day) | exogenous daily bar series |

Sources: [q1:member_key, q1:txn_key, q1:txn_full_row_duplicates, q1:price_key, q1:price_dup_days, q1:price_calendar_gaps].

- **Types.**
  - Transactions are `INTEGER, TEXT, TEXT, TEXT, TEXT, REAL, REAL, TEXT` on every row.
  - Prices are `TEXT, TEXT, REAL×4, TEXT, TEXT`. `volume` and `change` are text.
  - There are **no NULLs and no empty strings** in any of the three tables [q1:storage_types, q1:nulls_and_empty].
- **Joins.** No foreign keys are declared. Measured:
  - transactions.member_id → members: 0 orphans, and every member trades [q1:fk_member].
  - Transactions → prices on (ticker, date): **every one of the 22 918 has its day's bar** (0 missing) [q1:fk_price_day].
  - Prices run 2 days past the last trade: trades end 2021-08-27, bars end 2021-08-29 [q1:tx_time_range, q3:tx_after_prices].
- **Members per region**: United States 7, Australia 4, and India, Asia, Africa 1 each [q1:members_per_region]. For local156 this means India, Asia and Africa are single-member "regions".
- **Categoricals** [q1:categoricals]: ticker ∈ {BTC 12 484, ETH 10 434}; txn_type ∈ {BUY 18 881, SELL 4 037}. By ticker × type: BTC BUY 10 440, BTC SELL 2 044, ETH BUY 8 441, ETH SELL 1 993.
- **Time columns.**
  - `txn_date` is `DD-MM-YYYY`.
  - `txn_time` is ISO `YYYY-MM-DDTHH:MM:SS.mmmZ` (ms, `Z` suffix).
  - `market_date` is `DD-MM-YYYY`.
  - All of them are valid calendar dates, and `txn_date` equals the date of `txn_time` on **22 918 of 22 918** rows [q1:date_formats]. The range runs from 2017-01-01T00:00:00.000Z to 2021-08-27T22:26:10.258Z.

## 2. Event catalog

| Event / entity | Owner | Time | Attributes | Source rows | Count |
|---|---|---|---|---|---|
| entity `members` | — | created_at = first trade (2017-01-01 00:00 for all 14) | ext_id = member_id (md5 text), first_name, region | bitcoin_members | 14 |
| entity `tickers` | — | created_at = first bar | ext_id ∈ {BTC, ETH} | distinct ticker | 2 |
| `price_published` | ticker | market_date 00:00 UTC (rule, §3.4) | price (close), open, high, low (f64); volume (opt i64 coins); change_pct (f64) | bitcoin_prices, 1 row → 1 event | 3 404 |
| `trade` | member | txn_time (ms, UTC) | ticker (ref), txn_type cat(BUY, SELL), quantity f64, percentage_fee f64, txn_id i64 | bitcoin_transactions, 1 row → 1 event | 22 918 |

Total: **26 322 events and 16 entity rows** [p1].

**Why prices are an event stream and not an entity.**
- A bar is a dated observation of a market, not a thing with a lifecycle. As entities, the 3 404 rows would all be "created" once and never change. As `price_published` events they form an ordered series, and the views rebuild the table by projecting it.
- **Prices are exogenous.** Nothing in the trade log moves them, and they do not move the trades:
  - corr(daily change, trades that day) = −0.009 for BTC and −0.015 for ETH;
  - corr(change, sell share) = 0.029 and 0.000;
  - corr(close, mean quantity) = −0.003 and −0.012 [p2].
- So in stage 2 the series is an **exogenous input**. A Source replays it, or a fitted process generates it, through `src.share(...)`, and the same Source emits `price_published` so that the views can rebuild the table. The owner is the ticker. No member causes a bar.

**Why a trade carries no price.** The source records none. The "trade price" in every analysis is the **close of the trade's calendar day** (local156, §0.1).
- This is a join convention, not a fact. A trade at 00:00:01 is valued at a close that is set 24 h later, which is look-ahead.
- The log must **not** store a derived `price` on `trade`, because it would duplicate `price_published` and could drift from it. The views join it when a query needs it.

**What is not an event.**
- `txn_date` is derived from `txn_time` (§3.1).
- Holdings and balances are derived and are never stored.
- There is no deposit and no cash leg. The 28 opening 50-coin buys are ordinary `trade` rows with `txn_id` 1..28. They could be split out as a `position_seeded` event, but that is not needed for the round trip.

**Prototype result** [p1]: ingest → DuckDB views → the multiset comparison is **exact for all three tables**:
- bitcoin_members 14 = 14;
- bitcoin_transactions 22 918 = 22 918;
- bitcoin_prices 3 404 = 3 404.

The two alternatives also pass:
- volume and change kept as raw text;
- txn_id rebuilt as a rank instead of carried.

## 3. Rebuild rules and blockers to an exact round trip

1. **`txn_date` is derived exactly.** `txn_date = strftime(event_time, '%d-%m-%Y')`, with 0 mismatches [q1:date_formats]. `txn_time = strftime(event_time, '%Y-%m-%dT%H:%M:%S.%gZ')`: DuckDB's `%g` gives ms, and the 3 digits are always present, including `.000` [q1:date_formats, p1]. The `Z` means the wall clock is already UTC, so no zone folding is needed.
2. **txn_id.**
   - It equals the rank of txn_time with no exception: 22 917 of 22 917 consecutive pairs are non-decreasing in time, with 0 descents and 0 date descents [q3:id_vs_time], and `row_number() over (order by txn_time, txn_id) = txn_id` on 22 918 of 22 918 rows [q3:rank_by_time_equals_id].
   - The only tie is the 28 opening buys at 2017-01-01 00:00:00.000. They are the single tie group, and no tie exists outside it [q3:time_ties, q3:time_ties_excl_midnight].
   - Their order is **not** member order. BTC comes first, ordered c81e72, eccbc8, a87ff6, …, c4ca42 (6th) …; then ETH from 167909 [q3:initial_buys_order].
   - So txn_id cannot be derived without a tiebreak for those 28 rows. **Carry `txn_id` as an i64 attribute and use it as `ord`.** Stage 2 can derive it as rank(event_time) and draw any order among ties.
3. **Volume text** [q2:volume_*].
   - The formats are `<mantissa 2 dp>K` (1 963 rows), `<mantissa 2 dp>M` (1 440 rows) and one `-` (ETH 26-11-2017).
   - Every mantissa has exactly 2 decimals. K mantissas lie in 0.26–999.53 and M mantissas in 1.00–77.47, so the switch is exactly at 1 000 000.
   - The value is therefore an **exact integer number of coins**: K × 1 000 and M × 1 000 000, parsed from the digits rather than through floats (`16.03*1e3` = 16030.000000000002 in float).
   - Rebuild rule: `NULL → '-'`; `v ≥ 1e6 → printf('%.2fM', v/1e6)`; otherwise `printf('%.2fK', v/1e3)`. It is byte-exact on 3 404 of 3 404 rows, in Python and in DuckDB [p1].
   - Store `volume` as `opt(i64)`, with NULL for `-`. local157's "treat '-' as 0" is a query rule, and the log keeps NULL.
4. **Change text is not derivable, so carry it** [q2:change_*].
   - The format is `-?d+.dd%`, always 2 decimals, with no `+` sign and no `-0.00%`. `0.00%` occurs 7 times.
   - Recomputing it from the rounded closes, `printf('%.2f%%', 100·(price/prev − 1))`, matches the text on only **1 585 of 1 701 BTC rows and 1 540 of 1 701 ETH rows**. 3 rows differ by more than 1 bp: BTC 17-01-2017 is 8.74% in the text and 8.7514% recomputed [q2:change_vs_close, q2:change_mismatches]. The vendor computes it from unrounded prices.
   - The first day of each ticker has a change (BTC 3.33%, ETH 2.50%) that no row in the table can produce [q2:change_first_day].
   - Store `change_pct` as f64. The rebuild `printf('%.2f%%', change_pct)` is exact on 3 404 of 3 404 rows [p1]. Raw text also works.
5. **open is not the previous close.** It equals the previous close on only 570 of 1 701 BTC rows and 656 of 1 701 ETH rows. 1 658 and 1 623 are within 10 bp; 2 and 9 are more than 1% off, up to −3.17% for ETH on 12-01-2017 [q2:open_vs_prev_close*]. So carry OHLC as four f64 values; none of them is derivable.
6. **Floats.**
   - Prices: BTC has 1 decimal, ETH 1–2 [q2:price_decimals].
   - quantity: up to 9 decimals; `quantity == round(quantity, 9)` on 22 890 of 22 890 [p2, q3:qty_decimals].
   - percentage_fee: exactly 2 decimals, with 0 exceptions [q3:fee_values_two_decimals].
   - None of these is exact cents in a currency, so all stay `f64`. The REAL values round-trip by value.
7. **Time for prices (rule).**
   - `market_date` is a bare date. Following the refdata convention, it is read as **00:00 UTC of market_date**, the bar's label time.
   - A bar's close is only final at 24:00. A stage-2 pack whose members react to prices must therefore read the *previous* bar. Alternatively, it can publish at market_date + 1 d, and the views subtract a day. Both are exact for stage 1.
   - Snapshot N: the last bar is 2021-08-29, so N ≥ 2021-08-29 00:00 under the label rule, and every event lies at or before N. The last trade is at 2021-08-27 22:26:10.258.
8. **Physical order** is not compared (multiset), but it can be regenerated if wanted:
   - transactions are in txn_id order;
   - members are in md5-n order (rowid = n);
   - prices are **ETH first (rowids 1–1 702), then BTC (1 703–3 404), each newest first**, with 1 701 of 1 701 steps descending [q1:physical_order_prices].
9. **Nothing else blocks the round trip.** There are no NULLs, no `\N` and no duplicates. The source has no derived summary table.

## 4. Measured quirks

- **Generator fingerprints in the transactions** [q3, p2]:
  - **Seeding.** txn_id 1..28 are one 50.0-coin BUY per member per ticker, all at 2017-01-01T00:00:00.000Z. They are the only rows at midnight, the only rows with quantity 50, and the only rows with fewer than 4 decimals [q3:initial_buys, q3:qty_50, q3:qty_decimals].
  - **Arrivals are a single global Poisson process.**
    - Gaps: mean 6 416 s, sd 6 331 s, CV 0.987. KS against Exp(mean): D = 0.007, p = 0.21.
    - Per-day counts: mean 13.47, var 13.67 [p2]. No day is empty [q3:days_without_tx], and the busiest day has 32 rows [q3:rows_per_day].
    - Hour of day is flat (906–1 020 per hour) [q3:hour_of_day], and the ms digits are uniform: 22 rows of 22 890 have `.000` [q3:ms_digits].
    - There is no weekly or yearly seasonality: 361–450 per month and 4 856–5 047 per full year [q3:monthly_volume, q3:yearly].
  - **Quantity ~ U(0, 10)**, independent of side, ticker and price.
    - KS p-values: BTC BUY 0.42, ETH BUY 0.46, ETH SELL 0.29, BTC SELL 0.029 (n = 2 044, D = 0.032).
    - Decile counts are flat [q3:qty_hist_buy, p2].
    - Notional is therefore absurd for a retail book: a median BTC trade is $36 310 and the maximum is $594 223 [p2].
  - **Fee = min(round(U(0,1), 2), 0.30)**:
    - 0.30 occurs 16 166 times against 16 157 expected;
    - 0.00 occurs 114 times against 114.6 expected (a half-width bucket);
    - 0.01..0.29 average 228.9 against 229.2 expected;
    - χ² p = 0.70 [p2].
    The fee does not depend on member (mean 0.252–0.258), year, ticker or side [q3:fee_by_*].
  - **Member choice is weighted, not uniform.** Shares run from 5.53% (Charlie) to 9.43% (Danny); χ² against uniform gives p = 4e-107 [p2]. Each member has its own BTC share (0.378–0.727) and SELL share (0.048 for Ben … 0.295 for Pavan) [p2, q3:per_member].
  - **Holdings never go negative**: 0 rows, in txn_id or time order [q3:holdings_nonneg_by_*]. This is trivially so:
    - a SELL takes at most 26.3% of the holding just before it (median 0.4%), and at least 26.18 coins are left afterwards [q3:sell_max_frac, p2];
    - holdings only grow (final 413–4 226 coins per member and ticker).
    The data **cannot show whether a sell guard exists**: no sell ever came near the bound.
  - **Trades ignore the market.** All correlations with change and price are |r| < 0.03 (§2). Every trade day has a bar.
- **Price-series quirks** (vendor data) [q2]:
  - **ETH 2017-11-26 is a filler bar.** OHLC are all 464.0 (= the previous close), volume `-` and change `0.00%`. It is the only flat bar [q2:volume_dash_row, q2:ohlc_consistency].
  - **2 BTC bars break OHLC.** On 12-02-2017 high 1 007.8 < open 1 008.3. On 06-04-2017 low 1 130.5 > open 1 129.9 [q2:ohlc_violations]. A law `low ≤ open, close ≤ high` would fail on real data, so it must tolerate this.
  - **Volume glitches.** BTC 03-08-2021 is `0.26K` (260 coins, between 74.81K and 79.22K). Others are 25-12-2020 at 2.40K, 16-08-2021 at 2.41K and 07-10-2018 at 77.06K after 9.18M. In all, 15 day-on-day ratios are above 20× or below 0.05× [q2:volume_tiny, q2:volume_jumps]. local157's −99.65% and +30 369% come straight from this.
  - **Volume regime shifts.** Median BTC volume by year is 89.7k, 232k, 663k, 524k, then **109k in 2021**; ETH is 516k, 1.52M, 9.65M, 11.3M, then **1.73M** [p2]. The venue or the units appear to change in 2021. The BTC volume is far below the market total, so the volume belongs to one exchange.

## 5. Distributions to fit (stage 2)

- **Arrivals.**
  - One global homogeneous Poisson process at **13.47 trades per day**: mean gap 6 416 s, over 1 699.8 days [p2].
  - The member is drawn from 14 fixed weights, which are the shares in §4 (Danny 0.0943 … Charlie 0.0553).
  - Per member, the ticker is BTC with p_m ∈ [0.378, 0.727] (overall 0.5448), and the side is SELL with q_m ∈ [0.048, 0.295] (overall 0.1764) [p2].
  - Ticker and side are weakly dependent overall: the SELL share is 16.4% for BTC and 19.1% for ETH, χ² p = 7e-8 [p2]. That is consistent with the per-member mixing, not a separate effect.
- **Same member-ticker-day multiplicity** [q3:rows_per_member_ticker_day]: 1 → 13 742, 2 → 3 483, 3 → 596, 4 → 89, 5 → 12, 6 → 1. Poisson thinning predicts this.
- **Quantity**: U(0, 10), rounded to 9 dp. **Fee**: min(round(U(0,1), 2), 0.30). **Seeding**: one BUY of 50 per member × ticker at t = 0.
- **Lifecycle**: none. All 14 members are present from day 0 to the end (last trade 2021-08-25..27), and there is no churn and no sign-up [q3:per_member].
- **Exogenous prices** [p2]: daily log returns, close to close.

  | Ticker | Mean | sd | Skew | Excess kurtosis | Min / max | (H−L)/close p50 / p90 | log10 volume p10 / p50 / p90 |
  |---|---|---|---|---|---|---|---|
  | BTC | 0.00228 | 0.0433 | −0.90 | 12.5 | −0.497 / +0.228 | 0.047 / 0.112 | 4.82 / 5.34 / 6.05 |
  | ETH | 0.00350 | 0.0580 | −0.62 | 9.0 | −0.590 / +0.259 | 0.063 / 0.147 | 5.67 / 6.49 / 7.21 |

  Yearly price ranges are in [q2:price_range_by_year].
  - For stage-1 parity, replay the real series.
  - For a synthetic series, use a fat-tailed process, such as Student-t innovations or a GARCH-like model, fitted to these moments.
  - A Gaussian GBM with `crypto_exchange`'s `vol_per_day = 0.03` gives too little volatility (0.043 for BTC and 0.058 for ETH) and no tails.

## 6. simkit mapping sketch

**pack.py (stage 1)**

```python
p.entity("tickers", key="ticker_id", cols={"ext_id": text(doc="BTC | ETH")})
p.entity("members", key="member_id", cols={"ext_id": text(doc="md5(n)[:6]"),
                                           "first_name": text(), "region": text()})
p.event("price_published", doc="One daily bar of an exogenous market series", cols={
    "ticker_id": ref("tickers"), "price": f64(doc="close"), "open": f64(), "high": f64(), "low": f64(),
    "volume": opt(i64(min=0, doc="coins; NULL = '-' in the source")),
    "change_pct": f64(doc="vendor % change, 2 dp; not derivable from closes")})
p.event("trade", doc="A member buys or sells at the day's close (no price is stored)", cols={
    "member_id": ref("members"), "ticker_id": ref("tickers"), "txn_type": cat("BUY", "SELL"),
    "quantity": f64(), "percentage_fee": f64(), "txn_id": i64(min=1)})
```

**ingest.sql**
- `-- entity: tickers`: `SELECT DISTINCT ticker AS ext_id … ORDER BY ticker`.
- `-- entity: members`: `… ORDER BY member_id`. The key is the rank of ext_id, so it is *not* the md5 n.
- `-- event: price_published owner=ticker_id`:
  - event_time = `substr(market_date,7,4)||'-'||substr(market_date,4,2)||'-'||substr(market_date,1,2)||' 00:00:00'`;
  - volume is parsed from its digits: `CAST(replace(substr(volume,1,length(volume)-1),'.','') AS INTEGER) * (CASE suffix WHEN 'K' THEN 10 ELSE 10000 END)`, and NULL for `-`;
  - `ORDER BY ticker, market_date`.
- `-- event: trade owner=member_id ord=txn_id`:
  - event_time = `iso_time(txn_time, '%Y-%m-%dT%H:%M:%S.%fZ')`;
  - `ORDER BY txn_id`.
  - With ord = txn_id, the 28 ties at t = 0 keep their order, and `seq` follows txn_id.

**views.sql** (DuckDB):
- the three `-- table:` blocks exactly as in `p1_roundtrip.py`: `strftime` for `%d-%m-%Y` and `%Y-%m-%dT%H:%M:%S.%gZ`, the K/M/`-` formatter, and `printf('%.2f%%', change_pct)`.
- **source.toml** keys: `bitcoin_members = ["member_id"]`, `bitcoin_transactions = ["txn_id"]` and `bitcoin_prices = ["ticker", "market_date"]`.
- **queries**: `local156.sql` (the fee-included and fee-excluded variants) and `local157.sql`, both from `q4_spider.sql`.

**Stage 2 behaviour**
- **Source `market`.** It replays or generates the two daily series into `src.share("bars", close=…)` and emits `price_published` at each day. It inserts the 2 tickers and the 14 members with fixed weights.
- **One `desk` process.** A global Poisson timer at 13.47 per day picks a member by weight, then a ticker (p_m), then a side (q_m). It draws the quantity from U(0,10) and the fee from min(round(U,2), 0.3), and emits `trade`. At t = 0 it emits the 28 seeding buys.
  - A per-member owner process with rate w_m · 13.47 per day is equivalent and partitions better: Poisson splitting.
  - A `running_nonneg(trade, by=[member_id, ticker_id], qty=±quantity)` law holds on real data. A SELL guard (refuse a sell larger than the holding) never binds at these rates.
- **Laws that real data passes**:
  - `unique(trade, txn_id)`;
  - `consecutive(trade, txn_id)` from 1;
  - txn_id monotone in event_time;
  - `unique(price_published, [ticker_id, day])`;
  - a bar on every calendar day between the first and last bar;
  - every trade day has a bar;
  - non-negative holdings.
- **Laws that real data breaks**: OHLC containment (2 rows), `open = previous close`, `change = round(close/prev − 1)` and volume > 0 (1 NULL). Do not add them, or give them tolerances.
- **Overlap with `examples/crypto_exchange`.**
  - The same two assets: BTC-USD and ETH-USD there, BTC and ETH here.
  - The same pattern of an **exogenous fair price** shared by a Source: `src.share("fair", …)`, an hourly GBM at 3%/day.
  - Owners there are traders, here members.
  - That is the whole overlap. crypto_exchange has order books, makers, GTC/IOC/FOK orders, integer ticks and lots, counterparties and USD balances. Here there is no order, no counterparty, no cash, no trade price, and quantities are fractional coins.
  - The real bars could **calibrate crypto_exchange's fair-price process**: the returns, the fat tails, and the start levels for a 2017–2021 run. A `bitcoin` pack would be a much simpler retail-ledger pack. It is not a sub-case of the matching engine. A crypto_exchange `trade` (price, qty, buyer, seller) cannot be rebuilt into these tables without inventing the missing member, fee and close-valuation conventions.
- **Size**: about 26.3k events per native run (3.4k bars and 22.9k trades) over 1 702 days. That is trivial.

## 7. Open questions and risks

- **Exact price provenance.** The layout and the newest-first order point to an Investing.com export, but the exchange behind the volume is not identified. The 2021 drop in volume and the glitch bars (0.26K) suggest a switch of source or units. That affects only realism, not the round trip.
- **Licence.** Course material containing third-party market data, with no licence stated. Committing the specs and research is fine; do not commit the rows.
- **Valuation convention.** "Price of a trade = the close of its date" is what the gold answers use, but it is look-ahead. Should stage 2 value trades at the close, at the open, or at an intraday interpolation? Spider only checks the close join.
- **Price event time.** Use the label time (00:00 of market_date, recommended for stage 1) or the publication time (+1 d)? Decide before stage-2 members are allowed to read prices.
- **Seeding.** Should the 28 opening buys be modelled as their own event (`position_seeded`) or stay as trades? Today they hold txn_id 1..28, and Spider's local156 excludes 2017 anyway.
- **Is there a sell guard?** Not observable (§4), so stage 2 may include one or not.
- **Realism.** The generated half is classroom-grade: uniform quantities with million-dollar notionals, a fee drawn per trade rather than per member tier, no reaction to price, and no lifecycle. Its value is as a round-trip harness for **exogenous series + owner activity + implicit-price joins + text-formatted numbers**. The price series is the only realistic part.

---

Summary:
1. Feasible for an exact round trip: **yes**. The prototype rebuilds all three tables as exact multisets, and Spider's local156 (4 variants) and local157 (3 variants) reproduce exactly from the raw tables.
2. Proposed project: **`bitcoin`**, from 3 of bank_sales_trading's tables.
3. Events: **2 types**, `trade` (22 918) and `price_published` (3 404), for 26 322 events.
4. Entities: **2**, `members` (14) and `tickers` (2).
5. Hardest blocker: the vendor text in `bitcoin_prices`.
   - `change` cannot be derived from the closes (1 585 of 1 701 BTC and 1 540 of 1 701 ETH rows match), so it is carried.
   - `volume` K/M/"-" must be parsed to exact integer coins and re-formatted at the 1M switch.
   - Trades have no price, and are valued by joining the same day's close.
