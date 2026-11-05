-- name: bowler_stats_vs_scores
-- Do BowlerTotalPins / GamesBowled / Average / Hcp follow from Bowler_Scores?
SELECT b.BowlerID, b.BowlerTotalPins, s.pins, s.pins_first13, b.BowlerGamesBowled, s.games, s.games_first13,
       b.BowlerCurrentAverage, b.BowlerTotalPins / NULLIF(b.BowlerGamesBowled,0) AS avg_int, b.BowlerCurrentHcp
FROM Bowlers b LEFT JOIN (
  SELECT BowlerID, sum(RawScore) pins, count(*) games,
         sum(CASE WHEN m.TourneyID<=13 THEN RawScore END) pins_first13, sum(m.TourneyID<=13) games_first13
  FROM Bowler_Scores s JOIN Tourney_Matches m USING (MatchID) GROUP BY BowlerID) s USING (BowlerID) ORDER BY BowlerID;
-- name: pins_match_any_prefix
-- For each bowler, which prefix of their games (in match/game order) sums to BowlerTotalPins with count = GamesBowled?
WITH s AS (SELECT BowlerID, MatchID, GameNumber, RawScore, row_number() OVER (PARTITION BY BowlerID ORDER BY MatchID, GameNumber) n,
             sum(RawScore) OVER (PARTITION BY BowlerID ORDER BY MatchID, GameNumber) cum FROM Bowler_Scores)
SELECT sum(b.BowlerTotalPins = s.cum) AS total_eq_prefix_sum, count(*) AS bowlers
FROM Bowlers b JOIN s ON s.BowlerID=b.BowlerID AND s.n=b.BowlerGamesBowled;
-- name: avg_rule
SELECT sum(BowlerCurrentAverage = BowlerTotalPins / BowlerGamesBowled) AS avg_is_floor, sum(BowlerCurrentAverage = CAST(round(1.0*BowlerTotalPins/BowlerGamesBowled) AS INT)) AS avg_is_round, count(*) FROM Bowlers WHERE BowlerGamesBowled>0;
-- name: hcp_rule
SELECT sum(BowlerCurrentHcp = CAST(0.9*(200-BowlerCurrentAverage) AS INT)) AS hcp_90pct_200_trunc,
       sum(BowlerCurrentHcp = CAST(round(0.9*(200-BowlerCurrentAverage)) AS INT)) AS hcp_90pct_200_round,
       sum(BowlerCurrentHcp = CAST(0.9*(200-1.0*BowlerTotalPins/BowlerGamesBowled) AS INT)) AS hcp_90pct_exactavg_trunc,
       sum(BowlerCurrentHcp = CAST(round(0.9*(200-1.0*BowlerTotalPins/BowlerGamesBowled)) AS INT)) AS hcp_90pct_exactavg_round,
       count(*) FROM Bowlers WHERE BowlerGamesBowled>0;
-- name: hcp_mismatch
SELECT BowlerID, BowlerTotalPins, BowlerGamesBowled, BowlerCurrentAverage, BowlerCurrentHcp, 0.9*(200-BowlerCurrentAverage) AS x, 0.9*(200-1.0*BowlerTotalPins/BowlerGamesBowled) y
FROM Bowlers WHERE BowlerGamesBowled>0 AND BowlerCurrentHcp <> CAST(round(0.9*(200-BowlerCurrentAverage)) AS INT);
-- name: score_handicap
-- HandiCapScore - RawScore per row
SELECT HandiCapScore - RawScore AS hcp, count(*) FROM Bowler_Scores GROUP BY 1 ORDER BY 1;
-- name: hcp_per_bowler_match
-- is handicap constant within a match? within a bowler overall?
SELECT (SELECT count(*) FROM (SELECT BowlerID, MatchID FROM Bowler_Scores GROUP BY 1,2 HAVING count(DISTINCT HandiCapScore-RawScore)>1)) AS bowler_matches_varying,
       (SELECT count(*) FROM (SELECT BowlerID FROM Bowler_Scores GROUP BY 1 HAVING count(DISTINCT HandiCapScore-RawScore)>1)) AS bowlers_varying,
       (SELECT count(*) FROM (SELECT BowlerID FROM Bowler_Scores GROUP BY 1)) AS bowlers;
-- name: hcp_vs_current
SELECT sum(x.h = b.BowlerCurrentHcp), count(*) FROM (SELECT BowlerID, min(HandiCapScore-RawScore) h FROM Bowler_Scores GROUP BY 1) x JOIN Bowlers b USING (BowlerID);
-- name: hcp_vs_prior_avg
-- handicap in a match vs 90% of (200 - running average before that match)
WITH g AS (SELECT s.*, row_number() OVER (PARTITION BY BowlerID ORDER BY MatchID, GameNumber) n FROM Bowler_Scores s),
pm AS (SELECT BowlerID, MatchID, min(HandiCapScore-RawScore) h, min(n) n0 FROM g GROUP BY 1,2),
pr AS (SELECT pm.*, (SELECT sum(RawScore) FROM g WHERE g.BowlerID=pm.BowlerID AND g.n<pm.n0) pins, pm.n0-1 games FROM pm)
SELECT CASE WHEN games=0 THEN 'first match' ELSE 'later' END k, count(*), sum(h = CAST(0.9*(200 - pins/games) AS INT)) trunc_int_avg,
       sum(h = CAST(round(0.9*(200 - 1.0*pins/games)) AS INT)) round_real_avg, sum(h = CAST(0.9*(200 - 1.0*pins/games) AS INT)) trunc_real_avg FROM pr GROUP BY 1;
