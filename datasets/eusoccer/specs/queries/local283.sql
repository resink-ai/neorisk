-- local283: the champion of each league-season on 3/1/0 points, with its league, country and
-- points. Written from the question (no gold SQL); reproduces gold variant a (local283_a.csv,
-- 88 rows) exactly. Points tie for first twice (Belgium 2008/09 on 77, England 2011/12 on 89);
-- goal difference breaks the ties as the gold did (Anderlecht +45 over Standard +40, Manchester
-- City +64 over Manchester United +56), then team_api_id.
WITH r AS (
    SELECT season, league_id, home_team_api_id AS team, home_team_goal AS gf,
           away_team_goal AS ga FROM Match
    UNION ALL
    SELECT season, league_id, away_team_api_id, away_team_goal, home_team_goal FROM Match
),
p AS (SELECT season, league_id, team,
             sum(CASE WHEN gf > ga THEN 3 WHEN gf = ga THEN 1 ELSE 0 END) AS pts,
             sum(gf) - sum(ga) AS gd
      FROM r GROUP BY season, league_id, team),
k AS (SELECT p.*, row_number() OVER (PARTITION BY season, league_id
                                     ORDER BY pts DESC, gd DESC, team) AS rk FROM p)
SELECT k.season, t.team_long_name AS champion_team, l.name AS league, c.name AS country,
       k.pts AS total_points
FROM k JOIN Team t ON t.team_api_id = k.team
JOIN League l ON l.id = k.league_id JOIN Country c ON c.id = l.country_id
WHERE k.rk = 1
ORDER BY k.season, l.name;
