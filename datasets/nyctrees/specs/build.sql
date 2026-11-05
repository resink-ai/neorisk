-- NYC trees: events → source tables (refdata rebuild, DuckDB). Each source_row_duplicated adds
-- one more identical copy of its row.

-- table: trees
-- borocode is a function of boroname; state is the constant 'New York'.
WITH base AS (
    SELECT t.idx, CAST(t.ext_id AS BIGINT) AS tree_id, s.tree_dbh, s.stump_diam, s.status,
           s.health, sp.ext_id AS spc_latin, sp.spc_common, t.address, t.zipcode,
           CASE t.boroname WHEN 'Manhattan' THEN 1 WHEN 'Bronx' THEN 2 WHEN 'Brooklyn' THEN 3
                           WHEN 'Queens' THEN 4 WHEN 'Staten Island' THEN 5 END AS borocode,
           t.boroname, t.nta_name, 'New York' AS state, t.latitude, t.longitude, t.ext_id
    FROM trees t
    LEFT JOIN trees_snapshot s ON s.tree_id = t.tree_key
    LEFT JOIN species sp ON sp.species_key = t.species)
SELECT * EXCLUDE (ext_id) FROM base
UNION ALL
SELECT b.* EXCLUDE (ext_id) FROM source_row_duplicated d JOIN base b USING (ext_id)
WHERE d.source_table = 'trees';

-- table: income_trees
WITH base AS (
    SELECT CAST(z.ext_id AS BIGINT) AS zipcode, s.estimate_total AS Estimate_Total,
           s.moe_total AS Margin_of_Error_Total, s.estimate_median_income AS Estimate_Median_income,
           s.moe_median_income AS Margin_of_Error_Median_income,
           s.estimate_mean_income AS Estimate_Mean_income,
           s.moe_mean_income AS Margin_of_Error_Mean_income, z.ext_id
    FROM zip_incomes z LEFT JOIN zip_incomes_snapshot s ON s.zipcode = z.zip_key)
SELECT * EXCLUDE (ext_id) FROM base
UNION ALL
SELECT b.* EXCLUDE (ext_id) FROM source_row_duplicated d JOIN base b USING (ext_id)
WHERE d.source_table = 'income_trees';
