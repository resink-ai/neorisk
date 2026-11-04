-- Unicorn companies: source tables → events (refdata ingest). Each table's distinct rows are
-- the data; a row with an identical copy at a later rowid is a Spider2 duplicate (rows 1-11).
-- N = 2022-04-05 00:00:00, the last join: the snapshot and the duplicate markers (a rule).

-- entity: companies
SELECT CAST(d.company_id AS TEXT) AS ext_id, i.industry, d.year_founded,
       iso_time(d.date_joined, '%Y-%m-%dT%H:%M:%S.%f') AS created_at
FROM (SELECT DISTINCT * FROM companies_dates) d
JOIN (SELECT DISTINCT * FROM companies_industries) i USING (company_id)
ORDER BY d.company_id;

-- event: companies_snapshot owner=company_id
SELECT '2022-04-05 00:00:00' AS event_time, CAST(company_id AS TEXT) AS company_id, valuation,
       funding, select_investors
FROM (SELECT DISTINCT * FROM companies_funding) ORDER BY company_id;

-- event: source_row_duplicated owner=company_id ord=src_rowid
SELECT '2022-04-05 00:00:00' AS event_time, CAST(company_id AS TEXT) AS company_id, src_table,
       src_rowid
FROM (SELECT 'companies_funding' AS src_table, a.rowid AS src_rowid, a.company_id
      FROM companies_funding a WHERE EXISTS (
          SELECT 1 FROM companies_funding b WHERE b.rowid > a.rowid
          AND b.company_id IS a.company_id AND b.valuation IS a.valuation
          AND b.funding IS a.funding AND b.select_investors IS a.select_investors)
      UNION ALL
      SELECT 'companies_dates', a.rowid, a.company_id FROM companies_dates a WHERE EXISTS (
          SELECT 1 FROM companies_dates b WHERE b.rowid > a.rowid
          AND b.company_id IS a.company_id AND b.date_joined IS a.date_joined
          AND b.year_founded IS a.year_founded)
      UNION ALL
      SELECT 'companies_industries', a.rowid, a.company_id FROM companies_industries a
      WHERE EXISTS (
          SELECT 1 FROM companies_industries b WHERE b.rowid > a.rowid
          AND b.company_id IS a.company_id AND b.industry IS a.industry))
ORDER BY src_table, src_rowid;
