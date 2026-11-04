-- local039: film category with the most rental hours in cities starting with 'a' or containing '-'.
-- Gold SQL from xlang-ai/Spider2 spider2-lite/evaluation_suite/gold/sql/local039.sql.
SELECT category.name
FROM category
INNER JOIN film_category USING (category_id)
INNER JOIN film USING (film_id)
INNER JOIN inventory USING (film_id)
INNER JOIN rental USING (inventory_id)
INNER JOIN customer USING (customer_id)
INNER JOIN address USING (address_id)
INNER JOIN city USING (city_id)
WHERE LOWER(city.city) LIKE 'a%' OR city.city LIKE '%-%'
GROUP BY category.name
ORDER BY SUM(CAST((julianday(rental.return_date) - julianday(rental.rental_date)) * 24 AS INTEGER)) DESC
LIMIT 1;
