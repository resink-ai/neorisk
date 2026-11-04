-- local195: share of customers who rented a film with one of the top 5 actors.
-- Written from the question (no gold SQL); 99.33 as in gold CSV _c.
with fr as (select i.film_id, sum(p.amount) rev from payment p join rental r using(rental_id) join inventory i using(inventory_id) group by 1),
by_rev as (select fa.actor_id from film_actor fa join fr using(film_id) group by 1 order by sum(fr.rev) desc limit 5),
by_cnt as (select fa.actor_id from film_actor fa join inventory i using(film_id) join rental r using(inventory_id) group by 1 order by count(*) desc limit 5)
select 'by revenue' k, count(distinct r.customer_id), 100.0*count(distinct r.customer_id)/(select count(*) from customer)
from rental r join inventory i using(inventory_id) join film_actor fa using(film_id) where fa.actor_id in (select actor_id from by_rev)
union all
select 'by rentals', count(distinct r.customer_id), 100.0*count(distinct r.customer_id)/(select count(*) from customer)
from rental r join inventory i using(inventory_id) join film_actor fa using(film_id) where fa.actor_id in (select actor_id from by_cnt);
