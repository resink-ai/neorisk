-- bowling: source tables → events (refdata ingest). Every entity is created at T0 =
-- 2017-09-04, the first tournament date (a rule: no table has a creation column).
-- Matches and scores take their tournament's date; the match block sorts first by ord.

-- entity: teams
SELECT CAST(TeamID AS TEXT) AS ext_id, '2017-09-04 00:00:00' AS created_at,
       TeamName AS team_name, CAST(CaptainID AS TEXT) AS captain_id
FROM Teams ORDER BY TeamID;

-- entity: bowlers
SELECT CAST(BowlerID AS TEXT) AS ext_id, '2017-09-04 00:00:00' AS created_at,
       BowlerLastName AS last_name, BowlerFirstName AS first_name,
       BowlerMiddleInit AS middle_init, BowlerAddress AS address, BowlerCity AS city,
       BowlerState AS state, BowlerZip AS zip, BowlerPhoneNumber AS phone,
       CAST(TeamID AS TEXT) AS team_id
FROM Bowlers ORDER BY BowlerID;

-- entity: tournaments
SELECT CAST(TourneyID AS TEXT) AS ext_id, '2017-09-04 00:00:00' AS created_at,
       TourneyDate AS tourney_date, TourneyLocation AS tourney_location
FROM Tournaments ORDER BY TourneyID;

-- entity: wazips
SELECT ZIP AS ext_id, '2017-09-04 00:00:00' AS created_at, City AS city, State AS state
FROM WAZips ORDER BY ZIP;

-- event: match_scheduled owner=tourney_id ord=match_id
SELECT t.TourneyDate || ' 00:00:00' AS event_time, CAST(m.TourneyID AS TEXT) AS tourney_id,
       m.MatchID AS match_id, m.Lanes AS lanes,
       CAST(m.OddLaneTeamID AS TEXT) AS odd_lane_team_id,
       CAST(m.EvenLaneTeamID AS TEXT) AS even_lane_team_id
FROM Tourney_Matches m JOIN Tournaments t USING (TourneyID) ORDER BY m.MatchID;

-- event: game_bowled owner=bowler_id ord=match_game
SELECT t.TourneyDate || ' 00:00:00' AS event_time, s.MatchID * 10 + s.GameNumber AS match_game,
       CAST(s.BowlerID AS TEXT) AS bowler_id, s.MatchID AS match_id,
       s.GameNumber AS game_number, s.RawScore AS raw_score,
       s.HandiCapScore AS handicap_score, s.WonGame AS won_game
FROM Bowler_Scores s JOIN Tourney_Matches m USING (MatchID) JOIN Tournaments t USING (TourneyID)
ORDER BY s.MatchID, s.GameNumber, s.BowlerID;
