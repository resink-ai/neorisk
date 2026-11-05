# baseball

## What this is

Sean Lahman's Baseball Database, 2015 edition: every major-league season from 1871 to 2015 as season, stint and postseason-round aggregates (batting, pitching, fielding, appearances, salaries, managers, teams, home parks, all-star selections, awards and votes), plus Hall of Fame ballots to 2016 and the players' colleges.

Version `v1`, kind `spider2`. The input is one ordered event log of 572,700 events; the output is the 26 source tables, rebuilt exactly, and the answers to 2 saved Spider 2.0 questions.

## Raw data

`Baseball.sqlite` (all 26 tables, 553,693 rows), Kaggle's "The History of Baseball" export of Lahman's 2015 release, with the tables and columns renamed to snake_case. Real historical records; Lahman publishes them under CC BY-SA 3.0.

No cell is NULL: every missing value is `''`, so 90 numeric columns hold `''` next to their numbers. 86 of them hold integers; 4 hold reals (`pitching.baopp` and `era`, `pitching_postseason.era`, `player_award_vote.votes_first`), and `pitching_postseason.era` also holds one `'inf'`. `pitching.baopp` carries 17-digit float noise in 2,518 cells (0.24600000000000002), all from 2000 on. Dates (`debut`, `final_game`, `span_first`, `span_last`) are `YYYY-MM-DD` text; the all-star `game_id` embeds its game date. Every other fact row has only a year. 12 player ids in fact rows (`Cabremi01` among them) and 4 college ids in `player_college` are not in `player` and `college`.

The reverse-engineering research, with the queries behind every number, is in [`docs/research/spider2/baseball.md`](../../docs/research/spider2/baseball.md).

## How the log was made

Players, franchises, parks and colleges are entities, and so is `season`, one per year, which owns the postseason series because their old team codes do not all resolve. The 12 orphan player ids and 4 orphan college ids are stub entities (`stub = '1'`), so every id stays a typed ref; `specs/build.sql` leaves the stubs out of `player` and `college`. Every other source row is one event: player tables are owned by the player, `team` by its `franchise_id`, `team_half` and `home_game` by the franchise of their team (year, team_id), and `postseason` by its season. `player_college` rows are `college_attended` events at the player's creation. `final_game` and the six death columns are lifetime values, so they ride on one `player_snapshot_taken` event per player at N rather than on the creation.

A numeric column holding `''` next to integers travels as a null integer and is rebuilt as `coalesce(CAST(x AS VARCHAR), '')`, which SQLite's NUMERIC affinity turns back into the same integer or `''`. The 4 real-bearing mixed columns travel as SQLite's own `CAST(x AS TEXT)` (`'0.246'`, `''`, `'inf'`), the text the results hold for a mixed column. `salary` is whole dollars, carried as `amount` cents. `team.era`, `team.fp` and `player_award_vote.points_won` are plain reals, carried as `f64`; JSON's shortest form round-trips `fp`'s noisy values exactly.

`uv run dataset build baseball` runs `specs/ingest.sql` on the read-only source to make a simkit dataset (an internal stage), then writes it as one log. Entity rows become `<entity>_created` events at their creation time; business events keep their columns. The log is in `seq` order: event time, then entities before events at the same instant; at a season's S(y) the blocks order team, manager, appearances, batting, pitching, fielding, outfield and salary rows. Each row's `payload` is a JSON object whose fields are listed in `schema/events.json`.

## Event catalogue

| Event | Kind | Rows | Payload fields |
|---|---|---:|---|
| `player_created` | entity | 18,858 | `player_key`, `ext_id`, `stub`, `birth_year`, `birth_month`, `birth_day`, `birth_country`, `birth_state`, `birth_city`, `name_first`, `name_last`, `name_given`, `weight`, `height`, `bats`, `throws`, `debut`, `retro_id`, `bbref_id` |
| `team_franchise_created` | entity | 120 | `franchise_key`, `ext_id`, `franchise_name`, `active`, `na_assoc` |
| `park_created` | entity | 250 | `park_key`, `ext_id`, `park_name`, `park_alias`, `city`, `state`, `country` |
| `college_created` | entity | 1,211 | `college_key`, `ext_id`, `stub`, `name_full`, `city`, `state`, `country` |
| `season_created` | entity | 145 | `season_key`, `ext_id` |
| `team_season_reported` | business | 2,805 | `year`, `league_id`, `team_id`, `franchise_id`, `div_id`, `rank`, `g`, `ghome`, `w`, `l`, `div_win`, `wc_win`, `lg_win`, `ws_win`, `r`, `ab`, `h`, `double`, `triple`, `hr`, `bb`, `so`, `sb`, `cs`, `hbp`, `sf`, `ra`, `er`, `era`, `cg`, `sho`, `sv`, `ipouts`, `ha`, `hra`, `bba`, `soa`, `e`, `dp`, `fp`, `name`, `park`, `attendance`, `bpf`, `ppf`, `team_id_br`, `team_id_lahman45`, `team_id_retro` |
| `team_half_reported` | business | 52 | `franchise`, `year`, `league_id`, `team_id`, `half`, `div_id`, `div_win`, `rank`, `g`, `w`, `l` |
| `manager_stint_reported` | business | 3,405 | `player_id`, `year`, `team_id`, `league_id`, `inseason`, `g`, `w`, `l`, `rank`, `plyr_mgr` |
| `manager_half_reported` | business | 93 | `player_id`, `year`, `team_id`, `league_id`, `inseason`, `half`, `g`, `w`, `l`, `rank` |
| `appearances_reported` | business | 100,951 | `year`, `team_id`, `league_id`, `player_id`, `g_all`, `gs`, `g_batting`, `g_defense`, `g_p`, `g_c`, `g_1b`, `g_2b`, `g_3b`, `g_ss`, `g_lf`, `g_cf`, `g_rf`, `g_of`, `g_dh`, `g_ph`, `g_pr` |
| `batting_line_reported` | business | 101,332 | `player_id`, `year`, `stint`, `team_id`, `league_id`, `g`, `ab`, `r`, `h`, `double`, `triple`, `hr`, `rbi`, `sb`, `cs`, `bb`, `so`, `ibb`, `hbp`, `sh`, `sf`, `g_idp` |
| `pitching_line_reported` | business | 44,139 | `player_id`, `year`, `stint`, `team_id`, `league_id`, `w`, `l`, `g`, `gs`, `cg`, `sho`, `sv`, `ipouts`, `h`, `er`, `hr`, `bb`, `so`, `baopp`, `era`, `ibb`, `wp`, `hbp`, `bk`, `bfp`, `gf`, `r`, `sh`, `sf`, `g_idp` |
| `fielding_line_reported` | business | 170,526 | `player_id`, `year`, `stint`, `team_id`, `league_id`, `pos`, `g`, `gs`, `inn_outs`, `po`, `a`, `e`, `dp`, `pb`, `wp`, `sb`, `cs`, `zr` |
| `outfield_split_reported` | business | 12,028 | `player_id`, `year`, `stint`, `glf`, `gcf`, `grf` |
| `salary_reported` | business | 25,575 | `year`, `team_id`, `league_id`, `player_id`, `salary` |
| `home_games_reported` | business | 2,944 | `franchise`, `year`, `league_id`, `team_id`, `park_id`, `span_first`, `span_last`, `games`, `openings`, `attendance` |
| `all_star_selected` | business | 5,069 | `player_id`, `year`, `game_num`, `game_id`, `team_id`, `league_id`, `gp`, `starting_pos` |
| `postseason_series_decided` | business | 307 | `season`, `year`, `round`, `team_id_winner`, `league_id_winner`, `team_id_loser`, `league_id_loser`, `wins`, `losses`, `ties` |
| `batting_postseason_reported` | business | 11,690 | `year`, `round`, `player_id`, `team_id`, `league_id`, `g`, `ab`, `r`, `h`, `double`, `triple`, `hr`, `rbi`, `sb`, `cs`, `bb`, `so`, `ibb`, `hbp`, `sh`, `sf`, `g_idp` |
| `pitching_postseason_reported` | business | 5,109 | `player_id`, `year`, `round`, `team_id`, `league_id`, `w`, `l`, `g`, `gs`, `cg`, `sho`, `sv`, `ipouts`, `h`, `er`, `hr`, `bb`, `so`, `baopp`, `era`, `ibb`, `wp`, `hbp`, `bk`, `bfp`, `gf`, `r`, `sh`, `sf`, `g_idp` |
| `fielding_postseason_reported` | business | 12,311 | `player_id`, `year`, `team_id`, `league_id`, `round`, `pos`, `g`, `gs`, `inn_outs`, `po`, `a`, `e`, `dp`, `tp`, `pb`, `sb`, `cs` |
| `player_award_won` | business | 6,078 | `player_id`, `award_id`, `year`, `league_id`, `tie`, `notes` |
| `player_award_vote_received` | business | 6,795 | `award_id`, `year`, `league_id`, `player_id`, `points_won`, `points_max`, `votes_first` |
| `manager_award_won` | business | 177 | `player_id`, `award_id`, `year`, `league_id`, `tie`, `notes` |
| `manager_award_vote_received` | business | 414 | `award_id`, `year`, `league_id`, `player_id`, `points_won`, `points_max`, `votes_first` |
| `hof_ballot_recorded` | business | 4,120 | `player_id`, `yearid`, `votedby`, `ballots`, `needed`, `votes`, `inducted`, `category`, `needed_note` |
| `college_attended` | business | 17,350 | `player_id`, `college_id`, `year` |
| `player_snapshot_taken` | business | 18,846 | `player_id`, `final_game`, `death_year`, `death_month`, `death_day`, `death_country`, `death_state`, `death_city` |

## Times set by rule

Only debuts, home-game spans and all-star game dates are natural. Every other fact row has only a year, so 525,306 of the 533,270 source-row events sit on a rule date, set after every natural in-season date (the latest is 11-01):

- S(y) = `<y>-11-01 00:00:00`: regular-season lines, team seasons and halves, manager stints and salaries;
- P(y) = `<y>-11-02`: postseason series and lines;
- A(y) = `<y>-11-30`: awards and award votes;
- H(y) = `<yearid>-01-15`: Hall of Fame ballots, announced in January;
- the 49 all-star rows of 1945, when no game was played (`game_id = ''`), at 1945-07-10;
- a home-game row at its `span_last` (natural);
- a player is created at min(`debut`, his first owned event): the debut for 18,604; the first event for 191 players without a debut, for 49 with a rule-dated row before their debut (45 pre-debut salaries among the 54 rows) and for the 12 stubs; and T0 = 1871-01-01 for the 2 players with neither (`crossjo01`, `sulliwi01`). For 49 players the creation carries a `debut` later than its own time;
- a franchise at Jan 1 of its first team-season; a park at its first `span_first` (T0 for the unused `FOR02`); colleges, stubs included, at T0; a season at Jan 1 of its year;
- a `college_attended` event at its player's creation, ordered after it by (year, college_id);
- `player_snapshot_taken` at N = 2016-02-18, the last death date. Every other event is at most H(2016) = 2016-01-15.

Queries must filter on `year`, not on the event time.

## Expected output

`results/` holds every source table, as the source stores it. Each column's type follows the values it holds: text, int64 or float64. A mixed column holds text and numbers together, so it is stored as SQLite's own text rendering and declared in `dataset.toml`.

| Table | Rows | Columns | Mixed columns |
|---|---:|---:|---|
| `all_star` | 5,069 | 8 | `gp`, `starting_pos` |
| `appearances` | 100,951 | 21 | `g_all`, `g_defense`, `g_dh`, `g_ph`, `g_pr`, `gs` |
| `manager_award` | 177 | 6 | none |
| `player_award` | 6,078 | 6 | none |
| `manager_award_vote` | 414 | 7 | none |
| `player_award_vote` | 6,795 | 7 | `votes_first` |
| `batting` | 101,332 | 22 | `ab`, `bb`, `cs`, `double`, `g_idp`, `h`, `hbp`, `hr`, `ibb`, `r`, `rbi`, `sb`, `sf`, `sh`, `so`, `triple` |
| `batting_postseason` | 11,690 | 22 | `cs`, `g_idp`, `hbp`, `ibb`, `sf`, `sh` |
| `player_college` | 17,350 | 3 | none |
| `fielding` | 170,526 | 18 | `a`, `cs`, `dp`, `e`, `gs`, `inn_outs`, `pb`, `po`, `sb`, `wp`, `zr` |
| `fielding_outfield` | 12,028 | 6 | `gcf`, `glf`, `grf` |
| `fielding_postseason` | 12,311 | 17 | `cs`, `gs`, `inn_outs`, `pb`, `sb` |
| `hall_of_fame` | 4,120 | 9 | `ballots`, `needed`, `votes` |
| `home_game` | 2,944 | 9 | none |
| `manager` | 3,405 | 10 | `rank` |
| `manager_half` | 93 | 10 | none |
| `player` | 18,846 | 24 | `birth_day`, `birth_month`, `birth_year`, `death_day`, `death_month`, `death_year`, `height`, `weight` |
| `park` | 250 | 6 | none |
| `pitching` | 44,139 | 30 | `baopp`, `bfp`, `era`, `g_idp`, `gf`, `hbp`, `ibb`, `ipouts`, `sf`, `sh`, `wp` |
| `pitching_postseason` | 5,109 | 30 | `bfp`, `bk`, `era`, `g_idp`, `hbp`, `ibb`, `sf`, `sh`, `wp` |
| `salary` | 25,575 | 5 | none |
| `college` | 1,207 | 5 | none |
| `postseason` | 307 | 9 | none |
| `team` | 2,805 | 48 | `attendance`, `cs`, `dp`, `ghome`, `hbp`, `sb`, `sf`, `so` |
| `team_franchise` | 120 | 4 | none |
| `team_half` | 52 | 10 | none |

`expected/queries/` holds the answers of the saved questions (`local007`, `local008`), computed on the source. `dataset verify` runs `specs/build.sql` over the log, loads the tables into SQLite with the source's DDL, and compares them and the answers exactly: rows as multisets, numbers by value, text byte for byte.

local008 is Spider2's gold SQL and reproduces both gold CSVs; its `SUM(r)` over a column holding `''` returns a real (2295.0), which compares equal to the gold's integer. local007 has no gold SQL and neither gold CSV (4.85 and 5.09966563) can be reproduced from this file by any reading of the question; it is written from the question, field by field over the 18,653 players with a debut, and its expected answer (4.92375275) is computed on the source.

## Regenerate

```bash
uv run refdata fetch                 # once: the Spider 2.0 SQLite files → data/spider2/
uv run dataset build baseball             # → $NEORISK_DATA_ROOT/baseball/v1/ (default data/datasets/)
uv run dataset verify baseball            # exit 0 = every table and answer matches
```

## Extend

- **More rows:** not possible for a fixed source. Stage 2 will generate logs from `specs/pack.py`.
- **A new event type:** declare it in `specs/pack.py`, add its `-- event: <name> owner=<col>` block to `specs/ingest.sql`, and use it in `specs/build.sql`.
- **A new attribute:** add the column to the pack table and to its ingest block. It then appears in the payload and in `schema/events.json`.
- **A new results table:** add it to `specs/source.toml` and a `-- table: <name>` block to `specs/build.sql`.
- **A new saved question:** add `specs/queries/<id>.sql` (SQLite dialect, source table names).
- **A new engine port:** write `engines/<engine>/` from `specs/build.sql`. It must read only the log and match `results/` exactly.

Any change to `specs/`, `dataset.toml` or the source changes the build. Once a version is recorded in `v1.lock.json`, changed output needs a new version (`v2`).
