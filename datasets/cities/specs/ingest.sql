-- World cities: source tables → events (refdata ingest).
-- The lookups have no time: they are created at the catalog start 2021-01-01 (a rule).

-- entity: countries
SELECT country_code_2 AS ext_id, country_id, country_name, country_code_3, region, sub_region,
       intermediate_region, '2021-01-01 00:00:00' AS created_at
FROM cities_countries ORDER BY country_code_2;

-- entity: currencies
SELECT CAST(currency_id AS TEXT) AS ext_id, country_code_2 AS country, currency_name,
       currency_code, '2021-01-01 00:00:00' AS created_at
FROM cities_currencies ORDER BY currency_id;

-- entity: languages
SELECT CAST(language_id AS TEXT) AS ext_id, language, country_code_2 AS country,
       '2021-01-01 00:00:00' AS created_at
FROM cities_languages ORDER BY language_id;

-- entity: cities
-- population is REAL holding whole numbers only; it travels as an integer.
SELECT CAST(city_id AS TEXT) AS ext_id, city_name, latitude, longitude,
       country_code_2 AS country, capital, CAST(population AS INTEGER) AS population,
       iso_time(insert_date, '%Y-%m-%d') AS created_at
FROM cities ORDER BY insert_date, city_id;

-- event: countries_snapshot owner=country
-- created_on is the date the tables were built, after every insert: the snapshot time N.
SELECT iso_time(created_on, '%Y-%m-%d') AS event_time, country_code_2 AS country
FROM cities_countries ORDER BY country_code_2;
