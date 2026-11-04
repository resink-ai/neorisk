-- name: sqlite_sequence
SELECT s.name, s.seq, CASE s.name WHEN 'Bowlers' THEN (SELECT max(BowlerID) FROM Bowlers) WHEN 'Teams' THEN (SELECT max(TeamID) FROM Teams)
  WHEN 'Tournaments' THEN (SELECT max(TourneyID) FROM Tournaments) WHEN 'Tourney_Matches' THEN (SELECT max(MatchID) FROM Tourney_Matches) END AS max_id FROM sqlite_sequence s;
-- name: tournaments
SELECT t.*, strftime('%w', TourneyDate) AS dow, (SELECT count(*) FROM Tourney_Matches m WHERE m.TourneyID=t.TourneyID) AS matches FROM Tournaments t ORDER BY TourneyID;
-- name: date_format
SELECT length(TourneyDate) AS len, count(*) FROM Tournaments GROUP BY 1;
-- name: teams
SELECT t.*, (SELECT count(*) FROM Bowlers b WHERE b.TeamID=t.TeamID) AS bowlers, (SELECT TeamID FROM Bowlers b WHERE b.BowlerID=t.CaptainID) AS captain_team FROM Teams t;
-- name: bowlers
SELECT BowlerID, BowlerLastName, BowlerFirstName, TeamID, BowlerTotalPins, BowlerGamesBowled, BowlerCurrentAverage, BowlerCurrentHcp, BowlerZip, BowlerCity FROM Bowlers;
-- name: matches
SELECT * FROM Tourney_Matches ORDER BY MatchID;
-- name: match_57
SELECT m.*, (SELECT count(*) FROM Match_Games g WHERE g.MatchID=m.MatchID) AS games, (SELECT count(*) FROM Bowler_Scores s WHERE s.MatchID=m.MatchID) AS scores FROM Tourney_Matches m WHERE MatchID NOT IN (SELECT MatchID FROM Match_Games);
