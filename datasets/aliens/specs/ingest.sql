-- Aliens: source tables → events (refdata ingest). alien_data is not read: build.sql derives it.
-- No source time: every row takes the rule time 2024-01-01 (alien_data.age = 2024 - birth_year).

-- entity: aliens
SELECT CAST(a.id AS TEXT) AS ext_id, a.first_name, a.last_name, a.email, a.gender, a.type,
       a.birth_year, d.favorite_food, d.feeding_frequency, d.aggressive,
       '2024-01-01 00:00:00' AS created_at
FROM aliens a JOIN aliens_details d ON d.detail_id = a.id ORDER BY a.id;

-- event: aliens_snapshot owner=alien
SELECT '2024-01-01 00:00:00' AS event_time, CAST(loc_id AS TEXT) AS alien, current_location,
       state, country, occupation
FROM aliens_location ORDER BY loc_id;
