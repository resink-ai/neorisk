-- name: row_counts
select 'collisions', count(*) from collisions union all select 'case_ids', count(*) from case_ids
union all select 'parties', count(*) from parties union all select 'victims', count(*) from victims;
-- name: collisions_case_id_unique
select count(*), count(distinct case_id) from collisions;
-- name: case_ids_dup
select case_id, printf('%.0f', case_id), db_year, count(*) from case_ids group by case_id, db_year having count(*)>1 or case_id in (select case_id from case_ids group by case_id having count(*)>1);
-- name: case_ids_exact_dup_rows
select count(*) from (select case_id, db_year from case_ids group by 1,2 having count(*)>1);
-- name: parties_case_in_collisions
select count(*) n, sum(case_id in (select case_id from collisions)) matched from parties;
-- name: victims_case_in_collisions
select count(*) n, sum(case_id in (select case_id from collisions)) matched from victims;
-- name: case_ids_in_collisions
select count(*) n, sum(case_id in (select case_id from collisions)) matched from case_ids;
-- name: collisions_in_case_ids
select count(*) n, sum(case_id in (select case_id from case_ids)) matched from collisions;
-- name: collisions_with_parties
select count(*) n, sum(case_id in (select case_id from parties)) with_party, sum(case_id in (select case_id from victims)) with_victim from collisions;
-- name: victims_case_in_parties
select count(*) n, sum(case_id in (select case_id from parties)) matched_case,
 sum(exists(select 1 from parties p where p.case_id=v.case_id and p.party_number=v.party_number)) matched_party from victims v;
-- name: parties_id_dups
select count(*) dup_ids, sum(c) rows_in_dups from (select id, count(*) c from parties group by id having count(*)>1);
-- name: parties_id_dup_identical
select count(*) groups, sum(nd=1) identical from (select id, count(distinct case_id||'|'||party_number||'|'||ifnull(party_type,'')||ifnull(party_age,'')||ifnull(vehicle_make,'')) nd from parties group by id having count(*)>1);
-- name: parties_full_dup_rows
select count(*) - (select count(*) from (select distinct * from parties)) from parties;
-- name: victims_id_dups
select count(*) dup_ids, sum(c) rows_in_dups from (select id, count(*) c from victims group by id having count(*)>1);
-- name: victims_full_dup_rows
select count(*) - (select count(*) from (select distinct * from victims)) from victims;
-- name: parties_case_party_unique
select count(*), count(distinct printf('%.0f', case_id)||'/'||party_number) from parties;
-- name: parties_dup_id_examples
select p.* from parties p where id in (select id from parties group by id having count(*)>1 limit 3) order by id;
-- name: victims_dup_id_examples
select v.* from victims v where id in (select id from victims group by id having count(*)>1 limit 3) order by id;
-- name: case_ids_db_year_vs_collision_year
select c.db_year, substr(k.collision_date,1,4) y, count(*) from case_ids c join collisions k on k.case_id=c.case_id group by 1,2 order by 1,2;
-- name: rowid_order
select 'collisions', sum(a.case_id > b.case_id), sum(a.case_id < b.case_id) from collisions a join collisions b on b.rowid=a.rowid+1
union all select 'parties.id', sum(a.id > b.id), sum(a.id<b.id) from parties a join parties b on b.rowid=a.rowid+1
union all select 'victims.id', sum(a.id > b.id), sum(a.id<b.id) from victims a join victims b on b.rowid=a.rowid+1
union all select 'case_ids', sum(a.case_id > b.case_id), sum(a.case_id<b.case_id) from case_ids a join case_ids b on b.rowid=a.rowid+1;
-- name: collisions_date_order
select sum(a.collision_date > b.collision_date), sum(a.collision_date < b.collision_date) from collisions a join collisions b on b.rowid=a.rowid+1;
