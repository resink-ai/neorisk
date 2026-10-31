-- local061: France, 2019 → 2020 growth projected onto 2021 monthly sales, in USD, averaged per month.
-- Written from the question (no gold SQL); matches all 12 months of gold CSV _a.
with m as (
  select s.prod_id, t.calendar_year y, t.calendar_month_number mo, sum(s.amount_sold) amt
  from sales s join customers c using(cust_id) join countries k using(country_id) join times t using(time_id)
       join promotions p using(promo_id) join channels ch using(channel_id)
  where k.country_name = 'France' and p.promo_total_id = 1 and ch.channel_total_id = 1 and t.calendar_year in (2019, 2020)
  group by 1, 2, 3),
j as (select a.prod_id, a.mo, a.amt s19, b.amt s20 from m a join m b on a.prod_id = b.prod_id and a.mo = b.mo and a.y = 2019 and b.y = 2020),
pr as (select j.mo, (((s20 - s19) / s19) * s20 + s20) * coalesce(cu.to_us, 1) usd
       from j left join currency cu on cu.country = 'France' and cu.year = 2021 and cu.month = j.mo)
select mo, avg(usd) avg_projected_usd, count(*) n_products from pr group by mo order by mo;
