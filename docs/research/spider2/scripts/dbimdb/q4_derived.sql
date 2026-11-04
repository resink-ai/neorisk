-- Proofs that the rebuild rules reproduce each table exactly (0 differing rows both ways).
-- name: person_rebuilt_from_credits
-- Person = first-seen distinct trimmed PIDs over (M_Cast rows, then M_Producer rows), NULL kept as one value,
-- name with one leading space; then first-seen distinct directors, name unpadded. Gender is a per-PID attribute.
with pinfo as (select PID, trim(max(Name)) nm, max(Gender) g from Person where PID is not null group by PID),
stream as (select trim(PID) pid, "index" pos from M_Cast union all select trim(PID), "index" + 1000000 from M_Producer),
cp as (select pid, min(pos) f from stream group by pid),
cpr as (select pid, row_number() over (order by f) - 1 idx from cp),
d as (select PID pid, min("index") f from M_Director group by PID),
dr as (select pid, row_number() over (order by f) - 1 + (select count(*) from cp) idx from d),
rebuilt as (
  select cpr.idx "index", cpr.pid PID, case when cpr.pid is null then null else ' ' || p.nm end Name, p.g Gender from cpr left join pinfo p on p.PID = cpr.pid
  union all select dr.idx, dr.pid, p.nm, p.g from dr join pinfo p on p.PID = dr.pid)
select (select count(*) from rebuilt) rebuilt_rows,
  (select count(*) from (select "index", PID, Name, Gender from Person except select * from rebuilt)) src_minus_rebuilt,
  (select count(*) from (select * from rebuilt except select "index", PID, Name, Gender from Person)) rebuilt_minus_src;
-- name: cast_index_from_billing
-- M_Cast."index" = row_number over (Movie.index, billing position within movie) - 1; ID = index; PID = ' ' || pid
with b as (select c."index" i, m."index" mi, row_number() over (partition by c.MID order by c."index") pos from M_Cast c join Movie m using(MID)),
r as (select i, row_number() over (order by mi, pos) - 1 rebuilt from b)
select count(*) n, sum(i = rebuilt) same from r;
-- name: producer_index_from_position
with b as (select c."index" i, m."index" mi, row_number() over (partition by c.MID order by c."index") pos from M_Producer c join Movie m using(MID)),
r as (select i, row_number() over (order by mi, pos) - 1 rebuilt from b)
select count(*) n, sum(i = rebuilt) same from r;
-- name: credit_pid_padding_rule
select 'M_Cast' t, count(*) n, sum(PID is null or PID = ' ' || trim(PID)) rule_ok from M_Cast
union all select 'M_Producer', count(*), sum(PID is null or PID = ' ' || trim(PID)) from M_Producer
union all select 'M_Director', count(*), sum(PID = trim(PID)) from M_Director;
-- name: genre_padding_rule
select count(*) n, sum(Name = rtrim(Name) || '            ') twelve_spaces, quote(min(case when Name = rtrim(Name) then Name end)) unpadded from Genre;
-- name: year_split_rule
-- year = [roman disambiguator || ' '] || 4-digit year
select count(*) n, sum(year = case when length(year)=4 then year else substr(year,1,instr(year,' ')-1) || ' ' || substr(year,-4) end) rule_ok,
  sum(substr(year,-4) glob '[12][0-9][0-9][0-9]') four_digit_tail, sum(length(year)>4 and substr(year,1,instr(year,' ')-1) not in ('I','II','III','IV','V','VI','VII','VIII','IX','X','XI','XII','XIII','XIV','XV','XVI','XVII')) bad_prefix from Movie;
-- name: real_ids_whole
select 'M_Location.LID' c, count(LID) nonnull, sum(LID = cast(LID as integer)) whole from M_Location
union all select 'M_Country.CID', count(CID), sum(CID = cast(CID as integer)) from M_Country;
-- name: one_per_movie_link_tables
-- M_Genre/M_Language/M_Country/M_Location/M_Director rows i == Movie row i; ID == index: so each is a movie attribute
select 'all five' t, (select count(*) from Movie m join M_Genre g on g."index"=m."index" and g.MID=m.MID and g.ID=g."index"
  join M_Language l on l."index"=m."index" and l.MID=m.MID and l.ID=l."index"
  join M_Country c on c."index"=m."index" and c.MID=m.MID and c.ID=c."index"
  join M_Location o on o."index"=m."index" and o.MID=m.MID and o.ID=o."index"
  join M_Director d on d."index"=m."index" and d.MID=m.MID and d.ID=d."index") aligned, (select count(*) from Movie) movies;
