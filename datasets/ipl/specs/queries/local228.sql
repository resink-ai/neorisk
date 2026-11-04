-- local228: per season, the top 3 run scorers and the top 3 wicket takers (excluding run out,
-- hit wicket and retired hurt), ties to the smaller player id, paired by rank.
-- No gold SQL; written from the question (docs/research/spider2/ipl.md, q5:local228).
-- Reproduces all 27 rows of local228_a.csv.
WITH bat AS (
    SELECT m.season_id, b.striker AS p, sum(s.runs_scored) AS v
    FROM ball_by_ball b
    JOIN batsman_scored s USING (match_id, over_id, ball_id, innings_no)
    JOIN match m USING (match_id)
    GROUP BY 1, 2
),
bowl AS (
    SELECT m.season_id, b.bowler AS p, count(*) AS v
    FROM wicket_taken w
    JOIN ball_by_ball b USING (match_id, over_id, ball_id, innings_no)
    JOIN match m USING (match_id)
    WHERE w.kind_out NOT IN ('run out', 'hit wicket', 'retired hurt')
    GROUP BY 1, 2
),
rb AS (SELECT *, row_number() OVER (PARTITION BY season_id ORDER BY v DESC, p) AS r FROM bat),
rw AS (SELECT *, row_number() OVER (PARTITION BY season_id ORDER BY v DESC, p) AS r FROM bowl)
SELECT rb.season_id, pb.player_name AS batsman_name, rb.v AS total_runs,
       pw.player_name AS bowler_name, rw.v AS total_wickets
FROM rb JOIN rw ON rb.season_id = rw.season_id AND rb.r = rw.r
LEFT JOIN player pb ON pb.player_id = rb.p
LEFT JOIN player pw ON pw.player_id = rw.p
WHERE rb.r <= 3
ORDER BY rb.season_id, rb.r;
