-- name: product_whitespace_rows
SELECT product_code, '['||product||']' product, '['||variant||']' variant, '['||category||']' category FROM hardware_dim_product WHERE product <> trim(product) OR variant <> trim(variant) OR category <> trim(category);
-- name: missing_month_group_rule
-- group g = the calendar month index (months since 2019-09) mod 4 that a customer lacks; compare with rowid and code
WITH act AS (SELECT DISTINCT customer_code, date FROM hardware_fact_sales_monthly),
g AS (SELECT c.rowid rid, c.customer_code, (SELECT min((CAST(substr(m.date,1,4) AS INT)*12 + CAST(substr(m.date,6,2) AS INT) - (2019*12+9)) % 4) FROM (SELECT DISTINCT date FROM hardware_fact_sales_monthly) m WHERE NOT EXISTS (SELECT 1 FROM act a WHERE a.customer_code=c.customer_code AND a.date=m.date)) grp FROM hardware_dim_customer c)
SELECT 'grp = (rowid-1) % 4' rule_, sum(grp = (rid-1) % 4) ok, count(*) n FROM g UNION ALL
SELECT 'grp = customer_code % 4', sum(grp = customer_code % 4), count(*) FROM g UNION ALL
SELECT 'grp = (rank by code -1) % 4', sum(grp = (rk-1) % 4), count(*) FROM (SELECT g.*, rank() OVER (ORDER BY customer_code) rk FROM g);
-- name: missing_group_sizes_by_channel
WITH act AS (SELECT DISTINCT customer_code, date FROM hardware_fact_sales_monthly)
SELECT c.channel, sum(NOT EXISTS (SELECT 1 FROM act a WHERE a.customer_code=c.customer_code AND a.date='2019-09-01')) miss_sep, count(*) n FROM hardware_dim_customer c GROUP BY 1;
-- name: products_full_year
-- product active months per fiscal year it is sold
SELECT fiscal_year, m, count(*) products FROM (SELECT product_code, fiscal_year, count(DISTINCT date) m FROM hardware_fact_sales_monthly GROUP BY 1,2) GROUP BY 1,2 ORDER BY 1,2;
-- name: customers_per_product_month
SELECT fiscal_year, min(c) mn, avg(c) av, max(c) mx FROM (SELECT product_code, date, fiscal_year, count(*) c FROM hardware_fact_sales_monthly GROUP BY 1,2,3) GROUP BY 1;
-- name: price_rows_order_by_variant
-- gross price rises with the variant's sequence within a 9-char product prefix?
WITH g AS (SELECT substr(product_code,1,9) pre, product_code, fiscal_year, gross_price, lag(gross_price) OVER (PARTITION BY substr(product_code,1,9), fiscal_year ORDER BY product_code) prev FROM hardware_fact_gross_price)
SELECT sum(gross_price > prev) up, sum(gross_price < prev) down, sum(prev IS NOT NULL) pairs FROM g;
-- name: sales_cust_rank_vs_qty
SELECT c.platform, c.channel, round(avg(d.pre_invoice_discount_pct),4) avg_ded FROM hardware_dim_customer c JOIN hardware_fact_pre_invoice_deductions d USING(customer_code) GROUP BY 1,2;
-- name: monthly_rows_cv
SELECT fiscal_year, min(n) mn, max(n) mx FROM (SELECT date, fiscal_year, count(*) n FROM hardware_fact_sales_monthly GROUP BY 1,2) WHERE date <> '2020-03-01' GROUP BY 1;
