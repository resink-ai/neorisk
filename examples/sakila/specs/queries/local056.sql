-- local056: customer with the highest average absolute month-over-month payment change.
-- Written from the question (no gold SQL); matches the gold CSV.
with m as (select customer_id, strftime('%Y-%m', payment_date) ym, sum(amount) s from payment group by 1,2),
d as (select customer_id, abs(s - lag(s) over (partition by customer_id order by ym)) diff from m)
select c.first_name||' '||c.last_name, avg(diff) a from d join customer c using(customer_id) where diff is not null
group by d.customer_id order by a desc limit 3;
