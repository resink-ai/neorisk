-- local128: bowlers who won a game with a handicap score of 190 or less at all three of
-- Thunderbird, Totem and Bolero Lanes; those winning games, with match, game, handicap score,
-- tournament date and venue.
-- Written from the question (no gold SQL). Reproduces gold variant local128_a.csv, 11 of 11
-- rows as a multiset (bowlers 13, 19 and 25).
WITH w AS (SELECT s.BowlerID, s.MatchID, s.GameNumber, s.HandiCapScore, t.TourneyDate,
                  t.TourneyLocation
           FROM Bowler_Scores s JOIN Tourney_Matches m USING (MatchID)
           JOIN Tournaments t USING (TourneyID)
           WHERE s.WonGame = 1 AND s.HandiCapScore <= 190
             AND t.TourneyLocation IN ('Thunderbird Lanes', 'Totem Lanes', 'Bolero Lanes')),
q AS (SELECT BowlerID FROM w GROUP BY 1 HAVING count(DISTINCT TourneyLocation) = 3)
SELECT b.BowlerID, b.BowlerFirstName, b.BowlerLastName, w.MatchID, w.GameNumber,
       w.HandiCapScore, w.TourneyDate, w.TourneyLocation
FROM w JOIN q USING (BowlerID) JOIN Bowlers b USING (BowlerID)
ORDER BY b.BowlerID, w.TourneyLocation, w.TourneyDate, w.MatchID, w.GameNumber;
