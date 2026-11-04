# eusoccer

## What this is

The European Soccer Database: 25,979 matches in 11 top-flight European leagues over 8 seasons (2008/09 to 2015/16), with lineups, in-match incidents as XML and bookmaker odds, plus dated EA FIFA ratings for 11,060 players and 299 teams.

Version `v1`, kind `spider2`. The input is one ordered event log of 233,856 events; the output is the 7 source tables, rebuilt exactly, and the answers to 5 saved Spider 2.0 questions.

## Raw data

`EU_soccer.sqlite` (all 7 data tables: `Country`, `League`, `Team`, `Player`, `Match`, `Player_Attributes`, `Team_Attributes`). This is Hugo Mathien's Kaggle database (2016), recalled as ODbL 1.0; its content is third-party (football-data.co.uk bookmaker odds, enetscores incidents, EA FIFA ratings scraped from sofifa). Real data, scraped and not anonymised. Spider added the view `match_view`, which joins Match with the league, team and player names. `sqlite_sequence` holds generator fingerprints, not data, and is not compared.

Dates only: every date is `YYYY-MM-DD 00:00:00`, read as UTC midnight. Creation times of the four masters, and the height and weight snapshot, are rules.

The reverse-engineering research, with the queries behind every number, is in [`docs/research/spider2/eusoccer.md`](../../docs/research/spider2/eusoccer.md).

## How the log was made

Each match is a `match_played` event owned by its league, at its date, ordered by `Match.id` within a day. It carries the score, the 22 lineup slots as player refs, the 44 lineup coordinates, the 8 XML columns verbatim and the 30 odds as floats. Each `Player_Attributes` row is a `player_rated` event owned by its player, and each `Team_Attributes` row a `team_rated` event owned by its team, at the rating date. The 836 all-NULL `Player_Attributes` twins stay events with NULL ratings, and the scraper-damaged work rates (`'None'`, `norm`, `_0`, digits) travel as text. Countries, leagues, teams and players are entities; each source id (`Match.id`, `Team.id`, `Player.id`, the attribute ids) rides on its event or entity, because none follows from order. `players_snapshot` carries each player's height and weight at N.

`specs/build.sql` derives three things, each proved with 0 differing rows: `Match.country_id` is the league's country, `Team_Attributes.team_fifa_api_id` is the team's own, and the 9 classes of numeric tactics are bands of the value (≤ 33, 34–66, ≥ 67; a NULL `buildUpPlayDribbling` is `'Little'`). `Player_Attributes.player_fifa_api_id` is carried, since 212 rows disagree with the player's own.

The XML is 268,858,266 characters, 90% of the source. It comes back byte for byte, including the empty elements such as `<goal />` and Match 3639's pretty-printed values with tabs and newlines. The log's payloads hold 490,824,555 characters; the zstd log file is 47 MB. Build plus verify took 34 s + 13 s on an Apple-silicon laptop.

`uv run dataset build eusoccer` runs `specs/ingest.sql` on the read-only source to make a simkit dataset (an internal stage), then writes it as one log. Entity rows become `<entity>_created` events at their creation time; business events keep their columns. The log is in `seq` order: event time, then entities before events at the same instant. Each row's `payload` is a JSON object whose fields are listed in `schema/events.json`.

## Event catalogue

| Event | Kind | Rows | Payload fields |
|---|---|---:|---|
| `countries_created` | entity | 11 | `country_id`, `ext_id`, `name` |
| `leagues_created` | entity | 11 | `league_id`, `ext_id`, `country_id`, `name` |
| `teams_created` | entity | 299 | `team_id`, `ext_id`, `team_row_id`, `team_fifa_api_id`, `team_long_name`, `team_short_name` |
| `players_created` | entity | 11,060 | `player_id`, `ext_id`, `player_row_id`, `player_name`, `player_fifa_api_id`, `birthday` |
| `players_snapshot` | business | 11,060 | `player_id`, `height`, `weight` |
| `match_played` | business | 25,979 | `league_id`, `match_id`, `match_api_id`, `season`, `stage`, `home_team_id`, `away_team_id`, `home_team_goal`, `away_team_goal`, `home_player_X1`, `home_player_X2`, `home_player_X3`, `home_player_X4`, `home_player_X5`, `home_player_X6`, `home_player_X7`, `home_player_X8`, `home_player_X9`, `home_player_X10`, `home_player_X11`, `home_player_Y1`, `home_player_Y2`, `home_player_Y3`, `home_player_Y4`, `home_player_Y5`, `home_player_Y6`, `home_player_Y7`, `home_player_Y8`, `home_player_Y9`, `home_player_Y10`, `home_player_Y11`, `away_player_X1`, `away_player_X2`, `away_player_X3`, `away_player_X4`, `away_player_X5`, `away_player_X6`, `away_player_X7`, `away_player_X8`, `away_player_X9`, `away_player_X10`, `away_player_X11`, `away_player_Y1`, `away_player_Y2`, `away_player_Y3`, `away_player_Y4`, `away_player_Y5`, `away_player_Y6`, `away_player_Y7`, `away_player_Y8`, `away_player_Y9`, `away_player_Y10`, `away_player_Y11`, `home_player_1`, `home_player_2`, `home_player_3`, `home_player_4`, `home_player_5`, `home_player_6`, `home_player_7`, `home_player_8`, `home_player_9`, `home_player_10`, `home_player_11`, `away_player_1`, `away_player_2`, `away_player_3`, `away_player_4`, `away_player_5`, `away_player_6`, `away_player_7`, `away_player_8`, `away_player_9`, `away_player_10`, `away_player_11`, `goal`, `shoton`, `shotoff`, `foulcommit`, `card`, `cross`, `corner`, `possession`, `B365H`, `B365D`, `B365A`, `BWH`, `BWD`, `BWA`, `IWH`, `IWD`, `IWA`, `LBH`, `LBD`, `LBA`, `PSH`, `PSD`, `PSA`, `WHH`, `WHD`, `WHA`, `SJH`, `SJD`, `SJA`, `VCH`, `VCD`, `VCA`, `GBH`, `GBD`, `GBA`, `BSH`, `BSD`, `BSA` |
| `player_rated` | business | 183,978 | `player_id`, `attr_id`, `player_fifa_api_id`, `preferred_foot`, `attacking_work_rate`, `defensive_work_rate`, `overall_rating`, `potential`, `crossing`, `finishing`, `heading_accuracy`, `short_passing`, `volleys`, `dribbling`, `curve`, `free_kick_accuracy`, `long_passing`, `ball_control`, `acceleration`, `sprint_speed`, `agility`, `reactions`, `balance`, `shot_power`, `jumping`, `stamina`, `strength`, `long_shots`, `aggression`, `interceptions`, `positioning`, `vision`, `penalties`, `marking`, `standing_tackle`, `sliding_tackle`, `gk_diving`, `gk_handling`, `gk_kicking`, `gk_positioning`, `gk_reflexes` |
| `team_rated` | business | 1,458 | `team_id`, `attr_id`, `buildUpPlaySpeed`, `buildUpPlayDribbling`, `buildUpPlayPassing`, `chanceCreationPassing`, `chanceCreationCrossing`, `chanceCreationShooting`, `defencePressure`, `defenceAggression`, `defenceTeamWidth`, `buildUpPlayPositioningClass`, `chanceCreationPositioningClass`, `defenceDefenderLineClass` |

## Times set by rule

Countries and leagues are created at their first match (2008-07-18 to 2008-08-30). Teams are created at the earlier of their first match and their first team rating (51 teams are rated before they first play). Players are created at their first rating (2007-02-22 for 11,059 players, 2007-08-30 for one). Height and weight are snapshot at N = 2016-07-07, the last rating date.

## Expected output

`results/` holds every source table, as the source stores it. Each column's type follows the values it holds: text, int64 or float64. A mixed column holds text and numbers together, so it is stored as SQLite's own text rendering and declared in `dataset.toml`. `Player.height` is declared INTEGER but holds REAL, so it is float64; the NUMERIC odds hold integers and reals, so they are float64 too. No column is mixed.

| Table | Rows | Columns | Mixed columns |
|---|---:|---:|---|
| `Country` | 11 | 2 | none |
| `League` | 11 | 3 | none |
| `Team` | 299 | 5 | none |
| `Player` | 11,060 | 7 | none |
| `Match` | 25,979 | 115 | none |
| `Player_Attributes` | 183,978 | 42 | none |
| `Team_Attributes` | 1,458 | 25 | none |

`expected/queries/` holds the answers of the saved questions (`local218`, `local219`, `local220`, `local221`, `local283`), computed on the source. `dataset verify` runs `specs/build.sql` over the log, loads the tables into SQLite with the source's DDL, and compares them and the answers exactly: rows as multisets, numbers by value, text byte for byte. The source view `match_view` is created on the rebuilt tables before the questions run.

local218, local220, local221 and local283 have no gold SQL and are written from the question; local219 is the gold SQL. Each reproduces one accepted gold CSV exactly. Two are tie-sensitive, so each has a deterministic tie-break: local219 picks the lowest `Team.id` among the teams tied for fewest wins (gold variant c), and local283 breaks the two ties for first on points by goal difference (the gold's 88 rows).

## Regenerate

```bash
uv run refdata fetch                 # once: the Spider 2.0 SQLite files → data/spider2/
uv run dataset build eusoccer             # → $NEORISK_DATA_ROOT/eusoccer/v1/ (default data/datasets/)
uv run dataset verify eusoccer            # exit 0 = every table and answer matches
```

## Extend

- **More rows:** not possible for a fixed source. Stage 2 will generate logs from `specs/pack.py`.
- **A new event type:** declare it in `specs/pack.py`, add its `-- event: <name> owner=<col>` block to `specs/ingest.sql`, and use it in `specs/build.sql`. The XML incidents (goals, cards, shots) are a candidate, but they have only a minute and no kick-off time.
- **A new attribute:** add the column to the pack table and to its ingest block. It then appears in the payload and in `schema/events.json`.
- **A new results table:** add it to `specs/source.toml` and a `-- table: <name>` block to `specs/build.sql`.
- **A new saved question:** add `specs/queries/<id>.sql` (SQLite dialect, source table names; `match_view` is available).
- **A new engine port:** write `engines/<engine>/` from `specs/build.sql`. It must read only the log and match `results/` exactly.

Any change to `specs/`, `dataset.toml` or the source changes the build. Once a version is recorded in `v1.lock.json`, changed output needs a new version (`v2`).
