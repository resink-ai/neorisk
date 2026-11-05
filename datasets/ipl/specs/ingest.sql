-- IPL: source tables → events (refdata ingest). The source has dates only; the clock is a rule:
-- a match starts at 20:00 on its date, or 16:00 for the lower match_id of a two-match day.
-- Match 419136 has no match row: it is placed on 2010-03-29, the free day between its id
-- neighbours. Fixture, toss and team sheet are at start - 30 min. Delivery k (1..n per innings,
-- in over and ball order) is at start + (innings - 1) * 110 min + (k - 1) * 40 s. The result
-- is at the last delivery + 5 min.

-- entity: teams
-- Created at 00:00 of the team's first match. Team 1 has no row: a placeholder, listed = 0.
WITH m AS (SELECT match_id, match_date AS d FROM match UNION ALL SELECT 419136, '2010-03-29'),
f AS (SELECT pm.team_id, min(m.d) AS d FROM player_match pm JOIN m USING (match_id) GROUP BY 1)
SELECT CAST(t.team_id AS TEXT) AS ext_id, t.name, 1 AS listed, f.d || ' 00:00:00' AS created_at
FROM team t JOIN f USING (team_id)
UNION ALL
SELECT '1', NULL, 0, (SELECT d FROM f WHERE team_id = 1) || ' 00:00:00'
ORDER BY ext_id;

-- entity: players
-- Created at 00:00 of the first team sheet; player 448 is on none and takes 2008-04-18.
-- Player 35 has no row: a placeholder, listed = 0.
WITH m AS (SELECT match_id, match_date AS d FROM match UNION ALL SELECT 419136, '2010-03-29'),
f AS (SELECT pm.player_id, min(m.d) AS d FROM player_match pm JOIN m USING (match_id) GROUP BY 1)
SELECT CAST(p.player_id AS TEXT) AS ext_id, p.player_name, p.dob, p.batting_hand,
       p.bowling_skill, p.country_name, 1 AS listed,
       coalesce(f.d, '2008-04-18') || ' 00:00:00' AS created_at
FROM player p LEFT JOIN f USING (player_id)
UNION ALL
SELECT '35', NULL, NULL, NULL, NULL, NULL, 0, (SELECT d FROM f WHERE player_id = 35) || ' 00:00:00'
ORDER BY ext_id;

-- event: match_scheduled owner=match_id
WITH s AS (SELECT match_id, CASE WHEN count(*) OVER (PARTITION BY match_date) = 2
                  AND row_number() OVER (PARTITION BY match_date ORDER BY match_id) = 1
                  THEN '16:00:00' ELSE '20:00:00' END AS h FROM match)
SELECT datetime(m.match_date || ' ' || s.h, '-30 minutes') AS event_time, m.match_id,
       CAST(m.team_1 AS TEXT) AS team_1, CAST(m.team_2 AS TEXT) AS team_2, m.season_id, m.venue
FROM match m JOIN s USING (match_id) ORDER BY m.match_id;

-- event: toss_decided owner=match_id
WITH s AS (SELECT match_id, CASE WHEN count(*) OVER (PARTITION BY match_date) = 2
                  AND row_number() OVER (PARTITION BY match_date ORDER BY match_id) = 1
                  THEN '16:00:00' ELSE '20:00:00' END AS h FROM match)
SELECT datetime(m.match_date || ' ' || s.h, '-30 minutes') AS event_time, m.match_id,
       CAST(m.toss_winner AS TEXT) AS toss_winner, m.toss_decision
FROM match m JOIN s USING (match_id) ORDER BY m.match_id;

-- event: player_named owner=match_id ord=player_id
WITH m AS (SELECT match_id, match_date AS d FROM match UNION ALL SELECT 419136, '2010-03-29'),
s AS (SELECT match_id, d, CASE WHEN count(*) OVER (PARTITION BY d) = 2
             AND row_number() OVER (PARTITION BY d ORDER BY match_id) = 1
             THEN '16:00:00' ELSE '20:00:00' END AS h FROM m)
SELECT datetime(s.d || ' ' || s.h, '-30 minutes') AS event_time, pm.match_id,
       CAST(pm.player_id AS TEXT) AS player_id, CAST(pm.team_id AS TEXT) AS team_id, pm.role
FROM player_match pm JOIN s USING (match_id) ORDER BY pm.match_id, pm.player_id;

-- event: innings_started owner=match_id ord=innings_no
-- At the innings' first delivery. The batting side is the team most of its strikers are named
-- for; in 3 matches the source labels some innings-2 deliveries the other way round.
WITH m AS (SELECT match_id, match_date AS d FROM match UNION ALL SELECT 419136, '2010-03-29'),
s AS (SELECT match_id, d, CASE WHEN count(*) OVER (PARTITION BY d) = 2
             AND row_number() OVER (PARTITION BY d ORDER BY match_id) = 1
             THEN '16:00:00' ELSE '20:00:00' END AS h FROM m),
bat AS (SELECT b.match_id, b.innings_no, pm.team_id, count(*) AS c
        FROM ball_by_ball b JOIN player_match pm
            ON pm.match_id = b.match_id AND pm.player_id = b.striker
        GROUP BY 1, 2, 3),
inn AS (SELECT match_id, innings_no, team_id AS team_batting
        FROM (SELECT *, row_number() OVER (PARTITION BY match_id, innings_no
                                           ORDER BY c DESC, team_id) AS r FROM bat)
        WHERE r = 1)
SELECT datetime(s.d || ' ' || s.h, '+' || ((i.innings_no - 1) * 6600) || ' seconds') AS event_time,
       i.match_id, i.innings_no, CAST(i.team_batting AS TEXT) AS team_batting,
       (SELECT CAST(team_id AS TEXT) FROM player_match pm WHERE pm.match_id = i.match_id
        AND pm.team_id <> i.team_batting LIMIT 1) AS team_bowling
FROM inn i JOIN s USING (match_id) ORDER BY i.match_id, i.innings_no;

-- event: ball_bowled owner=match_id ord=k
-- The union of the four ball tables' keys; a part is NULL when its table has no row.
WITH m AS (SELECT match_id, match_date AS d FROM match UNION ALL SELECT 419136, '2010-03-29'),
s AS (SELECT match_id, d, CASE WHEN count(*) OVER (PARTITION BY d) = 2
             AND row_number() OVER (PARTITION BY d ORDER BY match_id) = 1
             THEN '16:00:00' ELSE '20:00:00' END AS h FROM m),
keys AS (SELECT match_id, innings_no, over_id, ball_id FROM ball_by_ball
         UNION SELECT match_id, innings_no, over_id, ball_id FROM batsman_scored
         UNION SELECT match_id, innings_no, over_id, ball_id FROM extra_runs
         UNION SELECT match_id, innings_no, over_id, ball_id FROM wicket_taken),
n AS (SELECT *, row_number() OVER (PARTITION BY match_id, innings_no
                                   ORDER BY over_id, ball_id) AS n FROM keys),
bat AS (SELECT b.match_id, b.innings_no, pm.team_id, count(*) AS c
        FROM ball_by_ball b JOIN player_match pm
            ON pm.match_id = b.match_id AND pm.player_id = b.striker
        GROUP BY 1, 2, 3),
inn AS (SELECT match_id, innings_no, team_id AS team_batting
        FROM (SELECT *, row_number() OVER (PARTITION BY match_id, innings_no
                                           ORDER BY c DESC, team_id) AS r FROM bat)
        WHERE r = 1)
SELECT datetime(s.d || ' ' || s.h,
                '+' || ((n.innings_no - 1) * 6600 + (n.n - 1) * 40) || ' seconds') AS event_time,
       n.match_id, n.innings_no, n.over_id, n.ball_id,
       CASE WHEN b.match_id IS NULL THEN 0 ELSE 1 END AS has_ball_row,
       CASE WHEN b.match_id IS NOT NULL AND b.team_batting <> i.team_batting THEN 1 ELSE 0 END
           AS teams_swapped,
       CAST(b.striker AS TEXT) AS striker, CAST(b.non_striker AS TEXT) AS non_striker,
       CAST(b.bowler AS TEXT) AS bowler, b.striker_batting_position, bs.runs_scored,
       er.extra_type, er.extra_runs, CAST(w.player_out AS TEXT) AS player_out, w.kind_out,
       n.innings_no * 10000 + n.over_id * 100 + n.ball_id AS k
FROM n JOIN s USING (match_id)
LEFT JOIN inn i ON i.match_id = n.match_id AND i.innings_no = n.innings_no
LEFT JOIN ball_by_ball b ON b.match_id = n.match_id AND b.innings_no = n.innings_no
    AND b.over_id = n.over_id AND b.ball_id = n.ball_id
LEFT JOIN batsman_scored bs ON bs.match_id = n.match_id AND bs.innings_no = n.innings_no
    AND bs.over_id = n.over_id AND bs.ball_id = n.ball_id
LEFT JOIN extra_runs er ON er.match_id = n.match_id AND er.innings_no = n.innings_no
    AND er.over_id = n.over_id AND er.ball_id = n.ball_id
LEFT JOIN wicket_taken w ON w.match_id = n.match_id AND w.innings_no = n.innings_no
    AND w.over_id = n.over_id AND w.ball_id = n.ball_id
ORDER BY n.match_id, n.innings_no, n.over_id, n.ball_id;

-- event: match_completed owner=match_id
-- At the last delivery + 5 min.
WITH s AS (SELECT match_id, match_date AS d, CASE WHEN count(*) OVER (PARTITION BY match_date) = 2
                  AND row_number() OVER (PARTITION BY match_date ORDER BY match_id) = 1
                  THEN '16:00:00' ELSE '20:00:00' END AS h FROM match),
keys AS (SELECT match_id, innings_no, over_id, ball_id FROM ball_by_ball
         UNION SELECT match_id, innings_no, over_id, ball_id FROM batsman_scored
         UNION SELECT match_id, innings_no, over_id, ball_id FROM extra_runs
         UNION SELECT match_id, innings_no, over_id, ball_id FROM wicket_taken),
last AS (SELECT match_id, max((innings_no - 1) * 6600 + (c - 1) * 40) AS sec
         FROM (SELECT match_id, innings_no, count(*) AS c FROM keys GROUP BY 1, 2) GROUP BY 1)
SELECT datetime(s.d || ' ' || s.h, '+' || (l.sec + 300) || ' seconds') AS event_time,
       m.match_id, CAST(m.match_winner AS TEXT) AS match_winner, m.win_type, m.win_margin,
       m.outcome_type, CAST(m.man_of_the_match AS TEXT) AS man_of_the_match
FROM match m JOIN s USING (match_id) JOIN last l USING (match_id) ORDER BY m.match_id;
