-- Baseball (Lahman 2015): source tables → events (refdata ingest).
-- No source cell is NULL: '' is the only missing marker. A numeric column holding
-- '' next to integers travels as a null integer; the 4 holding reals travel as
-- SQLite's own CAST AS TEXT. Rule times: S(y) <y>-11-01, P(y) <y>-11-02,
-- A(y) <y>-11-30, H(y) <y>-01-15; T0 = 1871-01-01; N = 2016-02-18.

-- entity: player
-- Every source player plus a stub for each of the 12 ids used only in fact rows.
-- created_at: min(debut, the first owned event); T0 for the 2 with neither.
WITH first_event(player_id, t) AS (
    SELECT player_id, min("year" || '-11-01 00:00:00')
          FROM manager GROUP BY player_id
    UNION ALL SELECT player_id, min("year" || '-11-01 00:00:00')
          FROM manager_half GROUP BY player_id
    UNION ALL SELECT player_id, min("year" || '-11-01 00:00:00')
          FROM appearances GROUP BY player_id
    UNION ALL SELECT player_id, min("year" || '-11-01 00:00:00')
          FROM batting GROUP BY player_id
    UNION ALL SELECT player_id, min("year" || '-11-01 00:00:00')
          FROM pitching GROUP BY player_id
    UNION ALL SELECT player_id, min("year" || '-11-01 00:00:00')
          FROM fielding GROUP BY player_id
    UNION ALL SELECT player_id, min("year" || '-11-01 00:00:00')
          FROM fielding_outfield GROUP BY player_id
    UNION ALL SELECT player_id, min("year" || '-11-01 00:00:00')
          FROM salary GROUP BY player_id
    UNION ALL SELECT player_id, min(CASE WHEN game_id = '' THEN '1945-07-10 00:00:00'
            ELSE substr(game_id, 4, 4) || '-' || substr(game_id, 8, 2) || '-' ||
                 substr(game_id, 10, 2) || ' 00:00:00' END)
          FROM all_star GROUP BY player_id
    UNION ALL SELECT player_id, min("year" || '-11-02 00:00:00')
          FROM batting_postseason GROUP BY player_id
    UNION ALL SELECT player_id, min("year" || '-11-02 00:00:00')
          FROM pitching_postseason GROUP BY player_id
    UNION ALL SELECT player_id, min("year" || '-11-02 00:00:00')
          FROM fielding_postseason GROUP BY player_id
    UNION ALL SELECT player_id, min("year" || '-11-30 00:00:00')
          FROM player_award GROUP BY player_id
    UNION ALL SELECT player_id, min("year" || '-11-30 00:00:00')
          FROM player_award_vote GROUP BY player_id
    UNION ALL SELECT player_id, min("year" || '-11-30 00:00:00')
          FROM manager_award GROUP BY player_id
    UNION ALL SELECT player_id, min("year" || '-11-30 00:00:00')
          FROM manager_award_vote GROUP BY player_id
    UNION ALL SELECT player_id, min("yearid" || '-01-15 00:00:00')
          FROM hall_of_fame GROUP BY player_id
),
created AS (
    SELECT i.player_id,
           coalesce(min(nullif(p.debut, '') || ' 00:00:00', f.t),
                    nullif(p.debut, '') || ' 00:00:00', f.t, '1871-01-01 00:00:00') AS created_at
    FROM (SELECT player_id FROM player UNION SELECT player_id FROM first_event) i
    LEFT JOIN player p USING (player_id)
    LEFT JOIN (SELECT player_id, min(t) AS t FROM first_event GROUP BY player_id) f
        USING (player_id)
)
SELECT c.player_id AS ext_id, CASE WHEN p.player_id IS NULL THEN '1' ELSE '0' END AS stub,
       NULLIF(p."birth_year", '') AS "birth_year", NULLIF(p."birth_month", '') AS "birth_month",
       NULLIF(p."birth_day", '') AS "birth_day", p."birth_country", p."birth_state", p."birth_city",
       p."name_first", p."name_last", p."name_given", NULLIF(p."weight", '') AS "weight",
       NULLIF(p."height", '') AS "height", p."bats", p."throws", p."debut", p."retro_id",
       p."bbref_id",
       c.created_at
FROM created c LEFT JOIN player p USING (player_id)
ORDER BY c.player_id;

-- entity: team_franchise
-- created_at: Jan 1 of the franchise's first team-season (rule).
SELECT f.franchise_id AS ext_id, f.franchise_name, f.active, f.na_assoc,
       (SELECT min(year) FROM team t WHERE t.franchise_id = f.franchise_id) || '-01-01 00:00:00'
           AS created_at
FROM team_franchise f ORDER BY f.franchise_id;

-- entity: park
-- created_at: its first home game (min span_first); T0 for the unused FOR02.
SELECT p.park_id AS ext_id, p.park_name, p.park_alias, p.city, p.state, p.country,
       coalesce((SELECT min(span_first) FROM home_game h WHERE h.park_id = p.park_id) || ' 00:00:00',
                '1871-01-01 00:00:00') AS created_at
FROM park p ORDER BY p.park_id;

-- entity: college
-- All at T0 (rule), plus a stub for each of the 4 unknown ids in player_college.
SELECT i.college_id AS ext_id, CASE WHEN c.college_id IS NULL THEN '1' ELSE '0' END AS stub,
       c.name_full, c.city, c.state, c.country, '1871-01-01 00:00:00' AS created_at
FROM (SELECT college_id FROM college UNION SELECT college_id FROM player_college) i
LEFT JOIN college c USING (college_id)
ORDER BY i.college_id;

-- entity: season
-- An owner shard for postseason series: one per team year, at Jan 1 (rule).
SELECT CAST(year AS TEXT) AS ext_id, year || '-01-01 00:00:00' AS created_at
FROM (SELECT DISTINCT year FROM team) ORDER BY year;

-- event: team_season_reported owner=franchise_id
-- S(y) = <year>-11-01. Owner: the franchise (team.franchise_id).
SELECT "year" || '-11-01 00:00:00' AS event_time, "year", "league_id", "team_id", "franchise_id",
       "div_id", "rank", "g", NULLIF("ghome", '') AS "ghome", "w", "l", "div_win", "wc_win",
       "lg_win", "ws_win", "r", "ab", "h", "double", "triple", "hr", "bb", NULLIF("so", '') AS "so",
       NULLIF("sb", '') AS "sb", NULLIF("cs", '') AS "cs", NULLIF("hbp", '') AS "hbp",
       NULLIF("sf", '') AS "sf", "ra", "er", "era", "cg", "sho", "sv", "ipouts", "ha", "hra", "bba",
       "soa", "e", NULLIF("dp", '') AS "dp", "fp", "name", "park",
       NULLIF("attendance", '') AS "attendance", "bpf", "ppf", "team_id_br", "team_id_lahman45",
       "team_id_retro"
FROM team ORDER BY year, team_id;

-- event: team_half_reported owner=franchise
-- S(y). Owner: the franchise of team (year, team_id); not a results column.
SELECT "year" || '-11-01 00:00:00' AS event_time,
       (SELECT franchise_id FROM team WHERE team.year = s.year AND team.team_id = s.team_id) AS franchise,
       "year", "league_id", "team_id", "half", "div_id", "div_win", "rank", "g", "w", "l"
FROM team_half s ORDER BY year, team_id, half;

-- event: manager_stint_reported owner=player_id
-- S(y). Owner: the manager (a player id).
SELECT "year" || '-11-01 00:00:00' AS event_time, "player_id", "year", "team_id", "league_id",
       "inseason", "g", "w", "l", NULLIF("rank", '') AS "rank", "plyr_mgr"
FROM manager ORDER BY year, team_id, inseason;

-- event: manager_half_reported owner=player_id
-- S(y).
SELECT "year" || '-11-01 00:00:00' AS event_time, "player_id", "year", "team_id", "league_id",
       "inseason", "half", "g", "w", "l", "rank"
FROM manager_half ORDER BY player_id, year, team_id, half;

-- event: appearances_reported owner=player_id
-- S(y).
SELECT "year" || '-11-01 00:00:00' AS event_time, "year", "team_id", "league_id", "player_id",
       NULLIF("g_all", '') AS "g_all", NULLIF("gs", '') AS "gs", "g_batting",
       NULLIF("g_defense", '') AS "g_defense", "g_p", "g_c", "g_1b", "g_2b", "g_3b", "g_ss", "g_lf",
       "g_cf", "g_rf", "g_of", NULLIF("g_dh", '') AS "g_dh", NULLIF("g_ph", '') AS "g_ph",
       NULLIF("g_pr", '') AS "g_pr"
FROM appearances ORDER BY year, team_id, player_id;

-- event: batting_line_reported owner=player_id
-- S(y).
SELECT "year" || '-11-01 00:00:00' AS event_time, "player_id", "year", "stint", "team_id",
       "league_id", "g", NULLIF("ab", '') AS "ab", NULLIF("r", '') AS "r", NULLIF("h", '') AS "h",
       NULLIF("double", '') AS "double", NULLIF("triple", '') AS "triple", NULLIF("hr", '') AS "hr",
       NULLIF("rbi", '') AS "rbi", NULLIF("sb", '') AS "sb", NULLIF("cs", '') AS "cs",
       NULLIF("bb", '') AS "bb", NULLIF("so", '') AS "so", NULLIF("ibb", '') AS "ibb",
       NULLIF("hbp", '') AS "hbp", NULLIF("sh", '') AS "sh", NULLIF("sf", '') AS "sf",
       NULLIF("g_idp", '') AS "g_idp"
FROM batting ORDER BY year, player_id, stint;

-- event: pitching_line_reported owner=player_id
-- S(y). era and baopp hold reals next to '': SQLite's own CAST AS TEXT.
SELECT "year" || '-11-01 00:00:00' AS event_time, "player_id", "year", "stint", "team_id",
       "league_id", "w", "l", "g", "gs", "cg", "sho", "sv", NULLIF("ipouts", '') AS "ipouts", "h",
       "er", "hr", "bb", "so", CAST("baopp" AS TEXT) AS "baopp", CAST("era" AS TEXT) AS "era",
       NULLIF("ibb", '') AS "ibb", NULLIF("wp", '') AS "wp", NULLIF("hbp", '') AS "hbp", "bk",
       NULLIF("bfp", '') AS "bfp", NULLIF("gf", '') AS "gf", "r", NULLIF("sh", '') AS "sh",
       NULLIF("sf", '') AS "sf", NULLIF("g_idp", '') AS "g_idp"
FROM pitching ORDER BY year, player_id, stint;

-- event: fielding_line_reported owner=player_id
-- S(y).
SELECT "year" || '-11-01 00:00:00' AS event_time, "player_id", "year", "stint", "team_id",
       "league_id", "pos", "g", NULLIF("gs", '') AS "gs", NULLIF("inn_outs", '') AS "inn_outs",
       NULLIF("po", '') AS "po", NULLIF("a", '') AS "a", NULLIF("e", '') AS "e",
       NULLIF("dp", '') AS "dp", NULLIF("pb", '') AS "pb", NULLIF("wp", '') AS "wp",
       NULLIF("sb", '') AS "sb", NULLIF("cs", '') AS "cs", NULLIF("zr", '') AS "zr"
FROM fielding ORDER BY year, player_id, stint, pos;

-- event: outfield_split_reported owner=player_id
-- S(y).
SELECT "year" || '-11-01 00:00:00' AS event_time, "player_id", "year", "stint",
       NULLIF("glf", '') AS "glf", NULLIF("gcf", '') AS "gcf", NULLIF("grf", '') AS "grf"
FROM fielding_outfield ORDER BY year, player_id, stint;

-- event: salary_reported owner=player_id
-- S(y). Salary is whole dollars, carried as cents.
SELECT "year" || '-11-01 00:00:00' AS event_time, "year", "team_id", "league_id", "player_id",
       salary * 100 AS salary
FROM salary ORDER BY year, team_id, player_id;

-- event: home_games_reported owner=franchise
-- Natural: the last home game at the park (span_last). Owner: the franchise of team.
SELECT span_last || ' 00:00:00' AS event_time,
       (SELECT franchise_id FROM team WHERE team.year = s.year AND team.team_id = s.team_id) AS franchise,
       "year", "league_id", "team_id", "park_id", "span_first", "span_last", "games", "openings",
       "attendance"
FROM home_game s ORDER BY year, team_id, park_id;

-- event: all_star_selected owner=player_id
-- Natural: the game date in game_id (ALSyyyymmddn); 1945 (no game, game_id = '') at the
-- rule date 1945-07-10.
SELECT CASE WHEN game_id = '' THEN '1945-07-10 00:00:00'
            ELSE substr(game_id, 4, 4) || '-' || substr(game_id, 8, 2) || '-' ||
                 substr(game_id, 10, 2) || ' 00:00:00' END AS event_time,
       "player_id", "year", "game_num", "game_id", "team_id", "league_id", NULLIF("gp", '') AS "gp",
       NULLIF("starting_pos", '') AS "starting_pos"
FROM all_star ORDER BY year, game_num, player_id;

-- event: postseason_series_decided owner=season
-- P(y) = <year>-11-02. Owner: the season (its team codes do not all resolve).
SELECT "year" || '-11-02 00:00:00' AS event_time, CAST(year AS TEXT) AS season, "year", "round",
       "team_id_winner", "league_id_winner", "team_id_loser", "league_id_loser", "wins", "losses",
       "ties"
FROM postseason s ORDER BY year, round;

-- event: batting_postseason_reported owner=player_id
-- P(y).
SELECT "year" || '-11-02 00:00:00' AS event_time, "year", "round", "player_id", "team_id",
       "league_id", "g", "ab", "r", "h", "double", "triple", "hr", "rbi", "sb",
       NULLIF("cs", '') AS "cs", "bb", "so", NULLIF("ibb", '') AS "ibb", NULLIF("hbp", '') AS "hbp",
       NULLIF("sh", '') AS "sh", NULLIF("sf", '') AS "sf", NULLIF("g_idp", '') AS "g_idp"
FROM batting_postseason ORDER BY year, round, player_id;

-- event: pitching_postseason_reported owner=player_id
-- P(y). era holds reals, '' and one 'inf': SQLite's own CAST AS TEXT.
SELECT "year" || '-11-02 00:00:00' AS event_time, "player_id", "year", "round", "team_id",
       "league_id", "w", "l", "g", "gs", "cg", "sho", "sv", "ipouts", "h", "er", "hr", "bb", "so",
       "baopp", CAST("era" AS TEXT) AS "era", NULLIF("ibb", '') AS "ibb", NULLIF("wp", '') AS "wp",
       NULLIF("hbp", '') AS "hbp", NULLIF("bk", '') AS "bk", NULLIF("bfp", '') AS "bfp", "gf", "r",
       NULLIF("sh", '') AS "sh", NULLIF("sf", '') AS "sf", NULLIF("g_idp", '') AS "g_idp"
FROM pitching_postseason ORDER BY year, round, player_id;

-- event: fielding_postseason_reported owner=player_id
-- P(y).
SELECT "year" || '-11-02 00:00:00' AS event_time, "player_id", "year", "team_id", "league_id",
       "round", "pos", "g", NULLIF("gs", '') AS "gs", NULLIF("inn_outs", '') AS "inn_outs", "po",
       "a", "e", "dp", "tp", NULLIF("pb", '') AS "pb", NULLIF("sb", '') AS "sb",
       NULLIF("cs", '') AS "cs"
FROM fielding_postseason ORDER BY year, round, player_id, pos;

-- event: player_award_won owner=player_id
-- A(y) = <year>-11-30.
SELECT "year" || '-11-30 00:00:00' AS event_time, "player_id", "award_id", "year", "league_id",
       "tie", "notes"
FROM player_award ORDER BY year, award_id, league_id, player_id;

-- event: player_award_vote_received owner=player_id
-- A(y). votes_first holds reals next to '': SQLite's own CAST AS TEXT.
SELECT "year" || '-11-30 00:00:00' AS event_time, "award_id", "year", "league_id", "player_id",
       "points_won", "points_max", CAST("votes_first" AS TEXT) AS "votes_first"
FROM player_award_vote ORDER BY year, award_id, league_id, player_id;

-- event: manager_award_won owner=player_id
-- A(y).
SELECT "year" || '-11-30 00:00:00' AS event_time, "player_id", "award_id", "year", "league_id",
       "tie", "notes"
FROM manager_award ORDER BY year, award_id, league_id, player_id;

-- event: manager_award_vote_received owner=player_id
-- A(y).
SELECT "year" || '-11-30 00:00:00' AS event_time, "award_id", "year", "league_id", "player_id",
       "points_won", "points_max", "votes_first"
FROM manager_award_vote ORDER BY year, award_id, league_id, player_id;

-- event: hof_ballot_recorded owner=player_id
-- H(y) = <yearid>-01-15.
SELECT "yearid" || '-01-15 00:00:00' AS event_time, "player_id", "yearid", "votedby",
       NULLIF("ballots", '') AS "ballots", NULLIF("needed", '') AS "needed",
       NULLIF("votes", '') AS "votes", "inducted", "category", "needed_note"
FROM hall_of_fame ORDER BY yearid, player_id, votedby;

-- event: college_attended owner=player_id ord=n
-- At the player's created_at (a college year is not a dated event), after the
-- creation: ord ranks the player's (year, college_id).
WITH first_event(player_id, t) AS (
    SELECT player_id, min("year" || '-11-01 00:00:00')
          FROM manager GROUP BY player_id
    UNION ALL SELECT player_id, min("year" || '-11-01 00:00:00')
          FROM manager_half GROUP BY player_id
    UNION ALL SELECT player_id, min("year" || '-11-01 00:00:00')
          FROM appearances GROUP BY player_id
    UNION ALL SELECT player_id, min("year" || '-11-01 00:00:00')
          FROM batting GROUP BY player_id
    UNION ALL SELECT player_id, min("year" || '-11-01 00:00:00')
          FROM pitching GROUP BY player_id
    UNION ALL SELECT player_id, min("year" || '-11-01 00:00:00')
          FROM fielding GROUP BY player_id
    UNION ALL SELECT player_id, min("year" || '-11-01 00:00:00')
          FROM fielding_outfield GROUP BY player_id
    UNION ALL SELECT player_id, min("year" || '-11-01 00:00:00')
          FROM salary GROUP BY player_id
    UNION ALL SELECT player_id, min(CASE WHEN game_id = '' THEN '1945-07-10 00:00:00'
            ELSE substr(game_id, 4, 4) || '-' || substr(game_id, 8, 2) || '-' ||
                 substr(game_id, 10, 2) || ' 00:00:00' END)
          FROM all_star GROUP BY player_id
    UNION ALL SELECT player_id, min("year" || '-11-02 00:00:00')
          FROM batting_postseason GROUP BY player_id
    UNION ALL SELECT player_id, min("year" || '-11-02 00:00:00')
          FROM pitching_postseason GROUP BY player_id
    UNION ALL SELECT player_id, min("year" || '-11-02 00:00:00')
          FROM fielding_postseason GROUP BY player_id
    UNION ALL SELECT player_id, min("year" || '-11-30 00:00:00')
          FROM player_award GROUP BY player_id
    UNION ALL SELECT player_id, min("year" || '-11-30 00:00:00')
          FROM player_award_vote GROUP BY player_id
    UNION ALL SELECT player_id, min("year" || '-11-30 00:00:00')
          FROM manager_award GROUP BY player_id
    UNION ALL SELECT player_id, min("year" || '-11-30 00:00:00')
          FROM manager_award_vote GROUP BY player_id
    UNION ALL SELECT player_id, min("yearid" || '-01-15 00:00:00')
          FROM hall_of_fame GROUP BY player_id
),
created AS (
    SELECT i.player_id,
           coalesce(min(nullif(p.debut, '') || ' 00:00:00', f.t),
                    nullif(p.debut, '') || ' 00:00:00', f.t, '1871-01-01 00:00:00') AS created_at
    FROM (SELECT player_id FROM player UNION SELECT player_id FROM first_event) i
    LEFT JOIN player p USING (player_id)
    LEFT JOIN (SELECT player_id, min(t) AS t FROM first_event GROUP BY player_id) f
        USING (player_id)
)
SELECT c.created_at AS event_time, pc.player_id, pc.college_id, pc.year,
       row_number() OVER (PARTITION BY pc.player_id ORDER BY pc.year, pc.college_id) AS n
FROM player_college pc JOIN created c USING (player_id)
ORDER BY pc.player_id, pc.year, pc.college_id;

-- event: player_snapshot_taken owner=player_id
-- At N = 2016-02-18, the last death date: final_game and the death columns are
-- lifetime values, known only at the snapshot.
SELECT '2016-02-18 00:00:00' AS event_time, player_id, "final_game", NULLIF("death_year", '') AS "death_year",
       NULLIF("death_month", '') AS "death_month", NULLIF("death_day", '') AS "death_day",
       "death_country", "death_state", "death_city"
FROM player ORDER BY player_id;
