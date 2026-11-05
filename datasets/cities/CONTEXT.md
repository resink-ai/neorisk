# cities

## What this is

World cities: 44,622 cities, each inserted on a date between 2021-01-01 and 2023-08-01, with country, currency and language lookups.

Version `v1`, kind `spider2`. The input is one ordered event log of 90,588 events; the output is the 4 source tables, rebuilt exactly, and the answers to 4 saved Spider 2.0 questions.

## Raw data

`city_legislation.sqlite` (the 4 `cities*` tables; the file's other tables belong to `legislators`, `jobpostings` and `aliens`). Course data: Jaime M. Shaker's SQL Coding Challenge (Aug 2023), its cleaned tables with a `cities_` prefix. The city facts are real, the text was dirtied then cleaned, and the insert dates are generated: uniform over all 943 days of the window. The repo declares no licence.

Dates only, read as UTC midnight. Lookups are created at a rule time; `created_on` is a snapshot.

The reverse-engineering research, with the queries behind every number, is in [`docs/research/spider2/cities.md`](../../docs/research/spider2/cities.md).

## How the log was made

Each city is an entity created at its `insert_date`, as a `city_inserted` event: that is the moment every saved question counts. A city's capital flag and population are values as of the extract, so they ride on one `cities_snapshot` event per city at N. Countries (keyed by `country_code_2`, with `country_id` carried for its 15 gaps), currencies and languages are entities too, and cities, currencies and languages reference their country. `cities_countries.created_on` is the day the tables were built, after every insert, so it rides on one `countries_snapshot` event per country instead of being the country's creation time. Every column passes through as stored: `latitude` holds longitudes and `longitude` latitudes (an upstream swap, kept), city 9272's name is NULL (pandas read the town `nan` as NaN), and `population` is whole numbers in a REAL column with 305 NULLs, so it travels as an integer. `city_id` is carried, since local070 picks the lowest id per date.

`uv run dataset build cities` runs `specs/ingest.sql` on the read-only source to make a simkit dataset (an internal stage), then writes it as one log. Entity rows become `<entity>_created` events (or the domain name the recipe gives) at their creation time; business events keep their columns. The log is in `seq` order: event time, then entities before events at the same instant. Each row's `payload` is a JSON object whose fields are listed in `schema/events.json`.

## Event catalogue

| Event | Kind | Rows | Payload fields |
|---|---|---:|---|
| `countries_created` | entity | 241 | `country_key`, `ext_id`, `country_id`, `country_name`, `country_code_3`, `region`, `sub_region`, `intermediate_region` |
| `currencies_created` | entity | 254 | `currency_key`, `ext_id`, `country`, `currency_name`, `currency_code` |
| `languages_created` | entity | 608 | `language_key`, `ext_id`, `language`, `country` |
| `city_inserted` | entity | 44,622 | `city_key`, `ext_id`, `city_name`, `latitude`, `longitude`, `country` |
| `countries_snapshot` | business | 241 | `country` |
| `cities_snapshot` | business | 44,622 | `city`, `capital`, `population` |

## Times set by rule

Countries, currencies and languages have no time: they are created at the catalog start, 2021-01-01, so every city's country exists before it. The snapshot time N is `created_on`, 2024-07-18 00:00:00, the same for all 241 countries and after the last city insert (2023-08-01); the cities' snapshots use the same N.

## Snapshot columns

| Entity | Snapshot event | At (UTC) | Rows | Columns |
|---|---|---|---:|---|
| `countries` | `countries_snapshot` | 2024-07-18 00:00:00 | 241 |  |
| `cities` | `cities_snapshot` | 2024-07-18 00:00:00 | 44,622 | `capital`, `population` |

`countries_snapshot` has no payload column: its value, `created_on`, is its event time.

| Column | Verdict | Reason |
|---|---|---|
| `countries.ext_id` | creation | The source key (`country_code_2`). |
| `countries.country_id` | creation | A source id, fixed with the row (carried for its 15 gaps). |
| `countries.country_name` | creation | A given name. |
| `countries.country_code_3` | creation | A code given with the country. |
| `countries.region` | creation | The UN geographic region the country was catalogued in; static geography. |
| `countries.sub_region` | creation | As `region`. |
| `countries.intermediate_region` | creation | As `region`. |
| `countries.created_on` | snapshot | The load stamp, later than every insert; it is the snapshot's event time (research). |
| `currencies.ext_id` | creation | The source key (`currency_id`). |
| `currencies.country` | creation | An immutable ref: the row is the country–currency pair itself. |
| `currencies.currency_name` | creation | The currency's given name; a different currency would be a different row. |
| `currencies.currency_code` | creation | The code given with the currency, as `currency_name`. |
| `languages.ext_id` | creation | The source key (`language_id`). |
| `languages.language` | creation | A given name; the row is the country–language pair itself. |
| `languages.country` | creation | An immutable ref, as for currencies. |
| `cities.ext_id` | creation | The source key (`city_id`). |
| `cities.city_name` | creation | A given name. |
| `cities.latitude` | creation | A fixed location, carried as stored (it holds the longitude). |
| `cities.longitude` | creation | As `latitude` (it holds the latitude). |
| `cities.country` | creation | An immutable ref. |
| `cities.insert_date` | creation | It decides the creation time (`created_at`). |
| `cities.capital` | snapshot | A current status: capitals move, and the source holds it only as of the extract. Research kept it on creation ("no updates"); the rubric puts a current status on the snapshot. local072 reads it through the rebuilt table, as the source does. |
| `cities.population` | snapshot | A count known as of the extract, not at the synthetic insert date. Research kept it on creation; the rubric puts it on the snapshot. No saved question reads it. |

Domain name: `city_inserted`, the insert that `insert_date` records and the name the research gives. Countries, currencies and languages are created at the catalog start by rule, which shows no real-world act, so they keep `<entity>_created`.

## Expected output

`results/` holds every source table, as the source stores it. Each column's type follows the values it holds: text, int64 or float64. A mixed column holds text and numbers together, so it is stored as SQLite's own text rendering and declared in `dataset.toml`.

| Table | Rows | Columns | Mixed columns |
|---|---:|---:|---|
| `cities` | 44,622 | 8 | none |
| `cities_countries` | 241 | 8 | none |
| `cities_currencies` | 254 | 4 | none |
| `cities_languages` | 608 | 3 | none |

`expected/queries/` holds the answers of the saved questions (`local068`, `local070`, `local071`, `local072`), computed on the source. `dataset verify` runs `specs/build.sql` over the log, loads the tables into SQLite with the source's DDL, and compares them and the answers exactly: rows as multisets, numbers by value, text byte for byte.

## Regenerate

```bash
uv run refdata fetch                 # once: the Spider 2.0 SQLite files → data/spider2/
uv run dataset build cities             # → $NEORISK_DATA_ROOT/cities/v1/ (default data/datasets/)
uv run dataset verify cities            # exit 0 = every table and answer matches
```

## Extend

- **More rows:** not possible for a fixed source. Stage 2 will generate logs from `specs/pack.py`.
- **A new event type:** declare it in `specs/pack.py`, add its `-- event: <name> owner=<col>` block to `specs/ingest.sql`, and use it in `specs/build.sql`.
- **A new attribute:** add the column to the pack table and to its ingest block. It then appears in the payload and in `schema/events.json`.
- **A new results table:** add it to `specs/source.toml` and a `-- table: <name>` block to `specs/build.sql`.
- **A new saved question:** add `specs/queries/<id>.sql` (SQLite dialect, source table names).
- **A new engine port:** write `engines/<engine>/` from `specs/build.sql`. It must read only the log and match `results/` exactly.

Any change to `specs/`, `dataset.toml` or the source changes the build. Once a version is recorded in `v1.lock.json`, changed output needs a new version (`v2`).
