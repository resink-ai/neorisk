-- dbimdb: events → source tables (refdata rebuild, DuckDB).
-- pandas wrote every table with an "index" column; the link tables' ID equals it. The five
-- 1-per-movie tables are row i of Movie, so their index and ID are the movie's src_index.

-- table: Movie
SELECT m.src_index AS "index", m.ext_id AS MID, m.title AS title,
       coalesce(s.disambig || ' ', '') || strftime(m.created_at AT TIME ZONE 'UTC', '%Y') AS year,
       s.rating AS rating, s.num_votes AS num_votes
FROM movies m LEFT JOIN movies_snapshot s USING (movie_id);

-- table: Genre
SELECT CAST(ext_id AS BIGINT) AS "index", name AS Name, CAST(ext_id AS BIGINT) AS GID FROM genres;

-- table: Language
SELECT CAST(ext_id AS BIGINT) AS "index", name AS Name, CAST(ext_id AS BIGINT) AS LAID
FROM languages;

-- table: Country
SELECT CAST(ext_id AS BIGINT) AS "index", name AS Name, CAST(ext_id AS BIGINT) AS CID
FROM countries;

-- table: Location
SELECT CAST(ext_id AS BIGINT) AS "index", name AS Name, CAST(ext_id AS BIGINT) AS LID
FROM locations;

-- table: M_Location
-- LID is REAL in the source: pandas' NaN for a missing location made the column float.
SELECT m.src_index AS "index", m.ext_id AS MID, CAST(l.ext_id AS DOUBLE) AS LID,
       m.src_index AS ID
FROM movies m LEFT JOIN locations l USING (location_id);

-- table: M_Country
SELECT m.src_index AS "index", m.ext_id AS MID, CAST(c.ext_id AS DOUBLE) AS CID,
       m.src_index AS ID
FROM movies m LEFT JOIN countries c USING (country_id);

-- table: M_Language
SELECT m.src_index AS "index", m.ext_id AS MID, CAST(l.ext_id AS BIGINT) AS LAID,
       m.src_index AS ID
FROM movies m JOIN languages l USING (language_id);

-- table: M_Genre
SELECT m.src_index AS "index", m.ext_id AS MID, CAST(g.ext_id AS BIGINT) AS GID,
       m.src_index AS ID
FROM movies m JOIN genres g USING (genre_id);

-- table: M_Director
SELECT m.src_index AS "index", m.ext_id AS MID, p.ext_id AS PID, m.src_index AS ID
FROM movies m JOIN persons p ON p.person_id = m.director_id;

-- table: M_Cast
-- Rows in movie order, then billing; the scraper kept the HTML's leading space in the PID.
SELECT row_number() OVER (ORDER BY m.src_index, c.billing) - 1 AS "index", m.ext_id AS MID,
       ' ' || p.ext_id AS PID, row_number() OVER (ORDER BY m.src_index, c.billing) - 1 AS ID
FROM cast_credited c JOIN movies m USING (movie_id) LEFT JOIN persons p USING (person_id);

-- table: M_Producer
SELECT row_number() OVER (ORDER BY m.src_index, x.position) - 1 AS "index", m.ext_id AS MID,
       ' ' || p.ext_id AS PID, row_number() OVER (ORDER BY m.src_index, x.position) - 1 AS ID
FROM producer_credited x JOIN movies m USING (movie_id) LEFT JOIN persons p USING (person_id);

-- table: Person
-- A first-seen dump of the credit stream (dbimdb.md §3.1). Block 1: the distinct people of
-- M_Cast then M_Producer, in order of first credit, with the leading space in the name and a
-- missing PID kept as one all-NULL row. Block 2: the distinct directors in movie order,
-- unpadded. A full-row drop_duplicates keeps both copies of people in both blocks.
WITH cast_pos AS (
    SELECT c.person_id, row_number() OVER (ORDER BY m.src_index, c.billing) AS pos
    FROM cast_credited c JOIN movies m USING (movie_id)),
producer_pos AS (
    SELECT x.person_id,
           (SELECT count(*) FROM cast_credited)
             + row_number() OVER (ORDER BY m.src_index, x.position) AS pos
    FROM producer_credited x JOIN movies m USING (movie_id)),
credited AS (
    SELECT person_id, min(pos) AS first
    FROM (SELECT * FROM cast_pos UNION ALL SELECT * FROM producer_pos) GROUP BY person_id),
directed AS (SELECT director_id AS person_id, min(src_index) AS first FROM movies GROUP BY 1),
listed AS (
    SELECT 1 AS block, first, person_id FROM credited
    UNION ALL SELECT 2, first, person_id FROM directed)
SELECT row_number() OVER (ORDER BY l.block, l.first) - 1 AS "index", p.ext_id AS PID,
       CASE WHEN l.block = 1 THEN ' ' || p.name ELSE p.name END AS Name, ps.gender AS Gender
FROM listed l LEFT JOIN persons p ON p.person_id = l.person_id
LEFT JOIN persons_snapshot ps ON ps.person_id = l.person_id;
