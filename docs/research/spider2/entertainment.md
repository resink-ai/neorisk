# EntertainmentAgency (Spider 2.0-lite): reverse-engineered event log

Source: `data/spider2/EntertainmentAgency.sqlite` (240 KB), opened read-only. `scripts/entertainment/rq.py` copies the file into an in-memory SQLite and runs named blocks; the file itself is never written.

Every number below comes from one of these scripts:
- a named query in `scripts/entertainment/q*.sql`;
- `profile.py` (storage classes, NULL / `''` / `'\N'`, whitespace, min, max per column);
- `coltypes.py` (results types, using the repo's rule in `apps/dataset/src/dataset/tables.py`);
- `gold_check.py` (a query's answer against a gold CSV, as a multiset);
- `d1_duck_helpers.sql`: DuckDB generates the four `ztbl*` helpers and diffs them against the source, which is attached `READ_ONLY`.

The raw outputs are in `scripts/entertainment/out_*.txt`. A reference such as `[q2:days_dist]` means file `q2_engagements.sql`, block `-- name: days_dist`. Gold files are in `scripts/entertainment/gold/`.

## 0. What this catalog is

- **Dataset.** The **Entertainment Agency** sample database from John L. Viescas and Michael J. Hernandez, *SQL Queries for Mere Mortals*. The evidence:
  - The agents, members and customers are the book's recurring cast: agents Carol and Caleb Viescas, member Michael Hernandez, and Pattersons, Hallmarks, Kennedys and Sheskeys, shared with BowlingLeague and school_scheduling [q1:agents, q1:members].
  - The schema has the book's Access-port habits: `ztbl*` driver tables, `nvarchar (n)` types and `DEFAULT 0` on keys.
  - There is a joke agent, "Daffy Dumbwit", with salary 50 and no engagements [q1:agents, q1:unused_rows].
- **Date shift.** The engagements run 2017-09-02 .. 2018-03-13, but agents were hired 1997–2000 and entertainers entered 1995–1998 [q5:hired_vs_first_engagement]. The helper calendars cover 2017–2019. This fits a later edition that moved only the activity dates forward, presumably the 4th (2018). **Unverified.**
- **Row counts** [profile]: Engagements 111, Entertainers 13, Members 25, Entertainer_Members 40, Entertainer_Styles 32, Musical_Styles 25, Customers 15, Musical_Preferences 36, Agents 9, ztblDays 1,096, ztblWeeks 156, ztblMonths 36, ztblSkipLabels 60. Total 1,654, of which 1,348 are calendar or number helpers.
- **Licence.** Unstated. These are the book's companion sample files.
- **Nature.** **Course data**, hand-made for a textbook. The prices follow a rough per-entertainer rate with noise (§4).

## 0.1 How Spider 2.0 uses it

Three questions use db `EntertainmentAgency`. All three read only the style tables (Musical_Styles, Musical_Preferences, Entertainer_Styles, Entertainers, Customers). None reads Engagements or the helpers.

| id | analysis | gold SQL? | gold value | reproduced |
|---|---|---|---|---|
| local131 | per style: how often it is a customer's 1st, 2nd and 3rd preference, in one row | **yes** (`gold/local131.sql`) + CSV `_a` | `_a` has 25 rows (all styles, zeros included), e.g. Standards 2/2/0, Jazz 2/1/0 | ✔ `_a` exactly, 25 of 25, via a LEFT JOIN [q4:local131]. The gold SQL itself returns only the 20 styles with a preference (its HAVING drops the 5 zero rows), so it does **not** equal its own CSV [q4:local131_gold_sql, out_gold_check.txt] |
| local132 | entertainer–customer pairs where the customer's 1st and 2nd preferences equal the entertainer's 1st and 2nd strengths, either order; both sides with ≤ 3 styles | no (CSV `_a`) | 6 pairs: JV & the Deep Six–Waldal, Topazz–Brehm, Katherine Ehrlich–Hallmark, Julia Schnebly–Hallmark, Coldwater Cattle Company–Thompson, Carol Peacock Trio–Patterson | ✔ 6 of 6 [q4:local132] |
| local133 | weighted score per style (3/2/1 for 1st/2nd/3rd); \|score − mean score\| over the 20 ranked styles | no (CSVs `_a`, `_b`) | mean 4.05; Standards 10 → 5.95, Jazz 8 → 3.95 … 80's Music 1 → 3.05 | ✔ `_a` 20 of 20 [q4:local133]. `_b` has the same differences with two extra columns (score, mean), so it differs only in shape |

The saved queries should compare source with rebuilt, not with gold: local131's gold SQL and CSV disagree.

## 1. Inventory, keys, joins

Every declared PK is unique, and rowid order equals PK order everywhere [profile]. All 9 FKs resolve with 0 orphans [q1:fk_orphans].

| Table | Rows | Key | Kind |
|---|---:|---|---|
| Engagements | 111 | EngagementNumber 2..131 (20 gaps) → CustomerID, AgentID, EntertainerID | activity (start and end date and time) |
| Agents | 9 | AgentID 1..9 | party (DateHired) |
| Entertainers | 13 | EntertainerID 1001..1013 | party (DateEntered) |
| Members | 25 | MemberID 101..125 | party (no time) |
| Entertainer_Members | 40 | (EntertainerID, MemberID) | link + Status |
| Customers | 15 | CustomerID 10001..10015 | party (no time) |
| Musical_Styles | 25 | StyleID 1..25 | lookup |
| Entertainer_Styles | 32 | (EntertainerID, StyleID); StyleStrength unique per entertainer | ranked link |
| Musical_Preferences | 36 | (CustomerID, StyleID); PreferenceSeq unique per customer | ranked link |
| ztblDays / ztblWeeks / ztblMonths / ztblSkipLabels | 1,096 / 156 / 36 / 60 | DateField / WeekStart / (YearNumber, MonthNumber) / LabelCount | **derived**: generated calendars and a number list (§3.1) |

Coverage [q1:parents_without_children, q1:unused_rows]:
- Customers 10008 (Gehring) and 10011 (Bonnicksen) have no engagements.
- Agent 9 (Dumbwit) has no engagements, and entertainer 1009 (Katherine Ehrlich) has none.
- 5 styles are unused by both entertainers and customers: 50's Music, Rap, Elvis, Karaoke, 90's Music. 8 styles have no entertainer, and 5 have no preference.
- Every customer has 2–3 preferences, and every entertainer has 1–3 styles. Rank values are unique within each owner, 0 duplicates [q1:pref_seq_unique_per_customer, q1:strength_unique_per_entertainer].
- **Members are shared.** 13 of 25 members belong to 2 or 3 entertainers; 120 Hernandez and 121 Ehrlich belong to 3 [q1:members_in_many]. Every entertainer has exactly one member with Status 2 (13 of 13). The 4 solo acts' only member has Status 2 [q5:status2_per_entertainer, q5:solo_status]. Status 2 looks like "leader or contact".
- **Missing engagement numbers:** 1, 18, 20, 25, 29, 33, 39, 40, 47, 50, 54, 57, 65, 67, 86, 93, 94, 113, 117, 130 [q1:missing_numbers]. These are deleted rows. The numbers are verbatim ids, so they need no rule.
- **Implied joins.** Two customers share a phone number with a member: Kerry Patterson ↔ Katherine Ehrlich (555-0399), and Estella Pundt ↔ Steve Pundt (555-9938) [q5:cust_member_phone]. No name matches. There is no ZIP lookup table in this file.

## 2. Event catalogue

Only Engagements is activity. There is **no booking or contract date**; the only times are the performance window. So the one event is stamped at the performance start, and that time is natural for the performance but imposed for the booking.

| # | Event | Owner | Time | Attributes | Source rows | Count |
|---|---|---|---|---|---|---:|
| E1 | `engagement_booked` | customer (ord = EngagementNumber) | `StartDate` + `StartTime` (natural start; booking time unknown) | engagement_number, entertainer_id (ref), agent_id (ref), end_date (text), stop_time (text), contract_price (i64 dollars) | Engagements | 111 |

**Total events: 111.**

Entities (8 tables, 215 rows):

| Entity | Rows | created_at | natural? |
|---|---:|---|---|
| agents | 9 | `DateHired` (1997-05-15 .. 2000-02-05) | natural |
| entertainers | 13 | `DateEntered` (1995-01-20 .. 1998-10-12) | natural |
| members | 25 | the earliest `DateEntered` among the member's entertainers | rule |
| entertainer_members | 40 | the entertainer's `DateEntered`; link entity, ext_id `"EntertainerID/MemberID"`, + status | rule |
| entertainer_styles | 32 | the entertainer's `DateEntered`; ext_id `"EntertainerID/StyleID"`, + style_strength | rule |
| musical_styles | 25 | T0 = 1995-01-20 (the earliest natural date) | rule |
| customers | 15 | first engagement start; for the 2 without one, T0 | rule |
| musical_preferences | 36 | the customer's created_at; ext_id `"CustomerID/StyleID"`, + preference_seq | rule |

What is **not** an event or an entity, and why:
- **`ztblDays`, `ztblWeeks`, `ztblMonths` and `ztblSkipLabels`** are generated, not recorded. Each equals a closed-form series with 0 differing rows in SQLite and in DuckDB (§3.1). They are derived: build.sql generates them, and they need no events and no entity rows. Making them entities would put 1,348 rows of the log on calendar arithmetic.
- **An engagement end** is not an event. EndDate and StopTime describe the booked window. An `engagement_ended` at EndDate + StopTime would be ambiguous on the 17 engagements whose StopTime is at or after midnight (§3.3). Carry them as text on E1.
- **Hiring and entering** stay as entity `created_at`: they predate the first engagement by 17 to 22 years (§4). As separate events they would only form a long, empty prefix.
- **Preferences and strengths** have no time. They are static ranked links, not changes.

Snapshot **N = 2018-03-13**, the last EndDate [q5:hired_vs_first_engagement].

## 3. Rebuild rules and blockers to an exact round trip

1. **Derived helper tables, proven exact** [q3:*, d1_duck_helpers]:
   - `ztblDays` = every day 2017-01-01 .. 2020-01-01 inclusive (1,096 rows; note the extra 2020-01-01). 0 rows differ both ways in SQLite and DuckDB.
   - `ztblWeeks` = Sunday-to-Saturday weeks from 2017-01-01, a Sunday, for 156 weeks (WeekEnd = start + 6). 0 / 0.
   - `ztblMonths` = 36 months from 2017-01: `MonthYear` is `'<English month name> <YYYY>'`; then YearNumber, MonthNumber, MonthStart and MonthEnd (the last day); then 12 one-hot month columns. 0 / 0. In DuckDB, `strftime(d, '%B %Y')` and `last_day(d)` reproduce the text.
   - `ztblSkipLabels` = 1..60. 0 / 0.
   - The DuckDB forms are in `d1_duck_helpers.sql`, ready to paste into build.sql. The ranges (2017-01-01, 2020-01-01, 156, 36, 60) are constants: nothing in the data implies them, since the engagements cover only 2017-09 .. 2018-03.
2. **No other derived columns.** ContractPrice is not a function of days × hours: the per-entertainer rate per day-hour varies within each entertainer, for example 1008's ranges from 30.6 to 83.3 [q2:price_per_day_hour]. Carry it.
3. **Times.**
   - StartDate and EndDate are `YYYY-MM-DD`, and StartTime and StopTime are `HH:MM:SS`, all 111 rows [q2:formats]. All minutes and seconds are zero [q5:minutes_nonzero].
   - `event_time = StartDate || ' ' || StartTime`, as UTC. The view formats it back into two columns, with `%Y-%m-%d` and `%H:%M:%S`.
   - **17 engagements have StopTime ≤ StartTime**: 20:00 → 01:00, 18:00 → 00:00 and the like [q2:stop_before_start]. They end after midnight. That is why the end stays as text and is not turned into a timestamp.
   - `DateHired` and `DateEntered` are `YYYY-MM-DD`. They are entity `created_at`, formatted back the same way.
4. **Numbers.**
   - `Salary` (declared `decimal(15,2)`) holds only integers, 50..35,000, so it is int64 in results [coltypes]. Carry it as i64 and not as cents, or the view must cast back to an integer.
   - `ContractPrice` is the same: integers 110..14,105, and every one ends in 0 or 5 [q2:price_last_digit].
   - `CommissionRate` (declared `float(24)`) is REAL: 0.01, 0.035, 0.04, 0.045, 0.05, 0.055, 0.06. Each prints at 17 digits as the plain decimal, so it is a clean double and not a float4 artefact [q1:agents]. Carry it as `f64` verbatim.
5. **NULL vs empty.** No `''` and no `'\N'`. NULLs: EntWebPage 5, EntEMailAddress 6, Members.Gender 1 (Jim Glynn) [profile]. No whitespace issues. No mixed columns [coltypes].
6. **Rows without time.** Members, styles, customers and the three links get `created_at` from the rules in §2. Every rule time is ≤ the first event that uses the row.

**Verdict:** exact round trip, yes. The only care is generating the helpers with the right constants, and keeping end date and stop time as text.

## 4. Measured quirks

- **Two eras.** Hires (1997–2000) and entries (1995–1998) are 17–22 years before the first engagement (2017-09-02) [q5:hired_vs_first_engagement]. 0 engagements start before their entertainer entered or their agent was hired [q2:engagements_before_entered_or_hired].
- **EngagementNumber is not in date order.** Only 82 of 110 consecutive pairs have a non-decreasing StartDate [q2:number_vs_startdate].
- **Double booking.** Entertainer 1008 (Country Feeling) has 2 overlapping pairs: 85/87 on 2018-01-07, and 99/120 inside 99's 32-day run [q5:overlap_pairs]. Engagement 99 is the only one longer than 11 days, and at 14,105 the only price above 5,000 [q5:outliers].
- **Weekdays.** Starts fall on Sunday 32, Monday 20, Tuesday 32, Saturday 26 and Friday 1, and never on Wednesday or Thursday [q2:weekday]. This is a hand-entered pattern.
- **Volume by month:** 2017-09 16, 10 22, 11 7, 12 17, 2018-01 28, 02 20, 03 1 [q2:per_month]. The November dip and the March tail are not explained.
- **Prices track the act.** Engagements cost per day-hour about 16–20 (solo acts 1004, 1011, 1012), 31–33 (Topazz), 46–53, 61–66 or 76–95 (the larger bands) [q2:price_per_day_hour]. That is a per-entertainer rate with ±10% noise, plus outliers such as 1001's 70.0 and 1008's 30.6.
- **Styles rarely match.** Only 30 of 111 engagements pair a customer with an entertainer who plays one of the customer's preferred styles [q5:style_matches_customer_pref]. The preferences are not used for booking.
- **Placeholders for outer-join exercises:** an agent, an entertainer and two customers with no engagements, and five styles nobody uses (§1).

## 5. Distributions to fit (stage 2)

| Quantity | Value |
|---|---|
| engagement starts | 111 over 2017-09-02 .. 2018-03-04; 1–4 per start date (36 dates with 1, 15 with 2, 7 with 3, 6 with 4) [q5:engagements_per_start_date] |
| gap between distinct start dates | 1 d (33), 4 d (10), 6 d (8), else 2–9 d [q5:gap_between_start_dates] |
| length in days | 1–11, roughly uniform over 2–10; one 32-day outlier [q2:days_dist] |
| daily hours | 2–6, uniform (21–24 each) [q5:hours_dist] |
| start time | 12:00–20:00 on the hour; 20:00 is the mode (17) [q5:start_time_dist] |
| contract price | p10 290, p50 950, p90 2,300, mean 1,266, max 14,105 [q2:price_quantiles]; ≈ rate(entertainer) × days × hours |
| per customer | 6–13 engagements (13 active customers) [q2:per_customer] |
| per agent | 6–19 [q2:per_agent]; 75 distinct customer–agent pairs over 111 engagements [q5:customer_agent_affinity] |
| per entertainer | 6–15 [q2:per_entertainer] |

## 6. simkit mapping sketch

```python
p.entity("agents", key="agent_id", cols={"ext_id": text(), "first_name": opt(text()), "last_name": opt(text()),
         "street_address": opt(text()), "city": opt(text()), "state": opt(text()), "zip": opt(text()),
         "phone": opt(text()), "salary": opt(i64()), "commission_rate": opt(f64())})        # created_at = DateHired
p.entity("entertainers", key="entertainer_id", cols={"ext_id": text(), "stage_name": opt(text()), "ssn": opt(text()),
         ..., "web_page": opt(text()), "email": opt(text())})                              # created_at = DateEntered
p.entity("members", key="member_id", cols={"ext_id": text(), "first_name": opt(text()), "last_name": opt(text()),
         "phone": opt(text()), "gender": opt(text())})
p.entity("entertainer_members", key="em_id", cols={"ext_id": text(), "entertainer_id": ref("entertainers"),
         "member_id": ref("members"), "status": opt(i64())})
p.entity("musical_styles", key="style_id", cols={"ext_id": text(), "style_name": opt(text())})
p.entity("entertainer_styles", key="es_id", cols={"ext_id": text(), "entertainer_id": ref("entertainers"),
         "style_id": ref("musical_styles"), "style_strength": i64()})
p.entity("customers", key="customer_id", cols={"ext_id": text(), "first_name": opt(text()), ..., "phone": opt(text())})
p.entity("musical_preferences", key="mp_id", cols={"ext_id": text(), "customer_id": ref("customers"),
         "style_id": ref("musical_styles"), "preference_seq": i64()})
p.event("engagement_booked", cols={"customer_id": ref("customers"), "engagement_number": i64(),
        "entertainer_id": ref("entertainers"), "agent_id": ref("agents"), "end_date": text(), "stop_time": text(),
        "contract_price": i64()})
```

Ingest:
- `-- event: engagement_booked owner=customer_id ord=engagement_number`, with `event_time = StartDate || ' ' || StartTime`, ORDER BY EngagementNumber.
- Entities carry `created_at` per §2. Members use `(SELECT min(e.DateEntered) FROM Entertainer_Members m JOIN Entertainers e …)`.

build.sql:
- `Engagements`: from E1. StartDate = `strftime(event_time, '%Y-%m-%d')` and StartTime = `strftime(event_time, '%H:%M:%S')`; the rest comes verbatim.
- `Agents.DateHired` and `Entertainers.DateEntered`: from `created_at`, formatted with `%Y-%m-%d`.
- The links come from the link entities.
- The four `ztbl*` tables come from `generate_series` / `range` as in `d1_duck_helpers.sql`.

Stage 2 owners:
- **customer** (13 active) books engagements with an agent;
- **entertainer** shard prices them, with rate × days × hours × noise;
- **agent** is an attribute draw.

The volume is tiny (111 events plus 215 entity rows).

## 7. Open questions and risks

- **Edition, date shift and licence** are unverified (§0). Low risk for fitting; confirm before redistributing rows.
- **Booking time is invented.** E1 sits at the performance start. A stage-2 sim that models booking lead time has no data to fit it; say so in CONTEXT.md.
- **Helper constants.** The ztbl ranges (through 2020-01-01; 156 weeks; 60 labels) are copied, not inferred. If another packaging of the file has different ranges, the build constants change.
- **The local131 gold SQL disagrees with its own CSV** (20 vs 25 rows). The saved query should use the LEFT JOIN form, which equals the CSV, or simply compare source with rebuilt.
- **Members' created_at** (the earliest entertainer entry) is a rule. Members have no date of their own.

**Summary**
- Exact round trip: yes. The four ztbl helpers are generated with 0 differing rows (SQLite and DuckDB); everything else is carried verbatim.
- Dataset name: `entertainment`.
- Event types 1 (`engagement_booked`); entities 8 (agents, entertainers, members, entertainer_members, musical_styles, entertainer_styles, customers, musical_preferences); 4 derived helper tables.
- Event shape: mostly imposed. Only 111 engagements are activity; the rest is static parties and ranked links with rule times, and the booking time itself is the performance start.
- Hardest blocker: none for exactness. The real gap is that there is no booking date, so the one event's time is the performance start. Engagement ends after midnight (17 rows) must stay as text.
