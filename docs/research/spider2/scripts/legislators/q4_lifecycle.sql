-- name: snapshot_N
-- latest date that is not a scheduled future end: max(term_start) and max term_end among terms that are not open
select max(term_start) last_start,
  (select max(term_end) from legislators_terms where term_end <= '2020-06-30') last_past_end,
  (select count(*) from legislators_terms where term_end > '2020-05-22') ends_after_N,
  (select count(*) from legislators_terms where term_end > '2020-05-22' and term_start <= '2020-05-22') open_at_N,
  (select count(distinct id_bioguide) from legislators_terms where term_end > '2020-05-22') people_open_at_N
from legislators_terms;

-- name: ends_in_2020_by_day
select term_end, count(*) from legislators_terms where term_end between '2020-01-01' and '2020-12-31' group by 1 order by 1;

-- name: open_terms_end_dates
select term_type, term_end, count(*) from legislators_terms where term_end > '2020-05-22' group by 1,2 order by 2;

-- name: current_block_is_open
-- legislators rowid 1..539 are exactly the people with a term open at N
with o as (select distinct id_bioguide from legislators_terms where term_end > '2020-05-22')
select sum(l.rowid <= 539 and o.id_bioguide is not null) cur_open, sum(l.rowid <= 539 and o.id_bioguide is null) cur_not_open,
       sum(l.rowid > 539 and o.id_bioguide is not null) hist_open
from legislators l left join o using(id_bioguide);

-- name: end_regularity
-- a term end is "regular" if it falls on a statutory congress boundary: 03-03 / 03-04 (before 1935) or 01-03 (1935+)
select term_type,
  sum(substr(term_end,6) in ('03-03','03-04') and term_end < '1935') reg_march,
  sum(substr(term_end,6) = '01-03' and term_end >= '1935') reg_jan,
  sum(not ((substr(term_end,6) in ('03-03','03-04') and term_end < '1935') or (substr(term_end,6) = '01-03' and term_end >= '1935'))) irregular,
  count(*) n
from legislators_terms group by 1;

-- name: start_regularity
select term_type, sum(substr(term_start,6) in ('03-04','01-03','01-05','01-06','01-07','01-04')) on_congress_open, count(*) n,
  count(distinct term_start) distinct_starts from legislators_terms group by 1;

-- name: starts_per_date_top
select term_start, count(*) from legislators_terms group by 1 order by 2 desc limit 10;

-- name: terms_per_legislator
select n_terms, count(*) people from (select count(*) n_terms from legislators_terms group by id_bioguide) group by 1 order by 1;

-- name: type_switch
-- people who served both rep and sen; first type
select sum(types = 2) both_chambers, count(*) people,
  sum(first_type = 'rep') first_rep, sum(first_type = 'sen') first_sen
from (select id_bioguide, count(distinct term_type) types,
  (select term_type from legislators_terms t2 where t2.id_bioguide = t.id_bioguide and term_number = 0) first_type
  from legislators_terms t group by 1);

-- name: gaps_between_terms
with g as (select julianday(term_start) - julianday(lag(term_end) over (partition by id_bioguide order by term_number)) gap from legislators_terms)
select case when gap is null then 'first' when gap <= 0 then '0 (contiguous)' when gap <= 7 then '1-7d' when gap <= 400 then '8-400d'
  when gap <= 3650 then '1-10y' else '10y+' end b, count(*) from g group by 1 order by 1;

-- name: party_changes
with p as (select id_bioguide, party, lag(party) over (partition by id_bioguide order by term_number) pp from legislators_terms)
select sum(pp is not null and party is not pp) party_changed, sum(pp is not null) continuing_terms from p;

-- name: state_changes
with p as (select id_bioguide, state, lag(state) over (partition by id_bioguide order by term_number) ps from legislators_terms)
select sum(ps is not null and state <> ps) state_changed from p;

-- name: first_starts_by_decade
select substr(fs,1,3)||'0s' decade, count(*) from (select min(term_start) fs from legislators_terms group by id_bioguide) group by 1 order by 1;

-- name: female_share_by_first_decade
select substr(fs,1,3)||'0s' decade, sum(gender='F') f, count(*) n from
  (select id_bioguide, min(term_start) fs from legislators_terms group by 1) join legislators using(id_bioguide)
group by 1 having f > 0 order by 1;

-- name: null_birthday_by_era
select substr(fs,1,2)||'00s' c, sum(birthday is null) null_bday, count(*) n from
  (select id_bioguide, min(term_start) fs from legislators_terms group by 1) join legislators using(id_bioguide) group by 1;

-- name: party_null_by_era
select substr(term_start,1,2)||'00s' c, sum(party is null) null_party, count(*) n from legislators_terms group by 1;

-- name: born_after_first_term
with f as (select id_bioguide, min(term_start) fs from legislators_terms group by 1)
select l.id_bioguide, full_name, birthday, fs from legislators l join f using(id_bioguide) where birthday >= fs;

-- name: previous_bioguide
select id_bioguide, id_bioguide_previous_0, full_name from legislators where id_bioguide_previous_0 is not null;

-- name: other_names
select id_bioguide, full_name, other_names_end, other_names_last from legislators where other_names_end is not null or other_names_last is not null;

-- name: terms_rowid_sort
-- is terms rowid order = order by (term_number, legislators.rowid)?
with a as (select t.rowid tr, t.term_number tn, l.rowid lr from legislators_terms t join legislators l using(id_bioguide)),
b as (select tr, row_number() over (order by tn, lr) rk from a)
select sum(tr = rk) aligned, count(*) n from b;

-- name: age_at_first_term
with f as (select id_bioguide, min(term_start) fs from legislators_terms group by 1)
select (cast((julianday(fs)-julianday(birthday))/365.25 as int)/10)*10 age_band, count(*) from legislators join f using(id_bioguide)
where birthday is not null group by 1 order by 1;

-- name: last_past_end_who
select l.id_bioguide, l.full_name, t.term_type, t.term_start, t.term_end from legislators_terms t join legislators l using(id_bioguide) where t.term_end = '2020-05-22';
