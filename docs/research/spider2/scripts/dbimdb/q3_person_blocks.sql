-- name: person_space_runs
-- consecutive runs of Person rows by leading-space-in-Name (NULL row is its own run)
with r as (select "index" i, coalesce(substr(Name,1,1)=' ', -1) sp from Person),
g as (select i, sp, i - row_number() over (partition by sp order by i) grp from r)
select min(i) first_index, max(i) last_index, count(*) n, sp lead_space from g group by sp, grp order by min(i);
-- name: block_membership
-- which credit tables each Person row's PID appears in, by block
with b as (select "index" i, PID, case when "index" < 30439 then 'A_0_30438' when "index" = 30439 then 'NULLROW' when substr(Name,1,1)=' ' then 'B_lead_space' else 'C_no_space' end blk from Person)
select blk, count(*) n, min(i), max(i),
  sum(PID in (select trim(PID) from M_Cast where PID is not null)) in_cast,
  sum(PID in (select trim(PID) from M_Producer where PID is not null)) in_producer,
  sum(PID in (select PID from M_Director)) in_director
from b group by blk order by min(i);
-- name: block_dup_pairs
with b as (select "index" i, PID, case when "index" < 30439 then 'A' when substr(Name,1,1)=' ' then 'B' else 'C' end blk from Person where PID is not null),
d as (select PID, min(blk) b1, max(blk) b2 from b where PID in (select PID from Person group by PID having count(*)>1) group by PID)
select b1||b2 pair, count(*) n from d group by 1;
-- name: unique_within_blocks
with b as (select "index" i, PID, case when "index" < 30439 then 'A' when substr(Name,1,1)=' ' then 'B' else 'C' end blk from Person where PID is not null)
select blk, count(*) n, count(distinct PID) d from b group by blk;
-- name: gender_by_block
with b as (select Gender, case when "index" < 30439 then 'A' when "index"=30439 then 'N' when substr(Name,1,1)=' ' then 'B' else 'C' end blk from Person)
select blk, quote(Gender) g, count(*) from b group by 1,2 order by 1,2;
-- name: cast_gender_coverage
-- gender of distinct cast people (via first Person row with that PID)
with c as (select distinct trim(PID) PID from M_Cast where PID is not null),
g as (select PID, max(Gender) Gender from Person where PID is not null group by PID)
select quote(g.Gender) gender, count(*) from c join g using(PID) group by 1;
-- name: block_A_order_vs_cast_first_seen
-- is block A exactly the distinct cast PIDs in first-seen order of M_Cast rows?
with fs as (select trim(PID) PID, min("index") f from M_Cast where PID is not null group by trim(PID)),
fsr as (select PID, row_number() over (order by f) - 1 rk from fs),
a as (select "index" i, PID from Person where "index" < 30439)
select (select count(*) from fsr) cast_distinct, (select count(*) from a) block_a, sum(a.i = fsr.rk) same_position from a join fsr using(PID);
-- name: block_B_order_vs_producer_first_seen
with fs as (select trim(PID) PID, min("index") f from M_Producer where PID is not null group by trim(PID)),
fsr as (select PID, row_number() over (order by f) + 30439 rk from fs),
b as (select "index" i, PID from Person where "index" > 30439 and substr(Name,1,1)=' ')
select (select count(*) from fsr) prod_distinct, (select count(*) from b) block_b, sum(b.i = fsr.rk) same_position from b join fsr using(PID);
-- name: block_C_order_vs_director_first_seen
with fs as (select PID, min("index") f from M_Director group by PID),
fsr as (select PID, row_number() over (order by f) rk from fs),
c as (select "index" i, PID, row_number() over (order by "index") r from Person where "index" > 30439 and substr(Name,1,1)<>' ')
select (select count(*) from fsr) dir_distinct, (select count(*) from c) block_c, sum(c.r = fsr.rk) same_position, min(c.i), max(c.i) from c join fsr using(PID);
