-- name: pk_unique
select 'actor' t, count(*) n, count(distinct actor_id) k from actor
union all select 'address', count(*), count(distinct address_id) from address
union all select 'category', count(*), count(distinct category_id) from category
union all select 'city', count(*), count(distinct city_id) from city
union all select 'country', count(*), count(distinct country_id) from country
union all select 'customer', count(*), count(distinct customer_id) from customer
union all select 'film', count(*), count(distinct film_id) from film
union all select 'film_actor', count(*), count(distinct actor_id||'/'||film_id) from film_actor
union all select 'film_category', count(*), count(distinct film_id||'/'||category_id) from film_category
union all select 'film_category film_id', count(*), count(distinct film_id) from film_category
union all select 'inventory', count(*), count(distinct inventory_id) from inventory
union all select 'language', count(*), count(distinct language_id) from language
union all select 'payment', count(*), count(distinct payment_id) from payment
union all select 'payment rental_id (non-null)', count(rental_id), count(distinct rental_id) from payment
union all select 'rental', count(*), count(distinct rental_id) from rental
union all select 'rental (date,inv,cust)', count(*), count(distinct rental_date||'/'||inventory_id||'/'||customer_id) from rental
union all select 'staff', count(*), count(distinct staff_id) from staff
union all select 'store', count(*), count(distinct store_id) from store;
-- name: id_gaps
select 'address' t, min(address_id) lo, max(address_id) hi, count(*) n from address
union all select 'rental', min(rental_id), max(rental_id), count(*) from rental
union all select 'payment', min(payment_id), max(payment_id), count(*) from payment;
-- name: missing_ids
with recursive s(i) as (select 1 union all select i+1 from s where i < 16049)
select 'rental' t, i from s where i not in (select rental_id from rental)
union all select 'address', i from s where i <= 605 and i not in (select address_id from address);
-- name: fk_coverage
select 'city.country_id->country' fk, count(*) n, sum(c.country_id is not null) ok from city x left join country c using(country_id)
union all select 'address.city_id->city', count(*), sum(c.city_id is not null) from address a left join city c using(city_id)
union all select 'customer.address_id->address', count(*), sum(a.address_id is not null) from customer x left join address a using(address_id)
union all select 'customer.store_id->store', count(*), sum(s.store_id is not null) from customer x left join store s using(store_id)
union all select 'staff.address_id->address', count(*), sum(a.address_id is not null) from staff x left join address a using(address_id)
union all select 'staff.store_id->store', count(*), sum(s.store_id is not null) from staff x left join store s using(store_id)
union all select 'store.manager_staff_id->staff', count(*), sum(s.staff_id is not null) from store x left join staff s on s.staff_id = x.manager_staff_id
union all select 'store.address_id->address', count(*), sum(a.address_id is not null) from store x left join address a using(address_id)
union all select 'film.language_id->language', count(*), sum(l.language_id is not null) from film f left join language l using(language_id)
union all select 'film_actor.actor_id->actor', count(*), sum(a.actor_id is not null) from film_actor x left join actor a using(actor_id)
union all select 'film_actor.film_id->film', count(*), sum(f.film_id is not null) from film_actor x left join film f using(film_id)
union all select 'film_category.film_id->film', count(*), sum(f.film_id is not null) from film_category x left join film f using(film_id)
union all select 'film_category.category_id->category', count(*), sum(c.category_id is not null) from film_category x left join category c using(category_id)
union all select 'inventory.film_id->film', count(*), sum(f.film_id is not null) from inventory x left join film f using(film_id)
union all select 'inventory.store_id->store', count(*), sum(s.store_id is not null) from inventory x left join store s using(store_id)
union all select 'rental.inventory_id->inventory', count(*), sum(i.inventory_id is not null) from rental x left join inventory i using(inventory_id)
union all select 'rental.customer_id->customer', count(*), sum(c.customer_id is not null) from rental x left join customer c using(customer_id)
union all select 'rental.staff_id->staff', count(*), sum(s.staff_id is not null) from rental x left join staff s using(staff_id)
union all select 'payment.customer_id->customer', count(*), sum(c.customer_id is not null) from payment x left join customer c using(customer_id)
union all select 'payment.staff_id->staff', count(*), sum(s.staff_id is not null) from payment x left join staff s using(staff_id)
union all select 'payment.rental_id(non-null)->rental', count(x.rental_id), sum(r.rental_id is not null) from payment x left join rental r using(rental_id);
-- name: reverse_coverage
select 'films with inventory' t, count(*) n, sum(exists(select 1 from inventory i where i.film_id=f.film_id)) k from film f
union all select 'films with actors', count(*), sum(exists(select 1 from film_actor i where i.film_id=f.film_id)) from film f
union all select 'actors with films', count(*), sum(exists(select 1 from film_actor i where i.actor_id=a.actor_id)) from actor a
union all select 'inventory ever rented', count(*), sum(exists(select 1 from rental r where r.inventory_id=i.inventory_id)) from inventory i
union all select 'rentals with payment', count(*), sum(exists(select 1 from payment p where p.rental_id=r.rental_id)) from rental r
union all select 'customers with rental', count(*), sum(exists(select 1 from rental r where r.customer_id=c.customer_id)) from customer c
union all select 'addresses used by customer/staff/store', count(*), sum(exists(select 1 from customer c where c.address_id=a.address_id) or exists(select 1 from staff s where s.address_id=a.address_id) or exists(select 1 from store s where s.address_id=a.address_id)) from address a
union all select 'cities with address', count(*), sum(exists(select 1 from address a where a.city_id=c.city_id)) from city c
union all select 'countries with city', count(*), sum(exists(select 1 from city a where a.country_id=c.country_id)) from country c
union all select 'categories with film', count(*), sum(exists(select 1 from film_category a where a.category_id=c.category_id)) from category c
union all select 'languages used by film', count(*), sum(exists(select 1 from film a where a.language_id=l.language_id)) from language l;
-- name: never_rented_inventory
select i.*, f.title from inventory i join film f using(film_id) where not exists(select 1 from rental r where r.inventory_id=i.inventory_id);
-- name: unused_addresses
select * from address a where not exists(select 1 from customer c where c.address_id=a.address_id) and not exists(select 1 from staff s where s.address_id=a.address_id) and not exists(select 1 from store s where s.address_id=a.address_id);
-- name: payments_without_rental
select * from payment where rental_id is null;
-- name: payments_without_rental_context
select p.payment_id, p.customer_id, p.amount, p.payment_date,
  (select count(*) from payment q where q.customer_id=p.customer_id) cust_payments,
  (select max(q.payment_date) from payment q where q.customer_id=p.customer_id and q.rental_id is not null) cust_last_rental_payment,
  (select count(*) from rental r where r.customer_id=p.customer_id and r.return_date is null) cust_open_rentals
from payment p where p.rental_id is null;
-- name: rentals_without_payment
select r.*, (select count(*) from payment p where p.customer_id=r.customer_id and p.rental_id is null) cust_null_payments
from rental r where not exists(select 1 from payment p where p.rental_id=r.rental_id);
-- name: payment_customer_vs_rental_customer
select count(*) n, sum(p.customer_id=r.customer_id) same_customer, sum(p.staff_id=r.staff_id) same_staff
from payment p join rental r using(rental_id);
-- name: city_dup_name
select city, count(*), group_concat(city_id) from city group by city having count(*)>1;
-- name: city_multi_address
select city_id, count(*) from address group by city_id having count(*)>1;
-- name: staff_store
select s.staff_id, s.store_id, st.store_id, st.manager_staff_id, s.address_id, st.address_id from staff s join store st on st.manager_staff_id=s.staff_id;
-- name: rental_staff_vs_inventory_store
select i.store_id inv_store, s.store_id staff_store, count(*) from rental r join inventory i using(inventory_id) join staff s using(staff_id) group by 1,2;
-- name: rental_customer_store_vs_inventory_store
select c.store_id cust_store, i.store_id inv_store, count(*) from rental r join inventory i using(inventory_id) join customer c using(customer_id) group by 1,2;
-- name: payment_staff_vs_rental_staff
select r.staff_id rental_staff, p.staff_id pay_staff, count(*) from payment p join rental r using(rental_id) group by 1,2;
-- name: film_category_per_film
select n, count(*) from (select film_id, count(*) n from film_category group by film_id) group by n;
-- name: films_without_actors
select film_id, title from film f where not exists(select 1 from film_actor a where a.film_id=f.film_id);
-- name: london_countries
select ci.city_id, ci.city, co.country from city ci join country co using(country_id) where ci.city = 'London';
-- name: trigger_count
select count(*) from sqlite_master where type = 'trigger';
