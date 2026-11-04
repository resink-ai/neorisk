# imdb_movies

## What this is

The "RSVP Movies" IMDb case study: 7,997 movies published from 2017 to 2019, tagged with genres, credited with directors and top-billed actors, and rated on IMDb at the scrape.

Version `v1`, kind `spider2`. The input is one ordered event log of 90,680 events; the output is the 7 source tables, rebuilt exactly, and the answers to 2 saved Spider 2.0 questions.

## Raw data

`imdb_movies.sqlite`, 7 tables, 75,898 rows. Course material (attributed to the IIIT Bangalore / upGrad data-science programme, unverified) built from real IMDb data; licence unstated.

`date_published` is a midnight `YYYY-MM-DD 00:00:00` text in a column declared `TIMESTAMP`; it is the publication (re-release) date, not always the original year. `year` is its year in all 7,997 rows. Ratings are filtered to at least 100 votes. Credits cover about 47% of movies, about 4 top-billed people each; 9,590 names have no credit. `worlwide_gross_income` (sic) is `'$ '` and plain digits. `country`, `languages` and `production_company` are `', '`-joined lists. `date_of_birth` is text in three shapes: `YYYY-MM-DD`, `YYYY` and one `'October 29'`. `names.known_for_movies` is a comma-joined list of ids, 2,261 of whose values point outside the catalog, so it is not a reference. The extra table `ERD` is the case study's ERD spreadsheet read by pandas: 25 rows, 5 text columns and 8 REAL columns that are NULL in every row.

The reverse-engineering research, with the queries behind every number, is in [`docs/research/spider2/imdbmovies.md`](../../docs/research/spider2/imdbmovies.md).

## How the log was made

Movies, names and the ERD rows are entities. Each genre tag, director credit and cast credit is an event owned by its movie. A movie's rating is one `movie_rated` event at N. The gross (4,273 movies, as integer dollars) and the known-for lists (10,509 names, verbatim) are snapshot values, in `movies_snapshot` and `names_snapshot` events at N. `year` and `date_published` are both rebuilt from the movie's creation time; height travels as integer centimetres and is rebuilt as REAL.

`uv run dataset build imdb_movies` runs `specs/ingest.sql` on the read-only source to make a simkit dataset (an internal stage), then writes it as one log. Entity rows become `<entity>_created` events at their creation time; business events keep their columns. The log is in `seq` order: event time, then entities before events at the same instant. Each row's `payload` is a JSON object whose fields are listed in `schema/events.json`.

## Event catalogue

| Event | Kind | Rows | Payload fields |
|---|---|---:|---|
| `erd_created` | entity | 25 | `erd_id`, `ext_id`, `table`, `column`, `u6`, `u9`, `u12` |
| `names_created` | entity | 25,735 | `name_id`, `ext_id`, `name`, `height`, `date_of_birth` |
| `movies_created` | entity | 7,997 | `movie_id`, `ext_id`, `title`, `duration`, `country`, `languages`, `production_company` |
| `movie_genre_tagged` | business | 14,662 | `movie_id`, `genre` |
| `director_credited` | business | 3,867 | `movie_id`, `person_id` |
| `cast_credited` | business | 15,615 | `movie_id`, `person_id`, `category` |
| `movie_rated` | business | 7,997 | `movie_id`, `avg_rating`, `total_votes`, `median_rating` |
| `movies_snapshot` | business | 4,273 | `movie_id`, `worldwide_gross_usd` |
| `names_snapshot` | business | 10,509 | `name_id`, `known_for_movies` |

## Times set by rule

A movie is created at its `date_published`, the only time in the source. Its genre tags and credits take that time. A person is created at their first credited publication; the 9,590 uncredited people and the 25 ERD rows are created at the catalog start, 2017-01-01. Ratings, gross and known-for lists are snapshot values at N = 2020-01-01, just after the last publication (2019-12-27).

## Expected output

`results/` holds every source table, as the source stores it. Each column's type follows the values it holds: text, int64 or float64. A mixed column holds text and numbers together, so it is stored as SQLite's own text rendering and declared in `dataset.toml`.

| Table | Rows | Columns | Mixed columns |
|---|---:|---:|---|
| `ERD` | 25 | 13 | none |
| `movies` | 7,997 | 9 | none |
| `genre` | 14,662 | 2 | none |
| `director_mapping` | 3,867 | 2 | none |
| `role_mapping` | 15,615 | 3 | none |
| `names` | 25,735 | 5 | none |
| `ratings` | 7,997 | 4 | none |

`expected/queries/` holds the answers of the saved questions (`local152`, `local230`), computed on the source. `dataset verify` runs `specs/build.sql` over the log, loads the tables into SQLite with the source's DDL, and compares them and the answers exactly: rows as multisets, numbers by value, text byte for byte.

`date_published` holds only text, so it is a text column, not a mixed one, even though its declared `TIMESTAMP` type has NUMERIC affinity. local152 lists the top 9 directors by movie count; it matches the gold variant `local152_a` on every cell but the mean rating of 2 directors on a half-cent tie (Steven Soderbergh 6.47 against 6.48, Sam Liu 6.22 against 6.23), where SQLite's `round` on the binary double goes down. local230 finds Drama, Action and Comedy, and four directors with 2 films each (Anthony Russo, James Mangold, Joe Russo, Marianne Elliott), as in `local230_a`.

## Regenerate

```bash
uv run refdata fetch                 # once: the Spider 2.0 SQLite files → data/spider2/
uv run dataset build imdb_movies             # → $NEORISK_DATA_ROOT/imdb_movies/v1/ (default data/datasets/)
uv run dataset verify imdb_movies            # exit 0 = every table and answer matches
```

## Extend

- **More rows:** not possible for a fixed source. Stage 2 will generate logs from `specs/pack.py`.
- **A new event type:** declare it in `specs/pack.py`, add its `-- event: <name> owner=<col>` block to `specs/ingest.sql`, and use it in `specs/build.sql`.
- **A new attribute:** add the column to the pack table and to its ingest block. It then appears in the payload and in `schema/events.json`.
- **A new results table:** add it to `specs/source.toml` and a `-- table: <name>` block to `specs/build.sql`.
- **A new saved question:** add `specs/queries/<id>.sql` (SQLite dialect, source table names).
- **A new engine port:** write `engines/<engine>/` from `specs/build.sql`. It must read only the log and match `results/` exactly.

Any change to `specs/`, `dataset.toml` or the source changes the build. Once a version is recorded in `v1.lock.json`, changed output needs a new version (`v2`).
