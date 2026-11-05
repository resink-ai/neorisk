# f1

## What this is

Formula 1, every World Championship race from 1950-05-13 to 2024-07-07: the calendar, qualifying, laps, pit stops, race and sprint classifications, and the official driver and constructor standings after each race.

Version `v1`, kind `spider2`. The input is one ordered event log of 687,472 events; the output is the 29 source tables, rebuilt exactly, and the answers to 9 saved Spider 2.0 questions.

## Raw data

`f1.sqlite`, all 29 tables. The 14 base tables are the Ergast Developer API database, renamed to snake_case; it is real public sports data, and Ergast's licence (most often cited as CC BY-NC-SA) is unverified. Spider2, or an upstream author, added 15 tables: four hand tables (`short_grand_prix_names`, `short_constructor_names`, `liveries`, `tdr_overrides`) and eleven derived ones (`circuits_ext`, `constructors_ext`, `drivers_ext`, `races_ext`, `driver_standings_ext`, `lap_times_ext`, `lap_time_stats`, `team_driver_ranks`, `drives`, `retirements`, `lap_positions`). Three columns are declared `VIRTUAL`: `drivers.full_name`, `lap_times.seconds` and `pit_stops.seconds`.

Race dates are ISO dates; 394 races (2005 on) have a UTC start time, 731 have none. `pit_stops.time` is a local wall clock. The 2024 calendar is complete (24 rounds) but results end at round 12, so 12 races are scheduled only, and race 1132 has results and pit stops but no laps.

The reverse-engineering research, with the queries behind every number, is in [`docs/research/spider2/f1.md`](../../docs/research/spider2/f1.md).

## How the log was made

Circuits, constructors, drivers, seasons, statuses and the four hand tables are entities. Values known only as of the mid-2024 dump ride on one `<entity>_snapshot` event per row at N: every Wikipedia `url`, a circuit's current name, a driver's permanent number and code, and a livery's end year. Each race is a `race_scheduled` event owned by its circuit; `race_id` is a plain id in every later event, since the 12 unraced rounds exist only as scheduled races. Qualifying, sprints, laps, pit stops and race results are events owned by the driver; constructor race points and both standings are reported events, because the official points and positions carry dropped scores, best-car rules and penalties that `results` does not give.

`specs/build.sql` formats `lap_times.time` and `pit_stops.duration` from the milliseconds; `results.time`, `pit_stops.time` and `fastest_lap_speed` travel verbatim. The three generated columns are never inserted: SQLite computes them from the source DDL. The eleven derived tables are rebuilt by SQL from the log (the rules in `docs/research/spider2/scripts/f1/q3_derived.sql`). `drives` is cut into runs of one constructor per driver-season by rule; for the 17 driver-seasons (39 rows, 16 of them with a shared 1950s car) where the source does something no rule gives, its rows travel as `drive_override_recorded` events and replace the rule's. `lap_time_stats` is rebuilt from exact integer sums; it agrees within the comparator's 1e-9 relative tolerance for float64, not bit for bit.

`uv run dataset build f1` runs `specs/ingest.sql` on the read-only source to make a simkit dataset (an internal stage), then writes it as one log. Entity rows become `<entity>_created` events at their creation time; business events keep their columns. The log is in `seq` order: event time, then entities before events at the same instant; at one instant, events sort by race id, then block order, so a race's results come before its points and standings. Each row's `payload` is a JSON object whose fields are listed in `schema/events.json`.

## Event catalogue

| Event | Kind | Rows | Payload fields |
|---|---|---:|---|
| `circuits_created` | entity | 77 | `circuit_id`, `ext_id`, `circuit_ref`, `location`, `country`, `lat`, `lng`, `alt` |
| `constructors_created` | entity | 212 | `constructor_id`, `ext_id`, `constructor_ref`, `name`, `nationality` |
| `drivers_created` | entity | 859 | `driver_id`, `ext_id`, `driver_ref`, `forename`, `surname`, `dob`, `nationality` |
| `seasons_created` | entity | 75 | `season_id`, `ext_id` |
| `status_created` | entity | 139 | `status_id`, `ext_id`, `status` |
| `short_grand_prix_names_created` | entity | 40 | `short_grand_prix_name_id`, `ext_id`, `short_name` |
| `short_constructor_names_created` | entity | 44 | `short_constructor_name_id`, `ext_id`, `short_name` |
| `liveries_created` | entity | 64 | `livery_id`, `ext_id`, `constructor_ref`, `start_year`, `primary_hex_code` |
| `tdr_overrides_created` | entity | 48 | `tdr_override_id`, `ext_id`, `year`, `constructor_ref`, `driver_ref`, `team_driver_rank` |
| `circuits_snapshot` | business | 77 | `circuit_id`, `name`, `url` |
| `constructors_snapshot` | business | 212 | `constructor_id`, `url` |
| `drivers_snapshot` | business | 859 | `driver_id`, `number`, `code`, `url` |
| `seasons_snapshot` | business | 75 | `season_id`, `url` |
| `liveries_snapshot` | business | 64 | `livery_id`, `end_year` |
| `race_scheduled` | business | 1,125 | `circuit_id`, `race_id`, `year`, `round`, `name`, `date`, `time`, `url`, `fp1_date`, `fp1_time`, `fp2_date`, `fp2_time`, `fp3_date`, `fp3_time`, `quali_date`, `quali_time`, `sprint_date`, `sprint_time` |
| `qualifying_classified` | business | 10,254 | `driver_id`, `qualify_id`, `race_id`, `constructor_id`, `number`, `position`, `q1`, `q2`, `q3` |
| `sprint_classified` | business | 300 | `driver_id`, `result_id`, `race_id`, `constructor_id`, `number`, `grid`, `position`, `position_text`, `position_order`, `points`, `laps`, `time`, `milliseconds`, `fastest_lap`, `fastest_lap_time`, `fastest_lap_speed`, `status_id` |
| `lap_completed` | business | 575,029 | `driver_id`, `race_id`, `lap`, `position`, `milliseconds` |
| `pit_stop_made` | business | 10,990 | `driver_id`, `race_id`, `stop`, `lap`, `time`, `milliseconds` |
| `race_result_classified` | business | 26,519 | `driver_id`, `result_id`, `race_id`, `constructor_id`, `number`, `grid`, `position`, `position_text`, `position_order`, `points`, `laps`, `time`, `milliseconds`, `fastest_lap`, `rank`, `fastest_lap_time`, `fastest_lap_speed`, `status_id` |
| `constructor_race_points_reported` | business | 12,505 | `constructor_id`, `constructor_results_id`, `race_id`, `points`, `status` |
| `driver_standings_published` | business | 34,595 | `driver_id`, `driver_standings_id`, `race_id`, `points`, `position`, `position_text`, `wins` |
| `constructor_standings_published` | business | 13,271 | `constructor_id`, `constructor_standings_id`, `race_id`, `points`, `position`, `position_text`, `wins` |
| `drive_override_recorded` | business | 39 | `driver_id`, `year`, `drive_id`, `constructor_id`, `first_round`, `last_round`, `is_first_drive_of_season`, `is_final_drive_of_season` |

## Times set by rule

N = 2024-07-08 00:00:00, the classification of the last race with results.

- **Races** are scheduled at Jan 1 of their season: no calendar publication date exists.
- **Laps** end at the race start + the driver's running milliseconds. The start is the race's date and UTC time, or 12:00 for the races with no time (all before 2005).
- **Pit stops** take their in-lap's time. Race 1132 has no laps, so its 45 stops are at the start + (the stop's local clock − the race's first stop clock).
- **Qualifying** is at the session's date and time (2021 on; 12:00 when the time is missing), else the day before the race at 12:00.
- **Sprints** are at the sprint date and time, or 12:00 for the 60 rows with no time.
- **Race results, constructor points and standings** are at race day + 1, 00:00; no lap ends after 22:04 on race day.
- **Entities:** circuits and constructors are created at Jan 1 of their first race year (the unused constructor at 1950-01-01), drivers at Jan 1 of their first year with a result or qualifying row, seasons at Jan 1 of the year, liveries at Jan 1 of `start_year`, statuses and the two short-name lookups at 1950-01-01, and `tdr_overrides` at N, as hand judgements made after the seasons.
- **Drive overrides** are recorded at N.
- **Snapshots** (`circuits_snapshot`, `constructors_snapshot`, `drivers_snapshot`, `seasons_snapshot`, `liveries_snapshot`) are all at N. No race, lap or standing is later.

## Snapshot columns

| Entity | Snapshot event | At (UTC) | Rows | Columns |
|---|---|---|---:|---|
| `circuits` | `circuits_snapshot` | 2024-07-08 00:00:00 | 77 | `name`, `url` |
| `constructors` | `constructors_snapshot` | 2024-07-08 00:00:00 | 212 | `url` |
| `drivers` | `drivers_snapshot` | 2024-07-08 00:00:00 | 859 | `number`, `code`, `url` |
| `seasons` | `seasons_snapshot` | 2024-07-08 00:00:00 | 75 | `url` |
| `liveries` | `liveries_snapshot` | 2024-07-08 00:00:00 | 64 | `end_year` |

| Column | Verdict | Reason |
|---|---|---|
| `circuits.circuit_id` (`ext_id`), `circuit_ref` | creation | The source key and its fixed text id. |
| `circuits.name` | snapshot | Ruling: the current name, not the one raced under (`villeneuve`, first raced 1978, took Gilles Villeneuve's name in 1982; `imola` became "Autodromo Enzo e Dino Ferrari" in 1988, after its first race in 1980). Research kept it in creation. |
| `circuits.location`, `country`, `lat`, `lng`, `alt` | creation | Where the track stands; it does not move. |
| `circuits.url` | snapshot | Ruling: a Wikipedia link as of the dump; articles are renamed (`galvez`'s link names "Oscar Alfredo Gálvez", its name "Juan y Oscar Gálvez"). Research kept it in creation. |
| `constructors.constructor_id` (`ext_id`), `constructor_ref` | creation | The source key and its fixed text id. |
| `constructors.name` | creation | A given name: a renamed team gets a new constructor id (`racing_point`, `aston_martin`; `toro_rosso`, `alphatauri`, `rb`). |
| `constructors.nationality` | creation | The nationality the constructor was entered with, one value per id. |
| `constructors.url` | snapshot | Ruling: a Wikipedia link as of the dump. Research kept it in creation. |
| `drivers.driver_id` (`ext_id`), `driver_ref` | creation | The source key and its fixed text id. |
| `drivers.number`, `code` | snapshot | Today's permanent number and code, NULL for 802 and 757 drivers (research §2). The previous build carried them on the creation. |
| `drivers.forename`, `surname` | creation | Given names. |
| `drivers.dob` | creation | A birth date. |
| `drivers.nationality` | creation | The nationality the driver raced under, one value for the career. |
| `drivers.url` | snapshot | Ruling: a Wikipedia link as of the dump. Research kept it in creation. |
| `seasons.year` (`ext_id`) | creation | The key. |
| `seasons.url` | snapshot | Ruling: a Wikipedia link as of the dump (2024's is `https`, the others `http`: edited at different times). Research kept it in creation. |
| `status.status_id` (`ext_id`), `status` | creation | A fixed lookup label. |
| `short_grand_prix_names.full_name` (`ext_id`), `short_name` | creation | An editorial lookup: the hand label is the row. |
| `short_constructor_names.constructor_ref` (`ext_id`), `short_name` | creation | An editorial lookup: the hand label is the row. |
| `liveries.constructor_ref`, `start_year` (`ext_id`) | creation | The key; `start_year` also decides the creation time. |
| `liveries.end_year` | snapshot | NULL for the 10 liveries still current at N (research §2). The previous build carried it on the creation. |
| `liveries.primary_hex_code` | creation | The livery's colour, fixed for the row. |
| `tdr_overrides.year`, `constructor_ref`, `driver_ref` (`ext_id`), `team_driver_rank` | creation | Hand judgements, created at N already. |

No snapshot column decides an event's time: circuits, constructors and drivers are created from their race years, liveries from `start_year`. The rebuild LEFT JOINs each snapshot on the entity key.

No domain name: every creation time is a rule (Jan 1 of a first year, the catalog start or N), not a real-world act the source shows, so every entity keeps `<entity>_created`. The real acts already have names (`race_scheduled`, `race_result_classified`, ...).

## Expected output

`results/` holds every source table, as the source stores it. Each column's type follows the values it holds: text, int64 or float64. A mixed column holds text and numbers together, so it is stored as SQLite's own text rendering and declared in `dataset.toml`.

| Table | Rows | Columns | Mixed columns |
|---|---:|---:|---|
| `circuits` | 77 | 9 | none |
| `constructor_results` | 12,505 | 5 | none |
| `constructor_standings` | 13,271 | 7 | none |
| `constructors` | 212 | 5 | none |
| `driver_standings` | 34,595 | 7 | none |
| `drivers` | 859 | 10 | none |
| `lap_times` | 575,029 | 7 | none |
| `pit_stops` | 10,990 | 8 | none |
| `qualifying` | 10,254 | 9 | none |
| `races` | 1,125 | 18 | none |
| `results` | 26,519 | 18 | none |
| `seasons` | 75 | 2 | none |
| `status` | 139 | 2 | none |
| `sprint_results` | 300 | 17 | none |
| `short_grand_prix_names` | 40 | 2 | none |
| `short_constructor_names` | 44 | 2 | none |
| `liveries` | 64 | 4 | none |
| `tdr_overrides` | 48 | 4 | none |
| `circuits_ext` | 77 | 11 | none |
| `constructors_ext` | 212 | 6 | none |
| `drivers_ext` | 859 | 10 | none |
| `races_ext` | 1,125 | 22 | none |
| `driver_standings_ext` | 35,012 | 7 | none |
| `lap_times_ext` | 575,029 | 8 | none |
| `lap_time_stats` | 10,789 | 6 | none |
| `team_driver_ranks` | 3,530 | 6 | none |
| `drives` | 3,784 | 8 | none |
| `retirements` | 11,568 | 6 | none |
| `lap_positions` | 613,112 | 5 | none |

`expected/queries/` holds the answers of the saved questions (`local309`, `local310`, `local311`, `local335`, `local336`, `local344`, `local354`, `local355`, `local356`), computed on the source. `dataset verify` runs `specs/build.sql` over the log, loads the tables into SQLite with the source's DDL, and compares them and the answers exactly: rows as multisets, numbers by value, text byte for byte, float64 within a relative 1e-9.

Only local309 has gold SQL, and it matches none of its exec_result CSVs; every query is written from the question. local309 reproduces `local309_a.csv` (the official champions from the final standings), local310, local311 and local335 reproduce their `_a` CSVs, local344 reproduces `local344_b.csv` and local354 `local354_c.csv`. local336, local355 and local356 match no variant; each file's header gives the nearest. The overtake questions (local336, local344, local356) follow the four labels of Spider2's `f1_overtake.md` over `lap_positions`.

## Regenerate

```bash
uv run refdata fetch                 # once: the Spider 2.0 SQLite files → data/spider2/
uv run dataset build f1             # → $NEORISK_DATA_ROOT/f1/v1/ (default data/datasets/)
uv run dataset verify f1            # exit 0 = every table and answer matches
```

## Extend

- **More rows:** not possible for a fixed source. Stage 2 will generate logs from `specs/pack.py`.
- **A new event type:** declare it in `specs/pack.py`, add its `-- event: <name> owner=<col>` block to `specs/ingest.sql`, and use it in `specs/build.sql`.
- **A new attribute:** add the column to the pack table and to its ingest block. It then appears in the payload and in `schema/events.json`.
- **A new results table:** add it to `specs/source.toml` and a `-- table: <name>` block to `specs/build.sql`.
- **A new saved question:** add `specs/queries/<id>.sql` (SQLite dialect, source table names).
- **A new engine port:** write `engines/<engine>/` from `specs/build.sql`. It must read only the log and match `results/` exactly.

Any change to `specs/`, `dataset.toml` or the source changes the build. Once a version is recorded in `v1.lock.json`, changed output needs a new version (`v2`).
