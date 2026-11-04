-- local058: hardware segments with their 2020 unique-product counts, ordered by the % increase
-- in unique sold products from 2020 to 2021 ("year" is fiscal_year).
-- Gold SQL from xlang-ai/Spider2 spider2-lite/evaluation_suite/gold/sql/local058.sql;
-- reproduces gold variant local058_a.csv exactly.
WITH UniqueProducts2020 AS (
    SELECT
        dp.segment,
        COUNT(DISTINCT fsm.product_code) AS unique_products_2020
    FROM
        hardware_fact_sales_monthly fsm
    JOIN
        hardware_dim_product dp ON fsm.product_code = dp.product_code
    WHERE
        fsm.fiscal_year = 2020
    GROUP BY
        dp.segment
),
UniqueProducts2021 AS (
    SELECT
        dp.segment,
        COUNT(DISTINCT fsm.product_code) AS unique_products_2021
    FROM
        hardware_fact_sales_monthly fsm
    JOIN
        hardware_dim_product dp ON fsm.product_code = dp.product_code
    WHERE
        fsm.fiscal_year = 2021
    GROUP BY
        dp.segment
)
SELECT
    spc.segment,
    spc.unique_products_2020 AS product_count_2020
FROM
    UniqueProducts2020 spc
JOIN
    UniqueProducts2021 fup ON spc.segment = fup.segment
ORDER BY
    ((fup.unique_products_2021 - spc.unique_products_2020) * 100.0) / (spc.unique_products_2020) DESC;
