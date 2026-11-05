-- name: local128
WITH w AS (SELECT s.BowlerID, s.MatchID, s.GameNumber, s.HandiCapScore, t.TourneyDate, t.TourneyLocation
           FROM Bowler_Scores s JOIN Tourney_Matches m USING (MatchID) JOIN Tournaments t USING (TourneyID)
           WHERE s.WonGame = 1 AND s.HandiCapScore <= 190 AND t.TourneyLocation IN ('Thunderbird Lanes','Totem Lanes','Bolero Lanes')),
q AS (SELECT BowlerID FROM w GROUP BY 1 HAVING count(DISTINCT TourneyLocation) = 3)
SELECT b.BowlerID, b.BowlerFirstName, b.BowlerLastName, w.MatchID, w.GameNumber, w.HandiCapScore, w.TourneyDate, w.TourneyLocation
FROM w JOIN q USING (BowlerID) JOIN Bowlers b USING (BowlerID) ORDER BY b.BowlerID, w.TourneyLocation, w.TourneyDate;
-- name: raw_score_dist
SELECT (RawScore/10)*10 AS band, count(*) FROM Bowler_Scores GROUP BY 1 ORDER BY 1;
-- name: raw_score_moments
SELECT avg(RawScore) mean, min(RawScore), max(RawScore), sqrt(avg(RawScore*RawScore) - avg(RawScore)*avg(RawScore)) sd FROM Bowler_Scores;
-- name: per_bowler_mean_sd
SELECT BowlerID, round(avg(RawScore),1) mean, min(RawScore) mn, max(RawScore) mx, round(sqrt(avg(RawScore*RawScore)-avg(RawScore)*avg(RawScore)),1) sd FROM Bowler_Scores GROUP BY 1 ORDER BY mean;
-- name: raw_score_spread_per_bowler
-- is each bowler's raw score within a narrow band (generator: base +/- k)?
SELECT max(mx-mn) max_range, min(mx-mn) min_range FROM (SELECT BowlerID, max(RawScore) mx, min(RawScore) mn FROM Bowler_Scores GROUP BY 1);
-- name: handicap_over_time
SELECT m.TourneyID, round(avg(HandiCapScore-RawScore),2) avg_hcp, round(avg(RawScore),2) avg_raw FROM Bowler_Scores s JOIN Tourney_Matches m USING (MatchID) GROUP BY 1;
-- name: handicap_first_match_vs_raw
-- first-match handicap vs 90% of (200 - first-game raw?)
SELECT BowlerID, HandiCapScore-RawScore h FROM Bowler_Scores WHERE MatchID IN (1,2,3,4) AND GameNumber=1 ORDER BY 1;
-- name: wins_per_bowler
SELECT sum(WonGame) wins, count(*) games, round(avg(WonGame),3) rate FROM Bowler_Scores;
-- name: odd_lane_team_won_by_hc
WITH t AS (SELECT s.MatchID, s.GameNumber, b.TeamID, sum(HandiCapScore) hc FROM Bowler_Scores s JOIN Bowlers b USING (BowlerID) GROUP BY 1,2,3)
SELECT sum(o.hc > e.hc) odd_higher, sum(o.hc < e.hc) even_higher, sum(o.hc=e.hc) ties FROM Tourney_Matches m JOIN t o ON o.MatchID=m.MatchID AND o.TeamID=m.OddLaneTeamID JOIN t e ON e.MatchID=m.MatchID AND e.GameNumber=o.GameNumber AND e.TeamID=m.EvenLaneTeamID;
-- name: bowler_dup_names
SELECT BowlerLastName, count(*) FROM Bowlers GROUP BY 1 ORDER BY 2 DESC LIMIT 5;
-- name: bowler_city_vs_zip_city
SELECT b.BowlerID, b.BowlerZip, b.BowlerCity, z.City FROM Bowlers b JOIN WAZips z ON z.ZIP=b.BowlerZip WHERE b.BowlerCity <> z.City;
-- name: wazips_used
SELECT count(DISTINCT BowlerZip) FROM Bowlers;
-- name: lanes_per_location
SELECT t.TourneyLocation, group_concat(DISTINCT m.Lanes) FROM Tourney_Matches m JOIN Tournaments t USING (TourneyID) GROUP BY 1;
