# wwe

## What this is

Professional wrestling results scraped from profightdb.com ("The Internet Wrestling Database"): every card of five promotions (WWWF, WWF, WWE, WCW, NXT) from 1963-01-25 to 2024-01-14, and the matches on each card.

Version `v1`, kind `spider2`. The input is one ordered event log of 128,303 events; the output is the 9 source tables, rebuilt exactly, and the answer to 1 saved Spider 2.0 question.

## Raw data

`WWE.sqlite` (168 MB, all 9 tables; `sqlite_sequence` is not data). Real data from a hand-written scraper; profightdb's terms are unknown, so treat the HTML and names as third-party content. A Kaggle mirror (`alexdiresta/all-wwe-and-wwf-matches`) is a lead for the origin, not a confirmed one.

`Cards` has 12,639 cards, each with a `YYYY-MM-DD` date, and the raw HTML of its page (`info_html`, `match_html`); `Tables` has the 1,270 listing pages' HTML. Every structured column is a parse of that HTML. `Matches` has 540,800 rows but only 77,567 distinct matches: the scraper ran 7 times and appended every known card's matches again on each run, so a card's matches appear 7 times if it was first seen on run 1 and once if first seen on run 7. Any count, sum or average over `Matches` is inflated 1–7× unless it is deduplicated, and an engine benchmark on it measures the duplication. A `Wrestlers` row is a match side, its members sorted and joined with " & " (`Dory Funk, Sr.` is stored as `Dory Funk & Sr.`), not a person. `''` means unknown or none (belt 1, match type 1, 337,952 durations); no column holds a NULL. `Matches`' four ref columns are TEXT holding decimal ids.

The reverse-engineering research, with the queries behind every number, is in [`docs/research/spider2/wwe.md`](../../docs/research/spider2/wwe.md).

## How the log was made

Promotions, locations, shows (`Events`), sides (`Wrestlers`), belts, match types and listing pages (`Tables`) are entities; every id is the scraper's counter, carried verbatim as `ext_id`, since the card counter skips 133 failed listing rows. A card is a `card_held` event on its date. Each distinct match is a `match_held` event at its card's date, with its 1-based `position` on the card; the distinct matches are each card's first contiguous id block in `Matches` (every block of a card is identical, in 12,638 of 12,638 cards with matches). `duration` travels as seconds (`duration_s`, NULL for `''`). Each of the 7 scraper passes is a `scrape_run` event, owned by the sentinel `'all'`. Each card's page is a `card_page_scraped` event at its first run, carrying the URL and the two HTML fragments verbatim, so the show-date event carries nothing from the future. A card's first run is 8 minus its block count; card 2475, which has no matches, is in the run-1 id range and gets run 1.

`specs/build.sql` rebuilds `Matches` by the rule the research proved: run r = 1..7 appends, in card-id order, the distinct matches of every card first scraped in a run ≤ r, and `id` is the running row number. The 21 exact duplicate rows inside a card's first block stay apart by `position`.

`uv run dataset build wwe` runs `specs/ingest.sql` on the read-only source to make a simkit dataset (an internal stage), then writes it as one log. Entity rows become `<entity>_created` events at their creation time; business events keep their columns. The log is in `seq` order: event time, then entities before events at the same instant; within a date, events follow card id, and a card's `card_held` precedes its matches. Card ids run newest-first within a promotion, so `card_id` is not a time. Each row's `payload` is a JSON object whose fields are listed in `schema/events.json`. The 59 MB of HTML comes back byte for byte; the build takes about 3 minutes and the verify about 8 seconds.

## Event catalogue

| Event | Kind | Rows | Payload fields |
|---|---|---:|---|
| `promotions_created` | entity | 6 | `promotion_id`, `ext_id`, `name` |
| `locations_created` | entity | 609 | `location_id`, `ext_id`, `name` |
| `shows_created` | entity | 5,033 | `show_id`, `ext_id`, `name` |
| `sides_created` | entity | 17,182 | `side_id`, `ext_id`, `name` |
| `belts_created` | entity | 143 | `belt_id`, `ext_id`, `name` |
| `match_types_created` | entity | 1,208 | `match_type_id`, `ext_id`, `name` |
| `listing_pages_created` | entity | 1,270 | `page_id`, `ext_id`, `html`, `url` |
| `card_held` | business | 12,639 | `promotion_id`, `card_id`, `location_id`, `show_id` |
| `match_held` | business | 77,567 | `promotion_id`, `card_id`, `position`, `winner_id`, `loser_id`, `win_type`, `match_type_id`, `duration_s`, `title_id`, `title_change` |
| `scrape_run` | business | 7 | `scraper`, `run` |
| `card_page_scraped` | business | 12,639 | `promotion_id`, `card_id`, `run`, `table_id`, `url`, `info_html`, `match_html` |

## Times set by rule

Card dates are the only times in the source, read as UTC midnight; a match takes its card's date. The scrape runs have no recorded time: run r is stamped at the latest card date among the cards first seen in runs 1..r, which gives 2023-11-04, 2023-11-14, 2023-11-24, 2023-12-05, 2023-12-18, 2023-12-28 and 2024-01-14 (N, the last card date). A card's page snapshot takes its first run's time. Sides, belts and match types are created on the earliest card date of a match that uses them. Promotions, locations and shows are created on the earliest card that uses them; the unused ones (ECW, 13 locations, 13 shows) and all listing pages are created at the run-1 time, 2023-11-04. Every time is ≤ N. Run times are a scraper fact and a lower bound, not a domain fact.

## Expected output

`results/` holds every source table, as the source stores it. Each column's type follows the values it holds: text, int64 or float64. A mixed column holds text and numbers together, so it is stored as SQLite's own text rendering and declared in `dataset.toml`.

| Table | Rows | Columns | Mixed columns |
|---|---:|---:|---|
| `Promotions` | 6 | 2 | none |
| `Tables` | 1,270 | 3 | none |
| `Cards` | 12,639 | 9 | none |
| `Locations` | 609 | 2 | none |
| `Events` | 5,033 | 2 | none |
| `Matches` | 540,800 | 9 | none |
| `Belts` | 143 | 2 | none |
| `Wrestlers` | 17,182 | 2 | none |
| `Match_Types` | 1,208 | 2 | none |

`expected/queries/` holds the answers of the saved questions (`local019`), computed on the source. `dataset verify` runs `specs/build.sql` over the log, loads the tables into SQLite with the source's DDL, and compares them and the answers exactly: rows as multisets, numbers by value, text byte for byte.

local019 is Spider2's gold SQL and reproduces `local019_a.csv` (Bron Breakker, Duke Hudson; NXT Championship, 00:43). It takes a minimum, so the 7 copies do not change it, and its `LIKE '%title change%'` filter matches no belt. `local019_b.csv` (Tiffany Stratton, Thea Hail, 08:28) is not reproduced by any reading the research tried.

## Regenerate

```bash
uv run refdata fetch                 # once: the Spider 2.0 SQLite files → data/spider2/
uv run dataset build wwe             # → $NEORISK_DATA_ROOT/wwe/v1/ (default data/datasets/)
uv run dataset verify wwe            # exit 0 = every table and answer matches
```

## Extend

- **More rows:** not possible for a fixed source. Stage 2 will generate logs from `specs/pack.py`; the scraper events (`scrape_run`, `card_page_scraped`) are not behavior, so stage 2 should emit one run at N or drop them.
- **A new event type:** declare it in `specs/pack.py`, add its `-- event: <name> owner=<col>` block to `specs/ingest.sql`, and use it in `specs/build.sql`.
- **A new attribute:** add the column to the pack table and to its ingest block. It then appears in the payload and in `schema/events.json`.
- **A new results table:** add it to `specs/source.toml` and a `-- table: <name>` block to `specs/build.sql`.
- **A new saved question:** add `specs/queries/<id>.sql` (SQLite dialect, source table names).
- **A new engine port:** write `engines/<engine>/` from `specs/build.sql`. It must read only the log and match `results/` exactly.

Any change to `specs/`, `dataset.toml` or the source changes the build. Once a version is recorded in `v1.lock.json`, changed output needs a new version (`v2`).
