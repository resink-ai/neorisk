-- Parch & Posey: source tables → events (refdata ingest). occurred_at is
-- 'YYYY-MM-DDTHH:MM:SS.000Z' in every row; the source ids ride as ord.

-- entity: region
SELECT CAST(id AS TEXT) AS ext_id, name, '2013-12-04 00:00:00' AS created_at
FROM web_region ORDER BY id;

-- entity: sales_reps
SELECT CAST(id AS TEXT) AS ext_id, name, CAST(region_id AS TEXT) AS region_id,
       '2013-12-04 00:00:00' AS created_at
FROM web_sales_reps ORDER BY id;

-- entity: accounts
-- Created at the account's first web visit (rule); every account has one.
SELECT CAST(a.id AS TEXT) AS ext_id, a.name, a.website, a.lat, a.long, a.primary_poc,
       CAST(a.sales_rep_id AS TEXT) AS sales_rep_id,
       (SELECT replace(substr(min(e.occurred_at), 1, 19), 'T', ' ') FROM web_events e
        WHERE e.account_id = a.id) AS created_at
FROM web_accounts a ORDER BY a.id;

-- event: web_visited owner=account_id ord=web_event_id
SELECT replace(substr(occurred_at, 1, 19), 'T', ' ') AS event_time,
       CAST(account_id AS TEXT) AS account_id, id AS web_event_id, channel
FROM web_events ORDER BY id;

-- event: order_placed owner=account_id ord=order_id
SELECT replace(substr(occurred_at, 1, 19), 'T', ' ') AS event_time,
       CAST(account_id AS TEXT) AS account_id, id AS order_id, standard_qty, gloss_qty,
       poster_qty
FROM web_orders ORDER BY id;
