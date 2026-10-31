-- Spider2 questions on Pagila / sqlite-sakila. Gold SQL exists for local038, local039, local197,
-- local199 (copied verbatim below); the others are my own readings, checked against the
-- exec_result CSVs.
-- name: local038_gold
SELECT
    actor.first_name || ' ' || actor.last_name AS full_name
FROM actor
INNER JOIN film_actor ON actor.actor_id = film_actor.actor_id
INNER JOIN film ON film_actor.film_id = film.film_id
INNER JOIN film_category ON film.film_id = film_category.film_id
INNER JOIN category ON film_category.category_id = category.category_id
INNER JOIN language ON film.language_id = language.language_id
WHERE category.name = 'Children' AND film.release_year BETWEEN 2000 AND 2010
  AND film.rating IN ('G', 'PG') AND language.name = 'English' AND film.length <= 120
GROUP BY actor.actor_id, actor.first_name, actor.last_name
ORDER BY COUNT(film.film_id) DESC
LIMIT 1;
-- name: local038_top_ties
select a.first_name||' '||a.last_name n, count(*) c from actor a join film_actor fa using(actor_id) join film f using(film_id)
join film_category fc using(film_id) join category c using(category_id)
where c.name='Children' and f.release_year between 2000 and 2010 and f.rating in ('G','PG') and f.length <= 120 and f.language_id=1
group by a.actor_id order by c desc limit 5;
-- name: local039_gold
SELECT category.name
FROM category
INNER JOIN film_category USING (category_id)
INNER JOIN film USING (film_id)
INNER JOIN inventory USING (film_id)
INNER JOIN rental USING (inventory_id)
INNER JOIN customer USING (customer_id)
INNER JOIN address USING (address_id)
INNER JOIN city USING (city_id)
WHERE LOWER(city.city) LIKE 'a%' OR city.city LIKE '%-%'
GROUP BY category.name
ORDER BY SUM(CAST((julianday(rental.return_date) - julianday(rental.rental_date)) * 24 AS INTEGER)) DESC
LIMIT 1;
-- name: local039_hours
select c.name, sum((julianday(r.return_date)-julianday(r.rental_date))*24) hours from category c join film_category using(category_id)
join inventory using(film_id) join rental r using(inventory_id) join customer cu using(customer_id) join address using(address_id) join city ci using(city_id)
where lower(ci.city) like 'a%' or ci.city like '%-%' group by 1 order by 2 desc limit 3;
-- name: local197_gold
WITH result_table AS (
  SELECT strftime('%m', pm.payment_date) AS pay_mon, customer_id, COUNT(pm.amount) AS pay_countpermon, SUM(pm.amount) AS pay_amount
  FROM payment AS pm GROUP BY pay_mon, customer_id),
top10_customer AS (
  SELECT customer_id, SUM(tb.pay_amount) AS total_payments FROM result_table AS tb GROUP BY customer_id
  ORDER BY SUM(tb.pay_amount) DESC LIMIT 10),
difference_per_mon AS (
  SELECT pay_mon AS month_number, pay_mon AS month, tb.pay_countpermon, tb.pay_amount,
    ABS(tb.pay_amount - LAG(tb.pay_amount) OVER (PARTITION BY tb.customer_id)) AS diff
  FROM result_table tb JOIN top10_customer top ON top.customer_id = tb.customer_id)
SELECT month, ROUND(max_diff, 2) AS max_diff
FROM (SELECT month, diff, month_number, MAX(diff) OVER (PARTITION BY month) AS max_diff FROM difference_per_mon) AS max_per_mon
WHERE diff = max_diff ORDER BY max_diff DESC LIMIT 1;
-- name: local197_mine
with m as (select customer_id, strftime('%Y-%m', payment_date) ym, sum(amount) s from payment group by 1,2),
top as (select customer_id from payment group by 1 order by sum(amount) desc limit 10),
d as (select m.customer_id, ym, s, s - lag(s) over (partition by m.customer_id order by ym) diff from m join top using(customer_id))
select d.customer_id, c.first_name||' '||c.last_name, ym, round(diff,2) from d join customer c using(customer_id)
where diff is not null order by abs(diff) desc limit 3;
-- name: local199_gold
WITH result_table AS (
  SELECT strftime('%Y', RE.RENTAL_DATE) AS YEAR, strftime('%m', RE.RENTAL_DATE) AS RENTAL_MONTH, ST.STORE_ID, COUNT(RE.RENTAL_ID) AS count
  FROM RENTAL RE JOIN STAFF ST ON RE.STAFF_ID = ST.STAFF_ID GROUP BY YEAR, RENTAL_MONTH, ST.STORE_ID),
monthly_sales AS (SELECT YEAR, RENTAL_MONTH, STORE_ID, SUM(count) AS total_rentals FROM result_table GROUP BY YEAR, RENTAL_MONTH, STORE_ID),
store_max_sales AS (SELECT STORE_ID, YEAR, RENTAL_MONTH, total_rentals, MAX(total_rentals) OVER (PARTITION BY STORE_ID) AS max_rentals FROM monthly_sales)
SELECT STORE_ID, YEAR, RENTAL_MONTH, total_rentals FROM store_max_sales WHERE total_rentals = max_rentals ORDER BY STORE_ID;
-- name: local056_mine
-- average month-over-month change in monthly payment totals (absolute diff), top customer
with m as (select customer_id, strftime('%Y-%m', payment_date) ym, sum(amount) s from payment group by 1,2),
d as (select customer_id, abs(s - lag(s) over (partition by customer_id order by ym)) diff from m)
select c.first_name||' '||c.last_name, avg(diff) a from d join customer c using(customer_id) where diff is not null
group by d.customer_id order by a desc limit 3;
-- name: local193_mine
with f as (select customer_id, min(payment_date) t0, sum(amount) ltv from payment group by 1 having sum(amount) > 0),
x as (select f.customer_id, f.ltv,
  sum(case when (julianday(p.payment_date)-julianday(f.t0)) < 7 then p.amount else 0 end) s7,
  sum(case when (julianday(p.payment_date)-julianday(f.t0)) < 30 then p.amount else 0 end) s30
  from f join payment p using(customer_id) group by 1,2)
select avg(100.0*s7/ltv) pct7, avg(100.0*s30/ltv) pct30, avg(ltv) avg_ltv from x;
-- name: local194_mine
-- revenue per film (payments via rental → inventory), split equally among its actors; top 3 per actor
with fr as (select i.film_id, sum(p.amount) rev from payment p join rental r using(rental_id) join inventory i using(inventory_id) group by 1),
na as (select film_id, count(*) n from film_actor group by 1),
x as (select fa.actor_id, f.title, fr.rev, fr.rev / na.n share,
  row_number() over (partition by fa.actor_id order by fr.rev desc) rk
  from film_actor fa join fr using(film_id) join na using(film_id) join film f using(film_id))
select actor_id, title, round(rev,2), round(share,4), round(avg(share) over (partition by actor_id),6) avg_share
from x where rk <= 3 order by actor_id, rk limit 9;
-- name: local195_mine
-- top 5 actors by revenue (equal split) and by rental count; share of customers who rented any of their films
with fr as (select i.film_id, sum(p.amount) rev from payment p join rental r using(rental_id) join inventory i using(inventory_id) group by 1),
by_rev as (select fa.actor_id from film_actor fa join fr using(film_id) group by 1 order by sum(fr.rev) desc limit 5),
by_cnt as (select fa.actor_id from film_actor fa join inventory i using(film_id) join rental r using(inventory_id) group by 1 order by count(*) desc limit 5)
select 'by revenue' k, count(distinct r.customer_id), 100.0*count(distinct r.customer_id)/(select count(*) from customer)
from rental r join inventory i using(inventory_id) join film_actor fa using(film_id) where fa.actor_id in (select actor_id from by_rev)
union all
select 'by rentals', count(distinct r.customer_id), 100.0*count(distinct r.customer_id)/(select count(*) from customer)
from rental r join inventory i using(inventory_id) join film_actor fa using(film_id) where fa.actor_id in (select actor_id from by_cnt);
-- name: local196_mine
-- first movie = the rental of the customer's earliest payment; avg total spend; avg (rentals − 1)
with fp as (select customer_id, rental_id from (select customer_id, rental_id, row_number() over (partition by customer_id order by payment_date, payment_id) rn from payment) where rn = 1),
fr as (select fp.customer_id, f.rating from fp join rental r using(rental_id) join inventory i using(inventory_id) join film f using(film_id)),
tot as (select customer_id, sum(amount) s from payment group by 1),
cnt as (select customer_id, count(*) n from rental group by 1)
select fr.rating, avg(tot.s), avg(cnt.n - 1.0) from fr join tot using(customer_id) join cnt using(customer_id) group by 1 order by 1;
