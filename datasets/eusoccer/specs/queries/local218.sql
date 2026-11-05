-- local218: the median, over teams, of each team's highest season goal total.
-- Written from the question (no gold SQL); reproduces gold variant a (local218_a.csv, 48.000).
WITH r AS (
    SELECT season, home_team_api_id AS team, home_team_goal AS gf FROM Match
    UNION ALL
    SELECT season, away_team_api_id, away_team_goal FROM Match
),
s AS (SELECT team, season, sum(gf) AS g FROM r GROUP BY team, season),
m AS (SELECT team, max(g) AS g FROM s GROUP BY team),
o AS (SELECT g, row_number() OVER (ORDER BY g, team) AS rn, count(*) OVER () AS n FROM m)
SELECT avg(g) AS median_highest_season_goals FROM o WHERE rn IN ((n + 1) / 2, (n + 2) / 2);
