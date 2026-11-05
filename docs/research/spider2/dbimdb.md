# Db-IMDB (Spider 2.0-lite): reverse-engineered event log

Source: `data/spider2/Db-IMDB.sqlite` (7.2 MB), opened read-only. `scripts/dbimdb/rq.py` copies the file into an in-memory SQLite and runs named blocks; the file itself is never written.

Every number below comes from one of these scripts:
- a named query in `scripts/dbimdb/q*.sql`;
- `p1_person_order.py` (how `Person` was generated), `p2_gold096.py` (local096 against its gold CSV);
- `x_overlap.py` (overlap with `imdb_movies`, shared with that report).

The raw outputs are in `scripts/dbimdb/out_*.txt`. A reference such as `[q2:fk_orphans]` means file `q2_keys_joins.sql`, block `-- name: fk_orphans`. Gold files are in `scripts/dbimdb/gold/`.

## 0. What this catalog is

- **Dataset.** A scrape of IMDb title and name pages, heavily weighted to Hindi cinema: 3,475 movies from 1931 to 2018, 2,989 of them in Hindi and 3,296 from India [q6:language_mix, q6:country_mix]. Ids are real IMDb ids (`tt` + 7 digits for all 3,475 movies, `nm…` for people) [q6:mid_shape]. Titles, ratings and vote counts are IMDb's at scrape time.
- **Origin.** Unverified. The 13-table shape (`Movie`, `Person`, `M_Cast`, `M_Director`, `M_Producer`, `M_Genre`, …) is a widely shared course database for SQL assignments, but a web search did not find a primary source. The evidence in the file:
  - It was written by **pandas `to_sql`**: every table has an `index` column equal to `rowid − 1`, with an `ix_<table>_index` index [q1:sqlite_master, q1:index_is_rowid_minus_1]. Link tables' `ID` equals `index` in every row [q1:link_id_equals_index].
  - Lookup ids are **pandas `factorize`** codes: `GID`, `LAID`, `CID` and `LID` are numbered in order of first use by `Movie.index`, 328/328, 32/32, 34/34 and 559/559 [q2:lookup_first_use_order].
  - `M_Location.LID` and `M_Country.CID` are REAL because they hold NaN (now NULL) for missing values: 1,626 and 5 rows [q1:typeof_columns].
  - The scraper kept the HTML's leading space in cast and producer ids and names (`' nm0000288'`, `' Christian Bale'`) [q1:padding_shapes].
- **Snapshot time.** No date is stored. On the 238 movies shared with `imdb_movies` (which runs to 2019-12-27), this file's vote count is lower on 237 and never higher [x_overlap]. So it was scraped earlier, after the last 2018 release.
- **Row counts** [q1:row_counts]: Movie 3,475; Genre 328; Language 32; Country 34; Location 559; M_Location, M_Country, M_Language, M_Genre and M_Director 3,475 each; Person 38,285; M_Producer 11,751; M_Cast 82,837. Total 154,676.
- **Licence.** Unstated. The content is IMDb's, whose terms allow personal, non-commercial use only. Fitting statistics is fine; redistributing rows needs a check.
- **Nature.** Real public data, scraped, not anonymised and not generated. The tables were reshaped by a student-style pandas script, with its fingerprints (§4).
- **Overlap with `imdb_movies`** [x_overlap]. They are two different scrapes:
  - 238 movie ids are shared (6.8% of 3,475 here, 3.0% of 7,997 there).
  - On those movies, titles match on 237, years on 199, ratings on 74 and vote counts on 1.
  - 1,771 person ids are shared, 1,732 of them with the same name.
  - Only 400 cast pairs are shared (6,533 here against 414 there on those movies).

  There is no copy to reuse, so they are **two datasets**.

## 0.1 How Spider 2.0 uses it

Five questions use db `Db-IMDB`. Only local099 has gold SQL; all five have exec_result CSVs. Three have alternative answers (`_b`, `_c`).

| id | asks | gold SQL? | gold value | reproduced |
|---|---|---|---|---|
| local096 | per year (last 4 chars of `year`): movies, and % whose cast is all `Female` (Male or NULL gender counts as non-female) | no | 78 years; non-zero only for 1939 50.00, 1999 1.52, 2000 1.56, 2018 0.96 | ✔ all 78 rows [p2_gold096, q5:local096_female_only] |
| local097 | the 10-year window [y, y+9] with the most movies, over the years present | no | 2008, 1,205 | ✔ [q5:local097_decade] |
| local098 | actors with no 4-year span without a credit, over their career | no | `_a` 29,066, `_b` 29,065, `_c` 28,698 | `_c` ✔: 28,698 cast PIDs whose consecutive credit years never differ by more than 4 [q5:local098_no_gap_over_3]. `_a` and `_b` not reproduced |
| local099 | actors with more films with Yash Chopra than with any other director | yes | `_a` 266, `_b` 107 | the gold SQL gives 107 (`_b`) [q5:local099_gold_sql]; "≥" gives 245 [q5:local099_ge_variant]. 266 not reproduced |
| local100 | actors with "Shahrukh number" 2 | no | 25,698 | ✔ with `Shah Rukh Khan` = nm0451321 [q5:local100_shahrukh_2] |

Every question joins credits to `Person` through `TRIM(PID)`, and three parse `year` with `substr(year, -4)`. So the leading spaces and the roman-numeral year prefixes (§3) must survive the round trip byte for byte.

## 1. Inventory, keys, joins

No PK or FK is declared. The keys below are measured [q1:key_uniqueness, q2:fk_orphans].

| Table | Rows | Key | Kind |
|---|---:|---|---|
| Movie | 3,475 | MID (unique, unpadded) | master: title, year label, rating snapshot |
| Person | 38,285 | **none**: 37,565 distinct PIDs, 719 PIDs twice, 1 all-NULL row | **derived** from credits (§3.1) |
| M_Cast | 82,837 | (MID, PID), unique; 2 NULL PIDs | credit link, in billing order |
| M_Producer | 11,751 | (MID, PID), unique; 21 NULL PIDs | credit link |
| M_Director | 3,475 | MID (exactly one director per movie) | 1:1 movie attribute |
| M_Genre, M_Language | 3,475 each | MID; row i is Movie row i | 1:1 movie attribute |
| M_Country, M_Location | 3,475 each | MID; row i is Movie row i; CID NULL 5, LID NULL 1,626 | 1:1 movie attribute (optional) |
| Genre | 328 | GID = index; Name is a **genre combination** ("Action, Crime, Drama") | lookup |
| Language, Country | 32, 34 | LAID / CID = index | lookup |
| Location | 559 | LID = index; one filming place per movie, "City, Region, Country" | lookup |

Joins:
- **Raw credit PIDs never join `Person`.** M_Cast's raw PIDs miss on 82,835 of 82,835 non-NULL rows; after `trim()` the misses are 0. M_Producer is the same: 0 orphans after trim. M_Director PIDs are unpadded and join directly [q2:fk_orphans].
- Every MID in every link table resolves to Movie. Every GID, LAID, CID and LID resolves to its lookup [q2:fk_orphans].
- All five 1-per-movie link tables line up with Movie row for row: `index`, MID and `ID = index` agree in 3,475 of 3,475 [q4:one_per_movie_link_tables]. They are one movie row split into five tables.
- Every lookup row is used, and every person has at least one credit [q2:lookup_unused, q2:person_coverage].
- Every movie has at least 1 cast credit, 1 producer and 1 director [q2:movies_without].
- Roles overlap: of the 37,565 people, 32,127 are cast, 5,436 producers and 1,464 directors. 392 are cast and director, 525 producer and director [q2:person_coverage]. The director is credited in their own cast on 299 movies [q2:director_is_also_cast].
- **Derived:** `Person` in full (§3.1); the `index`/`ID` columns of every table; lookup ids (first-use codes).

## 2. Event catalogue

The catalogue holds **no time column except `Movie.year`**, which is a year with an optional IMDb disambiguator ("I 2009"). Every time below comes from a rule:

- **R1, release.** A movie happens at **January 1 of its year** (`substr(year, -4)`), 00:00 UTC. It is the only time the source supports, and it is coarser than any real release date.
- **R2, credits.** Cast and producer credits are stamped at their movie's R1 time. A credit is part of the release; nothing in the source dates it otherwise.
- **R3, entities.** A person is created at their earliest credit's R1 time. Each Genre, Language, Country and Location row is created at the R1 time of the first movie that uses it, its "first use" (1931–2018 for genres) [q6:lookup_first_use_year].
- **R4, snapshot.** **N = 2019-01-01** (after the last 2018 release, before `imdb_movies`' later scrape). `rating` and `num_votes` are IMDb's values on the scrape day, so they are snapshot columns at N.

| # | Event | Owner (ord) | Time | Attributes | Source rows | Count |
|---|---|---|---|---|---|---:|
| E1 | `movie_released` (movies' creation event) | movie (ord = src_index) | R1 | ext_id MID, src_index (Movie.index), title, disambig (opt: I…XVII), genre_id, language_id, country_id (opt), location_id (opt), director_id (ref persons) | Movie + the five 1:1 link tables | 3,475 |
| E2 | `cast_credited` | movie (ord = billing) | R2 | movie_id, person_id (opt ref; NULL on 2 rows), billing (1-based position in the movie) | M_Cast | 82,837 |
| E3 | `producer_credited` | movie (ord = position) | R2 | movie_id, person_id (opt ref; NULL on 21), position | M_Producer | 11,751 |
| E4 | `movies_snapshot` | movie | N | rating (f64), num_votes (i64) | Movie | 3,475 |

Entities and their creation events: movies 3,475 (E1); persons 37,565 (`persons_created`, R3: ext_id PID, name trimmed, gender opt cat Male/Female); genres 328, languages 32, countries 34, locations 559 (`<entity>_created`, R3; ext_id the source id, name verbatim).

**Total log: 41,993 creation events + 3,475 snapshot events + 94,588 credit events = 140,056.**

**Event-shapedness:** mostly imposed. The only real event is a release *year*. Credits are attached to it by rule, and ratings are a snapshot.

What is **not** an entity or event, and why:
- **Person rows.** `Person` has no key: 719 PIDs appear twice, with names differing only by a leading space, and one row is all NULL [q2:person_dup_exact, q2:person_null_row]. It is a pure function of the credit stream (§3.1). So the entity is the **distinct person** (37,565), and the table is derived.
- **M_Director, M_Genre, M_Language, M_Country, M_Location.** These are not link entities. Each is exactly one row per movie, aligned row for row [q4:one_per_movie_link_tables], so they become E1 attributes and are derived in `build.sql`.
- **The rating.** It is not an event at a real time: there is a single value, observed at the scrape.
- **Genre.** It is not a set of genres but a *combination* string: 16 single, 77 double and 235 triple combinations [q6:genre_combo_sizes]. The pandas factorize turned each distinct string into an id. Splitting it into tags would lose the exact `Name` bytes for no gain.

## 3. Rebuild rules and blockers to an exact round trip

1. **`Person` is derived, and the rule is proven** [q4:person_rebuilt_from_credits: 38,285 rebuilt rows, 0 differing both ways; p1 H6 True]. The generator:
   - `Person` = the first-seen distinct trimmed PIDs over M_Cast rows, then M_Producer rows, with NULL kept as one value.
     - The name has **one leading space**.
     - The NULL value lands at index 30,439: the first NULL cast PID sits at M_Cast index 77,014 [p1].
   - Then come the first-seen distinct directors over M_Director, with the name **unpadded**.
   - A full-row `drop_duplicates` keeps both copies of the 719 people who direct and also act or produce, because ' Name' ≠ 'Name' [q3:block_dup_pairs: 376 cast+director, 343 producer+director; p1].
   - Gender is per person and identical across copies (719 of 719) [q2:person_dup_exact].
   - In DuckDB: `row_number() OVER (ORDER BY first position) − 1`, with M_Producer positions offset after M_Cast, and director indexes offset by the cast+producer count.
2. **Leading spaces.** M_Cast.PID and M_Producer.PID are `' ' || pid` on every non-NULL row (82,835 and 11,730). M_Director.PID is unpadded [q4:credit_pid_padding_rule]. The view adds the space. The entity's `ext_id` is the trimmed PID, so refs resolve.
3. **Row numbers.** Each `index` must be rebuilt, because it is a column:
   - Movie.index is **not** a function of anything: year order breaks 1,694 times in 3,474 pairs [q6:movie_order_vs_year]. Carry it as `src_index` on E1.
   - M_Cast.index = `row_number() OVER (ORDER BY movie src_index, billing) − 1`, proven 82,837 of 82,837 [q4:cast_index_from_billing]. M_Producer is the same, 11,751 of 11,751 [q4:producer_index_from_position]. `ID = index` everywhere.
   - The five 1:1 tables take index = ID = the movie's src_index. Lookup tables take index = their id.
4. **Year text.** `year` = `[roman || ' '] || 4-digit year` for 3,475 of 3,475, with prefixes I…XVII only [q4:year_split_rule]. Carry `disambig` (opt text) and rebuild from the event time.
5. **REAL ids.** M_Location.LID and M_Country.CID are REAL, whole numbers, and NULL when missing (1,849 of 1,849 and 3,470 of 3,470 are whole) [q4:real_ids_whole]. Rebuild them as `CAST(id AS DOUBLE)`.
6. **Padded Genre names.** 327 of 328 names end in exactly 12 spaces; the one exception is the literal text `'Null'` (GID 309, used by 7 movies) [q4:genre_padding_rule, q6:null_genre_use]. Carry Name verbatim as text. It is byte-exact by contract, so no rule is needed. `'Null'` is text, not NULL.
7. **Floats.** `rating` is REAL on a 0.1 grid (0 off-grid of 3,475) [q1:rating_shapes]. `f64` verbatim is exact.
8. **NULLs** [q1:nulls_and_empties]: Person.Gender 8,795 (it travels on persons as opt; the NULL row has NULL everything); 2 + 21 NULL credit PIDs; CID 5; LID 1,626. There is no `''` in any checked column.
9. **Rows without time:** all of them. Every time is from rules R1–R4.

**Verdict:** an exact round trip is feasible, with caveats. Nothing is lossy. The difficulty is that `Person` must be rebuilt by an order-sensitive first-seen rule, which is proven in SQLite and must be re-proven in DuckDB.

## 4. Measured quirks

- **Generator fingerprints:** pandas `index` and `ID` columns; factorized lookup ids; NaN-to-REAL ids; HTML leading spaces; the all-NULL Person row; the duplicate directors (§3.1).
- **Credit tables are sorted by Movie.index, then credit order** (82,836 and 11,750 non-decreasing pairs) [q2:credit_order_within_movie]. The cast credit order is IMDb's billing order (Mowgli: Bale, Blanchett, Cumberbatch…).
- **Duplicate person names:** 1,268 trimmed names are shared by more than one PID [q2:person_name_dups]. Anything keyed on name is ambiguous; Yash Chopra is safe (1 PID, 2 rows) [q5:yash_chopra_pids].
- **Gender NULL** for 2,871 of 32,127 cast people [q3:cast_gender_coverage]. Among Person rows it is NULL for 1,309 of 1,464 directors and 4,757 of 6,381 block-B rows [q3:gender_by_block]: the scraper only sexed people it met in a cast list.
- **Titles:** 123 titles are shared by 254 movies, but no title repeats within one year [q6:title_dups, q6:title_year_dups]. The roman prefix is IMDb's global disambiguator, not a local one: 13 of 117 prefixed movies share a title within this catalog [q6:year_prefix_vs_title_dups].
- **Location is missing** on 1,626 movies, evenly across eras: 666 of 1,397 before 2000, 960 of 2,078 after [q6:location_null_by_era].
- **Movie order is scrape order:** popular 2018 Hollywood titles first (Mowgli, Ocean's Eight, Tomb Raider), then mixed Hindi titles [q6:movie_index_head_years].
- **Non-ASCII text:** 4 titles and 223 person names [q6:title_samples_nonascii, q6:person_name_nonascii]. Keep them byte-exact.

## 5. Distributions to fit (stage 2)

| Quantity | Value |
|---|---|
| releases per decade | 1930s 6, 1940s 12, 1950s 71, 1960s 148, 1970s 254, 1980s 350, 1990s 556, 2000s 986, 2010s 1,092; 2010–2018 flat at 104–136 a year [q6:movies_per_decade, q6:movies_per_year_recent] |
| rating | integer part 1: 9, 2: 76, 3: 235, 4: 455, 5: 716, 6: 894, 7: 896, 8: 181, 9: 13; mean 6.93 before 1990, 5.67 1990–2009, 5.87 2010+ [q6:rating_hist, q6:rating_vs_votes_by_year] |
| num_votes | p5 59, p25 120, p50 388, p75 1,852, p95 15,607, max 1,137,529 (heavy tail; min 51) [q6:votes_quantiles] |
| cast per movie | 1–5: 94, 6–10: 402, 11–20: 1,365, 21–40: 1,240, 41–80: 311, 81+: 63 (mean 23.8, max 238) [q6:cast_size_hist, q2:cast_per_movie] |
| producers per movie | 1: 1,110, 2: 728, 3: 451, 4: 346, 5: 226, then a geometric-like tail [q6:producers_per_movie] |
| films per actor | 1: 24,388, 2–3: 4,373, 4–10: 2,226, 11–30: 770, 31–100: 327, 101+: 43 (max: Anupam Kher, 243) [q6:credits_per_actor, q6:top_actors] |
| films per director | 1: 914, 2: 220, 3: 96, 4: 56, 5: 53, … [q6:films_per_director] |
| cast gender (credit rows) | Male 55,214, Female 23,028, NULL 4,595 [q6:cast_gender_mix_rows] |
| language | Hindi 2,989, English 151, Tamil 99, Telugu 93 … [q6:language_mix] |
| genre combination | Drama 342, Action-Crime-Drama 218, Drama-Romance 206 … [q6:movies_per_genre_combo_top] |
| person arrivals (first credit decade) | grows from 111 (1930s) to 16,978 (2010s) [q6:person_min_year_vs_movie_count] |

## 6. simkit mapping sketch

```python
for name in ("genres", "languages", "countries", "locations"):
    p.entity(name, key=f"{name}_id", cols={"ext_id": i64(), "name": text()})          # ext_id = GID/LAID/CID/LID
p.entity("persons", key="person_id", cols={"ext_id": text(), "name": text(), "gender": opt(cat("Male", "Female"))})
p.entity("movies", key="movie_id", cols={"ext_id": text(), "src_index": i64(), "title": text(), "disambig": opt(text()),
         "genre_id": ref("genres"), "language_id": ref("languages"), "country_id": opt(ref("countries")),
         "location_id": opt(ref("locations")), "director_id": ref("persons"),
         "rating": f64(), "num_votes": i64()})   # created_at = R1; rating, num_votes marked snapshot columns -> movies_snapshot at N
p.event("cast_credited", cols={"movie_id": ref("movies"), "person_id": opt(ref("persons")), "billing": i32()})
p.event("producer_credited", cols={"movie_id": ref("movies"), "person_id": opt(ref("persons")), "position": i32()})
```

Ingest:
- Times: `iso_time(substr(year, -4) || '-01-01', '%Y-%m-%d')`.
- Entities: movies `created_at` = R1, ORDER BY index. Persons and lookups use R3 via `min()` over their credits or uses.
- `cast_credited owner=movie_id ord=billing`, with billing = `row_number() OVER (PARTITION BY MID ORDER BY index)`, ORDER BY index. `producer_credited` is the same.
- Person ids are entered as `trim(PID)`.

Views (`build.sql`):
- Movie: from E1 + E4, with `year = coalesce(disambig || ' ', '') || strftime(created_at, '%Y')`.
- M_Genre, M_Language, M_Country, M_Location and M_Director: from E1, with `index = ID = src_index`, CID and LID `::DOUBLE`.
- M_Cast and M_Producer: `index = ID = row_number() OVER (ORDER BY movie src_index, billing) − 1`, `PID = ' ' || ext_id`.
- Lookups: `index = id`.
- Person: the first-seen rule of §3.1.

Stage-2 owners: a **movie** shard per release year that draws the genre combination, language and cast size, and fills the cast from a **person pool** with preferential attachment (the film-count tail above). It has no request/reply: everything happens at release. About 140k events, no sample profile needed.

## 7. Open questions and risks

- **N and the release times are pure rules.** Jan 1 of the year and N = 2019-01-01 are not data. Stage 2 must not fit within-year timing, or rating dynamics, to this log.
- **Origin and licence** are unverified (IMDb content, an unknown scraper). Check before redistributing rows.
- **Gold alternatives:** local098 `_a`/`_b` (29,066 / 29,065) and local099 `_a` (266) are not reproduced. Their reading of the question is unknown, and the saved queries should pick the reproduced variant.
- **The DuckDB first-seen rule** (§3.1) depends on carrying `src_index` and billing exactly. Add a dedicated compare for `Person`, because a slip would show only as an index shift on ~7k rows.
- **NULL-person credits** (2 cast, 21 producer) must stay as events with a NULL ref, since `Person`'s all-NULL row depends on the first of them.

## Summary

- **Exact round trip:** yes, with caveats. `Person`, the indexes, the padding and the year labels all rebuild by rules proven at 0 differing rows. The only times are rules.
- **Dataset name:** `dbimdb`.
- **Size:** 4 event types (`movie_released`, `cast_credited`, `producer_credited`, `movies_snapshot`) and 6 entities (movies, persons, genres, languages, countries, locations). That is 140,056 log events.
- **Event-shaped:** mostly imposed. The only time is a release year; credits ride on it and ratings are a snapshot at N.
- **Hardest blocker:** `Person` is a keyless, order-dependent first-seen dump of the credit stream, with 719 space-variant duplicates and a NULL row. It must be derived exactly, and depends on carrying Movie.index and billing order.
