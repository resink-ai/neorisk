-- local220: the player in the most won matches and the player in the most lost matches
-- (filled lineup slots only; draws excluded; each match counted once per player).
-- Written from the question (no gold SQL); reproduces gold variant b (local220_b.csv) exactly:
-- Cristiano Ronaldo 199 wins (27 losses), Gorka Iraizoz Moreno 107 losses (114 wins).
WITH slots AS (
    SELECT id AS mid, home_player_1 AS pid, home_team_goal - away_team_goal AS d FROM Match
    UNION ALL SELECT id, home_player_2, home_team_goal - away_team_goal FROM Match
    UNION ALL SELECT id, home_player_3, home_team_goal - away_team_goal FROM Match
    UNION ALL SELECT id, home_player_4, home_team_goal - away_team_goal FROM Match
    UNION ALL SELECT id, home_player_5, home_team_goal - away_team_goal FROM Match
    UNION ALL SELECT id, home_player_6, home_team_goal - away_team_goal FROM Match
    UNION ALL SELECT id, home_player_7, home_team_goal - away_team_goal FROM Match
    UNION ALL SELECT id, home_player_8, home_team_goal - away_team_goal FROM Match
    UNION ALL SELECT id, home_player_9, home_team_goal - away_team_goal FROM Match
    UNION ALL SELECT id, home_player_10, home_team_goal - away_team_goal FROM Match
    UNION ALL SELECT id, home_player_11, home_team_goal - away_team_goal FROM Match
    UNION ALL SELECT id, away_player_1, away_team_goal - home_team_goal FROM Match
    UNION ALL SELECT id, away_player_2, away_team_goal - home_team_goal FROM Match
    UNION ALL SELECT id, away_player_3, away_team_goal - home_team_goal FROM Match
    UNION ALL SELECT id, away_player_4, away_team_goal - home_team_goal FROM Match
    UNION ALL SELECT id, away_player_5, away_team_goal - home_team_goal FROM Match
    UNION ALL SELECT id, away_player_6, away_team_goal - home_team_goal FROM Match
    UNION ALL SELECT id, away_player_7, away_team_goal - home_team_goal FROM Match
    UNION ALL SELECT id, away_player_8, away_team_goal - home_team_goal FROM Match
    UNION ALL SELECT id, away_player_9, away_team_goal - home_team_goal FROM Match
    UNION ALL SELECT id, away_player_10, away_team_goal - home_team_goal FROM Match
    UNION ALL SELECT id, away_player_11, away_team_goal - home_team_goal FROM Match
),
s AS (SELECT DISTINCT mid, pid, CASE WHEN d > 0 THEN 'W' WHEN d < 0 THEN 'L' ELSE 'D' END AS r
      FROM slots WHERE pid IS NOT NULL),
c AS (SELECT pid, sum(r = 'W') AS w, sum(r = 'L') AS l FROM s GROUP BY pid)
SELECT 'most_wins' AS metric, p.player_api_id, p.player_name, c.w AS wins, c.l AS losses
FROM c JOIN Player p ON p.player_api_id = c.pid WHERE c.w = (SELECT max(w) FROM c)
UNION ALL
SELECT 'most_losses', p.player_api_id, p.player_name, c.w, c.l
FROM c JOIN Player p ON p.player_api_id = c.pid WHERE c.l = (SELECT max(l) FROM c);
