# legislators

## What this is

Members of the US Congress, 1789–2020: each legislator's terms in the House or the Senate, each one starting and, unless it is still open, ending.

Version `v1`, kind `spider2`. The input is one ordered event log of 100,107 events; the output is the 3 source tables, rebuilt exactly, and the answers to 4 saved Spider 2.0 questions.

## Raw data

`city_legislation.sqlite` (the tables `legislators`, `legislators_terms` and `legislation_date_dim`). The rows are the `unitedstates/congress-legislators` YAML files, flattened, as published in the Chapter 4 data of Cathy Tanimura's *SQL for Data Analysis* (O'Reilly, 2021). The upstream project is public domain (CC0); Tanimura's repo states no licence. `legislation_date_dim` is a generated calendar.

Dates are `YYYY-MM-DD`, read as UTC midnight. The snapshot is N = 2020-05-22, the last term end that has already happened. Legislator creation is a rule.

The reverse-engineering research, with the queries behind every number, is in [`docs/research/spider2/legislators.md`](../../docs/research/spider2/legislators.md).

## How the log was made

Each term is a `term_started` event owned by its legislator, at `term_start`. Each of the 43,526 terms that ended by N is also a `term_ended` event, at `term_end`. The other 537 terms are still open at N: their scheduled end rides on the start event as `scheduled_end`, so no event carries an early or irregular end before it happens. Start events sort with `ord = 2 · term_number` and end events with `2 · term_number + 1`, so on the 7,882 days where one term ends and the next begins, the end comes first. Legislators are entities, with their biography and cross-reference ids. `term_id` is rebuilt as `id_bioguide || '-' || term_number`.

The source's REAL columns (`district`, `class`, `id_icpsr`, `id_house_history`, `id_house_history_alternate`, `id_thomas`, `id_cspan`, `id_votesmart`) hold only integers, so they travel as `i64` and are cast back to REAL. `other_names_middle` is NULL in every row and is rebuilt as a NULL REAL. `legislation_date_dim` has no events: `specs/build.sql` generates every day from 1917-01-01 to 1999-12-31 with its English month name and day number.

`uv run dataset build legislators` runs `specs/ingest.sql` on the read-only source to make a simkit dataset (an internal stage), then writes it as one log. Entity rows become `<entity>_created` events at their creation time; business events keep their columns. The log is in `seq` order: event time, then entities before events at the same instant. Each row's `payload` is a JSON object whose fields are listed in `schema/events.json`.

## Event catalogue

| Event | Kind | Rows | Payload fields |
|---|---|---:|---|
| `legislators_created` | entity | 12,518 | `legislator_id`, `ext_id`, `full_name`, `first_name`, `last_name`, `middle_name`, `nickname`, `suffix`, `other_names_end`, `other_names_last`, `birthday`, `gender`, `id_bioguide_previous_0`, `id_govtrack`, `id_icpsr`, `id_wikipedia`, `id_wikidata`, `id_google_entity_id`, `id_house_history`, `id_house_history_alternate`, `id_thomas`, `id_cspan`, `id_votesmart`, `id_lis`, `id_ballotpedia`, `id_opensecrets`, `id_fec_0`, `id_fec_1`, `id_fec_2` |
| `term_started` | business | 44,063 | `legislator_id`, `term_number`, `term_type`, `state`, `district`, `class`, `party`, `how`, `url`, `address`, `phone`, `fax`, `contact_form`, `office`, `state_rank`, `rss_url`, `caucus`, `scheduled_end` |
| `term_ended` | business | 43,526 | `legislator_id`, `term_number` |

## Times set by rule

A legislator is created at their first term start (1789-03-04 to 2020-05-19). Every term start and end is a source date.

## Expected output

`results/` holds every source table, as the source stores it. Each column's type follows the values it holds: text, int64 or float64. A mixed column holds text and numbers together, so it is stored as SQLite's own text rendering and declared in `dataset.toml`.

| Table | Rows | Columns | Mixed columns |
|---|---:|---:|---|
| `legislators` | 12,518 | 29 | none |
| `legislators_terms` | 44,063 | 20 | none |
| `legislation_date_dim` | 30,315 | 3 | none |

`expected/queries/` holds the answers of the saved questions (`local167`, `local169`, `local170`, `local171`), computed on the source. `dataset verify` runs `specs/build.sql` over the log, loads the tables into SQLite with the source's DDL, and compares them and the answers exactly: rows as multisets, numbers by value, text byte for byte.

None of the four questions has gold SQL; each has two gold answers, and the split is whether December 31 comes from any year or only from `legislation_date_dim`'s 1917–1999 rows. `local169` and `local171` reproduce both of their answers; `local167` and `local170` reproduce the date-dim answer (`_b`), so the generated calendar is exercised.

## Regenerate

```bash
uv run refdata fetch                 # once: the Spider 2.0 SQLite files → data/spider2/
uv run dataset build legislators             # → $NEORISK_DATA_ROOT/legislators/v1/ (default data/datasets/)
uv run dataset verify legislators            # exit 0 = every table and answer matches
```

## Extend

- **More rows:** not possible for a fixed source. Stage 2 will generate logs from `specs/pack.py`.
- **A new event type:** declare it in `specs/pack.py`, add its `-- event: <name> owner=<col>` block to `specs/ingest.sql`, and use it in `specs/build.sql`.
- **A new attribute:** add the column to the pack table and to its ingest block. It then appears in the payload and in `schema/events.json`.
- **A new results table:** add it to `specs/source.toml` and a `-- table: <name>` block to `specs/build.sql`.
- **A new saved question:** add `specs/queries/<id>.sql` (SQLite dialect, source table names).
- **A new engine port:** write `engines/<engine>/` from `specs/build.sql`. It must read only the log and match `results/` exactly.

Any change to `specs/`, `dataset.toml` or the source changes the build. Once a version is recorded in `v1.lock.json`, changed output needs a new version (`v2`).
