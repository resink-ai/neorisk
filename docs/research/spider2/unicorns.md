# modern_data (Spider 2.0-lite), companies_* tables: reverse-engineering the unicorn list into an event log

Source: `data/spider2/modern_data.sqlite`, opened read-only (`sqlite3 -readonly`, `python3 -I` with `mode=ro`).
Scripts: [`scripts/unicorns/`](scripts/unicorns/) (`00_fetch_gold.sh`, `01_inventory.sql`, `02_order.py`, `03_values.sql`, `04_local049.sql`, `05_dists.py`, gold CSVs in `gold/`), plus the cross-table fingerprint [`scripts/modern_misc/05_dup_fingerprint.py`](scripts/modern_misc/05_dup_fingerprint.py). Each script's raw output is the `out_<script>.txt` next to it.

## 0. What this catalog is

Three tables keyed by `company_id`: `companies_funding`, `companies_dates`, `companies_industries`. They are the **"Unicorn Companies" list (CB Insights data, distributed by Maven Analytics), in the split used by DataCamp's "Analyzing unicorn companies" SQL project**. That project's schema has the same tables, `dates(company_id, date_joined, year_founded)`, `funding(company_id, valuation, funding, select_investors)` and `industries(company_id, industry)`, plus a `companies` table (name, city, country, continent) that Spider2 **left out**. Evidence:
- 1,074 distinct companies, ids dense 0..1073 (`01_inventory.sql`). That is the row count of the Maven list.
- Joins run 2007-07-02 → 2022-04-05.
- The 15 industry labels include `Fintech`, `Internet software & services` and `"Supply chain, logistics, & delivery"`.
- Valuations are whole billions from $1B to $180B (`03_values.sql`).

The data is **real**: a public snapshot of a commercial database, rounded to $B/$M. Licence: **unstated**. Maven publishes it as free practice data, and the upstream CB Insights list is proprietary.

| Table | Rows | Distinct companies | Role |
|---|---:|---:|---|
| companies_funding | 1,085 | 1,074 | valuation, total funding, investor list |
| companies_dates | 1,085 | 1,074 | date_joined (became a unicorn), year_founded |
| companies_industries | 1,085 | 1,074 | one industry per company |

**Spider2 added 11 duplicate rows to each table.** Rows 1–11 of each table are exact copies of rows further down, and each table's 11 are *different companies*: 0 overlap between the three sets (`01_inventory.sql`). 11 = round(1% × 1,074). The same "prepend round(1%) copies" pattern appears in every non-pizza table of `modern_data` (§4, `modern_misc/05_dup_fingerprint.py`).

### 0.1 How Spider 2.0 uses it

`db == modern_data` has 7 questions. One of them uses these tables:

| id | Asks | Gold SQL? | Reproduced here? |
|---|---|---|---|
| local049 | Average number of new unicorns per year in the top industry, 2019–2021 | no (404); CSVs `_a`, `_b` | **Yes, both** (`04_local049.sql`) |

- **`_b` = 57.666667.** Deduplicate each table, join dates ⋈ industries, and take the top industry for 2019–2021: Fintech, with 173 = 20 + 15 + 138. 173 / 3 = 57.67.
- **`_a` = 60.333333.** The same over the raw rows, also joining `companies_funding`, as the DataCamp project's 3-table join does. Its duplicates fan out to 181 Fintech rows. A 2-table raw join gives 179 → 59.67, which matches neither.
- So the accepted answers **depend on the injected duplicates**. The rebuild must reproduce them row for row, not deduplicate.

Out of scope here: local040, local041 (trees, see `trees.md`), local201 (word_list, `modern_misc.md`), local065/066/073 (pizza, `pizzarunner.md`).

## 1. Inventory, keys, joins

| Table | Key (verified) | Notes |
|---|---|---|
| companies_funding | company_id, **after removing rows 1–11** | 11 ids appear twice, and the copies are identical in all columns |
| companies_dates | the same | 11 other ids appear twice |
| companies_industries | the same | 11 more ids appear twice |

From `01_inventory.sql` and `02_order.py`:
- No FKs are declared. All three tables cover the same 1,074 ids: 0 missing from 0..1073, 0 orphans.
- The relation is 1:1:1 on company_id. There is no company name, city or country, because the `companies` table is absent.
- **Physical order.** Rows 12..1085 of `dates` and `industries` hold the same permutation of ids (0 differing difflib opcodes). That permutation is not sorted by id (538 ascents, 535 descents) or by date.
  - `funding` follows the same permutation except for **3 rows moved earlier**: ids 1005, 506 and 292 (`02_order.py`).
  - The funding = 0 rows sit at the end: rows 1074–1085, plus row 12 (`03_values.sql`).
  - The tables compare as multisets, so none of this physical order needs to survive.
- **No derived tables.** Each table has columns the others lack.

## 2. Event catalogue

A company enters the list on `date_joined`. That date is the one natural time in the catalog, and it is a date, not a moment.

| Event / entity | Owner | Time | Attributes | Source rows | Count |
|---|---|---|---|---:|---:|
| `companies` entity → `unicorn_joined` (its `_created` event) | company_id | **natural:** date_joined 00:00 | industry `cat`(15), year_founded `i32`, ext_id | the distinct rows of dates ⋈ industries | 1,074 |
| `companies_snapshot` | company_id | **rule:** N | valuation `i64`, funding `i64`, select_investors `opt(text)` | the distinct funding rows | 1,074 |
| `source_row_duplicated` | company_id | **rule:** N | table `cat`(funding, dates, industries) | rows 1–11 of each table | 33 |

**3 event types, 1 entity, 2,181 events.**

- **Snapshot columns: valuation, funding, select_investors.** They are values as of the list's date: the latest valuation, lifetime funding, current notable investors. They are not values at joining. Nothing in the data dates them, so they must not travel in a creation event that is stamped up to 15 years earlier.
- **year_founded** is a year only. It could become a `company_founded` event on 1 January, but that would be imposed (1919 to 2021), and one company was "founded" after it joined (§4). Keep it as an attribute.
- **Not entities:**
  - **Industries:** a 15-value category, not a table with its own rows.
  - **Investors:** 1,254 distinct names inside a quoted comma list. No question splits it, so it stays verbatim text.
  - **The absent `companies` table:** nothing to rebuild.
- **The duplicates are not business events.** They are a benchmark artefact (§4), so they get their own event type. Stage 2 must not learn from them. It can drop that one event type and keep everything else.

## 3. Rebuild rules and blockers to an exact round trip

Views (DuckDB over the log):
- **companies_dates** = for each `unicorn_joined`: company_id, `strftime(event_time, '%Y-%m-%dT%H:%M:%S') || '.000'`, year_founded.
  - Every value is exactly `YYYY-MM-DDT00:00:00.000`, 23 characters (1,085/1,085), and 0 dates are invalid (`01_inventory.sql`).
  - Then `UNION ALL` the same row for each `source_row_duplicated` with table = 'dates'.
- **companies_industries** = (company_id, industry), plus its duplicates.
- **companies_funding** = (company_id, valuation, funding, select_investors) from the snapshot, plus its duplicates.

Blockers and rules:
1. **Duplicates must be rebuilt, not cleaned.** local049's `_a` needs them. With the dup event the round trip is exact, because tables compare as multisets.
2. **select_investors keeps its CSV quotes.** 1,027 of 1,073 non-NULL lists are wrapped in literal `"…"`: exactly those with a comma (0 quoted lists lack a comma, and 0 lists with a comma lack quotes). The industry `"Supply chain, logistics, & delivery"` is quoted the same way (57 rows).
   - Two lists contain an empty item, `,,`: rows 377 and 647. One repeats an investor: id 1025 lists Andreessen Horowitz twice.
   - All of this is byte-exact `text`.
   - 1 list is NULL: company 629, not `''`.
3. **Integers stay integers.** valuation and funding are INTEGER in all rows: valuations are multiples of 1e9, funding multiples of 1e6. Use `i64`, not `amount()`. They are whole dollars, and the largest, 180e9, fits easily.
4. **The time is midnight UTC by convention.** date_joined has no zone, and the `.000` is a format, not precision.
5. **Snapshot time N** ≥ 2022-04-05, the last join. N is a rule. The list's real "as of" date is not in the data.

Verdict: **exact round trip feasible**. All 3 tables come from 1,074 company entities, 1,074 snapshots and 33 duplicate markers. No derived tables.

## 4. Measured quirks

- **Injected duplicates:** rows 1–11 of each table are copies of rows 12+, 11 = round(1% of 1,074). Seven tables in this file show the same pattern (`modern_misc/05_dup_fingerprint.py`): companies ×3, trees, income_trees, statistics, word_list. The three companies tables duplicate **disjoint** company sets, so a join over raw rows inflates by different companies depending on which tables it touches. That is exactly local049's `_a`/`_b` split.
- **funding = 0 on 13 companies** (`03_values.sql`). These are the original list's "Unknown". The 0 is a sentinel, not a real zero. Any "average funding" over raw rows is biased by it.
- **Funding > valuation on 5 companies**: four at $2B on a $1B valuation, and one at $3B on $2B. Funding ≥ $1B is rounded to whole billions (114 values are multiples of 1e9), so these are rounding artefacts of the "$2B" text.
- **Founded after joining:** company 714 joined 2017-10-17 with year_founded 2021. Nine companies joined in their founding year. The largest gap is 98 years: founded 1919.
- **Weekday mix of date_joined (`03_values.sql`):** Tue 308, Wed 263, Thu 214, Mon 192, Fri 75, Sun 12, Sat 10. Announcements cluster on weekdays.
- **Bursts:** 639 distinct join dates for 1,074 companies, with up to 9 on one day.
- **4-item investor lists:** 8. The rest have 1–3 items (`03_values.sql`).

## 5. Distributions to fit (stage 2)

From `05_dists.py` and `03_values.sql`, over 1,074 companies:
- **Arrivals (joins per year):** 2007 1, 2011 2, 2012 4, 2013 3, 2014 13, 2015 35, 2016 21, 2017 44, 2018 103, 2019 104, 2020 108, **2021 520**, 2022 (to 04-05) 116. That is a regime change in 2021. Monthly 2021: 22–55 joins per month. In 2021, 59.5% of consecutive joins fall on the same day as the previous one.
- **Valuation ($B):** p10 1, median 2, p75 3, p90 6, p99 32, max 180, mean 3.46. 30 distinct values; 471 at exactly $1B. A Pareto fit with xmin = 1 gives α = 1.40 (MLE).
- **Funding ($M, the 1,061 with funding > 0):** p10 142, median 370, p90 1,000, p99 4,000, max 14,000. log10(funding/valuation) has mean −0.74 and sd 0.33.
- **Age at joining (years):** p10 2, median 6, p90 13, mean 7.0.
- **Industry mix:** Fintech 224, Internet software & services 205, E-commerce & DTC 111, AI 84, Health 74, Other 58, Supply chain 57, Cybersecurity 50, Data mgmt 41, Mobile & telecom 38, Hardware 34, Auto 31, Edtech 28, Consumer & retail 25, Travel 14.
- **Investor lists:** 3 items 937, 2 items 82, 1 item 46, 4 items 8, NULL 1. 1,254 distinct investors; the top are Accel 60, Tiger Global 53 and a16z 53.

## 6. simkit mapping sketch

```python
p.entity("companies", key="company_key", doc="A unicorn; created_at = date_joined (natural, midnight)",
         cols={"ext_id": text(doc="company_id"), "industry": cat(*INDUSTRIES),   # verbatim, incl. the quoted one
               "year_founded": i32()})
p.event("companies_snapshot", doc="As-of-N values: current valuation, lifetime funding, investors",
        cols={"company_id": ref("companies"), "valuation": i64(), "funding": i64(doc="0 = unknown in the source"),
              "select_investors": opt(text(doc="Verbatim, CSV-quoted when it has a comma"))})
p.event("source_row_duplicated", doc="Spider2 artefact: an extra identical row in one source table",
        cols={"company_id": ref("companies"), "table": cat("funding", "dates", "industries")})
```

- **Ingest:**
  - `-- entity: companies` from `SELECT DISTINCT` dates ⋈ industries, with created_at `substr(date_joined,1,10) || ' 00:00:00'`, `ORDER BY company_id`.
  - `-- event: companies_snapshot owner=company_id` from `SELECT DISTINCT * FROM companies_funding`, at N, `ORDER BY company_id`.
  - `-- event: source_row_duplicated owner=company_id ord=src_rowid`: one row per rowid 1–11 of each table, at N, `ORDER BY table, rowid`.
- **build.sql:** three blocks, each "base row from the entity or snapshot, `UNION ALL` the duplicated rows for that table", as in §3.
- **Saved query:** local049 with the `_a` reading (raw 3-table join, 60.333333). Optionally the `_b` reading (deduplicated, 57.666667) as a second query: it checks that the duplicate markers land on the right table.
- **Stage 2:** a Source of companies with yearly-varying intensity (the 2021 jump), a Pareto valuation, funding ≈ valuation × 10^N(−0.74, 0.33) rounded to the source's grid, and industry and investor categoricals.
  - Laws that hold: `year_founded ≤ year(date_joined)` **fails once**, so do not make it a law.
  - `valuation ≥ 1e9` holds (min 1e9).

## 7. Open questions and risks

- **The `companies` table is missing.** No question needs it, but country and city are gone. Stage 2 cannot model geography.
- **Snapshot date N.** The data has no "as of". Is N = 2022-04-05 (the last join) right, or should it be the source's publication date?
- **Should funding = 0 become NULL in the events, with the view writing 0?** That would be truer, but the view must still emit the integer 0. Keep the 0 and document it.
- **The 3 rows moved within `companies_funding`'s physical order** (ids 1005, 506, 292) suggest the funding table was sorted or re-written separately. That is harmless for multiset compare. Questions relying on rowid (none do) would notice.
- **The duplicate injection is a Spider2-lite artefact.** If a future Spider2 release drops it, local049 `_a` changes and the dup events go.

## Summary

1. **Feasible:** yes. All 3 tables rebuild exactly from one company entity, an as-of-N snapshot, and explicit duplicate-row markers. The dates' `T00:00:00.000` text and the CSV-quoted investor lists are kept verbatim.
2. **Dataset name:** `unicorns` (modern_data, companies_*). Saved query: local049 (`_a` = 60.333333; `_b` = 57.666667 reproduced too).
3. **Events and entities:** 3 event types (`unicorn_joined` as companies_created 1,074, `companies_snapshot` 1,074, `source_row_duplicated` 33), 1 entity (`companies`, 1,074).
4. **How event-shaped:** partly imposed. The join date is a natural arrival time; valuation, funding and investors are an as-of snapshot at a rule time N.
5. **Hardest blocker:** Spider2's injected duplicate rows: 11 per table, each table a different company set. They are invisible to a key-based model, yet local049's accepted `_a` answer depends on them, so they need their own marker event.
