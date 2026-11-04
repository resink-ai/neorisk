# modern_data (Spider 2.0-lite), statistics + word_list: the two leftover tables

Source: `data/spider2/modern_data.sqlite`, opened read-only (`sqlite3 -readonly`, `python3 -I` with `mode=ro`).
Scripts: [`scripts/modern_misc/`](scripts/modern_misc/) (`00_fetch_gold.sh`, `01_inventory.sql`, `02_words.sql`, `03_local201.py`, `04_statistics.py`, `05_dup_fingerprint.py`, gold CSVs in `gold/`). Each script's raw output is the `out_<script>.txt` next to it.

These two tables share nothing with each other, or with the pizza, unicorn and tree groups. They are one report only because each is too small for its own. They should become **two datasets**, or `word_list` should become an appendix to another.

## 0. What this catalog is

| Table | Rows | Distinct | Role |
|---|---:|---:|---|
| statistics | 1,010 | 1,000 (date, state) | daily **cumulative** COVID-19 cases and deaths for CO, FL, MA and NC, 2020-02-01 → 2020-11-11 |
| word_list | 373,804 | 370,101 non-NULL words, plus 2 NULLs | an English word list, lower case a–z |

Counts are from `01_inventory.sql` and `02_words.sql`.

**statistics:**
- Each state's series starts at 1 case: MA on 2020-02-01, the others 2020-03-02 to 03-05.
- Each series has no missing days, so it is daily state-level surveillance data.
- The publisher (NYT, COVID Tracking Project or a state feed) is **not identifiable** from the data. Licence: unstated.
- The data is real.

**word_list:**
- The base list begins `a, aa, aaa` and has 370,103 rows of `[a-z]+`. That is consistent with the `words_alpha.txt` list of the dwyl/english-words repository (Unlicense).
- Two words became NULL, and two became upper case (§4), which is a pandas-import fingerprint.
- Licence: unstated in Spider2.

**Spider2's duplicate prepend:**
- statistics rows 1–10 are copies of later rows, and 10 = 1% of 1,000.
- word_list rows 1–3,701 are copies, and 3,701 = round(1% × 370,103).
- Every non-pizza table of `modern_data` shows the same pattern. `05_dup_fingerprint.py` matches the leading duplicate run to round(1% of the base) on all 7 tables: companies ×3, trees, income_trees, statistics, word_list. The pizza tables have no prepended copies (k = 0).

### 0.1 How Spider 2.0 uses it

| id | Table | Asks | Gold SQL? | Reproduced here? (`03_local201.py`) |
|---|---|---|---|---|
| local201 | word_list | First 10 words (alphabetical) of length 4–5 starting with 'r' that have ≥ 1 same-length anagram (case-sensitive), with the anagram count | no; CSVs `_a`, `_b` | **both** |
| — | statistics | no question | — | — |

local201:
- **`_a`:** raad 3, raash 4, rabal 1, rabat 1, rabi 3, rabic 2, rabid 3, rabin 4, rabot 3, race 5. It equals all three readings tried: distinct words; raw rows with distinct anagrams; raw rows with rows counted. The first 10 r-words with real anagrams are not among the duplicated words, so the duplicates do not move `_a`.
- **`_b`:** rason, rcpt, recti, rekey, reset, ridge, roily, roose, roud, rugs, each with count 1. These are **exactly the first 10 duplicated r-words of length 4–5** (`03_local201.py`). `_b` counts a word's own second copy as its "anagram". That is a pure artefact of the injected rows: `rcpt` has no real anagram at all.
- So a rebuild that drops the duplicates still passes `_a`, but fails `_b`.

`statistics` is not used by any question.

## 1. Inventory, keys, joins

| Table | Key (verified) | Notes |
|---|---|---|
| statistics | (date, state), **on rows 11+** | 10 keys appear twice, and the copies are identical. Rows 11+ are sorted by (state, date) with 0 descents (`04_statistics.py`) |
| word_list | words, **on rows 3,702+**, except 2 NULLs | 3,701 words appear twice. The base has 0 repeated non-NULL words (`02_words.sql`) |

- No FKs, and no joins to any other table. `statistics.state` uses postal codes; nothing else in the file does.
- Rows per state: CO 251 days (03-05 → 11-10), FL 253 (03-02 → 11-09), MA 285 (02-01 → 11-11), NC 211 (03-03 → 09-29). The series end on different days.
- The word_list base is *almost* sorted: 17,477 descents in 370,102 neighbour pairs, e.g. `abacay` before `abacas`. It is not in byte order, and `lower()` does not fix it (17,475). The tables compare as multisets, so this order need not survive.

## 2. Event catalogue

| Event / entity | Owner | Time | Attributes | Source rows | Count |
|---|---|---|---|---:|---:|
| `daily_totals_reported` | state | **natural:** date 00:00 | state `cat`(CO, FL, MA, NC), total_cases `i64`, total_deaths `i64` | statistics rows 11+ | 1,000 |
| `words` entity → `words_created` | src_pos | **rule:** T0 | word `opt(text)` | word_list rows 3,702+ | 370,103 |
| `source_row_duplicated` | table | **rule:** N | table `cat`(statistics, word_list), plus the key: date+state or src_pos | statistics rows 1–10, word_list rows 1–3,701 | 3,711 |

**2 event types, 1 entity, 374,814 events**, across what should be two datasets.

**statistics** is a **pre-aggregated fact**: one reported row per state per day. No finer grain exists. The cases and deaths behind the totals are not in the data.
- The event carries the cumulative totals as reported, not daily deltas.
- Deltas would rebuild the totals exactly too, as integer prefix sums. But the source reports totals, and the totals sometimes *fall*, which makes "new cases" negative (§4). Keeping the totals avoids inventing a corrective event.

**word_list** is a **static table with no time and no use**, other than as a puzzle input. Each word is an entity at a rule time T0.
- The key cannot be the word, because 2 base rows are NULL and an entity's `ext_id` cannot be NULL.
- The key is therefore the 1-based position in the base list (src_pos = rowid − 3,701), with the word as a nullable attribute.

**Not entities:** states are a 4-value category, and the duplicate copies are markers, not data.

## 3. Rebuild rules and blockers to an exact round trip

Views:
- **statistics** = `strftime(event_time, '%Y-%m-%d %H:%M:%S')`, state, total_cases, total_deaths, `UNION ALL` the 10 marked rows.
  - All 1,010 dates are 19-character text ending in ` 00:00:00` (`01_inventory.sql`).
  - All counts are INTEGER.
- **word_list** = word from each `words` entity, `UNION ALL` one copy for each marked src_pos.

Blockers and rules:
1. **NULL words.** The 2 NULLs sit where `nan` and `null` belong alphabetically: between `nammo`/`nana` and between `nul`/`nullable` (`02_words.sql`). Neither word is present as text. This is pandas' default NA parsing. The rebuild must keep them as **NULL**, not restore the words, or the multiset differs.
2. **`TRUE` and `FALSE`.** These are the only upper-case words, at rows 335,218 and 113,221. The lower-case `true`/`false` are absent. A boolean parse wrote them back as upper-case text. Keep them byte-exact.
3. **Duplicates.** local201 `_b` needs the 3,701 copies, so they are marker events.
4. **Snapshot times.**
   - statistics: N ≥ 2020-11-11, the last row.
   - word_list: T0 and N are pure rules, e.g. both 2016-01-01 as in weblog's untimed masters. No time is data.
5. **No floats, no `'\N'`, no `''`.** 0 empty strings in word_list, and every statistics value is an integer.

Verdict: **exact round trip feasible** for both tables.

## 4. Measured quirks

- **Cumulative totals fall** (`01_inventory.sql`, distinct rows, by state and date):
  - cases drop on 5 days: FL 3, MA 1, NC 1;
  - deaths drop on 8 days: CO 2, MA 5, NC 1;
  - the largest drop is NC cases on 2020-07-02 (66,514 → 64,670).
  - These are reporting corrections. A law "totals are non-decreasing" is **false** on this data.
- **Flat days:** totals repeat unchanged on 57 state-days (CO 5, FL 6, MA 35, NC 11).
- **Weekday effect** in daily increments (`04_statistics.py`). Mean new cases by weekday peak on **Friday** in all 4 states, and the low falls on Sun–Tue: CO Sun 460 vs Fri 616; FL Mon 2,661 vs Fri 3,767; MA Tue 538 vs Fri 804; NC Mon 748 vs Fri 1,398.
- **word_list:**
  - lengths run 1–31, with mode 9 (53,940);
  - 26 rows have length 1;
  - there are 0 digits and 0 punctuation characters;
  - one row has a 31-letter word.

## 5. Distributions to fit (stage 2)

**statistics** (`04_statistics.py`): 4 series of 211–285 days, all starting at 1.

| State | Final cases | Final deaths | Median new cases/day | Max new cases/day | CFR at end |
|---|---:|---:|---:|---:|---:|
| CO | 138,427 | 2,427 | 371 | 4,797 | 1.75% |
| FL | 836,370 | 17,179 | 2,371.5 | 15,135 | 2.05% |
| MA | 182,367 | 10,202 | 417.5 | 4,946 | 5.59% |
| NC | 209,137 | 3,494 | 941 | 6,142 | 1.67% |

These are aggregate curves: an epidemic growth/decay process plus a weekday reporting cycle and occasional negative corrections. They are not an arrival process.

**word_list:** the length distribution is above (§4). There is nothing temporal or behavioural to fit.

## 6. simkit mapping sketch

```python
# dataset: covidstates (statistics)
p.event("daily_totals_reported", doc="Pre-aggregated: cumulative totals as reported for one state-day",
        cols={"state": cat("CO", "FL", "MA", "NC"), "total_cases": i64(), "total_deaths": i64()})
p.event("source_row_duplicated", cols={"table": cat("statistics"), "date": ts(), "state": cat("CO", "FL", "MA", "NC")})

# dataset: wordlist (word_list)
p.entity("words", key="word_key", doc="One row of the base list; created at rule time T0",
         cols={"ext_id": text(doc="src_pos, 1-based position in the base list"), "word": opt(text(doc="2 NULLs = 'nan','null'"))})
p.event("source_row_duplicated", cols={"table": cat("word_list"), "word": ref("words")})
```

- **Ingest:**
  - `daily_totals_reported owner=state`, `ORDER BY date, state`;
  - words `ORDER BY rowid`. The entity key is the rank of a text ext_id, so zero-pad src_pos (`printf('%06d', …)`) to keep the rank equal to the position.
- **build.sql:** as in §3.
- **Saved query:** local201, with both `_a` and `_b`. `_b` is the duplicate check.
- **Stage 2:**
  - covidstates: a per-state growth curve, a weekday multiplier and a small rate of negative corrections.
  - wordlist: nothing to generate. It is a reference input.

## 7. Open questions and risks

- **Fold word_list into another dataset?** It is 370 k entity rows for one puzzle question. As its own dataset, `wordlist`, it is a clean NULL/text exactness test. As part of anything else, it is noise. My call: its own small dataset.
- **statistics has no question.** It could be dropped from the validation set entirely, or kept as `covidstates`: the only true time series in `modern_data`, and small.
- **The source of statistics** is not identified, so the licence is unknown.
- **Order inside word_list's base** (17,477 descents) is not byte or case-insensitive order. It does not matter for multiset compare; it would matter only to a rowid-based question, and there is none.
- **local201 `_b` is an artefact answer.** It is accepted by Spider2, and a correct dataset must keep producing it, but it carries no linguistic meaning.

## Summary

1. **Feasible:** yes. statistics rebuilds from one reported event per state-day, and word_list from one entity per base row with 2 NULL words kept NULL. The 10 + 3,701 injected copies come back from marker events.
2. **Dataset names:** `covidstates` (statistics, no question) and `wordlist` (word_list, local201 `_a` and `_b`).
3. **Events and entities:** 2 event types (`daily_totals_reported` 1,000, `source_row_duplicated` 3,711), 1 entity (`words`, 370,103).
4. **How event-shaped:** statistics is natural but pre-aggregated, with no finer grain. word_list is wholly imposed: a static list at rule time T0.
5. **Hardest blocker:** word_list's 2 NULL rows. The words `nan` and `null` were eaten by pandas, so the word cannot be the entity key, and the rebuild must emit NULL, not the word. Next is local201 `_b`, which only the injected duplicates produce.
