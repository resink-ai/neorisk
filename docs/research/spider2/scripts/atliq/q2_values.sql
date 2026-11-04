-- name: rowid_order_product_date_cust
SELECT sum(nxt < cur) desc_pairs, count(*) pairs FROM (SELECT product_code||'|'||date||'|'||printf('%012d',customer_code) cur, lead(product_code||'|'||date||'|'||printf('%012d',customer_code)) OVER (ORDER BY rowid) nxt FROM hardware_fact_sales_monthly) WHERE nxt IS NOT NULL;
-- name: rowid_order_date_product_cust
SELECT sum(nxt < cur) desc_pairs, count(*) pairs FROM (SELECT date||'|'||product_code||'|'||printf('%012d',customer_code) cur, lead(date||'|'||product_code||'|'||printf('%012d',customer_code)) OVER (ORDER BY rowid) nxt FROM hardware_fact_sales_monthly) WHERE nxt IS NOT NULL;
-- name: rowid_descents_sample
SELECT * FROM (SELECT rowid r, date, product_code, customer_code, lag(date) OVER (ORDER BY rowid) pdate, lag(product_code) OVER (ORDER BY rowid) pprod FROM hardware_fact_sales_monthly) WHERE date < pdate LIMIT 8;
-- name: rowid_product_blocks
-- how many maximal runs of the same product_code in rowid order
SELECT count(*) runs, count(DISTINCT product_code) prods FROM (SELECT product_code, lag(product_code) OVER (ORDER BY rowid) p FROM hardware_fact_sales_monthly) WHERE p IS NULL OR p <> product_code;
-- name: rowid_customer_within_block_desc
SELECT sum(nc < cc) desc_cust FROM (SELECT customer_code cc, date d, product_code pc, lead(customer_code) OVER (ORDER BY rowid) nc, lead(date) OVER (ORDER BY rowid) nd, lead(product_code) OVER (ORDER BY rowid) np FROM hardware_fact_sales_monthly) WHERE nd = d AND np = pc;
-- name: customer_null_columns
SELECT sum(customer IS NULL) customer, sum(platform IS NULL) platform, sum(channel IS NULL) channel, sum(market IS NULL) market, sum(sub_zone IS NULL) sub_zone, sum(region IS NULL) region FROM hardware_dim_customer;
-- name: customer_null_rows
SELECT * FROM hardware_dim_customer WHERE sub_zone IS NULL OR region IS NULL OR market IS NULL LIMIT 10;
-- name: customer_head
SELECT rowid, * FROM hardware_dim_customer LIMIT 8;
-- name: product_head
SELECT rowid, * FROM hardware_dim_product LIMIT 8;
-- name: customer_mix
SELECT region, sub_zone, channel, platform, count(*) n FROM hardware_dim_customer GROUP BY 1,2,3,4 ORDER BY 1,2,3,4;
-- name: customer_names
SELECT count(DISTINCT customer) names, count(DISTINCT market) markets, count(DISTINCT customer||'|'||market) name_market, count(DISTINCT customer||'|'||market||'|'||channel||'|'||platform) nmcp FROM hardware_dim_customer;
-- name: customer_code_structure
SELECT substr(customer_code,1,2) p2, count(*) n, min(customer_code), max(customer_code) FROM hardware_dim_customer GROUP BY 1;
-- name: customer_code_vs_market
SELECT market, count(*) n, min(customer_code) lo, max(customer_code) hi, group_concat(customer||'/'||channel||'/'||platform, '; ') who FROM hardware_dim_customer GROUP BY market ORDER BY lo LIMIT 30;
-- name: customers_buying_per_month
SELECT count(DISTINCT customer_code) ever FROM hardware_fact_sales_monthly;
-- name: product_mix
SELECT division, segment, category, count(*) n FROM hardware_dim_product GROUP BY 1,2,3 ORDER BY 1,2,3;
-- name: product_code_structure
SELECT length(product_code) len, substr(product_code,1,1) c1, count(*) n FROM hardware_dim_product GROUP BY 1,2;
-- name: product_variant_mix
SELECT variant, count(*) n FROM hardware_dim_product GROUP BY 1 ORDER BY 2 DESC LIMIT 20;
-- name: product_code_prefix_vs_product
SELECT count(DISTINCT substr(product_code,1,9)) prefix9, count(DISTINCT product) products, count(DISTINCT substr(product_code,1,9)||product) both_ FROM hardware_dim_product;
-- name: unsold_products
SELECT p.* FROM hardware_dim_product p WHERE product_code NOT IN (SELECT product_code FROM hardware_fact_sales_monthly) LIMIT 10;
-- name: unsold_vs_priced
SELECT (SELECT count(*) FROM hardware_dim_product WHERE product_code NOT IN (SELECT product_code FROM hardware_fact_sales_monthly) AND product_code NOT IN (SELECT product_code FROM hardware_fact_gross_price)) unsold_and_unpriced;
-- name: products_by_year_sold
SELECT fy, count(*) n FROM (SELECT product_code, group_concat(DISTINCT fiscal_year) fy FROM (SELECT DISTINCT product_code, fiscal_year FROM hardware_fact_sales_monthly ORDER BY 1,2) GROUP BY 1) GROUP BY 1;
-- name: products_priced_by_year
SELECT fy, count(*) n FROM (SELECT product_code, group_concat(fiscal_year) fy FROM (SELECT product_code, fiscal_year FROM hardware_fact_gross_price ORDER BY 1,2) GROUP BY 1) GROUP BY 1;
-- name: qty_stats
SELECT min(sold_quantity) mn, max(sold_quantity) mx, avg(sold_quantity) av, sum(sold_quantity=0) zeros, sum(sold_quantity<0) negs, sum(sold_quantity) total FROM hardware_fact_sales_monthly;
-- name: cube_density
-- rows vs product x customer pairs active in a fiscal year x 12 months
SELECT s.fiscal_year, count(*) rows_, (SELECT count(*) FROM (SELECT DISTINCT product_code, customer_code FROM hardware_fact_sales_monthly x WHERE x.fiscal_year=s.fiscal_year)) pairs FROM hardware_fact_sales_monthly s GROUP BY 1;
-- name: months_per_pair
SELECT m, count(*) pairs FROM (SELECT product_code, customer_code, fiscal_year, count(*) m FROM hardware_fact_sales_monthly GROUP BY 1,2,3) GROUP BY 1 ORDER BY 1;
-- name: price_decimals
SELECT 'gp' t, sum(round(gross_price,4)=gross_price) dp4, sum(round(gross_price,2)=gross_price) dp2, min(gross_price), max(gross_price) FROM hardware_fact_gross_price UNION ALL
SELECT 'mc', sum(round(manufacturing_cost,4)=manufacturing_cost), sum(round(manufacturing_cost,2)=manufacturing_cost), min(manufacturing_cost), max(manufacturing_cost) FROM hardware_fact_manufacturing_cost UNION ALL
SELECT 'ded', sum(round(pre_invoice_discount_pct,4)=pre_invoice_discount_pct), sum(round(pre_invoice_discount_pct,2)=pre_invoice_discount_pct), min(pre_invoice_discount_pct), max(pre_invoice_discount_pct) FROM hardware_fact_pre_invoice_deductions;
-- name: price_text_samples
SELECT product_code, fiscal_year, gross_price, CAST(gross_price AS TEXT) t FROM hardware_fact_gross_price LIMIT 6;
-- name: cost_text_samples
SELECT product_code, cost_year, manufacturing_cost, CAST(manufacturing_cost AS TEXT) t FROM hardware_fact_manufacturing_cost LIMIT 6;
-- name: ded_text_samples
SELECT customer_code, fiscal_year, pre_invoice_discount_pct, CAST(pre_invoice_discount_pct AS TEXT) t FROM hardware_fact_pre_invoice_deductions LIMIT 6;
-- name: price_change_2020_2021
SELECT count(*) n, avg(b.gross_price/a.gross_price) ratio_avg, min(b.gross_price/a.gross_price) mn, max(b.gross_price/a.gross_price) mx FROM hardware_fact_gross_price a JOIN hardware_fact_gross_price b ON a.product_code=b.product_code AND a.fiscal_year=2020 AND b.fiscal_year=2021;
-- name: cost_change_2020_2021
SELECT count(*) n, avg(b.manufacturing_cost/a.manufacturing_cost) ratio_avg, min(b.manufacturing_cost/a.manufacturing_cost) mn, max(b.manufacturing_cost/a.manufacturing_cost) mx FROM hardware_fact_manufacturing_cost a JOIN hardware_fact_manufacturing_cost b ON a.product_code=b.product_code AND a.cost_year=2020 AND b.cost_year=2021;
-- name: margin
SELECT min(m.manufacturing_cost/g.gross_price) mn, avg(m.manufacturing_cost/g.gross_price) av, max(m.manufacturing_cost/g.gross_price) mx FROM hardware_fact_gross_price g JOIN hardware_fact_manufacturing_cost m ON m.product_code=g.product_code AND m.cost_year=g.fiscal_year;
-- name: ded_stats
SELECT fiscal_year, min(pre_invoice_discount_pct), avg(pre_invoice_discount_pct), max(pre_invoice_discount_pct) FROM hardware_fact_pre_invoice_deductions GROUP BY 1;
-- name: ded_year_corr
SELECT count(*) n, avg(b.pre_invoice_discount_pct - a.pre_invoice_discount_pct) d_avg, min(b.pre_invoice_discount_pct - a.pre_invoice_discount_pct) mn, max(b.pre_invoice_discount_pct - a.pre_invoice_discount_pct) mx FROM hardware_fact_pre_invoice_deductions a JOIN hardware_fact_pre_invoice_deductions b ON a.customer_code=b.customer_code AND a.fiscal_year=2020 AND b.fiscal_year=2021;
-- name: march_2020_missing_products
SELECT p.product_code, p.segment, p.product FROM hardware_dim_product p WHERE product_code IN (SELECT product_code FROM hardware_fact_sales_monthly WHERE fiscal_year=2020) AND product_code NOT IN (SELECT product_code FROM hardware_fact_sales_monthly WHERE date='2020-03-01');
-- name: customers_per_month_missing
SELECT date, (SELECT count(DISTINCT customer_code) FROM hardware_fact_sales_monthly) - count(DISTINCT customer_code) missing FROM hardware_fact_sales_monthly GROUP BY 1 ORDER BY 1 LIMIT 4;
-- name: customer_inactive_months
SELECT c.customer_code, c.customer, c.market, count(DISTINCT s.date) months FROM hardware_dim_customer c JOIN hardware_fact_sales_monthly s USING(customer_code) GROUP BY 1 HAVING months < 24 ORDER BY months LIMIT 20;
