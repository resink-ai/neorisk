-- currency as a pure function of countries x {2019,2020,2021} x {1..12}
-- name: rule_vs_table
with g as (
  select substr(k.country_name, 1, 20) country, y.y year, m.m month, case when k.country_name = 'Canada' then 0.74 else 1.0 end to_us
  from countries k,
       (select 2019 y union all select 2020 union all select 2021) y,
       (with recursive r(m) as (select 1 union all select m + 1 from r where m < 12) select m from r) m)
select (select count(*) from g) n_rule, (select count(*) from currency) n_table,
       (select count(*) from (select * from g except select * from currency)) rule_minus_table,
       (select count(*) from (select * from currency except select * from g)) table_minus_rule;
-- name: rowid_order_groups
-- order of countries in the table vs countries.country_id
select country, min(rowid) first_rowid, max(rowid) last_rowid from currency group by country order by first_rowid limit 8;
-- name: rowid_country_contiguous
select count(*) n_countries, sum(max_r - min_r + 1 = n) contiguous from (select country, min(rowid) min_r, max(rowid) max_r, count(*) n from currency group by country);
-- name: country_order_vs_id
select c.country, k.country_id, c.first_rowid from (select country, min(rowid) first_rowid from currency group by country) c
  left join countries k on substr(k.country_name, 1, 20) = c.country order by c.first_rowid;
