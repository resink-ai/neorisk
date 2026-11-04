-- name: setup_indexes
create index ic on cities(country_code_2); create index icc on cities_countries(country_code_2);
create index icu on cities_currencies(country_code_2); create index il on cities_languages(country_code_2);

-- name: key_uniqueness
select 'cities.city_id' k, count(*) n, count(distinct city_id) d from cities
union all select 'countries.country_id', count(*), count(distinct country_id) from cities_countries
union all select 'countries.country_code_2', count(*), count(distinct country_code_2) from cities_countries
union all select 'countries.country_code_3', count(*), count(distinct country_code_3) from cities_countries
union all select 'countries.country_name', count(*), count(distinct country_name) from cities_countries
union all select 'currencies.currency_id', count(*), count(distinct currency_id) from cities_currencies
union all select 'currencies.(cc2,code)', count(*), count(distinct country_code_2||'|'||coalesce(currency_code,'?')) from cities_currencies
union all select 'languages.language_id', count(*), count(distinct language_id) from cities_languages
union all select 'languages.(language,cc2)', count(*), count(distinct language||'|'||country_code_2) from cities_languages;

-- name: rowid_is_id
select (select sum(rowid = city_id) from cities) cities, (select count(*) from cities) n,
  (select sum(rowid = currency_id) from cities_currencies) cur, (select sum(rowid = language_id) from cities_languages) lang;

-- name: country_id_gaps
-- countries ids run 1..256 with 15 gaps (deduplicated rows removed; the 257th was dropped too)
select max(country_id) mx, count(*) n, max(country_id) - count(*) gaps from cities_countries;

-- name: fk_coverage
select 'cities -> countries' j, count(*) n, sum(exists (select 1 from cities_countries c where c.country_code_2 = x.country_code_2)) found from cities x
union all select 'currencies -> countries', count(*), sum(exists (select 1 from cities_countries c where c.country_code_2 = x.country_code_2)) from cities_currencies x
union all select 'languages -> countries', count(*), sum(exists (select 1 from cities_countries c where c.country_code_2 = x.country_code_2)) from cities_languages x;

-- name: fk_orphans_list
select 'cities' t, country_code_2, count(*) from cities x where not exists (select 1 from cities_countries c where c.country_code_2 = x.country_code_2) group by 2
union all select 'currencies', country_code_2, count(*) from cities_currencies x where not exists (select 1 from cities_countries c where c.country_code_2 = x.country_code_2) group by 2
union all select 'languages', country_code_2, count(*) from cities_languages x where not exists (select 1 from cities_countries c where c.country_code_2 = x.country_code_2) group by 2;

-- name: countries_without_cities
select count(*) from cities_countries c where not exists (select 1 from cities x where x.country_code_2 = c.country_code_2);

-- name: lat_long_swapped
-- latitude holds longitudes and vice versa (Shaker's normalize swap)
select sum(abs(latitude) > 90) lat_out_of_range, sum(abs(longitude) > 90) lon_out_of_range, min(longitude), max(longitude), count(*) from cities;

-- name: tokyo
select * from cities where city_id = 1;

-- name: duplicate_cities
select count(*) dup_groups, sum(n) rows_in_groups from (select city_name, country_code_2, count(*) n from cities group by 1,2 having n > 1);

-- name: exact_duplicate_rows_ignoring_id
select count(*) - (select count(*) from (select distinct city_name, latitude, longitude, country_code_2, capital, population, insert_date from cities)) from cities;

-- name: same_place_twice
select count(*) from (select city_name, latitude, longitude, country_code_2 from cities group by 1,2,3,4 having count(*) > 1);

-- name: capitals_per_country
select n, count(*) countries from (select country_code_2, sum(capital) n from cities group by 1) group by 1 order by 1;

-- name: population_zero_null
select sum(population is null) nulls, sum(population = 0) zeros, sum(population <> cast(population as int)) non_integral, max(population) from cities;

-- name: population_rank_order
-- the file is sorted by population descending (simplemaps order), NULLs last?
with p as (select city_id, population, lag(population) over (order by city_id) pp from cities)
select sum(population <= pp) nonincreasing, sum(population > pp) increases, count(pp) pairs,
  (select min(city_id) from cities where population is null) first_null_id from p;

-- name: city_name_null
select * from cities where city_name is null;

-- name: name_chars
-- non-ascii survives the cleaning (\w is Unicode); punctuation such as ' and - is removed
select sum(city_name glob '*[^ -~]*') non_ascii, sum(city_name like '%-%') hyphen, sum(city_name like '%''%') apostrophe, sum(city_name like '%.%') dot from cities;

-- name: insert_date_format
select sum(insert_date glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]') iso, sum(date(insert_date) = insert_date) valid, min(insert_date), max(insert_date), count(distinct insert_date) days,
  cast(julianday(max(insert_date)) - julianday(min(insert_date)) as int) + 1 span_days from cities;

-- name: insert_per_month
select substr(insert_date,1,7) m, count(*) from cities group by 1 order by 1;

-- name: insert_per_day_dist
select n, count(*) days from (select insert_date, count(*) n from cities group by 1) group by 1 order by 1;

-- name: insert_vs_population_independence
select case when city_id <= 1000 then 'top 1000 by population' when city_id <= 10000 then '1001-10000' else 'rest' end band,
  round(avg(julianday(insert_date) - julianday('2021-01-01')), 1) mean_day, count(*) from cities group by 1;

-- name: insert_weekday
select strftime('%w', insert_date) dow, count(*) from cities group by 1 order by 1;

-- name: capital_insert
select capital, round(avg(julianday(insert_date) - julianday('2021-01-01')), 1) mean_day, count(*) from cities group by 1;

-- name: created_on
select created_on, count(*) from cities_countries group by 1;

-- name: region_mix
select region, count(*) from cities_countries group by 1 order by 2 desc;

-- name: currencies_per_country
select n, count(*) from (select country_code_2, count(*) n from cities_currencies group by 1) group by 1;

-- name: languages_per_country
select n, count(*) from (select country_code_2, count(*) n from cities_languages group by 1) group by 1 order by 1;

-- name: null_currency_code
select * from cities_currencies where currency_code is null;

-- name: null_sub_region
select * from cities_countries where sub_region is null;

-- name: population_order_head
with p as (select city_id, population, lag(population) over (order by city_id) pp from cities)
select sum(population > pp) increases_before_id_898, sum(pp is not null) pairs_before_898 from p where city_id < 898;
