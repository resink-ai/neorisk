-- local194: each actor's top 3 films by revenue split equally among the cast.
-- Written from the question (no gold SQL); matches the gold CSV's first rows.
with fr as (select i.film_id, sum(p.amount) rev from payment p join rental r using(rental_id) join inventory i using(inventory_id) group by 1),
na as (select film_id, count(*) n from film_actor group by 1),
x as (select fa.actor_id, f.title, fr.rev, fr.rev / na.n share,
  row_number() over (partition by fa.actor_id order by fr.rev desc) rk
  from film_actor fa join fr using(film_id) join na using(film_id) join film f using(film_id))
select actor_id, title, round(rev,2), round(share,4), round(avg(share) over (partition by actor_id),6) avg_share
from x where rk <= 3 order by actor_id, rk limit 9;
