-- Rebuild checks for the proposed events. N = 2020-05-22 (last past date, q4:snapshot_N).

-- name: event_counts
select (select count(*) from legislators_terms) term_started,
       (select count(*) from legislators_terms where term_end <= '2020-05-22') term_ended,
       (select count(*) from legislators_terms where term_end > '2020-05-22') open_with_scheduled_end,
       (select count(*) from legislators_terms where term_start > '2020-05-22') starts_after_N;

-- name: term_end_roundtrip
-- term_end = coalesce(term_ended time, scheduled_end); both are the same text, so rebuild is identity
with e as (select term_id, case when term_end <= '2020-05-22' then term_end end ended_at,
                  case when term_end > '2020-05-22' then term_end end scheduled_end from legislators_terms)
select sum(coalesce(e.ended_at, e.scheduled_end) = t.term_end) ok, count(*) n from legislators_terms t join e using(term_id);

-- name: same_day_end_then_start
-- with ord = 2*term_number (+1 for the end), a same-day end of term k sorts after start of k? check per owner
with x as (select id_bioguide, term_number, term_start, lag(term_end) over (partition by id_bioguide order by term_number) pe from legislators_terms)
select count(*) same_day_handover from x where term_start = pe;

-- name: same_day_start_end_conflict
-- does any term end on the same day it or a later term starts? (would need end before start)
select count(*) from legislators_terms a join legislators_terms b on a.id_bioguide=b.id_bioguide and b.term_number > a.term_number and b.term_start < a.term_end;

-- name: current_block_stragglers
with le as (select id_bioguide, max(term_end) le from legislators_terms group by 1)
select l.rowid, l.id_bioguide, l.full_name, le from legislators l join le using(id_bioguide) where l.rowid <= 539 and le <= '2020-05-22';

-- name: entity_created_at
-- created_at = first term_start; all on or before N
select min(fs), max(fs), count(*) from (select min(term_start) fs from legislators_terms group by id_bioguide);

-- name: real_cols_as_int_roundtrip
-- REAL columns hold integers only: cast to int and back equals the stored value
select sum(cast(cast(district as int) as real) = district) d_ok, count(district) d_n,
       sum(cast(cast(class as int) as real) = class) c_ok, count(class) c_n from legislators_terms;

-- name: real_cols_legislators
select sum(cast(cast(id_icpsr as int) as real) = id_icpsr) icpsr_ok, count(id_icpsr) icpsr_n,
       sum(cast(cast(id_house_history as int) as real) = id_house_history) hh_ok, count(id_house_history) hh_n,
       max(id_house_history) hh_max from legislators;

-- name: snapshot_style_ids_by_era
-- modern identifiers exist mostly for people who served after 1970: evidence they are snapshot attributes
with le as (select id_bioguide, max(term_end) le from legislators_terms group by 1)
select case when le >= '1971' then 'served after 1970' else 'left before 1971' end era, count(*) n,
  sum(id_fec_0 is not null) fec, sum(id_opensecrets is not null) opensecrets, sum(id_votesmart is not null) votesmart,
  sum(id_cspan is not null) cspan, sum(id_ballotpedia is not null) ballotpedia, sum(id_thomas is not null) thomas, sum(id_lis is not null) lis
from legislators join le using(id_bioguide) group by 1;
