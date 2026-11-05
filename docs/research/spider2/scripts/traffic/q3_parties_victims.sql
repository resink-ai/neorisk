-- name: parties_per_case
select n, count(*) cases from (select case_id, count(*) n from parties group by case_id) group by n order by n;
-- name: victims_per_case
select n, count(*) cases from (select case_id, count(*) n from victims group by case_id) group by n order by n;
-- name: parties_dup_case_party
select printf('%.0f',case_id), party_number, id, party_type from parties where printf('%.0f',case_id)||'/'||party_number in (select printf('%.0f',case_id)||'/'||party_number from parties group by 1 having count(*)>1);
-- name: party_number_dist
select party_number, count(*) from parties group by 1 order by 1;
-- name: parties_id_ranges
select min(id), max(id), count(*) from parties;
-- name: parties_id_dup_case_gap
select sum(abs(a.case_id - b.case_id) > 1e6) far_apart, count(*) from parties a join parties b on a.id=b.id and a.rowid<b.rowid;
-- name: victims_id_dup_case_gap
select sum(abs(a.case_id - b.case_id) > 1e6) far_apart, count(*) from victims a join victims b on a.id=b.id and a.rowid<b.rowid;
-- name: parties_time_source
select case when case_id in (select case_id from collisions) then 'collision' when case_id>=1e17 then 'case_id_2001' else 'rule' end src, count(*) from parties group by 1;
-- name: victims_time_source
select case when case_id in (select case_id from collisions) then 'collision' when case_id>=1e17 then 'case_id_2001' else 'rule' end src, count(*) from victims group by 1;
-- name: case_ids_time_source
select case when case_id in (select case_id from collisions) then 'collision' when case_id>=1e17 then 'case_id_2001' else 'rule' end src, count(*) from case_ids group by 1;
-- name: case_ids_db_year_by_id_kind
select db_year, case when case_id>=1e17 then 'date-coded' when case_id>=9e7 then '9e7+' else 'counter' end k, count(*) from case_ids group by 1,2 order by 1,2;
-- name: parties_id_kind
select case when case_id>=1e17 then 'date-coded' when case_id>=9e7 then '9e7+' else 'counter' end k, count(*) from parties group by 1;
-- name: party_real_non_integer
select sum(party_age<>cast(party_age as int)), sum(vehicle_year<>cast(vehicle_year as int)), sum(oaf_violation_section<>cast(oaf_violation_section as int)) from parties;
-- name: victim_real_non_integer
select sum(victim_age<>cast(victim_age as int)) from victims;
-- name: party_type_mix
select party_type, count(*), sum(at_fault) at_fault from parties group by 1 order by 2 desc;
-- name: party_age_outliers
select sum(party_age>100) gt100, sum(party_age=0) zero, sum(party_age<14 and party_type='driver') child_driver from parties;
-- name: vehicle_year_outliers
select sum(vehicle_year>2022) future, sum(vehicle_year<1950) pre1950, max(vehicle_year), min(vehicle_year) from parties;
-- name: victim_age_outliers
select victim_age, count(*) from victims where victim_age>100 group by 1;
-- name: victim_role_vs_degree
select victim_degree_of_injury, count(*) from victims group by 1 order by 2 desc;
-- name: dirty_codes_pv
select 'party_drug_physical=G', count(*) from parties where party_drug_physical='G' union all
select 'party_sex=X', count(*) from parties where party_sex='X' union all
select 'movement=S', count(*) from parties where movement_preceding_collision='S' union all
select 'vehicle_make numeric', count(*) from parties where vehicle_make glob '[0-9]*' union all
select 'cellphone_use_type=4', count(*) from parties where cellphone_use_type='4' union all
select 'victim_sex in 2,4', count(*) from victims where victim_sex in ('2','4') union all
select 'victim_safety_equipment_2=Z', count(*) from victims where victim_safety_equipment_2='Z' union all
select 'chp_vehicle_type_towing like %.0', count(*) from parties where chp_vehicle_type_towing like '%.0' union all
select 'chp_vehicle_type_towed like %.0', count(*) from parties where chp_vehicle_type_towed like '%.0' union all
select 'oaf_violation_suffix=0', count(*) from parties where oaf_violation_suffix='0';
-- name: towed_codes
select chp_vehicle_type_towed, count(*) from parties where chp_vehicle_type_towed in ('0','00','0.0','000') group by 1;
-- name: party_whitespace
select sum(vehicle_make<>trim(vehicle_make)), sum(vehicle_make glob '*[^ -~]*') from parties;
-- name: matched_victims_party_number_le_party_count
select sum(v.party_number <= c.party_count), count(*) from victims v join collisions c using(case_id);
-- name: matched_parties_killed_vs_collision
select sum(p.k <= c.killed_victims), count(*) from (select case_id, sum(party_number_killed) k from parties group by case_id) p join collisions c using(case_id);
-- name: at_fault_rate_by_party_number
select party_number, round(avg(at_fault),3), count(*) from parties where party_number<=4 group by 1;
