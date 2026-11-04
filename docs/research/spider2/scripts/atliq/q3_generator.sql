-- name: months_active_per_customer
SELECT m, count(*) customers FROM (SELECT customer_code, count(DISTINCT date) m FROM hardware_fact_sales_monthly GROUP BY 1) GROUP BY 1;
-- name: customer_missing_month_patterns
-- for each customer: which calendar months (MM) are absent, as a set, across both fiscal years
WITH act AS (SELECT DISTINCT customer_code, date FROM hardware_fact_sales_monthly),
months AS (SELECT DISTINCT date FROM hardware_fact_sales_monthly),
miss AS (SELECT c.customer_code, m.date FROM hardware_dim_customer c CROSS JOIN months m WHERE NOT EXISTS (SELECT 1 FROM act a WHERE a.customer_code=c.customer_code AND a.date=m.date)),
pat AS (SELECT customer_code, group_concat(date, ',') p FROM (SELECT * FROM miss ORDER BY customer_code, date) GROUP BY 1)
SELECT p, count(*) customers FROM pat GROUP BY p ORDER BY customers DESC LIMIT 20;
-- name: missing_months_same_both_years
WITH act AS (SELECT DISTINCT customer_code, substr(date,6,2) mm, fiscal_year FROM hardware_fact_sales_monthly),
s AS (SELECT customer_code, fiscal_year, group_concat(mm) ms FROM (SELECT * FROM act ORDER BY customer_code, fiscal_year, mm) GROUP BY 1,2)
SELECT sum(a.ms = b.ms) same, count(*) n FROM s a JOIN s b ON a.customer_code=b.customer_code AND a.fiscal_year=2020 AND b.fiscal_year=2021;
-- name: pair_months_vs_customer_months
-- does every (product, customer, fy) row set equal a subset of the customer's active months? (always true) and how many pairs cover all of them
WITH cm AS (SELECT customer_code, fiscal_year, count(DISTINCT date) cmonths FROM hardware_fact_sales_monthly GROUP BY 1,2),
pm AS (SELECT product_code, customer_code, fiscal_year, count(*) pmonths FROM hardware_fact_sales_monthly GROUP BY 1,2,3)
SELECT sum(pmonths = cmonths) full_, sum(pmonths < cmonths) partial, count(*) n, max(cmonths) maxc FROM pm JOIN cm USING (customer_code, fiscal_year);
-- name: product_first_month
SELECT first, count(*) products FROM (SELECT product_code, min(date) first FROM hardware_fact_sales_monthly GROUP BY 1) GROUP BY 1 ORDER BY 1;
-- name: product_last_month
SELECT last, count(*) products FROM (SELECT product_code, max(date) last FROM hardware_fact_sales_monthly GROUP BY 1) GROUP BY 1 ORDER BY 1;
-- name: code_year_digits_vs_first_fy
SELECT substr(p.product_code,4,2) yy, f.ffy, count(*) n FROM hardware_dim_product p LEFT JOIN (SELECT product_code, min(fiscal_year) ffy FROM hardware_fact_sales_monthly GROUP BY 1) f USING (product_code) GROUP BY 1,2 ORDER BY 1,2;
-- name: code_digits67_vs_division
SELECT substr(product_code,6,2) d67, division, count(*) n FROM hardware_dim_product GROUP BY 1,2;
-- name: code_digits89_vs_segment
SELECT substr(product_code,8,2) d89, segment, count(*) n FROM hardware_dim_product GROUP BY 1,2 ORDER BY 1 LIMIT 40;
-- name: code_prefix_vs_channel
SELECT substr(customer_code,1,1) p, channel, count(*) n FROM hardware_dim_customer GROUP BY 1,2;
-- name: code_market_digits
SELECT substr(customer_code,2,4) mk, count(DISTINCT market) markets, group_concat(DISTINCT market) m, count(*) n FROM hardware_dim_customer GROUP BY 1 ORDER BY 1;
-- name: amazon_trailing_space
SELECT customer, length(customer) len, count(*) n FROM hardware_dim_customer WHERE customer LIKE 'Amazon%' GROUP BY 1,2;
-- name: whitespace
SELECT 'cust' t, count(*) n FROM hardware_dim_customer WHERE customer <> trim(customer) OR market <> trim(market) UNION ALL
SELECT 'prod', count(*) FROM hardware_dim_product WHERE product <> trim(product) OR variant <> trim(variant) OR category <> trim(category);
-- name: non_ascii_product
SELECT count(*) n, sum(product LIKE '%–%') endash FROM hardware_dim_product WHERE product GLOB '*[^ -~]*';
-- name: non_ascii_customer
SELECT customer, hex(customer) FROM hardware_dim_customer WHERE customer GLOB '*[^ -~]*' GROUP BY 1;
-- name: typos
SELECT DISTINCT market FROM hardware_dim_customer WHERE market IN ('Philiphines','Newzealand','Columbia');
-- name: qty_by_division_month
SELECT p.division, s.fiscal_year, sum(sold_quantity) qty, count(*) rows_ FROM hardware_fact_sales_monthly s JOIN hardware_dim_product p USING(product_code) GROUP BY 1,2;
-- name: qty_quantiles
WITH r AS (SELECT sold_quantity q, row_number() OVER (ORDER BY sold_quantity) rn, count(*) OVER () n FROM hardware_fact_sales_monthly)
SELECT max(CASE WHEN rn <= n*0.05 THEN q END) p05, max(CASE WHEN rn <= n*0.25 THEN q END) p25, max(CASE WHEN rn <= n*0.5 THEN q END) p50, max(CASE WHEN rn <= n*0.75 THEN q END) p75, max(CASE WHEN rn <= n*0.9 THEN q END) p90, max(CASE WHEN rn <= n*0.99 THEN q END) p99, max(q) mx FROM r;
-- name: qty_by_channel
SELECT c.channel, c.platform, count(*) rows_, sum(sold_quantity) qty, avg(sold_quantity) av FROM hardware_fact_sales_monthly s JOIN hardware_dim_customer c USING(customer_code) GROUP BY 1,2;
-- name: qty_by_segment
SELECT p.segment, count(*) rows_, sum(sold_quantity) qty, avg(sold_quantity) av FROM hardware_fact_sales_monthly s JOIN hardware_dim_product p USING(product_code) GROUP BY 1 ORDER BY 3 DESC;
-- name: seasonality_index
SELECT substr(date,6,2) mm, sum(sold_quantity) qty, round(avg(sold_quantity),2) av_per_row FROM hardware_fact_sales_monthly GROUP BY 1 ORDER BY 1;
-- name: gold_local058
WITH a AS (SELECT dp.segment, COUNT(DISTINCT fsm.product_code) u20 FROM hardware_fact_sales_monthly fsm JOIN hardware_dim_product dp ON fsm.product_code = dp.product_code WHERE fsm.fiscal_year = 2020 GROUP BY 1),
b AS (SELECT dp.segment, COUNT(DISTINCT fsm.product_code) u21 FROM hardware_fact_sales_monthly fsm JOIN hardware_dim_product dp ON fsm.product_code = dp.product_code WHERE fsm.fiscal_year = 2021 GROUP BY 1)
SELECT a.segment, a.u20 AS unique_product_count_2020, b.u21, round((b.u21 - a.u20) * 100.0 / a.u20, 2) pct FROM a JOIN b USING(segment) ORDER BY (b.u21 - a.u20) * 100.0 / a.u20 DESC;
-- name: gold_local059
-- calendar 2021 (date LIKE '2021%'), top 3 products by total qty per division, mean of their totals
WITH t AS (SELECT p.division, s.product_code, sum(s.sold_quantity) q FROM hardware_fact_sales_monthly s JOIN hardware_dim_product p USING(product_code) WHERE substr(s.date,1,4)='2021' GROUP BY 1,2),
r AS (SELECT *, row_number() OVER (PARTITION BY division ORDER BY q DESC) rk FROM t)
SELECT division, printf('%.6f', avg(q)) overall_avg_quantity_sold FROM r WHERE rk <= 3 GROUP BY 1 ORDER BY 1;
-- name: gold_local059_fiscal_variant
WITH t AS (SELECT p.division, s.product_code, sum(s.sold_quantity) q FROM hardware_fact_sales_monthly s JOIN hardware_dim_product p USING(product_code) WHERE s.fiscal_year=2021 GROUP BY 1,2),
r AS (SELECT *, row_number() OVER (PARTITION BY division ORDER BY q DESC) rk FROM t)
SELECT division, printf('%.6f', avg(q)) avg_fy2021 FROM r WHERE rk <= 3 GROUP BY 1 ORDER BY 1;
