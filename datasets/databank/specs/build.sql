-- Data Bank: events → source tables (refdata rebuild, DuckDB).

-- table: customer_regions
SELECT CAST(ext_id AS BIGINT) AS region_id, region_name FROM regions;

-- table: customer_nodes
WITH a AS (SELECT customer_id, node_id, event_time FROM account_opened
           UNION ALL
           SELECT customer_id, node_id, event_time FROM node_reassigned),
     b AS (SELECT *, lead(event_time) OVER (PARTITION BY customer_id ORDER BY event_time) AS nxt
           FROM a)
SELECT CAST(c.ext_id AS BIGINT) AS customer_id, CAST(r.ext_id AS BIGINT) AS region_id, b.node_id,
       strftime(b.event_time AT TIME ZONE 'UTC', '%Y-%m-%d') AS start_date,
       coalesce(strftime((b.nxt - INTERVAL 1 DAY) AT TIME ZONE 'UTC', '%Y-%m-%d'), '9999-12-31')
           AS end_date
FROM b JOIN customers c USING (customer_id) JOIN regions r ON r.region_id = c.region_id;

-- table: customer_transactions
SELECT CAST(c.ext_id AS BIGINT) AS customer_id,
       strftime(t.event_time AT TIME ZONE 'UTC', '%Y-%m-%d') AS txn_date,
       CAST(t.txn_type AS VARCHAR) AS txn_type, t.txn_amount // 100 AS txn_amount
FROM transaction_posted t JOIN customers c USING (customer_id);
