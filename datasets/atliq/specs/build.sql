-- AtliQ Hardware: events → source tables (refdata rebuild, DuckDB). Integers of 1e-4 units are
-- divided as doubles; a sale's fiscal_year is its calendar year, plus one from September.

-- table: hardware_dim_customer
SELECT CAST(ext_id AS BIGINT) AS customer_code, customer, platform, channel, market, sub_zone,
       region
FROM customers;

-- table: hardware_dim_product
SELECT ext_id AS product_code, division, segment, category, product, variant FROM products;

-- table: hardware_fact_gross_price
SELECT p.ext_id AS product_code, e.fiscal_year, CAST(e.gross_price AS DOUBLE) / 10000
           AS gross_price
FROM product_priced e JOIN products p ON p.product_key = e.product_id;

-- table: hardware_fact_manufacturing_cost
SELECT p.ext_id AS product_code, e.fiscal_year AS cost_year,
       CAST(e.manufacturing_cost AS DOUBLE) / 10000 AS manufacturing_cost
FROM product_priced e JOIN products p ON p.product_key = e.product_id;

-- table: hardware_fact_pre_invoice_deductions
SELECT CAST(c.ext_id AS BIGINT) AS customer_code, e.fiscal_year,
       CAST(e.pre_invoice_discount_pct AS DOUBLE) / 10000 AS pre_invoice_discount_pct
FROM customer_deduction_set e JOIN customers c ON c.customer_key = e.customer_id;

-- table: hardware_fact_sales_monthly
SELECT strftime(e.event_time AT TIME ZONE 'UTC', '%Y-%m-%d') AS date, p.ext_id AS product_code,
       CAST(c.ext_id AS BIGINT) AS customer_code, e.sold_quantity,
       CAST(strftime(e.event_time AT TIME ZONE 'UTC', '%Y') AS BIGINT)
           + CASE WHEN CAST(strftime(e.event_time AT TIME ZONE 'UTC', '%m') AS INTEGER) >= 9
                  THEN 1 ELSE 0 END AS fiscal_year
FROM monthly_sales_reported e JOIN products p ON p.product_key = e.product_id
    JOIN customers c ON c.customer_key = e.customer_id;
