-- local230: the 3 genres with the most movies rated above 8 (Drama, Action, Comedy), then the
-- 4 directors with the most films rated above 8 in those genres, with their counts.
-- Written from the question (no gold SQL). Reproduces gold variant local230_a.csv, 4 of 4 rows
-- (four directors tie at 2; the name order breaks the tie, as in the gold CSV).
WITH tg AS (
    SELECT g.genre FROM genre g JOIN ratings r USING (movie_id) WHERE r.avg_rating > 8
    GROUP BY 1 ORDER BY count(DISTINCT g.movie_id) DESC LIMIT 3)
SELECT n.name AS director, count(DISTINCT dm.movie_id) AS movie_count
FROM director_mapping dm JOIN names n ON n.id = dm.name_id
JOIN ratings r ON r.movie_id = dm.movie_id JOIN genre g ON g.movie_id = dm.movie_id
WHERE r.avg_rating > 8 AND g.genre IN (SELECT genre FROM tg)
GROUP BY dm.name_id ORDER BY movie_count DESC, director LIMIT 4;
