-- Sakila: events → source tables (refdata rebuild, DuckDB). Business times end in '.000'.

-- table: language
SELECT CAST(ext_id AS BIGINT) AS language_id, name, last_update FROM language;

-- table: country
SELECT CAST(ext_id AS BIGINT) AS country_id, country, last_update FROM country;

-- table: city
SELECT CAST(c.ext_id AS BIGINT) AS city_id, c.city, CAST(k.ext_id AS BIGINT) AS country_id,
       c.last_update
FROM city c JOIN country k USING (country_id);

-- table: address
SELECT CAST(a.ext_id AS BIGINT) AS address_id, a.address, a.address2, a.district,
       CAST(c.ext_id AS BIGINT) AS city_id, a.postal_code, a.phone, a.last_update
FROM address a JOIN city c USING (city_id);

-- table: store
SELECT CAST(s.ext_id AS BIGINT) AS store_id, CAST(m.ext_id AS BIGINT) AS manager_staff_id,
       CAST(a.ext_id AS BIGINT) AS address_id, s.last_update
FROM store s JOIN staff m ON m.staff_id = s.manager_staff_id JOIN address a
    ON a.address_id = s.address_id;

-- table: staff
SELECT CAST(s.ext_id AS BIGINT) AS staff_id, s.first_name, s.last_name,
       CAST(a.ext_id AS BIGINT) AS address_id, NULL::BLOB AS picture, s.email,
       CAST(t.ext_id AS BIGINT) AS store_id, s.active, s.username, s.password, s.last_update
FROM staff s JOIN address a ON a.address_id = s.address_id JOIN store t ON t.store_id = s.store_id;

-- table: customer
SELECT CAST(c.ext_id AS BIGINT) AS customer_id, CAST(s.ext_id AS BIGINT) AS store_id,
       c.first_name, c.last_name, c.email, CAST(a.ext_id AS BIGINT) AS address_id, c.active,
       c.create_date, c.last_update
FROM customer c JOIN store s ON s.store_id = c.store_id JOIN address a
    ON a.address_id = c.address_id;

-- table: actor
SELECT CAST(ext_id AS BIGINT) AS actor_id, first_name, last_name, last_update FROM actor;

-- table: category
SELECT CAST(ext_id AS BIGINT) AS category_id, name, last_update FROM category;

-- table: film
SELECT CAST(f.ext_id AS BIGINT) AS film_id, f.title, f.description, f.release_year,
       CAST(l.ext_id AS BIGINT) AS language_id, CAST(o.ext_id AS BIGINT) AS original_language_id,
       f.rental_duration, f.rental_rate / 100.0 AS rental_rate, f.length,
       f.replacement_cost / 100.0 AS replacement_cost, f.rating, f.special_features,
       f.last_update
FROM film f JOIN language l ON l.language_id = f.language_id
LEFT JOIN language o ON o.language_id = f.original_language_id;

-- table: film_actor
SELECT CAST(a.ext_id AS BIGINT) AS actor_id, CAST(f.ext_id AS BIGINT) AS film_id, x.last_update
FROM film_actor x JOIN actor a USING (actor_id) JOIN film f USING (film_id);

-- table: film_category
SELECT CAST(f.ext_id AS BIGINT) AS film_id, CAST(c.ext_id AS BIGINT) AS category_id,
       f.film_category_last_update AS last_update
FROM film f JOIN category c USING (category_id);

-- table: film_text
SELECT NULL::BIGINT AS film_id, NULL::VARCHAR AS title, NULL::VARCHAR AS description WHERE false;

-- table: inventory
SELECT CAST(i.ext_id AS BIGINT) AS inventory_id, CAST(f.ext_id AS BIGINT) AS film_id,
       CAST(s.ext_id AS BIGINT) AS store_id, i.last_update
FROM inventory i JOIN film f USING (film_id) JOIN store s USING (store_id);

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
