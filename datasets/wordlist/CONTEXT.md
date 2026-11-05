# wordlist

## What this is

An English word list: 370,103 lower-case words, with no time and no behaviour. Spider 2.0 uses it as a puzzle input for one anagram question.

Version `v1`, kind `spider2`. The input is one ordered event log of 373,804 events; the output is the source table, rebuilt exactly, and the answers to 2 saved Spider 2.0 questions.

## Raw data

`modern_data.sqlite` (the `word_list` table). The base list begins `a, aa, aaa` and is consistent with `words_alpha.txt` of the dwyl/english-words repository (Unlicense). Licence: unstated in Spider2.

Untimed. Every time is a rule.

The list passed through a pandas import: the words `nan` and `null` became NULL (2 rows), and `true` and `false` became `TRUE` and `FALSE`. All four are kept as stored. Spider2 prepended 3,701 copies of existing words, rows 1 to 3,701. They are kept: local201's accepted `_b` answer depends on them.

The reverse-engineering research, with the queries behind every number, is in [`docs/research/spider2/modern_misc.md`](../../docs/research/spider2/modern_misc.md).

## How the log was made

Each row of the base list is a `words` entity. Its key is its 1-based position in the base list, zero-padded in `ext_id` so that the key equals the position. The word cannot be the key, because 2 rows are NULL. Each of Spider2's 3,701 copied rows is a `source_row_duplicated` event that references the copied word; the view adds one more copy of that word. A copy is a non-NULL row with an identical row at a later rowid, so the 2 NULL rows are not treated as copies of each other. Stage 2 can drop that event type and keep the rest.

`uv run dataset build wordlist` runs `specs/ingest.sql` on the read-only source to make a simkit dataset (an internal stage), then writes it as one log. Entity rows become `<entity>_created` events at their creation time; business events keep their columns. The log is in `seq` order: event time, then entities before events at the same instant. Each row's `payload` is a JSON object whose fields are listed in `schema/events.json`.

## Event catalogue

| Event | Kind | Rows | Payload fields |
|---|---|---:|---|
| `words_created` | entity | 370,103 | `word_key`, `ext_id`, `word` |
| `source_row_duplicated` | business | 3,701 | `word_id`, `src_table` |

## Times set by rule

Every word is created, and every duplicate is marked, at T0 = 2016-01-01 00:00:00, as for weblog's untimed masters. No time is data.

## Expected output

`results/` holds every source table, as the source stores it. Each column's type follows the values it holds: text, int64 or float64. A mixed column holds text and numbers together, so it is stored as SQLite's own text rendering and declared in `dataset.toml`.

| Table | Rows | Columns | Mixed columns |
|---|---:|---:|---|
| `word_list` | 373,804 | 1 | none |

`expected/queries/` holds the answers of the saved questions (`local201`, `local201_b`), computed on the source. They are the two accepted readings of one question: `local201` counts distinct other words with the same sorted letters (gold `_a`, raad 3 to race 5), and `local201_b` counts other rows holding the same word (gold `_b`, the first 10 duplicated r-words, each 1). `dataset verify` runs `specs/build.sql` over the log, loads the table into SQLite with the source's DDL, and compares it and the answers exactly: rows as multisets, numbers by value, text byte for byte.

## Regenerate

```bash
uv run refdata fetch                 # once: the Spider 2.0 SQLite files → data/spider2/
uv run dataset build wordlist             # → $NEORISK_DATA_ROOT/wordlist/v1/ (default data/datasets/)
uv run dataset verify wordlist            # exit 0 = every table and answer matches
```

## Extend

- **More rows:** not possible for a fixed source. Stage 2 will generate logs from `specs/pack.py`.
- **A new event type:** declare it in `specs/pack.py`, add its `-- event: <name> owner=<col>` block to `specs/ingest.sql`, and use it in `specs/build.sql`.
- **A new attribute:** add the column to the pack table and to its ingest block. It then appears in the payload and in `schema/events.json`.
- **A new results table:** add it to `specs/source.toml` and a `-- table: <name>` block to `specs/build.sql`.
- **A new saved question:** add `specs/queries/<id>.sql` (SQLite dialect, source table names).
- **A new engine port:** write `engines/<engine>/` from `specs/build.sql`. It must read only the log and match `results/` exactly.

Any change to `specs/`, `dataset.toml` or the source changes the build. Once a version is recorded in `v1.lock.json`, changed output needs a new version (`v2`).
