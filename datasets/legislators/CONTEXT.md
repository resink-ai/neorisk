# legislators

## What this is

Members of the US Congress, 1789–2020: each legislator's terms in the House or the Senate, each one starting and, unless it is still open, ending.

Version `v1`, kind `spider2`. The input is one ordered event log of 112,625 events; the output is the 3 source tables, rebuilt exactly, and the answers to 4 saved Spider 2.0 questions.

## Raw data

`city_legislation.sqlite` (the tables `legislators`, `legislators_terms` and `legislation_date_dim`). The rows are the `unitedstates/congress-legislators` YAML files, flattened, as published in the Chapter 4 data of Cathy Tanimura's *SQL for Data Analysis* (O'Reilly, 2021). The upstream project is public domain (CC0); Tanimura's repo states no licence. `legislation_date_dim` is a generated calendar.

Dates are `YYYY-MM-DD`, read as UTC midnight. The snapshot is N = 2020-05-22, the last term end that has already happened. Legislator creation is a rule.

The reverse-engineering research, with the queries behind every number, is in [`docs/research/spider2/legislators.md`](../../docs/research/spider2/legislators.md).

## How the log was made

Each term is a `term_started` event owned by its legislator, at `term_start`. Each of the 43,526 terms that ended by N is also a `term_ended` event, at `term_end`. The other 537 terms are still open at N: their scheduled end rides on the start event as `scheduled_end`, so no event carries an early or irregular end before it happens. Start events sort with `ord = 2 · term_number` and end events with `2 · term_number + 1`, so on the 7,882 days where one term ends and the next begins, the end comes first. Legislators are entities, with their birth names, birthday, gender and the stable cross-reference ids. The current official and last names, the name-change record and the modern cross-reference ids are snapshot columns, so they ride on one `legislators_snapshot` event per legislator at N. `term_id` is rebuilt as `id_bioguide || '-' || term_number`.

The source's REAL columns (`district`, `class`, `id_icpsr`, `id_house_history`, `id_house_history_alternate`, `id_thomas`, `id_cspan`, `id_votesmart`) hold only integers, so they travel as `i64` and are cast back to REAL. `other_names_middle` is NULL in every row and is rebuilt as a NULL REAL. `legislation_date_dim` has no events: `specs/build.sql` generates every day from 1917-01-01 to 1999-12-31 with its English month name and day number.

`uv run dataset build legislators` runs `specs/ingest.sql` on the read-only source to make a simkit dataset (an internal stage), then writes it as one log. Entity rows become `<entity>_created` events at their creation time; business events keep their columns. The log is in `seq` order: event time, then entities before events at the same instant. Each row's `payload` is a JSON object whose fields are listed in `schema/events.json`.

## Event catalogue

| Event | Kind | Rows | Payload fields |
|---|---|---:|---|
| `legislators_created` | entity | 12,518 | `legislator_id`, `ext_id`, `first_name`, `middle_name`, `nickname`, `suffix`, `birthday`, `gender`, `id_bioguide_previous_0`, `id_govtrack`, `id_icpsr`, `id_wikidata`, `id_google_entity_id`, `id_house_history`, `id_house_history_alternate` |
| `legislators_snapshot` | business | 12,518 | `legislator_id`, `full_name`, `last_name`, `other_names_end`, `other_names_last`, `id_wikipedia`, `id_thomas`, `id_cspan`, `id_votesmart`, `id_lis`, `id_ballotpedia`, `id_opensecrets`, `id_fec_0`, `id_fec_1`, `id_fec_2` |
| `term_started` | business | 44,063 | `legislator_id`, `term_number`, `term_type`, `state`, `district`, `class`, `party`, `how`, `url`, `address`, `phone`, `fax`, `contact_form`, `office`, `state_rank`, `rss_url`, `caucus`, `scheduled_end` |
| `term_ended` | business | 43,526 | `legislator_id`, `term_number` |

## Times set by rule

A legislator is created at their first term start (1789-03-04 to 2020-05-19). Every term start and end is a source date. The snapshot time N is 2020-05-22 00:00:00, the dataset's existing snapshot (the last term end that has already happened); it is also the latest event time in the log.

## Snapshot columns

| Entity | Snapshot event | At (UTC) | Rows | Columns |
|---|---|---|---:|---|
| `legislators` | `legislators_snapshot` | 2020-05-22 00:00:00 | 12,518 | `full_name`, `last_name`, `other_names_end`, `other_names_last`, `id_wikipedia`, `id_thomas`, `id_cspan`, `id_votesmart`, `id_lis`, `id_ballotpedia`, `id_opensecrets`, `id_fec_0`, `id_fec_1`, `id_fec_2` |

| Column | Verdict | Reason |
|---|---|---|
| `legislators.id_bioguide` (`ext_id`) | creation | The source key. |
| `legislators.first_name`, `middle_name`, `nickname`, `suffix` | creation | Given names. |
| `legislators.birthday` | creation | A birth date. |
| `legislators.gender` | creation | Recorded once; nothing in the source changes it. |
| `legislators.id_bioguide_previous_0` | creation | The Bioguide id the member was first filed under (3 rows); a former key, not a current value. |
| `legislators.id_govtrack`, `id_icpsr`, `id_house_history`, `id_house_history_alternate`, `id_wikidata`, `id_google_entity_id` | creation | Stable identity ids that every era has (research): they alias the person and never change once given. |
| `legislators.full_name` | snapshot | Ruling: `name_official_full` as of the 2020 export, a name held now. Research kept it on creation but left the call open. |
| `legislators.last_name` | snapshot | Ruling: the surname held at the export; it changed after creation for 4 members (e.g. Bono → Bono Mack in 2007, first seated 1998). Research kept it on creation. |
| `legislators.other_names_end`, `other_names_last` | snapshot | Ruling: the record of a name change; `other_names_end` falls after the first term start for 4 of the 5 rows, so on creation it would be a value from the future. Research kept them on creation. |
| `legislators.id_wikipedia` | snapshot | Ruling: a Wikipedia page title, which can be renamed, known only as of the export. Research kept it on creation. |
| `legislators.id_thomas`, `id_cspan`, `id_votesmart`, `id_lis`, `id_ballotpedia`, `id_opensecrets`, `id_fec_0`, `id_fec_1`, `id_fec_2` | snapshot | Modern ids assigned by agencies long after most careers began; none of the 10,009 members who left before 1971 has one (research). |
| `legislators.other_names_middle` | derived | NULL in every row; `build.sql` makes it a NULL REAL. |
| `legislation_date_dim.*` | derived | A generated calendar, built by `build.sql`. |

No snapshot column decides an event time: creation takes the first term start from `legislators_terms`.

No domain name: the creation time is a rule (the first term start), and that act is already its own `term_started` event, so legislators keep `legislators_created`.

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
