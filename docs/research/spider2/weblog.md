# log (Spider 2.0-lite): reverse-engineering a textbook's teaching tables into one event log

Source: `data/spider2/log.sqlite` (120 KB, 19 tables, 854 rows), opened read-only (`mode=ro` URIs, `python3 -I`).
Scripts: [`scripts/weblog/`](scripts/weblog/). `wq.py DB FILE.sql` runs the `-- name:` blocks of a query file and prints values with `repr()`, so NULL, `''` and trailing spaces stay visible. Every output is saved next to its script as `*.out.txt`. A reference such as `[q2:invalid_vs_action_log]` means file `q2_relations.sql`, block `invalid_vs_action_log`. `[blocks]`, `[pii]`, `[proto]` and `[order]` mean `blocks.py`, `pii.py`, `roundtrip_proto.py` and `order_check.py`.

## 0. What this catalog is

- **Origin: the sample data of the Japanese book *ビッグデータ分析・活用のためのSQLレシピ*** ("SQL recipes for big-data analysis", Kaga and Tamiya, Mynavi, 2017). The evidence:
  - The table names match the book's recipes one for one: `mst_users_with_card_number` (chapter 3, NULL handling), `purchase_log` and `access_log` (chapter 6), and `action_log_with_noise`, `invalid_action_log`, `action_log_with_ip`, `dup_action_log`, `mst_products_20161201/20170101` (chapter 7, data cleaning and master diffs). A reader's chapter notes in https://github.com/nonsabotage/SQL4BIGDATA query exactly these tables.
  - That repository's README warns that "chapters share table names, but the contents differ, so recreate the tables before each chapter". Spider's file looks like the result of **not** doing that: it seems to hold several chapters' inserts in one table (§4.1). The strongest sign is `access_log`. Its 19 later rows are the book's other `access_log` layout, `(stamp, short_session, long_session, path)`, inserted by position into `(session, user_id, action, stamp)` [q1:access_log_shift]. The notes' chapter 7 queries use `long_session`, `short_session` and `path` on `access_log`.
  - The ids are textbook placeholders: users `U001`..`U030`; 8-hex sessions (`989004ea`); 6-character sessions (`0CVKaz`); products `A001`, `D002`; names `AAA`, `DAD`; `example.com` emails; masked phones `080-xxxx-xxxx`; and a 2-row `app1/app2` pair for a recipe that joins two apps' user masters [pii].
- **It is hand-written course data.** Nothing is real, anonymised or simulated at scale. Most tables hold 2–45 distinct rows, and the timestamps sit on whole hours or on one instant (all 16 activity sessions start at `2017-01-09 12:18:43`) [q3:activity_session_starts].
- **Licence: unstated.** I found no licence statement for the book's sample data; I did not check the publisher's support page. Spider 2.0's repository is MIT, but that does not cover the data. Treat it as quotation-scale material: fitting statistics is harmless, but do not redistribute it.

Row counts [q1:rows_and_distinct]:

| Table | Rows | Distinct rows | Table | Rows | Distinct rows |
|---|---:|---:|---|---:|---:|
| access_log | 30 | 30 | mst_users | 320 | 57 |
| action_log | 120 | 16 | mst_users_with_card_number | 3 | 3 |
| action_log_with_ip | 12 | 12 | app1_mst_users | 2 | 2 |
| action_log_with_noise | **0** | 0 | app2_mst_users | 2 | 2 |
| invalid_action_log | 7 | 7 | mst_categories | 8 | 8 |
| dup_action_log | 11 | 11 | mst_products_20161201 | 6 | 6 |
| activity_log | 244 | 68 | mst_products_20170101 | 6 | 6 |
| read_log | 15 | 15 | product_sales | 10 | 10 |
| form_log | 45 | 15 | purchase_log | 5 | 5 |
| form_error_log | 8 | 8 | **total** | **854** [q1:total_rows] | |

## 0.1 How Spider 2.0 uses it

There are 5 questions with `db == "log"` and none has external knowledge. **No gold SQL exists** (all five return 404). Gold result CSVs exist, often in several accepted variants that disagree, which shows that the answers depend on how ties are broken [fetch_gold.sh → `gold/`].

| id | Table | Analysis | Gold variants | Reproduced here |
|---|---|---|---|---|
| local329 | form_log | Sessions that visit `/regist/input` and then `/regist/confirm` | a: 1 | **Yes, exactly: 1** [q4:local329]. Only `46b4c72c` qualifies; `9b5f320f` reaches `/regist/confirm` from `/cart/input` |
| local330 | activity_log | Sessions per page as landing and/or exit page | a, b, c (b and c use the slash-less paths) | **Yes, exactly variant a** (`/detail/` 9, `/search_list/` 7, `/` 2, `/complete` 2, `/search_input/` 2). This uses `ORDER BY stamp` with ties in rowid order [q4:local330_natural]. With strict (stamp, rowid) first and last, it becomes 8 paths [q4:local330_strict_order] |
| local331 | activity_log | The top 3 third pages after two consecutive `/detail` | a: 55/2/2, b: 55/1/1, c: 52/3/2 | **No.** Readings give `/detail` 33 [q4:local331_natural], 57 after folding `/x/` to `/x` [q4:local331_norm_slash], or 0 on distinct rows [q4:local331_dedup]. The three gold variants disagree with each other too |
| local358 | mst_users | Users per age band (20s/30s/40s/50s/others) over all 320 rows | a: 88/24/24/56/128; b: 32/88/32/16/152 (in 30s, 20s, others, 40s, 50s order) | **Yes, both.** a = age in 2016 by year difference, or the exact age on 2017-01-01. b = 2025 by year difference [q4:local358_by_reference_year, local358_exact_age_on_date]. So the gold depends on the date it was run |
| local360 | activity_log | Sessions with the fewest searches (non-empty search_type) before the first `/detail` or `/complete` | a, b, c (they differ only in `/detail` vs `/detail/`) | **Yes, the session set** (9 sessions with 0 such events). The path column matches variant c (`/detail/` for all) [q4:local360_sessions] |

Consequences for the round trip:
- local358 counts the **duplicated** user rows (320, not 30), so the duplicates are data.
- local330, local331 and local360 depend on the order of rows that share a timestamp in one session. In `activity_log` every (session, stamp) group is tied: 36 of 36 groups, 244 rows, and 32 of them mix path variants such as `/detail/` and `/detail` [q3:ties_within_session].
- I rebuilt `activity_log` in memory in four insert orders. Source rowid order, (event_time, src_rowid) order and (event_time, session, src_rowid) order give identical answers to all three. Reverse rowid order changes local330 to the slash-less paths and local331 to 33/11 [order].
- So **`src_rowid` must be the `ord`, and the rebuilt table must be written in seq order.**

## 1. Inventory, keys, joins

| Table | Key (verified) | Kind | Group (by date and content) |
|---|---|---|---|
| access_log | none. Rows 1–11 are (session, user, `view`, stamp); rows 12–30 are **column-shifted** | log | A: 2016-01-01..01-11 (rows 1–11), 2016-10-01..10-03 (rows 12–30) |
| action_log | none (16 distinct of 120) | log | B: e-commerce, 2016-11-03..11-04 |
| action_log_with_ip | session (12 unique) | log | B |
| action_log_with_noise | — (empty) | log | B |
| invalid_action_log | none | log | B |
| dup_action_log | (session, stamp) unique | log | B |
| activity_log | none (68 distinct of 244) | log | C: search site, 2017-01-09 12:18–12:25 |
| read_log | (session, action) unique | log | D: articles, 2016-12-29 21:45–21:46 |
| form_log | none (15 distinct of 45) | log | E: forms, 2016-12-30 00:56–01:00 |
| form_error_log | (session, stamp, field) unique | log | E |
| purchase_log | purchase_id 10001..10005 | log | F: 2017-01-30..03-02 |
| mst_users | **none.** 30 user_ids over 320 rows; 27 of the 30 users have **2 versions** that differ in register_date | master, repeated | users |
| mst_users_with_card_number, app1_mst_users, app2_mst_users | user_id (3, 2, 2) | master, untimed | users |
| mst_categories | (id, stamp). id 6 appears twice: `food`@2016-01-01, then `cooking`@2016-02-01 | SCD master | — |
| mst_products_20161201 / _20170101 | product_id (6 each) | two dated snapshots | B (product ids) |
| product_sales | product_id (10) | aggregate, untimed | — |

Sources: [q1:candidate_keys, q1:mst_users_versions_per_user, q1:time_shapes, q2:categories_scd]

**Shared ids do not make one world** [q2:session_tables, q2:session_overlap_matrix, q2:session_user_conflicts]:
- 14 session ids appear in more than one table.
  - `989004ea`, `47db0370` and `87b5725f` are in action_log, action_log_with_ip, dup_action_log *and* activity_log, but on 2016-11-03/04 in the first three and on **2017-01-09** in activity_log.
  - The 6-character ids `0CVKaz`, `1QceiB` and `1hI43A` are `short_session` values in access_log's shifted rows (2016-10-01), and also sessions in action_log_with_ip and invalid_action_log (2016-11-03).
- Sessions map to conflicting users:
  - `87b5725f` is U001 in action_log and dup_action_log but U005 in action_log_with_ip.
  - `fe05e1d8` is U001 in action_log_with_ip but U004 in dup_action_log.
  - `9afaf87c` is U002 in 5 copies of action_log and U001 in the first copy.
  - `eee2b2` is U002 and U001 in access_log.
- Every user_id in every log exists in mst_users (U001–U008 at most) [q2:user_ids_by_table]. But mst_users has no single version per user, so there is nothing to join to.
- form_error_log's 5 sessions share **0** sessions with form_log's 7 [q2:form_error_vs_form_log].
- purchase_log amounts (200–800) match no action_log purchase (1000/2000) [q2:purchase_log_vs_action_log].
- The category names in action_log (`drama`, `action`), product_sales (`dvd`, `cd`, `book`) and mst_categories (8 names) do not overlap except `dvd` and `book` [q2:category_names_across_tables].
- product ids: action_log uses A004–A006, D001, D002. The masters hold A001, A002, B001, B002, C001, D001, D002. product_sales holds B001–B004, C001–C003, D001–D003 [q2:product_ids_across_tables].

**Are the variant tables exact functions of a base table?** No. Each is a separate hand-made sample, though some are visibly built from another:

| Variant | Relation measured | Verdict |
|---|---|---|
| invalid_action_log | 5 of 7 rows equal an action_log row in every column except session, with the session renamed to `0CVKaz` or `1QceiB`. The other 2 equal an action_log row once you allow for a NULL that was put in on purpose: row 5 has `products` NULL, row 7 has `stamp` NULL [q2:invalid_vs_action_log] | built from action_log by hand. Not derivable: the session rename has no rule, and the nulls were chosen |
| action_log_with_ip | Only 1 of 12 rows (`989004ea`/U001/view 18:00) exists in action_log [q2:with_ip_vs_others]. For 10 of 12, (user_id, stamp) also exists in dup_action_log; 7 of those have the same session. Every user has exactly one IP [q2:ip_per_user] | independent sample |
| dup_action_log | All actions are `click`; action_log has none. It has one near-duplicate pair, rows 10 and 11: same session, user and product, 10 s apart [q2:dup_near_duplicates] | independent sample |
| action_log_with_noise | 0 rows; the book's crawler and noise rows were not loaded | empty; the schema only |
| mst_products_20170101 | It equals 20161201 with B001 deleted, C001 repriced 4000 → 5000 (updated 2016-12-04 18:00) and D002 added (2016-12-04 19:00). 4 rows are unchanged. Every updated_at is before its snapshot date [q2:products_snapshot_diff, q2:products_updated_before_snapshot] | **both are exact functions of an 8-update, 1-delete change log** (§3) |

**Decision: one project, `weblog`.**
- The groups share no consistent entity, so splitting them would not give more structure: each would still be a set of independent tables.
- The whole file is 854 rows, and Spider's 5 questions read 3 of its tables.
- One project keeps the catalog in one round trip and one `source.toml`.
- Within it, every source log stays its own event table, and nothing is joined across groups.

## 2. Event catalog

Snapshot time **N = 2017-03-02 10:00:00**, the latest time in the file (purchase_log) [q1:global_time_range]. Times are naive wall clock, read as UTC. Every source row becomes exactly one event or entity row, except the two product snapshots, which become a change log. Counts are from [proto].

| # | Event | Owner (ingest) | Time | Attributes | From | Count |
|---|---|---|---|---|---|---:|
| E1 | `access_logged` | session text | `stamp`; **for shifted rows, `session`** (the column that holds the time) | shifted (bool), session opt, user_id, action, path_in_stamp opt, src_rowid | access_log | 30 |
| E2 | `action_logged` | session | stamp | user_id, action cat(view, favorite, review, add_cart, purchase), category opt, products opt text (comma list kept verbatim), amount opt `amount(JPY)`, src_rowid | action_log | 120 |
| E3 | `action_with_ip_logged` | session | stamp | user_id, action, ip text, src_rowid | action_log_with_ip | 12 |
| E4 | `noisy_action_logged` | session | stamp | products, url, ip, user_agent (text, opt) | action_log_with_noise | **0** |
| E5 | `dup_action_logged` | session | stamp | user_id, action, products, src_rowid | dup_action_log | 11 |
| E6 | `invalid_action_logged` | session | stamp; **rule** for the one NULL stamp | stamp_null (bool), user_id, action, category opt, products opt, amount opt, src_rowid | invalid_action_log | 7 |
| E7 | `activity_logged` | session | stamp | action, option cat(search, page, detail), path text, search_type text, **src_rowid (ord)** | activity_log | 244 |
| E8 | `read_logged` | session | stamp | action text (`view`, `read-20%`..`read-100%`), url, src_rowid | read_log | 15 |
| E9 | `form_viewed` | session | stamp | action, path, status (`''` or `error`), src_rowid | form_log | 45 |
| E10 | `form_error_logged` | session | stamp | form, field, error_type, value text, src_rowid | form_error_log | 8 |
| E11 | `purchase_logged` | user_id | stamp | purchase_id i64, amount `amount(JPY)` | purchase_log | 5 |
| E12 | `user_registered` | user_id | register_date 00:00:00 | sex cat(M, F), birth_date text, register_device cat(pc, sp, app), withdraw_date opt text, src_rowid | mst_users, one per row including duplicates | 320 |
| E13 | `category_named` | id | stamp | id i64, name text | mst_categories | 8 |
| E14 | `product_updated` | product_id | updated_at | name, price `amount(JPY)` | the 6 rows of 20161201, plus the 2 rows of 20170101 that differ | 8 |
| E15 | `product_deleted` | product_id | **rule:** 2016-12-01 00:00:00 | — | B001, absent from 20170101 | 1 |
| | **events** | | | | | **834** |

| Entity | Key / ext_id | Columns | created_at | Rows |
|---|---|---|---|---:|
| `app1_users` | user_id | name, email | rule: 2016-01-01 00:00:00 | 2 |
| `app2_users` | user_id | name, phone | rule | 2 |
| `user_cards` | user_id | card_number opt text | rule | 3 |
| `product_sales` | product_id | category_name, sales i64 | rule | 10 |
| | | | | **17** |

What is **not** an entity, and why:
- **users.** mst_users has 2 versions for 27 of 30 users, plus 8 or 16 copies of each, and local358 counts the copies. An entity keyed by user_id would lose rows. So each row is a `user_registered` event, and user_id stays text everywhere: access_log's shifted rows have non-user values in `user_id`, so `ref()` would fail.
- **sessions.** They are not one object across tables (§1), so session is only the ingest owner column, per table.
- **products and categories.** Their tables are versioned (two snapshots, and an SCD on id 6), so they are change events, not static rows.
- `product_sales` *is* a static entity: it is an untimed aggregate that no log in the file can produce (D001 has 50000 in sales; action_log's D001 revenue is 1000s).
- `app1_users`, `app2_users` and `user_cards` are untimed lookups, so they are entities with a rule time.

## 3. Rebuild rules and blockers to an exact round trip

The prototype `roundtrip_proto.py` builds the 834 events and 17 entity rows above in Python, rebuilds all 19 tables and compares them as type-aware multisets. **All 19 are equal** [proto]. The rules it uses:

1. **Time text.** Every timestamp is `YYYY-MM-DD HH:MM:SS`, 19 characters, with no fraction and no zone, in 17 columns [q1:time_shapes]. mst_users dates are `YYYY-MM-DD`. The views use `strftime('%Y-%m-%d %H:%M:%S')` and `'%Y-%m-%d'`. There are no `'\N'` strings, untrimmed values or trailing spaces anywhere [q1:backslash_N_anywhere].
2. **access_log column shift (19 rows, rowids 12–30).** In those rows `session` holds a valid time (19/19), `user_id` a 6-character short session, `action` a 6-character long session, and `stamp` a path (`/detail`, `/search`, `/top`) [q1:access_log_shift, q1:access_log_shift_summary].
   - Rule: `shifted = datetime(stamp) IS NULL`, and event_time = `session` when shifted, else `stamp`.
   - Views: `session = CASE WHEN shifted THEN strftime(event_time) ELSE session END`, `stamp = CASE WHEN shifted THEN path_in_stamp ELSE strftime(event_time) END`.
   - This is byte-exact, and the rows keep their real times. The alternative, keeping all four columns as text with a rule time, would also work, but it throws away a recoverable time.
3. **invalid_action_log NULL stamp (rowid 7).** Rule: the latest stamp of an earlier row in the same session, 2016-11-04 13:00:00 [proto]. The flag `stamp_null` makes the view write NULL back. The (deliberately) NULL products in row 5 are an opt column. The matching action_log row says 15:00, but the table is not derived from action_log, so that time is not used.
4. **Product snapshots as a change log.**
   - `mst_products_YYYYMMDD` = for each product, the latest `product_updated` with event_time < the snapshot date, unless a later `product_deleted` also falls before it. updated_at = strftime(event_time).
   - B001's deletion is not observed: it happened somewhere in [2016-12-01, 2017-01-01). Rule: at 2016-12-01 00:00:00, which is excluded from the 20161201 cut by the strict `<`.
   - Both snapshots rebuild exactly [proto].
5. **Untimed rows.** These are the 17 entity rows. Rule: created_at = 2016-01-01 00:00:00, the first day of the catalog (its earliest time is mst_categories' 2016-01-01 10:00:00). This is ≤ N.
6. **Duplicates are data.** action_log has 16 distinct rows in 120, activity_log 68 in 244, form_log 15 in 45 and mst_users 57 in 320 [q1:rows_and_distinct]. The ingest emits one event per row, and multiset compare does the rest. No dedup, anywhere.
7. **Row order.** The rebuilt `activity_log` must be inserted in (event_time, src_rowid) order (§0.1, [order]). The same `ord = src_rowid` is harmless and cheap for all logs.
   - action_log is not time-ordered inside a session: 6 descents within a session, e.g. each copy's `purchase 18:10` comes before its `view 18:00` [q3:rowid_time_descents, q3:action_log_block_order].
   - No query reads action_log, so for that table only multiset equality is needed.
8. **Money.** Every amount and price is a whole yen: action_log 1000/2000, purchase_log 200–800, prices 3000–5000. As `amount(JPY)` in minor units ×100 (as the prototype does), or ×1 if JPY is declared with 0 decimals. `product_sales.sales` is an aggregate, so it is i64, not money.
9. **The empty table.** `action_log_with_noise` must exist with its 7 columns, including the two declared `text` (url, user_agent) rather than varchar. Its view is `SELECT … FROM noisy_action_logged` over an empty Parquet file.
10. **Floats.** There are none. Every number is an INTEGER.

## 4. Measured quirks

### 4.1 Concatenated chapter inserts (block structure, [blocks])

| Table | Structure in rowid order | Difference between versions |
|---|---|---|
| action_log | 20-row block × 6 (rows 1–120) | Version 1 differs in **1 cell**: row 20 has user_id `U001`; copies 2–6 have `U002` |
| activity_log | A (32 rows) × 2, then B (36) × 3, then C (36) × 2 | A uses trailing-slash paths (`/detail/`, root `/`). B has none, and root is `''` (12 rows). C = B with root `/` (4 cells per copy, 0 other differences [q3:activity_B_vs_C]). B adds 4 conversion rows: `9afaf87c` `/input → /confirm → /complete`, and `8cc03a54` `/input → /confirm → /complete` at 1-second steps, carrying search_type `Area-L`. It drops 2 rows of A [q3:activity_A_vs_B_normalised, q3:activity_variant_counts] |
| form_log | 15-row block × 3 | identical |
| mst_users | 10-user block × 8, then 20 users U011–U030 once, then 30-user block V2 × 7, then the 10-user block once | V1 (rows 71–100) spreads register_date over 2016-10-01..11-28. V2 (rows 101–130) collapses it to 10-01 (U001–U019) and 10-02 (U020–U030). Sex, birth date, device and withdraw date are the same in both [blocks, q3:mst_users_mix_variant]. U001–U010 have 16 rows each and U011–U030 have 8 [q1:mst_users_versions_per_user] |

The copy counts (×6, ×2/×3/×2, ×3, ×8/×7) look like the number of recipes, each re-inserting its sample table. This is an inference: Spider's build script is not published.

### 4.2 Dirty rows that are meant to be dirty

- access_log: the 19 column-shifted rows (§3.2). They are probably an accident of loading, not a lesson, but they must round-trip either way.
- invalid_action_log: one NULL stamp, one NULL products on an `add_cart` row, one NULL category with NULL products on `view` (normal in action_log too), and 4 NULL amounts on non-purchases [q1:null_and_empty_counts].
- dup_action_log: rows 10 and 11 are the same click 10 s apart (the dedup recipe). Separately, U001 clicks D001 in two sessions a day apart [q2:dup_same_user_product_any_session].
- form_error_log `value` holds deliberately bad inputs. As shapes, not values [pii]: `''` × 3 (require), `999-` (zip), `aaa---.aa.aa` and `aaa@---aaaa` (email), `99-99999999` (tel), and a kanji name with an ASCII space (bytes `e5 b1 b1 e7 94 b0 20 …`, so it is not U+3000) under `not_kana`. That last value is the only non-ASCII text in the file [q1:backslash_N_anywhere].
- `''` versus NULL: activity_log search_type has 164 `''` and path 12 `''`, and form_log status has 30 `''`. None of these columns contains NULL. In action_log, NULLs appear only in category, products and amount [q1:null_and_empty_counts].

### 4.3 Personal-looking columns (all fake)

- **`mst_users_with_card_number.card_number`:**
  - Two values have the shape `9999-xxxx-xxxx-xxxx`: 19 characters, **4 digits** and 12 literal `x` mask characters. The third user has NULL.
  - The 4 digits are a run of consecutive digits in both values (sequential placeholders).
  - With 4 digits there is no full PAN, so a Luhn check is impossible, and they cannot be a real or a test card number [pii].
  - It is the book's NULL-handling example (`card_number IS NOT NULL → has_card`).
- **`app2_mst_users.phone`:** the shape `999-xxxx-xxxx`, masked.
- **`app1_mst_users.email`:** at `example.com`, which RFC 2606 reserves [pii].
- **`action_log_with_ip.ip`** is a classification exercise [pii]:
  - 3 globally routable addresses, one per user U001–U003. They look like big-portal ranges, but the owners were not verified.
  - `127.0.0.1` (loopback).
  - `10.0.0.3`, `172.16.0.5` and `192.168.0.23` (RFC 1918).
  - `192.0.0.10`, in the IANA special block 192.0.0.0/24. Python's `ipaddress` flags it as globally reachable, because .10 is the TURN anycast exception.

### 4.4 Other fingerprints

- Times are on round hours in the action group: 0 rows with non-zero seconds in action_log, action_log_with_ip and access_log [q1:time_shapes].
- All 16 activity sessions start at the same second, 12:18:43 [q3:activity_session_starts]. All 7 form sessions start at 00:56:08, and all 6 read sessions at 21:45:47 [q3:form_log_flow, q3:read_log_flow].
- mst_users is balanced by design. V1 has F 15 and M 15, with devices pc 11, app 11, sp 8. Birth decades: 1950s 8, 1960s 4, 1970s 4, 1980s 3, 1990s 6, 2000s 5. Two users were born in 2006 and 2009, so they were 7–10 when they registered [q3:mst_users_mix_variant, q3:birth_year_hist].
- Withdrawals: U002 and U006 withdraw on 2016-10-10. U006's V1 row registers and withdraws on the same day [q3:mst_users_withdraw].
- action_log purchase amounts are 1000 × the number of products for drama (1000 or 2000), but `A005,A006` costs 1000. Prices do not tie to either product master [q3:purchase_amount_vs_products].

## 5. Distributions to fit (stage 2)

This is a tutorial file: the "distributions" are a handful of hand-placed rows. Fitting them gives shapes and vocabularies, not rates. Each figure is on **one copy** of each block.

- **activity (block B, 16 sessions, 36 rows)** [q3:activity_events_per_session_B, q3:activity_gaps, q3:activity_vocab]:
  - Events per session: 1 → 9 sessions, 2 → 2, 3 → 1, 4 → 2, 5 → 1, 7 → 1. Mean 2.25.
  - Gaps between distinct stamps: 20 in all, with a median of 51.5 s [q3:activity_gap_median]. Three are 1 s (the scripted `input → confirm → complete`); the other 17 are 8–99 s.
  - Options: detail 11, page 15, search 10 [q3:activity_B_option_mix]. search_type takes 8 values; it is `''` on non-search rows, and on 1 search row.
  - Conversion: 2 of 16 sessions reach `/complete`.
- **forms (7 sessions)** [q3:form_log_flow, q3:form_status_counts]:
  - The flow is input → confirm → complete, with `error` loops: `9b5f320f` errors 4 times on `/regist/confirm`, and `b2dbcc54` errors once, then completes.
  - Status mix: `error` 5 of 15 rows. Completion: 1 of 7 sessions.
  - Error mix: require 3, format_error 4, not_kana 1. Fields: email 3, kana 3, zip 1, tel 1 [q3:form_error_vocab].
- **reading (6 sessions)** [q3:read_depth_distribution, q3:read_log_flow]:
  - Maximum depth: view only 3, 20% 1, 60% 1, 100% 1.
  - About 2–9 s per 20% step. The longest session (100%) takes 38 s.
- **e-commerce (action_log block, 20 rows, 4 sessions)** [q3:action_log_one_copy_mix, q3:action_log_vocab]:
  - Per copy: add_cart 12, purchase 5, view 1, favorite 1, review 1. Categories: drama, action.
  - Basket sizes: 1–2 products.
- **users (V1)** [q3:mst_users_register_by_month_V1]:
  - Registrations: 14 in October and 16 in November 2016.
  - Withdrawal: 2 of 30.
  - Sex 50/50; device pc 37%, app 37%, sp 27%.
- **purchases:** 5 orders from 2 users, 200–800 yen, 2017-01-30..03-02.

## 6. simkit mapping sketch

- **Pack `weblog`**, stage 1 schema only:
  - Entities `app1_users`, `app2_users`, `user_cards`, `product_sales`: `ext_id` text plus their columns; `card_number` is `opt(text)`; `sales` is `i64`.
  - Events E1–E15 as in §2, with these types:
    - `session` and `user_id`: `text` (or `opt(text)` for E1.session).
    - `products`, `path`, `url`, `value`, `search_type`, `birth_date` and `withdraw_date`: `text` or `opt(text)`.
    - `action` and `option`: `cat` where the vocabulary is closed (action_log, activity_log). read_log's `read-NN%` stays text.
    - `amount` and `price`: `amount("JPY")` (opt in E2 and E6).
    - `purchase_id` and category `id`: `i64`.
    - `src_rowid`: `i64`.
    - The flags `shifted` and `stamp_null`: `boolean`.
- **ingest.sql:**
  - One block per event and entity.
  - Header owners: `owner=session` for E1–E10, `owner=user_id` for E11–E12, `owner=id` for E13, `owner=product_id` for E14–E15.
  - **`ord=src_rowid`** on every log block, and `ORDER BY rowid`.
  - E1 uses `CASE WHEN datetime(stamp) IS NULL THEN session ELSE stamp END` as event_time.
  - E6 uses a window `max(stamp) OVER (PARTITION BY session ORDER BY rowid ROWS UNBOUNDED PRECEDING)` for the NULL-stamp row.
  - E14 is a `UNION` of the first snapshot and the rows of the second that differ (`EXCEPT`).
  - E15 is a constant `'2016-12-01 00:00:00'` for ids missing from the second snapshot.
- **views.sql:**
  - One block per source table.
  - activity_log, and for safety every log, `ORDER BY event_time, src_rowid` (= seq) before writing.
  - The two product snapshots use `arg_max` over events with event_time < cut, minus deletions.
  - `action_log_with_noise` reads its empty event file.
- **source.toml:** keys only for sorting diffs, e.g. activity_log `["session","stamp"]` and mst_users `["user_id","register_date"]`. Saved queries: local329, local330 (natural reading), local358 (reference year fixed at 2016 so it is deterministic; the gold's dependence on the run date should not leak in) and local360. Skip local331, since no reading reproduces its gold.
- **Stage 2:**
  - Little to simulate. An owner `session` machine per group (search → detail → input → confirm → complete with an error loop; read-depth steps at U(2, 9) s; cart → purchase) plus a `user` source.
  - The value of this pack is as a **round-trip and dirty-data harness**: column shift, NULL vs `''`, deliberate duplicates, snapshot diffs, tie order. It is not useful for realism.

## 7. Open questions and risks

- **Provenance detail.** The book is identified from the table names and recipes; I did not see Spider's build script. The chapter-concatenation explanation of the copies (×6, ×8, …) is an inference from the layout and the shift.
- **Licence** is unstated for the book's sample data. Keep it to a local copy for stage 1.
- **Tie order is load-bearing.** The answers to local330 and local360 hold only while `activity_log` is written in source rowid order among equal stamps, and the saved-query harness indexes tables on `source.toml` keys. An index on (session, stamp) could let SQLite read ties in a different order on the two files. This needs a check once the project exists; if it bites, drop the key from `source.toml`.
- **local331** reproduces none of the three gold variants (55/2/2, 55/1/1, 52/3/2). Its question is ambiguous over duplicates and over `/detail` vs `/detail/`.
- **local358's gold** depends on the date it was run (2016-based vs 2025-based answers). A saved query must pin the reference date.
- **Rule times:** 1 NULL stamp, 1 unobserved product deletion and 17 untimed entity rows. Stage 2 must not fit anything to them.
- **One project vs several.** If later packs want a coherent world (users ↔ sessions ↔ purchases), this file cannot supply it: the sessions and users conflict across tables (§1). Splitting it into five tiny projects would only multiply files.
