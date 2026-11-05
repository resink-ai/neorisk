# Data job postings (Spider 2.0-lite, `city_legislation`): reverse-engineered event log

Source: `data/spider2/city_legislation.sqlite` (44 MB), opened read-only. The file holds four unrelated catalogs. This report covers four tables: `job_postings_fact`, `job_company`, `skills_dim` and `skills_job_dim`. The others are covered in `legislators.md`, `aliens.md` and `cities.md`.

`scripts/jobpostings/rq.py` copies the file into an in-memory SQLite and runs named blocks (`setup*` blocks index the in-memory copy); the file itself is never written. Every number below comes from one of these scripts:
- a named query in `scripts/jobpostings/q*.sql`;
- `profile.py` (per-column storage classes, NULL / `''` / `'\N'` counts);
- `f1_float32.py` (salary float checks), `gold_168.py` (local168), `q4_dists.py` (distributions);
- `fetch_barousse.sh` (upstream DDL).

The raw outputs are in `scripts/jobpostings/out_*.txt`. A reference such as `[q2:salary_rate_vs_columns]` means file `q2_values.sql`, block `-- name: salary_rate_vs_columns`. Gold answer CSVs are in `scripts/jobpostings/gold/`.

## 0. What this catalog is

- **Dataset.** Data-job postings scraped from Google Jobs during 2023, published as the course database of **Luke Barousse's "SQL for Data Analytics"** course (repo `lukebarousse/SQL_Project_Data_Job_Analysis`, data from his datanerd.tech collection). The evidence:
  - The repo's `2_create_tables.sql` declares `job_postings_fact`, `skills_dim`, `skills_job_dim` and `company_dim` with exactly these columns in this order. Spider renamed `company_dim` to `job_company` [fetch_barousse].
  - Postings run 2022-12-31 06:03:30 .. 2023-12-31 03:18:00 [q2:posted_date_format]. The `job_via` values ("via LinkedIn", "via BeBee", "melalui …") are Google Jobs' source labels [q2:via_prefix, q2:via_top]. `link_google` is a google.com/search URL in 13,998 of 14,003 companies [q2:company_text].
- **This is a sample, not the course data.** Each table looks like an **independent ~10% random sample** of its upstream table:
  - only 7,334 of 78,769 postings find their company (9.3%); only 3,476 of 14,003 companies have a posting [q1:postings_company_coverage, q1:company_used];
  - only 36,880 of 366,960 skill links find their posting (26,908 of 266,553 distinct jobs, 10.1%), and only 55,165 find their skill (24 of 244 distinct skill ids, 9.8%). Just 5,590 links find both [q1:links_job_coverage, q1:links_skill_coverage, q1:links_both_found];
  - `skills_dim` has 26 rows, while links use skill ids 0..257 [q1:id_ranges]. `sql` (id 0, the most frequent skill id in the links, 38,582) is not in it [q2:link_skill_freq_top];
  - rowid order is shuffled: 39,324 of 78,768 consecutive posting pairs ascend (50%), as do 183,517 of 366,959 link pairs [q1:rowid_order].
  The upstream sizes (about ten times these) are from memory and not verified here (§7).
- **Row counts** [profile]: job_postings_fact 78,769, skills_job_dim 366,960, job_company 14,003, skills_dim 26.
- **Licence.** The course repo declares no licence [fetch_barousse]. The postings are scraped third-party content (titles, company names, Google thumbnails). Treat it as **unstated, and redistribution-sensitive**.
- **Nature.** Real scraped postings, sampled by Spider. They are not anonymised: company names, links and the free-text titles are verbatim.

## 0.1 How Spider 2.0 uses it

| id | asks | gold SQL? | gold | reproduced |
|---|---|---|---|---|
| local168 | remote Data Analyst postings with a non-null annual salary; average salary when only the top-3 most demanded skills count | no (2 CSVs) | `_a` 92,689.2222; `_b` 96,521.7109375 | ✔ both [gold_168] |

- The cohort is only **46 postings** [q3:cohort], and the five most frequent skill ids tie at 3 postings each (0, 1, 5, 181, 182). Only python (1) is in `skills_dim` [q3:cohort_skills_raw, gold_168].
- `_a` is skills {0, 1, 5}, a tie broken by lowest skill_id; `_b` is {0, 1, 181}. Both average over the 9 (posting, skill) rows [gold_168].
- Joining to `skills_dim` (which most solvers would do) gives 104,100 over 4 rows, which matches neither [q3:local168_inner_join, gold_168]. So the gold answers depend on **orphan skill ids** and on tie order. Rebuilding `skills_job_dim` verbatim, orphans included, is mandatory.

## 1. Inventory, keys, joins

No PK or FK is declared (upstream declares them). All keys below are verified unique; there are no duplicate links [q1:key_uniqueness, q1:exact_duplicate_rows].

| Table | Rows | Key | Kind |
|---|---:|---|---|
| job_postings_fact | 78,769 | job_id (23..1,826,663) | activity: one row per posting, with a timestamp |
| skills_job_dim | 366,960 | (job_id, skill_id) | link table, no own time |
| job_company | 14,003 | company_id; `name` is unique too | lookup |
| skills_dim | 26 | skill_id (1..250) | lookup (7 types) [q1:skill_types] |

Joins and coverage: see §0. Every FK is mostly orphaned, so **no column can be a simkit `ref`** without stub entities (§2, §7). Counts:
- 71,435 postings point at 31,394 company ids that are missing [q4_dists];
- links point at 239,645 missing job ids and 220 missing skill ids [q4_dists];
- 2 of the 26 skills are never linked [q1:skills_used]; 26,908 of 78,769 postings have at least one link [q1:postings_with_links].

No table is derived from another, and none is a copy.

## 2. Event catalogue

| # | Event | Owner | Time | Attributes | Source rows | Count |
|---|---|---|---|---|---|---:|
| E1 | `job_posted` | posting (`job_id`) | `job_posted_date` (natural) | job_id, company_id (raw i64; 9.3% resolve), job_title_short, job_title, job_location, job_via, job_schedule_type, job_work_from_home, search_location, job_no_degree_mention, job_health_insurance, job_country, salary_rate, salary_year_avg, salary_hour_avg | job_postings_fact | 78,769 |

**Total business events: 78,769.**

Entities (3 tables, 380,989 rows):

| Entity | ext_id | created_at | Rows |
|---|---|---|---:|
| `companies` (job_company) | company_id | the company's first E1 for 3,476 companies (rule); the catalog start, 2022-12-31 06:03:30, for the 10,527 with no posting in the sample (rule) [q4_dists] | 14,003 |
| `skills` (skills_dim) | skill_id | the catalog start (rule): no time exists | 26 |
| `job_skills` (skills_job_dim, a link entity) | `job_id-skill_id` | the posting's E1 time for 36,880 links; the catalog start for 330,080 orphan links (rule) [q4_dists] | 366,960 |

Snapshot columns: `job_company.link_google` and `thumbnail` carry scrape-session tokens (`sca_esv=`, `ved=`, `encrypted-tbn0` image ids). They are values at scrape time, so they go into one `companies_snapshot` event at N. N = 2023-12-31 03:18:00, the last posting.

What is **not** an event, and why:
- **Skill tagging is not an event.** Upstream, skills are parsed from the posting text, so tagging happens at posting time. But 90% of the links have no posting in this sample and so no time. A link entity with a stated rule is honest; an event at an invented time would not be.
- **There is no posting lifecycle.** There is no expiry, fill or removal date. Salary fields are attributes of E1.
- **Companies are not owners.** 91% of postings point at a company that is not in the sample. The posting owns its own event; `company_id` is a plain integer.

## 3. Rebuild rules and blockers to an exact round trip

1. **Orphans everywhere.** Refs must resolve, and here 90% do not. Carry `company_id`, and the link's `job_id` and `skill_id`, as `i64`, not `ref`. Every table then rebuilds verbatim. The alternative is stub entities for the 31,394 + 239,645 + 220 missing ids, with a `listed` flag that `build.sql` filters on (§7).
2. **Salaries are float32 artefacts, but not uniformly.**
   - All 2,174 `salary_year_avg` values are float32-exact: x = float64(float32(x)). 2,151 are plain 2-place doubles, and `float32(cents/100)` rebuilds 2,170 of them [f1_float32].
   - `salary_hour_avg`: only 1,030 of 1,090 are float32-exact, and 132 have no short decimal at all, such as 26.63999938964844 and 18.89999961853028. These are float32 values printed to 16 digits and reparsed [f1_float32, q2:salary_hour_examples].
   - **Carry both as `f64` verbatim.** They are true floats (REAL), and this is trivially exact. A cents rule would fail 4 yearly and 227 hourly values.
3. **Salary columns follow `salary_rate`.** Year salary is set iff rate = 'year' (2,174), and hour salary iff rate = 'hour' (1,090). Rates month (23), week (1) and day (1) carry no number; 75,480 rows have no rate [q2:salary_rate_vs_columns]. That is a consistency rule for stage 2, not a derivation; carry all three.
4. **Booleans are INTEGER 0/1** (Postgres BOOLEAN upstream) [profile]. `job_work_from_home` = 1 exactly when `job_location = 'Anywhere'` (7,014 rows) [q2:wfh_vs_location]. Carry both: a cheap check, not a derived-column dependency.
5. **Timestamps** are `YYYY-MM-DD HH:MM:SS` with no zone, in every row [q2:posted_date_format]. Read them as UTC and format them back with `%Y-%m-%d %H:%M:%S`. 75,984 distinct times over 78,769 rows: 2,785 ties [q2:duplicate_timestamps, q4_dists]. Tie order is irrelevant to the multiset rebuild; use `ord = job_id`.
6. **NULL vs empty.** No `''` and no `'\N'` anywhere [profile]. One NULL `job_title` (job 15425) [q2:null_title]; `job_title` has one value with trailing spaces (`Data Engineer     `) [q2:title_whitespace]; titles contain emoji and CJK text. Keep all text byte-exact.
7. **Rows without time.** Every posting has a time. Companies, skills and links get times by rule (§2).

**Verdict:** exact, with caveats. The caveat is that every relation is a raw integer, not a ref, because of the sampling. local168's gold depends on that.

## 4. Measured quirks

- **Sampling breaks every join** (§0, §1). It is the dominant property of this catalog. Any "top skills" or "company" analysis on it measures the sample, not the market.
- **Skill names missing for the top skills.** sql (0), r (5) and others are absent; python (1) is present. Python is the only top-10 link skill with a name [q2:link_skill_freq_top].
- **search_location ≠ job_country** on 20,648 rows. These are all US rows, searched as `New York, United States` and similar; `job_country` is NULL on 6 [q2:country_vs_search, q2:search_location_top, q2:country_top].
- **Odd countries.** Sudan has 2,104 postings, as many as Singapore (2,397), and `search_location` 'Georgia' 3,327 [q2:country_top, q2:search_location_top]. This looks like the scraper's search-location list, not the labour market.
- **Time-of-day fingerprint.** Postings dip at 05:00 (545) and spike at 07:00 (6,141), 00:00 (5,088) and 23:00 (4,060) [q2:posted_hour]. 1,257 times have :00 seconds and 58 have :00:00 [q2:posted_seconds]. The times are probably derived from relative "posted N hours ago" labels at scrape time, so they are approximate.
- **January is heavy:** 9,241 postings against 5,185–7,609 in the other months; 2022-12 has 181 [q2:posted_by_month].
- **One company dominates:** company 572 has 666 postings; 24,376 companies have exactly 1 [q2:postings_per_company, q2:postings_per_company_max].
- **job_via** is "via …" in 78,760 rows, Indonesian "melalui …" in 6, and NULL in 3 [q2:via_prefix].

## 5. Distributions to fit (stage 2)

| Quantity | Value |
|---|---|
| arrivals | 366 days, per day p5 124, p50 219, p95 311, max 383 (2023-01-20) [q4_dists]; weekdays 10,759–12,815 each, Sat 9,308, Sun 8,106 |
| inter-arrival | p50 113 s, p90 1,215 s, p99 3,426 s; 2,785 exact ties [q4_dists] |
| title mix | Data Analyst 19,743, Data Engineer 18,878, Data Scientist 17,189, Business Analyst 4,948, Software Engineer 4,459, Senior DE 4,411, Senior DS 3,679, Senior DA 2,891, MLE 1,405, Cloud 1,166 [q2:title_short] |
| salary disclosed | year 2.8%, hour 1.4% [q2:salary_rate_vs_columns] |
| salary_year_avg | p5 58,926, p25 90,000, p50 115,000, p75 150,000, p95 200,000, max 375,000; mode 90,000 (120) [q4_dists]. By title: DA 94k … Senior DS 154k [q2:title_short] |
| salary_hour_avg | p25 27.5, p50 46.5, p75 62.5, p95 85, max 391 [q4_dists] |
| flags | remote 8.9%, no-degree 30.7%, health insurance 10.9% [q2:booleans] |
| schedule | Full-time 70,308, Contractor 3,547, NULL 1,300, Internship 866, Part-time 769 [q2:schedule] |
| skills per job (links) | 1: 190,539; 2: 57,150; 3: 14,559; …; 9: 1 [q2:skills_per_job_in_links] (a 10% sample of links, so per-job counts are thinned) |
| postings per company | 1: 24,376; 2: 5,073; 3: 1,934; long tail to 666 [q2:postings_per_company] |

## 6. simkit mapping sketch

```python
p.entity("companies", key="company_key", cols={"ext_id": i64(), "name": text(), "link": opt(text()),
         "link_google": opt(text()), "thumbnail": opt(text())})           # link_google, thumbnail: snapshot
p.entity("skills", key="skill_key", cols={"ext_id": i64(), "skills": text(),
         "type": cat("programming", "databases", "analyst_tools", "webframeworks", "cloud", "async", "sync")})
p.entity("job_skills", key="job_skill_key", cols={"ext_id": text(), "job_id": i64(), "skill_id": i64()})
p.event("job_posted", cols={"job_id": i64(), "company_id": i64(), "job_title_short": cat(...10 titles...),
        "job_title": opt(text()), "job_location": opt(text()), "job_via": opt(text()), "job_schedule_type": opt(text()),
        "job_work_from_home": i32(), "search_location": text(), "job_no_degree_mention": i32(),
        "job_health_insurance": i32(), "job_country": opt(text()), "salary_rate": opt(cat("year", "hour", "month", "week", "day")),
        "salary_year_avg": opt(f64()), "salary_hour_avg": opt(f64())})
```

Ingest:
- `job_posted` ORDER BY job_id, `ord = job_id`, time `iso_time(job_posted_date, '%Y-%m-%d %H:%M:%S')`. The owner is the posting: a per-posting key, or one `postings` shard if simkit needs an entity owner.
- `companies` ORDER BY company_id, created_at = min posting time, else the catalog start.
- `job_skills` ORDER BY job_id, skill_id, created_at = the posting's time, else the catalog start.
- `skills` created_at = the catalog start.

`build.sql`: each table is a straight projection of its entity or event. `job_posted_date` = `strftime('%Y-%m-%d %H:%M:%S', event_time)`; the salaries pass through as REAL.

Stage-2 owners: a **posting source** shard per search_location, emitting `job_posted` on a weekday-heavy daily rhythm with a title mix and salary disclosure as a 4% branch. Companies are drawn Zipf-like. The volume is about 79k events plus 381k entity rows; a sample profile is optional.

## 7. Open questions and risks

- **Upstream sizes.** The full course data is recalled as about 788k postings, 140k companies, 259 skills and 3.67M links: roughly 10× each table here. That fits the measured ~10% coverage, but the CSVs (on Google Drive) were not fetched, so the claim is **unverified**. A full copy would remove the orphans and make this a natural catalog.
- **Refs vs raw ids.** Raw `i64` keeps the round trip exact but loses the relation. Stub entities would let a ref resolve, at the cost of 271k phantom rows filtered out in `build.sql`. Decide project-wide.
- **Link entity vs event.** `job_skills` could instead be a `job_skill_tagged` event for the 36,880 links with a posting, but the 330,080 orphans would still need a rule time.
- **Licence and PII.** The licence is unstated. The data is scraped third-party postings with company names, links and Google thumbnail URLs. Fitting statistics is fine; check before redistributing rows.
- **The gold is fragile.** local168's two gold answers differ only by how a 5-way tie breaks. Any engine that changes tie order gets the other answer. Saved queries should add a deterministic tie-break.

## Summary

- Exact round trip: **yes, with caveats**. Every table rebuilds verbatim, but company, job and skill relations must be raw integers, because the sample leaves about 90% of them orphaned.
- Proposed dataset name: **`jobpostings`**.
- Event types: **1** (`job_posted`, plus `companies_snapshot`); **3** entities (companies, skills, job_skills).
- Event shape: **partly imposed**. Postings are natural timestamped events; companies, skills and the 366,960 links get rule times.
- Hardest blocker: Spider's independent ~10% sampling of each table. The FKs are 90% orphaned, so nothing can be a resolving ref, and local168's gold depends on the orphan skill ids.
