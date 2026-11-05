# Fresh Segments (Spider 2.0-lite, `bank_sales_trading`): reverse-engineered event log

Source: the tables `interest_metrics` and `interest_map` of `data/spider2/bank_sales_trading.sqlite`, opened read-only.

`scripts/freshsegments/rq.py` copies the file into an in-memory SQLite and runs named blocks; the file itself is never written. Every number below comes from one of these:
- a named block in `scripts/freshsegments/q*.sql`;
- `f1_duck_rules.py` (DuckDB 1.5.6).

Raw outputs are `scripts/freshsegments/out_*.txt`. `[q2:null_rows_by_neighbour]` means file `q2_derived.sql`, block `null_rows_by_neighbour`. Gold files are in `scripts/freshsegments/gold/`.

## 0. What this catalog is

- **Dataset.** This is **Case Study #8 "Fresh Segments"** of Danny Ma's *8 Week SQL Challenge*. The evidence:
  - Same two tables and the same columns, including the underscore-prefixed `_month` and `_year`.
  - Monthly interest metrics from 07-2018 to 08-2019 [q1:month_year_values].
  - The case study's well-known 1,194 rows with no month [q1:metrics_null_patterns].
  - The one ID-bearing NULL-month row (interest 21246) [q2:id_present_null_month_row].
- **Types are Spider/pandas artefacts.** In interest_metrics, `_month`, `_year` and `interest_id` are REAL (`7.0`, `2018.0`, `32486.0`), as a pandas float column with NaNs stores them. `ranking` is INTEGER [q1:typeof_metrics]. `interest_map.id` is INTEGER [q1:typeof_map].
- **Row counts** [q1:row_counts]: interest_metrics 14,273; interest_map 1,209.
- **Licence.** Unstated. It is course data.
- **Nature.** Course data. It looks derived from a real ad-tech product's interest taxonomy: real-sounding names and summaries, and `created_at` stamps from 2016-05-26 to 2019-05-06 [q3:created_range]. The metric values are on a 2-dp grid [q2:value_grid]. Whether they are real or anonymised is not measurable here.

## 0.1 How Spider 2.0 uses it

Two of the 15 `bank_sales_trading` questions use these tables.

| id | asks | gold SQL? | reproduced |
|---|---|---|---|
| local077 | for 09-2018..08-2019: per month, the interest with max composition / index_value; its value; the 3-month rolling average; and the top interest and value 1 and 2 months back | no; 4 CSVs | ✔ `local077_b.csv` (and `_a`, `_c` up to date format and rolling-avg rounding) [q4:local077]. All 12 months match on names and on max values exactly. The rolling average differs by ≤ 2e-15 (float summation order). `_d` blanks the first two rolling averages. No month has a tie for the top [q4:local077_ties] |
| local078 | top 10 and bottom 10 interests by their maximum composition across months; time (MM-YYYY), name, composition | yes (`gold/local078.sql`) + 1 CSV | ✔ The same 20 rows [q4:local078_gold_sql]. The gold SQL partitions by **interest_name**, so ids 6364 and 45668 ("Pizza Lovers") merge; neither is in the top or bottom 10 [q1:duplicate_names, q4:local078_pizza_lovers_join]. The CSV lists the bottom 10 ascending even though the SQL orders DESC; the rows match as a multiset |

Both need `month_year` text verbatim, composition and index_value exactly, and the id → name join.

## 1. Inventory, keys, joins

No PK or FK is declared.

| Table | Rows | Key | Kind |
|---|---:|---|---|
| interest_map | 1,209 | `id` (1..51678, unique) [q1:key_uniqueness_map] | lookup with real `created_at` and `last_modified` |
| interest_metrics | 14,273 | (month_year, interest_id), unique on the 13,079 dated rows [q1:key_uniqueness_metrics] | monthly snapshot per interest; `ranking` and `percentile_ranking` are **derived** (§3.1) |

- **metrics → map:** 0 orphan ids [q1:orphans_metrics_to_map]. 7 map ids never appear in metrics [q1:map_ids_without_metrics, q3:map_unused].
- **interest_id is integral** in all 13,080 non-NULL rows [q1:interest_id_integral], so the ref resolves on value.
- **NULL patterns** [q1:metrics_null_patterns]:
  - 13,079 rows are complete;
  - 1,193 have month, year and id all NULL;
  - 1 has NULL month and year but id 21246.
- **NULL months are their own ranking group.** `ranking = RANK() OVER (PARTITION BY month_year ORDER BY index_value DESC)` holds for all 14,273 rows, with the 1,194 NULL-month rows ranked among themselves (N = 1,194) [q2:ranking_is_rank_by_index_value, q2:all_null_rows_ranked_together].
- **Physical position of the NULL rows:**
  - 26 sit inside month blocks, but their rank does not fit between their neighbours (0 of 26) [q2:null_rows_rank_fit];
  - 1,168 form a trailing block, rowids 13,106–14,273 [q2:null_rows_by_neighbour].

  So file position cannot recover their month.
- **_month and _year** equal `month_year` (`MM-YYYY`) in all 13,079 dated rows [q1:month_year_consistency]. They are derived.
- **interest_map.interest_name:** one duplicate, "Pizza Lovers" (6364, 45668) [q1:duplicate_names].
- **id vs created_at order:** non-decreasing in 1,207 of 1,208 pairs [q3:id_vs_created_order]. Ids are assigned in creation order.

## 2. Event catalogue

| # | Event / entity | Owner | Time | Attributes | Source rows | Count |
|---|---|---|---|---|---|---:|
| N1 | `interests_created` (entity `interests`) | interest | `created_at` (natural) | ext_id = id, interest_name, interest_summary (opt) | interest_map | 1,209 |
| E1 | `interest_modified` | interest | `last_modified` (natural) | none (the stamp is the event) | interest_map where last_modified > created_at | 709 [q3:created_modified_order] |
| E2 | `interest_metrics_reported` | interest (opt) | **rule:** the first day of the month **after** `month_year` (the month's close); N for NULL-month rows | month_year (opt text), interest_id (opt ref), composition (f64), index_value (f64) | interest_metrics | 14,273 |

**Total: 2 business event types (14,982 events) + 1 entity (1,209 creation events) = 16,191 log rows.**

- **Why the month's close.** In 188 rows, the interest was created *during* the metric month, after its first day [q3:metric_rows_before_created]. In 0 rows was it created after the month ended [q3:metric_rows_before_created_month_end]. Stamping at month start would reference an entity before its creation; stamping at the next month's first day never does.
- **Snapshot N = 2019-09-01 00:00:00**, the close of 08-2019. It is after the last `last_modified` (2019-08-26 11:24:45) [q3:created_range].
- **The 1,194 NULL-month rows** have no time. By rule they are stamped at N, with `month_year` null. 1,193 of them also have a null `interest_id`, so they have no owner: use a single fallback owner (`interest_id` null → partition "unknown"). Their month cannot be inferred (§1).
- **Not entities:**
  - months: 14 values with no table of their own;
  - rankings: derived per month.
- **`last_modified` as an event.** The 500 rows with last_modified = created_at get no E1; the view rebuilds `last_modified` as `coalesce(E1 time, created_at)`. What changed at that time is unknown, so E1 carries no attributes. The alternative is to treat `last_modified` as a snapshot column at N, but the stamps are real times, so an event is truer to the data.

## 3. Rebuild rules and blockers to an exact round trip

1. **ranking and percentile_ranking are derived** [q2:ranking_is_rank_by_index_value, f1]:
   - `ranking = RANK() OVER (PARTITION BY month_year ORDER BY index_value DESC)`. NULL month_year is one partition, as both SQLite and DuckDB treat it. 14,273 of 14,273.
   - `percentile_ranking = round(100 * (1 - ranking / N_month), 2)`, where N_month is the row count of the partition. 14,273 of 14,273 in SQLite, and 14,273 of 14,273 in DuckDB [f1]. There is no tie-rounding trouble on this data.
   - Ties in index_value are common: 2,879 distinct (month, index_value) pairs over 14,273 rows [q5:index_value_ties]. RANK, not ROW_NUMBER, is required.
2. **_month and _year** are `CAST(substr(month_year,1,2) AS DOUBLE)` and `CAST(substr(month_year,4,4) AS DOUBLE)`, NULL when month_year is NULL. DuckDB matches 14,273 [f1].
3. **REAL ids.** `interest_id` is REAL in the source. The view must write `CAST(key→ext_id AS DOUBLE)`; numbers compare by value, but the column type must be float64.
4. **Floats.** composition, index_value and percentile_ranking are all on the 2-dp grid [q2:value_grid]. Carry composition and index_value as `f64` verbatim, or as integer hundredths (`/100.0` reproduces the double). percentile_ranking is rebuilt.
5. **Text.**
   - `interest_summary` is NULL in 20 rows, never `''`. 4 summaries end in a trailing space, which must stay byte-exact [q1:map_text_formats, q3:summaries_untrimmed].
   - All map text is ASCII [q3:non_ascii].
   - Stamps are `YYYY-MM-DD HH:MM:SS` (1,209 / 1,209); format back with `%Y-%m-%d %H:%M:%S`.
   - `month_year` is `MM-YYYY`. Carry it as opt text in E2, or rebuild it from the event time minus one month for dated rows.
6. **Rows without time:** the 1,194 NULL-month rows go at N by rule (§2). There are no duplicates (the key is unique on dated rows; NULL rows differ by values).

**Verdict:** exact. The only rule-made times are the month-close stamp and the NULL rows at N.

## 4. Measured quirks

- **1,194 NULL-month rows.** One has an id (21246, ranking 1191) and 1,193 have no id [q2:id_present_null_month_row]. Their composition (mean 3.935) is in line with dated months [q5:composition_min_by_month].
- **Composition floor.** The minimum composition is 1.51–1.71 in every month [q5:composition_min_by_month], which is a reporting threshold. The 1.51–1.61 floor in later months is the case study's "composition < some cut" filter.
- **Interest churn.** 729 interests in 07-2018 grow to 1,149 in 08-2019, peaking in 03-2019 (1,136) [q1:month_year_values].
  - 480 of 1,202 interests appear in all 14 months; 13 appear once [q3:months_per_interest].
  - 438 have gaps in their presence [q5:gaps_in_presence].
  - 04-2019 → 05-2019 loses 246 interests (853 of 1,099 continue) [q5:month_to_month_persistence].
- **created_at bursts.** 154 interests share `2016-05-26 14:57:59` (ids < 1000) and 88 share `2017-03-27 16:59:29` [q3:top_created_stamps]. These are bulk loads.
- **last_modified bursts:** 434 in 2018-05 and 137 in 2017-12 [q3:modified_by_month].
- **Duplicate name.** "Pizza Lovers" is two ids, which merge in any by-name grouping (local078).
- **Values.**
  - Composition p50 is 2.86, with a max of 21.2 (Work Comes First Travelers, 12-2018) [q5:composition_quantiles].
  - index_value p50 is 1.45, with a max of 6.19 [q5:index_value_quantiles].
  - composition / index_value runs 0.74–9.14 [q2:composition_over_index].

## 5. Distributions to fit (stage 2)

| Quantity | Value |
|---|---|
| interests per month | 729, 767, 780, 857, 928, 995, 973, 1,121, 1,136, 1,099, 857, 824, 864, 1,149 [q1:month_year_values] |
| new interests by first month | 729 (07-2018), then 47, 30, 77, 82, 73, 15, 109, 12, 20, 4, 0, 2, 2 [q5:first_month_of_interests] |
| months present | 14 months: 480 interests; 7–13 months: 579; ≤ 6 months: 143 [q3:months_per_interest] |
| persistence | next-month presence 97–99% except 04→05-2019 (77.6%) and 05→06-2019 (86.7%) [q5:month_to_month_persistence] |
| composition | p5 1.72, p25 2.22, p50 2.86, p75 3.87, p95 6.61, max 21.2 [q5:composition_quantiles] |
| index_value | p5 0.88, p25 1.19, p50 1.45, p75 1.78, p95 2.45, max 6.19 [q5:index_value_quantiles] |
| month-to-month drift | consecutive-month ratio: composition mean 0.983 (32% within ±10%), index mean 1.007 [q5:month_lag_corr_inputs] |
| interest creation | 34 months from 2016-05 to 2019-05, with bursts (154 on day 1; 128 in 2017-03) [q3:created_by_month] |
| modification | 709 of 1,209 (58.6%) are modified after creation [q3:created_modified_order] |

## 6. simkit mapping sketch

```python
p.entity("interests", key="interest_key", doc="interest_map; created_at is the source's own stamp",
         cols={"ext_id": i64(doc="id"), "interest_name": text(), "interest_summary": opt(text())})
p.event("interest_modified", doc="last_modified > created_at; what changed is unknown",
        cols={"interest_key": ref("interests")})
p.event("interest_metrics_reported", doc="At the first day after the month; NULL-month rows at N",
        cols={"interest_key": opt(ref("interests")), "month_year": opt(text(doc="MM-YYYY, verbatim")),
              "composition": f64(), "index_value": f64()})
```

Ingest:
- `-- entity: interests`: created_at = `created_at`, ORDER BY id.
- `-- event: interest_modified owner=interest_key`: time = last_modified, WHERE last_modified > created_at, ORDER BY id.
- `-- event: interest_metrics_reported owner=interest_key ord=rowid`:
  - time = `date(_year || '-' || printf('%02d', _month) || '-01', '+1 month')`, or `'2019-09-01'` when month_year is NULL;
  - ORDER BY that time, ranking, rowid.
  - A NULL owner needs a pack decision: give the 1,193 rows a sentinel owner, or let `opt(ref)` events be unowned.

`build.sql`:
- `interest_map`: the entity, with last_modified = `coalesce(max E1 time, created_at)`, strftime'd.
- `interest_metrics`: E2 joined to the entity (`CAST(ext_id AS DOUBLE)`), with `_month`/`_year` from month_year, plus `RANK()` and the percentile formula over `PARTITION BY month_year`.

Stage 2:
- owner = interest. Each month, each live interest reports a composition (lognormal, mean-reverting) and an index; there is a churn hazard, and arrivals follow the first-month counts.
- Rankings are computed, never generated.

## 7. Open questions and risks

- **A NULL owner on 1,193 events.** The pack must support an optional owner, or use a sentinel `unknown` partition. Whether `opt(ref)` may be the owner column is untested.
- **NULL-month rows at N** is a pure rule. Their ranking group (N = 1,194) is self-contained, so the rule is safe for the round trip. Stage 2 should model them as a "lost month label" defect, or drop them.
- **The month-close stamp** (the first of the next month) is a choice made to avoid referencing interests before their creation. If a saved query filters on event_time, it must use `month_year`, not the event time.
- **`interest_modified` carries nothing.** The stamp could instead be a snapshot column on the entity. Either rebuilds exactly; pick per the dataset-wide convention.
- **The licence of the case-study data is unstated.**

## Summary

- Round trip: **yes, exact**. ranking and percentile_ranking are proven derived (RANK by index_value per month, NULL month as one group), and _month and _year come from month_year.
- Dataset name: `freshsegments`.
- 2 event types (`interest_modified`, `interest_metrics_reported`) and 1 entity (`interests`).
- Event shape: **partly imposed**. Map stamps are natural; monthly metrics are snapshots stamped at the month's close by rule.
- Hardest blocker: 1,194 metric rows have no month (1,193 also have no interest). They need a rule time (N) and an owner-less or sentinel partition.
