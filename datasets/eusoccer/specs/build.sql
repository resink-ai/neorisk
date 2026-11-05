-- EU_soccer: events → source tables (refdata rebuild, DuckDB). Dates are formatted back as
-- 'YYYY-MM-DD 00:00:00'. sqlite_sequence is system data and match_view a view: neither is
-- rebuilt (verify replays the view from the source DDL).

-- table: Country
SELECT CAST(ext_id AS BIGINT) AS id, name FROM countries;

-- table: League
SELECT CAST(l.ext_id AS BIGINT) AS id, CAST(c.ext_id AS BIGINT) AS country_id, l.name
FROM leagues l JOIN countries c USING (country_id);

-- table: Team
SELECT team_row_id AS id, CAST(ext_id AS BIGINT) AS team_api_id, team_fifa_api_id,
       team_long_name, team_short_name
FROM teams;

-- table: Player
SELECT p.player_row_id AS id, CAST(p.ext_id AS BIGINT) AS player_api_id, p.player_name,
       p.player_fifa_api_id, p.birthday, s.height, s.weight
FROM players p LEFT JOIN players_snapshot s USING (player_id);

-- table: Match
-- country_id is the league's country.
SELECT m.match_id AS id, CAST(c.ext_id AS BIGINT) AS country_id,
       CAST(l.ext_id AS BIGINT) AS league_id, m.season, m.stage,
       strftime(m.event_time, '%Y-%m-%d %H:%M:%S') AS date,
       m.match_api_id, CAST(h.ext_id AS BIGINT) AS home_team_api_id,
       CAST(a.ext_id AS BIGINT) AS away_team_api_id, m.home_team_goal, m.away_team_goal,
       m.home_player_X1, m.home_player_X2, m.home_player_X3, m.home_player_X4,
       m.home_player_X5, m.home_player_X6, m.home_player_X7, m.home_player_X8,
       m.home_player_X9, m.home_player_X10, m.home_player_X11, m.home_player_Y1,
       m.home_player_Y2, m.home_player_Y3, m.home_player_Y4, m.home_player_Y5,
       m.home_player_Y6, m.home_player_Y7, m.home_player_Y8, m.home_player_Y9,
       m.home_player_Y10, m.home_player_Y11, m.away_player_X1, m.away_player_X2,
       m.away_player_X3, m.away_player_X4, m.away_player_X5, m.away_player_X6,
       m.away_player_X7, m.away_player_X8, m.away_player_X9, m.away_player_X10,
       m.away_player_X11, m.away_player_Y1, m.away_player_Y2, m.away_player_Y3,
       m.away_player_Y4, m.away_player_Y5, m.away_player_Y6, m.away_player_Y7,
       m.away_player_Y8, m.away_player_Y9, m.away_player_Y10, m.away_player_Y11,
       CAST(p1.ext_id AS BIGINT) AS home_player_1, CAST(p2.ext_id AS BIGINT) AS home_player_2,
       CAST(p3.ext_id AS BIGINT) AS home_player_3, CAST(p4.ext_id AS BIGINT) AS home_player_4,
       CAST(p5.ext_id AS BIGINT) AS home_player_5, CAST(p6.ext_id AS BIGINT) AS home_player_6,
       CAST(p7.ext_id AS BIGINT) AS home_player_7, CAST(p8.ext_id AS BIGINT) AS home_player_8,
       CAST(p9.ext_id AS BIGINT) AS home_player_9,
       CAST(p10.ext_id AS BIGINT) AS home_player_10,
       CAST(p11.ext_id AS BIGINT) AS home_player_11,
       CAST(p12.ext_id AS BIGINT) AS away_player_1,
       CAST(p13.ext_id AS BIGINT) AS away_player_2,
       CAST(p14.ext_id AS BIGINT) AS away_player_3,
       CAST(p15.ext_id AS BIGINT) AS away_player_4,
       CAST(p16.ext_id AS BIGINT) AS away_player_5,
       CAST(p17.ext_id AS BIGINT) AS away_player_6,
       CAST(p18.ext_id AS BIGINT) AS away_player_7,
       CAST(p19.ext_id AS BIGINT) AS away_player_8,
       CAST(p20.ext_id AS BIGINT) AS away_player_9,
       CAST(p21.ext_id AS BIGINT) AS away_player_10,
       CAST(p22.ext_id AS BIGINT) AS away_player_11,
       m."goal", m."shoton", m."shotoff", m."foulcommit", m."card", m."cross", m."corner",
       m."possession",
       m.B365H, m.B365D, m.B365A, m.BWH, m.BWD, m.BWA, m.IWH, m.IWD, m.IWA, m.LBH, m.LBD,
       m.LBA, m.PSH, m.PSD, m.PSA, m.WHH, m.WHD, m.WHA, m.SJH, m.SJD, m.SJA, m.VCH, m.VCD,
       m.VCA, m.GBH, m.GBD, m.GBA, m.BSH, m.BSD, m.BSA
FROM match_played m
JOIN leagues l ON l.league_id = m.league_id
JOIN countries c ON c.country_id = l.country_id
JOIN teams h ON h.team_id = m.home_team_id
JOIN teams a ON a.team_id = m.away_team_id
LEFT JOIN players p1 ON p1.player_id = m.home_player_1
LEFT JOIN players p2 ON p2.player_id = m.home_player_2
LEFT JOIN players p3 ON p3.player_id = m.home_player_3
LEFT JOIN players p4 ON p4.player_id = m.home_player_4
LEFT JOIN players p5 ON p5.player_id = m.home_player_5
LEFT JOIN players p6 ON p6.player_id = m.home_player_6
LEFT JOIN players p7 ON p7.player_id = m.home_player_7
LEFT JOIN players p8 ON p8.player_id = m.home_player_8
LEFT JOIN players p9 ON p9.player_id = m.home_player_9
LEFT JOIN players p10 ON p10.player_id = m.home_player_10
LEFT JOIN players p11 ON p11.player_id = m.home_player_11
LEFT JOIN players p12 ON p12.player_id = m.away_player_1
LEFT JOIN players p13 ON p13.player_id = m.away_player_2
LEFT JOIN players p14 ON p14.player_id = m.away_player_3
LEFT JOIN players p15 ON p15.player_id = m.away_player_4
LEFT JOIN players p16 ON p16.player_id = m.away_player_5
LEFT JOIN players p17 ON p17.player_id = m.away_player_6
LEFT JOIN players p18 ON p18.player_id = m.away_player_7
LEFT JOIN players p19 ON p19.player_id = m.away_player_8
LEFT JOIN players p20 ON p20.player_id = m.away_player_9
LEFT JOIN players p21 ON p21.player_id = m.away_player_10
LEFT JOIN players p22 ON p22.player_id = m.away_player_11;

-- table: Player_Attributes
SELECT m.attr_id AS id, m.player_fifa_api_id, CAST(p.ext_id AS BIGINT) AS player_api_id,
       strftime(m.event_time, '%Y-%m-%d %H:%M:%S') AS date, m.overall_rating, m.potential,
       m.preferred_foot,
       m.attacking_work_rate, m.defensive_work_rate,
       m.crossing, m.finishing, m.heading_accuracy, m.short_passing, m.volleys, m.dribbling,
       m.curve, m.free_kick_accuracy, m.long_passing, m.ball_control, m.acceleration,
       m.sprint_speed, m.agility, m.reactions, m.balance, m.shot_power, m.jumping, m.stamina,
       m.strength, m.long_shots, m.aggression, m.interceptions, m.positioning, m.vision,
       m.penalties, m.marking, m.standing_tackle, m.sliding_tackle, m.gk_diving, m.gk_handling,
       m.gk_kicking, m.gk_positioning, m.gk_reflexes
FROM player_rated m JOIN players p USING (player_id);

-- table: Team_Attributes
-- team_fifa_api_id is the team's own. The 9 classes of numeric tactics are bands of the
-- value: <= 33, 34..66, >= 67; a NULL dribbling (every snapshot before 2014-09-19) is
-- 'Little'.
SELECT m.attr_id AS id, t.team_fifa_api_id, CAST(t.ext_id AS BIGINT) AS team_api_id,
       strftime(m.event_time, '%Y-%m-%d %H:%M:%S') AS date,
       buildUpPlaySpeed, CASE WHEN buildUpPlaySpeed <= 33 THEN 'Slow'
            WHEN buildUpPlaySpeed <= 66 THEN 'Balanced' ELSE 'Fast' END AS buildUpPlaySpeedClass,
       buildUpPlayDribbling,
       CASE WHEN buildUpPlayDribbling IS NULL THEN 'Little'
            WHEN buildUpPlayDribbling <= 33 THEN 'Little'
            WHEN buildUpPlayDribbling <= 66 THEN 'Normal' ELSE 'Lots' END
            AS buildUpPlayDribblingClass,
       buildUpPlayPassing, CASE WHEN buildUpPlayPassing <= 33 THEN 'Short'
            WHEN buildUpPlayPassing <= 66 THEN 'Mixed' ELSE 'Long' END AS buildUpPlayPassingClass,
       CAST(buildUpPlayPositioningClass AS VARCHAR) AS buildUpPlayPositioningClass,
       chanceCreationPassing, CASE WHEN chanceCreationPassing <= 33 THEN 'Safe'
            WHEN chanceCreationPassing <= 66 THEN 'Normal' ELSE 'Risky' END
            AS chanceCreationPassingClass,
       chanceCreationCrossing, CASE WHEN chanceCreationCrossing <= 33 THEN 'Little'
            WHEN chanceCreationCrossing <= 66 THEN 'Normal' ELSE 'Lots' END
            AS chanceCreationCrossingClass,
       chanceCreationShooting, CASE WHEN chanceCreationShooting <= 33 THEN 'Little'
            WHEN chanceCreationShooting <= 66 THEN 'Normal' ELSE 'Lots' END
            AS chanceCreationShootingClass,
       CAST(chanceCreationPositioningClass AS VARCHAR) AS chanceCreationPositioningClass,
       defencePressure, CASE WHEN defencePressure <= 33 THEN 'Deep'
            WHEN defencePressure <= 66 THEN 'Medium' ELSE 'High' END AS defencePressureClass,
       defenceAggression, CASE WHEN defenceAggression <= 33 THEN 'Contain'
            WHEN defenceAggression <= 66 THEN 'Press' ELSE 'Double' END AS defenceAggressionClass,
       defenceTeamWidth, CASE WHEN defenceTeamWidth <= 33 THEN 'Narrow'
            WHEN defenceTeamWidth <= 66 THEN 'Normal' ELSE 'Wide' END AS defenceTeamWidthClass,
       CAST(defenceDefenderLineClass AS VARCHAR) AS defenceDefenderLineClass
FROM team_rated m JOIN teams t USING (team_id);
