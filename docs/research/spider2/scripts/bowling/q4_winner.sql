-- name: winner_by_game_number
SELECT g.GameNumber, sum(WinningTeamID=OddLaneTeamID) odd, sum(WinningTeamID=EvenLaneTeamID) even FROM Match_Games g JOIN Tourney_Matches m USING (MatchID) GROUP BY 1;
-- name: winner_rule_exact
SELECT count(*) games, sum(WinningTeamID = CASE GameNumber WHEN 2 THEN EvenLaneTeamID ELSE OddLaneTeamID END) rule_odd_even_odd FROM Match_Games g JOIN Tourney_Matches m USING (MatchID);
