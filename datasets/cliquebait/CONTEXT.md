# cliquebait

## What this is

Clique Bait, an online seafood shop: a click log of page views, cart adds, purchases and ad events per visit.

Version `v1`, kind `spider2`. The input is one ordered event log of 34,537 events; the output is the 5 source tables, rebuilt exactly, and the answers to 1 saved Spider 2.0 questions.

## Raw data

`bank_sales_trading.sqlite` (the five `shopping_cart_*` tables). Synthetic course data (8 Week SQL Challenge #6); course material.

Event times are UTC wall clock with microseconds; the source strips trailing zeros.

The reverse-engineering research, with the queries behind every number, is in [`docs/research/spider2/bank_clicklog.md`](../../docs/research/spider2/bank_clicklog.md).

## How the log was made

The source is already an event log: each row of `shopping_cart_events` is one `page_event`, owned by the visit. Cookies (with their user), pages, event kinds and campaigns are entities. A cookie's creation event is named `cookie_issued`.

`uv run dataset build cliquebait` runs `specs/ingest.sql` on the read-only source to make a simkit dataset (an internal stage), then writes it as one log. Entity rows become `<entity>_created` events (or the domain name the recipe gives) at their creation time; business events keep their columns. The log is in `seq` order: event time, then entities before events at the same instant. Each row's `payload` is a JSON object whose fields are listed in `schema/events.json`.

## Event catalogue

| Event | Kind | Rows | Payload fields |
|---|---|---:|---|
| `cookie_issued` | entity | 1,782 | `cookie_key`, `ext_id`, `user_id` |
| `pages_created` | entity | 13 | `page_key`, `ext_id`, `page_name`, `product_category`, `product_id` |
| `event_kinds_created` | entity | 5 | `event_kind_key`, `ext_id`, `event_name` |
| `campaigns_created` | entity | 3 | `campaign_key`, `ext_id`, `products`, `campaign_name`, `start_date`, `end_date` |
| `page_event` | business | 32,734 | `visit_id`, `cookie_key`, `page_key`, `event_kind_key`, `sequence_number` |

## Times set by rule

Page events carry the source's times, with microseconds. A cookie is issued at 00:00:00 UTC of its source `start_date` (the date of its first event). Pages, event kinds and campaigns have no creation time in the source; they are created at the first event time, 2020-01-01 07:44:56.541202. There are no snapshot events, so there is no N.

## Snapshot columns

None: every entity attribute travels in its creation event.

| Column | Verdict | Reason |
|---|---|---|
| `cookies.ext_id` | creation | The source key (`cookie_id`). |
| `cookies.user_id` | creation | The user the cookie was issued to; a cookie never changes owner (one user per cookie). |
| `cookies.start_date` | creation | It decides the creation time (`created_at`); the research shows it is the date of the cookie's first event. |
| `pages.ext_id` | creation | The source key (`page_id`). |
| `pages.page_name` | creation | A given name. |
| `pages.product_category` | creation | The category the page was made with; the hierarchy is static (research). |
| `pages.product_id` | creation | An immutable ref from a product page to its product. |
| `event_kinds.ext_id` | creation | The source key (`event_type`). |
| `event_kinds.event_name` | creation | A given name. |
| `campaigns.ext_id` | creation | The source key (`campaign_id`). |
| `campaigns.campaign_name` | creation | A given name. |
| `campaigns.products` | creation | The product range the campaign was defined for; static (research). |
| `campaigns.start_date` | creation | The planned window, fixed when the campaign is defined; static (research). |
| `campaigns.end_date` | creation | As `start_date`: a planned end, not one observed later. No event carries it, and the research treats campaigns as static labels. |

Domain name: `cookie_issued`, the act the research names for a cookie's first appearance (its `start_date`). Pages, event kinds and campaigns are created at the log's start by rule, which shows no real-world act, so they keep `<entity>_created`.

## Expected output

`results/` holds every source table, as the source stores it. Each column's type follows the values it holds: text, int64 or float64. A mixed column holds text and numbers together, so it is stored as SQLite's own text rendering and declared in `dataset.toml`.

| Table | Rows | Columns | Mixed columns |
|---|---:|---:|---|
| `shopping_cart_users` | 1,782 | 3 | none |
| `shopping_cart_events` | 32,734 | 6 | none |
| `shopping_cart_page_hierarchy` | 13 | 4 | none |
| `shopping_cart_event_identifier` | 5 | 2 | none |
| `shopping_cart_campaign_identifier` | 3 | 5 | none |

`expected/queries/` holds the answers of the saved questions (`local075`), computed on the source. `dataset verify` runs `specs/build.sql` over the log, loads the tables into SQLite with the source's DDL, and compares them and the answers exactly: rows as multisets, numbers by value, text byte for byte.

## Regenerate

```bash
uv run refdata fetch                 # once: the Spider 2.0 SQLite files → data/spider2/
uv run dataset build cliquebait             # → $NEORISK_DATA_ROOT/cliquebait/v1/ (default data/datasets/)
uv run dataset verify cliquebait            # exit 0 = every table and answer matches
```

## Extend

- **More rows:** not possible for a fixed source. Stage 2 will generate logs from `specs/pack.py`.
- **A new event type:** declare it in `specs/pack.py`, add its `-- event: <name> owner=<col>` block to `specs/ingest.sql`, and use it in `specs/build.sql`.
- **A new attribute:** add the column to the pack table and to its ingest block. It then appears in the payload and in `schema/events.json`.
- **A new results table:** add it to `specs/source.toml` and a `-- table: <name>` block to `specs/build.sql`.
- **A new saved question:** add `specs/queries/<id>.sql` (SQLite dialect, source table names).
- **A new engine port:** write `engines/<engine>/` from `specs/build.sql`. It must read only the log and match `results/` exactly.

Any change to `specs/`, `dataset.toml` or the source changes the build. Once a version is recorded in `v1.lock.json`, changed output needs a new version (`v2`).
