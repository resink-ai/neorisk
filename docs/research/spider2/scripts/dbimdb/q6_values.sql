-- name: movie_order_vs_year
with m as (select "index" i, cast(substr(year,-4) as integer) y from Movie)
select count(*) pairs, sum(y >= p) nondecr, sum(y < p) drops from (select y, lag(y) over (order by i) p from m) where p is not null;
-- name: movie_index_head_years
select "index", MID, title, year from Movie where "index" in (0,1,2,100,500,1000,2000,3000,3474);
-- name: movies_per_decade
select (cast(substr(year,-4) as integer)/10)*10 decade, count(*) n from Movie group by 1 order by 1;
-- name: movies_per_year_recent
select cast(substr(year,-4) as integer) y, count(*) n from Movie where cast(substr(year,-4) as integer) >= 2010 group by 1 order by 1;
-- name: title_dups
select count(*) titles_with_gt1_movie, sum(c) movies from (select title, count(*) c from Movie group by title having count(*)>1);
-- name: title_year_dups
select count(*) from (select title, substr(year,-4) from Movie group by 1,2 having count(*)>1);
-- name: mid_shape
select length(MID) len, substr(MID,1,2) pfx, count(*) n from Movie group by 1,2;
-- name: rating_hist
select cast(rating as integer) r, count(*) n from Movie group by 1 order by 1;
-- name: votes_quantiles
with v as (select num_votes x, row_number() over (order by num_votes) rn, count(*) over () n from Movie)
select max(case when rn = cast(n*0.05 as int) then x end) p5, max(case when rn = cast(n*0.25 as int) then x end) p25, max(case when rn = cast(n*0.5 as int) then x end) p50,
 max(case when rn = cast(n*0.75 as int) then x end) p75, max(case when rn = cast(n*0.95 as int) then x end) p95, max(x) mx from v;
-- name: rating_vs_votes_by_year
select case when cast(substr(year,-4) as integer) < 1990 then '<1990' when cast(substr(year,-4) as integer) < 2010 then '1990-2009' else '2010+' end era, count(*) n, round(avg(rating),2) avg_rating, round(avg(num_votes)) avg_votes from Movie group by 1;
-- name: genre_combo_sizes
select (length(rtrim(Name)) - length(replace(rtrim(Name), ',', '')) + 1) genres_in_combo, count(*) combos from Genre group by 1;
-- name: movies_per_genre_combo_top
select rtrim(g.Name) combo, count(*) n from M_Genre mg join Genre g using(GID) group by 1 order by 2 desc limit 10;
-- name: null_genre_use
select g.GID, quote(g.Name), count(mg.MID) movies from Genre g left join M_Genre mg using(GID) where rtrim(g.Name) = 'Null' group by 1,2;
-- name: language_mix
select l.Name, count(*) n from M_Language m join Language l using(LAID) group by 1 order by 2 desc limit 8;
-- name: country_mix
select coalesce(c.Name, 'NULL') country, count(*) n from M_Country m left join Country c on c.CID = m.CID group by 1 order by 2 desc limit 8;
-- name: location_null_by_era
select case when cast(substr(year,-4) as integer) < 2000 then '<2000' else '2000+' end era, count(*) n, sum(l.LID is null) no_location from Movie m join M_Location l using(MID) group by 1;
-- name: location_name_shape
select (length(Name) - length(replace(Name, ',', ''))) commas, count(*) n from Location group by 1 order by 1;
-- name: cast_size_hist
select case when c <= 5 then '1-5' when c <= 10 then '6-10' when c <= 20 then '11-20' when c <= 40 then '21-40' when c <= 80 then '41-80' else '81+' end band, count(*) movies from (select MID, count(*) c from M_Cast group by MID) group by 1 order by min(c);
-- name: producers_per_movie
select c producers, count(*) movies from (select m.MID, count(p.MID) c from Movie m left join M_Producer p using(MID) group by m.MID) group by 1 order by 1 limit 20;
-- name: credits_per_actor
with a as (select trim(PID) PID, count(distinct MID) c from M_Cast where PID is not null group by 1)
select case when c=1 then '1' when c<=3 then '2-3' when c<=10 then '4-10' when c<=30 then '11-30' when c<=100 then '31-100' else '101+' end band, count(*) actors, max(c) from a group by 1 order by min(c);
-- name: top_actors
select trim(p.Name) name, count(distinct c.MID) films from M_Cast c join (select distinct PID, Name from Person where substr(Name,1,1)=' ') p on p.PID = trim(c.PID) group by p.PID order by 2 desc limit 5;
-- name: films_per_director
with d as (select PID, count(*) c from M_Director group by PID)
select c films, count(*) directors from d group by 1 order by 1 limit 15;
-- name: cast_gender_mix_rows
select quote(g.Gender) gender, count(*) credit_rows from M_Cast c left join (select distinct PID, Gender from Person where PID is not null) g on g.PID = trim(c.PID) group by 1;
-- name: person_min_year_vs_movie_count
-- persons' first-credit year (the created_at rule): distribution
with credits as (select trim(PID) PID, MID from M_Cast where PID is not null union all select trim(PID), MID from M_Producer where PID is not null union all select PID, MID from M_Director),
f as (select PID, min(cast(substr(m.year,-4) as integer)) y from credits join Movie m using(MID) group by PID)
select (y/10)*10 decade, count(*) persons from f group by 1 order by 1;
-- name: lookup_first_use_year
select 'Genre' t, min(y), max(y), count(*) from (select GID, min(cast(substr(m.year,-4) as integer)) y from M_Genre join Movie m using(MID) group by GID)
union all select 'Location', min(y), max(y), count(*) from (select LID, min(cast(substr(m.year,-4) as integer)) y from M_Location join Movie m using(MID) where LID is not null group by LID);
-- name: title_samples_nonascii
select count(*) from Movie where title glob '*[^ -~]*';
-- name: person_name_nonascii
select count(*) from Person where Name glob '*[^ -~]*';
-- name: year_prefix_vs_title_dups
select (length(year) > 4) prefixed, count(*) movies, sum(title in (select title from Movie group by title having count(*)>1)) title_shared_in_catalog from Movie group by 1;
-- name: same_title_same_tail_year
select title, group_concat(year, ' | ') years from Movie where title in (select title from Movie group by title, substr(year,-4) having count(*)>1) group by title limit 10;
