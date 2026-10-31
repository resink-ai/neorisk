-- name: row_counts
select 'sales' t, count(*) from sales union all select 'costs', count(*) from costs
union all select 'times', count(*) from times union all select 'products', count(*) from products
union all select 'customers', count(*) from customers union all select 'promotions', count(*) from promotions
union all select 'channels', count(*) from channels union all select 'countries', count(*) from countries
union all select 'currency', count(*) from currency union all select 'supplementary_demographics', count(*) from supplementary_demographics;
-- name: pk_unique
select 'times' t, count(*), count(distinct time_id) from times
union all select 'products', count(*), count(distinct prod_id) from products
union all select 'customers', count(*), count(distinct cust_id) from customers
union all select 'promotions', count(*), count(distinct promo_id) from promotions
union all select 'channels', count(*), count(distinct channel_id) from channels
union all select 'countries', count(*), count(distinct country_id) from countries
union all select 'supp_demo', count(*), count(distinct cust_id) from supplementary_demographics
union all select 'currency(country,year,month)', count(*), (select count(*) from (select distinct country,year,month from currency)) from currency;
-- name: sales_key_dups
select count(*) n_rows,
  (select count(*) from (select 1 from sales group by prod_id,cust_id,time_id,channel_id,promo_id)) n_keys,
  (select count(*) from (select 1 from sales group by prod_id,cust_id,time_id,channel_id,promo_id,quantity_sold,amount_sold)) n_distinct_rows
from sales;
-- name: sales_key_multiplicity
select k, count(*) n_keys, sum(k) n_rows from (select count(*) k from sales group by prod_id,cust_id,time_id,channel_id,promo_id) group by k order by k;
-- name: sales_exact_dup_multiplicity
select k, count(*) n_groups, sum(k) n_rows from (select count(*) k from sales group by prod_id,cust_id,time_id,channel_id,promo_id,quantity_sold,amount_sold) group by k order by k;
-- name: dup_key_same_amount
-- among keys with >1 row: how many have all amounts equal
select sum(namt=1) all_equal, sum(namt>1) differ, count(*) from
 (select count(distinct amount_sold) namt from sales group by prod_id,cust_id,time_id,channel_id,promo_id having count(*)>1);
-- name: costs_key_dups
select count(*) n_rows,
 (select count(*) from (select 1 from costs group by prod_id,time_id,channel_id,promo_id)) n_keys,
 (select count(*) from (select 1 from costs group by prod_id,time_id,channel_id,promo_id,unit_cost,unit_price)) n_distinct
from costs;
-- name: costs_key_multiplicity
select k, count(*) from (select count(*) k from costs group by prod_id,time_id,channel_id,promo_id) group by k;
-- name: fk_coverage
select 'sales.prod->products' fk, count(*), sum(p.prod_id is not null) from sales s left join products p using(prod_id)
union all select 'sales.cust->customers', count(*), sum(c.cust_id is not null) from sales s left join customers c using(cust_id)
union all select 'sales.time->times', count(*), sum(t.time_id is not null) from sales s left join times t using(time_id)
union all select 'sales.channel->channels', count(*), sum(c.channel_id is not null) from sales s left join channels c using(channel_id)
union all select 'sales.promo->promotions', count(*), sum(p.promo_id is not null) from sales s left join promotions p using(promo_id)
union all select 'costs.prod->products', count(*), sum(p.prod_id is not null) from costs s left join products p using(prod_id)
union all select 'costs.time->times', count(*), sum(t.time_id is not null) from costs s left join times t using(time_id)
union all select 'costs.channel->channels', count(*), sum(c.channel_id is not null) from costs s left join channels c using(channel_id)
union all select 'costs.promo->promotions', count(*), sum(p.promo_id is not null) from costs s left join promotions p using(promo_id)
union all select 'customers.country->countries', count(*), sum(k.country_id is not null) from customers c left join countries k using(country_id)
union all select 'supp_demo.cust->customers', count(*), sum(c.cust_id is not null) from supplementary_demographics d left join customers c using(cust_id);
-- name: reverse_coverage
select 'products sold' x, count(*), sum(exists(select 1 from sales s where s.prod_id=p.prod_id)) from products p
union all select 'customers with sales', count(*), sum(exists(select 1 from sales s where s.cust_id=c.cust_id)) from customers c
union all select 'times with sales', count(*), sum(exists(select 1 from sales s where s.time_id=t.time_id)) from times t
union all select 'times with costs', count(*), sum(exists(select 1 from costs s where s.time_id=t.time_id)) from times t
union all select 'promos in sales', count(*), sum(exists(select 1 from sales s where s.promo_id=p.promo_id)) from promotions p
union all select 'promos in costs', count(*), sum(exists(select 1 from costs s where s.promo_id=p.promo_id)) from promotions p
union all select 'channels in sales', count(*), sum(exists(select 1 from sales s where s.channel_id=c.channel_id)) from channels c
union all select 'countries with customers', count(*), sum(exists(select 1 from customers c where c.country_id=k.country_id)) from countries k
union all select 'customers with supp_demo', count(*), sum(exists(select 1 from supplementary_demographics d where d.cust_id=c.cust_id)) from customers c;
-- name: sales_to_costs
-- each sales row: does a costs row exist on (prod,time,channel,promo)?
select count(*) n, sum(exists(select 1 from costs c where c.prod_id=s.prod_id and c.time_id=s.time_id and c.channel_id=s.channel_id and c.promo_id=s.promo_id)) matched from sales s;
-- name: costs_to_sales
select count(*) n, sum(exists(select 1 from sales s where c.prod_id=s.prod_id and c.time_id=s.time_id and c.channel_id=s.channel_id and c.promo_id=s.promo_id)) matched from costs c;
-- name: typeofs
select 'sales.time_id' c, typeof(time_id), count(*) from sales group by 2
union all select 'sales.amount_sold', typeof(amount_sold), count(*) from sales group by 2
union all select 'sales.quantity_sold', typeof(quantity_sold), count(*) from sales group by 2
union all select 'costs.unit_cost', typeof(unit_cost), count(*) from costs group by 2
union all select 'costs.unit_price', typeof(unit_price), count(*) from costs group by 2
union all select 'costs.time_id', typeof(time_id), count(*) from costs group by 2
union all select 'times.time_id', typeof(time_id), count(*) from times group by 2
union all select 'currency.to_us', typeof(to_us), count(*) from currency group by 2
union all select 'customers.cust_credit_limit', typeof(cust_credit_limit), count(*) from customers group by 2
union all select 'customers.cust_eff_from', typeof(cust_eff_from), count(*) from customers group by 2
union all select 'customers.cust_eff_to', typeof(cust_eff_to), count(*) from customers group by 2
union all select 'products.prod_eff_from', typeof(prod_eff_from), count(*) from products group by 2
union all select 'products.prod_eff_to', typeof(prod_eff_to), count(*) from products group by 2
union all select 'promotions.promo_begin_date', typeof(promo_begin_date), count(*) from promotions group by 2
union all select 'products.prod_list_price', typeof(prod_list_price), count(*) from products group by 2
union all select 'promotions.promo_cost', typeof(promo_cost), count(*) from promotions group by 2;
-- name: time_ranges
select 'sales' t, min(time_id), max(time_id), count(distinct time_id) from sales
union all select 'costs', min(time_id), max(time_id), count(distinct time_id) from costs
union all select 'times', min(time_id), max(time_id), count(*) from times
union all select 'promo_begin', min(promo_begin_date), max(promo_begin_date), count(distinct promo_begin_date) from promotions
union all select 'promo_end', min(promo_end_date), max(promo_end_date), count(distinct promo_end_date) from promotions
union all select 'cust_eff_from', min(cust_eff_from), max(cust_eff_from), count(distinct cust_eff_from) from customers
union all select 'cust_eff_to', min(cust_eff_to), max(cust_eff_to), count(distinct cust_eff_to) from customers
union all select 'prod_eff_from', min(prod_eff_from), max(prod_eff_from), count(distinct prod_eff_from) from products
union all select 'prod_eff_to', min(prod_eff_to), max(prod_eff_to), count(distinct prod_eff_to) from products;
-- name: time_text_formats
select 'sales.time_id' c, length(time_id) l, min(time_id), count(*) from sales group by 2
union all select 'costs.time_id', length(time_id), min(time_id), count(*) from costs group by 2
union all select 'times.time_id', length(time_id), min(time_id), count(*) from times group by 2
union all select 'times.week_ending_day', length(week_ending_day), min(week_ending_day), count(*) from times group by 2
union all select 'cust_eff_from', length(cust_eff_from), min(cust_eff_from), count(*) from customers group by 2
union all select 'cust_eff_to', length(cust_eff_to), min(cust_eff_to), count(*) from customers group by 2
union all select 'prod_eff_from', length(prod_eff_from), min(prod_eff_from), count(*) from products group by 2
union all select 'prod_eff_to', length(prod_eff_to), min(prod_eff_to), count(*) from products group by 2
union all select 'promo_begin', length(promo_begin_date), min(promo_begin_date), count(*) from promotions group by 2;
