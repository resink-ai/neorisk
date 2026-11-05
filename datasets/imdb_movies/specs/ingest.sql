-- imdb_movies: source tables → events (refdata ingest).
-- Times (docs/research/spider2/imdbmovies.md §2): a movie at its date_published (natural);
-- its genre tags and credits at the same time (a rule); a person at their first credited
-- publication, else at the catalog start 2017-01-01 like the ERD rows (rules); ratings,
-- gross, heights and known-for lists at N = 2020-01-01 (a rule).

-- entity: erd
SELECT "table" || '.' || "column" AS ext_id, '2017-01-01 00:00:00' AS created_at,
       "table" AS "table", "column" AS "column", "Unnamed: 6" AS u6, "Unnamed: 9" AS u9,
       "Unnamed: 12" AS u12
FROM ERD ORDER BY "table", "column";

-- entity: names
WITH credit AS (SELECT movie_id, name_id FROM director_mapping
                UNION ALL SELECT movie_id, name_id FROM role_mapping),
first AS (SELECT c.name_id, min(m.date_published) AS dp
          FROM credit c JOIN movies m ON m.id = c.movie_id GROUP BY c.name_id)
SELECT n.id AS ext_id, coalesce(iso_time(f.dp, '%Y-%m-%d %H:%M:%S'), '2017-01-01 00:00:00')
         AS created_at,
       n.name AS name, n.date_of_birth AS date_of_birth
FROM names n LEFT JOIN first f ON f.name_id = n.id ORDER BY n.id;

-- entity: movies event=movie_released
SELECT id AS ext_id, iso_time(date_published, '%Y-%m-%d %H:%M:%S') AS created_at,
       title, duration, country, languages, production_company
FROM movies ORDER BY date_published, id;

-- event: movie_genre_tagged owner=movie_id
SELECT iso_time(m.date_published, '%Y-%m-%d %H:%M:%S') AS event_time, g.movie_id, g.genre
FROM genre g JOIN movies m ON m.id = g.movie_id ORDER BY g.movie_id, g.genre;

-- event: director_credited owner=movie_id
SELECT iso_time(m.date_published, '%Y-%m-%d %H:%M:%S') AS event_time, d.movie_id,
       d.name_id AS person_id
FROM director_mapping d JOIN movies m ON m.id = d.movie_id ORDER BY d.movie_id, d.name_id;

-- event: cast_credited owner=movie_id
SELECT iso_time(m.date_published, '%Y-%m-%d %H:%M:%S') AS event_time, r.movie_id,
       r.name_id AS person_id, r.category
FROM role_mapping r JOIN movies m ON m.id = r.movie_id ORDER BY r.movie_id, r.name_id;

-- event: movie_rated owner=movie_id
SELECT '2020-01-01 00:00:00' AS event_time, movie_id, avg_rating, total_votes, median_rating
FROM ratings ORDER BY movie_id;

-- event: movies_snapshot owner=movie_id
-- The gross is always '$ ' and plain digits, so it travels as integer dollars.
SELECT '2020-01-01 00:00:00' AS event_time, id AS movie_id,
       CAST(substr(worlwide_gross_income, 3) AS INTEGER) AS worldwide_gross_usd
FROM movies WHERE worlwide_gross_income IS NOT NULL ORDER BY id;

-- event: names_snapshot owner=name_id
SELECT '2020-01-01 00:00:00' AS event_time, id AS name_id, CAST(height AS INTEGER) AS height,
       known_for_movies
FROM names WHERE height IS NOT NULL OR known_for_movies IS NOT NULL ORDER BY id;
