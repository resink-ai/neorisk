-- Spider2 complex_oracle reproductions (no gold SQL exists; compare with exec_result CSVs)
-- name: local063_local060
with us as (
  select s.prod_id, c.cust_city, t.calendar_quarter_id q, s.amount_sold
  from sales s join customers c using(cust_id) join countries k using(country_id) join times t using(time_id)
  where k.country_iso_code = 'US' and s.promo_id = 999 and t.calendar_quarter_id in (1772, 1776)),
city as (
  select cust_city from us group by cust_city
  having sum(case when q = 1776 then amount_sold end) >= 1.2 * sum(case when q = 1772 then amount_sold end)),
ps as (
  select u.prod_id, sum(case when q = 1772 then amount_sold else 0 end) s19, sum(case when q = 1776 then amount_sold else 0 end) s20,
         sum(amount_sold) tot
  from us u join city using(cust_city) group by u.prod_id),
pn as (select ps.*, p.prod_name from ps join products p using(prod_id)),          -- inner join drops orphan prod_ids
rk as (select pn.*, ntile(5) over (order by tot desc) nt,
          s19 * 1.0 / sum(s19) over () sh19, s20 * 1.0 / sum(s20) over () sh20 from pn)
select prod_id, prod_name, round(s19, 2) s19, round(s20, 2) s20, sh19 * 100 share19_pct, sh20 * 100 share20_pct, (sh20 - sh19) * 100 change_pp, nt
from rk where nt = 1 order by change_pp desc;
-- name: local062
with p as (
  select s.cust_id, sum(s.quantity_sold * (c.unit_price - c.unit_cost)) profit
  from sales s join costs c using(prod_id, time_id, channel_id, promo_id)
       join customers u using(cust_id) join countries k using(country_id)
  where k.country_name = 'Italy' and s.time_id between '2021-12-01' and '2021-12-31'
  group by s.cust_id),
b as (select p.*, (select min(profit) from p) lo, (select max(profit) from p) hi from p),
bk as (select cust_id, profit, min(10, cast((profit - lo) / ((hi - lo) / 10) as int) + 1) bucket from b)
select bucket, count(*) n_customers, min(profit), max(profit) from bk group by bucket order by bucket;
-- name: local061
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
-- name: local050
with m as (
  select s.prod_id, t.calendar_year y, t.calendar_month_number mo, sum(s.amount_sold) amt
  from sales s join customers c using(cust_id) join countries k using(country_id) join times t using(time_id)
       join promotions p using(promo_id) join channels ch using(channel_id)
  where k.country_name = 'France' and p.promo_total_id = 1 and ch.channel_total_id = 1 and t.calendar_year in (2019, 2020)
  group by 1, 2, 3),
j as (select a.prod_id, a.mo, a.amt s19, b.amt s20 from m a join m b on a.prod_id = b.prod_id and a.mo = b.mo and a.y = 2019 and b.y = 2020),
pr as (select j.mo, avg((((s20 - s19) / s19) * s20 + s20) * coalesce(cu.to_us, 1)) a
       from j left join currency cu on cu.country = 'France' and cu.year = 2021 and cu.month = j.mo group by j.mo),
o as (select a, row_number() over (order by a) r, count(*) over () n from pr)
select avg(a) median from o where r in ((n + 1) / 2, (n + 2) / 2);
-- name: local067_ntile
with p as (
  select s.cust_id, sum(s.quantity_sold * (c.unit_price - c.unit_cost)) profit
  from sales s join costs c using(prod_id, time_id, channel_id, promo_id)
       join customers u using(cust_id) join countries k using(country_id)
  where k.country_name = 'Italy' and s.time_id between '2021-12-01' and '2021-12-31'
  group by s.cust_id)
select t, min(profit), max(profit), count(*) from (select profit, ntile(10) over (order by profit) t from p) group by t order by t;
-- name: local067_per_line_ntile
with p as (
  select s.quantity_sold * (c.unit_price - c.unit_cost) profit
  from sales s join costs c using(prod_id, time_id, channel_id, promo_id)
       join customers u using(cust_id) join countries k using(country_id)
  where k.country_name = 'Italy' and s.time_id between '2021-12-01' and '2021-12-31')
select t, min(profit), max(profit), count(*) from (select profit, ntile(10) over (order by profit) t from p) group by t order by t;
-- name: local067_per_cust_prod_ntile
with p as (
  select s.cust_id, s.prod_id, sum(s.quantity_sold * (c.unit_price - c.unit_cost)) profit
  from sales s join costs c using(prod_id, time_id, channel_id, promo_id)
       join customers u using(cust_id) join countries k using(country_id)
  where k.country_name = 'Italy' and s.time_id between '2021-12-01' and '2021-12-31'
  group by 1, 2)
select t, min(profit), max(profit), count(*) from (select profit, ntile(10) over (order by profit) t from p) group by t order by t;
-- name: profits_view_rows
select count(*) from profits;
-- name: local060_all_products
-- same, but shares and the top-20% cut are computed over every prod_id (orphans included); names joined last
with us as (
  select s.prod_id, c.cust_city, t.calendar_quarter_id q, s.amount_sold
  from sales s join customers c using(cust_id) join countries k using(country_id) join times t using(time_id)
  where k.country_iso_code = 'US' and s.promo_id = 999 and t.calendar_quarter_id in (1772, 1776)),
city as (
  select cust_city from us group by cust_city
  having sum(case when q = 1776 then amount_sold end) >= 1.2 * sum(case when q = 1772 then amount_sold end)),
ps as (
  select u.prod_id, sum(case when q = 1772 then amount_sold else 0 end) s19, sum(case when q = 1776 then amount_sold else 0 end) s20,
         sum(amount_sold) tot
  from us u join city using(cust_city) group by u.prod_id),
rk as (select ps.*, ntile(5) over (order by tot desc) nt, count(*) over () n_prod,
          s19 * 1.0 / sum(s19) over () sh19, s20 * 1.0 / sum(s20) over () sh20 from ps)
select rk.prod_id, p.prod_name, round(s19, 2) s19, round(s20, 2) s20, sh19 * 100 share19_pct, sh20 * 100 share20_pct, (sh20 - sh19) * 100 change_pp, nt, n_prod
from rk left join products p using(prod_id) where nt = 1 order by change_pp desc;
