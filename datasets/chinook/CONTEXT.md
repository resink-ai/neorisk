# chinook

## What this is

Chinook, a digital music store: invoices and their lines over a catalogue of tracks, albums, artists and playlists.

Version `v1`, kind `spider2`. The input is one ordered event log of 19,177 events; the output is the 11 source tables, rebuilt exactly, and the answers to 3 saved Spider 2.0 questions.

## Raw data

`chinook.sqlite`, 11 tables. A generated sample database; MIT licence.

Invoice dates are midnights, read as UTC. sqlite_sequence and sqlite_stat1 are not data.

The reverse-engineering research, with the queries behind every number, is in [`docs/research/spider2/chinook.md`](../../docs/research/spider2/chinook.md).

## How the log was made

Each invoice and each invoice line is an event owned by the customer. The catalogue (including playlist membership, as a link entity) and the employees are entities. An employee is created by an `employee_hired` event at the hire date. A track's list price, an employee's title, manager, address and contacts, and a customer's company, contacts and support rep are values as of the extract, so they travel in one `<entity>_snapshot` event per row at N. A customer's address stays on creation: every invoice, the first included, is billed to it, so the source dates it from the customer's first invoice. Invoice totals are the line cents summed and divided by 100.

`uv run dataset build chinook` runs `specs/ingest.sql` on the read-only source to make a simkit dataset (an internal stage), then writes it as one log. Entity rows become `<entity>_created` events at their creation time; business events keep their columns. The log is in `seq` order: event time, then entities before events at the same instant. Each row's `payload` is a JSON object whose fields are listed in `schema/events.json`.

## Event catalogue

| Event | Kind | Rows | Payload fields |
|---|---|---:|---|
| `genres_created` | entity | 25 | `genre_id`, `ext_id`, `name` |
| `media_types_created` | entity | 5 | `media_type_id`, `ext_id`, `name` |
| `artists_created` | entity | 275 | `artist_id`, `ext_id`, `name` |
| `albums_created` | entity | 347 | `album_id`, `ext_id`, `title`, `artist_id` |
| `tracks_created` | entity | 3,503 | `track_id`, `ext_id`, `name`, `album_id`, `media_type_id`, `genre_id`, `composer`, `milliseconds`, `bytes` |
| `playlists_created` | entity | 18 | `playlist_id`, `ext_id`, `name` |
| `playlist_track_created` | entity | 8,715 | `pt_id`, `ext_id`, `playlist_id`, `track_id` |
| `employee_hired` | entity | 8 | `employee_id`, `ext_id`, `last_name`, `first_name`, `birth_date` |
| `customers_created` | entity | 59 | `customer_id`, `ext_id`, `first_name`, `last_name`, `address`, `city`, `state`, `country`, `postal_code` |
| `invoice_issued` | business | 412 | `customer_id`, `invoice_id` |
| `invoice_line_added` | business | 2,240 | `customer_id`, `invoice_id`, `invoice_line_id`, `track_id`, `unit_price`, `quantity` |
| `tracks_snapshot` | business | 3,503 | `track_id`, `unit_price` |
| `employees_snapshot` | business | 8 | `employee_id`, `title`, `reports_to`, `address`, `city`, `state`, `country`, `postal_code`, `phone`, `fax`, `email` |
| `customers_snapshot` | business | 59 | `customer_id`, `company`, `phone`, `fax`, `email`, `support_rep_id` |

## Times set by rule

Customers are created at their first invoice. The catalogue (genres, media types, artists, albums, tracks, playlists and their links) is created at T0 = 2009-01-01 00:00:00, the first invoice. Snapshots are at N = 2013-12-22 00:00:00, the last invoice and so the latest event time in the log.

## Snapshot columns

| Entity | Snapshot event | At (UTC) | Rows | Columns |
|---|---|---|---:|---|
| `tracks` | `tracks_snapshot` | 2013-12-22 00:00:00 | 3,503 | `unit_price` |
| `employees` | `employees_snapshot` | 2013-12-22 00:00:00 | 8 | `title`, `reports_to`, `address`, `city`, `state`, `country`, `postal_code`, `phone`, `fax`, `email` |
| `customers` | `customers_snapshot` | 2013-12-22 00:00:00 | 59 | `company`, `phone`, `fax`, `email`, `support_rep_id` |

| Column | Verdict | Reason |
|---|---|---|
| `genres.ext_id` | creation | The source key (`GenreId`). |
| `genres.name` | creation | A given name. |
| `media_types.ext_id` | creation | The source key (`MediaTypeId`). |
| `media_types.name` | creation | A given name. |
| `artists.ext_id` | creation | The source key (`ArtistId`). |
| `artists.name` | creation | A given name. |
| `albums.ext_id` | creation | The source key (`AlbumId`). |
| `albums.title` | creation | A title. |
| `albums.artist_id` | creation | An immutable ref: the album's artist. |
| `tracks.ext_id` | creation | The source key (`TrackId`). |
| `tracks.name` | creation | A title. |
| `tracks.album_id` | creation | An immutable ref: the album the track was released on. |
| `tracks.media_type_id` | creation | An immutable ref: the file's encoding. |
| `tracks.genre_id` | creation | The original category. |
| `tracks.composer` | creation | Part of the release; the source shows no change. |
| `tracks.milliseconds` | creation | A property of the recording. |
| `tracks.bytes` | creation | A property of the file. |
| `tracks.unit_price` | snapshot | A list price as of the extract; the price paid is on `invoice_line_added`. Research kept it on creation. |
| `playlists.ext_id` | creation | The source key (`PlaylistId`). |
| `playlists.name` | creation | A given name. |
| `playlist_track.ext_id` | creation | The link's two source ids; a link has no other attribute. |
| `playlist_track.playlist_id` | creation | An immutable ref: one end of the link. |
| `playlist_track.track_id` | creation | An immutable ref: one end of the link. |
| `employees.ext_id` | creation | The source key (`EmployeeId`). |
| `employees.created_at` (`HireDate`) | creation | The hire date; it is the event's time. |
| `employees.last_name` | creation | Given names. |
| `employees.first_name` | creation | Given names. |
| `employees.birth_date` | creation | A birth date. |
| `employees.title` | snapshot | A title held, which can change after the hire. Research kept it on creation. |
| `employees.reports_to` | snapshot | The current manager, a self-ref; the org chart can change. Research kept it on creation. |
| `employees.address` | snapshot | An address, known only as of the extract. Research kept it on creation. |
| `employees.city` | snapshot | An address. Research kept it on creation. |
| `employees.state` | snapshot | An address. Research kept it on creation. |
| `employees.country` | snapshot | An address. Research kept it on creation. |
| `employees.postal_code` | snapshot | An address. Research kept it on creation. |
| `employees.phone` | snapshot | A phone. Research kept it on creation. |
| `employees.fax` | snapshot | A phone. Research kept it on creation. |
| `employees.email` | snapshot | An e-mail. Research kept it on creation. |
| `customers.ext_id` | creation | The source key (`CustomerId`). |
| `customers.created_at` | creation | The first invoice (a rule); it is the event's time. |
| `customers.first_name` | creation | Given names. |
| `customers.last_name` | creation | Given names. |
| `customers.address` | creation | Ruling: the rubric lists addresses as snapshot, but the five billing columns equal the customer's address in 412 of 412 invoices, so the source records it at the first invoice, the creation time, and never shows a change. `invoices` rebuilds its billing address from it, which a snapshot at N would make a value from the invoice's future. |
| `customers.city` | creation | As `address`: billed on every invoice from the first. |
| `customers.state` | creation | As `address`: billed on every invoice from the first. |
| `customers.country` | creation | As `address`: billed on every invoice from the first. |
| `customers.postal_code` | creation | As `address`: billed on every invoice from the first. |
| `customers.company` | snapshot | The customer's employer as of the extract; when in doubt, snapshot. Research kept it on creation. |
| `customers.phone` | snapshot | A phone. Research kept it on creation. |
| `customers.fax` | snapshot | A phone. Research kept it on creation. |
| `customers.email` | snapshot | An e-mail. Research kept it on creation. |
| `customers.support_rep_id` | snapshot | The rep assigned as of the extract; a customer can be reassigned. Research kept it on creation. |
| `invoices.Total` | derived | The line cents summed, / 100.0 (412 of 412); computed in `build.sql`, not carried. |

Only employees carry a domain name, `employee_hired`: the source dates the hire. Customers are created at their first invoice by rule, and the catalogue at T0, so they keep `<entity>_created`.

## Expected output

`results/` holds every source table, as the source stores it. Each column's type follows the values it holds: text, int64 or float64. A mixed column holds text and numbers together, so it is stored as SQLite's own text rendering and declared in `dataset.toml`.

| Table | Rows | Columns | Mixed columns |
|---|---:|---:|---|
| `genres` | 25 | 2 | none |
| `media_types` | 5 | 2 | none |
| `artists` | 275 | 2 | none |
| `albums` | 347 | 3 | none |
| `tracks` | 3,503 | 9 | none |
| `playlists` | 18 | 2 | none |
| `playlist_track` | 8,715 | 2 | none |
| `employees` | 8 | 15 | none |
| `customers` | 59 | 13 | none |
| `invoices` | 412 | 9 | none |
| `invoice_items` | 2,240 | 5 | none |

`expected/queries/` holds the answers of the saved questions (`local054`, `local055`, `local198`), computed on the source. `dataset verify` runs `specs/build.sql` over the log, loads the tables into SQLite with the source's DDL, and compares them and the answers exactly: rows as multisets, numbers by value, text byte for byte.

## Regenerate

```bash
uv run refdata fetch                 # once: the Spider 2.0 SQLite files → data/spider2/
uv run dataset build chinook             # → $NEORISK_DATA_ROOT/chinook/v1/ (default data/datasets/)
uv run dataset verify chinook            # exit 0 = every table and answer matches
```

## Extend

- **More rows:** not possible for a fixed source. Stage 2 will generate logs from `specs/pack.py`.
- **A new event type:** declare it in `specs/pack.py`, add its `-- event: <name> owner=<col>` block to `specs/ingest.sql`, and use it in `specs/build.sql`.
- **A new attribute:** add the column to the pack table and to its ingest block. It then appears in the payload and in `schema/events.json`.
- **A new results table:** add it to `specs/source.toml` and a `-- table: <name>` block to `specs/build.sql`.
- **A new saved question:** add `specs/queries/<id>.sql` (SQLite dialect, source table names).
- **A new engine port:** write `engines/<engine>/` from `specs/build.sql`. It must read only the log and match `results/` exactly.

Any change to `specs/`, `dataset.toml` or the source changes the build. Once a version is recorded in `v1.lock.json`, changed output needs a new version (`v2`).
