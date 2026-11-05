-- World cities: events → source tables (refdata rebuild, DuckDB).

-- table: cities
SELECT CAST(c.ext_id AS BIGINT) AS city_id, c.city_name, c.latitude, c.longitude,
       n.ext_id AS country_code_2, s.capital, CAST(s.population AS DOUBLE) AS population,
       strftime(c.created_at AT TIME ZONE 'UTC', '%Y-%m-%d') AS insert_date
FROM cities c JOIN countries n ON n.country_key = c.country
LEFT JOIN cities_snapshot s ON s.city = c.city_key
ORDER BY city_id;

-- table: cities_countries
SELECT n.country_id, n.country_name, n.ext_id AS country_code_2, n.country_code_3, n.region,
       n.sub_region, n.intermediate_region,
       strftime(s.event_time AT TIME ZONE 'UTC', '%Y-%m-%d') AS created_on
FROM countries n LEFT JOIN countries_snapshot s ON s.country = n.country_key
ORDER BY n.country_id;

-- table: cities_currencies
SELECT CAST(c.ext_id AS BIGINT) AS currency_id, n.ext_id AS country_code_2, c.currency_name,
       c.currency_code
FROM currencies c JOIN countries n ON n.country_key = c.country
ORDER BY currency_id;

-- table: cities_languages
SELECT CAST(l.ext_id AS BIGINT) AS language_id, l.language, n.ext_id AS country_code_2
FROM languages l JOIN countries n ON n.country_key = l.country
ORDER BY language_id;
