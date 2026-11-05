-- Parch & Posey: source tables → events (refdata ingest). occurred_at is
-- 'YYYY-MM-DDTHH:MM:SS.000Z' in every row; the source ids ride as ord.
-- Snapshots at N = 2017-01-02 00:02:40, the last order (a rule).

-- entity: region
SELECT CAST(id AS TEXT) AS ext_id, name, '2013-12-04 00:00:00' AS created_at
FROM web_region ORDER BY id;

-- entity: sales_reps
SELECT CAST(id AS TEXT) AS ext_id, name, '2013-12-04 00:00:00' AS created_at
FROM web_sales_reps ORDER BY id;

-- entity: accounts
-- Created at the account's first web visit (rule); every account has one.
SELECT CAST(a.id AS TEXT) AS ext_id, a.name,
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

-- event: sales_reps_snapshot owner=rep_key
SELECT '2017-01-02 00:02:40' AS event_time, CAST(id AS TEXT) AS rep_key,
       CAST(region_id AS TEXT) AS region_id
FROM web_sales_reps ORDER BY id;

-- event: accounts_snapshot owner=account_key
SELECT '2017-01-02 00:02:40' AS event_time, CAST(id AS TEXT) AS account_key, website, lat, long,
       primary_poc, CAST(sales_rep_id AS TEXT) AS sales_rep_id
FROM web_accounts ORDER BY id;
