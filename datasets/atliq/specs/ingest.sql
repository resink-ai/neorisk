-- AtliQ Hardware: source tables → events (refdata ingest). Fiscal year N starts (N-1)-09-01.
-- Price and deduction blocks come before the sales block, so on a tied time (09-01) the year's
-- price and discount sort before that year's first sales.

-- entity: customers
SELECT CAST(customer_code AS TEXT) AS ext_id, customer, platform, channel, market, sub_zone,
       region, '2019-09-01 00:00:00' AS created_at
FROM hardware_dim_customer ORDER BY customer_code;

-- entity: products
-- Created at the start of the first fiscal year it is priced in; never-priced ones at the
-- catalog start (rule).
SELECT p.product_code AS ext_id, p.division, p.segment, p.category, p.product, p.variant,
       coalesce((SELECT (min(g.fiscal_year) - 1) || '-09-01 00:00:00'
                 FROM hardware_fact_gross_price g WHERE g.product_code = p.product_code),
                '2019-09-01 00:00:00') AS created_at
FROM hardware_dim_product p ORDER BY p.product_code;

-- event: product_priced owner=product_id
-- gross_price and manufacturing_cost share their 579 (product, year) keys.
SELECT (g.fiscal_year - 1) || '-09-01 00:00:00' AS event_time, g.product_code AS product_id,
       g.fiscal_year, CAST(round(g.gross_price * 10000) AS INTEGER) AS gross_price,
       CAST(round(c.manufacturing_cost * 10000) AS INTEGER) AS manufacturing_cost
FROM hardware_fact_gross_price g JOIN hardware_fact_manufacturing_cost c
    ON c.product_code = g.product_code AND c.cost_year = g.fiscal_year
ORDER BY g.product_code, g.fiscal_year;

-- event: customer_deduction_set owner=customer_id
SELECT (fiscal_year - 1) || '-09-01 00:00:00' AS event_time, customer_code AS customer_id,
       fiscal_year, CAST(round(pre_invoice_discount_pct * 10000) AS INTEGER)
           AS pre_invoice_discount_pct
FROM hardware_fact_pre_invoice_deductions ORDER BY customer_code, fiscal_year;

-- event: monthly_sales_reported owner=customer_id
SELECT date || ' 00:00:00' AS event_time, customer_code AS customer_id,
       product_code AS product_id, sold_quantity
FROM hardware_fact_sales_monthly ORDER BY date, product_code, customer_code;
