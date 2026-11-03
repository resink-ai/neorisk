-- local062: Italian customers, December 2021: profit = qty × (unit_price − unit_cost), in 10 equal-width
-- buckets.
-- Written from the question (no gold SQL); matches all 10 buckets of gold CSV _a.
with p as (
  select s.cust_id, sum(s.quantity_sold * (c.unit_price - c.unit_cost)) profit
  from sales s join costs c using(prod_id, time_id, channel_id, promo_id)
       join customers u using(cust_id) join countries k using(country_id)
  where k.country_name = 'Italy' and s.time_id between '2021-12-01' and '2021-12-31'
  group by s.cust_id),
b as (select p.*, (select min(profit) from p) lo, (select max(profit) from p) hi from p),
bk as (select cust_id, profit, min(10, cast((profit - lo) / ((hi - lo) / 10) as int) + 1) bucket from b)
select bucket, count(*) n_customers, min(profit), max(profit) from bk group by bucket order by bucket;
