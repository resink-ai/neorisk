-- local067: the same customers in 10 NTILE tiers with min and max profit.
-- Written from the question (no gold SQL); tiers 3–10 match gold CSV _a, tiers 1–2 do not;
-- kept as the source-vs-rebuilt check.
with p as (
  select s.cust_id, sum(s.quantity_sold * (c.unit_price - c.unit_cost)) profit
  from sales s join costs c using(prod_id, time_id, channel_id, promo_id)
       join customers u using(cust_id) join countries k using(country_id)
  where k.country_name = 'Italy' and s.time_id between '2021-12-01' and '2021-12-31'
  group by s.cust_id)
select t, min(profit), max(profit), count(*) from (select profit, ntile(10) over (order by profit) t from p) group by t order by t;
