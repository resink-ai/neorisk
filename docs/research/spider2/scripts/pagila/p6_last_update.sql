-- name: load_window_per_table
-- last_update per table: span, distinct seconds, and whether it is non-decreasing in rowid order
select 'language' t, min(last_update) lo, max(last_update) hi, count(distinct last_update) secs, count(*) n from language
union all select 'country', min(last_update), max(last_update), count(distinct last_update), count(*) from country
union all select 'city', min(last_update), max(last_update), count(distinct last_update), count(*) from city
union all select 'address', min(last_update), max(last_update), count(distinct last_update), count(*) from address
union all select 'actor', min(last_update), max(last_update), count(distinct last_update), count(*) from actor
union all select 'category', min(last_update), max(last_update), count(distinct last_update), count(*) from category
union all select 'staff', min(last_update), max(last_update), count(distinct last_update), count(*) from staff
union all select 'store', min(last_update), max(last_update), count(distinct last_update), count(*) from store
union all select 'film', min(last_update), max(last_update), count(distinct last_update), count(*) from film
union all select 'inventory', min(last_update), max(last_update), count(distinct last_update), count(*) from inventory
union all select 'film_actor', min(last_update), max(last_update), count(distinct last_update), count(*) from film_actor
union all select 'film_category', min(last_update), max(last_update), count(distinct last_update), count(*) from film_category
union all select 'customer', min(last_update), max(last_update), count(distinct last_update), count(*) from customer
union all select 'rental', min(last_update), max(last_update), count(distinct last_update), count(*) from rental
union all select 'payment', min(last_update), max(last_update), count(distinct last_update), count(*) from payment
order by lo, hi;
-- name: monotone_in_rowid
select 'actor' t, count(*) pairs, sum(b.last_update >= a.last_update) nondecr from actor a join actor b on b.rowid=a.rowid+1
union all select 'address', count(*), sum(b.last_update >= a.last_update) from address a join address b on b.rowid=a.rowid+1
union all select 'city', count(*), sum(b.last_update >= a.last_update) from city a join city b on b.rowid=a.rowid+1
union all select 'film', count(*), sum(b.last_update >= a.last_update) from film a join film b on b.rowid=a.rowid+1
union all select 'inventory', count(*), sum(b.last_update >= a.last_update) from inventory a join inventory b on b.rowid=a.rowid+1
union all select 'film_actor', count(*), sum(b.last_update >= a.last_update) from film_actor a join film_actor b on b.rowid=a.rowid+1
union all select 'film_category', count(*), sum(b.last_update >= a.last_update) from film_category a join film_category b on b.rowid=a.rowid+1
union all select 'customer', count(*), sum(b.last_update >= a.last_update) from customer a join customer b on b.rowid=a.rowid+1
union all select 'rental', count(*), sum(b.last_update >= a.last_update) from rental a join rental b on b.rowid=a.rowid+1
union all select 'payment', count(*), sum(b.last_update >= a.last_update) from payment a join payment b on b.rowid=a.rowid+1;
-- name: rowid_order_keys
-- is each table's rowid order its key order?
select 'actor' t, count(*) n, sum(rowid = actor_id) rowid_eq_key from actor
union all select 'address', count(*), sum(rowid = address_id) from address
union all select 'city', count(*), sum(rowid = city_id) from city
union all select 'country', count(*), sum(rowid = country_id) from country
union all select 'customer', count(*), sum(rowid = customer_id) from customer
union all select 'film', count(*), sum(rowid = film_id) from film
union all select 'inventory', count(*), sum(rowid = inventory_id) from inventory
union all select 'payment', count(*), sum(rowid = payment_id) from payment;
-- name: rowid_order_composite
select 'film_actor (actor,film)' t, count(*) pairs, sum(b.actor_id > a.actor_id or (b.actor_id = a.actor_id and b.film_id > a.film_id)) in_key_order
from film_actor a join film_actor b on b.rowid=a.rowid+1
union all select 'film_category (film)', count(*), sum(b.film_id > a.film_id) from film_category a join film_category b on b.rowid=a.rowid+1
union all select 'rental (rental_id)', count(*), sum(b.rental_id > a.rental_id) from rental a join rental b on b.rowid=a.rowid+1
union all select 'address (address_id)', count(*), sum(b.address_id > a.address_id) from address a join address b on b.rowid=a.rowid+1;
-- name: rows_per_second_payment
select last_update, count(*) from payment group by 1 order by 1 limit 10;
-- name: rows_per_second_stats
select t, min(c), max(c), avg(c) from (
  select 'rental' t, last_update, count(*) c from rental group by 2
  union all select 'payment', last_update, count(*) from payment group by 2
  union all select 'inventory', last_update, count(*) from inventory group by 2
  union all select 'film_actor', last_update, count(*) from film_actor group by 2) group by t;
-- name: customer_create_date
select create_date, count(*), min(customer_id), max(customer_id) from customer group by 1;
-- name: customer_create_vs_first_rental
select count(*) n, sum(c.create_date < (select min(rental_date) from rental r where r.customer_id=c.customer_id)) created_before_first_rental
from customer c;
-- name: rental_last_update_vs_return
-- does rental.last_update carry any lifecycle information? (it is a load timestamp in rowid order)
select return_date is null open_, min(last_update), max(last_update), count(*) from rental group by 1;
-- name: payment_2006_last_update
select substr(payment_date,1,4) y, count(*), min(last_update), max(last_update) from payment group by 1;
