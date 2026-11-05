-- imdb_movies: events → source tables (refdata rebuild, DuckDB).

-- table: ERD
-- The 8 REAL columns are empty in every row of the spreadsheet.
SELECT "table", "column", NULL::DOUBLE AS "Unnamed: 2", NULL::DOUBLE AS "Unnamed: 3",
       NULL::DOUBLE AS "Unnamed: 4", NULL::DOUBLE AS "Unnamed: 5", u6 AS "Unnamed: 6",
       NULL::DOUBLE AS "Unnamed: 7", NULL::DOUBLE AS "Unnamed: 8", u9 AS "Unnamed: 9",
       NULL::DOUBLE AS "Unnamed: 10", NULL::DOUBLE AS "Unnamed: 11", u12 AS "Unnamed: 12"
FROM erd;

-- table: movies
-- year and date_published both come from the publication time; the gross gets its '$ ' back.
SELECT m.ext_id AS id, m.title AS title,
       CAST(strftime(m.created_at AT TIME ZONE 'UTC', '%Y') AS BIGINT) AS year,
       strftime(m.created_at AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S') AS date_published,
       m.duration AS duration, m.country AS country,
       '$ ' || CAST(s.worldwide_gross_usd AS VARCHAR) AS worlwide_gross_income,
       m.languages AS languages, m.production_company AS production_company
FROM movies m LEFT JOIN movies_snapshot s USING (movie_id);

-- table: genre
SELECT m.ext_id AS movie_id, g.genre AS genre FROM movie_genre_tagged g JOIN movies m USING (movie_id);

-- table: director_mapping
SELECT m.ext_id AS movie_id, n.ext_id AS name_id
FROM director_credited d JOIN movies m USING (movie_id) JOIN names n ON n.name_id = d.person_id;

-- table: role_mapping
SELECT m.ext_id AS movie_id, n.ext_id AS name_id, r.category AS category
FROM cast_credited r JOIN movies m USING (movie_id) JOIN names n ON n.name_id = r.person_id;

-- table: names
SELECT n.ext_id AS id, n.name AS name, CAST(s.height AS DOUBLE) AS height,
       n.date_of_birth AS date_of_birth, s.known_for_movies AS known_for_movies
FROM names n LEFT JOIN names_snapshot s USING (name_id);

-- table: ratings
SELECT m.ext_id AS movie_id, r.avg_rating AS avg_rating, r.total_votes AS total_votes,
       r.median_rating AS median_rating
FROM movie_rated r JOIN movies m USING (movie_id);
