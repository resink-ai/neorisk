-- local059: calendar 2021, the mean total quantity of the top 3 products (by total quantity
-- sold) in each division.
-- Written from the question (no gold SQL); reproduces gold variant local059_a.csv exactly with
-- the calendar reading (date in 2021), not fiscal_year = 2021. From the report's
-- scripts/atliq/q3_generator.sql block gold_local059.
WITH t AS (
    SELECT p.division, s.product_code, sum(s.sold_quantity) AS q
    FROM hardware_fact_sales_monthly s JOIN hardware_dim_product p USING (product_code)
    WHERE substr(s.date, 1, 4) = '2021'
    GROUP BY 1, 2
),
r AS (SELECT *, row_number() OVER (PARTITION BY division ORDER BY q DESC) AS rk FROM t)
SELECT division, avg(q) AS overall_avg_quantity_sold
FROM r WHERE rk <= 3 GROUP BY 1 ORDER BY 1;
