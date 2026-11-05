-- local221: the top 10 teams by total wins, home and away.
-- Written from the question (no gold SQL); reproduces gold variant a (local221_a.csv) exactly,
-- in order. There is no tie at the cut (10th 180, 11th 178); team_api_id breaks any other tie.
WITH r AS (
    SELECT home_team_api_id AS team, home_team_goal AS gf, away_team_goal AS ga FROM Match
    UNION ALL
    SELECT away_team_api_id, away_team_goal, home_team_goal FROM Match
)
SELECT t.team_long_name, sum(r.gf > r.ga) AS total_wins
FROM r JOIN Team t ON t.team_api_id = r.team
GROUP BY r.team, t.team_long_name
ORDER BY total_wins DESC, r.team
LIMIT 10;
