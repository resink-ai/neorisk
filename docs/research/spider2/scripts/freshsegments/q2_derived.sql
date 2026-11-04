-- Are ranking / percentile_ranking / _month / _year functions of other columns?  Where do NULL-month rows belong?
-- name: create_ranked
create temp table ranked as
select rowid rid, *, rank() over (partition by month_year order by index_value desc) rk,
       count(*) over (partition by month_year) n_in_month
from interest_metrics;
-- name: ranking_is_rank_by_index_value
select coalesce(month_year, 'NULL') my, count(*) n, sum(ranking = rk) ranking_eq_rank, max(n_in_month) n_month,
       sum(percentile_ranking = round(100.0 * (1 - 1.0 * ranking / n_in_month), 2)) pct_eq_round2,
       sum(abs(percentile_ranking - 100.0 * (1 - 1.0 * ranking / n_in_month)) <= 0.005 + 1e-9) pct_within_half_cent
from ranked group by 1 order by min(rid);
-- name: percentile_mismatch_sample
select month_year, ranking, n_in_month, percentile_ranking, printf('%.6f', 100.0 * (1 - 1.0 * ranking / n_in_month)) exact
from ranked where month_year is not null and percentile_ranking <> round(100.0 * (1 - 1.0 * ranking / n_in_month), 2) limit 15;
-- name: create_neighbours
-- for each NULL-month row: month of nearest non-NULL row before and after it in rowid order
create temp table nb as
select r.rid, r.interest_id, r.ranking, r.index_value, r.percentile_ranking,
  (select month_year from interest_metrics p where p.rowid < r.rid and p.month_year is not null order by p.rowid desc limit 1) prev_my,
  (select month_year from interest_metrics p where p.rowid > r.rid and p.month_year is not null order by p.rowid limit 1) next_my,
  (select ranking from interest_metrics p where p.rowid < r.rid and p.month_year is not null order by p.rowid desc limit 1) prev_rank,
  (select ranking from interest_metrics p where p.rowid > r.rid and p.month_year is not null order by p.rowid limit 1) next_rank
from ranked r where r.month_year is null;
-- name: null_rows_by_neighbour
select case when prev_my = next_my then 'between same month' when next_my is null then 'trailing block' else 'between months' end pos,
       count(*) n, min(rid), max(rid) from nb group by 1;
-- name: null_rows_rank_fit
-- interleaved NULL rows: does their ranking sit between the neighbours' rankings (sorted-by-rank file)?
select count(*) n, sum(ranking between prev_rank and coalesce(next_rank, 1e9)) fits_between from nb where prev_my = next_my;
-- name: trailing_block
select count(*) n, min(rid), max(rid), min(ranking), max(ranking), count(distinct ranking) distinct_ranks,
       sum(interest_id is not null) with_id from nb where next_my is null;
-- name: null_rows_percentile_vs_month_size
-- percentile_ranking = 100*(1 - ranking/N): solve N per NULL row
select count(*) n, min(round(ranking / (1 - percentile_ranking / 100.0))) n_min, max(round(ranking / (1 - percentile_ranking / 100.0))) n_max
from nb where percentile_ranking < 100;
-- name: interleaved_implied_month_size
select prev_my, count(*) n, min(ranking), max(ranking), round(avg(ranking / (1 - percentile_ranking / 100.0)), 1) implied_N from nb where prev_my = next_my group by 1;
-- name: trailing_ranked_among_themselves
-- is the trailing block ranked by index_value within itself (a 15th month)?
select count(*) n, sum(ranking = rk2) eq from (select ranking, rank() over (order by index_value desc) rk2 from nb where next_my is null);
-- name: all_null_rows_ranked_together
select count(*) n, sum(ranking = rk2) eq, (select count(*) from nb) n_null from (select ranking, rank() over (order by index_value desc) rk2 from nb);
-- name: id_present_null_month_row
select rid, interest_id, ranking, index_value, composition from ranked where month_year is null and interest_id is not null;
-- name: composition_over_index
select count(*) n, min(composition / index_value), max(composition / index_value), round(avg(composition / index_value), 3) mean from interest_metrics;
-- name: value_grid
select count(*) n, sum(composition = round(composition, 2)) comp_2dp, sum(index_value = round(index_value, 2)) idx_2dp, sum(percentile_ranking = round(percentile_ranking, 2)) pct_2dp,
       min(composition), max(composition), min(index_value), max(index_value) from interest_metrics;
