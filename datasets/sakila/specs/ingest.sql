-- Sakila: source tables → events (refdata ingest). film_text is empty and has no pack table.

-- entity: language
SELECT CAST(language_id AS TEXT) AS ext_id, name, last_update FROM language ORDER BY language_id;

-- entity: country
SELECT CAST(country_id AS TEXT) AS ext_id, country, last_update FROM country ORDER BY country_id;

-- entity: city
SELECT CAST(city_id AS TEXT) AS ext_id, city, CAST(country_id AS TEXT) AS country_id, last_update
FROM city ORDER BY city_id;

-- entity: address
SELECT CAST(address_id AS TEXT) AS ext_id, address, address2, district,
       CAST(city_id AS TEXT) AS city_id, postal_code, phone, last_update
FROM address ORDER BY address_id;

-- entity: store
SELECT CAST(store_id AS TEXT) AS ext_id, CAST(manager_staff_id AS TEXT) AS manager_staff_id,
       CAST(address_id AS TEXT) AS address_id, last_update
FROM store ORDER BY store_id;

-- entity: staff
SELECT CAST(staff_id AS TEXT) AS ext_id, first_name, last_name, CAST(address_id AS TEXT) AS address_id,
       email, CAST(store_id AS TEXT) AS store_id, active, username, password, last_update
FROM staff ORDER BY staff_id;

-- entity: customer
SELECT CAST(customer_id AS TEXT) AS ext_id, CAST(store_id AS TEXT) AS store_id, first_name,
       last_name, email, CAST(address_id AS TEXT) AS address_id, active, create_date, last_update
FROM customer ORDER BY customer_id;

-- entity: actor
SELECT CAST(actor_id AS TEXT) AS ext_id, first_name, last_name, last_update
FROM actor ORDER BY actor_id;

-- entity: category
SELECT CAST(category_id AS TEXT) AS ext_id, name, last_update FROM category ORDER BY category_id;

-- entity: film
SELECT CAST(f.film_id AS TEXT) AS ext_id, f.title, f.description, f.release_year,
       CAST(f.language_id AS TEXT) AS language_id,
       CAST(f.original_language_id AS TEXT) AS original_language_id, f.rental_duration,
       CAST(round(f.rental_rate * 100) AS INTEGER) AS rental_rate, f.length,
       CAST(round(f.replacement_cost * 100) AS INTEGER) AS replacement_cost, f.rating,
       f.special_features, f.last_update, CAST(c.category_id AS TEXT) AS category_id,
       c.last_update AS film_category_last_update
FROM film f JOIN film_category c USING (film_id) ORDER BY f.film_id;

-- entity: film_actor
SELECT actor_id || '/' || film_id AS ext_id, CAST(actor_id AS TEXT) AS actor_id,
       CAST(film_id AS TEXT) AS film_id, last_update
FROM film_actor ORDER BY actor_id, film_id;

-- entity: inventory
SELECT CAST(inventory_id AS TEXT) AS ext_id, CAST(film_id AS TEXT) AS film_id,
       CAST(store_id AS TEXT) AS store_id, last_update
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
