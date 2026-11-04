# music

## What this is

Chinook, a digital music store, under its upstream table names: invoices and their lines over a catalogue of tracks, albums, artists and playlists.

Version `v1`, kind `spider2`. The input is one ordered event log of 15,607 events; the output is the 11 source tables, rebuilt exactly, and the answer to 1 saved Spider 2.0 question.

## Raw data

`music.sqlite`, 11 tables. Chinook by Luis Rocha (`lerocha/chinook-database`) in its upstream SQLite packaging; MIT licence.

The tables have upstream's singular PascalCase names (`Album`, `InvoiceLine`, `PlaylistTrack`, …). Every table holds the same rows, in the same physical order, as its twin in `chinook.sqlite` (the `chinook` dataset): 0 differing rows in all 11. Only the table names, the DDL style and the indexes differ. There is no AUTOINCREMENT, so there is no `sqlite_sequence`. Invoice dates run from 2009-01-01 to 2013-12-22; they are midnights, read as UTC.

The reverse-engineering research, with the queries behind every number, is in [`docs/research/spider2/music.md`](../../docs/research/spider2/music.md), which builds on [`chinook.md`](../../docs/research/spider2/chinook.md).

## How the log was made

The pack, the ingest blocks and the build bodies are chinook's. Only the source table names in `specs/ingest.sql` and the `-- table:` headers in `specs/build.sql` change. So the log is chinook's log: the same events, the same payloads, the same order.

Each invoice and each invoice line is an event owned by the customer. The catalogue (including playlist membership, as a link entity) and the employees are entities. Invoice totals are the line cents summed and divided by 100.

`uv run dataset build music` runs `specs/ingest.sql` on the read-only source to make a simkit dataset (an internal stage), then writes it as one log. Entity rows become `<entity>_created` events at their creation time; business events keep their columns. The log is in `seq` order: event time, then entities before events at the same instant. Each row's `payload` is a JSON object whose fields are listed in `schema/events.json`.

## Event catalogue

| Event | Kind | Rows | Payload fields |
|---|---|---:|---|
| `genres_created` | entity | 25 | `genre_id`, `ext_id`, `name` |
| `media_types_created` | entity | 5 | `media_type_id`, `ext_id`, `name` |
| `artists_created` | entity | 275 | `artist_id`, `ext_id`, `name` |
| `albums_created` | entity | 347 | `album_id`, `ext_id`, `title`, `artist_id` |
| `tracks_created` | entity | 3,503 | `track_id`, `ext_id`, `name`, `album_id`, `media_type_id`, `genre_id`, … (10 in all) |
| `playlists_created` | entity | 18 | `playlist_id`, `ext_id`, `name` |
| `playlist_track_created` | entity | 8,715 | `pt_id`, `ext_id`, `playlist_id`, `track_id` |
| `employees_created` | entity | 8 | `employee_id`, `ext_id`, `last_name`, `first_name`, `title`, `reports_to`, … (15 in all) |
| `customers_created` | entity | 59 | `customer_id`, `ext_id`, `first_name`, `last_name`, `company`, `address`, … (14 in all) |
| `invoice_issued` | business | 412 | `customer_id`, `invoice_id` |
| `invoice_line_added` | business | 2,240 | `customer_id`, `invoice_id`, `invoice_line_id`, `track_id`, `unit_price`, `quantity` |

## Times set by rule

Customers are created at their first invoice. Employees are created at their hire date; invoices and their lines take the invoice date.

## Expected output

`results/` holds every source table, as the source stores it. Each column's type follows the values it holds: text, int64 or float64. A mixed column holds text and numbers together, so it is stored as SQLite's own text rendering and declared in `dataset.toml`.

| Table | Rows | Columns | Mixed columns |
|---|---:|---:|---|
| `Genre` | 25 | 2 | none |
| `MediaType` | 5 | 2 | none |
| `Artist` | 275 | 2 | none |
| `Album` | 347 | 3 | none |
| `Track` | 3,503 | 9 | none |
| `Playlist` | 18 | 2 | none |
| `PlaylistTrack` | 8,715 | 2 | none |
| `Employee` | 8 | 15 | none |
| `Customer` | 59 | 13 | none |
| `Invoice` | 412 | 9 | none |
| `InvoiceLine` | 2,240 | 5 | none |

`expected/queries/` holds the answer of the saved question (`local244`), computed on the source. `dataset verify` runs `specs/build.sql` over the log, loads the tables into SQLite with the source's DDL, and compares them and the answers exactly: rows as multisets, numbers by value, text byte for byte.

local244 classifies tracks by duration, with cut points at 197,335.106 ms and 2,840,276.106 ms, and sums the invoice-line revenue per class: short 469.26, medium 1,817.55, long 41.79. Its query reproduces the gold variant `local244_a`. The gold CSVs show these sums with different float rounding in the last digits, because they were summed in another order; float64 columns compare with a relative tolerance of 1e-9.

## Regenerate

```bash
uv run refdata fetch                 # once: the Spider 2.0 SQLite files → data/spider2/
uv run dataset build music             # → $NEORISK_DATA_ROOT/music/v1/ (default data/datasets/)
uv run dataset verify music            # exit 0 = every table and answer matches
```

## Extend

- **More rows:** not possible for a fixed source. Stage 2 will generate logs from `specs/pack.py`.
- **A new event type:** declare it in `specs/pack.py`, add its `-- event: <name> owner=<col>` block to `specs/ingest.sql`, and use it in `specs/build.sql`.
- **A new attribute:** add the column to the pack table and to its ingest block. It then appears in the payload and in `schema/events.json`.
- **A new results table:** add it to `specs/source.toml` and a `-- table: <name>` block to `specs/build.sql`.
- **A new saved question:** add `specs/queries/<id>.sql` (SQLite dialect, source table names).
- **A new engine port:** write `engines/<engine>/` from `specs/build.sql`. It must read only the log and match `results/` exactly.
- **Keeping it in step with chinook:** the pack is a copy of `datasets/chinook/specs/pack.py`. A change to one should go to the other, or the two logs stop being the same.

Any change to `specs/`, `dataset.toml` or the source changes the build. Once a version is recorded in `v1.lock.json`, changed output needs a new version (`v2`).
