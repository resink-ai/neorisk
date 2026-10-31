-- name: amount_ne_price_where
-- rows with amount_sold <> unit_price: are they confined to multi-amount keys?
with k as (select prod_id, time_id, channel_id, promo_id from sales group by 1,2,3,4 having count(distinct amount_sold) > 1)
select (select count(*) from sales s join k using(prod_id, time_id, channel_id, promo_id)) rows_in_multi_keys,
 (select count(*) from sales s join costs c using(prod_id, time_id, channel_id, promo_id) join k using(prod_id, time_id, channel_id, promo_id) where abs(s.amount_sold - c.unit_price) >= 0.005) ne_in_multi_keys,
 (select count(*) from sales s join costs c using(prod_id, time_id, channel_id, promo_id) where abs(s.amount_sold - c.unit_price) >= 0.005) ne_total;
-- name: multi_amount_keys
select prod_id, time_id, channel_id, promo_id, group_concat(distinct amount_sold), count(*), (select unit_price from costs c where c.prod_id=s.prod_id and c.time_id=s.time_id and c.channel_id=s.channel_id and c.promo_id=s.promo_id) up
from sales s group by 1,2,3,4 having count(distinct amount_sold) > 1 limit 12;
-- name: ne_by_key_amounts
-- in multi-amount keys: does one amount equal unit_price and the rest differ?
with k as (select prod_id, time_id, channel_id, promo_id, count(distinct amount_sold) na, count(*) n from sales group by 1,2,3,4 having na > 1)
select k.na, count(*) keys_, sum(k.n) rows_, sum(exists(select 1 from sales s join costs c using(prod_id,time_id,channel_id,promo_id) where s.prod_id=k.prod_id and s.time_id=k.time_id and s.channel_id=k.channel_id and s.promo_id=k.promo_id and abs(s.amount_sold-c.unit_price)<0.005)) has_price_amount
from k group by 1;
-- name: ne_timing
select substr(s.time_id,1,7) m, count(*) from sales s join costs c using(prod_id, time_id, channel_id, promo_id) where abs(s.amount_sold - c.unit_price) >= 0.005 group by 1 order by 2 desc limit 10;
-- name: negative_costs
select count(*), sum(unit_cost < 0), sum(unit_cost = 0), sum(unit_cost > unit_price), min(time_id), max(time_id) from costs;
-- name: negative_costs_detail
select prod_id, channel_id, promo_id, count(*), min(unit_cost), min(time_id), max(time_id) from costs where unit_cost <= 0 group by 1,2,3;
-- name: cost_gt_price_detail
select prod_id, promo_id, channel_id, count(*), min(time_id), max(time_id) from costs where unit_cost > unit_price group by 1,2,3 order by 4 desc limit 10;
-- name: margin_quantiles_input
select round((unit_price - unit_cost) / unit_price, 2) m, count(*) from costs group by 1 order by 1 limit 0;
-- name: customers_constants
select count(distinct cust_eff_from), count(distinct cust_total), count(distinct cust_total_id), group_concat(distinct cust_valid), sum(cust_src_id is null), sum(cust_eff_to is null) from customers;
-- name: cust_valid_mix
select cust_valid, count(*), sum(exists(select 1 from sales s where s.cust_id=c.cust_id)) buyers from customers c group by 1;
-- name: customers_types
select typeof(cust_postal_code), typeof(cust_year_of_birth), typeof(cust_credit_limit), typeof(cust_main_phone_number), count(*) from customers group by 1,2,3,4;
-- name: customers_fd
select 'city_id -> city' fd, count(*), sum(n>1) from (select count(distinct cust_city) n from customers group by cust_city_id)
union all select 'city -> city_id', count(*), sum(n>1) from (select count(distinct cust_city_id) n from customers group by cust_city)
union all select 'city_id -> state_id', count(*), sum(n>1) from (select count(distinct cust_state_province_id) n from customers group by cust_city_id)
union all select 'state_id -> state', count(*), sum(n>1) from (select count(distinct cust_state_province) n from customers group by cust_state_province_id)
union all select 'state_id -> country', count(*), sum(n>1) from (select count(distinct country_id) n from customers group by cust_state_province_id)
union all select 'city_id -> country', count(*), sum(n>1) from (select count(distinct country_id) n from customers group by cust_city_id)
union all select '(last,first) dup', count(*), sum(n>1) from (select count(*) n from customers group by cust_last_name, cust_first_name)
union all select 'email dup', count(*), sum(n>1) from (select count(*) n from customers group by cust_email);
-- name: customers_mix
select 'gender' k, cust_gender v, count(*) from customers group by 2
union all select 'marital', coalesce(cust_marital_status,'NULL'), count(*) from customers group by 2
union all select 'income', coalesce(cust_income_level,'NULL'), count(*) from customers group by 2
union all select 'credit', cust_credit_limit, count(*) from customers group by 2;
-- name: yob
select min(cust_year_of_birth), max(cust_year_of_birth), avg(cust_year_of_birth) from customers;
-- name: cust_id_ranges
select min(cust_id), max(cust_id), count(*), (select min(cust_id) from supplementary_demographics), (select max(cust_id) from supplementary_demographics),
 (select count(*) from supplementary_demographics d where exists(select 1 from sales s where s.cust_id=d.cust_id)) demo_buyers from customers;
-- name: buyers_cust_id_range
select min(cust_id), max(cust_id), count(distinct cust_id) from sales;
-- name: supp_demo_mix
select 'education' k, education v, count(*) from supplementary_demographics group by 2
union all select 'household', household_size, count(*) from supplementary_demographics group by 2
union all select 'affinity', affinity_card, count(*) from supplementary_demographics group by 2
union all select 'yrs_res', yrs_residence, count(*) from supplementary_demographics group by 2
union all select 'typeof household', typeof(household_size), count(*) from supplementary_demographics group by 2;
-- name: supp_comments_crlf
select sum(comments like '%'||char(13)||'%'), sum(comments like '%'||char(10)||'%'), sum(comments <> trim(comments)), count(distinct comments) from supplementary_demographics;
-- name: promotions_mix
select promo_category, count(*), min(promo_begin_date), max(promo_end_date), avg(promo_cost) from promotions group by 1;
-- name: promo_durations
select julianday(promo_end_date) - julianday(promo_begin_date) d, count(*) from promotions where promo_id <> 999 group by 1 order by 2 desc limit 10;
-- name: sales_in_promo_window
select s.promo_id, count(*), sum(s.time_id between p.promo_begin_date and p.promo_end_date) in_window, min(s.time_id), max(s.time_id), p.promo_begin_date, p.promo_end_date
from sales s join promotions p using(promo_id) group by 1;
-- name: products_text_quirks
select sum(prod_eff_to = ''), sum(prod_src_id is null), sum(prod_src_id = ''), typeof(prod_src_id), count(*) from products group by typeof(prod_src_id);
-- name: countries_quirk
select country_id, country_name, country_subregion_id, country_region, country_region_id from countries where country_region_id = 52798 or country_name = 'Chile';
-- name: text_trailing_spaces
select 'customers' t, sum(cust_first_name <> trim(cust_first_name) or cust_last_name <> trim(cust_last_name) or cust_street_address <> trim(cust_street_address) or cust_city <> trim(cust_city)) from customers
union all select 'promotions', sum(promo_name <> trim(promo_name)) from promotions
union all select 'products', sum(prod_name <> trim(prod_name) or prod_desc <> trim(prod_desc)) from products
union all select 'countries', sum(country_name <> trim(country_name)) from countries;
