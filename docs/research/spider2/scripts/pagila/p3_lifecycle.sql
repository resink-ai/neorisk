-- name: missing_rental_neighbours
-- dates of the rentals around each missing rental_id, and the null-rental payment whose date falls between them
select m.i missing_id,
  (select rental_date from rental where rental_id = m.i-1) prev_date,
  (select rental_date from rental where rental_id = m.i+1) next_date,
  (select group_concat(payment_id||':'||customer_id||'@'||payment_date) from payment p where p.rental_id is null
     and p.payment_date between (select rental_date from rental where rental_id = m.i-1) and (select rental_date from rental where rental_id = m.i+1)) null_payment_in_gap
from (select 321 i union all select 2247 union all select 6579 union all select 9426 union all select 15592) m;
-- name: rental_id_vs_date_order
-- is rental_id in rental_date order?
select count(*) pairs, sum(b.rental_date >= a.rental_date) nondecreasing, sum(b.rental_date > a.rental_date) increasing
from rental a join rental b on b.rowid = a.rowid + 1;
-- name: rental_rowid_vs_id
select count(*) n, sum(rowid = rental_id) rowid_eq_id from rental;
-- name: payment_id_order
-- payment_id order: by customer then date?
select count(*) pairs, sum(b.customer_id > a.customer_id or (b.customer_id = a.customer_id and b.payment_date >= a.payment_date)) cust_then_date,
  sum(b.customer_id = a.customer_id) same_customer, sum(b.customer_id < a.customer_id) cust_decrease
from payment a join payment b on b.payment_id = a.payment_id + 1;
-- name: payment_order_violations
select a.payment_id, a.customer_id, a.payment_date, b.payment_id, b.customer_id, b.payment_date
from payment a join payment b on b.payment_id = a.payment_id + 1
where b.customer_id = a.customer_id and b.payment_date < a.payment_date limit 20;
-- name: payment_date_vs_rental_date
select count(*) n, sum(p.payment_date = r.rental_date) equal, sum(p.payment_date > r.rental_date) after, sum(p.payment_date < r.rental_date) before
from payment p join rental r using(rental_id);
-- name: payment_after_rental_detail
select p.payment_id, r.rental_id, r.rental_date, p.payment_date, r.return_date, p.amount,
  round((julianday(p.payment_date)-julianday(r.rental_date))*24,3) gap_h
from payment p join rental r using(rental_id) where p.payment_date <> r.rental_date order by gap_h limit 40;
-- name: payment_date_neq_rental_by_month
select substr(r.rental_date,1,7) m, count(*) n, sum(p.payment_date <> r.rental_date) neq
from payment p join rental r using(rental_id) group by 1;
-- name: return_null_by_month
select substr(rental_date,1,7) m, count(*) n, sum(return_date is null) open_, min(rental_date), max(rental_date) from rental group by 1;
-- name: return_null_by_day_2006
select substr(rental_date,1,10) d, count(*), sum(return_date is null) from rental where rental_date >= '2005-08-24' group by 1;
-- name: open_rentals_before_2006
select r.*, f.rental_duration from rental r join inventory i using(inventory_id) join film f using(film_id)
where return_date is null and rental_date < '2006-01-01' order by rental_date limit 30;
-- name: open_rentals_split
select rental_date < '2006-01-01' pre2006, count(*) from rental where return_date is null group by 1;
-- name: return_before_rental
select count(*) from rental where return_date < rental_date;
-- name: rental_days_hist
select cast((julianday(return_date)-julianday(rental_date)) as integer) d, count(*) from rental where return_date is not null group by 1;
-- name: rental_hours_quantiles
with x as (select (julianday(return_date)-julianday(rental_date))*24 h from rental where return_date is not null),
o as (select h, row_number() over (order by h) rn, count(*) over () n from x)
select min(h), max(h), avg(h),
  max(case when rn = cast(n*0.05 as int) then h end) p05, max(case when rn = cast(n*0.25 as int) then h end) p25,
  max(case when rn = cast(n*0.5 as int) then h end) p50, max(case when rn = cast(n*0.75 as int) then h end) p75,
  max(case when rn = cast(n*0.95 as int) then h end) p95 from o;
-- name: overlap_same_inventory
-- an inventory item rented again before its previous return (or while still out)
with r as (select rental_id, inventory_id, rental_date, return_date,
  lead(rental_date) over (partition by inventory_id order by rental_date) next_rental from rental)
select count(*) consecutive_pairs, sum(next_rental < return_date) next_before_return,
  sum(return_date is null and next_rental is not null) open_then_rented
from r where next_rental is not null;
-- name: overlap_examples
with r as (select rental_id, inventory_id, rental_date, return_date,
  lead(rental_date) over (partition by inventory_id order by rental_date) next_rental,
  lead(rental_id) over (partition by inventory_id order by rental_date) next_id from rental)
select * from r where next_rental < return_date or (return_date is null and next_rental is not null) limit 15;
-- name: idle_gap_hist
-- hours between a return and the next rental of the same item
with r as (select inventory_id, rental_date, return_date,
  lead(rental_date) over (partition by inventory_id order by rental_date) next_rental from rental)
select case when g < 0 then '<0' when g < 24 then '0-1d' when g < 72 then '1-3d' when g < 168 then '3-7d'
            when g < 720 then '7-30d' else '30d+' end b, count(*)
from (select (julianday(next_rental)-julianday(return_date))*24 g from r where next_rental is not null and return_date is not null) group by 1;
-- name: customer_concurrent_out
-- max number of rentals a customer has out at once (sampled at each rental start)
with s as (select r1.customer_id, r1.rental_id, (select count(*) from rental r2 where r2.customer_id = r1.customer_id
   and r2.rental_date <= r1.rental_date and (r2.return_date is null or r2.return_date > r1.rental_date)) k from rental r1)
select k, count(*) from s group by k order by k;
-- name: return_vs_rental_duration
-- late returns: days kept vs film.rental_duration
select f.rental_duration, count(*) n,
  sum(julianday(return_date)-julianday(rental_date) > f.rental_duration) late,
  round(avg(julianday(return_date)-julianday(rental_date)),3) avg_days
from rental r join inventory i using(inventory_id) join film f using(film_id) where return_date is not null group by 1;
