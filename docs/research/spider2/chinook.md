# Chinook (Spider 2.0-lite): reverse-engineered event log

Source: `data/spider2/chinook.sqlite` (864 KB), opened read-only. `scripts/chinook/rq.py` copies the file into an in-memory SQLite and runs named blocks; the file itself is never written. Every number below comes from a named query in `scripts/chinook/q*.sql` or from `c5_upstream.py`, and the raw outputs are in `scripts/chinook/out_*.txt`. A reference such as `[q2:total_vs_lines_float]` means file `q2_keys_totals.sql`, block `-- name: total_vs_lines_float`. Gold answer CSVs are in `scripts/chinook/gold/`.

## 0. What this catalog is

- **Dataset.** This is the **Chinook sample database** by Luis Rocha (`lerocha/chinook-database`), in the **sqlitetutorial.net `chinook.db` packaging**:
  - The table names are plural snake_case (`albums`, `invoice_items`, `media_types`, `playlist_track`). Upstream uses singular PascalCase (`Album`, `InvoiceLine`, `MediaType`, `PlaylistTrack`). The columns and the bracket-quoted DDL with `AUTOINCREMENT` and the `IFK_*` indexes are upstream's.
  - The invoice dates run **2009-01-01 to 2013-12-22**. That is the date era of Chinook ≤ 1.4.x. Upstream master (v1.4.5, 2024) shifted every invoice by exactly **+12 years** (2021–2025). Against master: 412 of 412 invoices have the same customer and total, and the same month, day and time with the year +12; 2,240 of 2,240 invoice lines are identical [c5_upstream].
- **How it was generated.** The upstream README says:
  - "Media related data was created using real data from an iTunes Library".
  - Customers and employees were "manually created using fictitious names".
  - "Sales information is auto generated using random data for a four year period".

  The data spans five calendar years (2009–2013), and its generator is **deterministic**, not random (§4): a fixed cycle of 7 invoice sizes, Fibonacci-like date gaps, and arithmetic walks over customers and tracks.
- **Row counts** [q1:row_counts]: artists 275, albums 347, tracks 3,503, genres 25, media_types 5, playlists 18, playlist_track 8,715, employees 8, customers 59, invoices 412, invoice_items 2,240. Total 15,607.
- **System tables.** `sqlite_sequence` holds one row per AUTOINCREMENT table (10), and each `seq` equals that table's max id: 2,240 for invoice_items, 412 for invoices, and so on [q1:seq_vs_max]. `sqlite_stat1` holds 15 ANALYZE rows [q1:system_tables]. Neither is source data.
- **Licence.** Upstream `LICENSE.md` is the **MIT licence**, "Copyright (c) 2008-2024 Luis Rocha". sqlitetutorial.net states no separate licence. Spider 2.0's repository is MIT.
- **Nature.** The catalog is real metadata (track names, composers, durations, byte sizes) and the sales are **generated**.

## 0.1 How Spider 2.0 uses it

Three questions use db `chinook`. No gold SQL exists under `evaluation_suite/gold/sql` for any of them; exec_result CSVs exist for all three.

| id | analysis | gold SQL? | gold value | reproduced |
|---|---|---|---|---|
| local054 | customers who spent < $1 on albums by the best-selling artist | no (CSV only) | Edward, Ladislav, Eduardo, Hugh, Stanisław, each 0.99 | ✔ The best artist is Iron Maiden (ArtistId 90, 138.60 over 140 lines) [q4:local054_best_artist_under_1, q4:local054_top_artists] |
| local055 | top and bottom artist by sales (ties alphabetical); \|avg spend of buyers of top − avg of bottom\| | no (CSVs `_a`, `_b`) | `_a` 5.133333…, `_b` 4.143333… | ✔ both. `_b`: rank only artists with sales. Bottom = "Academy of St. Martin in the Fields & Sir Neville Marriner" (0.99), diff 4.143333 [q4:local055_reading_a]. `_a`: rank all 275 artists. Bottom = "A Cor Do Som" with 0 sales (110 artists have 0), so avg 0 and diff 5.133333 [q4:local055_reading_b] |
| local198 | median of total sales per country, over countries with > 4 customers | no (CSV only) | 249.53 | ✔ USA 523.06, Canada 303.96, France 195.10, Brazil 190.10, so the median is (195.10 + 303.96)/2. As a float sum this is 249.52999999999997 [q4:local198_median_country_sales]. The saved query must compare with the 1e-9 tolerance |

All three questions read only invoices, invoice_items, tracks, albums, artists and customers.

## 1. Inventory, keys, joins

Every PK is declared and dense from 1 to n (`playlist_track` has the composite PK). All 11 declared FKs resolve at 100%, with 0 orphans [q1:ids_dense, q2:fk_orphans].

| Table | Rows | Key | Kind |
|---|---:|---|---|
| genres | 25 | GenreId | lookup |
| media_types | 5 | MediaTypeId | lookup |
| artists | 275 | ArtistId | catalog |
| albums | 347 | AlbumId → ArtistId | catalog |
| tracks | 3,503 | TrackId → AlbumId, GenreId, MediaTypeId | catalog (price, duration, size) |
| playlists | 18 | PlaylistId | catalog |
| playlist_track | 8,715 | (PlaylistId, TrackId) | link table |
| employees | 8 | EmployeeId → ReportsTo | org chart (1 root, depth 3) |
| customers | 59 | CustomerId → SupportRepId | party |
| invoices | 412 | InvoiceId → CustomerId | activity (1 date) |
| invoice_items | 2,240 | InvoiceLineId → InvoiceId, TrackId | activity (no own time) |

Coverage the other way [q2:parents_without_children]:
- 71 artists have no album.
- 1,519 of 3,503 tracks were never sold; 1,728 were sold once and 256 twice [q3:tracks_sold_distribution]. No track appears twice in one invoice.
- 4 playlists are empty (Movies 2 and 7, Audiobooks 4 and 6).
- Every customer has invoices: 58 have 7 and customer 59 has 6 [q2:invoices_per_customer].
- Only employees 3, 4 and 5 (the Sales Support Agents) support customers: 21, 20 and 18 [q2:support_rep_load].

Row order: invoice_items rowid order is non-decreasing in InvoiceId (2,239 of 2,239 pairs) [q3:line_id_order]. playlist_track is *not* in PK order (8,302 of 8,714 increasing pairs) [q2:playlist_track_rowid_order]. The comparison is a multiset, so that is harmless.

## 2. Event catalog

Only invoices carry a time. Everything else is a catalog or a party, so this is a small log over large lookup entities.

| # | Event | Owner | Time | Attributes | Source rows | Count |
|---|---|---|---|---|---|---:|
| E1 | `invoice_issued` | customer | `InvoiceDate` (always 00:00:00) | invoice_id (InvoiceId verbatim), customer_id | invoices | 412 |
| E2 | `invoice_line_added` | customer (ord = InvoiceLineId) | = E1 time (no own time) | invoice_line_id, invoice_id, track_id (ref), unit_price (amount, cents), quantity | invoice_items | 2,240 |

**Total events: 2,652.**

Entities (9 tables, 12,955 rows):

| Entity | Rows | created_at | Notes |
|---|---:|---|---|
| genres, media_types | 25, 5 | none (lookup) | |
| artists | 275 | none | 71 without albums must still exist |
| albums | 347 | none | ref artists |
| tracks | 3,503 | none | ref album/genre/media; Composer (opt text, 978 NULL), Milliseconds, Bytes (i64), UnitPrice (amount) |
| playlists | 18 | none | duplicate names are separate rows (Music 1/8, TV Shows 3/10, Movies 2/7, Audiobooks 4/6) [q2:playlist_dups] |
| playlist_track | 8,715 | none | link entity, ext_id `"PlaylistId/TrackId"`; refs to playlists and tracks |
| employees | 8 | HireDate | BirthDate and HireDate kept as text attributes; ReportsTo is an opt self-ref |
| customers | 59 | first invoice date (rule) | address fields; SupportRepId ref employees |

What is **not** an event, and why:
- **Hiring.** Hires are 2002–2004, five or more years before the first invoice (2009-01-01) [q3:invoice_vs_hire_birth], so `employee_hired` would be a lone prefix of 8 events. Keep HireDate on the entity as `created_at`.
- **Playlist membership.** It has no time and no order that means anything. It is a static link entity.
- **Customer sign-up.** There is no source time. created_at is the first invoice by rule, and stage 2 must not treat it as data.

## 3. Rebuild rules and blockers to an exact round trip

1. **Invoice total equals the sum of its lines exactly, in cents; not in float.** [q2:total_vs_lines_float, q3:cents_rebuild_exact]
   - `Total` is REAL on the cent grid in 412 of 412 invoices. `round(Total·100)` equals Σ cents of the lines in **412 of 412**.
   - The float sum `Σ UnitPrice·Quantity` equals the stored Total in only **355 of 412**. The other 57 differ by ≤ 8.9e-16. They are 6-line 0.99 invoices, where 6 × 0.99 summed in float ≠ the double nearest 5.94 [q2:total_float_mismatch_examples].
   - **Rule:** Total = (Σ line cents) / 100.0. That equals the stored double in 412 of 412, because one correctly rounded division gives the nearest double to the decimal. So Total is derived and not carried. Line UnitPrice = cents / 100.0 is exact in 2,240 of 2,240, and track UnitPrice in 3,503 of 3,503.
   - Text: SQLite prints every Total with exactly two decimals (412 of 412), so there are no trailing-zero issues.
2. **Billing address = customer address.** All five billing columns equal the customer's own (NULL-safe) in 412 of 412 invoices [q2:billing_equals_customer_address]. The view derives them from the customer entity, and E1 carries no address.
3. **Quantity is always 1** (2,240 rows), and the line price always equals the track's current price (2,240 of 2,240) [q2:quantity_values, q2:line_price_vs_track_price]. Carry both on E2 anyway; it costs nothing and a sim may vary them.
4. **Times.** `InvoiceDate` is `YYYY-MM-DD 00:00:00` (19 characters, 412 of 412) [q3:date_format]. Employee BirthDate and HireDate are the same format. Read them as UTC midnight and format them back with `%Y-%m-%d %H:%M:%S`.
5. **NULL vs empty.** No `''` exists anywhere. NULLs: customers Company 49, State 29, PostalCode 4, Phone 1, Fax 47; invoices BillingState 202, BillingPostalCode 28; tracks Composer 978; employees ReportsTo 1 [q1:null_and_empty_*]. Every one must be `opt(text)`.
6. **Text.** 274 track names, 149 composers, 20 album titles and 31 artist names are non-ASCII. Playlist 5 is `90’s Music`, with U+2019. No leading or trailing whitespace, no newlines [q1:text_whitespace]. Keep the text byte-exact.
7. **System tables.** Leave `sqlite_sequence` and `sqlite_stat1` out of `source.toml`. Rebuilding with the source DDL (AUTOINCREMENT) recreates `sqlite_sequence` with the same max ids as a side effect. `sqlite_stat1` only affects query plans.
8. **Rows without time.** Only catalog and party rows lack time, and they are entities. No invented event time is needed except customers' `created_at` (the first invoice). The snapshot N is 2013-12-22, the last invoice.

**Verdict:** an exact round trip is straightforward. Nothing is ambiguous; the only care is deriving Total from cents and not from a float sum.

## 4. Measured quirks (generator fingerprints)

- **A 7-invoice cycle.** In InvoiceId order, line counts repeat 1, 2, 2, 4, 6, 9, 14 [q3:lines_cycle]. That gives 59 invoices each of 1, 4, 6, 9 and 14 lines and 117 of 2 lines [q2:lines_per_invoice]. Customer 59 lacks one 2-line invoice, at the end of the series [q3:customer_with_6_invoices].
- **Date gaps follow the cycle.** The gap to the previous invoice is 0, 1, 1, 3, 5, 8, 13 days. The counts are gap 0: 58, 1: 118, 3: 59, 5: 59, 8: 59, 13: 58 [q3:gap_days_between_consecutive_invoices]. Dates never go backwards in InvoiceId order (411 of 411). 58 days have 2 invoices [q3:id_vs_date_order, q3:same_day_invoices].
- **Customer and track walks.** The step from one invoice's customer to the next is fixed per position in the cycle, mod 59. The first track of an invoice is the previous invoice's last track plus the same step, and the step between tracks within an invoice is fixed by the line count: 2 lines → 1 or 2; 4 → 2; 6 → 4; 9 → 6; 14 → 9 [q3:cycle_rules_by_lines, q3:within_step_by_lines]. The track walk wraps mod 3,503 6 times [q3:track_wraps]. **So the whole sales table is a deterministic function of (InvoiceId).**
- **Flat volume.** 7 invoices per month in 54 of 60 months, otherwise 5 or 6 [q3:per_month_counts_dist]. Revenue is 37.62 per month in most months [q3:monthly_invoices]. Weekdays are uniform, 58–60 each [q3:weekday]. There is no growth, seasonality or weekday effect.
- **Price deviations come only from video.** 214 tracks are `Protected MPEG-4 video file`, and 213 of them cost 1.99 [q2:price_by_media]. 111 lines in 30 invoices are 1.99 [q3:video_lines]. Those 30 invoices are why there are 23 distinct Totals and not 6 [q2:total_values].
- **Spending is nearly equal per customer:** 36.64 to 49.62, mean 39.47 [q3:customer_spend].
- **Duplicates.** 246 duplicate track names, 6 of them within one album; 4 duplicated playlist names (two pairs share identical tracks: Music 3,290 and TV Shows 213). Two pairs are empty [q1:dup_names, q2:playlist_pairs_same_tracks].
- **Track ids.** TrackId is grouped by album (3,064 of 3,502 consecutive pairs share one), but 55 steps go back to an earlier album [q3:track_id_album_contiguous].

## 5. Distributions to fit (stage 2)

The sales side is a deterministic schedule, so "fitting" means reproducing the rule, not a distribution:

| Quantity | Value |
|---|---|
| invoices | 412 over 1,816 days (2009-01-01..2013-12-22); 7 per 31-day cycle [q3:date_range] |
| lines per invoice | cycle 1, 2, 2, 4, 6, 9, 14 (mean 5.44) |
| line price | 0.99 audio, 1.99 video; quantity 1 |
| invoices per customer | 7 (58 customers), 6 (1) |
| customers per country | USA 13, Canada 8, Brazil 5, France 5, Germany 4, UK 3, CZ/India/Portugal 2, 15 countries with 1 [q3:country_customers] |
| genre mix of sold lines | Rock 835, Latin 386, Metal 264, Alternative & Punk 244, Jazz 80, Blues 61, TV Shows 47 [q3:genre_sales] |

The catalog distributions are real:
- **Tracks per album:** 82 singletons; mode 14 tracks (34 albums); max 57 [q3:tracks_per_album].
- **Albums per artist:** 148 artists have 1; max 21 [q3:albums_per_artist].
- **Duration (ms) by media type:** MPEG audio mean 265,574 (1,071–1,612,329); video mean 2,342,940 [q3:track_catalog_stats].

A realistic stage-2 pack would replace the cycle with a random arrival process. The exact round trip does not depend on that choice.

## 6. simkit mapping sketch

```python
p.entity("genres", key="genre_id", cols={"ext_id": text(), "name": opt(text())})
p.entity("media_types", key="media_type_id", cols={"ext_id": text(), "name": opt(text())})
p.entity("artists", key="artist_id", cols={"ext_id": text(), "name": opt(text())})
p.entity("albums", key="album_id", cols={"ext_id": text(), "title": text(), "artist_id": ref("artists")})
p.entity("tracks", key="track_id", cols={"ext_id": text(), "name": text(), "album_id": ref("albums"),
         "media_type_id": ref("media_types"), "genre_id": ref("genres"), "composer": opt(text()),
         "milliseconds": i64(), "bytes": i64(), "unit_price": amount("USD")})
p.entity("playlists", key="playlist_id", cols={"ext_id": text(), "name": opt(text())})
p.entity("playlist_track", key="pt_id", cols={"ext_id": text(), "playlist_id": ref("playlists"), "track_id": ref("tracks")})
p.entity("employees", key="employee_id", cols={"ext_id": text(), "last_name": text(), "first_name": text(),
         "title": opt(text()), "reports_to": opt(ref("employees")), "birth_date": opt(text()), ...})
p.entity("customers", key="customer_id", cols={"ext_id": text(), "first_name": text(), ..., "support_rep_id": opt(ref("employees"))})
p.event("invoice_issued", cols={"customer_id": ref("customers"), "invoice_id": i64()})
p.event("invoice_line_added", cols={"customer_id": ref("customers"), "invoice_id": i64(), "invoice_line_id": i64(),
        "track_id": ref("tracks"), "unit_price": amount("USD"), "quantity": i64()})
```

Ingest:
- `-- event: invoice_issued owner=customer_id ord=invoice_id`, ORDER BY InvoiceId.
- `-- event: invoice_line_added owner=customer_id ord=invoice_line_id`, ORDER BY InvoiceLineId.
- An issue sorts before its lines because its block comes first and the times tie.
- `unit_price = CAST(round(UnitPrice*100) AS INTEGER)`.

Views:
- `invoices`: E1 ⋈ customers for the billing address. `Total = SUM(line cents)/100.0`, grouped by invoice_id.
- `invoice_items`: E2 with `unit_price/100.0`.
- `tracks.UnitPrice = cents/100.0`.

Stage 2 owners: `customer` (59, each with its own invoice schedule) and a `catalog` source that inserts the entities. The volume is tiny (2.7k events); no sample profile is needed.

## 7. Open questions and risks

- **Which Chinook build exactly.** The content matches upstream 1.4.x dates, with master's invoices and lines identical apart from the +12-year shift [c5_upstream]. I did not diff the catalog tables against a pinned 1.4.0 file, nor confirm the sqlitetutorial.net download byte for byte.
- **Licence.** MIT (upstream). Low risk; keep the attribution line.
- **local055 has two gold CSVs** that encode two readings: zero-sales artists included (5.1333) or excluded (4.1433). Save the query in one reading and compare source with rebuilt, not with gold.
- **Float query results.** local198's float sum is 249.52999999999997. Totals computed from rebuilt cents are the identical doubles, so source and rebuilt agree exactly. The gold CSV is rounded.
- **Realism.** The sales are a deterministic toy, so they are a poor target for stage-2 distribution fitting. The value of this dataset is the exact-round-trip and query checks, and the real music catalog.
