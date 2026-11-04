-- local152: the top 9 directors by movie count, then total duration: id, name, movie count,
-- mean days between consecutive publications (rounded), mean rating (2 dp), total votes,
-- min and max rating, total duration.
-- Written from the question (no gold SQL). Reproduces gold variant local152_a.csv on all 9
-- rows and every column but the mean rating of 2 rows, which sit on a half-cent tie:
-- Soderbergh 6.47 (gold 6.48) and Sam Liu 6.22 (gold 6.23); SQLite's round on the binary
-- double goes down there. name_id is a last tie-break, for a deterministic order.
WITH d AS (
    SELECT dm.name_id, n.name, m.id, m.date_published AS dp, m.duration, r.avg_rating,
           r.total_votes
    FROM director_mapping dm JOIN names n ON n.id = dm.name_id
    JOIN movies m ON m.id = dm.movie_id JOIN ratings r ON r.movie_id = m.id),
g AS (SELECT name_id,
             julianday(dp) - julianday(lag(dp) OVER (PARTITION BY name_id ORDER BY dp)) AS gap
      FROM d)
SELECT d.name_id AS DIRECTOR_ID, d.name AS DIRECTOR_NAME, count(*) AS MOVIE_COUNT,
       (SELECT round(avg(gap)) FROM g WHERE g.name_id = d.name_id) AS AVG_INTER_MOVIE_DURATION,
       round(avg(avg_rating), 2) AS AVG_RATING, sum(total_votes) AS TOTAL_VOTES,
       min(avg_rating) AS MIN_RATING, max(avg_rating) AS MAX_RATING,
       sum(duration) AS TOTAL_MOVIE_DURATION
FROM d GROUP BY d.name_id
ORDER BY MOVIE_COUNT DESC, TOTAL_MOVIE_DURATION DESC, DIRECTOR_ID LIMIT 9;
