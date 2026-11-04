-- Run: sqlite3 -readonly data/spider2/modern_data.sqlite < docs/research/spider2/scripts/trees/01_inventory.sql
.headers on
.mode list
.print ## counts
SELECT 'trees' t, count(*) n, count(DISTINCT idx) idx_d, min(idx) idx_lo, max(idx) idx_hi, count(DISTINCT tree_id) tid_d, min(tree_id) tid_lo, max(tree_id) tid_hi FROM trees;
SELECT 'income_trees' t, count(*) n, count(DISTINCT zipcode) zips, min(zipcode), max(zipcode) FROM income_trees;
.print ## trees: idx <-> tree_id is 1:1 ?
SELECT count(*) FROM (SELECT idx FROM trees GROUP BY idx HAVING count(DISTINCT tree_id)>1);
SELECT count(*) FROM (SELECT tree_id FROM trees GROUP BY tree_id HAVING count(DISTINCT idx)>1);
.print ## trees duplicates: ids with >1 row, total rows, distinct full rows among them
SELECT count(*) dup_ids, sum(n) rows, max(n) max_copies FROM (SELECT idx, count(*) n FROM trees GROUP BY idx HAVING n>1);
SELECT count(*) distinct_full_rows_of_dup_ids FROM (SELECT DISTINCT * FROM trees WHERE idx IN (SELECT idx FROM trees GROUP BY idx HAVING count(*)>1));
SELECT count(*) distinct_full_rows FROM (SELECT DISTINCT * FROM trees);
.print ## where the duplicates sit physically: min rowid of first copies, rowid range of the earlier copy
SELECT min(r1), max(r1), min(r2), max(r2) FROM (SELECT min(rowid) r1, max(rowid) r2 FROM trees GROUP BY idx HAVING count(*)>1);
SELECT count(*) dup_first_copy_in_rows_1_6838 FROM (SELECT min(rowid) r1 FROM trees GROUP BY idx HAVING count(*)>1) WHERE r1<=6838;
.print ## rows 6839.. distinct idx
SELECT count(*), count(DISTINCT idx) FROM trees WHERE rowid>6838;
.print ## idx = rank(tree_id)-1 ?  (over distinct)
SELECT count(*) mismatches FROM (SELECT idx, tree_id, rank() OVER (ORDER BY tree_id)-1 rk FROM (SELECT DISTINCT idx, tree_id FROM trees)) WHERE idx<>rk;
.print ## physical order of rows 6839.. by idx: ascents/descents
SELECT sum(b.idx>a.idx) asc_, sum(b.idx<a.idx) desc_ FROM trees a JOIN trees b ON b.rowid=a.rowid+1 WHERE a.rowid>6838;
.print ## storage types per column
SELECT 'tree_dbh', typeof(tree_dbh), count(*) FROM trees GROUP BY 2 UNION ALL
SELECT 'stump_diam', typeof(stump_diam), count(*) FROM trees GROUP BY 2 UNION ALL
SELECT 'status', typeof(status), count(*) FROM trees GROUP BY 2 UNION ALL
SELECT 'health', typeof(health), count(*) FROM trees GROUP BY 2 UNION ALL
SELECT 'spc_latin', typeof(spc_latin), count(*) FROM trees GROUP BY 2 UNION ALL
SELECT 'spc_common', typeof(spc_common), count(*) FROM trees GROUP BY 2 UNION ALL
SELECT 'address', typeof(address), count(*) FROM trees GROUP BY 2 UNION ALL
SELECT 'zipcode', typeof(zipcode), count(*) FROM trees GROUP BY 2 UNION ALL
SELECT 'borocode', typeof(borocode), count(*) FROM trees GROUP BY 2 UNION ALL
SELECT 'boroname', typeof(boroname), count(*) FROM trees GROUP BY 2 UNION ALL
SELECT 'nta_name', typeof(nta_name), count(*) FROM trees GROUP BY 2 UNION ALL
SELECT 'state', typeof(state), count(*) FROM trees GROUP BY 2 UNION ALL
SELECT 'latitude', typeof(latitude), count(*) FROM trees GROUP BY 2 UNION ALL
SELECT 'longitude', typeof(longitude), count(*) FROM trees GROUP BY 2;
.print ## empty strings per text column
SELECT sum(status='') status, sum(health='') health, sum(spc_latin='') spc_latin, sum(spc_common='') spc_common, sum(address='') address,
       sum(boroname='') boroname, sum(nta_name='') nta_name, sum(state='') state FROM trees;
.print ## income_trees storage types
SELECT typeof(zipcode), typeof(Estimate_Total), typeof(Margin_of_Error_Total), typeof(Estimate_Median_income), typeof(Margin_of_Error_Median_income), typeof(Estimate_Mean_income), typeof(Margin_of_Error_Mean_income), count(*) FROM income_trees GROUP BY 1,2,3,4,5,6,7;
.print ## income_trees duplicates
SELECT count(*) dup_zips, sum(n) rows FROM (SELECT zipcode, count(*) n FROM income_trees GROUP BY 1 HAVING n>1);
SELECT count(*) distinct_full_rows FROM (SELECT DISTINCT * FROM income_trees);
SELECT rowid, * FROM income_trees WHERE zipcode IN (SELECT zipcode FROM income_trees GROUP BY 1 HAVING count(*)>1) ORDER BY zipcode, rowid;
.print ## income_trees zeros / negatives
SELECT sum(Estimate_Total=0) tot0, sum(Estimate_Median_income=0) med0, sum(Estimate_Mean_income=0) mean0, sum(Estimate_Median_income<0) medneg,
       sum(Margin_of_Error_Median_income<0) moe_neg, sum(Estimate_Mean_income<0) meanneg FROM (SELECT DISTINCT * FROM income_trees);
SELECT * FROM (SELECT DISTINCT * FROM income_trees) WHERE Estimate_Median_income<=0 OR Estimate_Mean_income<=0 OR Margin_of_Error_Median_income<0 ORDER BY zipcode;
.print ## joins: trees.zipcode -> income_trees
SELECT count(DISTINCT zipcode) tree_zips, sum(zipcode IN (SELECT zipcode FROM income_trees)) rows_matched, sum(zipcode NOT IN (SELECT zipcode FROM income_trees)) rows_unmatched, sum(zipcode IS NULL) null_zip, sum(zipcode=0) zero_zip FROM trees;
SELECT count(DISTINCT zipcode) tree_zips_unmatched FROM trees WHERE zipcode NOT IN (SELECT zipcode FROM income_trees);
SELECT count(*) income_zips_without_trees FROM (SELECT DISTINCT zipcode FROM income_trees WHERE zipcode NOT IN (SELECT zipcode FROM trees));
.print ## trees: borocode <-> boroname 1:1 ; nta_name in one borough
SELECT boroname, borocode, count(*) FROM trees GROUP BY 1,2 ORDER BY 2;
SELECT count(*) nta_multi_boro FROM (SELECT nta_name FROM trees GROUP BY 1 HAVING count(DISTINCT borocode)>1);
SELECT count(DISTINCT nta_name) ntas, count(DISTINCT spc_latin) latin, count(DISTINCT spc_common) common, count(DISTINCT address) addresses FROM trees;
.print ## spc_latin <-> spc_common 1:1 ?
SELECT count(*) FROM (SELECT spc_latin FROM trees GROUP BY 1 HAVING count(DISTINCT ifnull(spc_common,'<N>'))>1);
SELECT count(*) FROM (SELECT spc_common FROM trees GROUP BY 1 HAVING count(DISTINCT ifnull(spc_latin,'<N>'))>1);
.print ## zipcode in more than one borough
SELECT count(*) zips_multi_boro FROM (SELECT zipcode FROM trees GROUP BY 1 HAVING count(DISTINCT borocode)>1);
