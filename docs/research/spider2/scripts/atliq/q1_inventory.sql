-- name: row_counts
SELECT 'dim_customer' t, count(*) n FROM hardware_dim_customer UNION ALL
SELECT 'dim_product', count(*) FROM hardware_dim_product UNION ALL
SELECT 'fact_gross_price', count(*) FROM hardware_fact_gross_price UNION ALL
SELECT 'fact_manufacturing_cost', count(*) FROM hardware_fact_manufacturing_cost UNION ALL
SELECT 'fact_pre_invoice_deductions', count(*) FROM hardware_fact_pre_invoice_deductions UNION ALL
SELECT 'fact_sales_monthly', count(*) FROM hardware_fact_sales_monthly;
-- name: typeof_columns
SELECT 'cust.customer_code' c, typeof(customer_code) ty, count(*) n FROM hardware_dim_customer GROUP BY 2 UNION ALL
SELECT 'prod.product_code', typeof(product_code), count(*) FROM hardware_dim_product GROUP BY 2 UNION ALL
SELECT 'gp.gross_price', typeof(gross_price), count(*) FROM hardware_fact_gross_price GROUP BY 2 UNION ALL
SELECT 'mc.manufacturing_cost', typeof(manufacturing_cost), count(*) FROM hardware_fact_manufacturing_cost GROUP BY 2 UNION ALL
SELECT 'ded.pct', typeof(pre_invoice_discount_pct), count(*) FROM hardware_fact_pre_invoice_deductions GROUP BY 2 UNION ALL
SELECT 'sm.date', typeof(date), count(*) FROM hardware_fact_sales_monthly GROUP BY 2 UNION ALL
SELECT 'sm.sold_quantity', typeof(sold_quantity), count(*) FROM hardware_fact_sales_monthly GROUP BY 2 UNION ALL
SELECT 'sm.customer_code', typeof(customer_code), count(*) FROM hardware_fact_sales_monthly GROUP BY 2 UNION ALL
SELECT 'sm.fiscal_year', typeof(fiscal_year), count(*) FROM hardware_fact_sales_monthly GROUP BY 2;
-- name: nulls_and_empty
SELECT 'cust' t, sum(customer IS NULL)+sum(platform IS NULL)+sum(channel IS NULL)+sum(market IS NULL)+sum(sub_zone IS NULL)+sum(region IS NULL) nulls,
  sum(customer='')+sum(platform='')+sum(channel='')+sum(market='')+sum(sub_zone='')+sum(region='') empties FROM hardware_dim_customer UNION ALL
SELECT 'prod', sum(division IS NULL)+sum(segment IS NULL)+sum(category IS NULL)+sum(product IS NULL)+sum(variant IS NULL),
  sum(division='')+sum(segment='')+sum(category='')+sum(product='')+sum(variant='') FROM hardware_dim_product UNION ALL
SELECT 'sales', sum(date IS NULL)+sum(product_code IS NULL)+sum(customer_code IS NULL)+sum(sold_quantity IS NULL)+sum(fiscal_year IS NULL), 0 FROM hardware_fact_sales_monthly UNION ALL
SELECT 'gp', sum(gross_price IS NULL)+sum(fiscal_year IS NULL), 0 FROM hardware_fact_gross_price UNION ALL
SELECT 'mc', sum(manufacturing_cost IS NULL)+sum(cost_year IS NULL), 0 FROM hardware_fact_manufacturing_cost UNION ALL
SELECT 'ded', sum(pre_invoice_discount_pct IS NULL), 0 FROM hardware_fact_pre_invoice_deductions;
-- name: key_uniqueness
SELECT 'cust customer_code' k, count(*) - count(DISTINCT customer_code) dups FROM hardware_dim_customer UNION ALL
SELECT 'prod product_code', count(*) - count(DISTINCT product_code) FROM hardware_dim_product UNION ALL
SELECT 'gp (product,fy)', count(*) - (SELECT count(*) FROM (SELECT DISTINCT product_code, fiscal_year FROM hardware_fact_gross_price)) FROM hardware_fact_gross_price UNION ALL
SELECT 'mc (product,cy)', count(*) - (SELECT count(*) FROM (SELECT DISTINCT product_code, cost_year FROM hardware_fact_manufacturing_cost)) FROM hardware_fact_manufacturing_cost UNION ALL
SELECT 'ded (cust,fy)', count(*) - (SELECT count(*) FROM (SELECT DISTINCT customer_code, fiscal_year FROM hardware_fact_pre_invoice_deductions)) FROM hardware_fact_pre_invoice_deductions UNION ALL
SELECT 'sales (date,product,cust)', count(*) - (SELECT count(*) FROM (SELECT DISTINCT date, product_code, customer_code FROM hardware_fact_sales_monthly)) FROM hardware_fact_sales_monthly UNION ALL
SELECT 'sales full-row dups', count(*) - (SELECT count(*) FROM (SELECT DISTINCT * FROM hardware_fact_sales_monthly)) FROM hardware_fact_sales_monthly;
-- name: fk_orphans
SELECT 'sales.product -> prod' j, sum(p.product_code IS NULL) orphans, count(*) n FROM hardware_fact_sales_monthly s LEFT JOIN hardware_dim_product p USING(product_code) UNION ALL
SELECT 'sales.customer -> cust', sum(c.customer_code IS NULL), count(*) FROM hardware_fact_sales_monthly s LEFT JOIN hardware_dim_customer c USING(customer_code) UNION ALL
SELECT 'gp.product -> prod', sum(p.product_code IS NULL), count(*) FROM hardware_fact_gross_price g LEFT JOIN hardware_dim_product p USING(product_code) UNION ALL
SELECT 'mc.product -> prod', sum(p.product_code IS NULL), count(*) FROM hardware_fact_manufacturing_cost g LEFT JOIN hardware_dim_product p USING(product_code) UNION ALL
SELECT 'ded.customer -> cust', sum(c.customer_code IS NULL), count(*) FROM hardware_fact_pre_invoice_deductions d LEFT JOIN hardware_dim_customer c USING(customer_code);
-- name: parents_without_children
SELECT 'products never sold' w, count(*) n FROM hardware_dim_product WHERE product_code NOT IN (SELECT product_code FROM hardware_fact_sales_monthly) UNION ALL
SELECT 'customers never buying', count(*) FROM hardware_dim_customer WHERE customer_code NOT IN (SELECT customer_code FROM hardware_fact_sales_monthly) UNION ALL
SELECT 'products without price', count(*) FROM hardware_dim_product WHERE product_code NOT IN (SELECT product_code FROM hardware_fact_gross_price) UNION ALL
SELECT 'products without cost', count(*) FROM hardware_dim_product WHERE product_code NOT IN (SELECT product_code FROM hardware_fact_manufacturing_cost) UNION ALL
SELECT 'customers without deduction', count(*) FROM hardware_dim_customer WHERE customer_code NOT IN (SELECT customer_code FROM hardware_fact_pre_invoice_deductions) UNION ALL
SELECT 'sales (prod,fy) without price', count(*) FROM (SELECT DISTINCT product_code, fiscal_year FROM hardware_fact_sales_monthly) s WHERE NOT EXISTS (SELECT 1 FROM hardware_fact_gross_price g WHERE g.product_code=s.product_code AND g.fiscal_year=s.fiscal_year) UNION ALL
SELECT 'sales (prod,fy) without cost', count(*) FROM (SELECT DISTINCT product_code, fiscal_year FROM hardware_fact_sales_monthly) s WHERE NOT EXISTS (SELECT 1 FROM hardware_fact_manufacturing_cost g WHERE g.product_code=s.product_code AND g.cost_year=s.fiscal_year) UNION ALL
SELECT 'sales (cust,fy) without deduction', count(*) FROM (SELECT DISTINCT customer_code, fiscal_year FROM hardware_fact_sales_monthly) s WHERE NOT EXISTS (SELECT 1 FROM hardware_fact_pre_invoice_deductions g WHERE g.customer_code=s.customer_code AND g.fiscal_year=s.fiscal_year) UNION ALL
SELECT 'price rows (prod,fy) never sold', count(*) FROM hardware_fact_gross_price g WHERE NOT EXISTS (SELECT 1 FROM hardware_fact_sales_monthly s WHERE g.product_code=s.product_code AND g.fiscal_year=s.fiscal_year) UNION ALL
SELECT 'ded rows (cust,fy) never sold', count(*) FROM hardware_fact_pre_invoice_deductions g WHERE NOT EXISTS (SELECT 1 FROM hardware_fact_sales_monthly s WHERE g.customer_code=s.customer_code AND g.fiscal_year=s.fiscal_year);
-- name: price_cost_same_keys
SELECT (SELECT count(*) FROM hardware_fact_gross_price g JOIN hardware_fact_manufacturing_cost m ON m.product_code=g.product_code AND m.cost_year=g.fiscal_year) matched,
       (SELECT count(*) FROM hardware_fact_gross_price) gp, (SELECT count(*) FROM hardware_fact_manufacturing_cost) mc;
-- name: years
SELECT 'gp' t, fiscal_year y, count(*) n FROM hardware_fact_gross_price GROUP BY 2 UNION ALL
SELECT 'mc', cost_year, count(*) FROM hardware_fact_manufacturing_cost GROUP BY 2 UNION ALL
SELECT 'ded', fiscal_year, count(*) FROM hardware_fact_pre_invoice_deductions GROUP BY 2 UNION ALL
SELECT 'sales', fiscal_year, count(*) FROM hardware_fact_sales_monthly GROUP BY 2 ORDER BY 1,2;
-- name: date_formats
SELECT length(date) len, substr(date,9,2) dd, count(*) n, min(date), max(date) FROM hardware_fact_sales_monthly GROUP BY 1,2;
-- name: fiscal_year_rule
-- AtliQ fiscal year starts in September: fy = year(date) + (month >= 9)
SELECT sum(fiscal_year = CAST(substr(date,1,4) AS INT) + (CAST(substr(date,6,2) AS INT) >= 9)) ok, count(*) n FROM hardware_fact_sales_monthly;
-- name: months
SELECT date, count(*) n, sum(sold_quantity) qty, count(DISTINCT product_code) prods, count(DISTINCT customer_code) custs FROM hardware_fact_sales_monthly GROUP BY 1 ORDER BY 1;
-- name: rowid_order
SELECT sum(nxt < cur) desc_pairs, count(*) pairs FROM (SELECT date||'|'||product_code||'|'||printf('%012d',customer_code) cur, lead(date||'|'||product_code||'|'||printf('%012d',customer_code)) OVER (ORDER BY rowid) nxt FROM hardware_fact_sales_monthly) WHERE nxt IS NOT NULL;
-- name: rowid_order_date
SELECT sum(nxt < cur) desc_pairs, count(*) pairs FROM (SELECT date cur, lead(date) OVER (ORDER BY rowid) nxt FROM hardware_fact_sales_monthly) WHERE nxt IS NOT NULL;
-- name: rowid_head
SELECT rowid, * FROM hardware_fact_sales_monthly ORDER BY rowid LIMIT 12;
-- name: dim_rowid_order
SELECT 'cust' t, sum(nxt < cur) desc_pairs FROM (SELECT customer_code cur, lead(customer_code) OVER (ORDER BY rowid) nxt FROM hardware_dim_customer) UNION ALL
SELECT 'prod', sum(nxt < cur) FROM (SELECT product_code cur, lead(product_code) OVER (ORDER BY rowid) nxt FROM hardware_dim_product) UNION ALL
SELECT 'gp', sum(nxt < cur) FROM (SELECT product_code||fiscal_year cur, lead(product_code||fiscal_year) OVER (ORDER BY rowid) nxt FROM hardware_fact_gross_price) UNION ALL
SELECT 'ded', sum(nxt < cur) FROM (SELECT printf('%012d',customer_code)||fiscal_year cur, lead(printf('%012d',customer_code)||fiscal_year) OVER (ORDER BY rowid) nxt FROM hardware_fact_pre_invoice_deductions);
