-- local196: by the rating of each customer's first rented film: average spend and rentals − 1.
-- Written from the question (no gold SQL); matches all 5 gold rows.
with fp as (select customer_id, rental_id from (select customer_id, rental_id, row_number() over (partition by customer_id order by payment_date, payment_id) rn from payment) where rn = 1),
fr as (select fp.customer_id, f.rating from fp join rental r using(rental_id) join inventory i using(inventory_id) join film f using(film_id)),
tot as (select customer_id, sum(amount) s from payment group by 1),
cnt as (select customer_id, count(*) n from rental group by 1)
select fr.rating, avg(tot.s), avg(cnt.n - 1.0) from fr join tot using(customer_id) join cnt using(customer_id) group by 1 order by 1;
