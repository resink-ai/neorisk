-- name: row_counts
SELECT 'web_accounts' t, count(*) n FROM web_accounts UNION ALL SELECT 'web_events', count(*) FROM web_events UNION ALL
SELECT 'web_orders', count(*) FROM web_orders UNION ALL SELECT 'web_region', count(*) FROM web_region UNION ALL SELECT 'web_sales_reps', count(*) FROM web_sales_reps;
-- name: typeof_columns
SELECT 'orders.occurred_at' c, typeof(occurred_at) ty, count(*) n FROM web_orders GROUP BY 2 UNION ALL
SELECT 'orders.standard_amt_usd', typeof(standard_amt_usd), count(*) FROM web_orders GROUP BY 2 UNION ALL
SELECT 'orders.gloss_amt_usd', typeof(gloss_amt_usd), count(*) FROM web_orders GROUP BY 2 UNION ALL
SELECT 'orders.poster_amt_usd', typeof(poster_amt_usd), count(*) FROM web_orders GROUP BY 2 UNION ALL
SELECT 'orders.total_amt_usd', typeof(total_amt_usd), count(*) FROM web_orders GROUP BY 2 UNION ALL
SELECT 'orders.total', typeof(total), count(*) FROM web_orders GROUP BY 2 UNION ALL
SELECT 'events.occurred_at', typeof(occurred_at), count(*) FROM web_events GROUP BY 2 UNION ALL
SELECT 'accounts.lat', typeof(lat), count(*) FROM web_accounts GROUP BY 2 UNION ALL
SELECT 'accounts.long', typeof(long), count(*) FROM web_accounts GROUP BY 2;
-- name: nulls_empty
SELECT 'accounts' t, sum(name IS NULL)+sum(website IS NULL)+sum(lat IS NULL)+sum(long IS NULL)+sum(primary_poc IS NULL)+sum(sales_rep_id IS NULL) nulls, sum(name='')+sum(website='')+sum(primary_poc='') empties FROM web_accounts UNION ALL
SELECT 'orders', sum(occurred_at IS NULL)+sum(account_id IS NULL)+sum(standard_qty IS NULL)+sum(gloss_qty IS NULL)+sum(poster_qty IS NULL)+sum(total IS NULL)+sum(total_amt_usd IS NULL), sum(occurred_at='') FROM web_orders UNION ALL
SELECT 'events', sum(occurred_at IS NULL)+sum(account_id IS NULL)+sum(channel IS NULL), sum(channel='') FROM web_events UNION ALL
SELECT 'reps', sum(name IS NULL)+sum(region_id IS NULL), sum(name='') FROM web_sales_reps;
-- name: key_uniqueness
SELECT 'accounts.id' k, count(*)-count(DISTINCT id) dups, min(id), max(id) FROM web_accounts UNION ALL
SELECT 'orders.id', count(*)-count(DISTINCT id), min(id), max(id) FROM web_orders UNION ALL
SELECT 'events.id', count(*)-count(DISTINCT id), min(id), max(id) FROM web_events UNION ALL
SELECT 'reps.id', count(*)-count(DISTINCT id), min(id), max(id) FROM web_sales_reps UNION ALL
SELECT 'region.id', count(*)-count(DISTINCT id), min(id), max(id) FROM web_region UNION ALL
SELECT 'accounts.name', count(*)-count(DISTINCT name), NULL, NULL FROM web_accounts UNION ALL
SELECT 'reps.name', count(*)-count(DISTINCT name), NULL, NULL FROM web_sales_reps;
-- name: dense_ids
SELECT 'orders' t, max(id)-min(id)+1 = count(*) dense FROM web_orders UNION ALL SELECT 'events', max(id)-min(id)+1 = count(*) FROM web_events UNION ALL
SELECT 'reps', max(id)-min(id)+1 = count(*) FROM web_sales_reps UNION ALL SELECT 'accounts', (max(id)-min(id))/10+1 = count(*) FROM web_accounts;
-- name: account_id_step
SELECT DISTINCT id % 10 r FROM web_accounts;
-- name: fk_orphans
SELECT 'orders.account_id' j, sum(a.id IS NULL) orphans, count(*) n FROM web_orders o LEFT JOIN web_accounts a ON a.id=o.account_id UNION ALL
SELECT 'events.account_id', sum(a.id IS NULL), count(*) FROM web_events o LEFT JOIN web_accounts a ON a.id=o.account_id UNION ALL
SELECT 'accounts.sales_rep_id', sum(r.id IS NULL), count(*) FROM web_accounts a LEFT JOIN web_sales_reps r ON r.id=a.sales_rep_id UNION ALL
SELECT 'reps.region_id', sum(g.id IS NULL), count(*) FROM web_sales_reps r LEFT JOIN web_region g ON g.id=r.region_id;
-- name: parents_without_children
SELECT 'accounts w/o orders' w, count(*) n FROM web_accounts WHERE id NOT IN (SELECT account_id FROM web_orders) UNION ALL
SELECT 'accounts w/o events', count(*) FROM web_accounts WHERE id NOT IN (SELECT account_id FROM web_events) UNION ALL
SELECT 'accounts w/o either', count(*) FROM web_accounts WHERE id NOT IN (SELECT account_id FROM web_events) AND id NOT IN (SELECT account_id FROM web_orders) UNION ALL
SELECT 'reps w/o accounts', count(*) FROM web_sales_reps WHERE id NOT IN (SELECT sales_rep_id FROM web_accounts) UNION ALL
SELECT 'regions w/o reps', count(*) FROM web_region WHERE id NOT IN (SELECT region_id FROM web_sales_reps);
-- name: account_wo_orders_rows
SELECT * FROM web_accounts WHERE id NOT IN (SELECT account_id FROM web_orders);
-- name: region_rows
SELECT * FROM web_region;
-- name: reps_per_region
SELECT region_id, count(*) reps FROM web_sales_reps GROUP BY 1;
-- name: time_formats
SELECT 'orders' t, length(occurred_at) len, substr(occurred_at,11,1) sep, count(*) n, min(occurred_at), max(occurred_at) FROM web_orders GROUP BY 2,3 UNION ALL
SELECT 'events', length(occurred_at), substr(occurred_at,11,1), count(*), min(occurred_at), max(occurred_at) FROM web_events GROUP BY 2,3;
-- name: time_parse
SELECT 'orders' t, sum(datetime(occurred_at) IS NULL) unparsable, sum(datetime(occurred_at) <> occurred_at) not_canonical FROM web_orders UNION ALL
SELECT 'events', sum(datetime(occurred_at) IS NULL), sum(datetime(occurred_at) <> occurred_at) FROM web_events;
-- name: time_samples
SELECT occurred_at FROM web_orders LIMIT 3;
-- name: rowid_vs_id
SELECT 'orders' t, sum(rowid <> id) mism FROM web_orders UNION ALL SELECT 'events', sum(rowid <> id) FROM web_events UNION ALL SELECT 'accounts', sum(rowid*10+990 <> id) FROM web_accounts;
-- name: id_vs_time_order
SELECT 'orders' t, sum(nxt < cur) desc_pairs, count(*) pairs FROM (SELECT occurred_at cur, lead(occurred_at) OVER (ORDER BY id) nxt FROM web_orders) WHERE nxt IS NOT NULL UNION ALL
SELECT 'events', sum(nxt < cur), count(*) FROM (SELECT occurred_at cur, lead(occurred_at) OVER (ORDER BY id) nxt FROM web_events) WHERE nxt IS NOT NULL;
-- name: id_order_by_account
SELECT 'orders sorted by (account,time)' t, sum(nk < ck) desc_pairs FROM (SELECT printf('%06d', account_id)||occurred_at ck, lead(printf('%06d', account_id)||occurred_at) OVER (ORDER BY id) nk FROM web_orders) UNION ALL
SELECT 'events sorted by (account,time)', sum(nk < ck) FROM (SELECT printf('%06d', account_id)||occurred_at ck, lead(printf('%06d', account_id)||occurred_at) OVER (ORDER BY id) nk FROM web_events);
-- name: dup_rows
SELECT 'orders (account,time)' k, count(*) - (SELECT count(*) FROM (SELECT DISTINCT account_id, occurred_at FROM web_orders)) d FROM web_orders UNION ALL
SELECT 'events (account,time,channel)', count(*) - (SELECT count(*) FROM (SELECT DISTINCT account_id, occurred_at, channel FROM web_events)) FROM web_events UNION ALL
SELECT 'events (account,time)', count(*) - (SELECT count(*) FROM (SELECT DISTINCT account_id, occurred_at FROM web_events)) FROM web_events;
