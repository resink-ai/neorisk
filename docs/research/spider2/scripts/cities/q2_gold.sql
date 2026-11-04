-- Reproduce the gold CSVs in scripts/cities/gold/. Streaks = runs of consecutive insert_date days (gaps-and-islands).

-- name: local068
with m as (select cast(strftime('%Y', insert_date) as int) y, cast(strftime('%m', insert_date) as int) mo, count(*) n
           from cities where strftime('%Y', insert_date) between '2021' and '2023' and strftime('%m', insert_date) in ('04','05','06') group by 1,2),
r as (select y, mo, n, sum(n) over (partition by mo order by y) rt from m),
g as (select y, mo, n, rt, lag(n) over (partition by mo order by y) pn, lag(rt) over (partition by mo order by y) prt from r)
select y year, mo month, n monthly_total, rt running_total, round(100.0*(n - pn)/pn, 6) monthly_yoy, round(100.0*(rt - prt)/prt, 6) running_yoy
from g where y in (2022, 2023) order by y, mo;

-- name: local070_streaks
-- Chinese cities, July 2021: islands of consecutive insert days
with d as (select distinct insert_date dt from cities where country_code_2 = 'cn' and insert_date between '2021-07-01' and '2021-07-31'),
i as (select dt, julianday(dt) - row_number() over (order by dt) grp from d)
select min(dt) start, max(dt) stop, count(*) len from i group by grp order by start;

-- name: local070_cities_per_day
-- how many cn cities share each streak date (the gold picks one per date; _a and _b pick differently)
select insert_date, count(*) n, min(city_id) min_id, group_concat(city_name, ' | ') names from cities
where country_code_2 = 'cn' and insert_date in ('2021-07-12','2021-07-13','2021-07-19','2021-07-23','2021-07-27','2021-07-29','2021-07-30')
group by 1 order by 1;

-- name: local070_pick_min_id
-- one city per date by lowest city_id, for the shortest (2) and longest (13) streaks
with d as (select distinct insert_date dt from cities where country_code_2 = 'cn' and insert_date between '2021-07-01' and '2021-07-31'),
i as (select dt, julianday(dt) - row_number() over (order by dt) grp from d),
s as (select grp, count(*) len from i group by grp),
pick as (select i.dt from i join s using(grp) where s.len in ((select min(len) from s), (select max(len) from s)))
select p.dt, (select upper(substr(city_name,1,1)) || substr(city_name,2) from cities c where c.country_code_2='cn' and c.insert_date=p.dt order by city_id limit 1) first_by_id,
  (select upper(substr(city_name,1,1)) || substr(city_name,2) from cities c where c.country_code_2='cn' and c.insert_date=p.dt order by city_id desc limit 1) last_by_id
from pick p order by 1;

-- name: local071
-- June 2022: countries whose longest streak of consecutive insert days is the overall maximum
with d as (select distinct country_code_2 cc, insert_date dt from cities where insert_date between '2022-06-01' and '2022-06-30'),
i as (select cc, dt, julianday(dt) - row_number() over (partition by cc order by dt) grp from d),
s as (select cc, count(*) len from i group by cc, grp),
b as (select cc, max(len) best from s group by cc)
select cc, best from b where best = (select max(best) from b) order by cc;

-- name: local072
-- the country with exactly 9 distinct insert days in January 2022; its longest streak; capital share of rows in it
with j as (select * from cities where insert_date between '2022-01-01' and '2022-01-31'),
c as (select country_code_2 cc from j group by 1 having count(distinct insert_date) = 9),
d as (select distinct j.country_code_2 cc, insert_date dt from j join c on c.cc = j.country_code_2),
i as (select cc, dt, julianday(dt) - row_number() over (partition by cc order by dt) grp from d),
s as (select cc, grp, min(dt) st, max(dt) en, count(*) len from i group by cc, grp),
best as (select * from s order by len desc, st limit 1)
select best.cc, best.st, best.en, best.len, count(*) rows_in_period, sum(j.capital) capital_rows, 100.0*sum(j.capital)/count(*) pct
from best join j on j.country_code_2 = best.cc and j.insert_date between best.st and best.en;

-- name: local072_candidates
select country_code_2, count(distinct insert_date) days from cities where insert_date between '2022-01-01' and '2022-01-31' group by 1 having days = 9;
