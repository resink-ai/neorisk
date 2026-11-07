-- Sakila: events → source tables, Flink SQL port of specs/build.sql, for `flink` and
-- `flink-stream`: plain joins only, so both planners accept every block.

-- table: language
SELECT CAST(l.ext_id AS BIGINT) AS language_id, l.name, n.last_update
FROM `language` l LEFT JOIN language_snapshot n ON n.language_id = l.language_id;

-- table: country
SELECT CAST(k.ext_id AS BIGINT) AS country_id, k.country, n.last_update
FROM country k LEFT JOIN country_snapshot n ON n.country_id = k.country_id;

-- table: city
SELECT CAST(c.ext_id AS BIGINT) AS city_id, c.city, CAST(k.ext_id AS BIGINT) AS country_id,
       n.last_update
FROM city c JOIN country k ON k.country_id = c.country_id
LEFT JOIN city_snapshot n ON n.city_id = c.city_id;

-- table: address
SELECT CAST(a.ext_id AS BIGINT) AS address_id, a.address, a.address2, a.district,
       CAST(c.ext_id AS BIGINT) AS city_id, a.postal_code, n.phone, n.last_update
FROM address a JOIN city c ON c.city_id = a.city_id
LEFT JOIN address_snapshot n ON n.address_id = a.address_id;

-- table: store
SELECT CAST(s.ext_id AS BIGINT) AS store_id, CAST(m.ext_id AS BIGINT) AS manager_staff_id,
       CAST(a.ext_id AS BIGINT) AS address_id, n.last_update
FROM store s LEFT JOIN store_snapshot n ON n.store_id = s.store_id
LEFT JOIN staff m ON m.staff_id = n.manager_staff_id
LEFT JOIN address a ON a.address_id = n.address_id;

-- table: staff
SELECT CAST(s.ext_id AS BIGINT) AS staff_id, s.first_name, s.last_name,
       CAST(a.ext_id AS BIGINT) AS address_id, CAST(NULL AS STRING) AS picture, n.email,
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
FROM actor a LEFT JOIN actor_snapshot n ON n.actor_id = a.actor_id;

-- table: category
SELECT CAST(c.ext_id AS BIGINT) AS category_id, c.name, n.last_update
FROM category c LEFT JOIN category_snapshot n ON n.category_id = c.category_id;

-- table: film
-- Amounts are cents; DuckDB's `/ 100.0` is a DOUBLE, Flink's a DECIMAL, so cast first.
SELECT CAST(f.ext_id AS BIGINT) AS film_id, f.title, f.description, f.release_year,
       CAST(l.ext_id AS BIGINT) AS language_id, CAST(o.ext_id AS BIGINT) AS original_language_id,
       n.rental_duration, CAST(n.rental_rate AS DOUBLE) / 100 AS rental_rate, f.length,
       CAST(n.replacement_cost AS DOUBLE) / 100 AS replacement_cost, f.rating,
       f.special_features, n.last_update
FROM film f JOIN `language` l ON l.language_id = f.language_id
LEFT JOIN `language` o ON o.language_id = f.original_language_id
LEFT JOIN film_snapshot n ON n.film_id = f.film_id;

-- table: film_actor
SELECT CAST(a.ext_id AS BIGINT) AS actor_id, CAST(f.ext_id AS BIGINT) AS film_id, n.last_update
FROM film_actor x JOIN actor a ON a.actor_id = x.actor_id JOIN film f ON f.film_id = x.film_id
LEFT JOIN film_actor_snapshot n ON n.film_actor_id = x.film_actor_id;

-- table: film_category
SELECT CAST(f.ext_id AS BIGINT) AS film_id, CAST(c.ext_id AS BIGINT) AS category_id,
       n.film_category_last_update AS last_update
FROM film f JOIN category c ON c.category_id = f.category_id
LEFT JOIN film_snapshot n ON n.film_id = f.film_id;

-- table: film_text
SELECT CAST(NULL AS BIGINT) AS film_id, CAST(NULL AS STRING) AS title,
       CAST(NULL AS STRING) AS description
FROM (VALUES (1)) AS t(x) WHERE FALSE;

-- table: inventory
SELECT CAST(i.ext_id AS BIGINT) AS inventory_id, CAST(f.ext_id AS BIGINT) AS film_id,
       CAST(s.ext_id AS BIGINT) AS store_id, n.last_update
FROM inventory i JOIN film f ON f.film_id = i.film_id JOIN store s ON s.store_id = i.store_id
LEFT JOIN inventory_snapshot n ON n.inventory_id = i.inventory_id;

-- table: payment
SELECT p.payment_id, CAST(c.ext_id AS BIGINT) AS customer_id, CAST(s.ext_id AS BIGINT) AS staff_id,
       p.rental_id, CAST(p.amount AS DOUBLE) / 100 AS amount,
       DATE_FORMAT(p.event_time, 'yyyy-MM-dd HH:mm:ss') || '.000' AS payment_date,
       p.last_update
FROM payment_taken p JOIN customer c ON c.customer_id = p.customer_id
JOIN staff s ON s.staff_id = p.staff_id;

-- table: rental
SELECT r.rental_id,
       DATE_FORMAT(r.event_time, 'yyyy-MM-dd HH:mm:ss') || '.000' AS rental_date,
       CAST(i.ext_id AS BIGINT) AS inventory_id, CAST(c.ext_id AS BIGINT) AS customer_id,
       DATE_FORMAT(b.event_time, 'yyyy-MM-dd HH:mm:ss') || '.000' AS return_date,
       CAST(s.ext_id AS BIGINT) AS staff_id, r.last_update
FROM rental_started r JOIN inventory i ON i.inventory_id = r.inventory_id
JOIN customer c ON c.customer_id = r.customer_id
JOIN staff s ON s.staff_id = r.staff_id
LEFT JOIN rental_returned b ON b.rental_id = r.rental_id;
