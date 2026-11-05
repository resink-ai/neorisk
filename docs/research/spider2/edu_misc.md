# StaffHours and SalaryDataset (Spider 2.0-lite, `education_business`): reverse-engineered event log

Source: the two stand-alone tables `StaffHours` and `SalaryDataset` of `data/spider2/education_business.sqlite`, opened read-only. They share no key with each other or with the file's other catalogs: AtliQ ([atliq.md](atliq.md)), Parch & Posey ([parchposey.md](parchposey.md)) and the university ([university.md](university.md)). They are reported together only because each is a single table. `scripts/edu_misc/rq.py` copies the file into an in-memory SQLite and runs named blocks; the file itself is never written.

Every number below comes from one of these scripts:
- a named query in `scripts/edu_misc/q1_salary.sql` or `q2_staffhours.sql`;
- `f1_local253.py` (Python, salary-cleaning rules against the gold CSVs);
- `f2_salary_text.py` (Python, the Salary text round trip and StaffHours' rowid pattern);
- `f3_duck_lakh.py` (DuckDB, the same text round trip in SQL; run with `uv run python -I`).

The raw outputs are in `scripts/edu_misc/out_*.txt`. A reference such as `[q2:alternation]` means file `q2_staffhours.sql`, block `-- name: alternation`. Gold CSVs are in `scripts/edu_misc/gold/`.

## 0. What this catalog is

- **SalaryDataset** (4,344 rows) [q1:row_counts]:
  - **What it is.** An India data-science salary table scraped from Glassdoor: company, job title, number of salaries reported, city and an average salary string such as `₹6,48,573/yr`.
  - **Origin.** The columns and size match the public Kaggle dataset *"Salary Dataset – Data Science and Analytics Industry (India)"*. `index` is a pandas `RangeIndex` (0..4,343 = rowid − 1, 4,344 of 4,344) [q1:index_vs_rowid], so the table was written from a pandas DataFrame. The Kaggle author, date and licence are **unverified**.
  - **Coverage.** 5 cities: Bangalore 1,584, Pune 818, Hyderabad 669, New Delhi 656 and Mumbai 617 [q1:location_mix]. It has 26 job titles and 2,529 companies [q1:job_titles].
  - **Nature.** **Real, scraped, pre-aggregated** data. Each row is an aggregate of `SalariesReported` individual reports. The company names are real, and no person is identifiable.
- **StaffHours** (236 rows):
  - **What it is.** A clock-in/clock-out log: staff member `A`..`Z`, date, `HH:MM`, and `Enter` or `Exit`, for 2013-01-02..2013-03-12 [q2:formats, q2:members].
  - **Origin.** Unknown. It looks like a SQL-puzzle fixture ("compute hours worked").
  - **Nature.** **Generated**: the rows cycle through the letters and alternate Enter/Exit in rowid order, but not in time order (§4).
  - **Use.** No Spider question touches it.
- **Licence:** unstated for both.

## 0.1 How Spider 2.0 uses it

| id | asks | gold SQL? | gold answer | reproduced |
|---|---|---|---|---|
| local253 | clean `Salary` to a number; top 5 companies by average salary in each of Mumbai, Pune, New Delhi and Hyderabad, each with the national average | no (3 CSVs, 3 different cleaning rules) | _a: Hyderabad Meta 6,275,360; national 915,555.247007. _b and _c: no Meta; Hyderabad Qwerty Concepts 5,081,882 first; national 907,524.49 (_b) or 912,140.12 (_c) | ✔ _a exactly: annualise `/mo` × 12 and `/hr` × 2,080, keep all currencies, take the national mean over all rows [f1]. ✔ _c exactly: `/mo` × 12, drop the `/hr` rows [f1]. The _b top-5 lists equal _c's, but its national 907,524.49 is **not** reproduced by any rule I tried [f1] |

- Meta's single Hyderabad row is `₹3,017/hr`. × 2,080 gives 6,275,360, the _a value [q1:meta_rank, f1].
- Stripping only the digits ranks differently from every gold file. It puts `XYZ (Turkey)` third in Hyderabad [q1:gold_local253_strip_digits, f1].

So the question depends on the **exact Salary text**: the currency prefix, the lakh grouping and the `/yr`, `/mo` or `/hr` period. The rebuild must be byte-exact (§3).

StaffHours has no question.

## 1. Inventory, keys, joins

| Table | Rows | Key | Kind |
|---|---:|---|---|
| SalaryDataset | 4,344 | `index` (0..4,343, = rowid − 1). (CompanyName, JobTitle, Location) is **not** unique: 326 extra rows, but 0 full-row duplicates [q1:duplicates] | pre-aggregated, untimed fact |
| StaffHours | 236 | none declared. (StaffMember, EventDate, EventTime) is unique: 0 same-moment rows, 0 full duplicates [q2:dups] | log (clock events) |

- **Joins:** none. Neither table references anything.
- **Copies:** none.
- **Derived tables:** none. In SalaryDataset, `index` is a derived column (rowid − 1). If rows are rebuilt in `index` order it can be carried as the `ext_id`; it is not computed from other columns.
- **Rowid order of SalaryDataset.**
  - The rows form 60 runs of (JobTitle, Location) [q1:rowid_sort].
  - Inside a run, `SalariesReported` is non-increasing in all but 5 of 4,284 adjacent pairs [q1:rowid_reported_desc_within_runs]. That is the scraper's per-search "most reported first" listing order.
- **Repeated keys.** Same company, title and city with different salaries: for example ABC / Data Scientist / New Delhi has 3 rows, `₹7,28,836/yr`, `₹30,82,142/yr` and `₹87,000/mo` [q1:dup_examples]. Glassdoor lists yearly and monthly reports separately.

## 2. Event catalogue

**StaffHours: a natural event log.** Each row is one clock event at its own date and minute.

| # | Event | Owner | Time | Attributes | Source rows | Count |
|---|---|---|---|---|---|---:|
| E1 | `staff_clocked` | staff member (ord = src_rowid) | `EventDate` + `EventTime` (natural, minute resolution) | event_type (`Enter` or `Exit`), src_rowid | StaffHours | 236 |

Splitting E1 into `staff_entered` (123) and `staff_exited` (113) is equivalent [q2:members].

- **Entity `staff`** (26): ext_id = the letter. `created_at` = its first clock event, by rule.
- **N** = the last stamp, on 2013-03-12 [q2:formats].

**SalaryDataset: an untimed pre-aggregate.** It has no time column at all. Each row is a Glassdoor aggregate over an unknown collection window. It becomes one **entity**, `salary_listings` (4,344 rows), created at a **rule** time.

I propose **2022-01-01 00:00:00**, the nominal publication year. That year is unverified (§7). The alternative would be a `salary_aggregate_reported` event at that same rule time, but an event whose time is pure invention adds nothing over an entity. The brief's "pre-aggregated fact" shape needs a period date, and this table has none.

Attributes:
- `ext_id` = `index`;
- `company_name` (opt);
- `job_title` (cat, 26 values);
- `salaries_reported` (opt, integral);
- `location` (cat, 5 values);
- `salary_currency` (cat: `₹`, `$`, `£`, `AFN `);
- `salary_amount` (i64);
- `salary_period` (cat: `yr`, `mo`, `hr`).

The last three, or the verbatim text as a fallback, are explained in §3.

What is **not** an entity: **companies** (2,529 names, 3 NULL) and **job titles**. They have no table and no attributes beyond the name, and a company entity would need a home for the 3 NULL-company rows. Keep them as text and category.

No snapshot columns: the listing is entirely a snapshot, and its creation time is N.

## 3. Rebuild rules and blockers to an exact round trip

1. **The Salary text decomposes exactly.**
   - Every value matches `<currency><digits with commas>/<yr|mo|hr>` (4,344 of 4,344).
   - The currencies are `₹` 4,318, `$` 19, `£` 6 and `AFN ` 1. The last has a trailing space before the digits [f2].
   - Reprinting the integer amount with **Indian lakh grouping** (last 3 digits, then pairs: `6,48,573`, `1,00,488`, `30,82,142`) reproduces 4,344 of 4,344 byte for byte in Python [f2]. Even the `$` and `£` amounts use lakh grouping.
   - A pure DuckDB formatter also gives 4,344 of 4,344 [f3]. It reverses the head digits, inserts a comma after each pair, trims and reverses back, then appends `','||right(d,3)`. DuckDB's RE2 has no look-ahead, so the reverse trick is required [f3].
   - **Recommendation:** carry (currency, amount, period) so that stage 2 sees numbers. Verbatim text is the trivially exact fallback.
2. **`SalariesReported`** is REAL. All 4,342 non-NULL values are integral, and 2 are NULL [q1:salary_typeof, q1:reported_integral, q1:null_reported_rows]. Carry it as `opt(i64)` and rebuild it as `CAST(x AS DOUBLE)`. Its affinity is REAL → float64, so it is not mixed.
3. **NULLs.** `CompanyName` is NULL in 3 rows and `SalariesReported` in 2. There are no empty strings and no stray whitespace [q1:salary_nulls, q1:whitespace].
4. **`index`** is INTEGER and equals rowid − 1. Carry it as `ext_id`.
5. **StaffHours times.**
   - `EventDate` is `YYYY-MM-DD` and `EventTime` is `HH:MM` (zero-padded, 5 characters). Both parse for 236 of 236 rows [q2:formats, q2:parse].
   - Store `event_time = date || ' ' || time || ':00'`. Rebuild with `strftime(t, '%Y-%m-%d')` and `strftime(t, '%H:%M')`.
   - All minutes are on a 5-minute grid [q2:minute_grid]. All four columns are TEXT [q2:typeof].
6. **Ties.** StaffHours has no same-moment rows for one member [q2:dups]. `ord = src_rowid` keeps rowid order for rows of different members at the same time.

**Verdict:** an exact round trip is feasible for both tables. The only proof needed beyond verbatim copies is the lakh formatter, which is shown exact in Python and DuckDB.

## 4. Measured quirks

- **StaffHours does not pair.**
  - In time order per member, there are 87 Enter→Enter and 82 Exit→Exit steps, against only 41 alternations. 11 members start with an Exit [q2:alternation].
  - G, I, K, Q, S and U have only Enters, and H, J, R and T only Exits [q2:per_member].
  - Only 2 Enter→Exit pairs fall on the same day. 18 span days, up to 700 hours [q2:same_day_pairs, q2:shift_hours].
  - **Rowid order is the generator's.** The next row's member is the next letter for 213 of 235 rows, and the event type alternates Enter/Exit for 223 of 235 rows [f2]. The dates were drawn at random per row, so the rowid order is not time order (121 descents in 235 pairs) [q2:rowid_order].
  - The data cannot answer "hours worked" sensibly. A stage-2 model should not learn shift structure from it.
- **StaffHours times of day:**
  - Enters cluster at 07–09 h (85 of 123);
  - Exits at 11–15 h (86 of 113);
  - all within 07:30–18:25 [q2:hours, q2:formats];
  - 87 / 87 / 62 rows in Jan / Feb / Mar [q2:per_date].
- **Members have 8–11 rows each**, and the counts decrease with the letter: A 11, B–L about 10, M–P 9, Q–Z 8 [q2:per_member]. That is a fingerprint of round-robin generation: 236 = 9 × 26 + 2, over a cycle that sometimes skips.
- **SalaryDataset mixes periods and currencies**: 3,211 `₹…/yr`, 1,087 `₹…/mo`, 20 `₹…/hr`, plus 26 non-rupee rows [q1:salary_format_mix]. A "salary" is not comparable across rows without a rule, and the three gold files use three different rules (§0.1).
- **The Salary amounts** [f2]:
  - Rupee `/yr` amounts: p10 361,080, p50 839,303, p90 1,881,045, p99 3,665,141; the range is 10,814–9,568,943.
  - Rupee `/mo` amounts: p50 30,979.
  - Some monthly values look like yearly values mislabelled, and vice versa; this is unmeasured.
- **`SalariesReported`:** 2,504 rows have 1 report, 1,421 have 2–5, 354 have 6–20 and 63 have 21+ [q1:reported_dist].
- **Job titles are skewed.** Data Scientist 1,844, Data Analyst 990, Data Engineer 805, Machine Learning Engineer 568, and a long tail of 22 titles with 43 or fewer rows each [q1:job_title_mix].
- **Placeholder companies:** `ABC`, `XYZ (Turkey)`, `ABCDEF`, `DasDas` and people's names (`VINAYA KUMAR`) [q1:dup_examples, f1]. Glassdoor's user-entered employer names survive.

## 5. Distributions to fit (stage 2)

| Quantity | Value |
|---|---|
| SalaryDataset city mix | Bangalore 36.5%, Pune 18.8%, Hyderabad 15.4%, New Delhi 15.1%, Mumbai 14.2% [q1:location_mix] |
| title mix | 4 titles cover 96.8%: 1,844 / 990 / 805 / 568 [q1:job_title_mix] |
| period mix | yr 74.4%, mo 25.1%, hr 0.5% [q1:salary_format_mix] |
| rupee yearly salary | lognormal-like; p10 361k, p50 839k, p90 1.88M [f2] |
| reports per row | 1: 57.7%, 2–5: 32.7%, 6–20: 8.2%, 21+: 1.5% [q1:reported_dist] |
| StaffHours | 26 members, 236 events over 2013-01-02..03-12; Enter at 07–09 h, Exit at 11–15 h; 5-minute grid [q2:hours, q2:minute_grid] |

## 6. simkit mapping sketch

```python
# dataset salaries_india
p.entity("salary_listings", key="listing_key", doc="Glassdoor aggregate; untimed, created by rule at 2022-01-01",
         cols={"ext_id": i64(doc="pandas index"), "company_name": opt(text()), "job_title": text(),
               "salaries_reported": opt(i64()), "location": cat("Bangalore", "Hyderabad", "Mumbai", "New Delhi", "Pune"),
               "salary_currency": cat("₹", "$", "£", "AFN "), "salary_amount": i64(),
               "salary_period": cat("yr", "mo", "hr")})
# dataset staffhours
p.entity("staff", key="staff_key", cols={"ext_id": text(doc="letter A..Z")})
p.event("staff_clocked", cols={"staff_id": ref("staff"), "event_type": cat("Enter", "Exit"), "src_rowid": i64()})
```

Ingest:
- **salary_listings:** ORDER BY `index`. The currency, amount and period are split with SQLite string functions: `instr`, `substr` and `replace(…, ',', '')`.
- **staff_clocked:** `owner=staff_id ord=src_rowid`. The time is `EventDate||' '||EventTime||':00'`. ORDER BY rowid.

`build.sql`:
- **`SalaryDataset`:** `ext_id AS "index"`, and so on. `CAST(salaries_reported AS DOUBLE)`. `Salary = currency || lakh(amount) || '/' || period`, using the [f3] expression.
- **`StaffHours`:** `strftime` back into the two text columns, plus `event_type`.

Stage-2 owners:
- StaffHours: a staff member with a daily clock, if anyone wants it. Note that the source itself is incoherent.
- SalaryDataset: there is no event process to simulate. A row generator by (city, title, company) with a lognormal salary and the period mix is the most stage 2 can do.

## 7. Open questions and risks

- **The SalaryDataset origin, date and licence** are unverified. The Kaggle title and the 2022 creation rule are my inferences. Confirm the licence before redistributing. Fitting statistics on aggregate salaries is low-risk.
- **local253's three gold files disagree.** _a annualises the `/hr` rows (× 2,080); _c drops them. _b's national average of 907,524.49 is unexplained; it is close to _a's average over (city, company) groups, 907,091.42, but not equal [f1]. Any saved query must pick one variant. This does not affect the tables.
- **The StaffHours origin is unknown,** and no question uses it. It could be dropped from the benchmark set, or kept as a 236-event fixture.
- **Two datasets or one?** The tables are unrelated. I propose two tiny datasets, `salaries_india` and `staffhours`. Folding them into one `edu_misc` dataset also works mechanically, but it mixes two domains.
- **The lakh formatter** depends on DuckDB's `reverse` and `regexp_replace` behaving the same across versions. It was tested on DuckDB 1.5.6, as installed in the repo's uv environment. Add a unit test, or fall back to verbatim text.

---

- Exact round trip: **yes**. Both tables rebuild verbatim; SalaryDataset's `Salary` also round-trips as (currency, integer, period) with a lakh formatter, proven exact on 4,344 of 4,344 rows in Python and DuckDB.
- Proposed dataset names: **`salaries_india`** and **`staffhours`** (or one **`edu_misc`**).
- 1 event type (`staff_clocked`, 236 events) and 2 entities (salary_listings 4,344, staff 26).
- Event shape: **mixed**. StaffHours is natural (but generated and incoherent). SalaryDataset is mostly imposed: an untimed aggregate placed at a rule time.
- Hardest blocker: SalaryDataset has no time and its collection window is unknown, so any time is invented. local253's three gold variants disagree, and one cannot be reproduced.
