# modern_data (Spider 2.0-lite), trees + income_trees: reverse-engineering the NYC tree census into an event log

Source: `data/spider2/modern_data.sqlite`, opened read-only (`sqlite3 -readonly`, `python3 -I` with `mode=ro`).
Scripts: [`scripts/trees/`](scripts/trees/) (`00_fetch_gold.sh`, `01_inventory.sql`, `02_gold.sql`, `03_quirks.sql`, `04_dists.py`, gold CSVs in `gold/`), plus [`scripts/modern_misc/05_dup_fingerprint.py`](scripts/modern_misc/05_dup_fingerprint.py) for the duplicate pattern. Each script's raw output is the `out_<script>.txt` next to it.

## 0. What this catalog is

### `trees`

`trees` is the **2015 NYC Street Tree Census** (NYC Parks, NYC Open Data). Evidence:
- **683,788 distinct `tree_id`s** (`01_inventory.sql`), which is the census's published tree count.
- The columns are a subset of the census schema: tree_id, tree_dbh, stump_diam, status Alive/Dead/Stump, health Good/Fair/Poor, spc_latin, spc_common, address, zipcode, borocode, boroname, nta_name, state, latitude, longitude.
- `idx` (0..683787) is a pandas index, added when the table was exported.
- The census's own `created_at` survey date and its other columns are **not** in this copy.

### `income_trees`

`income_trees` is a per-ZIP household-income table: Estimate/Margin_of_Error of Total households, median income and mean income, for 216 NYC ZIPs. These are American Community Survey estimates. That conclusion rests on the shape alone: the column names follow ACS table S1901, and zero-household ZIPs carry the MOE 11 (§4). The vintage is unknown.

### Data, licence, sizes

The data is **real**. Licence: unstated in Spider2. The tree census is published under the NYC Open Data terms of use, and ACS data is US-government public data.

| Table | Rows | Distinct | Role |
|---|---:|---:|---|
| trees | 690,626 | 683,788 trees | one row per tree, a census snapshot with no time |
| income_trees | 220 | 216 zipcodes | ZIP-level income lookup |

### Duplicates added by Spider2

- **trees:** rows 1–6,838 are exact copies of rows further down. 6,838 = round(1% × 683,788). The base, rows 6,839+, is in `idx` order: 683,787 ascents, 0 descents, ids dense.
- **income_trees:** rows 1–2 are copies, 2 = round(1% × 218).
- **Inside the base**, income_trees also has two zips (10463 and 11370) twice with identical values. These look like duplicates in the upstream table itself (`01_inventory.sql`, `03_quirks.sql`, `05_dup_fingerprint.py`).

### 0.1 How Spider 2.0 uses it

`db == modern_data` has 7 questions. Two of them use these tables:

| id | Asks | Gold SQL? | Reproduced here? (`02_gold.sql`) |
|---|---|---|---|
| local040 | Trees ⋈ income by ZIP ("filling missing ZIP values"); keep median > 0 and mean > 0 and a valid borough; give the top 3 boroughs by tree count and the average mean income of each | no; CSVs `_a`–`_d` | **`_c` exactly; `_d` exactly**; `_a` partly; `_b` no |
| local041 | % of Bronx trees with health 'Good' | no; CSVs `_a`, `_b` | **both** |

local040:
- **`_c`:** raw `trees` ⋈ `SELECT DISTINCT * FROM income_trees`. It gives Queens 252,846 / 79,366.738418, Brooklyn 177,132 / 73,555.190988 and Staten Island 106,374 / 94,029.327834, equal to `_c` at every printed digit.
- **`_d`:** a raw ⋈ raw join, in which income's duplicate zips fan out. Its averages are 79,312.572258 / 73,675.976969 / 94,029.327834, equal to `_d`.
- **`_a`:** its counts (250,364 / 175,358 / 105,318) are the deduplicated-trees ⋈ deduplicated-income counts. Its averages are `_c`'s. No single reading gives both.
- **`_b`:** its averages are `_d`'s, but its counts (Queens 256,065, Brooklyn 186,668) match no reading tried. The raw ⋈ raw join gives 256,056 / 184,711.
- "Filling missing ZIPs" does nothing on this copy: 0 NULL or 0 zipcodes.

local041:
- **`_a`:** 78.1473 = Good / all Bronx rows, over raw rows (78.147266).
- **`_b`:** 82.649376 = Good / Bronx rows with non-NULL health, over **distinct** trees. The same number comes from Alive-only over distinct trees.

**Three of the four reproduced answers depend on the injected duplicates.** local041 `_a`, local040 `_c` and `_d` all read raw `trees`, so the rebuild must keep them.

## 1. Inventory, keys, joins

| Table | Key (verified) | Notes |
|---|---|---|
| trees | tree_id, **on rows 6,839+**; idx ↔ tree_id is 1:1 (0 conflicts either way) | 6,838 ids appear twice, and the copies are identical in all columns. idx is not the rank of tree_id (683,788 mismatches), and tree_id order along idx is noise (368,859 ascents vs 314,928 descents) |
| income_trees | zipcode, **after removing 4 identical extra rows** | 216 zips over 220 rows |

Measured in `01_inventory.sql` and `03_quirks.sql`:

**ZIP join:**
- trees.zipcode → income_trees: 191 tree zips. 6 have no income row: **83** (Central Park, 935 trees, ZIP `00083` with its leading zeros lost), 10048, 10281, 11096, 11249 and 11251. Together that is 2,963 distinct trees (2,998 raw rows).
- 31 income zips have no trees.
- So zipcode **cannot be a `ref`**: an unmatched id is an error.

**Hierarchies:**
- borocode ↔ boroname is 1:1: Manhattan 1, Bronx 2, Brooklyn 3, Queens 4, Staten Island 5.
- 7 NTAs span two boroughs, e.g. Marble Hill-Inwood (Manhattan 1,508, Bronx 246) and East New York (Brooklyn 9,594, Queens 13).
- 3 zips span two boroughs: 11208, 11234 and 11414, each with 1–7 strays.

**Species:** spc_latin ↔ spc_common is 1:1 over 132 species. They are NULL together on all rows. Species NULL tracks health NULL except on 7 trees (§4).

**Constants:** state = 'New York' on all rows.

**Derived tables:** none.

## 2. Event catalogue

Nothing in either table has a time. The census was a single survey, carried out 2015–2016 per its documentation; its survey dates are not in this copy. So **every time below is a rule**.

| Event / entity | Owner | Time | Attributes | Source rows | Count |
|---|---|---|---|---:|---:|
| `trees` entity → `trees_created` | tree_id | **rule:** T0 (catalog start) | idx `i64`, species `opt(ref(species))`, address `text`, zipcode `i64`, boroname `cat`(5), nta_name `text`, latitude `f64`, longitude `f64` | distinct trees | 683,788 |
| `trees_snapshot` (tree surveyed) | tree_id | **rule:** N | tree_dbh `i32`, stump_diam `i32`, status `cat`(Alive, Dead, Stump), health `opt(cat)`(Good, Fair, Poor) | distinct trees | 683,788 |
| `species` entity | spc_latin | **rule:** T0 | spc_common `text` | the 132 pairs | 132 |
| `zip_incomes` entity | zipcode | **rule:** T0 | the 6 ACS columns `i64` | distinct income rows | 216 |
| `source_row_duplicated` | tree_id or zipcode | **rule:** N | table `cat`(trees, income_trees) | trees rows 1–6,838; income rows 1–2; plus 2 in-base repeats | 6,842 |

**3 event types, 3 entities, 1,374,766 events.** Of those, 684,136 are entity `_created` events (683,788 + 132 + 216), and the rest are 683,788 snapshots plus 6,842 duplicate markers.

- **Snapshot columns: status, health, tree_dbh, stump_diam.** They are what the surveyor saw, and they change over a tree's life.
- **Creation columns:** species, location, address and NTA. They are fixed for a given tree.
- **Not entities:**
  - **Boroughs:** 5 values, and borocode is a pure function of boroname. That is proven 1:1, so the view derives borocode.
  - **NTAs:** text that does not nest inside boroughs.
  - **ZIPs without income:** they are not in income_trees.
  - **state:** a constant.
- **`zip_incomes` keeps its estimates on creation, not in a snapshot.** An ACS estimate describes a fixed reference period and is not a moving state. See §7.
- **What is natural here:** essentially nothing about time. The catalog is a census snapshot and a lookup. The one real structure is the observation split: fixed traits at creation, observed state at N.

## 3. Rebuild rules and blockers to an exact round trip

Views (DuckDB):
- **trees** = trees_created ⋈ trees_snapshot ⋈ species, with:
  - `borocode = CASE boroname WHEN 'Manhattan' THEN 1 … END`;
  - `state = 'New York'`;
  - spc_latin and spc_common from the species ref (both NULL when the ref is NULL);
  - then `UNION ALL` one copy for each `source_row_duplicated` with table = 'trees'.
- **income_trees** = zip_incomes, `UNION ALL` the 4 marked rows. Two of those are the in-base repeats: zips 10463 and 11370.

Blockers and rules:
1. **Duplicates are load-bearing.** local041 `_a` and local040 `_c`/`_d` read the raw rows (§0.1). The marker event keeps them exact under multiset compare.
2. **NULL, not `''`:** health is NULL on 31,935 raw rows, and spc_* on 31,938. There are 0 empty strings in any text column (`01_inventory.sql`). Use `opt(...)`.
3. **Floats:** latitude and longitude are REAL. As text they print with 2–8 decimals (615,243 have 8). f64 JSON in shortest round-trip form reproduces them by value. 217 points are shared by 653 trees (`03_quirks.sql`). That is harmless.
4. **zipcode 83** is an integer, not `'00083'`. Keep `i64`.
5. **T0 and N are both rules.** Suggested: T0 = N = 2015-01-01 00:00 UTC. That is a stated rule, not data: the census ran in 2015–2016 per its documentation, and the survey dates are not in this copy. A one-instant catalog makes it explicit that no ordering is data. The order of equal-time events comes from `ord = idx`.
6. **All income columns are INTEGER:** 220/220 rows, 7 columns. There are no mixed columns.

Verdict: **exact round trip feasible**. The trees table comes from creation + snapshot + species, income_trees from one entity, and the copies from the marker event.

## 4. Measured quirks

From `03_quirks.sql`, over distinct rows:

**Status × NULL pattern:**

| Status | health set, species set | health set, species NULL | health NULL, species set | health NULL, species NULL |
|---|---:|---:|---:|---:|
| Alive | 652,167 | 5 | 1 | — |
| Dead | — | — | 1 | 13,960 |
| Stump | — | — | — | 17,654 |

So "not Alive ⇒ health NULL" holds on all 31,615 dead trees and stumps. "Alive ⇒ health set" fails on 1 tree, and 5 alive trees have no species.

**Sizes:**
- Stumps have tree_dbh 0 (17,654/17,654) and stump_diam 1–140.
- Alive and dead trees have stump_diam 0 (all).
- 222 alive trees have dbh 0.
- 70 trees have dbh > 100 inches, max **450**. These are census data-entry outliers.

**income_trees sentinels:**
- 32 zips have 0 households, with all estimates 0 and Margin_of_Error_Total = 11. These are non-residential zips such as 10020 and 10110.
- Zips 10007 and 10282 have **median income 250 with MOE 0**, while their mean is 441,278 / 318,142. This is ACS's top code "250,000+", truncated to 250 at the thousands comma.
- local040's "median > 0 AND mean > 0" filter removes the 32 zeros but keeps the two 250s.
- Mean ≥ median on every zip with households: 0 exceptions.

**Physical order:**
- trees rows 6,839+ are sorted by idx, but boroughs are interleaved: 429,832 borough changes between neighbours.
- income_trees base (rows 3+) is 214 ascents and 3 descents of zipcode, i.e. 4 sorted runs.

**Text:**
- Addresses are upper case, trimmed, with no double spaces.
- spc_common case is mixed: 289,070 rows are not all lower case, e.g. `London planetree`, `Callery pear`.

## 5. Distributions to fit (stage 2)

From `04_dists.py`, over 683,788 trees:
- **Status:** Alive 95.38%, Stump 2.58%, Dead 2.04%. **Health given Alive:** Good 81.09%, Fair 14.80%, Poor 4.11%.
- **Borough:** Queens 36.6%, Brooklyn 25.9%, Staten Island 15.4%, Bronx 12.5%, Manhattan 9.6%.
- **Good share by borough:** 72.4% in Manhattan to 78.5% on Staten Island. **Alive share:** 94.6% (Bronx) to 96.3% (Staten Island).
- **dbh, alive trees (inches):** p10 3, p25 5, median 10, p75 16, p90 24, p99 37, max 425, mean 11.7. **Dead trees:** median 4. **Stump diameter:** median 14, p99 53.
- **Species:** 132 in all, heavy-headed. The top 1 (London planetree) covers 13.3%, the top 10 cover 65.4% and the top 50 cover 95.4%. There are 0 singletons.
- **Trees per zip:** median 3,229, p90 6,855, max 22,186, across 191 zips.
- **Income, the 184 zips with households:**
  - median household income: p10 30,779, median 58,076, p90 105,500;
  - mean/median: median 1.36, p90 1.69;
  - MOE/estimate on the median: median 6.6%.
- **No arrivals or gaps:** there is no time in the source.

## 6. simkit mapping sketch

```python
p.entity("species", key="species_key", cols={"ext_id": text(doc="spc_latin"), "spc_common": text()})
p.entity("trees", key="tree_key", doc="2015 census tree; created at rule time T0",
         cols={"ext_id": text(doc="tree_id"), "idx": i64(doc="Source pandas index; also the ingest ord"),
               "species": opt(ref("species")), "address": text(), "zipcode": i64(doc="83 = Central Park"),
               "boroname": cat("Manhattan", "Bronx", "Brooklyn", "Queens", "Staten Island"),
               "nta_name": text(), "latitude": f64(), "longitude": f64()})
p.event("trees_snapshot", doc="What the census observed, at N",
        cols={"tree_id": ref("trees"), "tree_dbh": i32(), "stump_diam": i32(),
              "status": cat("Alive", "Dead", "Stump"), "health": opt(cat("Good", "Fair", "Poor"))})
p.entity("zip_incomes", key="zip_key", doc="ACS household income by ZIP; created at T0",
         cols={"ext_id": text(doc="zipcode"), "estimate_total": i64(), "moe_total": i64(),
               "estimate_median_income": i64(doc="250 = top-coded 250,000+"), "moe_median_income": i64(),
               "estimate_mean_income": i64(), "moe_mean_income": i64()})
p.event("source_row_duplicated", doc="Spider2 artefact or upstream repeat: one extra identical row",
        cols={"table": cat("trees", "income_trees"), "ext_id": text(doc="tree_id or zipcode")})
```

- **Ingest:**
  - entities from `SELECT DISTINCT` over `rowid > 6838` (trees) and over all rows (income), each `ORDER BY` its id;
  - `trees_snapshot owner=tree_id ord=idx` `ORDER BY idx`;
  - `source_row_duplicated owner=table ord=src_rowid`, with one row per extra copy, `ORDER BY table, rowid`.
- **build.sql:** as in §3. The view writes spc_latin as the species `ext_id`, and REAL lat/long straight from `f64`.
- **Saved queries:**
  - local041 `_a` (raw, 78.1473) and `_b` (distinct + non-NULL health, 82.649376);
  - local040 `_c` (raw trees ⋈ DISTINCT income), which is exact on counts and averages.
- **Volume:** 1.37 M events. Ingest and roundtrip are a few seconds, comparable to `oraclesh`.
- **Stage 2:**
  - a spatial Source of trees per zip;
  - species categorical;
  - a status/health chain;
  - a lognormal-ish dbh per species.
  - No temporal laws exist to check. A law "stump ⇒ dbh = 0" holds (17,654/17,654). "Not alive ⇒ health NULL" holds (31,615/31,615). "Alive ⇒ health set" fails once.

## 7. Open questions and risks

- **Time is wholly imposed.** Should the dataset skip the snapshot split and put everything at N, or keep the creation/snapshot split so stage 2 can evolve tree state? The sketch keeps the split.
- **zip_incomes:** creation-only or snapshot? ACS estimates are period values. I left them on creation, which is defensible, but by the "when in doubt, snapshot" rule they could move.
- **local040 `_a`/`_b`** mix readings: `_a`'s counts use deduplicated trees with averages from raw trees, and `_b`'s counts match no reading. They were probably computed on a different copy of the table, perhaps before or after the duplicate injection. Use `_c` for the saved query.
- **The in-base repeats of zips 10463 and 11370** could be upstream or a second injection. They are measured as identical; their origin is unknown.
- **The 7 trees whose species NULL and health NULL disagree** are real census oddities: 5 alive trees with health but no species, 1 alive tree with species but no health, and 1 dead tree with a species. Do not "fix" them.

## Summary

1. **Feasible:** yes. trees and income_trees rebuild exactly from tree, species and zip entities, a census snapshot at N, and explicit duplicate-row markers. Nothing is derived; borocode and state are pure functions of boroname and a constant.
2. **Dataset name:** `nyctrees` (modern_data, trees + income_trees). Saved queries: local040 (`_c`), local041 (`_a`, `_b`).
3. **Events and entities:** 3 event types (`trees_created` 683,788, `trees_snapshot` 683,788, `source_row_duplicated` 6,842), 3 entities (`trees` 683,788, `species` 132, `zip_incomes` 216).
4. **How event-shaped:** mostly imposed. It is a one-time census plus a lookup, with no time column. T0 and N are rules.
5. **Hardest blocker:** the 6,838 + 4 duplicate rows. They carry no meaning, yet three of the four reproduced gold answers count them. Next is the absence of any time, which leaves stage 2 nothing temporal to learn.
