-- IPL: events → source tables (refdata rebuild, DuckDB). Placeholders (listed = 0) are no rows.

-- table: player
SELECT CAST(ext_id AS BIGINT) AS player_id, player_name, dob, batting_hand, bowling_skill,
       country_name
FROM players WHERE listed = 1;

-- table: team
SELECT CAST(ext_id AS BIGINT) AS team_id, name FROM teams WHERE listed = 1;

-- table: match
SELECT s.match_id, CAST(t1.ext_id AS BIGINT) AS team_1, CAST(t2.ext_id AS BIGINT) AS team_2,
       strftime(s.event_time AT TIME ZONE 'UTC', '%Y-%m-%d') AS match_date, s.season_id, s.venue,
       CAST(tw.ext_id AS BIGINT) AS toss_winner, d.toss_decision, c.win_type, c.win_margin,
       c.outcome_type, CAST(mw.ext_id AS BIGINT) AS match_winner,
       CAST(mm.ext_id AS BIGINT) AS man_of_the_match
FROM match_scheduled s
JOIN toss_decided d USING (match_id)
JOIN match_completed c USING (match_id)
JOIN teams t1 ON t1.team_key = s.team_1
JOIN teams t2 ON t2.team_key = s.team_2
JOIN teams tw ON tw.team_key = d.toss_winner
JOIN teams mw ON mw.team_key = c.match_winner
JOIN players mm ON mm.player_key = c.man_of_the_match;

-- table: player_match
SELECT n.match_id, CAST(p.ext_id AS BIGINT) AS player_id, n.role,
       CAST(t.ext_id AS BIGINT) AS team_id
FROM player_named n JOIN players p ON p.player_key = n.player_id
JOIN teams t ON t.team_key = n.team_id;

-- table: ball_by_ball
-- teams_swapped = 1: the source labels this delivery's sides the other way round.
SELECT b.match_id, b.over_id, b.ball_id, b.innings_no,
       CAST(CASE WHEN b.teams_swapped = 1 THEN tw.ext_id ELSE tb.ext_id END AS BIGINT)
           AS team_batting,
       CAST(CASE WHEN b.teams_swapped = 1 THEN tb.ext_id ELSE tw.ext_id END AS BIGINT)
           AS team_bowling,
       b.striker_batting_position, CAST(ps.ext_id AS BIGINT) AS striker,
       CAST(pn.ext_id AS BIGINT) AS non_striker, CAST(pb.ext_id AS BIGINT) AS bowler
FROM ball_bowled b
JOIN innings_started i ON i.match_id = b.match_id AND i.innings_no = b.innings_no
JOIN teams tb ON tb.team_key = i.team_batting
JOIN teams tw ON tw.team_key = i.team_bowling
JOIN players ps ON ps.player_key = b.striker
JOIN players pn ON pn.player_key = b.non_striker
JOIN players pb ON pb.player_key = b.bowler
WHERE b.has_ball_row = 1;

-- table: batsman_scored
SELECT match_id, over_id, ball_id, runs_scored, innings_no
FROM ball_bowled WHERE runs_scored IS NOT NULL;

-- table: wicket_taken
SELECT b.match_id, b.over_id, b.ball_id, CAST(p.ext_id AS BIGINT) AS player_out, b.kind_out,
       b.innings_no
FROM ball_bowled b JOIN players p ON p.player_key = b.player_out
WHERE b.kind_out IS NOT NULL;

-- table: extra_runs
SELECT match_id, over_id, ball_id, extra_type, extra_runs, innings_no
FROM ball_bowled WHERE extra_type IS NOT NULL;
