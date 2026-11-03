-- local038: actor with the most English Children films rated G/PG, ≤ 120 min, released 2000–2010.
-- Gold SQL from xlang-ai/Spider2 spider2-lite/evaluation_suite/gold/sql/local038.sql.
SELECT
    actor.first_name || ' ' || actor.last_name AS full_name
FROM actor
INNER JOIN film_actor ON actor.actor_id = film_actor.actor_id
INNER JOIN film ON film_actor.film_id = film.film_id
INNER JOIN film_category ON film.film_id = film_category.film_id
INNER JOIN category ON film_category.category_id = category.category_id
INNER JOIN language ON film.language_id = language.language_id
WHERE category.name = 'Children' AND film.release_year BETWEEN 2000 AND 2010
  AND film.rating IN ('G', 'PG') AND language.name = 'English' AND film.length <= 120
GROUP BY actor.actor_id, actor.first_name, actor.last_name
ORDER BY COUNT(film.film_id) DESC
LIMIT 1;
