-- Aliens: events → source tables (refdata rebuild, DuckDB).

-- table: aliens
SELECT CAST(a.ext_id AS BIGINT) AS id, a.first_name, a.last_name, s.email,
       CAST(s.gender AS VARCHAR) AS gender, CAST(a.type AS VARCHAR) AS type, a.birth_year
FROM aliens a LEFT JOIN aliens_snapshot s ON s.alien = a.alien_id ORDER BY id;

-- table: aliens_details
SELECT CAST(a.ext_id AS BIGINT) AS detail_id, s.favorite_food,
       CAST(s.feeding_frequency AS VARCHAR) AS feeding_frequency, s.aggressive
FROM aliens a LEFT JOIN aliens_snapshot s ON s.alien = a.alien_id ORDER BY detail_id;

-- table: aliens_location
SELECT CAST(a.ext_id AS BIGINT) AS loc_id, s.current_location, s.state, s.country, s.occupation
FROM aliens a LEFT JOIN aliens_snapshot s ON s.alien = a.alien_id ORDER BY loc_id;

-- table: alien_data
-- Every text column lowered; the name 'Nan' became NULL (pandas read it as NaN); gender folds
-- the six others into 'non-binary'; age = 2024 - birth_year; us_region is the state's BEA region.
WITH rm(state, us_region) AS (VALUES
  ('california', 'far west'), ('washington', 'far west'), ('hawaii', 'far west'),
  ('oregon', 'far west'), ('alaska', 'far west'), ('nevada', 'far west'),
  ('ohio', 'great lakes'), ('michigan', 'great lakes'), ('illinois', 'great lakes'),
  ('wisconsin', 'great lakes'), ('indiana', 'great lakes'),
  ('maryland', 'mideast'), ('pennsylvania', 'mideast'), ('new jersey', 'mideast'),
  ('district of columbia', 'mideast'), ('new york', 'mideast'), ('delaware', 'mideast'),
  ('connecticut', 'new england'), ('rhode island', 'new england'),
  ('massachusetts', 'new england'), ('maine', 'new england'), ('new hampshire', 'new england'),
  ('vermont', 'new england'),
  ('nebraska', 'plains'), ('missouri', 'plains'), ('kansas', 'plains'),
  ('south dakota', 'plains'), ('minnesota', 'plains'), ('iowa', 'plains'),
  ('north dakota', 'plains'),
  ('utah', 'rocky mountain'), ('montana', 'rocky mountain'), ('colorado', 'rocky mountain'),
  ('idaho', 'rocky mountain'), ('wyoming', 'rocky mountain'),
  ('virginia', 'southeast'), ('georgia', 'southeast'), ('florida', 'southeast'),
  ('north carolina', 'southeast'), ('arkansas', 'southeast'), ('kentucky', 'southeast'),
  ('tennessee', 'southeast'), ('alabama', 'southeast'), ('west virginia', 'southeast'),
  ('louisiana', 'southeast'), ('south carolina', 'southeast'), ('mississippi', 'southeast'),
  ('texas', 'southwest'), ('oklahoma', 'southwest'), ('arizona', 'southwest'),
  ('new mexico', 'southwest'))
SELECT CAST(a.ext_id AS BIGINT) AS id,
       CASE WHEN a.first_name = 'Nan' THEN NULL ELSE lower(a.first_name) END AS first_name,
       lower(a.last_name) AS last_name, s.email,
       CASE CAST(s.gender AS VARCHAR) WHEN 'Female' THEN 'female' WHEN 'Male' THEN 'male'
            ELSE 'non-binary' END AS gender,
       lower(CAST(a.type AS VARCHAR)) AS type, a.birth_year, 2024 - a.birth_year AS age,
       lower(s.favorite_food) AS favorite_food,
       lower(CAST(s.feeding_frequency AS VARCHAR)) AS feeding_frequency, s.aggressive,
       lower(s.occupation) AS occupation, lower(s.current_location) AS current_location,
       lower(s.state) AS state, rm.us_region, lower(s.country) AS country
FROM aliens a LEFT JOIN aliens_snapshot s ON s.alien = a.alien_id
LEFT JOIN rm ON rm.state = lower(s.state)
ORDER BY id;
