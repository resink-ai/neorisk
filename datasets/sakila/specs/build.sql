-- Sakila: events → source tables (refdata rebuild, DuckDB). Business times end in '.000'.
-- Snapshot columns come back by LEFT JOIN on the entity key.

-- table: language
SELECT CAST(l.ext_id AS BIGINT) AS language_id, l.name, n.last_update
FROM language l LEFT JOIN language_snapshot n USING (language_id);

-- table: country
SELECT CAST(k.ext_id AS BIGINT) AS country_id, k.country, n.last_update
FROM country k LEFT JOIN country_snapshot n USING (country_id);

-- table: city
SELECT CAST(c.ext_id AS BIGINT) AS city_id, c.city, CAST(k.ext_id AS BIGINT) AS country_id,
       n.last_update
FROM city c JOIN country k USING (country_id) LEFT JOIN city_snapshot n USING (city_id);

-- table: address
SELECT CAST(a.ext_id AS BIGINT) AS address_id, a.address, a.address2, a.district,
       CAST(c.ext_id AS BIGINT) AS city_id, a.postal_code, n.phone, n.last_update
FROM address a JOIN city c USING (city_id) LEFT JOIN address_snapshot n USING (address_id);

-- table: store
SELECT CAST(s.ext_id AS BIGINT) AS store_id, CAST(m.ext_id AS BIGINT) AS manager_staff_id,
       CAST(a.ext_id AS BIGINT) AS address_id, n.last_update
FROM store s LEFT JOIN store_snapshot n ON n.store_id = s.store_id
LEFT JOIN staff m ON m.staff_id = n.manager_staff_id
LEFT JOIN address a ON a.address_id = n.address_id;

-- table: staff
SELECT CAST(s.ext_id AS BIGINT) AS staff_id, s.first_name, s.last_name,
       CAST(a.ext_id AS BIGINT) AS address_id, NULL::BLOB AS picture, n.email,
       CAST(t.ext_id AS BIGINT) AS store_id, n.active, s.username, n.password, n.last_update
FROM staff s JOIN store t ON t.store_id = s.store_id
LEFT JOIN staff_snapshot n ON n.staff_id = s.staff_id
LEFT JOIN address a ON a.address_id = n.address_id;

-- table: customer
SELECT CAST(c.ext_id AS BIGINT) AS customer_id, CAST(s.ext_id AS BIGINT) AS store_id,
       c.first_name, c.last_name, n.email, CAST(a.ext_id AS BIGINT) AS address_id, n.active,
       n.create_date, n.last_update
FROM customer c JOIN address a ON a.address_id = c.address_id
LEFT JOIN customer_snapshot n ON n.customer_id = c.customer_id
LEFT JOIN store s ON s.store_id = n.store_id;

-- table: actor
SELECT CAST(a.ext_id AS BIGINT) AS actor_id, a.first_name, a.last_name, n.last_update
FROM actor a LEFT JOIN actor_snapshot n USING (actor_id);

-- table: category
SELECT CAST(c.ext_id AS BIGINT) AS category_id, c.name, n.last_update
FROM category c LEFT JOIN category_snapshot n USING (category_id);

-- table: film
SELECT CAST(f.ext_id AS BIGINT) AS film_id, f.title, f.description, f.release_year,
       CAST(l.ext_id AS BIGINT) AS language_id, CAST(o.ext_id AS BIGINT) AS original_language_id,
       n.rental_duration, n.rental_rate / 100.0 AS rental_rate, f.length,
       n.replacement_cost / 100.0 AS replacement_cost, f.rating, f.special_features,
       n.last_update
FROM film f JOIN language l ON l.language_id = f.language_id
LEFT JOIN language o ON o.language_id = f.original_language_id
LEFT JOIN film_snapshot n ON n.film_id = f.film_id;

-- table: film_actor
SELECT CAST(a.ext_id AS BIGINT) AS actor_id, CAST(f.ext_id AS BIGINT) AS film_id, n.last_update
FROM film_actor x JOIN actor a USING (actor_id) JOIN film f USING (film_id)
LEFT JOIN film_actor_snapshot n USING (film_actor_id);

-- table: film_category
SELECT CAST(f.ext_id AS BIGINT) AS film_id, CAST(c.ext_id AS BIGINT) AS category_id,
       n.film_category_last_update AS last_update
FROM film f JOIN category c USING (category_id) LEFT JOIN film_snapshot n USING (film_id);

-- table: film_text
SELECT NULL::BIGINT AS film_id, NULL::VARCHAR AS title, NULL::VARCHAR AS description WHERE false;

-- table: inventory
SELECT CAST(i.ext_id AS BIGINT) AS inventory_id, CAST(f.ext_id AS BIGINT) AS film_id,
       CAST(s.ext_id AS BIGINT) AS store_id, n.last_update
FROM inventory i JOIN film f USING (film_id) JOIN store s USING (store_id)
LEFT JOIN inventory_snapshot n USING (inventory_id);

-- table: payment
SELECT p.payment_id, CAST(c.ext_id AS BIGINT) AS customer_id, CAST(s.ext_id AS BIGINT) AS staff_id,
       p.rental_id, p.amount / 100.0 AS amount,
       strftime(p.event_time AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S') || '.000' AS payment_date,
       p.last_update
FROM payment_taken p JOIN customer c USING (customer_id) JOIN staff s USING (staff_id);

-- table: rental
SELECT r.rental_id,
       strftime(r.event_time AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S') || '.000' AS rental_date,
       CAST(i.ext_id AS BIGINT) AS inventory_id, CAST(c.ext_id AS BIGINT) AS customer_id,
       strftime(b.event_time AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S') || '.000' AS return_date,
       CAST(s.ext_id AS BIGINT) AS staff_id, r.last_update
FROM rental_started r JOIN inventory i USING (inventory_id) JOIN customer c USING (customer_id)
JOIN staff s USING (staff_id) LEFT JOIN rental_returned b USING (rental_id);
