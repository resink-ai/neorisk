-- Parch & Posey: events → source tables (refdata rebuild, DuckDB). Money is integer cents
-- (standard 499, gloss 749, poster 812) divided by 100 once, as a double.

-- table: web_region
SELECT CAST(ext_id AS BIGINT) AS id, name FROM region;

-- table: web_sales_reps
SELECT CAST(s.ext_id AS BIGINT) AS id, s.name, CAST(r.ext_id AS BIGINT) AS region_id
FROM sales_reps s LEFT JOIN sales_reps_snapshot n USING (rep_key)
LEFT JOIN region r ON r.region_key = n.region_id;

-- table: web_accounts
SELECT CAST(a.ext_id AS BIGINT) AS id, a.name, n.website, n.lat, n.long, n.primary_poc,
       CAST(s.ext_id AS BIGINT) AS sales_rep_id
FROM accounts a LEFT JOIN accounts_snapshot n USING (account_key)
LEFT JOIN sales_reps s ON s.rep_key = n.sales_rep_id;

-- table: web_events
SELECT e.web_event_id AS id, CAST(a.ext_id AS BIGINT) AS account_id,
       strftime(e.event_time AT TIME ZONE 'UTC', '%Y-%m-%dT%H:%M:%S') || '.000Z' AS occurred_at,
       e.channel
FROM web_visited e JOIN accounts a ON a.account_key = e.account_id;

-- table: web_orders
SELECT o.order_id AS id, CAST(a.ext_id AS BIGINT) AS account_id,
       strftime(o.event_time AT TIME ZONE 'UTC', '%Y-%m-%dT%H:%M:%S') || '.000Z' AS occurred_at,
       o.standard_qty, o.gloss_qty, o.poster_qty,
       o.standard_qty + o.gloss_qty + o.poster_qty AS total,
       CAST(o.standard_qty * 499 AS DOUBLE) / 100 AS standard_amt_usd,
       CAST(o.gloss_qty * 749 AS DOUBLE) / 100 AS gloss_amt_usd,
       CAST(o.poster_qty * 812 AS DOUBLE) / 100 AS poster_amt_usd,
       CAST(o.standard_qty * 499 + o.gloss_qty * 749 + o.poster_qty * 812 AS DOUBLE) / 100
           AS total_amt_usd
FROM order_placed o JOIN accounts a ON a.account_key = o.account_id;
