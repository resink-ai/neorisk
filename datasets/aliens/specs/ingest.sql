-- Aliens: source tables → events (refdata ingest). alien_data is not read: build.sql derives it.
-- No source time: every row takes the rule time 2024-01-01 (alien_data.age = 2024 - birth_year).

-- entity: aliens
SELECT CAST(id AS TEXT) AS ext_id, first_name, last_name, type, birth_year,
       '2024-01-01 00:00:00' AS created_at
FROM aliens ORDER BY id;

-- event: aliens_snapshot owner=alien
-- The three tables are 1:1 on id = detail_id = loc_id, with no orphans.
SELECT '2024-01-01 00:00:00' AS event_time, CAST(a.id AS TEXT) AS alien, a.email, a.gender,
       d.favorite_food, d.feeding_frequency, d.aggressive, l.current_location, l.state,
       l.country, l.occupation
FROM aliens a JOIN aliens_details d ON d.detail_id = a.id JOIN aliens_location l ON l.loc_id = a.id
ORDER BY a.id;
