-- name: millis_always_zero
select 'rental_date' c, sum(substr(rental_date,21) <> '000') nonzero_ms, count(*) n from rental
union all select 'return_date', sum(substr(return_date,21) <> '000'), count(return_date) from rental
union all select 'payment_date', sum(substr(payment_date,21) <> '000'), count(*) from payment
union all select 'create_date', sum(substr(create_date,21) <> '000'), count(*) from customer;
-- name: rental_id_order_breaks
-- where rental_id order disagrees with rental_date order
select a.rental_id, a.rental_date, b.rental_id, b.rental_date from rental a join rental b on b.rowid = a.rowid + 1
where b.rental_date < a.rental_date limit 12;
-- name: rental_id_order_breaks_by_kind
select (b.rental_date like '2006%') next_is_2006, (a.rental_date like '2006%') prev_is_2006, count(*)
from rental a join rental b on b.rowid = a.rowid + 1 where b.rental_date < a.rental_date group by 1,2;
-- name: rental_id_order_without_2006
with r as (select rowid rid, rental_id, rental_date from rental where rental_date < '2006-01-01'),
s as (select rental_date, lag(rental_date) over (order by rid) prev from r)
select count(*), sum(rental_date >= prev), sum(rental_date < prev) from s where prev is not null;
-- name: rental_2006_ids
select min(rental_id), max(rental_id), count(*) from rental where rental_date like '2006%';
-- name: same_timestamp_rentals
select rental_date, count(*) from rental group by 1 having count(*) > 1 order by 2 desc limit 10;
-- name: same_timestamp_rentals_count
select sum(c) rows_in_shared, count(*) groups from (select rental_date, count(*) c from rental where rental_date < '2006-01-01' group by 1 having c > 1);
-- name: same_timestamp_returns
select count(*) groups, sum(c) rows_ from (select return_date, count(*) c from rental where return_date is not null group by 1 having c > 1);
-- name: return_seconds_equal_rental_seconds
-- generator fingerprint: return keeps the rental's seconds?
select count(*) n, sum(substr(return_date,18,2) = substr(rental_date,18,2)) same_ss,
  sum(substr(return_date,15,5) = substr(rental_date,15,5)) same_mmss from rental where return_date is not null;
-- name: return_minus_rental_whole_minutes
select count(*) n, sum(((julianday(return_date)-julianday(rental_date))*1440 - round((julianday(return_date)-julianday(rental_date))*1440)) between -1e-6 and 1e-6) whole_minutes
from rental where return_date is not null;
-- name: daily_counts
select substr(rental_date,1,10) d, count(*) n from rental group by 1 order by 1;
-- name: hour_mix
select cast(substr(rental_date,12,2) as int) h, count(*) n, sum(return_date is not null) from rental where rental_date < '2006-01-01' group by 1;
-- name: return_hour_mix
select cast(substr(return_date,12,2) as int) h, count(*) n from rental where return_date is not null group by 1;
-- name: weekday_mix
select strftime('%w', rental_date) dow, count(*) from rental where rental_date < '2006-01-01' group by 1;
-- name: rentals_per_customer_per_window
select substr(rental_date,1,7) m, count(distinct customer_id) customers, count(*) rentals from rental group by 1;
-- name: open_2006_rows_detail
select count(*) n, count(distinct customer_id) customers, count(distinct inventory_id) items, sum(staff_id=1) staff1 from rental where rental_date like '2006%';
-- name: inventory_out_at_2006
-- the 2006 rentals: were those items free at the time (every earlier rental returned)?
select count(*) n, sum(not exists(select 1 from rental q where q.inventory_id = r.inventory_id and q.rental_date < r.rental_date and q.return_date is null)) item_free
from rental r where rental_date like '2006%';
-- name: open_2005_rental_item_later
-- rental 14098 is never returned: is its item rented again later?
select r2.* from rental r2 where inventory_id = 6 order by rental_date;
-- name: staff_payment_vs_rental_staff_2006
select r.staff_id, p.staff_id, count(*) from rental r join payment p using(rental_id) where r.rental_date like '2006%' group by 1,2;
-- name: address_text_fields
select district, phone, count(*), sum(postal_code is null), sum(address2 is null) from address group by 1,2;
-- name: address_null_postal
select * from address where postal_code is null;
-- name: address_trailing_space
select sum(address <> trim(address)), sum(city_id is null) from address;
-- name: names_upper
select 'actor' t, sum(first_name <> upper(first_name) or last_name <> upper(last_name)) not_upper, count(*) from actor
union all select 'customer', sum(first_name <> upper(first_name) or last_name <> upper(last_name)), count(*) from customer;
-- name: email_rule
select count(*) n, sum(email = first_name || '.' || last_name || '@sakilacustomer.org') rule_ok from customer;
-- name: title_description_shape
select count(*) n, sum(description like 'A %' or description like 'An %') starts_a, sum(title = upper(title)) title_upper from film;
-- name: city_nonascii
select count(*) from city where city glob '*[^ -~]*';
-- name: city_odd
select city_id, city from city where city like '%(%' or city glob '[a-z]*' limit 10;
-- name: film_last_update_vs_film_id
select count(*) from film a join film b on b.film_id = a.film_id + 1 where b.last_update < a.last_update;
-- name: language_rows
select * from language;
-- name: staff_rows
select staff_id, first_name, last_name, address_id, typeof(picture), email, store_id, active, username, password, last_update from staff;
-- name: store_rows
select * from store;
-- name: category_rows
select * from category;
-- name: affinity_trap
-- TIMESTAMP columns have NUMERIC affinity: a bare '2006' literal becomes the integer 2006, and every text value sorts above it
select sum(rental_date < '2006') lt_2006_bare, sum(rental_date < '2006-01-01') lt_2006_full, sum(rental_date > 2006) gt_int from rental;
-- name: windows
-- rentals come in 7-day windows, 21 days apart
with d as (select rental_date t, julianday(rental_date) j from rental where rental_date < '2006-01-01'),
g as (select t, j, case when j - lag(j) over (order by j) > 2 then 1 else 0 end brk from d),
w as (select t, j, sum(brk) over (order by j rows unbounded preceding) win from g)
select win, min(t) first_, max(t) last_, count(*) n, round(max(j)-min(j),3) span_days,
  round(min(j) - lag(min(j)) over (order by win), 3) start_gap_days from w group by win;
-- name: window_boundary_rental_ids
with d as (select rental_id, julianday(rental_date) j from rental where rental_date < '2006-01-01'),
g as (select rental_id, j, case when j - lag(j) over (order by j) > 2 then 1 else 0 end brk from d),
w as (select rental_id, sum(brk) over (order by j rows unbounded preceding) win from g)
select win, min(rental_id), max(rental_id), count(*) from w group by win;
-- name: rentals_2006_by_window_id_range
select count(*) from rental where rental_date like '2006%' and rental_id between 11496 and 16049;
-- name: item_rentals_per_window
-- an inventory item is rented at most once per 7-day window?
with w as (select inventory_id, case when rental_date < '2005-06-01' then 0 when rental_date < '2005-07-01' then 1
  when rental_date < '2005-07-20' then 2 when rental_date < '2005-08-10' then 3 when rental_date < '2006-01-01' then 4 else 5 end win from rental)
select n, count(*) from (select inventory_id, win, count(*) n from w group by 1,2) group by n;
-- name: windows_per_item
with w as (select inventory_id, case when rental_date < '2005-06-01' then 0 when rental_date < '2005-07-01' then 1
  when rental_date < '2005-07-20' then 2 when rental_date < '2005-08-10' then 3 when rental_date < '2006-01-01' then 4 else 5 end win from rental)
select win, count(distinct inventory_id) items, count(*) rentals from w group by 1;
-- name: idle_gap_short
with r as (select inventory_id, rental_date, return_date, lead(rental_date) over (partition by inventory_id order by rental_date) nx from rental)
select min((julianday(nx)-julianday(return_date))*24) min_idle_h, count(*) from r where nx is not null and return_date is not null and julianday(nx)-julianday(return_date) < 7;
-- name: items_2006_also_in_window4
select count(*) items_2006, sum(exists(select 1 from rental q where q.inventory_id = r.inventory_id and q.rental_date between '2005-08-10' and '2006-01-01')) also_rented_aug16_23
from rental r where rental_date like '2006%';
-- name: window4_plus_2006_items
select count(distinct inventory_id) from rental where rental_date >= '2005-08-10';
