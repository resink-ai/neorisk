# dbimdb

## What this is

Db-IMDB, a scrape of IMDb title and name pages weighted to Hindi cinema: 3,475 movies from 1931 to 2018, each released with a cast, producers and one director, and rated on IMDb at the scrape.

Version `v1`, kind `spider2`. The input is one ordered event log of 177,621 events; the output is the 13 source tables, rebuilt exactly, and the answers to 5 saved Spider 2.0 questions.

## Raw data

`Db-IMDB.sqlite`, 13 tables, 154,676 rows. Real public IMDb data, scraped, with real `tt…` and `nm…` ids; origin unverified and licence unstated (IMDb's terms allow personal, non-commercial use). 2,989 of the movies are in Hindi.

The tables were written by pandas `to_sql`: every table has an `index` column, and the link tables' `ID` equals it. Lookup ids (`GID`, `LAID`, `CID`, `LID`) are pandas factorize codes. `M_Country.CID` and `M_Location.LID` are REAL because pandas' NaN held the 5 and 1,626 missing values. The scraper kept the HTML's leading space in cast and producer PIDs and names. Genre names are combinations ("Action, Crime, Drama"); 327 of 328 end in 12 spaces, and one is the text `'Null'`. The only time is `Movie.year`, a year with an optional IMDb roman-numeral prefix ("I 2009", up to XVII).

The reverse-engineering research, with the queries behind every number, is in [`docs/research/spider2/dbimdb.md`](../../docs/research/spider2/dbimdb.md).

## How the log was made

Movies, persons and the four lookups (genres, languages, countries, locations) are entities. The five 1-per-movie link tables (`M_Genre`, `M_Language`, `M_Country`, `M_Location`, `M_Director`) are row i of `Movie`, so they ride on the movie as attributes; the movie also carries `Movie.index` as `src_index`, since that order is scrape order and not a function of anything. Each cast and producer credit is an event owned by its movie, with its 1-based position in the movie; the 2 cast and 21 producer credits with no PID keep a NULL person. A movie's creation event is named `movie_released`. Rating, vote count and the year's roman-numeral disambiguator travel in one `movies_snapshot` event per movie at N, and each person's gender in one `persons_snapshot` event per person at N.

`Person` is not an entity table: it has no key (719 PIDs twice, one all-NULL row). It is rebuilt in `specs/build.sql` as a first-seen dump of the credit stream: the distinct people of `M_Cast` then `M_Producer`, in order of first credit, with the leading space and the NULL row; then the distinct directors in movie order, unpadded. The person entity holds the PID and name without the space. The credit tables' `index` is the row number in movie order, then position, and their PIDs get the space back.

`uv run dataset build dbimdb` runs `specs/ingest.sql` on the read-only source to make a simkit dataset (an internal stage), then writes it as one log. Entity rows become `<entity>_created` events (movies: `movie_released`) at their creation time; business events keep their columns. The log is in `seq` order: event time, then entities before events at the same instant. Each row's `payload` is a JSON object whose fields are listed in `schema/events.json`.

## Event catalogue

| Event | Kind | Rows | Payload fields |
|---|---|---:|---|
| `genres_created` | entity | 328 | `genre_id`, `ext_id`, `name` |
| `languages_created` | entity | 32 | `language_id`, `ext_id`, `name` |
| `countries_created` | entity | 34 | `country_id`, `ext_id`, `name` |
| `locations_created` | entity | 559 | `location_id`, `ext_id`, `name` |
| `persons_created` | entity | 37,565 | `person_id`, `ext_id`, `name` |
| `movie_released` | entity | 3,475 | `movie_id`, `ext_id`, `src_index`, `title`, `genre_id`, `language_id`, `country_id`, `location_id`, `director_id` |
| `cast_credited` | business | 82,837 | `movie_id`, `person_id`, `billing` |
| `producer_credited` | business | 11,751 | `movie_id`, `person_id`, `position` |
| `movies_snapshot` | business | 3,475 | `movie_id`, `rating`, `num_votes`, `disambig` |
| `persons_snapshot` | business | 37,565 | `person_id`, `gender` |

## Times set by rule

The source has no time but the year. A movie is released at January 1 of its year (`substr(year, -4)`), 00:00 UTC, and its cast and producer credits take that time. A person is created at their earliest credit's release, and a lookup row at the release of the first movie that uses it. The snapshot time N = 2019-01-01 00:00:00 is the dataset's existing one: after the last 2018 release, and before `imdb_movies`' later scrape (which has higher vote counts on 237 of 238 shared movies). It is also the latest event time in the log.

## Snapshot columns

| Entity | Snapshot event | At (UTC) | Rows | Columns |
|---|---|---|---:|---|
| `movies` | `movies_snapshot` | 2019-01-01 00:00:00 | 3,475 | `rating`, `num_votes`, `disambig` |
| `persons` | `persons_snapshot` | 2019-01-01 00:00:00 | 37,565 | `gender` |

| Column | Verdict | Reason |
|---|---|---|
| `Movie.MID` (`ext_id`) | creation | The source key. |
| `Movie.index` (`src_index`) | creation | The scraper's row number, carried verbatim like an id; it is not a function of anything and places every `M_*` row. |
| `Movie.title` | creation | A title. |
| `Movie.year`, its 4-digit year | creation | The release year, which sets the movie's creation time; it comes back from the event time. |
| `Movie.year`, its roman prefix (`disambig`) | snapshot | Ruling: IMDb's global disambiguator, which IMDb gives or changes when another title of the same name and year is listed, so it is known only as of the scrape. Research kept it on creation. It does not decide a time: only the last 4 characters do. |
| `Movie.rating`, `num_votes` | snapshot | IMDb's values on the scrape day (research). |
| `M_Genre.GID`, `M_Language.LAID`, `M_Country.CID`, `M_Location.LID`, `M_Director.PID` | creation | 1-per-movie refs, fixed with the movie: its original genre, language, country, location and director. |
| `Person.PID` (`ext_id`) | creation | The source key. |
| `Person.Name` | creation | A given name (stored without the scraper's leading space). |
| `Person.Gender` | snapshot | Ruling: recorded by the scraper as of the scrape, and only for people it met in a cast list (NULL for 1,309 of 1,464 directors), so nothing fixes it at the first credit. Research kept it on creation. |
| `Genre.Name`, `Language.Name`, `Country.Name`, `Location.Name` | creation | Given names of lookup rows. |
| `M_Cast`, `M_Producer` | not entity columns | Credits are their own events. |
| `*.index`, `*.ID` of the link tables, `Person`'s row order | derived | `build.sql` computes them from `src_index` and the credit positions (research). |

Every snapshot column leaves events that happened before N; none of them decides an event's time or place, so moving them takes no value from any event's future.

Domain name: a movie's creation is its release (the year is the only time the source holds), so it is `movie_released`, as the research names it. Persons and lookup rows are created by rule at first use, which shows no real-world act, so they keep `<entity>_created`.

## Expected output

`results/` holds every source table, as the source stores it. Each column's type follows the values it holds: text, int64 or float64. A mixed column holds text and numbers together, so it is stored as SQLite's own text rendering and declared in `dataset.toml`.

| Table | Rows | Columns | Mixed columns |
|---|---:|---:|---|
| `Movie` | 3,475 | 6 | none |
| `Genre` | 328 | 3 | none |
| `Language` | 32 | 3 | none |
| `Country` | 34 | 3 | none |
| `Location` | 559 | 3 | none |
| `M_Location` | 3,475 | 4 | none |
| `M_Country` | 3,475 | 4 | none |
| `M_Language` | 3,475 | 4 | none |
| `M_Genre` | 3,475 | 4 | none |
| `Person` | 38,285 | 4 | none |
| `M_Producer` | 11,751 | 4 | none |
| `M_Director` | 3,475 | 4 | none |
| `M_Cast` | 82,837 | 4 | none |

`expected/queries/` holds the answers of the saved questions (`local096`, `local097`, `local098`, `local099`, `local100`), computed on the source. `dataset verify` runs `specs/build.sql` over the log, loads the tables into SQLite with the source's DDL, and compares them and the answers exactly: rows as multisets, numbers by value, text byte for byte.

Every question joins credits to `Person` through `trim(PID)`, and three parse the year with `substr(year, -4)`, so the padding and the year prefixes matter. local096 (78 years; non-zero only for 1939, 1999, 2000 and 2018), local097 (2008, 1,205 movies) and local100 (25,698 actors) reproduce their only gold variant. local098 reproduces `local098_c` (28,698); `_a` (29,066) and `_b` (29,065) were not reproduced. local099 is the gold SQL, which gives `local099_b` (107); `_a` (266) was not reproduced.

## Regenerate

```bash
uv run refdata fetch                 # once: the Spider 2.0 SQLite files → data/spider2/
uv run dataset build dbimdb             # → $NEORISK_DATA_ROOT/dbimdb/v1/ (default data/datasets/)
uv run dataset verify dbimdb            # exit 0 = every table and answer matches
```

## Extend

- **More rows:** not possible for a fixed source. Stage 2 will generate logs from `specs/pack.py`.
- **A new event type:** declare it in `specs/pack.py`, add its `-- event: <name> owner=<col>` block to `specs/ingest.sql`, and use it in `specs/build.sql`.
- **A new attribute:** add the column to the pack table and to its ingest block. It then appears in the payload and in `schema/events.json`.
- **A new results table:** add it to `specs/source.toml` and a `-- table: <name>` block to `specs/build.sql`.
- **A new saved question:** add `specs/queries/<id>.sql` (SQLite dialect, source table names).
- **A new engine port:** write `engines/<engine>/` from `specs/build.sql`. It must read only the log and match `results/` exactly. `Person` depends on carrying `src_index`, billing and position exactly.

Any change to `specs/`, `dataset.toml` or the source changes the build. Once a version is recorded in `v1.lock.json`, changed output needs a new version (`v2`).
