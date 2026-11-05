# bowling

## What this is

A bowling league: eight teams of four bowlers play a double round robin over 14 weekly tournaments, three games a match, each bowler scored per game with a handicap.

Version `v1`, kind `spider2`. The input is one ordered event log of 2,032 events; the output is the 11 source tables, rebuilt exactly, and the answer to 1 saved Spider 2.0 question.

## Raw data

`BowlingLeague.sqlite`, 11 tables. The Bowling League sample database from John L. Viescas and Michael J. Hernandez, *SQL Queries for Mere Mortals*: hand-made and generated course data. The licence is unstated; the files ship with the book for its readers.

The tournaments are 14 Mondays from 2017-09-04 to 2017-12-04, plus six 2018 Thursdays with no matches. They are dates, read as UTC midnight. Match 57 (teams 9 and 10, which have no bowlers) has no games, and bowlers 33 and 34 never bowled. The four `_Archive` tables are empty. `sqlite_sequence` is not data.

The reverse-engineering research, with the queries behind every number, is in [`docs/research/spider2/bowling.md`](../../docs/research/spider2/bowling.md).

## How the log was made

Each match is an event owned by its tournament, and each bowler's game is an event owned by the bowler. Teams, bowlers, tournaments and the Washington ZIP lookup are entities. A team's captain, and a bowler's address, phone and team, are current state the source holds only as of the extract: they travel on `teams_snapshot` and `bowlers_snapshot` at N, not on creation. Teams 9 and 10 are captained by bowlers who play for teams 2 and 6. Both columns are refs, and on the snapshots they no longer form a reference cycle between creation events.

Two things are rebuilt by SQL, not carried:
- `Match_Games` is one row per game bowled. Its `WinningTeamID` is a fill pattern, not a result: the odd-lane team in games 1 and 3, the even-lane team in game 2 (168 of 168 games).
- The four `Bowlers` stats are a function of the scores as of tournament 13, dated 2017-11-27: total pins, games bowled, average = round(pins / games) and handicap = round(0.9 × (200 − average)), both by integer half-up rounding. Bowlers with no games get 0. The cut-off date is a constant in `specs/build.sql`: it matches all 34 bowlers, but nothing in the source says why week 14 is left out.

`WonGame` and `HandiCapScore` are carried verbatim. `WonGame` follows "handicap score at least the paired opponent's" in 1,342 of 1,344 rows, and the handicap is not a function of the running average.

`uv run dataset build bowling` runs `specs/ingest.sql` on the read-only source to make a simkit dataset (an internal stage), then writes it as one log. Entity rows become `<entity>_created` events at their creation time; business events keep their columns. The log is in `seq` order: event time, then entities before events at the same instant. Each row's `payload` is a JSON object whose fields are listed in `schema/events.json`.

## Event catalogue

| Event | Kind | Rows | Payload fields |
|---|---|---:|---|
| `teams_created` | entity | 10 | `team_id`, `ext_id`, `team_name` |
| `bowlers_created` | entity | 34 | `bowler_id`, `ext_id`, `last_name`, `first_name`, `middle_init` |
| `tournaments_created` | entity | 20 | `tourney_id`, `ext_id`, `tourney_date`, `tourney_location` |
| `wazips_created` | entity | 523 | `zip_id`, `ext_id`, `city`, `state` |
| `match_scheduled` | business | 57 | `tourney_id`, `match_id`, `lanes`, `odd_lane_team_id`, `even_lane_team_id` |
| `game_bowled` | business | 1,344 | `bowler_id`, `match_id`, `game_number`, `raw_score`, `handicap_score`, `won_game` |
| `teams_snapshot` | business | 10 | `team_id`, `captain_id` |
| `bowlers_snapshot` | business | 34 | `bowler_id`, `address`, `city`, `state`, `zip`, `phone`, `team_id` |

## Times set by rule

Every entity is created at T0 = 2017-09-04 00:00, the first tournament date; no table has a creation column. This includes the six 2018 tournaments, which are scheduled, not held. Matches and games have no time of their own: they take their tournament's date at midnight. Within a day, matches sort before games, and games by match and game number. Snapshots are at N = 2017-12-04 00:00, the last played tournament and the latest event time in the log.

## Snapshot columns

| Entity | Snapshot event | At (UTC) | Rows | Columns |
|---|---|---|---:|---|
| `teams` | `teams_snapshot` | 2017-12-04 00:00:00 | 10 | `captain_id` |
| `bowlers` | `bowlers_snapshot` | 2017-12-04 00:00:00 | 34 | `address`, `city`, `state`, `zip`, `phone`, `team_id` |

| Column | Verdict | Reason |
|---|---|---|
| `teams.ext_id` | creation | The source key (`TeamID`). |
| `teams.team_name` | creation | A given name. |
| `teams.captain_id` | snapshot | A title held, which can pass to another bowler; teams 9 and 10 are captained from other teams. Research kept it on creation. |
| `bowlers.ext_id` | creation | The source key (`BowlerID`). |
| `bowlers.last_name` | creation | Given names. |
| `bowlers.first_name` | creation | Given names. |
| `bowlers.middle_init` | creation | Given names. |
| `bowlers.address` | snapshot | An address, known only as of the extract. Research kept it on creation. |
| `bowlers.city` | snapshot | An address. Research kept it on creation. |
| `bowlers.state` | snapshot | An address. Research kept it on creation. |
| `bowlers.zip` | snapshot | An address. Research kept it on creation. |
| `bowlers.phone` | snapshot | A phone. Research kept it on creation. |
| `bowlers.team_id` | snapshot | The roster as of the extract (team 7 has 6 bowlers); a bowler can change team, so when in doubt, snapshot. Research kept it on creation. |
| `bowlers.BowlerTotalPins`, `BowlerGamesBowled`, `BowlerCurrentAverage`, `BowlerCurrentHcp` | derived | A function of `game_bowled` with the 2017-11-27 cut-off (34 of 34); computed in `build.sql`, not carried. |
| `tournaments.ext_id` | creation | The source key (`TourneyID`). |
| `tournaments.tourney_date` | creation | The scheduled date the tournament was created with; it also decides its matches' and games' times, so it stays. |
| `tournaments.tourney_location` | creation | Part of the published schedule; the source shows no change. |
| `wazips.ext_id` | creation | The source key (`ZIP`). |
| `wazips.city` | creation | A static postal lookup. |
| `wazips.state` | creation | A static postal lookup. |

No creation event takes a domain name: every entity is created at T0 by rule.

## Expected output

`results/` holds every source table, as the source stores it. Each column's type follows the values it holds: text, int64 or float64. A mixed column holds text and numbers together, so it is stored as SQLite's own text rendering and declared in `dataset.toml`.

| Table | Rows | Columns | Mixed columns |
|---|---:|---:|---|
| `Teams` | 10 | 3 | none |
| `Bowlers` | 34 | 14 | none |
| `Tournaments` | 20 | 3 | none |
| `Tourney_Matches` | 57 | 5 | none |
| `Match_Games` | 168 | 3 | none |
| `Bowler_Scores` | 1,344 | 6 | none |
| `WAZips` | 523 | 3 | none |
| `Tournaments_Archive` | 0 | 3 | none |
| `Tourney_Matches_Archive` | 0 | 5 | none |
| `Match_Games_Archive` | 0 | 3 | none |
| `Bowler_Scores_Archive` | 0 | 6 | none |

`expected/queries/` holds the answer of the saved question (`local128`), computed on the source. `dataset verify` runs `specs/build.sql` over the log, loads the tables into SQLite with the source's DDL, and compares them and the answers exactly: rows as multisets, numbers by value, text byte for byte.

local128 lists the winning games with a handicap score of 190 or less of the bowlers who won such a game at all three of Thunderbird, Totem and Bolero Lanes: 11 games of bowlers 13, 19 and 25. There is no gold SQL; the query is written from the question and reproduces the gold variant `local128_a` as a multiset. It reads `WonGame` and `HandiCapScore`, which is why both are carried verbatim.

The empty `Tournaments_Archive.TourneyDate` is int64: it is declared `DATE` (NUMERIC affinity) and holds no values, so its type falls back to the affinity.

## Regenerate

```bash
uv run refdata fetch                 # once: the Spider 2.0 SQLite files → data/spider2/
uv run dataset build bowling             # → $NEORISK_DATA_ROOT/bowling/v1/ (default data/datasets/)
uv run dataset verify bowling            # exit 0 = every table and answer matches
```

## Extend

- **More rows:** not possible for a fixed source. Stage 2 will generate logs from `specs/pack.py`.
- **A new event type:** declare it in `specs/pack.py`, add its `-- event: <name> owner=<col>` block to `specs/ingest.sql`, and use it in `specs/build.sql`.
- **A new attribute:** add the column to the pack table and to its ingest block. It then appears in the payload and in `schema/events.json`.
- **A new results table:** add it to `specs/source.toml` and a `-- table: <name>` block to `specs/build.sql`.
- **A new saved question:** add `specs/queries/<id>.sql` (SQLite dialect, source table names).
- **A new engine port:** write `engines/<engine>/` from `specs/build.sql`. It must read only the log and match `results/` exactly.
- **Stats after week 14:** a source whose stats were updated later needs a new cut-off constant in the `Bowlers` block of `specs/build.sql`.

Any change to `specs/`, `dataset.toml` or the source changes the build. Once a version is recorded in `v1.lock.json`, changed output needs a new version (`v2`).
