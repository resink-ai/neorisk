-- Run: sqlite3 -readonly data/spider2/modern_data.sqlite < docs/research/spider2/scripts/trees/03_quirks.sql
-- Over the 683,788 distinct trees (rowid > 6838) unless noted.
.headers on
.mode list
.print ## status x health NULL x species NULL
SELECT status, health IS NULL h_null, spc_latin IS NULL s_null, count(*) FROM trees WHERE rowid>6838 GROUP BY 1,2,3 ORDER BY 1,2,3;
.print ## health values
SELECT health, count(*) FROM trees WHERE rowid>6838 GROUP BY 1 ORDER BY 2 DESC;
.print ## dbh / stump_diam by status: zero counts, min, max
SELECT status, sum(tree_dbh=0) dbh0, min(tree_dbh), max(tree_dbh), sum(stump_diam=0) stump0, min(stump_diam), max(stump_diam), count(*) FROM trees WHERE rowid>6838 GROUP BY 1;
.print ## extreme dbh (> 100 inches)
SELECT count(*) dbh_gt_100, max(tree_dbh) FROM trees WHERE rowid>6838 AND tree_dbh>100;
.print ## lat/long ranges and printed decimals
SELECT min(latitude), max(latitude), min(longitude), max(longitude) FROM trees WHERE rowid>6838;
SELECT length(CAST(latitude AS TEXT)) - instr(CAST(latitude AS TEXT), '.') lat_decimals, count(*) FROM trees WHERE rowid>6838 GROUP BY 1 ORDER BY 1;
.print ## same (lat, long) shared by several trees
SELECT count(*) shared_points, sum(n) trees_on_them, max(n) FROM (SELECT latitude, longitude, count(*) n FROM trees WHERE rowid>6838 GROUP BY 1,2 HAVING n>1);
.print ## NTAs in more than one borough (rows per borough)
SELECT nta_name, boroname, count(*) FROM trees WHERE rowid>6838 AND nta_name IN (SELECT nta_name FROM trees GROUP BY 1 HAVING count(DISTINCT borocode)>1) GROUP BY 1,2 ORDER BY 1, 3 DESC;
.print ## zipcodes in more than one borough
SELECT zipcode, boroname, count(*) FROM trees WHERE rowid>6838 AND zipcode IN (SELECT zipcode FROM trees GROUP BY 1 HAVING count(DISTINCT borocode)>1) GROUP BY 1,2 ORDER BY 1, 3 DESC;
.print ## tree zipcodes not in income_trees
SELECT zipcode, boroname, count(*) FROM trees WHERE rowid>6838 AND zipcode NOT IN (SELECT zipcode FROM income_trees) GROUP BY 1,2 ORDER BY 1;
.print ## idx vs tree_id order (rows in idx order): ascents/descents of tree_id
SELECT sum(b.tree_id>a.tree_id) asc_, sum(b.tree_id<a.tree_id) desc_ FROM trees a JOIN trees b ON b.rowid=a.rowid+1 WHERE a.rowid>6838;
.print ## physical order of rows 6839.. by borough runs (number of borough changes)
SELECT sum(b.borocode<>a.borocode) boro_changes FROM trees a JOIN trees b ON b.rowid=a.rowid+1 WHERE a.rowid>6838;
.print ## text oddities: untrimmed, lower/upper address, double spaces
SELECT sum(address<>trim(address)) addr_untrim, sum(address<>upper(address)) addr_not_upper, sum(instr(address,'  ')>0) addr_dblspace,
       sum(spc_common<>lower(spc_common)) common_not_lower, sum(nta_name<>trim(nta_name)) nta_untrim FROM trees WHERE rowid>6838;
.print ## top species
SELECT spc_common, count(*) FROM trees WHERE rowid>6838 GROUP BY 1 ORDER BY 2 DESC LIMIT 10;
.print ## income_trees margin_of_error totals for the zero-pop zips (sentinel 11) and other MOE stats
SELECT Margin_of_Error_Total, count(*) FROM (SELECT DISTINCT * FROM income_trees) WHERE Estimate_Total=0 GROUP BY 1;
SELECT min(Estimate_Total), max(Estimate_Total), min(NULLIF(Estimate_Median_income,0)), max(Estimate_Median_income), max(Estimate_Mean_income) FROM (SELECT DISTINCT * FROM income_trees);
SELECT count(*) median_250001 FROM (SELECT DISTINCT * FROM income_trees) WHERE Estimate_Median_income>=250000;
SELECT sum(Estimate_Mean_income < Estimate_Median_income) mean_lt_median FROM (SELECT DISTINCT * FROM income_trees) WHERE Estimate_Total>0;
.print ## income_trees physical order (zip ascents/descents)
SELECT sum(b.zipcode>a.zipcode) asc_, sum(b.zipcode<a.zipcode) desc_ FROM income_trees a JOIN income_trees b ON b.rowid=a.rowid+1;
SELECT min(rowid), max(rowid) FROM income_trees WHERE rowid IN (SELECT min(rowid) FROM income_trees GROUP BY zipcode HAVING count(*)>1);
.print ## income_trees: implausible medians (< 10000) and zero MOE on non-zero estimates
SELECT * FROM (SELECT DISTINCT * FROM income_trees) WHERE (Estimate_Median_income BETWEEN 1 AND 9999) OR (Estimate_Total>0 AND Margin_of_Error_Median_income=0);
.print ## income_trees: rows 1-2 prepended copies? base = rows 3..220
SELECT count(*) base_rows, count(DISTINCT zipcode) base_zips FROM income_trees WHERE rowid>=3;
SELECT sum(b.zipcode>a.zipcode) asc_, sum(b.zipcode<a.zipcode) desc_, sum(b.zipcode=a.zipcode) eq FROM income_trees a JOIN income_trees b ON b.rowid=a.rowid+1 WHERE a.rowid>=3;
SELECT a.rowid, a.zipcode, b.zipcode FROM income_trees a JOIN income_trees b ON b.rowid=a.rowid+1 WHERE a.rowid>=3 AND b.zipcode<=a.zipcode;
