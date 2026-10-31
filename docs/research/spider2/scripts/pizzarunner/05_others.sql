-- Out-of-scope modern_data tables: size and time columns, to judge whether any is event-shaped.
-- Run: sqlite3 -readonly data/spider2/modern_data.sqlite < docs/research/spider2/scripts/pizzarunner/05_others.sql
.headers on
.mode list
SELECT 'companies_dates' t, count(*) n, count(DISTINCT company_id) ids, min(date_joined) lo, max(date_joined) hi, min(year_founded) yf_lo, max(year_founded) yf_hi FROM companies_dates;
SELECT 'companies_funding' t, count(*), count(DISTINCT company_id), min(valuation), max(valuation) FROM companies_funding;
SELECT 'companies_industries' t, count(*), count(DISTINCT company_id), count(DISTINCT industry) FROM companies_industries;
SELECT 'trees' t, count(*), count(DISTINCT tree_id), count(DISTINCT zipcode) FROM trees;
SELECT 'income_trees' t, count(*), count(DISTINCT zipcode) FROM income_trees;
SELECT 'statistics' t, count(*), count(DISTINCT state), count(DISTINCT date), min(date), max(date) FROM statistics;
SELECT 'word_list' t, count(*), count(DISTINCT words) FROM word_list;
SELECT 'trees_columns' t, group_concat(name, ',') FROM pragma_table_info('trees');
