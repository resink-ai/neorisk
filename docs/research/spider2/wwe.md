# WWE (Spider 2.0-lite): reverse-engineered event log

Source: `data/spider2/WWE.sqlite` (168 MB), opened read-only. `scripts/wwe/rq.py` copies the file into an in-memory SQLite and runs named blocks; the Python scripts open it with `mode=ro`. The file is never written.

Every number below comes from one of these scripts:
- a named query in `scripts/wwe/q*.sql` (`q1_inventory`, `q2_keys_joins`, `q3_values`, `q4_gold`, `q5_rebuild`);
- `p1_passes.py` (the repeated blocks in Matches);
- `p2_rebuild_matches.py` (the Matches rebuild rule, and the scrape runs);
- `p3_html.py` (the structured columns as a parse of the stored HTML);
- `p4_dists.py` (distributions, over distinct matches).

The raw outputs are in `scripts/wwe/out_*.txt`. A reference such as `[q2:fp_match_counter]` means file `q2_keys_joins.sql`, block `-- name: fp_match_counter`. The gold SQL and CSVs are in `scripts/wwe/gold/`.

## 0. What this catalog is

- **Dataset.** This is a **web scrape of profightdb.com** ("The Internet Wrestling Database"). It covers every card of five promotions, 1963-01-25 to 2024-01-14, and the matches on them. The evidence:
  - every `Tables.url` is a profightdb listing page, such as `http://www.profightdb.com/cards/wwwf-cards-pg1-no-20.html?order=&type=`. Every `Cards.url` is a profightdb card page [q1:tables_url_shape];
  - `Tables.html`, `Cards.info_html` and `Cards.match_html` hold the raw HTML fragments: 8.1 MB, 12.4 MB and 38.7 MB of text [q1:text_bytes];
  - every structured column is a parse of that HTML (§3.2) [p3].
- **Exact lineage (unverified).** A web search names a Kaggle mirror of a profightdb SQLite dump, `alexdiresta/all-wwe-and-wwf-matches`, but I could not open its page to compare tables ([Ringside Analytics paper](https://wrastlingfirst.vercel.app/paper.html), [its citation file](https://huggingface.co/datasets/datamatters24/ringside-analytics/blob/main/CITATION.cff)). Treat that origin as a lead, not a fact.
- **Row counts** [q1:row_counts]:

  | Table | Rows |
  |---|---:|
  | Matches | 540,800 |
  | Wrestlers | 17,182 |
  | Cards | 12,639 |
  | Events | 5,033 |
  | Tables | 1,270 |
  | Match_Types | 1,208 |
  | Locations | 609 |
  | Belts | 143 |
  | Promotions | 6 |

  `sqlite_sequence` also exists (9 rows) and is not a results table.
- **Matches holds 7 copies of the data.** There are only **77,567 distinct matches**. The scraper ran 7 times and appended every card's matches again on each run (§1, §3.1) [p1, p2].
- **Licence:** unstated. profightdb's terms are unknown, so treat the HTML as third-party content.
- **Nature:** **real data** (historical wrestling results, mostly scripted outcomes), produced by a hand-written scraper. The scraper left strong fingerprints (§4). It is not anonymised and not generated.

### 0.1 How Spider 2.0 uses it

One question uses db `WWE` [spider2-lite.jsonl]. Gold SQL exists, with two exec_result CSVs.

| id | asks | gold SQL? | gold value | reproduced |
|---|---|---|---|---|
| local019 | for the NXT title with the shortest match (excluding "title change"), the two wrestlers' names | yes | `_b`: Bron Breakker, Duke Hudson (NXT Championship, 00:43). `_a`: Tiffany Stratton, Thea Hail, 08:28 | `_b` ✔ exactly, by the gold SQL [q4:local019_gold_sql]. `_a` ✗ not reproduced: that match exists (NXT Women's Title, 08:28, title_change 0), but no reading I tried makes it the minimum [q4:local019_variant_a_*] |

What the question depends on:
- **Text sorting of `duration`.** Every non-empty value is `MM:SS` with two-digit minutes (00:02..81:00), so text order equals time order [q3:duration_format].
- **`''` means unknown.** The query filters `duration <> ''` and `b.name <> ''`. Belt 1 is `''` ("no title"), and 337,952 rows have duration `''`.
- **The copies do not change the answer.** The query takes a minimum, so 7 copies (2,924 rows; 424 distinct) [q4:local019_dedup_invariance] give the same result as 1. A `count(*)` question would not.
- **`Belts.name LIKE '%title change%'` matches 0 belts** [q3:belts_title_change_names]. The title change is the `title_change` flag, so that filter in the gold SQL does nothing.

## 1. Inventory, keys, joins

Each table declares `id INTEGER PRIMARY KEY AUTOINCREMENT`. No FK is declared. All joins below resolve with 0 orphans [q2:fk_orphans].

| Table | Rows | Key | Kind |
|---|---:|---|---|
| Matches | 540,800 | id 1..540,800, dense [q1:matches_id_dense] | activity, **7 scrape copies of 77,567 matches** |
| Cards | 12,639 | id 1..14,344 (1,705 gaps); `url` and `match_html` UNIQUE | activity: one show on one date |
| Tables | 1,270 | id = number of the page's first listing row; `html` and `url` UNIQUE | scrape artefact: listing page |
| Wrestlers | 17,182 | id up to 1,081,588; `name` UNIQUE (declared with **no type**) | lookup: a **match side**, not a person |
| Events | 5,033 | id; `name` UNIQUE | lookup: show name ("Monday Night Raw") |
| Match_Types | 1,208 | id; `name` UNIQUE; id 1 = `''` | lookup |
| Locations | 609 | id; `name` = "City, State" | lookup |
| Belts | 143 | id; id 1 = `''` (no title) | lookup |
| Promotions | 6 | WWWF 1, WWF 230, WWE 3211, WCW 9876, NXT 10963, ECW 12682 | lookup |

**Refs.**
- Matches.card_id → Cards. Matches' `winner_id` / `loser_id` → Wrestlers, `match_type_id` → Match_Types and `title_id` → Belts. These four are **TEXT columns** holding canonical decimal ids. 0 of 540,800 rows are non-canonical [q2:matches_ref_text_shape].
- Cards.table_id → Tables, location_id → Locations, promotion_id → Promotions, event_id → Events.

**Unused parents** [q2:unused_parents]:
- 1 card has no matches: card 2475, a 1991 WWF house show whose `match_html` is 323 bytes [q3:card_without_matches];
- 13 Locations and 13 Events are used by no card;
- Promotion ECW is used by no card;
- every Wrestlers, Belts, Match_Types and Tables row is used.

**The ids are scraper counters**, a generator fingerprint:
- **Match counter.** Belts.id and Match_Types.id equal the id of the first match that uses them, in **143 of 143** and **1,208 of 1,208**. Wrestlers.id equals the first slot that uses it (slot `2·id−1` as winner, `2·id` as loser) in **17,182 of 17,182** [q2:fp_match_counter]. `sqlite_sequence` agrees: Belts and Match_Types 540,800, Wrestlers 1,081,600 = 2 × 540,800 [q1:sqlite_sequence].
- **Card counter.** In run 1, the scraper numbered the listing rows 1..12,681 across the pages in order.
  - Tables.id is the number of the page's first row in **1,270 of 1,270**.
  - Cards.id is the number of its listing row in **12,548 of 12,548** listed cards [p3 §4].
  - 133 listing rows produced no card. The Locations and Events that are not used first (29 and 17) sit **exactly** on those failed rows: they were inserted, and then their card failed [p3 §4, q2:fp_card_counter_misses_other].
  - ECW (12682) is the next counter value after the last listing row.
  - Cards from later runs take ids 13,382..14,344. All five card-counter tables end at sequence 14,431 [q1:sqlite_sequence].
- **So the ids are not a pure function of the other rows.** The failed listing rows are not in the data, so the card-counter ids must be carried verbatim. The match-counter ids could be derived (§3.4), but carrying them as `ext_id` is simpler and exact.

**Copies.** Matches is 7 copies of itself (§3.1). No other table is a copy of another.

**Derived columns.** Every structured column of Cards and Matches is a parse of Cards' and Tables' HTML (§3.2). It is derivable in principle, but not in `build.sql`.

## 2. Event catalogue

**Times.**
- `Cards.event_date` is the only time in the catalog: `YYYY-MM-DD`, valid and canonical in 12,639 of 12,639 rows [q3:event_date_format].
- **Matches have no time of their own.** A match happens on its card's date, and its position on the card gives the order.
- **The scrape runs have no recorded time.** Each run is dated by rule: the latest card date known after that run [p2].

  | run | new cards | card ids | their dates | run time (rule) |
  |---|---:|---|---|---|
  | 1 | 12,547 (+ card 2475) | 1..12,681 | 1963-01-25..2023-11-04 | 2023-11-04 |
  | 2 | 14 | 13,382..13,419 | 2023-10-17..2023-11-14 | 2023-11-14 |
  | 3 | 11 | 13,472..13,559 | 2023-11-07..11-24 | 2023-11-24 |
  | 4 | 16 | 13,632..13,742 | 2023-11-25..12-05 | 2023-12-05 |
  | 5 | 21 | 13,832..13,943 | 2023-11-28..12-18 | 2023-12-18 |
  | 6 | 7 | 14,132..14,138 | 2023-12-22..12-28 | 2023-12-28 |
  | 7 | 22 | 14,232..14,344 | 2023-12-12..2024-01-14 | 2024-01-14 |

  The runs were roughly every 10 days.
- Snapshot **N = 2024-01-14**, the last card date and run 7's time [q5:snapshot_N].

| # | Event | Owner | Time | Attributes | Source rows | Count |
|---|---|---|---|---|---|---:|
| E1 | `card_held` | promotion (ord = card id) | `event_date` (natural, day grain) | card_id (ext id), location_id (ref), event_id (ref shows) | Cards | 12,639 |
| E2 | `match_held` | promotion (ord = card id; block row = position) | = E1 time (natural date; order by position is natural) | card_id, position 1..30, winner_id, loser_id (ref sides), win_type (cat, 25 values), match_type_id (ref), duration_s (opt i64), title_id (ref belts), title_change (i64 0/1) | each card's first block of Matches | 77,567 |
| E3 | `scrape_run` | scraper (single owner; ord = run) | run time (**rule**, table above) | run (1..7) | none: implied by the 7 blocks | 7 |
| E4 | `card_page_scraped` | promotion (ord = card id) | time of the card's first run (**rule**) | card_id, run (first run), table_id (ref listing_pages), url, info_html, match_html | Cards | 12,639 |

**Total business events: 102,852.**

**Entities (7 tables, 25,451 rows):**

| Entity | Rows | `created_at` | Rule or natural |
|---|---:|---|---|
| promotions | 6 | the earliest card that uses it; ECW (unused) at the run-1 time | rule |
| locations | 609 | earliest using card; the 13 unused at the run-1 time | rule |
| shows (`Events`) | 5,033 | earliest using card; the 13 unused at the run-1 time | rule |
| sides (`Wrestlers`) | 17,182 | earliest card date of a match using it: 1963-01-25..2024-01-13. 84 are first seen after run 1 [q5:wrestler_first_use_date] | rule |
| belts | 143 | earliest using match | rule |
| match_types | 1,208 | earliest using match | rule |
| listing_pages (`Tables`) | 1,270 | run-1 time, 2023-11-04 | rule; the `html` is a run-1 page snapshot |

What is **not** an entity or event, and why:
- **Matches' 7 copies.** They are scraper runs, not 7 bouts. They become E3 plus a rule in `build.sql` (§3.1), never 540,800 business events. A stage-2 simulator that learned the 7× duplication would be learning the scraper.
- **A person.** A Wrestlers row is a *side* string. 12,952 of 17,182 contain " & " [q3:wrestler_names_tags]. The longest has 62 members [p4], and "Dory Funk, Sr." is stored as `Dory Funk & Sr.` (§4). There is no person table, so a person cannot be an entity without parsing names, which is out of scope.
- **Venues and attendance.** These exist only inside `info_html` text, and are carried there verbatim.
- **The HTML columns** are page snapshots taken at scrape time, never at the show's date. That is why they ride on E4, not E1, so E1 carries nothing from its future.

## 3. Rebuild rules and blockers to an exact round trip

1. **Matches = 77,567 distinct matches × the scrape runs. This is proved.**
   - Each card's matches appear as contiguous id blocks, 88,131 blocks in all. Every block of a card is identical, in 12,638 of 12,638 cards [p1].
   - Block counts per card are 7 (12,547 cards), then 6, 5, 4, 3, 2 and 1 for the cards that first appeared in runs 2..7: 14, 11, 16, 21, 7 and 22 cards [p1, p2].
   - **Rule:** run r = 1..7 visits every card whose first run is ≤ r, in card-id order, and appends that card's distinct matches in position order. `Matches.id` is the running row number.
   - In Python, the rule rebuilds the 540,800-row multiset with **0 rows differing** [p2:multiset equal]. In SQL, as the `build.sql` will compute it, it gives 77,567 distinct, 540,800 rebuilt, and 0 / 0 rows only on one side [q5:matches_rebuild_sql].
   - `first_run` is monotone in card id (0 decreases) [p2], and pass order has 0 card-order inversions [p1].
2. **Derived from HTML. Measured; not used in `build.sql`.**
   - From `Tables.html`: each listed card's `event_date`, promotion and location equal its own listing row in 12,548 of 12,548. The Events name is equal in 12,541; the other 7 differ only because my parser collapsed a double space, and the stored names keep it [p3].
   - From `info_html`: the date link, the `Promotion:` text and the last two venue links equal the date, promotion and location in **12,639 of 12,639** [p3].
   - From `match_html`: the row count equals the distinct match count in 12,639 of 12,639 cards. Win type, duration, match type, title and title change agree in **77,567 of 77,567**.
   - The side names agree in 77,567 of 77,567 once the scraper's rule is applied: split every anchor on ",", strip, **sort**, join with " & " [p3].
   - The 91 cards from runs 2..7 are absent from the listing pages, which are run-1 snapshots.
   - **Decision:** carry the structured columns as data and the HTML verbatim as text. Parsing HTML in DuckDB is fragile, and the event ids could not come from it anyway.
3. **Text formats.**
   - `event_date` is `YYYY-MM-DD`. Read it as UTC midnight and format it back with `%Y-%m-%d`.
   - `duration` is `MM:SS` or `''`. Carried as `opt(i64)` seconds, it rebuilds with `CASE WHEN s IS NULL THEN '' ELSE printf('%02d:%02d', s/60, s%60) END`, with 0 of 540,800 differing [q5:duration_seconds_roundtrip]. Carrying the text verbatim is the fallback.
   - **The four ref columns must come back as TEXT** (`CAST(ext_id AS VARCHAR)`). An INTEGER would fail the byte-exact text comparison. 540,800 of 540,800 are canonical [q5:ref_text_roundtrip].
   - `Wrestlers.name` has no declared type, so its results column is string. All values are text [q1:typeof_lookups].
4. **Empty strings, never NULL.**
   - No column holds a NULL [q1:nulls_cards, q1:nulls_matches].
   - `''` appears in Belts 1, Match_Types 1 and Wrestlers 4631 [q1:empty_names], in `win_type` (28 rows; 4 distinct), and in `duration` (337,952 rows; 48,495 distinct).
   - Keep `''` as `''`, and keep NULL out of the views.
5. **Ids.** All are carried as `ext_id` verbatim.
   - The match-counter ids are reproducible: each is the min first slot over the rebuilt Matches [q2:fp_match_counter]. A `build.sql` could recompute them as a self-check.
   - The card-counter ids are not reproducible. The 133 failed listing rows are not in the data.
6. **Duplicates.** 21 rows inside a card's first block repeat another row of that card exactly [p1, p4]. Position keeps them apart. The table compares as a multiset, so they rebuild exactly as long as `position` is carried.
7. **Rows without time.** These are all matches (the card's date), the 7 runs (the rule), the HTML snapshots (the first run's time) and every entity (first use, else run 1). Every invented time is ≤ N.
8. **Size.** The HTML is 59 MB of text in event payloads. That is exact, but it dominates the log's size.

**Verdict:** exact with caveats. The 7× Matches duplication is fully explained, and is rebuilt from 7 events and a proven rule. The remaining risk is carrying 59 MB of HTML byte-exact through JSON.

## 4. Measured quirks

- **The 7 scrape copies** (§3.1).
  - 85.7% of Matches rows are copies.
  - Any `count`, `sum` or `avg` over Matches is 7× (or 1..7×, depending on the card) unless it is deduplicated.
- **The side-name mangling.** The scraper sorted every side's members and replaced commas with " & ". So `Dory Funk, Sr.` becomes `Dory Funk & Sr.`, and `Miguel Perez, Sr. & Pedro Morales` becomes `Miguel Perez & Pedro Morales & Sr.` [p3]. A side is a set, not a team identity: `Jr. & Jr.` appears inside long battle-royal sides [q3:wrestler_names_long].
- **Degenerate matches** (distinct):
  - 15 have winner = loser: 12 with the `''` side and 3 with "Unknown Male Wrestler" [p4];
  - 4 have an empty `win_type`;
  - 45 are `vs.`, and 29 have no `def.` (`(pin)`, `(DQ)`, `(sub)`);
  - 6 are fused `def.draw (…)` [p4].
- **title_change without a title.** This happens on 9 distinct matches: 63 rows, i.e. title_id 1 with title_change 1 [p4, q3:title_change_mix].
- **Compound belts.** 42 of 143 Belts names hold two or more titles, such as `NXT North American Championship NXT Tag Team Titles`. A multi-title match points to one combined belt [p4, q4:local019_variant_a_try_per_belt_max_of_min].
- **NXT belts outside NXT.** WWE cards carry NXT-named belts on 691 rows [q3:promotion_by_belt_prefix].
- **Double spaces** survive in 7 Events names, such as `WrestleMania 36  - Day 1 Taping Part 2` [p3].
- **Listing order.** Card ids run newest-first inside each promotion: 0 date-ascending steps within run 1 [q3:card_id_vs_date_within_promo]. So id order is anti-chronological, and `ord` must not stand in for time.
- **Late backfill.** Run 2's cards start at 2023-10-17, before run 1's last date, 2023-11-04 [p2]. The site added older cards after run 1.
- **Same-day cards.** 3,866 (promotion, date) pairs have 2–8 cards, and one date has 8 [q3:same_date_cards].
- **Durations** are missing on 62.5% of distinct matches. The share present varies by decade: 0.79 in the 1980s, 0.24 in the 2010s. `:00` seconds occur 5.05% of the time against 1.67% for a uniform spread, a sign of rounded entries [p4].

## 5. Distributions to fit (stage 2)

All over distinct matches and cards [p4].

| Quantity | Value |
|---|---|
| cards per year | WWWF median 11 (1963–79); WWF 137 (max 323); WCW 59 (max 256); WWE 265 (max 444); NXT 135 (max 230) |
| cards by decade | 1960s 118, 70s 120, 80s 543, 90s 2,586, 2000s 2,827, 2010s 4,931, 2020s 1,514 |
| weekday | Mon 3,666, Tue 3,357 (TV tapings), Sun 1,405, Sat 1,358, Fri 1,158, Wed 860, Thu 835 |
| gap between cards (days, per promotion) | WWE p50 1, p90 4, 43% zero; WWF p50 1, p90 9; WCW p50 1, p90 7; NXT p50 1, p90 7; WWWF p50 28 |
| matches per card | 1–30; quartiles WWE 3/6/8, WCW 7/8/9, NXT 5/7/8; mode 8 (2,290 cards) |
| win type | def. (pin) 54.8%, def. 29.2%, sub 6.1%, DQ 5.5%, draw (NC) 1.8%, CO 1.2%, other draws 1.1% |
| duration (s), where present | p10 108, p50 334, p90 900, max 4,860 |
| title matches | 14.5% of matches; title change on 13.6% of title matches (1,532 of 11,276) |
| match type | `''` (plain) 80.6%, dark 3.7%, 6-person tag 3.3%, handicap tag 1.1%, then a long tail over 1,208 types |
| side size | 1 member 71.7%, 2: 22.3%, 3: 4.2%, 4+: 1.8% (max 62) |
| appearances per side | 60% appear once; p90 12; max 985 (Dolph Ziggler) |
| cards per location | p50 5, p90 63; Orlando 695, New York 482, Winter Park 404 [q3:locations_top] |
| show names | 4,837 of 5,033 used once; Monday Night Raw 1,337 cards [q3:events_reuse, q3:events_top] |

## 6. simkit mapping sketch

```python
p.entity("promotions", key="promotion_id", cols={"ext_id": text(), "name": text()})
p.entity("locations", key="location_id", cols={"ext_id": text(), "name": text()})
p.entity("shows", key="show_id", doc="Spider2 table Events", cols={"ext_id": text(), "name": text()})
p.entity("sides", key="side_id", doc="Spider2 Wrestlers: one match side, members sorted, ' & '-joined",
         cols={"ext_id": text(), "name": text()})
p.entity("belts", key="belt_id", cols={"ext_id": text(), "name": text(doc="'' = no title")})
p.entity("match_types", key="match_type_id", cols={"ext_id": text(), "name": text(doc="'' = plain")})
p.entity("listing_pages", key="page_id", doc="Spider2 Tables; run-1 snapshot",
         cols={"ext_id": text(), "html": text(), "url": text()})
p.event("card_held", cols={"promotion_id": ref("promotions"), "card_id": i64(),
        "location_id": ref("locations"), "show_id": ref("shows")})
p.event("match_held", cols={"promotion_id": ref("promotions"), "card_id": i64(), "position": i32(),
        "winner_id": ref("sides"), "loser_id": ref("sides"), "win_type": cat(*WIN_TYPES),  # 25 incl. ''
        "match_type_id": ref("match_types"), "duration_s": opt(i64()), "title_id": ref("belts"),
        "title_change": i64()})
p.event("scrape_run", cols={"run": i32()})
p.event("card_page_scraped", cols={"promotion_id": ref("promotions"), "card_id": i64(), "run": i32(),
        "table_id": ref("listing_pages"), "url": text(), "info_html": text(), "match_html": text()})
```

Ingest:
- `card_held owner=promotion_id ord=card_id`: `iso_time(event_date, '%Y-%m-%d')`, ORDER BY id.
- `match_held owner=promotion_id ord=card_id`: the first block of each card (the islands query in `q5:matches_rebuild_sql`, `b = 1`), with `position` = row_number within the block. ORDER BY card_id, position. Block order puts each card's `card_held` first.
- `scrape_run owner=scraper ord=run`: 7 rows at the run times in §2, computed as the running max `event_date` over cards grouped by `first_run = 8 − block count`.
- `card_page_scraped owner=promotion_id ord=card_id`: at its run's time, ORDER BY id. Card 2475, which has no matches, gets run 1 by rule: its id is in the run-1 range.
- Entities: `ext_id = CAST(id AS TEXT)`, with `created_at` by the §2 rules.

`build.sql` (DuckDB):
- The six lookups: `SELECT CAST(ext_id AS BIGINT) id, name`. Tables: `id, html, url` from listing_pages.
- **Cards:** `card_held` ⋈ `card_page_scraped` on card_id. `event_date = strftime(event_time, '%Y-%m-%d')`, and the ref ext ids are cast to BIGINT.
- **Matches:** `scrape_run r` ⋈ `card_page_scraped` (`run ≤ r.run`) ⋈ `match_held`, then `id = row_number() OVER (ORDER BY r.run, card_id, position)`.
  - `winner_id`, `loser_id`, `match_type_id` and `title_id` are `CAST(ext_id AS VARCHAR)`.
  - `duration` is `CASE WHEN duration_s IS NULL THEN '' ELSE printf('%02d:%02d', duration_s // 60, duration_s % 60) END`.
  - This is the query proved in `q5:matches_rebuild_sql`.

Stage-2 owners:
- **promotion** (6), each with a show calendar: a weekday mix and same-day multiplicity;
- per card, a match count, and per match a side draw from a heavy-tailed roster with a title share and a title-change rate.

The scraper (E3/E4) is not behaviour. Stage 2 should either emit one run at N or drop it.

## 7. Open questions and risks

- **The `_a` gold CSV** (Stratton/Hail 08:28) is not reproduced by any reading I tried. The gold SQL reproduces `_b`. The evaluator accepts either CSV, so the risk is low.
- **Origin and licence.** The data is profightdb content. The Kaggle mirror is named by one secondary source only, and the licence is unknown. Fitting statistics is fine. Confirm the terms before redistributing the HTML or names.
- **Should results keep 540,800 rows?** The contract says every source table, exactly, so yes. But any engine benchmark on Matches measures 7× duplication. The dataset's CONTEXT.md should say so plainly.
- **Run times are a rule** (a lower bound: the latest card date known). They are a scraper fact, not a domain fact.
- **The ids hide 133 failed listing rows.** We know their counter values (the Locations and Events that sit on them) but not their content. The Tables HTML does list those cards' dates and names, so they could be recovered as "lost cards" if ever wanted. They are not needed for the round trip.
- **HTML payload size** (59 MB) and byte-exact JSON of text with `&nbsp;`, accents and newlines: the round trip must be tested on this dataset specifically.
- **Side vs person.** Splitting sides into people is possible (`' & '`, after the comma mangling), but lossy: "Sr." becomes a member. Leave it to stage 2.

---

- Exact round trip: **yes, with caveats.** Matches' 540,800 rows rebuild from 77,567 distinct matches plus 7 scrape runs by a proven rule (0 rows differ). The 59 MB of HTML is carried verbatim.
- Proposed dataset name: **`wwe`**.
- Event types: **4** (`card_held`, `match_held`, `scrape_run`, `card_page_scraped`; 102,852 events). Entities: **7** (25,451 rows).
- Event shape: **partly imposed**. Cards and matches are natural, at day grain with in-card position. Scrape runs, page snapshots and all entity creation times are set by rule.
- Hardest blocker: Matches is 7 scraper copies laid out over 7 interleaved runs. The rebuild is solved, but it makes Matches a scrape artefact, and the HTML must survive byte-exact.
