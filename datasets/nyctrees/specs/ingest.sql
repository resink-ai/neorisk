-- NYC trees: source tables → events (refdata ingest). The source has no time: T0 = N =
-- 2015-01-01 00:00:00 UTC (a rule). Of identical rows the last copy by rowid is the entity; each
-- earlier copy is one source_row_duplicated.

-- entity: species
SELECT spc_latin AS ext_id, spc_common, '2015-01-01 00:00:00' AS created_at
FROM (SELECT DISTINCT spc_latin, spc_common FROM trees WHERE spc_latin IS NOT NULL)
ORDER BY spc_latin;

-- entity: trees
SELECT CAST(tree_id AS TEXT) AS ext_id, idx, spc_latin AS species, address, zipcode, boroname,
       nta_name, latitude, longitude, '2015-01-01 00:00:00' AS created_at
FROM (SELECT *, row_number() OVER (PARTITION BY tree_id ORDER BY rowid DESC) AS k FROM trees)
WHERE k = 1 ORDER BY tree_id;

-- entity: zip_incomes
SELECT CAST(zipcode AS TEXT) AS ext_id, '2015-01-01 00:00:00' AS created_at
FROM (SELECT DISTINCT zipcode FROM income_trees) ORDER BY zipcode;

-- event: trees_snapshot owner=tree_id ord=idx
SELECT '2015-01-01 00:00:00' AS event_time, CAST(tree_id AS TEXT) AS tree_id, tree_dbh,
       stump_diam, status, health, idx
FROM (SELECT *, row_number() OVER (PARTITION BY tree_id ORDER BY rowid DESC) AS k FROM trees)
WHERE k = 1 ORDER BY idx;

-- event: zip_incomes_snapshot owner=zipcode
SELECT '2015-01-01 00:00:00' AS event_time, CAST(zipcode AS TEXT) AS zipcode,
       Estimate_Total AS estimate_total, Margin_of_Error_Total AS moe_total,
       Estimate_Median_income AS estimate_median_income,
       Margin_of_Error_Median_income AS moe_median_income,
       Estimate_Mean_income AS estimate_mean_income,
       Margin_of_Error_Mean_income AS moe_mean_income
FROM (SELECT *, row_number() OVER (PARTITION BY zipcode ORDER BY rowid DESC) AS k
      FROM income_trees)
WHERE k = 1 ORDER BY zipcode;

-- event: source_row_duplicated owner=source_table ord=src_rowid
SELECT '2015-01-01 00:00:00' AS event_time, source_table, ext_id, src_rowid
FROM (SELECT 'trees' AS source_table, CAST(tree_id AS TEXT) AS ext_id, rowid AS src_rowid,
             row_number() OVER (PARTITION BY tree_id ORDER BY rowid DESC) AS k FROM trees
      UNION ALL
      SELECT 'income_trees', CAST(zipcode AS TEXT), rowid,
             row_number() OVER (PARTITION BY zipcode ORDER BY rowid DESC) FROM income_trees)
WHERE k > 1 ORDER BY source_table DESC, src_rowid;
