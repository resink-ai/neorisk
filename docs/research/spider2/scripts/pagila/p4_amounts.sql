-- name: amount_values
select amount, typeof(amount) t, count(*) from payment group by 1,2 order by 1;
-- name: amount_cent_grid
select count(*) n, sum(abs(amount*100 - round(amount*100)) > 1e-9) off_grid from payment;
-- name: amount_minus_rate
-- amount − film.rental_rate for linked payments
select round(p.amount - f.rental_rate, 2) extra, count(*) from payment p join rental r using(rental_id)
join inventory i using(inventory_id) join film f using(film_id) group by 1 order by 1;
-- name: late_fee_rule
-- test: amount = rental_rate + max(0, ceil(days_out) - rental_duration) for returned rentals
with x as (select p.amount, f.rental_rate, f.rental_duration,
  julianday(r.return_date)-julianday(r.rental_date) days
  from payment p join rental r using(rental_id) join inventory i using(inventory_id) join film f using(film_id)
  where r.return_date is not null),
y as (select *, rental_rate + max(0, (cast(days as int) + (days > cast(days as int))) - rental_duration) rule_ceil,
               rental_rate + max(0, cast(days as int) - rental_duration) rule_floor from x)
select count(*) n, sum(abs(amount-rule_ceil)<1e-9) ceil_ok, sum(abs(amount-rule_floor)<1e-9) floor_ok from y;
-- name: late_fee_rule_residuals
with x as (select p.payment_id, p.amount, f.rental_rate, f.rental_duration,
  julianday(r.return_date)-julianday(r.rental_date) days, r.rental_date, r.return_date
  from payment p join rental r using(rental_id) join inventory i using(inventory_id) join film f using(film_id)
  where r.return_date is not null),
y as (select *, rental_rate + max(0, cast(days as int) - rental_duration) rule_floor from x)
select round(amount - rule_floor, 2) resid, count(*) from y group by 1 order by 1;
-- name: late_fee_rule_residual_examples
with x as (select p.payment_id, p.amount, f.rental_rate, f.rental_duration,
  julianday(r.return_date)-julianday(r.rental_date) days, r.rental_date, r.return_date
  from payment p join rental r using(rental_id) join inventory i using(inventory_id) join film f using(film_id)
  where r.return_date is not null),
y as (select *, rental_rate + max(0, cast(days as int) - rental_duration) rule_floor from x)
select * from y where abs(amount-rule_floor) > 1e-9 limit 25;
-- name: open_rental_amounts
select p.amount, f.rental_rate, count(*) from payment p join rental r using(rental_id) join inventory i using(inventory_id) join film f using(film_id)
where r.return_date is null group by 1,2;
-- name: rental_rate_mix
select rental_rate, count(*) from film group by 1;
-- name: rental_duration_mix
select rental_duration, count(*) from film group by 1;
-- name: replacement_cost_mix
select replacement_cost, count(*) from film group by 1;
-- name: rating_mix
select rating, count(*) from film group by 1;
-- name: special_features_mix
select special_features, count(*) from film group by 1 order by 2 desc;
-- name: length_stats
select min(length), max(length), avg(length), count(distinct length) from film;
-- name: category_mix
select c.name, count(*) from film_category fc join category c using(category_id) group by 1 order by 2 desc;
-- name: actors_per_film
select n, count(*) from (select film_id, count(*) n from film_actor group by 1) group by n;
-- name: films_per_actor
select min(n), max(n), avg(n) from (select actor_id, count(*) n from film_actor group by 1);
-- name: copies_per_film_store
select n, count(*) from (select film_id, store_id, count(*) n from inventory group by 1,2) group by n;
-- name: inventory_order
-- inventory_id order: by film then store?
select count(*) pairs, sum(b.film_id > a.film_id or (b.film_id = a.film_id and b.store_id >= a.store_id)) film_then_store
from inventory a join inventory b on b.inventory_id = a.inventory_id + 1;
-- name: rentals_per_customer
select min(n), max(n), avg(n) from (select customer_id, count(*) n from rental group by 1);
-- name: rentals_per_customer_hist
select n/5*5 b, count(*) from (select customer_id, count(*) n from rental group by 1) group by 1;
-- name: revenue_per_customer
select min(s), max(s), avg(s) from (select customer_id, sum(amount) s from payment group by 1);
-- name: rentals_per_inventory_hist
select n, count(*) from (select inventory_id, count(*) n from rental group by 1) group by n;
-- name: active_customers
select active, count(*) from customer group by 1;
-- name: inactive_customer_activity
select c.active, count(distinct c.customer_id) cust, count(r.rental_id) rentals, max(r.rental_date) last_rental,
  sum(r.rental_date >= '2006-01-01') rentals_2006
from customer c join rental r using(customer_id) group by 1;
-- name: customer_store_mix
select store_id, count(*) from customer group by 1;
-- name: inventory_store_mix
select store_id, count(*) from inventory group by 1;
-- name: staff_rental_mix
select staff_id, count(*) from rental group by 1;
-- name: amount_zero_rows
select p.*, r.rental_date, r.return_date from payment p left join rental r using(rental_id) where amount = 0 limit 30;
-- name: amount_zero_count
select count(*), sum(rental_id is null) from payment where amount = 0;
