-- name: key_uniqueness
select 'legislators.id_bioguide' k, count(*) n, count(distinct id_bioguide) d from legislators
union all select 'legislators.id_govtrack', count(*), count(distinct id_govtrack) from legislators
union all select 'terms.term_id', count(*), count(distinct term_id) from legislators_terms
union all select 'terms.(id_bioguide,term_number)', count(*), count(distinct id_bioguide||'|'||term_number) from legislators_terms
union all select 'date_dim.date', count(*), count(distinct date) from legislation_date_dim;

-- name: term_id_rule
select sum(term_id = id_bioguide||'-'||term_number) ok, count(*) n from legislators_terms;

-- name: fk_orphans
select 'terms->legislators' j, count(*) orphans from legislators_terms t where not exists (select 1 from legislators l where l.id_bioguide=t.id_bioguide)
union all select 'legislators without terms', count(*) from legislators l where not exists (select 1 from legislators_terms t where t.id_bioguide=l.id_bioguide)
union all select 'previous_0 -> legislators', count(*) from legislators where id_bioguide_previous_0 is not null and id_bioguide_previous_0 not in (select id_bioguide from legislators);

-- name: term_number_dense
-- term_number runs 0..n-1 per legislator
select sum(mx = cnt-1 and mn = 0) dense, count(*) legislators from
 (select id_bioguide, min(term_number) mn, max(term_number) mx, count(*) cnt from legislators_terms group by 1);

-- name: term_number_in_start_order
-- is term_number the rank of term_start within the legislator?
with r as (select id_bioguide, term_number, term_start,
   row_number() over (partition by id_bioguide order by term_start, term_number) - 1 rk,
   lag(term_start) over (partition by id_bioguide order by term_number) prev_start,
   lag(term_end) over (partition by id_bioguide order by term_number) prev_end from legislators_terms)
select sum(rk = term_number) rank_equals_number, count(*) n,
  sum(prev_start is not null and term_start < prev_start) start_goes_back,
  sum(prev_start is not null and term_start = prev_start) same_start_as_prev,
  sum(prev_end is not null and term_start < prev_end) overlaps_prev,
  sum(prev_end is not null and term_start = prev_end) starts_on_prev_end
from r;

-- name: rowid_order
-- rowid order: legislators grouped? terms order
with t as (select rowid r, id_bioguide, term_number, lag(id_bioguide) over (order by rowid) pb, lag(term_number) over (order by rowid) pn from legislators_terms)
select sum(pb = id_bioguide and term_number = pn+1) next_term_same_person,
       sum(pb <> id_bioguide) person_changes, count(distinct id_bioguide) people,
       sum(pb <> id_bioguide and term_number = 0) changes_at_term0
from t;

-- name: terms_rowid_vs_legislators_rowid
-- term_number = 0 rows: does their rowid order follow legislators rowid order?
with a as (select t.rowid tr, l.rowid lr from legislators_terms t join legislators l using(id_bioguide) where term_number = 0)
select count(*) n, sum(lr = (select count(*) from a a2 where a2.tr <= a.tr)) rank_match from a;

-- name: rowid_order_term0_block
select min(rowid), max(rowid), count(*) from legislators_terms where term_number = 0;

-- name: term_number_blocks
select term_number, min(rowid), max(rowid), count(*) from legislators_terms group by 1 order by 1 limit 6;

-- name: legislators_current_first
-- the Tanimura CSV is current (legislators-current.yaml) followed by historical
with lastend as (select id_bioguide, max(term_end) le from legislators_terms group by 1)
select (l.rowid <= 539) block, count(*), min(le), max(le) from legislators l join lastend using(id_bioguide) group by 1;

-- name: current_block_size
with lastend as (select l.rowid r, max(term_end) le from legislators l join legislators_terms t using(id_bioguide) group by l.rowid)
select min(r) first_rowid_ending_before_2021 from lastend where le < '2021-01-03';

-- name: type_columns
select term_type, count(*), sum(district is not null) has_district, sum(class is not null) has_class,
  sum(state_rank is not null) has_rank, sum(how is not null) appointment from legislators_terms group by 1;

-- name: date_formats
select 'term_start' c, sum(term_start glob '[12][0-9][0-9][0-9]-[01][0-9]-[0-3][0-9]') iso, sum(date(term_start) = term_start) valid, count(*) from legislators_terms
union all select 'term_end', sum(term_end glob '[12][0-9][0-9][0-9]-[01][0-9]-[0-3][0-9]'), sum(date(term_end)=term_end), count(*) from legislators_terms
union all select 'birthday', sum(birthday glob '[12][0-9][0-9][0-9]-[01][0-9]-[0-3][0-9]'), sum(date(birthday)=birthday), count(birthday) from legislators
union all select 'other_names_end', sum(other_names_end glob '[12][0-9][0-9][0-9]-[01][0-9]-[0-3][0-9]'), sum(date(other_names_end)=other_names_end), count(other_names_end) from legislators;

-- name: end_vs_start
select sum(term_end > term_start) pos, sum(term_end = term_start) zero, sum(term_end < term_start) neg from legislators_terms;

-- name: snapshot
select max(term_start) last_start, max(term_end) last_end,
  sum(term_end > '2020-05-19') ends_after_last_start, sum(term_start <= '2020-05-19' and term_end > '2020-05-19') open_at_last_start
from legislators_terms;

-- name: term_lengths_days
select term_type, cast(julianday(term_end)-julianday(term_start) as int) days, count(*) from legislators_terms group by 1,2 order by 3 desc limit 12;

-- name: real_columns_integral
select 'district' c, sum(district <> cast(district as int)) non_integral from legislators_terms
union all select 'class', sum(class <> cast(class as int)) from legislators_terms
union all select 'id_icpsr', sum(id_icpsr <> cast(id_icpsr as int)) from legislators
union all select 'id_house_history', sum(id_house_history <> cast(id_house_history as int)) from legislators
union all select 'id_thomas', sum(id_thomas <> cast(id_thomas as int)) from legislators
union all select 'id_cspan', sum(id_cspan <> cast(id_cspan as int)) from legislators
union all select 'id_votesmart', sum(id_votesmart <> cast(id_votesmart as int)) from legislators;

-- name: district_values
select district, count(*) from legislators_terms where district <= 0 or district is null group by 1;

-- name: url_whitespace
select term_id, '['||url||']' from legislators_terms where url <> trim(url);

-- name: party_top
select party, count(*) from legislators_terms group by 1 order by 2 desc limit 15;

-- name: party_rare
select count(*) parties_under_10_terms from (select party from legislators_terms group by 1 having count(*) < 10);

-- name: states
select count(distinct state) states, group_concat(distinct state) from (select state from legislators_terms order by state);

-- name: gender
select gender, count(*) from legislators group by 1;

-- name: birthday_vs_first_term
with f as (select id_bioguide, min(term_start) fs from legislators_terms group by 1)
select count(*) with_bday, sum(birthday >= fs) born_after_first_term,
  min(cast((julianday(fs)-julianday(birthday))/365.25 as int)) min_age, max(cast((julianday(fs)-julianday(birthday))/365.25 as int)) max_age
from legislators join f using(id_bioguide) where birthday is not null;

-- name: duplicate_full_names
select count(*) names_shared, sum(c) people from (select full_name, count(*) c from legislators group by 1 having c > 1);

-- name: contact_cols_only_recent
select min(term_start), count(*) from legislators_terms where url is not null or address is not null or phone is not null or office is not null;

-- name: contact_cols_last_term_only
with mx as (select id_bioguide, max(term_number) m from legislators_terms group by 1)
select sum(t.term_number = mx.m) on_last_term, count(*) rows_with_office from legislators_terms t join mx using(id_bioguide) where office is not null;

-- name: url_rows_by_last
with mx as (select id_bioguide, max(term_number) m from legislators_terms group by 1)
select sum(t.term_number = mx.m) on_last_term, count(*) rows_with_url from legislators_terms t join mx using(id_bioguide) where url is not null;
