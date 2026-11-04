-- name: fk_orphans
SELECT 'scores->bowlers' fk, count(*) FROM Bowler_Scores s WHERE BowlerID NOT IN (SELECT BowlerID FROM Bowlers)
UNION ALL SELECT 'scores->match_games', count(*) FROM Bowler_Scores s WHERE NOT EXISTS (SELECT 1 FROM Match_Games g WHERE g.MatchID=s.MatchID AND g.GameNumber=s.GameNumber)
UNION ALL SELECT 'match_games->matches', count(*) FROM Match_Games WHERE MatchID NOT IN (SELECT MatchID FROM Tourney_Matches)
UNION ALL SELECT 'match_games winner->teams', count(*) FROM Match_Games WHERE WinningTeamID NOT IN (SELECT TeamID FROM Teams)
UNION ALL SELECT 'matches->tournaments', count(*) FROM Tourney_Matches WHERE TourneyID NOT IN (SELECT TourneyID FROM Tournaments)
UNION ALL SELECT 'matches odd->teams', count(*) FROM Tourney_Matches WHERE OddLaneTeamID NOT IN (SELECT TeamID FROM Teams)
UNION ALL SELECT 'matches even->teams', count(*) FROM Tourney_Matches WHERE EvenLaneTeamID NOT IN (SELECT TeamID FROM Teams)
UNION ALL SELECT 'bowlers->teams', count(*) FROM Bowlers WHERE TeamID NOT IN (SELECT TeamID FROM Teams)
UNION ALL SELECT 'teams captain->bowlers', count(*) FROM Teams WHERE CaptainID NOT IN (SELECT BowlerID FROM Bowlers)
UNION ALL SELECT 'bowlers zip->WAZips', count(*) FROM Bowlers WHERE BowlerZip NOT IN (SELECT ZIP FROM WAZips)
UNION ALL SELECT 'bowlers city = WAZips city', sum(b.BowlerCity = z.City) FROM Bowlers b JOIN WAZips z ON z.ZIP=b.BowlerZip
UNION ALL SELECT 'winner in (odd,even)', sum(g.WinningTeamID IN (m.OddLaneTeamID, m.EvenLaneTeamID)) FROM Match_Games g JOIN Tourney_Matches m USING (MatchID)
UNION ALL SELECT 'score bowler team in (odd,even)', sum(b.TeamID IN (m.OddLaneTeamID, m.EvenLaneTeamID)) FROM Bowler_Scores s JOIN Bowlers b USING (BowlerID) JOIN Tourney_Matches m USING (MatchID);
-- name: shape
SELECT (SELECT count(*) FROM (SELECT MatchID FROM Match_Games GROUP BY 1 HAVING count(*)=3)) matches_with_3_games,
       (SELECT count(*) FROM (SELECT MatchID, GameNumber FROM Bowler_Scores GROUP BY 1,2 HAVING count(*)=8)) games_with_8_scores,
       (SELECT count(*) FROM (SELECT s.MatchID, s.GameNumber, b.TeamID FROM Bowler_Scores s JOIN Bowlers b USING (BowlerID) GROUP BY 1,2,3 HAVING count(*)=4)) team_games_with_4;
-- name: team_once_per_tourney
SELECT TourneyID, count(*) slots, count(DISTINCT t) teams FROM (SELECT TourneyID, OddLaneTeamID t FROM Tourney_Matches WHERE MatchID<=56 UNION ALL SELECT TourneyID, EvenLaneTeamID FROM Tourney_Matches WHERE MatchID<=56) GROUP BY 1;
-- name: pair_schedule
-- each pair of the 8 teams meets how many times in 14 tourneys?
SELECT n, count(*) pairs FROM (SELECT min(OddLaneTeamID,EvenLaneTeamID) a, max(OddLaneTeamID,EvenLaneTeamID) b, count(*) n FROM Tourney_Matches WHERE MatchID<=56 GROUP BY 1,2) GROUP BY n;
-- name: winner_vs_team_totals
WITH t AS (SELECT s.MatchID, s.GameNumber, b.TeamID, sum(RawScore) raw, sum(HandiCapScore) hc FROM Bowler_Scores s JOIN Bowlers b USING (BowlerID) GROUP BY 1,2,3),
w AS (SELECT g.*, o.raw oraw, o.hc ohc, e.raw eraw, e.hc ehc, m.OddLaneTeamID odd, m.EvenLaneTeamID even FROM Match_Games g JOIN Tourney_Matches m USING (MatchID)
      JOIN t o ON o.MatchID=g.MatchID AND o.GameNumber=g.GameNumber AND o.TeamID=m.OddLaneTeamID
      JOIN t e ON e.MatchID=g.MatchID AND e.GameNumber=g.GameNumber AND e.TeamID=m.EvenLaneTeamID)
SELECT count(*) games, sum(WinningTeamID = CASE WHEN ohc>ehc THEN odd WHEN ehc>ohc THEN even END) by_handicap_total,
       sum(WinningTeamID = CASE WHEN oraw>eraw THEN odd WHEN eraw>oraw THEN even END) by_raw_total,
       sum(ohc=ehc) hc_ties, sum(WinningTeamID=odd) odd_wins,
       sum(WinningTeamID = CASE WHEN (SELECT sum(WonGame) FROM Bowler_Scores s JOIN Bowlers b USING(BowlerID) WHERE s.MatchID=w.MatchID AND s.GameNumber=w.GameNumber AND b.TeamID=odd)
                                   > (SELECT sum(WonGame) FROM Bowler_Scores s JOIN Bowlers b USING(BowlerID) WHERE s.MatchID=w.MatchID AND s.GameNumber=w.GameNumber AND b.TeamID=even) THEN odd
                                   WHEN (SELECT sum(WonGame) FROM Bowler_Scores s JOIN Bowlers b USING(BowlerID) WHERE s.MatchID=w.MatchID AND s.GameNumber=w.GameNumber AND b.TeamID=odd)
                                   < (SELECT sum(WonGame) FROM Bowler_Scores s JOIN Bowlers b USING(BowlerID) WHERE s.MatchID=w.MatchID AND s.GameNumber=w.GameNumber AND b.TeamID=even) THEN even END) by_wongame_count
FROM w;
-- name: wongame_pairing
-- pair k-th bowler (by BowlerID) of odd team with k-th of even team in each game; compare handicap scores
WITH s AS (SELECT s.*, b.TeamID, row_number() OVER (PARTITION BY s.MatchID, s.GameNumber, b.TeamID ORDER BY s.BowlerID) k FROM Bowler_Scores s JOIN Bowlers b USING (BowlerID)),
p AS (SELECT s.*, o.HandiCapScore opp_hc, o.RawScore opp_raw FROM s JOIN s o ON o.MatchID=s.MatchID AND o.GameNumber=s.GameNumber AND o.k=s.k AND o.TeamID<>s.TeamID)
SELECT count(*) rows_, sum(WonGame = (HandiCapScore > opp_hc)) won_iff_hc_gt, sum(WonGame = (HandiCapScore >= opp_hc)) won_iff_hc_ge,
       sum(WonGame = (RawScore > opp_raw)) won_iff_raw_gt, sum(HandiCapScore=opp_hc) hc_ties, sum(HandiCapScore=opp_hc AND WonGame=1) tie_won FROM p;
-- name: wongame_per_game
SELECT winners, count(*) games FROM (SELECT MatchID, GameNumber, sum(WonGame) winners FROM Bowler_Scores GROUP BY 1,2) GROUP BY 1;
-- name: wongame_mismatch_sample
WITH s AS (SELECT s.*, b.TeamID, row_number() OVER (PARTITION BY s.MatchID, s.GameNumber, b.TeamID ORDER BY s.BowlerID) k FROM Bowler_Scores s JOIN Bowlers b USING (BowlerID)),
p AS (SELECT s.*, o.BowlerID opp, o.HandiCapScore opp_hc FROM s JOIN s o ON o.MatchID=s.MatchID AND o.GameNumber=s.GameNumber AND o.k=s.k AND o.TeamID<>s.TeamID)
SELECT MatchID, GameNumber, BowlerID, HandiCapScore, WonGame, opp, opp_hc FROM p WHERE WonGame <> (HandiCapScore >= opp_hc) LIMIT 20;
