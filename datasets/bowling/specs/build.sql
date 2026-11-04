-- bowling: events → source tables (refdata rebuild, DuckDB).

-- table: Teams
SELECT CAST(t.ext_id AS BIGINT) AS TeamID, t.team_name AS TeamName,
       CAST(c.ext_id AS BIGINT) AS CaptainID
FROM teams t JOIN bowlers c ON c.bowler_id = t.captain_id;

-- table: Bowlers
-- The 4 stats are as of tournament 13: the scores of tournaments dated up to 2017-11-27, a
-- constant (nothing in the source says why week 14 is left out). Average and handicap are
-- integer half-up rounding: avg = (2·pins + games) // (2·games), hcp = (9·(200 − avg) + 5) // 10.
WITH s AS (SELECT g.bowler_id, sum(g.raw_score) AS pins, count(*) AS games
           FROM game_bowled g JOIN match_scheduled m USING (match_id)
           JOIN tournaments t USING (tourney_id)
           WHERE t.tourney_date <= '2017-11-27' GROUP BY g.bowler_id),
a AS (SELECT bowler_id, pins, games, (2 * pins + games) // (2 * games) AS avg FROM s)
SELECT CAST(b.ext_id AS BIGINT) AS BowlerID, b.last_name AS BowlerLastName,
       b.first_name AS BowlerFirstName, b.middle_init AS BowlerMiddleInit,
       b.address AS BowlerAddress, b.city AS BowlerCity, b.state AS BowlerState,
       b.zip AS BowlerZip, b.phone AS BowlerPhoneNumber, CAST(t.ext_id AS BIGINT) AS TeamID,
       coalesce(a.pins, 0) AS BowlerTotalPins, coalesce(a.games, 0) AS BowlerGamesBowled,
       coalesce(a.avg, 0) AS BowlerCurrentAverage,
       coalesce((9 * (200 - a.avg) + 5) // 10, 0) AS BowlerCurrentHcp
FROM bowlers b JOIN teams t USING (team_id) LEFT JOIN a USING (bowler_id);

-- table: Tournaments
SELECT CAST(ext_id AS BIGINT) AS TourneyID, tourney_date AS TourneyDate,
       tourney_location AS TourneyLocation
FROM tournaments;

-- table: Tourney_Matches
SELECT m.match_id AS MatchID, CAST(t.ext_id AS BIGINT) AS TourneyID, m.lanes AS Lanes,
       CAST(o.ext_id AS BIGINT) AS OddLaneTeamID, CAST(e.ext_id AS BIGINT) AS EvenLaneTeamID
FROM match_scheduled m JOIN tournaments t USING (tourney_id)
JOIN teams o ON o.team_id = m.odd_lane_team_id JOIN teams e ON e.team_id = m.even_lane_team_id;

-- table: Match_Games
-- One row per game bowled; the winner is a fill pattern: odd lanes in games 1 and 3, even in 2.
SELECT DISTINCT g.match_id AS MatchID, g.game_number AS GameNumber,
       CAST(CASE g.game_number WHEN 2 THEN e.ext_id ELSE o.ext_id END AS BIGINT) AS WinningTeamID
FROM game_bowled g JOIN match_scheduled m USING (match_id)
JOIN teams o ON o.team_id = m.odd_lane_team_id JOIN teams e ON e.team_id = m.even_lane_team_id;

-- table: Bowler_Scores
SELECT g.match_id AS MatchID, g.game_number AS GameNumber, CAST(b.ext_id AS BIGINT) AS BowlerID,
       g.raw_score AS RawScore, g.handicap_score AS HandiCapScore, g.won_game AS WonGame
FROM game_bowled g JOIN bowlers b USING (bowler_id);

-- table: WAZips
SELECT ext_id AS ZIP, city AS City, state AS State FROM wazips;

-- table: Tournaments_Archive
-- The four _Archive tables are empty in the source. TourneyDate (DATE, NUMERIC affinity)
-- holds nothing, so its results type is int64.
SELECT NULL::BIGINT AS TourneyID, NULL::BIGINT AS TourneyDate, NULL::VARCHAR AS TourneyLocation
WHERE false;

-- table: Tourney_Matches_Archive
SELECT NULL::BIGINT AS MatchID, NULL::BIGINT AS TourneyID, NULL::VARCHAR AS Lanes,
       NULL::BIGINT AS OddLaneTeamID, NULL::BIGINT AS EvenLaneTeamID
WHERE false;

-- table: Match_Games_Archive
SELECT NULL::BIGINT AS MatchID, NULL::BIGINT AS GameNumber, NULL::BIGINT AS WinningTeamID
WHERE false;

-- table: Bowler_Scores_Archive
SELECT NULL::BIGINT AS MatchID, NULL::BIGINT AS GameNumber, NULL::BIGINT AS BowlerID,
       NULL::BIGINT AS RawScore, NULL::BIGINT AS HandiCapScore, NULL::BIGINT AS WonGame
WHERE false;
