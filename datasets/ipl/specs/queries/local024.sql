-- local024: the top 5 countries by the mean of their players' average runs per match.
-- No gold SQL; written from the question. Reproduces local024_a.csv (England 14.563182 ...):
-- a player's average is over every match he is named in, 0 when he did not score.
WITH r AS (
    SELECT b.striker AS p, b.match_id, sum(s.runs_scored) AS runs
    FROM ball_by_ball b
    JOIN batsman_scored s USING (match_id, over_id, ball_id, innings_no)
    GROUP BY 1, 2
),
pa AS (
    SELECT pm.player_id AS p, avg(coalesce(r.runs, 0)) AS a
    FROM player_match pm
    LEFT JOIN r ON r.p = pm.player_id AND r.match_id = pm.match_id
    GROUP BY 1
)
SELECT pl.country_name, avg(pa.a) AS country_batting_average
FROM pa JOIN player pl ON pl.player_id = pa.p
GROUP BY 1
ORDER BY 2 DESC
LIMIT 5;
