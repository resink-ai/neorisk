-- name: local202_detail
with s as (select state, count(*) n, avg(aggressive = 0) friendly, avg(aggressive = 1) hostile, avg(age) avg_age
           from alien_data group by 1 order by n desc limit 10)
select *, friendly > hostile and avg_age > 200 qualifies from s;

-- name: local202
with s as (select state, count(*) n, avg(aggressive = 0) friendly, avg(aggressive = 1) hostile, avg(age) avg_age
           from alien_data group by 1 order by n desc limit 10)
select count(*) qualified_states_count from s where friendly > hostile and avg_age > 200;

-- name: local202_from_base_tables
-- same answer from the three base tables (age = 2024 - birth_year)
with s as (select l.state, count(*) n, avg(d.aggressive = 0) friendly, avg(d.aggressive = 1) hostile, avg(2024 - a.birth_year) avg_age
           from aliens a join aliens_details d on d.detail_id = a.id join aliens_location l on l.loc_id = a.id
           group by 1 order by n desc limit 10)
select count(*) qualified_states_count from s where friendly > hostile and avg_age > 200;
