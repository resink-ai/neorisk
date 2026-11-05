-- Reproduce the Spider2 gold CSVs (scripts/legislators/gold/). Tanimura chapter-4 method:
-- a legislator is "retained" in year Y if some term covers Y-12-31; period = Y - year(first term_start).

-- name: local169_with_date_dim
-- cohort: first term_start in 1917..1999; Dec-31 dates taken from legislation_date_dim (1917..1999 only)
with f as (select id_bioguide, min(term_start) fs from legislators_terms group by 1),
c as (select * from f where fs between '1917-01-01' and '1999-12-31'),
r as (select c.id_bioguide, cast(strftime('%Y', d.date) as int) - cast(strftime('%Y', c.fs) as int) period
      from c join legislators_terms t using(id_bioguide)
      join legislation_date_dim d on d.date between t.term_start and t.term_end and d.month_name='December' and d.day_of_month=31),
p(n) as (select 1 union all select n+1 from p where n < 20)
select p.n period, (select count(*) from c) cohort, count(distinct r.id_bioguide) retained,
       round(100.0*count(distinct r.id_bioguide)/(select count(*) from c), 2) pct
from p left join r on r.period = p.n group by p.n order by p.n;

-- name: local169_all_dec31
-- same, but every Dec 31 (not limited to the dim's 1917..1999 range)
with f as (select id_bioguide, min(term_start) fs from legislators_terms group by 1),
c as (select * from f where fs between '1917-01-01' and '1999-12-31'),
y(n) as (select 1 union all select n+1 from y where n < 20),
r as (select distinct c.id_bioguide, y.n period from c cross join y join legislators_terms t using(id_bioguide)
      where (cast(strftime('%Y', c.fs) as int) + y.n) || '-12-31' between t.term_start and t.term_end)
select y.n period, (select count(*) from c) cohort, count(r.id_bioguide) retained,
       round(100.0*count(r.id_bioguide)/(select count(*) from c), 2) pct
from y left join r on r.period = y.n group by y.n order by y.n;

-- name: local167
-- female legislators, state of first term; count those with any term covering a Dec 31 (any year)
with f as (select t.id_bioguide, t.state from legislators_terms t join legislators l using(id_bioguide)
           where l.gender='F' and t.term_number = 0),
cov as (select distinct t.id_bioguide from legislators_terms t join legislators l using(id_bioguide)
        where l.gender='F' and (cast(strftime('%Y', t.term_end) as int) > cast(strftime('%Y', t.term_start) as int)
                                or substr(t.term_end, 6) = '12-31'))
select f.state, count(*) n from f join cov using(id_bioguide) group by 1 order by 2 desc limit 3;

-- name: local167_with_date_dim
with f as (select t.id_bioguide, t.state from legislators_terms t join legislators l using(id_bioguide)
           where l.gender='F' and t.term_number = 0),
cov as (select distinct t.id_bioguide from legislators_terms t join legislators l using(id_bioguide)
        join legislation_date_dim d on d.date between t.term_start and t.term_end and d.month_name='December' and d.day_of_month=31
        where l.gender='F')
select f.state, count(*) n from f join cov using(id_bioguide) group by 1 order by 2 desc limit 3;

-- name: local171
-- male, Louisiana (state of first term), distinct legislators serving on Dec 31 of year fs+k, 30<k<50
with f as (select t.id_bioguide, min(t.term_start) fs from legislators_terms t join legislators l using(id_bioguide)
           where l.gender='M' group by 1),
la as (select f.* from f join legislators_terms t on t.id_bioguide=f.id_bioguide and t.term_number=0 where t.state='LA'),
y(n) as (select 31 union all select n+1 from y where n < 49),
r as (select distinct la.id_bioguide, y.n from la cross join y join legislators_terms t using(id_bioguide)
      where (cast(strftime('%Y', la.fs) as int) + y.n) || '-12-31' between t.term_start and t.term_end)
select y.n years, count(r.id_bioguide) active from y left join r using(n) group by y.n order by y.n;

-- name: local171_state_any_term
-- variant: LA terms only (state of the term itself)
with f as (select t.id_bioguide, min(t.term_start) fs from legislators_terms t join legislators l using(id_bioguide)
           where l.gender='M' group by 1),
y(n) as (select 31 union all select n+1 from y where n < 49),
r as (select distinct f.id_bioguide, y.n from f cross join y join legislators_terms t using(id_bioguide)
      where t.state='LA' and (cast(strftime('%Y', f.fs) as int) + y.n) || '-12-31' between t.term_start and t.term_end)
select y.n years, count(r.id_bioguide) active from y left join r using(n) group by y.n order by y.n;

-- name: local170
-- states where both genders have retention > 0 at periods 0,2,4,6,8,10 (state of first term, all Dec 31s)
with f as (select t.id_bioguide, l.gender, t.term_start fs, t.state from legislators_terms t join legislators l using(id_bioguide) where t.term_number=0),
y(n) as (select 0 union all select n+2 from y where n < 10),
r as (select distinct f.state, f.gender, y.n, f.id_bioguide from f cross join y join legislators_terms t using(id_bioguide)
      where (cast(strftime('%Y', f.fs) as int) + y.n) || '-12-31' between t.term_start and t.term_end),
ok as (select state, gender from r group by 1,2 having count(distinct n) = 6)
select group_concat(state) states, count(*) n from (select state from ok group by state having count(*) = 2 order by state);

-- name: local170_with_date_dim
with f as (select t.id_bioguide, l.gender, t.term_start fs, t.state from legislators_terms t join legislators l using(id_bioguide) where t.term_number=0),
r as (select distinct f.state, f.gender, cast(strftime('%Y', d.date) as int) - cast(strftime('%Y', f.fs) as int) n
      from f join legislators_terms t using(id_bioguide)
      join legislation_date_dim d on d.date between t.term_start and t.term_end and d.month_name='December' and d.day_of_month=31),
ok as (select state, gender from r where n in (0,2,4,6,8,10) group by 1,2 having count(distinct n) = 6)
select group_concat(state) states, count(*) n from (select state from ok group by state having count(*) = 2 order by state);
