-- name: accounts_rowid_order
SELECT sum(nxt < cur) desc_pairs, count(*) pairs FROM (SELECT id cur, lead(id) OVER (ORDER BY rowid) nxt FROM web_accounts) WHERE nxt IS NOT NULL;
-- name: accounts_rowid_head
SELECT rowid, id, name, sales_rep_id FROM web_accounts ORDER BY rowid LIMIT 6;
-- name: accounts_sorted_by_name
SELECT sum(nxt < cur) desc_pairs FROM (SELECT name cur, lead(name) OVER (ORDER BY rowid) nxt FROM web_accounts) WHERE nxt IS NOT NULL;
-- name: odd_website
SELECT id, name, website FROM web_accounts WHERE website NOT LIKE 'www.%';
-- name: reps_rows
SELECT rowid, * FROM web_sales_reps LIMIT 5;
-- name: rep_region_of_accounts
-- accounts' lat/long vs their rep's region: longitude by region
SELECT g.name, round(min(a.long),2) mn_long, round(max(a.long),2) mx_long, round(min(a.lat),2) mn_lat, round(max(a.lat),2) mx_lat, count(*) n FROM web_accounts a JOIN web_sales_reps s ON s.id=a.sales_rep_id JOIN web_region g ON g.id=s.region_id GROUP BY 1;
-- name: poc_dups
SELECT primary_poc, count(*) n FROM web_accounts GROUP BY 1 HAVING n > 1 ORDER BY n DESC LIMIT 5;
-- name: amounts_by_region_year
SELECT g.name, substr(o.occurred_at,1,4) y, count(*) n FROM web_orders o JOIN web_accounts a ON a.id=o.account_id JOIN web_sales_reps s ON s.id=a.sales_rep_id JOIN web_region g ON g.id=s.region_id GROUP BY 1,2 ORDER BY 1,2;
-- name: channel_by_year
SELECT substr(occurred_at,1,4) y, channel, count(*) n FROM web_events GROUP BY 1,2 ORDER BY 1,2;
-- name: weekday_mix
SELECT 'orders' t, strftime('%w', occurred_at) dow, count(*) n FROM web_orders GROUP BY 2 UNION ALL SELECT 'events', strftime('%w', occurred_at), count(*) FROM web_events GROUP BY 2 ORDER BY 1,2;
-- name: event_gaps_hours
SELECT CASE WHEN g < 1 THEN '<1h' WHEN g < 24 THEN '1-24h' WHEN g < 24*7 THEN '1-7d' WHEN g < 24*31 THEN '7-31d' ELSE '>31d' END b, count(*) n FROM (SELECT (julianday(lead(occurred_at) OVER (PARTITION BY account_id ORDER BY occurred_at)) - julianday(occurred_at))*24 g FROM web_events) WHERE g IS NOT NULL GROUP BY 1;
-- name: orders_with_zero_part
SELECT sum(standard_qty>0 AND gloss_qty>0 AND poster_qty>0) all3, sum((standard_qty>0)+(gloss_qty>0)+(poster_qty>0) = 2) two, sum((standard_qty>0)+(gloss_qty>0)+(poster_qty>0) = 1) one, sum(total = 0) none FROM web_orders;
