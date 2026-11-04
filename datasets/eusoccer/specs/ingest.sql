-- EU_soccer: source tables → events (refdata ingest). sqlite_sequence and the view match_view
-- are not read. Every source time is a date at 00:00:00, read as UTC.
-- Creation times are rules: countries and leagues at their first match, teams at min(first
-- match, first team rating), players at their first rating. N = 2016-07-07 (last rating).

-- entity: countries
SELECT CAST(c.id AS TEXT) AS ext_id, c.name,
       iso_time((SELECT min(m.date) FROM Match m WHERE m.country_id = c.id), '%Y-%m-%d %H:%M:%S')
         AS created_at
FROM Country c ORDER BY c.id;

-- entity: leagues
SELECT CAST(l.id AS TEXT) AS ext_id, CAST(l.country_id AS TEXT) AS country_id, l.name,
       iso_time((SELECT min(m.date) FROM Match m WHERE m.league_id = l.id), '%Y-%m-%d %H:%M:%S')
         AS created_at
FROM League l ORDER BY l.id;

-- entity: teams
WITH firsts(team, d) AS (
  SELECT home_team_api_id, date FROM Match UNION ALL SELECT away_team_api_id, date FROM Match
  UNION ALL SELECT team_api_id, date FROM Team_Attributes),
f AS (SELECT team, min(d) AS d FROM firsts GROUP BY team)
SELECT CAST(t.team_api_id AS TEXT) AS ext_id, t.id AS team_row_id, t.team_fifa_api_id,
       t.team_long_name, t.team_short_name, iso_time(f.d, '%Y-%m-%d %H:%M:%S') AS created_at
FROM Team t JOIN f ON f.team = t.team_api_id ORDER BY t.id;

-- entity: players
WITH f AS (SELECT player_api_id, min(date) AS d FROM Player_Attributes GROUP BY player_api_id)
SELECT CAST(p.player_api_id AS TEXT) AS ext_id, p.id AS player_row_id, p.player_name,
       p.player_fifa_api_id, p.birthday, iso_time(f.d, '%Y-%m-%d %H:%M:%S') AS created_at
FROM Player p JOIN f USING (player_api_id) ORDER BY p.id;

-- event: players_snapshot owner=player_id
-- height and weight at N = 2016-07-07, the last Player_Attributes date.
SELECT '2016-07-07 00:00:00' AS event_time, CAST(player_api_id AS TEXT) AS player_id, height,
       weight
FROM Player ORDER BY id;

-- event: match_played owner=league_id ord=match_id
SELECT iso_time(date, '%Y-%m-%d %H:%M:%S') AS event_time, CAST(league_id AS TEXT) AS league_id,
       id AS match_id, match_api_id, season, stage,
       CAST(home_team_api_id AS TEXT) AS home_team_id,
       CAST(away_team_api_id AS TEXT) AS away_team_id, home_team_goal, away_team_goal,
       home_player_X1, home_player_X2, home_player_X3, home_player_X4, home_player_X5,
       home_player_X6, home_player_X7, home_player_X8, home_player_X9, home_player_X10,
       home_player_X11, home_player_Y1, home_player_Y2, home_player_Y3, home_player_Y4,
       home_player_Y5, home_player_Y6, home_player_Y7, home_player_Y8, home_player_Y9,
       home_player_Y10, home_player_Y11, away_player_X1, away_player_X2, away_player_X3,
       away_player_X4, away_player_X5, away_player_X6, away_player_X7, away_player_X8,
       away_player_X9, away_player_X10, away_player_X11, away_player_Y1, away_player_Y2,
       away_player_Y3, away_player_Y4, away_player_Y5, away_player_Y6, away_player_Y7,
       away_player_Y8, away_player_Y9, away_player_Y10, away_player_Y11,
       CAST(home_player_1 AS TEXT) AS home_player_1,
       CAST(home_player_2 AS TEXT) AS home_player_2,
       CAST(home_player_3 AS TEXT) AS home_player_3,
       CAST(home_player_4 AS TEXT) AS home_player_4,
       CAST(home_player_5 AS TEXT) AS home_player_5,
       CAST(home_player_6 AS TEXT) AS home_player_6,
       CAST(home_player_7 AS TEXT) AS home_player_7,
       CAST(home_player_8 AS TEXT) AS home_player_8,
       CAST(home_player_9 AS TEXT) AS home_player_9,
       CAST(home_player_10 AS TEXT) AS home_player_10,
       CAST(home_player_11 AS TEXT) AS home_player_11,
       CAST(away_player_1 AS TEXT) AS away_player_1,
       CAST(away_player_2 AS TEXT) AS away_player_2,
       CAST(away_player_3 AS TEXT) AS away_player_3,
       CAST(away_player_4 AS TEXT) AS away_player_4,
       CAST(away_player_5 AS TEXT) AS away_player_5,
       CAST(away_player_6 AS TEXT) AS away_player_6,
       CAST(away_player_7 AS TEXT) AS away_player_7,
       CAST(away_player_8 AS TEXT) AS away_player_8,
       CAST(away_player_9 AS TEXT) AS away_player_9,
       CAST(away_player_10 AS TEXT) AS away_player_10,
       CAST(away_player_11 AS TEXT) AS away_player_11,
       "goal", "shoton", "shotoff", "foulcommit", "card", "cross", "corner", "possession",
       B365H, B365D, B365A, BWH, BWD, BWA, IWH, IWD, IWA, LBH, LBD, LBA, PSH, PSD, PSA, WHH,
       WHD, WHA, SJH, SJD, SJA, VCH, VCD, VCA, GBH, GBD, GBA, BSH, BSD, BSA
FROM Match ORDER BY date, id;

-- event: player_rated owner=player_id ord=attr_id
SELECT iso_time(date, '%Y-%m-%d %H:%M:%S') AS event_time, CAST(player_api_id AS TEXT) AS player_id,
       id AS attr_id, player_fifa_api_id, preferred_foot, attacking_work_rate,
       defensive_work_rate,
       overall_rating, potential, crossing, finishing, heading_accuracy, short_passing,
       volleys, dribbling, curve, free_kick_accuracy, long_passing, ball_control, acceleration,
       sprint_speed, agility, reactions, balance, shot_power, jumping, stamina, strength,
       long_shots, aggression, interceptions, positioning, vision, penalties, marking,
       standing_tackle, sliding_tackle, gk_diving, gk_handling, gk_kicking, gk_positioning,
       gk_reflexes
FROM Player_Attributes ORDER BY date, id;

-- event: team_rated owner=team_id ord=attr_id
SELECT iso_time(date, '%Y-%m-%d %H:%M:%S') AS event_time, CAST(team_api_id AS TEXT) AS team_id,
       id AS attr_id,
       buildUpPlaySpeed, buildUpPlayDribbling, buildUpPlayPassing, chanceCreationPassing,
       chanceCreationCrossing, chanceCreationShooting, defencePressure, defenceAggression,
       defenceTeamWidth, buildUpPlayPositioningClass, chanceCreationPositioningClass,
       defenceDefenderLineClass
FROM Team_Attributes ORDER BY date, id;
