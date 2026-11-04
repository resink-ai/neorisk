-- name: millis_suffix
SELECT 'orders' t, sum(substr(occurred_at,20) = '.000Z') ms000z, count(*) n FROM web_orders UNION ALL SELECT 'events', sum(substr(occurred_at,20) = '.000Z'), count(*) FROM web_events;
-- name: rowid_vs_account_id
SELECT sum(id <> 991 + 10*rowid) mism, count(*) n FROM web_accounts;
-- name: reps_id_step
SELECT min(id), max(id), count(*), (max(id)-min(id))/10+1 slots, sum(id % 10 <> 0) not_step10 FROM web_sales_reps;
-- name: reps_rowid_order
SELECT sum(nxt < cur) desc_pairs FROM (SELECT id cur, lead(id) OVER (ORDER BY rowid) nxt FROM web_sales_reps);
-- name: total_is_sum_qty
SELECT sum(total = standard_qty + gloss_qty + poster_qty) ok, count(*) n FROM web_orders;
-- name: unit_prices
SELECT 'standard' p, min(standard_amt_usd/standard_qty) mn, max(standard_amt_usd/standard_qty) mx FROM web_orders WHERE standard_qty > 0 UNION ALL
SELECT 'gloss', min(gloss_amt_usd/gloss_qty), max(gloss_amt_usd/gloss_qty) FROM web_orders WHERE gloss_qty > 0 UNION ALL
SELECT 'poster', min(poster_amt_usd/poster_qty), max(poster_amt_usd/poster_qty) FROM web_orders WHERE poster_qty > 0;
-- name: amt_is_qty_times_price_sqlite
SELECT sum(standard_amt_usd = standard_qty * 4.99) std_eq, sum(abs(standard_amt_usd - standard_qty * 4.99) < 1e-6) std_close,
       sum(gloss_amt_usd = gloss_qty * 7.49) gl_eq, sum(abs(gloss_amt_usd - gloss_qty * 7.49) < 1e-6) gl_close,
       sum(poster_amt_usd = poster_qty * 8.12) po_eq, sum(abs(poster_amt_usd - poster_qty * 8.12) < 1e-6) po_close, count(*) n FROM web_orders;
-- name: total_amt_is_sum_sqlite
SELECT sum(total_amt_usd = standard_amt_usd + gloss_amt_usd + poster_amt_usd) eq, sum(abs(total_amt_usd - (standard_amt_usd + gloss_amt_usd + poster_amt_usd)) < 1e-6) close_, count(*) n FROM web_orders;
-- name: amt_cents_grid
SELECT sum(round(standard_amt_usd*100) = standard_amt_usd*100) std, sum(round(gloss_amt_usd*100) = gloss_amt_usd*100) gl, sum(round(poster_amt_usd*100) = poster_amt_usd*100) po, sum(round(total_amt_usd*100) = total_amt_usd*100) tot, count(*) n FROM web_orders;
-- name: zero_qty_orders
SELECT sum(total = 0) total0, sum(standard_qty = 0) std0, sum(gloss_qty = 0) gl0, sum(poster_qty = 0) po0, sum(standard_qty=0 AND gloss_qty=0) only_poster FROM web_orders;
-- name: zero_total_rows
SELECT * FROM web_orders WHERE total = 0 LIMIT 5;
-- name: dup_orders_same_account_time
SELECT o.* FROM web_orders o JOIN (SELECT account_id, occurred_at FROM web_orders GROUP BY 1,2 HAVING count(*) > 1) d USING (account_id, occurred_at) ORDER BY account_id, occurred_at, id;
-- name: order_desc_by_account_time
SELECT * FROM (SELECT id, account_id, occurred_at, lag(account_id) OVER (ORDER BY id) pa, lag(occurred_at) OVER (ORDER BY id) pt FROM web_orders) WHERE pa = account_id AND occurred_at < pt;
-- name: orders_id_order_rule
-- is id order = (account_id, occurred_at)? count of id pairs where account decreases
SELECT sum(na < a) acct_desc, sum(na = a AND nt < t) time_desc_within_account FROM (SELECT account_id a, occurred_at t, lead(account_id) OVER (ORDER BY id) na, lead(occurred_at) OVER (ORDER BY id) nt FROM web_orders);
-- name: events_id_order_rule
SELECT sum(na < a) acct_desc, sum(na = a AND nt < t) time_desc_within_account, sum(na = a AND nt = t) ties FROM (SELECT account_id a, occurred_at t, lead(account_id) OVER (ORDER BY id) na, lead(occurred_at) OVER (ORDER BY id) nt FROM web_events);
-- name: events_id_order_channel
-- within an account, are events grouped by channel then time?
SELECT sum(na = a AND nc < c) chan_desc, sum(na = a AND nc = c AND nt < t) time_desc_within_chan, sum(na = a AND nc <> c) chan_switches FROM (SELECT account_id a, channel c, occurred_at t, lead(account_id) OVER (ORDER BY id) na, lead(channel) OVER (ORDER BY id) nc, lead(occurred_at) OVER (ORDER BY id) nt FROM web_events);
-- name: account_order_in_ids
SELECT 'orders' t, count(*) runs, count(DISTINCT account_id) accts FROM (SELECT account_id, lag(account_id) OVER (ORDER BY id) p FROM web_orders) WHERE p IS NULL OR p <> account_id UNION ALL
SELECT 'events', count(*), count(DISTINCT account_id) FROM (SELECT account_id, lag(account_id) OVER (ORDER BY id) p FROM web_events) WHERE p IS NULL OR p <> account_id;
-- name: channel_mix
SELECT channel, count(*) n FROM web_events GROUP BY 1 ORDER BY 2 DESC;
-- name: event_hour_mix
SELECT 'events' t, substr(occurred_at,12,2) hh, count(*) n FROM web_events GROUP BY 2 UNION ALL SELECT 'orders', substr(occurred_at,12,2), count(*) FROM web_orders GROUP BY 2 ORDER BY 1,2;
-- name: per_year
SELECT 'orders' t, substr(occurred_at,1,4) y, count(*) n, round(sum(total_amt_usd),2) usd FROM web_orders GROUP BY 2 UNION ALL SELECT 'events', substr(occurred_at,1,4), count(*), NULL FROM web_events GROUP BY 2 ORDER BY 1,2;
-- name: per_month_orders
SELECT substr(occurred_at,1,7) ym, count(*) n FROM web_orders GROUP BY 1 ORDER BY 1;
-- name: orders_per_account_month
-- the Udacity generator: at most one order per account per month?
SELECT c, count(*) n FROM (SELECT account_id, substr(occurred_at,1,7) ym, count(*) c FROM web_orders GROUP BY 1,2) GROUP BY 1;
-- name: orders_monthly_rhythm
-- gap in days between an account's consecutive orders
SELECT CAST(julianday(nt) - julianday(t) AS INT) / 1 gap_days, count(*) n FROM (SELECT occurred_at t, lead(occurred_at) OVER (PARTITION BY account_id ORDER BY occurred_at) nt FROM web_orders) WHERE nt IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 15;
-- name: order_time_of_day_repeats
-- does an account keep the same time-of-day across orders (generator)?
SELECT sum(c) orders_in_repeated_tod, count(*) groups FROM (SELECT account_id, substr(occurred_at,12,8) tod, count(*) c FROM web_orders GROUP BY 1,2 HAVING c > 1);
-- name: order_tod_drift
SELECT * FROM web_orders WHERE account_id = 1001 ORDER BY occurred_at LIMIT 14;
-- name: event_tod_drift
SELECT * FROM web_events WHERE account_id = 1001 ORDER BY occurred_at LIMIT 14;
-- name: events_per_account_month
SELECT c, count(*) n FROM (SELECT account_id, channel, substr(occurred_at,1,7) ym, count(*) c FROM web_events GROUP BY 1,2,3) GROUP BY 1;
-- name: event_before_order
-- for each order: is there a web event for the account within the 24 hours before it?
SELECT sum(EXISTS (SELECT 1 FROM web_events e WHERE e.account_id=o.account_id AND e.occurred_at <= o.occurred_at AND julianday(o.occurred_at) - julianday(e.occurred_at) < 1)) with_event_24h, count(*) n FROM web_orders o;
-- name: order_minus_nearest_event_minutes
SELECT CAST((julianday(o.occurred_at) - julianday((SELECT max(e.occurred_at) FROM web_events e WHERE e.account_id=o.account_id AND e.occurred_at <= o.occurred_at)))*1440 AS INT) mins, count(*) n FROM web_orders o GROUP BY 1 ORDER BY 2 DESC LIMIT 12;
-- name: first_activity
SELECT sum(fo < fe) order_first, sum(fe < fo) event_first, sum(fe = fo) same FROM (SELECT a.id, (SELECT min(occurred_at) FROM web_orders WHERE account_id=a.id) fo, (SELECT min(occurred_at) FROM web_events WHERE account_id=a.id) fe FROM web_accounts a) WHERE fo IS NOT NULL;
-- name: qty_stats
SELECT 'standard' p, min(standard_qty), avg(standard_qty), max(standard_qty) FROM web_orders UNION ALL SELECT 'gloss', min(gloss_qty), avg(gloss_qty), max(gloss_qty) FROM web_orders UNION ALL
SELECT 'poster', min(poster_qty), avg(poster_qty), max(poster_qty) FROM web_orders UNION ALL SELECT 'total', min(total), avg(total), max(total) FROM web_orders;
-- name: total_amt_quantiles
WITH r AS (SELECT total_amt_usd q, row_number() OVER (ORDER BY total_amt_usd) rn, count(*) OVER () n FROM web_orders)
SELECT max(CASE WHEN rn <= n*0.1 THEN q END) p10, max(CASE WHEN rn <= n*0.25 THEN q END) p25, max(CASE WHEN rn <= n*0.5 THEN q END) p50, max(CASE WHEN rn <= n*0.75 THEN q END) p75, max(CASE WHEN rn <= n*0.9 THEN q END) p90, max(CASE WHEN rn <= n*0.99 THEN q END) p99, max(q) mx FROM r;
-- name: orders_per_account
SELECT CASE WHEN c <= 5 THEN '1-5' WHEN c <= 10 THEN '6-10' WHEN c <= 20 THEN '11-20' WHEN c <= 40 THEN '21-40' ELSE '41+' END b, count(*) accts, min(c), max(c) FROM (SELECT account_id, count(*) c FROM web_orders GROUP BY 1) GROUP BY 1 ORDER BY min(c);
-- name: events_per_account
SELECT CASE WHEN c <= 5 THEN '1-5' WHEN c <= 10 THEN '6-10' WHEN c <= 20 THEN '11-20' WHEN c <= 40 THEN '21-40' ELSE '41+' END b, count(*) accts, min(c), max(c) FROM (SELECT account_id, count(*) c FROM web_events GROUP BY 1) GROUP BY 1 ORDER BY min(c);
-- name: account_text
SELECT sum(website NOT LIKE 'www.%') odd_web, sum(name <> trim(name)) name_ws, sum(primary_poc <> trim(primary_poc)) poc_ws, count(DISTINCT primary_poc) pocs FROM web_accounts;
-- name: lat_long_precision
SELECT max(length(CAST(lat AS TEXT))) lat_len, max(length(CAST(long AS TEXT))) long_len, min(lat), max(lat), min(long), max(long) FROM web_accounts;
-- name: accounts_per_rep
SELECT c, count(*) reps FROM (SELECT sales_rep_id, count(*) c FROM web_accounts GROUP BY 1) GROUP BY 1 ORDER BY 1;
-- name: last_times
SELECT (SELECT max(occurred_at) FROM web_orders) last_order, (SELECT max(occurred_at) FROM web_events) last_event, (SELECT count(*) FROM web_orders WHERE occurred_at >= '2017-01-01') orders_2017, (SELECT count(*) FROM web_events WHERE occurred_at >= '2017-01-01') events_2017;
-- name: gold_local114
WITH r AS (SELECT g.name region, s.name rep, sum(o.total_amt_usd) amt, count(*) n FROM web_orders o JOIN web_accounts a ON a.id=o.account_id JOIN web_sales_reps s ON s.id=a.sales_rep_id JOIN web_region g ON g.id=s.region_id GROUP BY 1,2),
t AS (SELECT region, sum(n) orders, sum(amt) total FROM r GROUP BY 1),
m AS (SELECT region, max(amt) mx FROM r GROUP BY 1)
SELECT t.region, t.orders, t.total, r.rep, r.amt FROM t JOIN m USING(region) JOIN r ON r.region=t.region AND r.amt=m.mx ORDER BY 1;
