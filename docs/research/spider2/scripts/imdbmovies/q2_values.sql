-- name: date_published_shape
select length(date_published) len, substr(date_published, 11) time_part, count(*) n, min(date_published), max(date_published) from movies group by 1,2;
-- name: year_vs_published_year
select count(*) n, sum(year = cast(substr(date_published,1,4) as integer)) same_year, sum(year < cast(substr(date_published,1,4) as integer)) year_before, sum(year > cast(substr(date_published,1,4) as integer)) year_after from movies;
-- name: year_mismatch_samples
select id, title, year, date_published from movies where year <> cast(substr(date_published,1,4) as integer) limit 10;
-- name: movies_per_year
select year, count(*) n, min(date_published), max(date_published) from movies group by 1;
-- name: rowid_order_within_year
select count(*) pairs, sum(id > p) id_incr, sum(id < p) id_drops, sum(dp >= pdp) date_nondecr from
 (select id, date_published dp, lag(id) over (partition by year order by rowid) p, lag(date_published) over (partition by year order by rowid) pdp from movies) where p is not null;
-- name: movies_id_drops_at_year_change
select count(*) drops, sum(y <> py) at_year_change from (select id, year y, lag(id) over (order by rowid) p, lag(year) over (order by rowid) py from movies) where p is not null and id < p;
-- name: published_per_month
select substr(date_published,1,7) ym, count(*) n from movies group by 1 order by 1;
-- name: published_weekday
select strftime('%w', date_published) dow, count(*) n from movies group by 1 order by 1;
-- name: published_day1
select sum(substr(date_published,9,2)='01') day1, count(*) n from movies;
-- name: gross_prefixes
select substr(worlwide_gross_income, 1, instr(worlwide_gross_income, ' ')) prefix, count(*) n from movies where worlwide_gross_income is not null group by 1;
-- name: gross_digits_only
select count(*) n, sum(substr(worlwide_gross_income, instr(worlwide_gross_income,' ')+1) glob '*[^0-9]*') nondigit, sum(substr(worlwide_gross_income, instr(worlwide_gross_income,' ')+1) glob '0*') leading_zero,
 min(cast(substr(worlwide_gross_income, instr(worlwide_gross_income,' ')+1) as integer)) mn, max(cast(substr(worlwide_gross_income, instr(worlwide_gross_income,' ')+1) as integer)) mx from movies where worlwide_gross_income is not null;
-- name: gross_samples
select worlwide_gross_income from movies where worlwide_gross_income not like '$ %' limit 5;
-- name: duration_stats
select min(duration), max(duration), avg(duration), sum(duration < 60) under_60, sum(duration > 240) over_240 from movies;
-- name: country_multi
select (length(country) - length(replace(country, ',', ''))) commas, count(*) n from movies group by 1;
-- name: country_top
select country, count(*) n from movies group by 1 order by 2 desc limit 10;
-- name: languages_multi
select (length(languages) - length(replace(languages, ',', ''))) commas, count(*) from movies group by 1;
-- name: list_separator_shape
-- are multi-valued lists always ', ' separated with no padding?
select 'country' c, sum(country like '%,%' and country like '%, %') comma_space, sum(country like '%,[^ ]%') , sum(country <> trim(country)) padded from movies
union all select 'languages', sum(languages like '%, %'), 0, sum(languages <> trim(languages)) from movies
union all select 'production_company', sum(production_company like '%,%'), 0, sum(production_company <> trim(production_company)) from movies;
-- name: comma_no_space
select 'country' c, sum(replace(country, ', ', '') like '%,%') from movies union all select 'languages', sum(replace(languages, ', ', '') like '%,%') from movies;
-- name: genre_values
select genre, count(*) n from genre group by 1 order by 2 desc;
-- name: genres_per_movie
select c, count(*) movies from (select movie_id, count(*) c from genre group by 1) group by 1;
-- name: category_values
select category, count(*) from role_mapping group by 1;
-- name: roles_per_movie
select c, count(*) movies from (select movie_id, count(*) c from role_mapping group by 1) group by 1 order by 1;
-- name: directors_per_movie
select c, count(*) movies from (select movie_id, count(*) c from director_mapping group by 1) group by 1 order by 1;
-- name: role_order_within_movie
-- within a movie: actor before actress? or by name_id?
select count(*) pairs, sum(name_id > p) by_name_id, sum(category >= pc) by_category from (select movie_id, name_id, category, lag(name_id) over (partition by movie_id order by rowid) p, lag(category) over (partition by movie_id order by rowid) pc from role_mapping) where p is not null;
-- name: role_sorted_by_cat_then_id
select count(*) pairs, sum(category > pc or (category = pc and name_id > p)) sorted_cat_id from (select movie_id, name_id, category, lag(name_id) over (partition by movie_id order by rowid) p, lag(category) over (partition by movie_id order by rowid) pc from role_mapping) where p is not null;
-- name: director_order_within_movie
select count(*) pairs, sum(name_id > p) by_name_id from (select movie_id, name_id, lag(name_id) over (partition by movie_id order by rowid) p from director_mapping) where p is not null;
-- name: genre_order_within_movie
select count(*) pairs, sum(genre > p) alpha from (select genre, lag(genre) over (partition by movie_id order by rowid) p from genre) where p is not null;
-- name: height_stats
select min(height), max(height), sum(height <> cast(height as integer)) fractional, count(height) n from names;
-- name: dob_shape
select length(date_of_birth) len, count(*) n, min(date_of_birth), max(date_of_birth) from names group by 1;
-- name: dob_after_2019
select count(*) from names where date_of_birth > '2019-12-31';
-- name: names_rowid_order
select count(*) drops from (select id, lag(id) over (order by rowid) p from names) where id < p;
-- name: ratings_shapes
select min(avg_rating), max(avg_rating), sum(avg_rating*10 <> cast(round(avg_rating*10) as integer)) non_tenths, sum(median_rating <> cast(median_rating as integer)) frac_median,
  min(median_rating), max(median_rating), min(total_votes), max(total_votes) from ratings;
-- name: avg_vs_median
select sum(abs(avg_rating - median_rating) <= 1) within1, sum(avg_rating > median_rating) avg_gt, sum(avg_rating < median_rating) avg_lt, count(*) from ratings;
-- name: votes_quantiles
with v as (select total_votes x, row_number() over (order by total_votes) rn, count(*) over () n from ratings)
select max(case when rn = cast(n*0.05 as int) then x end) p5, max(case when rn = cast(n*0.25 as int) then x end) p25, max(case when rn = cast(n*0.5 as int) then x end) p50,
 max(case when rn = cast(n*0.75 as int) then x end) p75, max(case when rn = cast(n*0.95 as int) then x end) p95, max(x) mx from v;
-- name: median_hist
select median_rating, count(*) from ratings group by 1 order by 1;
-- name: votes_by_year
select m.year, count(*), round(avg(r.total_votes)) avg_votes, round(avg(r.avg_rating),2) avg_r from movies m join ratings r on r.movie_id = m.id group by 1;
-- name: title_dups
select count(*) titles, sum(c) movies from (select title, count(*) c from movies group by 1 having count(*)>1);
-- name: whitespace
select sum(title <> trim(title)) title_pad, (select sum(name <> trim(name)) from names) name_pad, (select sum(genre <> trim(genre)) from genre) genre_pad from movies;
-- name: nonascii
select (select count(*) from movies where title glob '*[^ -~]*') titles, (select count(*) from names where name glob '*[^ -~]*') names;
-- name: production_company_count
select count(distinct production_company) companies, count(production_company) movies from movies;
