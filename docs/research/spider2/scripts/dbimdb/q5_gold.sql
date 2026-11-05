-- Reproductions of Spider2 gold answers.
-- name: local097_decade
with y as (select cast(substr(year,-4) as integer) y from Movie),
s as (select distinct y from y)
select s.y start_year, (select count(*) from y where y.y between s.y and s.y + 9) total_movies from s order by 2 desc, 1 limit 3;
-- name: local096_female_only
with my as (select MID, cast(substr(year,-4) as integer) y from Movie),
g as (select distinct PID, Gender from Person where PID is not null),
mc as (select c.MID, sum(case when g.Gender = 'Female' then 0 else 1 end) nonfemale from M_Cast c left join g on g.PID = trim(c.PID) group by c.MID)
select my.y year, count(*) total, round(100.0 * sum(mc.nonfemale = 0) / count(*), 2) pct from my left join mc using(MID) group by my.y order by my.y;
-- name: local096_vs_gold_rows_with_female_only
with my as (select MID, cast(substr(year,-4) as integer) y from Movie),
g as (select distinct PID, Gender from Person where PID is not null),
mc as (select c.MID, sum(case when g.Gender = 'Female' then 0 else 1 end) nonfemale from M_Cast c left join g on g.PID = trim(c.PID) group by c.MID)
select my.y, count(*) total, sum(mc.nonfemale = 0) female_only from my left join mc using(MID) group by my.y having sum(mc.nonfemale = 0) > 0;
-- name: local099_gold_sql
WITH YASH_CHOPRAS_PID AS (SELECT TRIM(P.PID) AS PID FROM Person P WHERE TRIM(P.Name) = 'Yash Chopra'),
NUM_OF_MOV_BY_ACTOR_DIRECTOR AS (SELECT TRIM(MC.PID) AS ACTOR_PID, TRIM(MD.PID) AS DIRECTOR_PID, COUNT(DISTINCT TRIM(MD.MID)) AS NUM_OF_MOV
  FROM M_Cast MC JOIN M_Director MD ON TRIM(MC.MID) = TRIM(MD.MID) GROUP BY ACTOR_PID, DIRECTOR_PID),
NUM_OF_MOVIES_BY_YC AS (SELECT NM.ACTOR_PID, NM.DIRECTOR_PID, NM.NUM_OF_MOV AS NUM_OF_MOV_BY_YC FROM NUM_OF_MOV_BY_ACTOR_DIRECTOR NM JOIN YASH_CHOPRAS_PID YCP ON NM.DIRECTOR_PID = YCP.PID),
MAX_MOV_BY_OTHER_DIRECTORS AS (SELECT ACTOR_PID, MAX(NUM_OF_MOV) AS MAX_NUM_OF_MOV FROM NUM_OF_MOV_BY_ACTOR_DIRECTOR NM JOIN YASH_CHOPRAS_PID YCP ON NM.DIRECTOR_PID <> YCP.PID GROUP BY ACTOR_PID),
ACTORS_MOV_COMPARISION AS (SELECT NMY.ACTOR_PID, CASE WHEN NMY.NUM_OF_MOV_BY_YC > IFNULL(NMO.MAX_NUM_OF_MOV, 0) THEN 'Y' ELSE 'N' END AS MORE_MOV_BY_YC
  FROM NUM_OF_MOVIES_BY_YC NMY LEFT OUTER JOIN MAX_MOV_BY_OTHER_DIRECTORS NMO ON NMY.ACTOR_PID = NMO.ACTOR_PID)
SELECT COUNT(DISTINCT TRIM(P.PID)) AS "Number of actor" FROM Person P WHERE TRIM(P.PID) IN (SELECT DISTINCT ACTOR_PID FROM ACTORS_MOV_COMPARISION WHERE MORE_MOV_BY_YC = 'Y');
-- name: local099_ge_variant
-- ">= any other director" instead of ">" (candidate explanation of the 107 vs 266 alternative)
with ad as (select trim(c.PID) a, d.PID dir, count(distinct d.MID) n from M_Cast c join M_Director d using(MID) where c.PID is not null group by 1,2),
yc as (select PID from Person where trim(Name) = 'Yash Chopra'),
y as (select a, n from ad where dir in (select PID from yc)),
o as (select a, max(n) m from ad where dir not in (select PID from yc) group by a)
select sum(y.n > coalesce(o.m,0)) strictly_more, sum(y.n >= coalesce(o.m,0)) at_least from y left join o using(a);
-- name: yash_chopra_pids
select "index", PID, quote(Name) from Person where trim(Name) = 'Yash Chopra';
-- name: local100_shahrukh_2
with srk as (select distinct PID from Person where trim(Name) in ('Shah Rukh Khan', 'Shahrukh Khan')),
c as (select distinct MID, trim(PID) PID from M_Cast where PID is not null),
s1 as (select distinct b.PID from c a join c b on a.MID = b.MID where a.PID in (select PID from srk) and b.PID not in (select PID from srk)),
s2 as (select distinct b.PID from c a join c b on a.MID = b.MID where a.PID in (select PID from s1))
select (select group_concat(PID) from srk) srk_pids, count(*) shahrukh_2 from s2 where PID not in (select PID from s1) and PID not in (select PID from srk);
-- name: local098_no_gap_over_3
-- actors (cast PIDs) whose consecutive distinct credit years never differ by more than 4 (no 4-year span without a film)
with cy as (select distinct trim(c.PID) a, cast(substr(m.year,-4) as integer) y from M_Cast c join Movie m using(MID) where c.PID is not null),
g as (select a, y - lag(y) over (partition by a order by y) gap from cy)
select count(distinct a) actors, sum(case when mx is null or mx <= 4 then 1 else 0 end) gap_le_4, sum(case when mx is null or mx <= 3 then 1 else 0 end) gap_le_3
from (select a, max(gap) mx from g group by a);
