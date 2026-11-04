-- name: bowler_stats_rebuild_diff
-- Bowler stats rebuilt from scores in tournaments dated <= 2017-11-27 (all but the last played one). Rows that differ, both ways.
WITH s AS (SELECT BowlerID, sum(RawScore) pins, count(*) games FROM Bowler_Scores s JOIN Tourney_Matches m USING (MatchID) JOIN Tournaments t USING (TourneyID)
           WHERE t.TourneyDate <= '2017-11-27' GROUP BY 1),
r AS (SELECT b.BowlerID, coalesce(s.pins,0) BowlerTotalPins, coalesce(s.games,0) BowlerGamesBowled,
             coalesce(CAST(round(1.0*s.pins/s.games) AS INT),0) BowlerCurrentAverage,
             coalesce(CAST(round(0.9*(200 - round(1.0*s.pins/s.games))) AS INT),0) BowlerCurrentHcp
      FROM Bowlers b LEFT JOIN s USING (BowlerID)),
o AS (SELECT BowlerID, BowlerTotalPins, BowlerGamesBowled, BowlerCurrentAverage, BowlerCurrentHcp FROM Bowlers)
SELECT (SELECT count(*) FROM (SELECT * FROM r EXCEPT SELECT * FROM o)) r_minus_o, (SELECT count(*) FROM (SELECT * FROM o EXCEPT SELECT * FROM r)) o_minus_r;
-- name: hcp_rounding_halves
-- do any averages or handicaps land exactly on .5 (rounding mode matters)?
SELECT sum((2*BowlerTotalPins) % BowlerGamesBowled = 0 AND (BowlerTotalPins % BowlerGamesBowled) <> 0) avg_exact_half,
       sum(((200-BowlerCurrentAverage)*9) % 10 = 5) hcp_exact_half FROM Bowlers WHERE BowlerGamesBowled>0;
-- name: match_games_rebuild_diff
WITH r AS (SELECT DISTINCT s.MatchID, s.GameNumber, CASE s.GameNumber WHEN 2 THEN m.EvenLaneTeamID ELSE m.OddLaneTeamID END WinningTeamID
           FROM Bowler_Scores s JOIN Tourney_Matches m USING (MatchID))
SELECT (SELECT count(*) FROM (SELECT * FROM r EXCEPT SELECT * FROM Match_Games)) r_minus_o, (SELECT count(*) FROM (SELECT * FROM Match_Games EXCEPT SELECT * FROM r)) o_minus_r,
       (SELECT count(*) FROM r) r_rows;
-- name: team_membership_static
-- every score's bowler is on one of the two teams by Bowlers.TeamID (no substitutes, no transfers)
SELECT count(*) scores, sum(b.TeamID IN (m.OddLaneTeamID, m.EvenLaneTeamID)) on_a_team FROM Bowler_Scores s JOIN Bowlers b USING (BowlerID) JOIN Tourney_Matches m USING (MatchID);
-- name: captain_cross_team
SELECT t.TeamID, t.TeamName, t.CaptainID, b.TeamID AS captain_team FROM Teams t JOIN Bowlers b ON b.BowlerID=t.CaptainID WHERE b.TeamID<>t.TeamID;
-- name: hcp_half_rows
SELECT BowlerID, BowlerCurrentAverage, BowlerCurrentHcp, 0.9*(200-BowlerCurrentAverage) AS f, printf('%.17g', 0.9*(200-BowlerCurrentAverage)) f17, round(0.9*(200-BowlerCurrentAverage)) sqlite_round,
       (9*(200-BowlerCurrentAverage)+5)/10 AS int_rule FROM Bowlers WHERE BowlerGamesBowled>0 AND ((200-BowlerCurrentAverage)*9) % 10 = 5;
-- name: integer_rule_diff
-- integer-only rule: avg = (2*pins + games) / (2*games); hcp = (9*(200-avg) + 5) / 10
WITH s AS (SELECT BowlerID, sum(RawScore) pins, count(*) games FROM Bowler_Scores s JOIN Tourney_Matches m USING (MatchID) JOIN Tournaments t USING (TourneyID)
           WHERE t.TourneyDate <= '2017-11-27' GROUP BY 1)
SELECT count(*) bowlers, sum(b.BowlerCurrentAverage = (2*s.pins + s.games)/(2*s.games)) avg_ok, sum(b.BowlerCurrentHcp = (9*(200-(2*s.pins + s.games)/(2*s.games))+5)/10) hcp_ok
FROM Bowlers b JOIN s USING (BowlerID);
