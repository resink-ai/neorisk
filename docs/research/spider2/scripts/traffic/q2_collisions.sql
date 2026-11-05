-- name: date_time_formats
select sum(collision_date glob '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]') date_iso, sum(date(collision_date)=collision_date) date_valid,
 sum(collision_time glob '[0-2][0-9]:[0-5][0-9]:[0-5][0-9]') time_hms, sum(substr(collision_time,7,2)<>'00') time_nonzero_sec,
 sum(collision_time is null) time_null, sum(collision_time='00:00:00') time_midnight,
 sum(process_date glob '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]' and date(process_date)=process_date) process_iso from collisions;
-- name: process_lag_days
select case when d<0 then 'neg' when d=0 then '0' when d<=7 then '1-7' when d<=30 then '8-30' when d<=90 then '31-90' when d<=365 then '91-365' when d<=730 then '366-730' else '>730' end b, count(*), min(d), max(d)
from (select julianday(process_date)-julianday(collision_date) d from collisions) group by b order by min(d);
-- name: process_lag_quantiles
with x as (select julianday(process_date)-julianday(collision_date) d, row_number() over (order by julianday(process_date)-julianday(collision_date)) r, count(*) over () n from collisions)
select max(case when r=cast(n*0.1 as int) then d end) p10, max(case when r=cast(n*0.5 as int) then d end) p50, max(case when r=cast(n*0.9 as int) then d end) p90, max(case when r=cast(n*0.99 as int) then d end) p99 from x;
-- name: snapshot
select max(collision_date), max(process_date), min(collision_date), min(process_date) from collisions;
-- name: per_year
select substr(collision_date,1,4) y, count(*), round(avg(julianday(process_date)-julianday(collision_date)),1) mean_lag from collisions group by y order by y;
-- name: injured_sum_rule
select sum(injured_victims = severe_injury_count+other_visible_injury_count+complaint_of_pain_injury_count) eq,
 sum(injured_victims <> severe_injury_count+other_visible_injury_count+complaint_of_pain_injury_count) ne, sum(injured_victims is null) null_ from collisions;
-- name: injured_sum_diffs
select injured_victims - (severe_injury_count+other_visible_injury_count+complaint_of_pain_injury_count) d, count(*) from collisions where injured_victims is not null group by d order by d;
-- name: killed_vs_mode_counts
select sum(killed_victims >= pedestrian_killed_count+bicyclist_killed_count+motorcyclist_killed_count) ge, sum(killed_victims < pedestrian_killed_count+bicyclist_killed_count+motorcyclist_killed_count) lt from collisions;
-- name: severity_rule
select collision_severity, sum(killed_victims>0) k, sum(killed_victims=0 and severe_injury_count>0) s, sum(killed_victims=0 and severe_injury_count=0 and other_visible_injury_count>0) o,
 sum(killed_victims=0 and severe_injury_count=0 and other_visible_injury_count=0 and complaint_of_pain_injury_count>0) p,
 sum(killed_victims=0 and severe_injury_count=0 and other_visible_injury_count=0 and complaint_of_pain_injury_count=0) none_, sum(killed_victims is null) knull, count(*) from collisions group by 1;
-- name: flag_vs_involved_with
select pedestrian_collision, motor_vehicle_involved_with='pedestrian' mv_ped, count(*) from collisions group by 1,2;
-- name: not_chp_consistency
select chp_shift='not chp' a, beat_type='not chp' b, chp_beat_type='not chp' c, chp_beat_class='not chp' d, count(*) from collisions group by 1,2,3,4;
-- name: caltrans_null_pattern
select caltrans_district is null a, state_route is null b, postmile is null c, caltrans_county is null d, location_type is null e, side_of_highway is null f, count(*) from collisions group by 1,2,3,4,5,6;
-- name: county_city_to_county_fd
select count(*) ccl, sum(nc>1) multi_county from (select county_city_location, count(distinct county_location) nc from collisions group by 1);
-- name: county_city_to_population_fd
select count(*) ccl, sum(np>1) multi_population from (select county_city_location, count(distinct population) np from collisions group by 1);
-- name: latlon_presence_by_year
select substr(collision_date,1,4) y, count(*), sum(latitude is not null) with_latlon from collisions group by y order by y;
-- name: real_columns_non_integer
select 'jurisdiction', sum(jurisdiction<>cast(jurisdiction as int)) from collisions union all
select 'distance', sum(distance<>cast(distance as int)) from collisions union all
select 'postmile', sum(postmile<>cast(postmile as int)) from collisions union all
select 'killed_victims', sum(killed_victims<>cast(killed_victims as int)) from collisions union all
select 'party_count', sum(party_count<>cast(party_count as int)) from collisions union all
select 'pcf_violation', sum(pcf_violation<>cast(pcf_violation as int)) from collisions union all
select 'state_route', sum(state_route<>cast(state_route as int)) from collisions union all
select 'latitude', sum(latitude<>cast(latitude as int)) from collisions union all
select 'motorcyclist_injured_count', sum(motorcyclist_injured_count<>cast(motorcyclist_injured_count as int)) from collisions;
-- name: latlon_decimals
select max(length(cast(latitude as text))), max(length(cast(longitude as text))), sum(latitude=round(latitude,5)), sum(latitude is not null), sum(longitude=round(longitude,5)), sum(postmile=round(postmile,3)), sum(postmile is not null) from collisions;
-- name: text_dot_zero
select 'reporting_district', sum(reporting_district like '%.0') from collisions union all
select 'chp_road_type', sum(chp_road_type like '%.0') from collisions union all
select 'chp_vehicle_type_at_fault', sum(chp_vehicle_type_at_fault like '%.0') from collisions union all
select 'officer_id', sum(officer_id like '%.0') from collisions union all
select 'beat_number', sum(beat_number like '%.0') from collisions;
-- name: chp_road_type_values
select chp_road_type, count(*) from collisions group by 1 order by 1;
-- name: whitespace
select sum(primary_road<>trim(primary_road)) pr, sum(secondary_road<>trim(secondary_road)) sr, sum(officer_id<>trim(officer_id)) oid, sum(beat_number<>trim(beat_number)) bn, sum(reporting_district<>trim(reporting_district)) rd,
 sum(primary_road glob '*[^ -~]*') pr_nonascii, sum(secondary_road glob '*[^ -~]*') sr_nonascii from collisions;
-- name: odd_leading_chars
select substr(officer_id,1,1) c, count(*) from collisions where officer_id not glob '[0-9A-Za-z]*' group by c union all
select 'road:'||substr(primary_road,1,1), count(*) from collisions where primary_road not glob '[0-9A-Za-z]*' group by 1;
-- name: dirty_codes
select 'road_surface=H', count(*) from collisions where road_surface='H' union all
select 'pcf_violation_code', count(*) from collisions where pcf_violation_code in ('''','A','D') union all
select 'motor_vehicle_involved_with=2', count(*) from collisions where motor_vehicle_involved_with='2' union all
select 'distance>52800 (10 mi)', count(*) from collisions where distance>52800;
-- name: hit_and_run_x_severity
select hit_and_run, collision_severity, count(*) from collisions group by 1,2 order by 1,2;
-- name: weekday_hour
select strftime('%w', collision_date) dow, count(*) from collisions group by 1 order by 1;
-- name: hour
select substr(collision_time,1,2) h, count(*) from collisions group by 1 order by 1;
-- name: minute_rounding
select sum(substr(collision_time,4,2) in ('00','30')) on_half_hour, sum(substr(collision_time,4,2) in ('00','15','30','45')) on_quarter, sum(cast(substr(collision_time,4,2) as int)%5=0) on_5min, count(collision_time) from collisions;
-- name: same_day_count
with d as (select collision_date, count(*) c from collisions group by 1) select c, count(*) days from d group by c order by c;
-- name: severity_mix
select collision_severity, count(*), round(100.0*count(*)/(select count(*) from collisions),2) pct from collisions group by 1 order by 2 desc;
-- name: party_count_dist
select party_count, count(*) from collisions group by 1 order by 1;
-- name: pcf_category_mix
select pcf_violation_category, count(*) from collisions group by 1 order by 2 desc;
-- name: type_of_collision_mix
select type_of_collision, count(*) from collisions group by 1 order by 2 desc;
-- name: matched_party_count_vs_parties
select sum(c.party_count = p.n) eq, sum(c.party_count > p.n) more_in_collision, sum(c.party_count < p.n) fewer, count(*) from collisions c join (select case_id, count(*) n from parties group by case_id) p using(case_id);
