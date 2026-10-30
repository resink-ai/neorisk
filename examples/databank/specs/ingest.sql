-- Data Bank: source tables → events (refdata ingest). Dates are read as midnight UTC.

-- entity: regions
SELECT CAST(region_id AS TEXT) AS ext_id, region_name FROM customer_regions ORDER BY region_id;

-- entity: customers
SELECT CAST(customer_id AS TEXT) AS ext_id, CAST(MIN(region_id) AS TEXT) AS region_id,
       MIN(start_date) || ' 00:00:00' AS created_at
FROM customer_nodes GROUP BY customer_id ORDER BY customer_id;

-- event: account_opened owner=customer_id
SELECT start_date || ' 00:00:00' AS event_time, CAST(customer_id AS TEXT) AS customer_id, node_id
FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY start_date) AS k
      FROM customer_nodes)
WHERE k = 1 ORDER BY customer_id;

-- event: node_reassigned owner=customer_id
SELECT start_date || ' 00:00:00' AS event_time, CAST(customer_id AS TEXT) AS customer_id, node_id
FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY start_date) AS k
      FROM customer_nodes)
WHERE k > 1 ORDER BY customer_id, start_date;

-- event: transaction_posted owner=customer_id ord=src_rowid
SELECT txn_date || ' 00:00:00' AS event_time, CAST(customer_id AS TEXT) AS customer_id, txn_type,
       txn_amount * 100 AS txn_amount, rowid AS src_rowid
FROM customer_transactions ORDER BY rowid;
