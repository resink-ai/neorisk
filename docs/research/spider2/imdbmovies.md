# imdb_movies (Spider 2.0-lite): reverse-engineered event log

Source: `data/spider2/imdb_movies.sqlite` (3.0 MB), opened read-only. `scripts/imdbmovies/rq.py` copies the file into an in-memory SQLite and runs named blocks; the file itself is never written.

Every number below comes from one of these scripts:
- a named query in `scripts/imdbmovies/q*.sql`;
- `x_overlap.py` (overlap with `Db-IMDB`; the same script and output as in `scripts/dbimdb/`).

The raw outputs are in `scripts/imdbmovies/out_*.txt`. A reference such as `[q1:fk_orphans]` means file `q1_inventory.sql`, block `-- name: fk_orphans`. Gold CSVs are in `scripts/imdbmovies/gold/`.

## 0. What this catalog is

- **Dataset.** The **"RSVP Movies" IMDb SQL case study**, a course dataset from the IIIT Bangalore / upGrad data-science programme. Many public write-ups use the same six tables (`movie`, `genre`, `director_mapping`, `role_mapping`, `names`, `ratings`), the misspelt column `worlwide_gross_income`, and the "top director in the top 3 genres rated above 8 is James Mangold" finding that local230 asks for. This is unverified against an official upGrad page.
- **Evidence in the file.**
  - The extra table **`ERD`** (25 rows, columns `Unnamed: 2` … `Unnamed: 12`) is the case study's ERD **spreadsheet**, read with pandas `read_excel`. Its `(table, column)` pairs list all 25 real columns (25 of 25 exist) [q1:erd_rows, q3:erd_matches_schema], and the other cells are the drawn boxes' labels.
  - The table is `movies` here; the ERD calls it `movie`.
  - Every movie is published 2017-01-01 .. 2019-12-27: 3,052 in 2017, 2,944 in 2018 and 2,001 in 2019 [q2:movies_per_year].
- **Row counts** [q1:row_counts]: ERD 25, movies 7,997, genre 14,662, director_mapping 3,867, role_mapping 15,615, names 25,735, ratings 7,997. Total 75,898.
- **Licence.** Unstated. It is course material built from IMDb data, whose terms allow non-commercial use. Fitting statistics is fine; redistributing rows needs a check.
- **Nature.** Real IMDb data, curated for a course, not anonymised.
  - Ratings are filtered to at least 100 votes (min `total_votes` = 100) [q2:ratings_shapes].
  - Credits are trimmed to about the top 4 billed (3,380 of 3,757 credited movies have exactly 4 roles) [q2:roles_per_movie].
- **Overlap with `Db-IMDB`** [x_overlap]: 238 shared movie ids and 1,771 shared person ids. The vote counts here are higher on 237 of the shared movies and never lower, so this is a later scrape. The years differ on 39 of the 238: Db-IMDB's *Ankur* is 1974, here it is 2019. So `year` and `date_published` here are a **publication (re-release) date**, not the original year. These are separate catalogs and **two datasets**.

## 0.1 How Spider 2.0 uses it

Two questions use db `imdb_movies`. Neither has gold SQL; each has an exec_result CSV.

| id | asks | gold SQL? | gold value | reproduced |
|---|---|---|---|---|
| local152 | top 9 directors by movie count (ties broken by total duration): id, name, count, mean days between consecutive `date_published`, avg rating (2 dp), total votes, min/max rating, total duration | no | A.L. Vijay 5 / 177 / 5.42 / 1,754 / 3.7 / 6.9 / 613 … Sam Liu 4 / 260 / 6.23 / 28,557 | ✔ on all 9 rows and every column except **avg rating on 2 rows**: Soderbergh 6.47 against gold 6.48, Sam Liu 6.22 against 6.23 [q4:local152_top9_directors]. Both true means end in 5 at the third decimal (6.475, 6.225), and SQLite's `round` on the binary double goes down where the gold engine went up |
| local230 | top 3 genres by movies rated > 8, then top 4 directors by > 8 films in them | no | Anthony Russo 2, James Mangold 2, Joe Russo 2, Marianne Elliott 2 | ✔ [q4:local230_top_genres: Drama 175, Action 46, Comedy 44; q4:local230_top_directors] |

Both questions need `date_published`, `duration` and the ratings exactly, and a director's movie set from `director_mapping`.

## 1. Inventory, keys, joins

No PK or FK is declared. Measured [q1:key_uniqueness, q1:full_row_dups, q1:fk_orphans]:

| Table | Rows | Key | Kind |
|---|---:|---|---|
| movies | 7,997 | id (tt…) | master + release date |
| ratings | 7,997 | movie_id, 1:1 with movies | snapshot of IMDb rating |
| genre | 14,662 | (movie_id, genre); 13 values; 1–3 per movie | tag link |
| director_mapping | 3,867 | (movie_id, name_id) | credit link |
| role_mapping | 15,615 | (movie_id, name_id); category is actor or actress, never both | credit link |
| names | 25,735 | id (nm…) | person master |
| ERD | 25 | (table, column) | static documentation |

Joins:
- All movie_id and name_id references resolve, with 0 orphans [q1:fk_orphans].
- **`names.known_for_movies` is not a reference.** It holds 1–4 comma-separated ids, and 2,261 of the 10,509 non-NULL values point outside the catalog. It is one of the person's credits here in only 6,215 [q1:known_for_shape, q1:known_for_in_credits].
- Every movie has a rating and a genre [q1:coverage].
- **Credits are sparse.** 4,240 movies have no role, 4,420 have no director, and 4,230 have neither [q1:coverage, q3:role_movies_vs_director_movies]. The share with credits is flat:
  - by year: 2017 48%, 2018 48%, 2019 44% with roles [q3:credited_movies_by_year];
  - by vote band: 47–48% in each [q3:credited_movies_by_votes].

  So the credits are an unbiased **sample of movies**, probably a course-size cut.
- **9,590 names have no credit at all** [q1:coverage]. 796 of them have a known-for value, and 668 of those point into the catalog [q3:names_unused_with_known_for].
- 69 people both act and direct [q1:coverage].
- No table is a copy or a pure function of another. There are no duplicate rows [q1:full_row_dups].
- **Derived column:** `movies.year` = year of `date_published`, 7,997 of 7,997 [q2:year_vs_published_year].

## 2. Event catalogue

Times:
- **Natural:** `date_published`, the movie's publication date. All values are midnight `YYYY-MM-DD 00:00:00` [q2:date_published_shape]. It is a real, day-level time.
- **R1, rule:** credits and genre tags are stamped at their movie's `date_published`. There is no other time for them.
- **R2, rule:** a person is created at their earliest credited `date_published`. The 9,590 uncredited people, and the ERD rows, are created at the catalog start, 2017-01-01.
- **R3, snapshot, rule:** **N = 2020-01-01**, just after the last publication (2019-12-27). These are snapshot columns at N:
  - ratings (avg, median, votes), observed at the scrape;
  - `worlwide_gross_income`, a lifetime total;
  - `known_for_movies`, IMDb's computed list, which can name later films.

| # | Event | Owner (ord) | Time | Attributes | Source rows | Count |
|---|---|---|---|---|---|---:|
| E1 | `movie_released` (movies' creation event) | movie | `date_published` (natural) | ext_id, title, duration, country (opt), languages (opt), production_company (opt) | movies | 7,997 |
| E2 | `movie_genre_tagged` | movie | R1 | movie_id, genre (cat, 13) | genre | 14,662 |
| E3 | `director_credited` | movie | R1 | movie_id, person_id | director_mapping | 3,867 |
| E4 | `cast_credited` | movie | R1 | movie_id, person_id, category (cat actor/actress) | role_mapping | 15,615 |
| E5 | `movie_rated` | movie | N | movie_id, avg_rating (f64), total_votes (i64), median_rating (f64) | ratings | 7,997 |
| E6 | `movies_snapshot` | movie | N | worldwide_gross_usd (i64) | movies where gross is not NULL | 4,273 |
| E7 | `names_snapshot` | name | N | known_for_movies (text) | names where it is not NULL | 10,509 |

Entities:
- **movies** 7,997, created by E1.
- **names** 25,735, via `names_created` at R2: ext_id, name, height (opt i32 cm), date_of_birth (opt text).
- **erd** 25, via `erd_created` at 2017-01-01: ext_id = `table.column`, plus the 11 `Unnamed` cells verbatim.

**Total log: 33,757 creation events + 7,997 E5 + 4,273 E6 + 10,509 E7 + 34,144 E2–E4 = 90,680.**

**Event-shapedness:** partly imposed. Releases have a real date. Credits and tags are attached to them by rule, and ratings are a snapshot.

What is **not** an entity or event, and why:
- **Ratings** are not an entity. They are 1:1 with a movie but observed at the scrape, so they form one dated *report* event (E5) at N. Putting them on E1 would leak the future.
- **Genres** are not an entity. They are a 13-value category, and a lookup entity adds nothing.
- **date_of_birth is not a creation time.** It runs back to 1872 and is partly year-only. It is an attribute.
- **ERD** is an entity at a rule time, not derived. It is a spreadsheet layout, so its cell positions cannot be generated from the schema. It has no time and no use, so it sits at the catalog start.

## 3. Rebuild rules and blockers to an exact round trip

1. **`date_published` is a mixed column.** It is declared `TIMESTAMP`, which has NUMERIC affinity, but all 7,997 values are text [q1:typeof_columns]. The results contract types NUMERIC as float64, so this column is **mixed → string**, and must be listed as `mixed` in `dataset.toml`. `build.sql` must output `strftime(event_time, '%Y-%m-%d 00:00:00')`.
2. **`year`** = `CAST(strftime(event_time, '%Y') AS INTEGER)`, 7,997 of 7,997.
3. **Gross income** is text `'$ ' || digits` on all 4,273 non-NULL values, with no other currency, no leading zeros and no non-digits; it runs from 37 to 2,797,800,564 [q2:gross_prefixes, q2:gross_digits_only]. Carry it as integer dollars and rebuild it as `'$ ' || n`. Verbatim text is the fallback.
4. **Lists stay text.** `country`, `languages` and `production_company` are ', '-joined lists. There is never a comma without a space and never padding [q2:list_separator_shape, q2:comma_no_space]. Carry them verbatim, without splitting.
5. **Floats.** `avg_rating` sits on a 0.1 grid (0 off-grid). `median_rating` is REAL with 74 half-values (2.5 … 9.5). `height` is REAL and always whole (76–201) [q2:ratings_shapes, q2:height_stats]. Carry the ratings as `f64`, and height as an integer, rebuilt `::DOUBLE`.
6. **`date_of_birth`** is text with three shapes: 11,399 `YYYY-MM-DD` (all valid dates), 904 `YYYY`, and 1 `'October 29'`; 13,431 are NULL [q3:dob_formats, q3:dob_other_samples, q3:dob_invalid_dates]. Carry it as opt text, not as a date.
7. **NULLs and empties.** There is no `''` anywhere. NULLs [q1:empties]:
   - country 20, gross 3,724, languages 198, production_company 528;
   - height 17,335, dob 13,431, known_for 15,226.
8. **ERD.** The 5 text columns (table, column, Unnamed: 6, 9, 12) are carried verbatim. `Unnamed: 2`, 3, 4, 5, 7, 8, 10 and 11 are REAL and NULL in all 25 rows [q3:erd_real_columns_nonnull]. They rebuild as `NULL::DOUBLE`.
9. **Row order does not matter** for a multiset compare, and no table has an index column. `ratings` and the link tables are sorted by movie_id; `movies` is sorted by year, then mostly by id [q1:rowid_orders, q1:movies_rowid_order_by_year].
10. **Rows without time:** credits, tags, names and ERD rows get times from R1 and R2. Ratings, gross and known-for get N (R3).

**Verdict:** an exact round trip is feasible. The only real work is the TIMESTAMP-declared text column, which is mixed by the contract's affinity rule.

## 4. Measured quirks

- **Friday releases:** Friday 3,693 (46%), Thursday 1,652, Wednesday 978, Tuesday 698, Saturday 425, Monday 310, Sunday 241 [q2:published_weekday]. 598 movies fall on day 1 of a month, about 2.3 times the uniform share: these are likely month-precision dates [q2:published_day1].
- **2019 is truncated:** 2019-11 has 97 releases and 2019-12 has 16, against about 200 a month before [q2:published_per_month].
- **Duration** runs 41–808 minutes, mean 103.9; 24 are under 60 and 1 is over 240 [q2:duration_stats].
- **Genre rows are in reverse-alphabetical order within a movie** (6,664 of 6,665 pairs) [q3:genre_order_desc]. Credits list actors before actresses (8,863 of 11,858 pairs never go actress → actor) [q3:roles_actor_first]. These are export fingerprints, irrelevant to a multiset compare.
- **Child actors:** 24 people were born in 2005 or later; the youngest is Marta Timofeeva, 2009-08-08 [q3:dob_late].
- **Names:** 57 names are shared by more than one id [q3:name_dups]. 1,964 names and 491 titles are non-ASCII [q2:nonascii]. 60 titles are shared by 125 movies [q2:title_dups].
- **avg vs median rating:** the average is below the median on 6,192 movies and above it on 1,322 [q2:avg_vs_median]. That is a left-skewed vote distribution.
- **Re-release dates** (§0): on the 238 movies shared with Db-IMDB, 39 show a classic film's year as 2017–2019 [x_overlap].

## 5. Distributions to fit (stage 2)

| Quantity | Value |
|---|---|
| releases per month | 2017–2018: 167–327, peak Sep–Oct, dip Jun–Jul; 2019 declining (truncated) [q2:published_per_month] |
| weekday | Friday 46%, Thursday 21% [q2:published_weekday] |
| genres per movie | 1: 3,289, 2: 2,751, 3: 1,957; Drama 4,285, Comedy 2,412, Thriller 1,484 … Others 100 [q2:genres_per_movie, q2:genre_values] |
| credited movies | 47% with roles; given roles, 4 roles on 90% [q2:roles_per_movie] |
| directors per movie | 1: 3,363, 2: 177, 3: 21, 4: 4, 5: 1, 6: 11 [q2:directors_per_movie] |
| actor / actress | 9,362 / 6,253 [q2:category_values] |
| avg rating | 1.0–10.0, mean 5.75 (2017), 5.76 (2018), 5.96 (2019) [q2:votes_by_year] |
| total votes | p5 115, p25 206, p50 471, p75 1,623, p95 23,886, max 725,138 (floor 100) [q2:votes_quantiles] |
| median rating | modes 7 (2,235) and 6 (1,963) [q2:median_hist] |
| country | USA 2,260, India 1,007, UK 387 …; 6,422 single-country [q2:country_top, q2:country_multi] |
| gross | present on 4,273 of 7,997 (53%) |

## 6. simkit mapping sketch

```python
p.entity("names", key="name_id", cols={"ext_id": text(), "name": text(), "height": opt(i32()), "date_of_birth": opt(text()),
         "known_for_movies": opt(text())})                     # known_for marked snapshot -> names_snapshot at N
p.entity("movies", key="movie_id", cols={"ext_id": text(), "title": text(), "duration": i32(), "country": opt(text()),
         "languages": opt(text()), "production_company": opt(text()), "worldwide_gross_usd": opt(i64())})  # gross: snapshot
p.entity("erd", key="erd_id", cols={"ext_id": text(), "table": text(), "column": text(), "u6": opt(text()), "u9": opt(text()), "u12": opt(text())})
p.event("movie_genre_tagged", cols={"movie_id": ref("movies"), "genre": cat("Drama", "Comedy", ..., "Others")})
p.event("director_credited", cols={"movie_id": ref("movies"), "person_id": ref("names")})
p.event("cast_credited", cols={"movie_id": ref("movies"), "person_id": ref("names"), "category": cat("actor", "actress")})
p.event("movie_rated", cols={"movie_id": ref("movies"), "avg_rating": f64(), "total_votes": i64(), "median_rating": f64()})
```

Ingest:
- movies: `created_at = iso_time(date_published, '%Y-%m-%d %H:%M:%S')`, ORDER BY date_published, id.
- `movie_genre_tagged`, `director_credited` and `cast_credited`: owner=movie_id, at the movie's time, ORDER BY movie_id and then genre / name_id. They sort after creation because the entity event comes first.
- names: `created_at` = `min(date_published)` over their credits, else `'2017-01-01'`.
- `movie_rated owner=movie_id`, at N, ORDER BY movie_id.

Views:
- `movies.year` and `date_published` from `created_at` (§3.1–2).
- gross: `'$ ' || n`.
- height: `::DOUBLE`.
- ERD: the 8 all-NULL REAL columns as `NULL::DOUBLE`.

Stage-2 owners:
- a **movie** arrival process with day-level times (Friday-heavy, seasonal), drawing genres (1–3), country/language lists and duration;
- for about 47% of movies, a credit step: about 4 top-billed people (≈60% actor) and 1 director from a **names** pool;
- a single rating report at N, with votes from a heavy-tailed draw floored at 100.

About 91k events; no sample profile is needed.

## 7. Open questions and risks

- **N = 2020-01-01 is a rule.** The scrape date is unknown. Ratings and gross are post-hoc values, and must not be read as known at release.
- **Re-release dates.** `date_published` is not the original release for classics (39 of the 238 shared movies). A sim fitting "movie age vs rating" on this catalog would be wrong.
- **Credit sampling.** Credits cover about 47% of movies at random. Questions such as local152 run on the credited subset only. Reproduce this as a sampling step, not as missing data.
- **local152 rounding.** The 2 avg-rating cells at a half-cent tie differ from the gold CSV in the last digit. The saved query compares source with rebuilt, which agree, but anything compared with the gold CSV needs a tolerance of 0.01.
- **Provenance** (upGrad / IIIT-B RSVP case study) and licence are unverified.
- **`'October 29'`** in `date_of_birth` is a source error kept verbatim. Stage 2 should not generate it.

## Summary

- **Exact round trip:** yes. Every column is verbatim or rebuilt by a proven rule. `date_published` must be declared mixed (text in a TIMESTAMP/NUMERIC column).
- **Dataset name:** `imdb_movies`.
- **Size:** 7 event types (`movie_released`, `movie_genre_tagged`, `director_credited`, `cast_credited`, `movie_rated`, `movies_snapshot`, `names_snapshot`) and 3 entities (movies, names, erd). That is 90,680 log events.
- **Event-shaped:** partly imposed. Releases carry a real day-level date; credits and tags are stamped at release by rule; ratings, gross and known-for are snapshots at N.
- **Hardest blocker:** there are no times for credits, people or ratings, so N and the release-stamping rule are inventions. On the exactness side, it is the mixed `date_published` column; there is no structural blocker.
