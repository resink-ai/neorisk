-- Oracle SH: events → source tables (refdata rebuild, DuckDB).

-- table: countries
SELECT CAST(x.ext_id AS BIGINT) AS country_id, x.country_iso_code, x.country_name, x.country_subregion, x.country_subregion_id, x.country_region, x.country_region_id, x.country_total, x.country_total_id
FROM countries x ;

-- table: channels
SELECT CAST(x.ext_id AS BIGINT) AS channel_id, x.channel_desc, x.channel_class, x.channel_class_id, x.channel_total, x.channel_total_id
FROM channels x ;

-- table: promotions
SELECT CAST(x.ext_id AS BIGINT) AS promo_id, x.promo_name, x.promo_subcategory, x.promo_subcategory_id, x.promo_category, x.promo_category_id, s.promo_cost, x.promo_begin_date, x.promo_end_date, x.promo_total, x.promo_total_id
FROM promotions x LEFT JOIN promotions_snapshot s USING (promo_id);

-- table: customers
SELECT CAST(x.ext_id AS BIGINT) AS cust_id, x.cust_first_name, x.cust_last_name, x.cust_gender, x.cust_year_of_birth, s.cust_marital_status, s.cust_street_address, s.cust_postal_code, s.cust_city, s.cust_city_id, s.cust_state_province, s.cust_state_province_id, CAST(r_country_id.ext_id AS BIGINT) AS country_id, s.cust_main_phone_number, s.cust_income_level, s.cust_credit_limit, s.cust_email, x.cust_total, x.cust_total_id, x.cust_src_id, x.cust_eff_from, s.cust_eff_to, s.cust_valid
FROM customers x LEFT JOIN customers_snapshot s USING (cust_id)
LEFT JOIN countries r_country_id ON r_country_id.country_id = s.country_id;

-- table: times
SELECT CAST(x.ext_id AS VARCHAR) AS time_id, x.day_name, x.day_number_in_week, x.day_number_in_month, x.calendar_week_number, x.fiscal_week_number, x.week_ending_day, x.week_ending_day_id, x.calendar_month_number, x.fiscal_month_number, x.calendar_month_desc, x.calendar_month_id, x.fiscal_month_desc, x.fiscal_month_id, x.days_in_cal_month, x.days_in_fis_month, x.end_of_cal_month, x.end_of_fis_month, x.calendar_month_name, x.fiscal_month_name, x.calendar_quarter_desc, x.calendar_quarter_id, x.fiscal_quarter_desc, x.fiscal_quarter_id, x.days_in_cal_quarter, x.days_in_fis_quarter, x.end_of_cal_quarter, x.end_of_fis_quarter, x.calendar_quarter_number, x.fiscal_quarter_number, x.calendar_year, x.calendar_year_id, x.fiscal_year, x.fiscal_year_id, x.days_in_cal_year, x.days_in_fis_year, x.end_of_cal_year, x.end_of_fis_year
FROM times x ;

-- table: products
SELECT CAST(p.ext_id AS BIGINT) AS prod_id, p.prod_name, p.prod_desc, p.prod_subcategory,
       p.prod_subcategory_id, p.prod_subcategory_desc, p.prod_category, p.prod_category_id,
       p.prod_category_desc, p.prod_weight_class, p.prod_unit_of_measure, p.prod_pack_size,
       s.supplier_id, s.prod_status, s.prod_list_price, s.prod_min_price, p.prod_total,
       p.prod_total_id, p.prod_src_id, p.prod_eff_from, s.prod_eff_to, s.prod_valid
FROM products p LEFT JOIN products_snapshot s USING (prod_id) WHERE p.catalogued = 1;

-- table: supplementary_demographics
SELECT CAST(c.ext_id AS BIGINT) AS cust_id, s.education, s.occupation, s.household_size,
       s.yrs_residence, s.affinity_card, s.cricket, s.baseball, s.tennis, s.soccer, s.golf,
       s.unknown, s.misc, s.comments
FROM demographics d JOIN customers c ON c.cust_id = d.customer_id
LEFT JOIN demographics_snapshot s USING (demographics_id);

-- table: costs
SELECT CAST(p.ext_id AS BIGINT) AS prod_id,
       strftime(q.event_time AT TIME ZONE 'UTC', '%Y-%m-%d') AS time_id,
       CAST(m.ext_id AS BIGINT) AS promo_id, CAST(c.ext_id AS BIGINT) AS channel_id,
       q.unit_cost / 100.0 AS unit_cost, q.unit_price / 100.0 AS unit_price
FROM price_quoted q JOIN products p USING (prod_id) JOIN channels c USING (channel_id)
JOIN promotions m USING (promo_id);

-- table: sales
SELECT CAST(p.ext_id AS BIGINT) AS prod_id, CAST(u.ext_id AS BIGINT) AS cust_id,
       strftime(s.event_time AT TIME ZONE 'UTC', '%Y-%m-%d') AS time_id,
       CAST(c.ext_id AS BIGINT) AS channel_id, CAST(m.ext_id AS BIGINT) AS promo_id,
       s.quantity_sold, s.amount_sold / 100.0 AS amount_sold
FROM unit_sold s JOIN customers u USING (cust_id) JOIN products p USING (prod_id)
JOIN channels c USING (channel_id) JOIN promotions m USING (promo_id);

-- table: currency
-- A rule: 35 countries × 2019–2021 × 12 months; name cut to 20 characters; Canada 0.74.
SELECT substr(country_name, 1, 20) AS country, y AS year, mo AS month,
       CASE WHEN country_name = 'Canada' THEN 0.74 ELSE 1.0 END AS to_us
FROM countries, range(2019, 2022) t(y), range(1, 13) u(mo);
