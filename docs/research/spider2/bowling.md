# BowlingLeague (Spider 2.0-lite): reverse-engineered event log

Source: `data/spider2/BowlingLeague.sqlite` (252 KB), opened read-only. `scripts/bowling/rq.py` copies the file into an in-memory SQLite and runs named blocks; the file itself is never written.

Every number below comes from one of these scripts:
- a named query in `scripts/bowling/q*.sql`;
- `profile.py` (every column's storage classes, NULL / `''` / `'\N'`, whitespace, min, max);
- `coltypes.py` (the results type of each column, using the repo's own rule in `apps/dataset/src/dataset/tables.py`);
- `gold_check.py` (a query's answer against a gold CSV, as a multiset);
- `d1_duck_round.sql` (DuckDB rounding check).

The raw outputs are in `scripts/bowling/out_*.txt`. A reference such as `[q3:wongame_pairing]` means file `q3_games.sql`, block `-- name: wongame_pairing`. Gold answer CSVs are in `scripts/bowling/gold/`.

## 0. What this catalog is

- **Dataset.** The **Bowling League** sample database from John L. Viescas and Michael J. Hernandez, *SQL Queries for Mere Mortals*. The evidence is in the rows:
  - The bowlers include 7 Viescas and 2 Hernandez (the authors' surnames), plus the book's recurring families Patterson, Hallmark, Thompson, Kennedy, Sheskey [q1:bowlers, q5:bowler_dup_names].
  - Its sister catalogs in this batch (EntertainmentAgency, school_scheduling) share the same people and the same Access-style schema habits: `ztbl*` helpers, `_Archive` twins, `DEFAULT 0` on every key.
  - `WAZips` (523 Washington ZIP codes) and Seattle-area teams named after sea animals are the book's Bowling League.
- **Edition.** The tournament dates are 2017-09-04 .. 2017-12-04 (14 weekly Mondays) plus six 2018 Thursdays [q1:tournaments]. A 2017 season fits the 4th edition (2018), whose sample files moved the dates forward. This is **unverified**: I did not diff against the publisher's download.
- **Row counts** [profile]: Bowler_Scores 1,344, Match_Games 168, Tourney_Matches 57, Tournaments 20, Bowlers 34, Teams 10, WAZips 523. The four `_Archive` tables (Bowler_Scores_Archive, Match_Games_Archive, Tourney_Matches_Archive, Tournaments_Archive) have 0 rows. Total 2,156.
- **System table.** `sqlite_sequence` has 4 rows. Each `seq` equals its table's max id: Bowlers 34, Teams 10, Tournaments 20, Tourney_Matches 57 [q1:sqlite_sequence]. It is not source data.
- **Licence.** Unstated. The sample files ship with the book (Addison-Wesley) for readers' use. Spider 2.0's repository is MIT, but that does not relicense the rows.
- **Nature.** **Course data**: hand-made and generated for a textbook. The scores come from a simple generator (§4). Nothing is real.

## 0.1 How Spider 2.0 uses it

One question uses db `BowlingLeague`. There is no gold SQL; there is one exec_result CSV.

| id | analysis | gold SQL? | gold value | reproduced |
|---|---|---|---|---|
| local128 | bowlers who won a game with a handicap score ≤ 190 at all three of Thunderbird, Totem and Bolero Lanes; list those winning games with match, game, score, date and venue | no (CSV `_a` only) | 11 rows for bowlers 13 (Hallmark, 3 games), 19 (Viescas, 4) and 25 (Patterson, 4) | ✔ 11 of 11 rows, equal as a multiset [q5:local128, out_gold_check.txt] |

local128 reads `Bowler_Scores.WonGame` and `HandiCapScore`, so both must be carried verbatim, not recomputed (§3.2).

## 1. Inventory, keys, joins

Every declared PK is unique, and rowid order equals PK order in every table [profile]. All 10 declared or implied FKs resolve with 0 orphans [q3:fk_orphans].

| Table | Rows | Key | Kind |
|---|---:|---|---|
| Tournaments | 20 | TourneyID 1..20 | schedule (a date and a venue) |
| Tourney_Matches | 57 | MatchID 1..57 → TourneyID, OddLaneTeamID, EvenLaneTeamID | schedule (no own time) |
| Match_Games | 168 | (MatchID, GameNumber) | **derived** (§3.1) |
| Bowler_Scores | 1,344 | (MatchID, GameNumber, BowlerID) | activity (no own time) |
| Bowlers | 34 | BowlerID → TeamID | party, plus 4 **derived** stats columns (§3.1) |
| Teams | 10 | TeamID; CaptainID → Bowlers | party |
| WAZips | 523 | ZIP | static lookup |
| 4 `_Archive` tables | 0 | as their twins | empty |

Shape, measured:
- Each of the 14 played tournaments has 4 matches between the 8 active teams, each team exactly once [q3:team_once_per_tourney]. Over the 14 weeks each of the 28 team pairs meets exactly twice: a double round robin [q3:pair_schedule].
- Every match has 3 games, and every game has 8 scores, 4 per team [q3:shape].
- Every score's bowler is on one of the match's two teams by `Bowlers.TeamID`, 1,344 of 1,344 [q6:team_membership_static]. There are no substitutes and no transfers, so team membership is static.
- **Unplayed rows.**
  - Match 57 (tournament 11, lanes 19-20) pits teams 10 "Never Show Ups" and 9 "Huckleberrys", which have no bowlers. It has no games and no scores [q1:match_57].
  - Tournaments 15–20 (2018-07-12 .. 08-16) have no matches [q1:tournaments].
  - Bowlers 33 and 34 (Kerry and Maria Patterson, team 7) never bowled, and their stats are all 0 [q1:bowlers].
- **Captains.** Teams 9 and 10 are captained by bowlers 7 and 22, who play for teams 2 and 6 [q6:captain_cross_team]. `Bowlers.TeamID` and `Teams.CaptainID` refer to each other (a reference cycle).
- **WAZips** is used only through an implied join: 12 distinct bowler ZIPs, all present. The bowler's city equals the ZIP's city in 28 of 34 bowlers (for example ZIP 98014 is Carnation, but bowlers 1 and 2 say Bothell) [q3:fk_orphans, q5:bowler_city_vs_zip_city]. The table is not otherwise referenced.

## 2. Event catalogue

Only `Tournaments` carries a time, and it is a date. Matches and scores happen on their tournament's date. There is no time of day, so the order within a day is by key.

| # | Event | Owner | Time | Attributes | Source rows | Count |
|---|---|---|---|---|---|---:|
| E1 | `match_scheduled` | tournament (ord = MatchID) | the tournament's `TourneyDate` (rule: a match has no own time) | match_id, tourney_id (ref), lanes (text), odd_lane_team_id (ref teams), even_lane_team_id (ref teams) | Tourney_Matches | 57 |
| E2 | `game_bowled` | bowler (ord = MatchID, then GameNumber) | the tournament's `TourneyDate` (rule) | match_id, game_number, raw_score, handicap_score, won_game | Bowler_Scores | 1,344 |

**Total events: 1,401.**

Entities (4 tables, 587 rows), all with `created_at` = **T0 = 2017-09-04 00:00** (the first tournament date) by rule, because none has a creation column:

| Entity | Rows | Notes |
|---|---:|---|
| teams | 10 | captain_id: a ref to bowlers, or a plain i64 if the cycle is a problem (§7) |
| bowlers | 34 | team_id (ref); name, address, ZIP, phone (text, middle initial opt). The 4 stats columns are derived and not carried |
| tournaments | 20 | tourney_date (text `YYYY-MM-DD`), tourney_location (text). Created at T0 like the season schedule, including the six 2018 tournaments |
| wazips | 523 | static lookup with no time and no use beyond an implied join; an entity at T0 by rule |

What is **not** an event, and why:
- **Match_Games** is a pure function of E2 and E1: one row per distinct (MatchID, GameNumber) among the scores, and its winner is the odd-lane team for games 1 and 3 and the even-lane team for game 2 (§3.1). It produces no events.
- **Bowler stats** (`BowlerTotalPins`, `BowlerGamesBowled`, `BowlerCurrentAverage`, `BowlerCurrentHcp`) are a pure function of E2 with a date cut-off (§3.1). They are derived, not snapshot columns.
- **A tournament is not an event.** 6 of the 20 have no matches, so a `tournament_held` event would assert something that did not happen. It is a scheduled entity whose date is an attribute.
- **Team membership** is static (§1). There is no `bowler_joined_team` history to emit.
- **The four `_Archive` tables** are empty and have no entity; their views return 0 typed rows.

Snapshot **N = 2017-12-04**, the last played tournament.

## 3. Rebuild rules and blockers to an exact round trip

1. **Derived tables and columns, proven with 0 differing rows.**
   - **Match_Games** [q4:winner_rule_exact, q6:match_games_rebuild_diff]. `WinningTeamID = CASE GameNumber WHEN 2 THEN EvenLaneTeamID ELSE OddLaneTeamID END` holds in 168 of 168 games. The rebuild is `SELECT DISTINCT MatchID, GameNumber, <rule>` over the scores joined to their match: 0 rows in either direction of the EXCEPT, 168 rows.
   - **Bowler stats** [q2:bowler_stats_vs_scores, q6:bowler_stats_rebuild_diff, q6:integer_rule_diff]. The stats are as of tournament 13 (2017-11-27): every active bowler has 39 games there, against the 42 in the scores. With the scores from tournaments dated ≤ 2017-11-27:
     - TotalPins = Σ RawScore, and GamesBowled = the count;
     - CurrentAverage = round(pins / games), which matches 32 of 32 (truncation matches 13);
     - CurrentHcp = round(0.9 × (200 − CurrentAverage)), which matches 32 of 32;
     - bowlers with no games get 0 for all four.

     The full rebuild differs in 0 rows both ways, over 34 bowlers.
   - **Rounding.** Two handicaps fall exactly on a half: bowlers 3 and 23 have average 165, and 0.9 × 35 = 31.5, stored as 32 [q6:hcp_half_rows]. SQLite's and DuckDB's `round` both give 32 [d1_duck_round]. Even so, build.sql should use the integer-only form, which matches 32 of 32 averages and 32 of 32 handicaps [q6:integer_rule_diff]:
     - avg = (2·pins + games) / (2·games);
     - hcp = (9·(200 − avg) + 5) / 10.
   - **The cut-off date 2017-11-27 is a constant in build.sql.** Nothing in the source says why tournament 14 is excluded. It is presumably when the book's authors last ran the update query. Record it in CONTEXT.md.
2. **Not derivable, so carried verbatim.**
   - **`WonGame`.** Pair the k-th bowler (by BowlerID) of each team in a game. "Won if the handicap score ≥ the opponent's" holds for 1,342 of 1,344 rows. "Won if >" holds for 1,300, because all 42 tied pairs are marked as won by both sides [q3:wongame_pairing]. The 2 exceptions are bowlers 16 (match 48) and 12 (match 51), who are marked as winners at 200 vs 203 and 202 vs 206, both against bowler 24 [q3:wongame_mismatch_sample]. Carry it as i64 on E2.
   - **`HandiCapScore`.** HandiCapScore − RawScore is the game's handicap, 20..55 [q5:score_handicap]. It is constant within a bowler's match in all but 1 of 448 bowler-matches: bowler 24 in match 8 has 28, 28, 29 [q2:hcp_per_bowler_match]. It is not 90% of (200 − the running average): only 317 of 416 later matches fit [q2:hcp_vs_prior_avg]. Carry it verbatim.
3. **Times.** `TourneyDate` is `YYYY-MM-DD` text in 20 of 20 rows [q1:date_format]. Read it as UTC midnight and format it back with `%Y-%m-%d`. The one time on E1 and E2 is the tournament's date. Since the tournament is a T0 entity, the date also travels as text on the entity, and the views take it from there.
4. **Results types** [coltypes]. No column is mixed. Every score, id and stat is int64; `BOOLEAN` WonGame holds only integers, so it is int64. `TourneyDate` (declared `DATE`, NUMERIC affinity) holds only text, so it is string. The empty `Tournaments_Archive.TourneyDate` falls back to its affinity and becomes **int64**, so the empty view must cast it to BIGINT, not VARCHAR.
5. **NULL vs empty.** No `''` and no `'\N'` anywhere. The only NULLs are `BowlerMiddleInit`, 23 of 34 [profile]. No text has leading or trailing whitespace.
6. **Floats, duplicates, untimed rows.** There are no floats. No duplicate keys. Every untimed row is an entity at T0; the only invented times are the T0 rule and "a score happens on its tournament's date".

**Verdict:** exact round trip, yes. The two derived tables have 0-row proofs. The only judgment call is the stats cut-off constant.

## 4. Measured quirks

- **`WinningTeamID` is a fill pattern, not a result.** It is odd, even, odd in every match: the odd-lane team in 56 of 56 game 1s and game 3s, and the even-lane team in 56 of 56 game 2s [q4:winner_by_game_number]. Compare that with the scores: the winner has the higher team handicap total in only 81 of 168 games (82 by raw total) [q3:winner_vs_team_totals]. Any analysis of team wins on this table is meaningless; stage 2 should not fit it.
- **Bowler-level wins are honest.** `WonGame` follows the pairwise handicap rule (§3.2). Ties count as a win for both, so there are 4–7 winners per 8-bowler game: 4 in 148 games, 5 in 18, 6 in 1, 7 in 1 [q5:wins_per_bowler, q3:wongame_per_game]. The overall win rate is 695 of 1,344 = 51.7%.
- **Score generator.** Raw scores are 135..195, mean 154.5, sd 14.7 [q5:raw_score_moments]. Bowlers fall into skill tiers by their mean, about 142, 149, 157 and 165, with one per team at each tier in every team but team 6 (whose bowler 24 replaces the low tier). The higher the tier, the wider the range: bowler 32 has 136–149, bowler 27 has 137–195 [q5:per_bowler_mean_sd]. Every bowler's floor is 135–140, except bowler 24, whose range is 159–178. The mean per tournament is flat, 152.8–156.6 [q5:handicap_over_time].
- **Lanes.** Each match takes a pair of lanes (`01-02` .. `27-28`), with a venue-specific block of 6–8 lane pairs per venue [q5:lanes_per_location]. Lanes is text with leading zeros.
- **Calendar.** 14 consecutive Mondays from 2017-09-04, then six 2018 Thursdays from 2018-07-12 with no matches [q1:tournaments]. The 7 venues rotate in a fixed order (Red Rooster, Thunderbird, Bolero, Imperial, Sports World, Totem, Acapulco); 2018 drops Acapulco and swaps Imperial and Sports World.
- **Placeholders.** Teams 9 and 10 have no bowlers, and they are the two sides of unplayed match 57. Bowlers 33 and 34 have no games. These rows exist so that the book's outer-join exercises return something.
- **Bowler city vs ZIP** disagrees in 6 of 34 rows (§1).

## 5. Distributions to fit (stage 2)

| Quantity | Value |
|---|---|
| tournaments | weekly, 1 per Monday; 4 matches each; 7 venues in rotation [q1:tournaments] |
| schedule | a double round robin over 8 teams in 14 weeks [q3:pair_schedule] |
| games | 3 per match; 4 bowlers per team per game |
| raw score | 135–195, mean 154.5, sd 14.7. Bands: 130s 201, 140s 448, 150s 244, 160s 198, 170s 161, 180s 64, 190s 28 [q5:raw_score_dist] |
| per-bowler skill | means 142–169; sd 3.8 for the low tier up to 18 for the high tier [q5:per_bowler_mean_sd] |
| handicap | 20–55 pins, mean about 40.8 per tournament, near 0.9 × (200 − average) [q5:score_handicap, q5:handicap_over_time] |
| bowler win rate | 51.7%; ties count as a win for both [q5:wins_per_bowler] |

Volume is tiny (1.4k events). The generator is simple enough that fitting means reproducing per-bowler score bands, not a rich distribution.

## 6. simkit mapping sketch

```python
p.entity("teams", key="team_id", cols={"ext_id": text(), "team_name": text(), "captain_id": ref("bowlers")})
p.entity("bowlers", key="bowler_id", cols={"ext_id": text(), "last_name": text(), "first_name": text(),
         "middle_init": opt(text()), "address": text(), "city": text(), "state": text(), "zip": text(),
         "phone": text(), "team_id": ref("teams")})
p.entity("tournaments", key="tourney_id", cols={"ext_id": text(), "tourney_date": text(doc="'YYYY-MM-DD'"),
         "tourney_location": text()})
p.entity("wazips", key="zip_id", cols={"ext_id": text(doc="the ZIP"), "city": text(), "state": text()})
p.event("match_scheduled", cols={"tourney_id": ref("tournaments"), "match_id": i64(), "lanes": text(),
        "odd_lane_team_id": ref("teams"), "even_lane_team_id": ref("teams")})
p.event("game_bowled", cols={"bowler_id": ref("bowlers"), "match_id": i64(), "game_number": i64(min=1),
        "raw_score": i64(), "handicap_score": i64(), "won_game": i64()})
```

Ingest:
- Entities: every `created_at = '2017-09-04 00:00:00'`.
- `-- event: match_scheduled owner=tourney_id ord=match_id`: Tourney_Matches ⋈ Tournaments, `event_time = TourneyDate`, ORDER BY MatchID.
- `-- event: game_bowled owner=bowler_id ord=match_game`, with `ord = MatchID*10 + GameNumber`: Bowler_Scores ⋈ Tourney_Matches ⋈ Tournaments, ORDER BY MatchID, GameNumber, BowlerID.
- The match block comes first, so a match sorts before its games on the same date.

build.sql:
- `Tournaments`, `Teams`, `Bowlers` (base columns), `WAZips` and `Tourney_Matches` come straight from entities and E1.
- `Bowler_Scores` = E2.
- `Match_Games` = `SELECT DISTINCT match_id, game_number, CASE game_number WHEN 2 THEN even ELSE odd END` from E2 ⋈ E1.
- The Bowlers stats come from a LEFT JOIN to E2 aggregated over tournaments with `tourney_date <= '2017-11-27'`, with the integer rounding of §3.1 and `coalesce(…, 0)`.
- The four `_Archive` tables are `SELECT … WHERE false` with their types; `TourneyDate` is BIGINT there.

Stage 2 owners:
- a **league** source that emits the weekly schedule (round robin, venue rotation);
- **bowler** owners that draw scores from per-tier bands;
- a referee rule for `won_game`.

The derived tables then follow from the views with no extra events.

## 7. Open questions and risks

- **Edition and licence.** The 4th-edition attribution of the dates and the book's licence for its sample files are unverified. The risk is low for fitting statistics; confirm before redistributing rows.
- **Reference cycle.** `teams.captain_id → bowlers` and `bowlers.team_id → teams`. If the ingest needs a ref's target to exist before the referring entity, carry `captain_id` as `i64` (BowlerID verbatim) and join on ext_id in the view.
- **Stats cut-off.** The 2017-11-27 constant is proven, not explained. If a variant of the file updated the stats after week 14, the view's constant must change. A snapshot-column fallback (carry the four stats on a `bowlers_snapshot` event) is also exact, but it would put week-13 values at an N after week 14.
- **`WinningTeamID`** contradicts the scores in about half the games (§4). The rebuild reproduces the source's rule exactly; it does not "fix" it.
- **The two `WonGame` exceptions** (bowler 24's opponents in matches 48 and 51) may be hand edits in the book's data. They are carried verbatim.
- **Time of day.** None exists; every score in a tournament shares one timestamp. Order within a day comes from `ord`, which is enough for the round trip but carries no behavioural meaning.

**Summary**
- Exact round trip: yes. Match_Games and the four Bowlers stats columns are derived with 0 differing rows; the rest is carried verbatim.
- Dataset name: `bowling`.
- Event types 2 (`match_scheduled`, `game_bowled`); entities 4 (teams, bowlers, tournaments, wazips); 4 empty `_Archive` tables.
- Event shape: partly imposed. The scores are natural per-game events, but their times are their tournament's date by rule, and all entities sit at T0 by rule.
- Hardest blocker: the bowler stats are frozen at an unexplained cut-off (tournaments ≤ 2017-11-27), so build.sql carries that date as a constant. Close behind: `WinningTeamID` is a fill pattern (odd, even, odd) and not a real result.
