# ipl

## What this is

The Indian Premier League, seasons 1 to 9 (2008-04-18 to 2016-05-29), ball by ball: 567 matches and 134,704 deliveries. Each match is scheduled, the toss is decided and the team sheets are named; then each innings starts and every delivery is bowled; then the result is recorded.

Version `v1`, kind `spider2`. The input is one ordered event log of 150,518 events; the output is the 8 source tables, rebuilt exactly, and the answers to 11 saved Spider 2.0 questions.

## Raw data

`IPL.sqlite` (all 8 tables). Real sports data: real players, scores and dates. It is likely the Kaggle "IPL SQLite Database" (`harsha547/ipldatabase`), but that link is unverified, and the licence is unstated.

The source has dates only, read as UTC. Every time of day is a rule. Integers and text only: no REAL column, no NULL, no `''`.

The reverse-engineering research, with the queries behind every number, is in [`docs/research/spider2/ipl.md`](../../docs/research/spider2/ipl.md).

## How the log was made

Every event is owned by its match. The fixture, toss and result come from the `match` row, each team-sheet line is an event, each innings start is an event, and each delivery is one event. A delivery is the union of the four ball tables' keys: 134,704 deliveries, one more than `ball_by_ball`, because the first delivery of the file (335987, innings 1, 1.1, a leg-bye) has an `extra_runs` row but no ball row. A delivery's runs, extras and wicket parts are NULL when their table has no row for it, so `batsman_scored`, `extra_runs` and `wicket_taken` rebuild as the deliveries whose part is present, and `ball_by_ball` as those with `has_ball_row = 1`. Players and teams are entities.

Three ids are used but have no row:
- **Team 1** (Kolkata, by its venues) and **player 35** are placeholder entities with NULL attributes and `listed = 0`, so every ref resolves. The `team` and `player` tables keep only `listed = 1`.
- **Match 419136** has 250 deliveries and 22 team-sheet lines but no `match` row. `match_id` is an owner value, not a ref, so it simply has no scheduling, toss or result event.

The batting side of an innings is the team its strikers are named for. In 3 matches (392202, 392207, 419119) the source labels 169 innings-2 deliveries the other way round; those deliveries carry `teams_swapped = 1`, and the rebuild swaps both team columns back. Results (`win_type`, `win_margin`, `match_winner`) and `striker_batting_position` are carried, not derived: 22 results disagree with the scorecard.

`uv run dataset build ipl` runs `specs/ingest.sql` on the read-only source to make a simkit dataset (an internal stage), then writes it as one log. Entity rows become `<entity>_created` events at their creation time; business events keep their columns. The log is in `seq` order: event time, then entities before events at the same instant. Each row's `payload` is a JSON object whose fields are listed in `schema/events.json`.

## Event catalogue

| Event | Kind | Rows | Payload fields |
|---|---|---:|---|
| `teams_created` | entity | 13 | `team_key`, `ext_id`, `name`, `listed` |
| `players_created` | entity | 469 | `player_key`, `ext_id`, `player_name`, `dob`, `batting_hand`, `bowling_skill`, `country_name`, `listed` |
| `match_scheduled` | business | 567 | `match_id`, `team_1`, `team_2`, `season_id`, `venue` |
| `toss_decided` | business | 567 | `match_id`, `toss_winner`, `toss_decision` |
| `player_named` | business | 12,495 | `match_id`, `player_id`, `team_id`, `role` |
| `innings_started` | business | 1,136 | `match_id`, `innings_no`, `team_batting`, `team_bowling` |
| `ball_bowled` | business | 134,704 | `match_id`, `innings_no`, `over_id`, `ball_id`, `has_ball_row`, `teams_swapped`, `striker`, `non_striker`, `bowler`, `striker_batting_position`, `runs_scored`, `extra_type`, `extra_runs`, `player_out`, `kind_out` |
| `match_completed` | business | 567 | `match_id`, `match_winner`, `win_type`, `win_margin`, `outcome_type`, `man_of_the_match` |

## Times set by rule

- A match starts at 20:00 on its `match_date`. On the 164 days with two matches, the lower `match_id` starts at 16:00.
- Match 419136 has no date: it is placed on 2010-03-29, the free day between its id neighbours 419135 (2010-03-28) and 419137 (2010-03-30).
- The fixture, toss and team sheet are at start − 30 min, in that order.
- Delivery k (1..n per innings, in over and ball order) is at start + (innings − 1) × 110 min + (k − 1) × 40 s. An innings starts at its first delivery. No two deliveries share a time, and no match crosses midnight.
- The result is at the last delivery + 5 min. The last one, N, is 2016-05-29 23:17:00.
- A team is created at 00:00 of its first match, a player at 00:00 of his first team sheet. Player 448 is on no sheet and takes the first match day, 2008-04-18.

Only the dates reach the tables (`match_date` is the fixture's date), so the clock cannot change any table. Only the order is real; stage 2 must not fit gaps between deliveries from it.

## Expected output

`results/` holds every source table, as the source stores it. Each column's type follows the values it holds: text, int64 or float64. A mixed column holds text and numbers together, so it is stored as SQLite's own text rendering and declared in `dataset.toml`.

| Table | Rows | Columns | Mixed columns |
|---|---:|---:|---|
| `player` | 468 | 6 | none |
| `team` | 12 | 2 | none |
| `match` | 567 | 13 | none |
| `player_match` | 12,495 | 4 | none |
| `ball_by_ball` | 134,703 | 10 | none |
| `batsman_scored` | 131,259 | 5 | none |
| `wicket_taken` | 6,618 | 6 | none |
| `extra_runs` | 7,349 | 6 | none |

`expected/queries/` holds the answers of the saved questions (`local020`, `local021`, `local022`, `local023`, `local024`, `local025`, `local026`, `local228`, `local229`, `local258`, `local259`), computed on the source. `dataset verify` runs `specs/build.sql` over the log, loads the tables into SQLite with the source's DDL, and compares them and the answers exactly: rows as multisets, numbers by value, text byte for byte, and float answers within a relative 1e-9.

Only local022 and local023 have gold SQL, which is used as it is. The other nine are written from the question, and each file's header names the answer CSV it reproduces.

## Regenerate

```bash
uv run refdata fetch                 # once: the Spider 2.0 SQLite files → data/spider2/
uv run dataset build ipl             # → $NEORISK_DATA_ROOT/ipl/v1/ (default data/datasets/)
uv run dataset verify ipl            # exit 0 = every table and answer matches
```

## Extend

- **More rows:** not possible for a fixed source. Stage 2 will generate logs from `specs/pack.py`.
- **A new event type:** declare it in `specs/pack.py`, add its `-- event: <name> owner=<col>` block to `specs/ingest.sql`, and use it in `specs/build.sql`. A `batter_came_in` event could carry `striker_batting_position` instead of every delivery.
- **A new attribute:** add the column to the pack table and to its ingest block. It then appears in the payload and in `schema/events.json`.
- **A new results table:** add it to `specs/source.toml` and a `-- table: <name>` block to `specs/build.sql`.
- **A new saved question:** add `specs/queries/<id>.sql` (SQLite dialect, source table names).
- **A new engine port:** write `engines/<engine>/` from `specs/build.sql`. It must read only the log and match `results/` exactly.

Any change to `specs/`, `dataset.toml` or the source changes the build. Once a version is recorded in `v1.lock.json`, changed output needs a new version (`v2`).
