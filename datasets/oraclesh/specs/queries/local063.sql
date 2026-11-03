-- local063: among local060's top-20% products, the one with the smallest share change.
-- Written from the question (no gold SQL); 130 Pro Maple Youth Bat as in gold CSVs _a and _b.
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
from rk join products p using(prod_id) where nt = 1 order by abs(change_pp), rk.prod_id limit 1;
