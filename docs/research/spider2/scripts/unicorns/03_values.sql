-- Run: sqlite3 -readonly data/spider2/modern_data.sqlite < docs/research/spider2/scripts/unicorns/03_values.sql
-- Value quirks of companies_*; all over the 1074 distinct companies (rows 12..) unless noted.
.headers on
.mode list
.print ## valuation: min, max, distinct, multiples of 1e9, of 1e8
SELECT min(valuation), max(valuation), count(DISTINCT valuation) d, sum(valuation % 1000000000 = 0) mult_1e9, sum(valuation % 100000000 = 0) mult_1e8, count(*) n FROM companies_funding WHERE rowid>=12;
.print ## valuation top values
SELECT valuation, count(*) FROM companies_funding WHERE rowid>=12 GROUP BY 1 ORDER BY 2 DESC LIMIT 6;
.print ## funding: zeros, multiples of 1e6, min, max
SELECT sum(funding=0) zero, sum(funding % 1000000 = 0) mult_1e6, sum(funding % 1000000000 = 0 AND funding>0) mult_1e9, min(NULLIF(funding,0)) min_pos, max(funding) mx FROM companies_funding WHERE rowid>=12;
.print ## funding > valuation
SELECT count(*) FROM companies_funding WHERE rowid>=12 AND funding > valuation;
.print ## select_investors: NULL, empty, wrapped in double quotes, contains comma, contains ', ' only, leading/trailing space
SELECT sum(select_investors IS NULL) nul, sum(select_investors='') empty,
       sum(select_investors GLOB '"*"') dq_wrapped, sum(instr(select_investors, ',')>0) has_comma,
       sum(select_investors GLOB '"*"' AND instr(select_investors, ',')=0) dq_no_comma,
       sum(NOT select_investors GLOB '"*"' AND instr(select_investors, ',')>0) comma_no_dq,
       sum(select_investors <> trim(select_investors)) untrimmed,
       sum(instr(select_investors, ',,')>0) double_comma, sum(instr(select_investors, ', ,')>0) empty_item
FROM companies_funding WHERE rowid>=12;
.print ## select_investors item count (commas+1), distribution
SELECT length(select_investors)-length(replace(select_investors, ',', ''))+1 items, count(*) FROM companies_funding WHERE rowid>=12 AND select_investors IS NOT NULL GROUP BY 1;
.print ## the NULL investor row
SELECT rowid, * FROM companies_funding WHERE select_investors IS NULL;
.print ## industries: distinct values, untrimmed, quoted
SELECT count(DISTINCT industry) d, sum(industry GLOB '"*"') dq, sum(industry<>trim(industry)) untrimmed FROM companies_industries;
SELECT industry, count(*) n FROM companies_industries WHERE rowid>=12 GROUP BY 1 ORDER BY 2 DESC, 1;
.print ## case variants of industries
SELECT lower(industry), count(DISTINCT industry) FROM companies_industries GROUP BY 1 HAVING count(DISTINCT industry)>1;
.print ## year_founded vs year joined
SELECT sum(year_founded > CAST(substr(date_joined,1,4) AS INT)) founded_after_join, sum(year_founded = CAST(substr(date_joined,1,4) AS INT)) same_year,
       min(CAST(substr(date_joined,1,4) AS INT) - year_founded) min_gap, max(CAST(substr(date_joined,1,4) AS INT) - year_founded) max_gap
FROM companies_dates WHERE rowid>=12;
SELECT rowid, * FROM companies_dates WHERE rowid>=12 AND year_founded > CAST(substr(date_joined,1,4) AS INT);
.print ## joins per year
SELECT substr(date_joined,1,4) y, count(*) FROM companies_dates WHERE rowid>=12 GROUP BY 1 ORDER BY 1;
.print ## distinct join dates, max companies per date
SELECT count(DISTINCT date_joined) dates, max(c) max_per_date FROM (SELECT date_joined, count(*) c FROM companies_dates WHERE rowid>=12 GROUP BY 1);
.print ## weekday of date_joined (0=Sun)
SELECT strftime('%w', substr(date_joined,1,10)) dow, count(*) FROM companies_dates WHERE rowid>=12 GROUP BY 1;
.print ## year_founded distribution, deciles-ish
SELECT CASE WHEN year_founded<2000 THEN '<2000' ELSE CAST(year_founded AS TEXT) END y, count(*) FROM companies_dates WHERE rowid>=12 GROUP BY 1 ORDER BY 1;
.print ## select_investors with ',,' or 4 items
SELECT rowid, company_id, select_investors FROM companies_funding WHERE rowid>=12 AND (instr(select_investors, ',,')>0 OR length(select_investors)-length(replace(select_investors, ',', ''))=3);
.print ## funding = 0 rows (likely 'Unknown' in the original) and funding > valuation rows
SELECT rowid, company_id, valuation, funding FROM companies_funding WHERE rowid>=12 AND (funding=0 OR funding>valuation);
