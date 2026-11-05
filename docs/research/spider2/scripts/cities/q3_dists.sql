-- name: cities_per_country_top
select country_code_2, count(*) from cities group by 1 order by 2 desc limit 10;

-- name: cities_per_country_bands
select case when n = 1 then '1' when n <= 10 then '2-10' when n <= 100 then '11-100' when n <= 1000 then '101-1000' else '1000+' end b, count(*) countries
from (select country_code_2, count(*) n from cities group by 1) group by 1;

-- name: population_quantiles
with p as (select population, row_number() over (order by population) r, count(*) over () n from cities where population is not null)
select max(case when r = cast(n*0.05 as int) then population end) p5, max(case when r = cast(n*0.25 as int) then population end) p25,
  max(case when r = cast(n*0.5 as int) then population end) p50, max(case when r = cast(n*0.75 as int) then population end) p75,
  max(case when r = cast(n*0.95 as int) then population end) p95, max(population) mx from p;

-- name: coord_decimals
select length(cast(latitude as text)) - instr(cast(latitude as text), '.') dec, count(*) from cities group by 1 order by 1;

-- name: same_day_same_country
select n, count(*) from (select country_code_2, insert_date, count(*) n from cities group by 1,2) group by 1 order by 1;

-- name: insert_day_count_moments
with d as (select insert_date, count(*) n from cities group by 1)
select count(*) days, avg(n) mean, avg(n*n) - avg(n)*avg(n) var from d;
