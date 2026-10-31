-- name: sales_prod_ids
select s.prod_id, count(*) n, p.prod_id is not null in_products, min(time_id), max(time_id) from sales s left join products p using(prod_id) group by s.prod_id order by s.prod_id;
-- name: costs_prod_ids
select c.prod_id, count(*) n, p.prod_id is not null in_products from costs c left join products p using(prod_id) group by c.prod_id order by c.prod_id;
-- name: products_all
select prod_id, prod_name, prod_subcategory, prod_subcategory_id, prod_category, prod_category_id, prod_weight_class, prod_unit_of_measure, prod_pack_size, supplier_id, prod_status, prod_list_price, prod_min_price, prod_total, prod_total_id, prod_src_id, prod_eff_from, quote(prod_eff_to), prod_valid from products order by prod_id;
-- name: channels_all
select * from channels;
-- name: sales_by_channel
select channel_id, count(*), sum(amount_sold), sum(quantity_sold) from sales group by 1;
-- name: sales_by_promo
select promo_id, count(*), sum(amount_sold) from sales group by 1;
-- name: costs_by_promo_channel
select promo_id, channel_id, count(*) from costs group by 1,2;
-- name: promos_used
select * from promotions where promo_id in (select promo_id from sales union select promo_id from costs);
-- name: countries_all
select c.*, (select count(*) from customers u where u.country_id=c.country_id) n_cust,
 (select count(distinct s.cust_id) from sales s join customers u using(cust_id) where u.country_id=c.country_id) n_buyers from countries c order by country_id;
-- name: currency_countries
select country, count(*), min(year), max(year), min(month), max(month), min(to_us), max(to_us), count(distinct to_us) from currency group by country order by country;
-- name: currency_vs_countries
select country, exists(select 1 from countries k where k.country_name=c.country) in_countries from (select distinct country from currency) c;
-- name: currency_sample
select * from currency where country in ('France','Italy','United States of America','Japan') and month in (1,6,12) order by country, year, month;
-- name: currency_constant_over_months
select country, year, count(distinct to_us) n_rates from currency group by country, year order by n_rates desc, country limit 40;
-- name: currency_typeof
select typeof(country), typeof(year), typeof(month), typeof(to_us), count(*) from currency group by 1,2,3,4;
-- name: currency_rowid_order
select rowid, * from currency limit 15;
