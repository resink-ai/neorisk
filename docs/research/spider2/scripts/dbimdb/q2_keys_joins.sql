-- name: person_dup_pids
select count(*) dup_pid_groups, sum(c) rows_in_groups, sum(c-1) extra_rows, max(c) max_copies from (select PID, count(*) c from Person group by PID having count(*)>1);
-- name: person_dup_exact
-- duplicate PIDs: are the copies byte-identical (Name, Gender)?
select count(*) groups, sum(dn=1 and dg=1) identical, sum(dn>1) name_differs, sum(dg>1) gender_differs from (
  select PID, count(distinct quote(Name)) dn, count(distinct quote(Gender)) dg from Person where PID is not null group by PID having count(*)>1);
-- name: person_dup_name_samples
select PID, quote(Name), quote(Gender), "index" from Person where PID in (
  select PID from Person group by PID having count(distinct quote(Name))>1 or count(distinct quote(Gender))>1) order by PID, "index" limit 20;
-- name: person_full_row_dups
select count(*) - (select count(*) from (select distinct PID, Name, Gender from Person)) full_row_extra from Person;
-- name: person_null_row
select "index", quote(PID), quote(Name), quote(Gender) from Person where PID is null or Name is null;
-- name: person_name_dups
select count(*) names_shared_by_gt1_pid from (select trim(Name) from Person group by trim(Name) having count(distinct PID)>1);
-- name: fk_orphans
select 'M_Cast.PID(trim)->Person' fk, count(*) n, sum(PID is null) null_ref, sum(PID is not null and trim(PID) not in (select PID from Person where PID is not null)) orphans from M_Cast
union all select 'M_Cast.PID(raw)->Person', count(*), sum(PID is null), sum(PID is not null and PID not in (select PID from Person where PID is not null)) from M_Cast
union all select 'M_Producer.PID(trim)->Person', count(*), sum(PID is null), sum(PID is not null and trim(PID) not in (select PID from Person where PID is not null)) from M_Producer
union all select 'M_Director.PID->Person', count(*), sum(PID is null), sum(PID not in (select PID from Person where PID is not null)) from M_Director
union all select 'M_Cast.MID->Movie', count(*), sum(MID is null), sum(MID not in (select MID from Movie)) from M_Cast
union all select 'M_Producer.MID->Movie', count(*), sum(MID is null), sum(MID not in (select MID from Movie)) from M_Producer
union all select 'M_Director.MID->Movie', count(*), sum(MID is null), sum(MID not in (select MID from Movie)) from M_Director
union all select 'M_Genre.MID->Movie', count(*), 0, sum(MID not in (select MID from Movie)) from M_Genre
union all select 'M_Genre.GID->Genre', count(*), sum(GID is null), sum(GID not in (select GID from Genre)) from M_Genre
union all select 'M_Language.LAID->Language', count(*), sum(LAID is null), sum(LAID not in (select LAID from Language)) from M_Language
union all select 'M_Country.CID->Country', count(*), sum(CID is null), sum(CID is not null and CID not in (select CID from Country)) from M_Country
union all select 'M_Location.LID->Location', count(*), sum(LID is null), sum(LID is not null and LID not in (select LID from Location)) from M_Location;
-- name: link_rows_align_with_movie
-- the four 1-per-movie link tables: is row i the i-th Movie?
select 'M_Location' t, count(*) n, sum(l.MID = m.MID) same_row from M_Location l join Movie m on m."index" = l."index"
union all select 'M_Country', count(*), sum(l.MID = m.MID) from M_Country l join Movie m on m."index" = l."index"
union all select 'M_Language', count(*), sum(l.MID = m.MID) from M_Language l join Movie m on m."index" = l."index"
union all select 'M_Genre', count(*), sum(l.MID = m.MID) from M_Genre l join Movie m on m."index" = l."index"
union all select 'M_Director', count(*), sum(l.MID = m.MID) from M_Director l join Movie m on m."index" = l."index";
-- name: lookup_first_use_order
-- are lookup ids assigned in order of first use by Movie.index? (pandas factorize fingerprint)
select 'Genre' t, count(*) ids, sum(rk = GID+1) in_first_use_order from (select GID, row_number() over (order by min(m."index")) rk from M_Genre g join Movie m using(MID) group by GID)
union all select 'Language', count(*), sum(rk = LAID+1) from (select LAID, row_number() over (order by min(m."index")) rk from M_Language g join Movie m using(MID) group by LAID)
union all select 'Country', count(*), sum(rk = CID+1) from (select CID, row_number() over (order by min(m."index")) rk from M_Country g join Movie m using(MID) where CID is not null group by CID)
union all select 'Location', count(*), sum(rk = LID+1) from (select LID, row_number() over (order by min(m."index")) rk from M_Location g join Movie m using(MID) where LID is not null group by LID);
-- name: lookup_unused
select 'Genre' t, count(*) n, sum(GID not in (select GID from M_Genre)) unused from Genre
union all select 'Language', count(*), sum(LAID not in (select LAID from M_Language)) from Language
union all select 'Country', count(*), sum(CID not in (select CID from M_Country where CID is not null)) from Country
union all select 'Location', count(*), sum(LID not in (select LID from M_Location where LID is not null)) from Location;
-- name: person_coverage
with p as (select distinct PID from Person where PID is not null),
c as (select distinct trim(PID) PID from M_Cast where PID is not null),
pr as (select distinct trim(PID) PID from M_Producer where PID is not null),
d as (select distinct PID from M_Director)
select (select count(*) from p) persons, (select count(*) from c) cast_people, (select count(*) from pr) producers, (select count(*) from d) directors,
 (select count(*) from p where PID not in (select PID from c union select PID from pr union select PID from d)) unused,
 (select count(*) from p where PID in (select PID from c) and PID in (select PID from d)) cast_and_director,
 (select count(*) from p where PID in (select PID from pr) and PID in (select PID from d)) producer_and_director;
-- name: person_order_vs_first_credit
-- Person row order vs first credit (movie index, then credit row) across cast/producer/director
with credits as (
  select trim(PID) PID, m."index" mi, 0 kind, c."index" ci from M_Cast c join Movie m using(MID) where PID is not null
  union all select trim(PID), m."index", 1, c."index" from M_Producer c join Movie m using(MID) where PID is not null
  union all select PID, m."index", 2, c."index" from M_Director c join Movie m using(MID)),
first_p as (select PID, min("index") pi from Person where PID is not null group by PID),
first_c as (select PID, min(mi) mi from credits group by PID)
select count(*) n, sum(a.pi_rank = b.c_rank) same_rank,
       sum(a.pi_rank < b.c_rank) earlier, sum(a.pi_rank > b.c_rank) later
from (select PID, rank() over (order by pi) pi_rank from first_p where PID in (select PID from first_c)) a
join (select PID, dense_rank() over (order by mi) c_rank from first_c) b using(PID);
-- name: person_movie_monotone
-- is the first-credit movie index of Person rows non-decreasing along Person.index?
with credits as (
  select trim(PID) PID, m."index" mi from M_Cast c join Movie m using(MID) where PID is not null
  union all select trim(PID), m."index" from M_Producer c join Movie m using(MID) where PID is not null
  union all select PID, m."index" from M_Director c join Movie m using(MID)),
fc as (select PID, min(mi) mi from credits group by PID),
seq as (select p."index" pi, fc.mi, lag(fc.mi) over (order by p."index") prev from Person p join fc using(PID))
select count(*) pairs, sum(mi >= prev) nondecreasing, sum(mi < prev) drops from seq where prev is not null;
-- name: cast_per_movie
select count(*) movies_with_cast, min(c), max(c), avg(c) from (select MID, count(*) c from M_Cast group by MID);
-- name: movies_without
select (select count(*) from Movie where MID not in (select MID from M_Cast)) no_cast,
       (select count(*) from Movie where MID not in (select MID from M_Producer)) no_producer,
       (select count(*) from Movie where MID not in (select MID from M_Director)) no_director;
-- name: cast_dup_rows
select MID, quote(PID), count(*) from M_Cast group by MID, PID having count(*)>1;
-- name: producer_dup_rows
select MID, quote(PID), count(*) from M_Producer group by MID, PID having count(*)>1 limit 10;
-- name: null_pid_credit_rows
select 'M_Cast' t, "index", MID, quote(PID) from M_Cast where PID is null
union all select 'M_Producer', "index", MID, quote(PID) from M_Producer where PID is null;
-- name: credit_order_within_movie
-- credit rows are grouped by movie in Movie.index order?
select 'M_Cast' t, count(*) pairs, sum(mi >= prev) nondecr from (select m."index" mi, lag(m."index") over (order by c."index") prev from M_Cast c join Movie m using(MID)) where prev is not null
union all select 'M_Producer', count(*), sum(mi >= prev) from (select m."index" mi, lag(m."index") over (order by c."index") prev from M_Producer c join Movie m using(MID)) where prev is not null;
-- name: director_is_also_cast
select count(*) movies, sum(exists(select 1 from M_Cast c where c.MID=d.MID and trim(c.PID)=d.PID)) director_in_cast from M_Director d;
