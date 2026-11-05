-- name: split_points
SELECT 'orders' t, id, account_id, lag(account_id) OVER (ORDER BY id) prev FROM web_orders WHERE 0 UNION ALL
SELECT * FROM (SELECT 'orders', id, account_id, lag(account_id) OVER (ORDER BY id) p FROM web_orders) WHERE p > account_id UNION ALL
SELECT * FROM (SELECT 'events', id, account_id, lag(account_id) OVER (ORDER BY id) p FROM web_events) WHERE p > account_id;
-- name: order_series_stats
SELECT CASE WHEN id < 4307 THEN 'A ids 1-4306' ELSE 'B ids 4307-6912' END s, count(*) n, count(DISTINCT account_id) accts, round(avg(total),1) avg_total, round(avg(total_amt_usd),2) avg_usd, min(occurred_at), max(occurred_at) FROM web_orders GROUP BY 1;
-- name: order_series_one_per_month
SELECT CASE WHEN id < 4307 THEN 'A' ELSE 'B' END s, max(c) max_per_account_month, sum(c > 1) multi FROM (SELECT id, account_id, substr(occurred_at,1,7) ym, count(*) OVER (PARTITION BY id < 4307, account_id, substr(occurred_at,1,7)) c FROM web_orders) GROUP BY 1;
-- name: event_series_stats
SELECT CASE WHEN id < 4394 THEN 'A ids 1-4393' ELSE 'B ids 4394-9073' END s, channel, count(*) n FROM web_events GROUP BY 1,2 ORDER BY 1,3 DESC;
-- name: series_a_event_order_pairing
-- series-A event k of an account vs series-A order k of the same account (by rank within account)
WITH e AS (SELECT account_id, occurred_at et, row_number() OVER (PARTITION BY account_id ORDER BY id) k FROM web_events WHERE id < 4394),
o AS (SELECT account_id, occurred_at ot, row_number() OVER (PARTITION BY account_id ORDER BY id) k FROM web_orders WHERE id < 4307)
SELECT (SELECT count(*) FROM e) ea, (SELECT count(*) FROM o) oa, count(*) paired, sum(et <= ot) event_before, sum(julianday(ot)-julianday(et) BETWEEN 0 AND 1.0/24) within_1h, min(round((julianday(ot)-julianday(et))*1440,1)) min_min, max(round((julianday(ot)-julianday(et))*1440,1)) max_min FROM e JOIN o USING (account_id, k);
-- name: series_a_counts_per_account
WITH e AS (SELECT account_id, count(*) ne FROM web_events WHERE id < 4394 GROUP BY 1), o AS (SELECT account_id, count(*) no FROM web_orders WHERE id < 4307 GROUP BY 1)
SELECT sum(ne = no) eq, sum(ne > no) more_events, sum(ne < no) more_orders, count(*) n FROM e LEFT JOIN o USING(account_id);
-- name: series_a_extra_events
-- the 87 = 4393 - 4306 extra A events: which accounts? (one per account with no A order?)
WITH e AS (SELECT account_id, count(*) ne FROM web_events WHERE id < 4394 GROUP BY 1), o AS (SELECT account_id, count(*) no FROM web_orders WHERE id < 4307 GROUP BY 1)
SELECT ne - coalesce(no,0) diff, count(*) accts FROM e LEFT JOIN o USING(account_id) GROUP BY 1;
-- name: series_a_gap_minutes
WITH e AS (SELECT account_id, occurred_at et, row_number() OVER (PARTITION BY account_id ORDER BY id) k FROM web_events WHERE id < 4394),
o AS (SELECT account_id, occurred_at ot, row_number() OVER (PARTITION BY account_id ORDER BY id) k FROM web_orders WHERE id < 4307)
SELECT CAST((julianday(ot)-julianday(et))*1440/5 AS INT)*5 bucket_min, count(*) n FROM e JOIN o USING (account_id, k) GROUP BY 1 ORDER BY 1 LIMIT 12;
-- name: order_b_vs_a_same_day
-- series-B orders: is each one on the same day as a series-A order of that account?
SELECT sum(EXISTS (SELECT 1 FROM web_orders a WHERE a.id < 4307 AND a.account_id=b.account_id AND substr(a.occurred_at,1,10)=substr(b.occurred_at,1,10))) same_day, count(*) n FROM web_orders b WHERE b.id >= 4307;
-- name: order_b_minus_a_minutes
SELECT CAST(m/10 AS INT)*10 bucket, count(*) n FROM (SELECT b.id, (SELECT min(abs(julianday(b.occurred_at)-julianday(a.occurred_at)))*1440 FROM web_orders a WHERE a.id < 4307 AND a.account_id=b.account_id) m FROM web_orders b WHERE b.id >= 4307) GROUP BY 1 ORDER BY 2 DESC LIMIT 8;
-- name: monthly_day_drift
-- series A: day gap between consecutive orders of an account
SELECT CAST(round(julianday(nt) - julianday(t)) AS INT) gap, count(*) n FROM (SELECT occurred_at t, lead(occurred_at) OVER (PARTITION BY account_id ORDER BY occurred_at) nt FROM web_orders WHERE id < 4307) WHERE nt IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 8;
-- name: series_b_qty_profile
SELECT CASE WHEN id < 4307 THEN 'A' ELSE 'B' END s, round(avg(standard_qty)) std, round(avg(gloss_qty)) gl, round(avg(poster_qty)) po, sum(total=0) zero FROM web_orders GROUP BY 1;
-- name: account_first_event_vs_rep
SELECT min(fe), max(fe) FROM (SELECT account_id, min(occurred_at) fe FROM web_events GROUP BY 1);
-- name: account_lifespan_ends
SELECT substr(lo,1,7) last_month, count(*) accts FROM (SELECT account_id, max(occurred_at) lo FROM web_orders GROUP BY 1) GROUP BY 1 ORDER BY 1 DESC LIMIT 6;
-- name: accounts_start_month
SELECT substr(fe,1,4) y, count(*) accts FROM (SELECT account_id, min(occurred_at) fe FROM web_events GROUP BY 1) GROUP BY 1;
-- name: events_after_last_order
SELECT sum(le > lo) events_after, count(*) n FROM (SELECT account_id, (SELECT max(occurred_at) FROM web_orders o WHERE o.account_id=e.account_id) lo, max(occurred_at) le FROM web_events e GROUP BY 1) WHERE lo IS NOT NULL;
-- name: active_months_contiguous
-- series A: is an account's set of order months a contiguous range of months?
WITH m AS (SELECT DISTINCT account_id, CAST(substr(occurred_at,1,4) AS INT)*12 + CAST(substr(occurred_at,6,2) AS INT) mi FROM web_orders WHERE id < 4307)
SELECT sum(mx - mn + 1 = c) contiguous, count(*) n FROM (SELECT account_id, min(mi) mn, max(mi) mx, count(*) c FROM m GROUP BY 1);
