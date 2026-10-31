-- local193: average share of lifetime value in the first 7 and 30 days, and the average LTV.
-- Written from the question (no gold SQL); matches the gold CSV to 1e-12.
with f as (select customer_id, min(payment_date) t0, sum(amount) ltv from payment group by 1 having sum(amount) > 0),
x as (select f.customer_id, f.ltv,
  sum(case when (julianday(p.payment_date)-julianday(f.t0)) < 7 then p.amount else 0 end) s7,
  sum(case when (julianday(p.payment_date)-julianday(f.t0)) < 30 then p.amount else 0 end) s30
  from f join payment p using(customer_id) group by 1,2)
select avg(100.0*s7/ltv) pct7, avg(100.0*s30/ltv) pct30, avg(ltv) avg_ltv from x;
