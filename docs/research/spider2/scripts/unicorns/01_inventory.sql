-- Run: sqlite3 -readonly data/spider2/modern_data.sqlite < docs/research/spider2/scripts/unicorns/01_inventory.sql
.headers on
.mode list
.print ## counts
SELECT 'funding' t, count(*) n, count(DISTINCT company_id) ids, min(company_id) lo, max(company_id) hi FROM companies_funding UNION ALL
SELECT 'dates', count(*), count(DISTINCT company_id), min(company_id), max(company_id) FROM companies_dates UNION ALL
SELECT 'industries', count(*), count(DISTINCT company_id), min(company_id), max(company_id) FROM companies_industries;

.print ## id range is dense 0..1073 (missing ids)
WITH RECURSIVE s(i) AS (SELECT 0 UNION ALL SELECT i+1 FROM s WHERE i<1073)
SELECT count(*) missing_in_funding FROM s WHERE i NOT IN (SELECT company_id FROM companies_funding);

.print ## duplicate ids: rows, distinct full rows
SELECT 'funding' t, count(*) dup_ids, sum(n) rows, sum(dv) distinct_rows FROM
 (SELECT company_id, count(*) n, count(DISTINCT valuation||'|'||funding||'|'||ifnull(select_investors,'<NULL>')) dv FROM companies_funding GROUP BY 1 HAVING n>1)
UNION ALL SELECT 'dates', count(*), sum(n), sum(dv) FROM
 (SELECT company_id, count(*) n, count(DISTINCT date_joined||'|'||year_founded) dv FROM companies_dates GROUP BY 1 HAVING n>1)
UNION ALL SELECT 'industries', count(*), sum(n), sum(dv) FROM
 (SELECT company_id, count(*) n, count(DISTINCT industry) dv FROM companies_industries GROUP BY 1 HAVING n>1);

.print ## rowids of the first copy of each duplicate (min rowid), per table
SELECT 'funding', group_concat(r, ' ') FROM (SELECT min(rowid) r FROM companies_funding GROUP BY company_id HAVING count(*)>1 ORDER BY 1);
SELECT 'dates', group_concat(r, ' ') FROM (SELECT min(rowid) r FROM companies_dates GROUP BY company_id HAVING count(*)>1 ORDER BY 1);
SELECT 'industries', group_concat(r, ' ') FROM (SELECT min(rowid) r FROM companies_industries GROUP BY company_id HAVING count(*)>1 ORDER BY 1);
.print ## duplicated id sets overlap between tables
SELECT count(*) f_and_d FROM (SELECT company_id FROM companies_funding GROUP BY 1 HAVING count(*)>1 INTERSECT SELECT company_id FROM companies_dates GROUP BY 1 HAVING count(*)>1);
SELECT count(*) f_and_i FROM (SELECT company_id FROM companies_funding GROUP BY 1 HAVING count(*)>1 INTERSECT SELECT company_id FROM companies_industries GROUP BY 1 HAVING count(*)>1);
SELECT count(*) d_and_i FROM (SELECT company_id FROM companies_dates GROUP BY 1 HAVING count(*)>1 INTERSECT SELECT company_id FROM companies_industries GROUP BY 1 HAVING count(*)>1);

.print ## rows 12..1085: same company at same rowid in all 3 tables; distinct ids there
SELECT count(*) aligned FROM companies_funding f JOIN companies_dates d ON d.rowid=f.rowid JOIN companies_industries i ON i.rowid=f.rowid
 WHERE f.rowid>=12 AND f.company_id=d.company_id AND f.company_id=i.company_id;
SELECT count(*) rows_12_on, count(DISTINCT company_id) ids_12_on FROM companies_funding WHERE rowid>=12;
SELECT count(DISTINCT company_id) ids_rows_1_11_in_12_on FROM companies_funding WHERE rowid<=11 AND company_id IN (SELECT company_id FROM companies_funding WHERE rowid>=12);
.print ## physical order of rows 12.. vs company_id: ascents/descents
SELECT sum(b.company_id>a.company_id) ascents, sum(b.company_id<a.company_id) descents FROM companies_funding a JOIN companies_funding b ON b.rowid=a.rowid+1 WHERE a.rowid>=12;
.print ## is physical order sorted by date_joined? (rows 12..)
SELECT sum(b.date_joined>a.date_joined) asc_, sum(b.date_joined<a.date_joined) desc_, sum(b.date_joined=a.date_joined) eq FROM companies_dates a JOIN companies_dates b ON b.rowid=a.rowid+1 WHERE a.rowid>=12;

.print ## storage types
SELECT 'funding', typeof(company_id), typeof(valuation), typeof(funding), typeof(select_investors), count(*) FROM companies_funding GROUP BY 2,3,4,5;
SELECT 'dates', typeof(company_id), typeof(date_joined), typeof(year_founded), length(date_joined), count(*) FROM companies_dates GROUP BY 2,3,4,5;
SELECT 'industries', typeof(company_id), typeof(industry), count(*) FROM companies_industries GROUP BY 2,3;
.print ## date_joined format
SELECT count(*) n, sum(date_joined GLOB '[12][0-9][0-9][0-9]-[01][0-9]-[0-3][0-9]T00:00:00.000') ymd_midnight_ms FROM companies_dates;
SELECT min(date_joined), max(date_joined), min(year_founded), max(year_founded) FROM companies_dates;
SELECT count(*) bad_dates FROM companies_dates WHERE date(substr(date_joined,1,10)) IS NULL OR date(substr(date_joined,1,10)) <> substr(date_joined,1,10);
