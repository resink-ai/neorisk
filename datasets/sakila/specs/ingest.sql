-- Sakila: source tables → events (refdata ingest). film_text is empty and has no pack table.
-- Snapshots at N = 2006-02-15 00:00:00, the day after the last rental and payment (a rule).

-- entity: language
SELECT CAST(language_id AS TEXT) AS ext_id, name FROM language ORDER BY language_id;

-- entity: country
SELECT CAST(country_id AS TEXT) AS ext_id, country FROM country ORDER BY country_id;

-- entity: city
SELECT CAST(city_id AS TEXT) AS ext_id, city, CAST(country_id AS TEXT) AS country_id
FROM city ORDER BY city_id;

-- entity: address
SELECT CAST(address_id AS TEXT) AS ext_id, address, address2, district,
       CAST(city_id AS TEXT) AS city_id, postal_code
FROM address ORDER BY address_id;

-- entity: store
SELECT CAST(store_id AS TEXT) AS ext_id FROM store ORDER BY store_id;

-- entity: staff
SELECT CAST(staff_id AS TEXT) AS ext_id, first_name, last_name, CAST(store_id AS TEXT) AS store_id,
       username
FROM staff ORDER BY staff_id;

-- entity: customer
SELECT CAST(customer_id AS TEXT) AS ext_id, first_name, last_name,
       CAST(address_id AS TEXT) AS address_id
FROM customer ORDER BY customer_id;

-- entity: actor
SELECT CAST(actor_id AS TEXT) AS ext_id, first_name, last_name FROM actor ORDER BY actor_id;

-- entity: category
SELECT CAST(category_id AS TEXT) AS ext_id, name FROM category ORDER BY category_id;

-- entity: film
SELECT CAST(f.film_id AS TEXT) AS ext_id, f.title, f.description, f.release_year,
       CAST(f.language_id AS TEXT) AS language_id,
       CAST(f.original_language_id AS TEXT) AS original_language_id, f.length, f.rating,
       f.special_features, CAST(c.category_id AS TEXT) AS category_id
FROM film f JOIN film_category c USING (film_id) ORDER BY f.film_id;

-- entity: film_actor
SELECT actor_id || '/' || film_id AS ext_id, CAST(actor_id AS TEXT) AS actor_id,
       CAST(film_id AS TEXT) AS film_id
FROM film_actor ORDER BY actor_id, film_id;

-- entity: inventory
SELECT CAST(inventory_id AS TEXT) AS ext_id, CAST(film_id AS TEXT) AS film_id,
       CAST(store_id AS TEXT) AS store_id
FROM inventory ORDER BY inventory_id;

-- event: rental_started owner=customer_id ord=k
SELECT substr(rental_date, 1, 19) AS event_time, CAST(customer_id AS TEXT) AS customer_id,
       rental_id, CAST(inventory_id AS TEXT) AS inventory_id, CAST(staff_id AS TEXT) AS staff_id,
       last_update, 0 AS k
FROM rental ORDER BY rental_id;

-- event: payment_taken owner=customer_id ord=k
-- At its rental's time, after the rental (k = 1).
SELECT substr(payment_date, 1, 19) AS event_time, CAST(customer_id AS TEXT) AS customer_id,
       payment_id, rental_id, CAST(staff_id AS TEXT) AS staff_id,
       CAST(round(amount * 100) AS INTEGER) AS amount, last_update, 1 AS k
FROM payment ORDER BY payment_id;

-- event: rental_returned owner=customer_id
SELECT substr(return_date, 1, 19) AS event_time, CAST(customer_id AS TEXT) AS customer_id,
       rental_id
FROM rental WHERE return_date IS NOT NULL ORDER BY rental_id;

-- event: language_snapshot owner=language_id
SELECT '2006-02-15 00:00:00' AS event_time, CAST(language_id AS TEXT) AS language_id, last_update
FROM language ORDER BY language_id;

-- event: country_snapshot owner=country_id
SELECT '2006-02-15 00:00:00' AS event_time, CAST(country_id AS TEXT) AS country_id, last_update
FROM country ORDER BY country_id;

-- event: city_snapshot owner=city_id
SELECT '2006-02-15 00:00:00' AS event_time, CAST(city_id AS TEXT) AS city_id, last_update FROM city ORDER BY city_id;

-- event: address_snapshot owner=address_id
SELECT '2006-02-15 00:00:00' AS event_time, CAST(address_id AS TEXT) AS address_id, phone, last_update
FROM address ORDER BY address_id;

-- event: store_snapshot owner=store_id
SELECT '2006-02-15 00:00:00' AS event_time, CAST(store_id AS TEXT) AS store_id,
       CAST(manager_staff_id AS TEXT) AS manager_staff_id, CAST(address_id AS TEXT) AS address_id,
       last_update
FROM store ORDER BY store_id;

-- event: staff_snapshot owner=staff_id
SELECT '2006-02-15 00:00:00' AS event_time, CAST(staff_id AS TEXT) AS staff_id, CAST(address_id AS TEXT) AS address_id,
       email, active, password, last_update
FROM staff ORDER BY staff_id;

-- event: customer_snapshot owner=customer_id
SELECT '2006-02-15 00:00:00' AS event_time, CAST(customer_id AS TEXT) AS customer_id, CAST(store_id AS TEXT) AS store_id,
       email, active, create_date, last_update
FROM customer ORDER BY customer_id;

-- event: actor_snapshot owner=actor_id
SELECT '2006-02-15 00:00:00' AS event_time, CAST(actor_id AS TEXT) AS actor_id, last_update FROM actor ORDER BY actor_id;

-- event: category_snapshot owner=category_id
SELECT '2006-02-15 00:00:00' AS event_time, CAST(category_id AS TEXT) AS category_id, last_update
FROM category ORDER BY category_id;

-- event: film_snapshot owner=film_id
SELECT '2006-02-15 00:00:00' AS event_time, CAST(f.film_id AS TEXT) AS film_id, f.rental_duration,
       CAST(round(f.rental_rate * 100) AS INTEGER) AS rental_rate,
       CAST(round(f.replacement_cost * 100) AS INTEGER) AS replacement_cost, f.last_update,
       c.last_update AS film_category_last_update
FROM film f JOIN film_category c USING (film_id) ORDER BY f.film_id;

-- event: film_actor_snapshot owner=film_actor_id
SELECT '2006-02-15 00:00:00' AS event_time, actor_id || '/' || film_id AS film_actor_id, last_update
FROM film_actor ORDER BY actor_id, film_id;

-- event: inventory_snapshot owner=inventory_id
SELECT '2006-02-15 00:00:00' AS event_time, CAST(inventory_id AS TEXT) AS inventory_id, last_update
FROM inventory ORDER BY inventory_id;
