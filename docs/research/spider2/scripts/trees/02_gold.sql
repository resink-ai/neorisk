-- Run: sqlite3 -readonly data/spider2/modern_data.sqlite < docs/research/spider2/scripts/trees/02_gold.sql
-- Readings of local040 and local041 against the gold CSVs (no gold SQL exists).
-- local040 gold: _a Queens 250364 / Brooklyn 175358 / SI 105318, avg 79366.738418 / 73555.190988 / 94029.327834
--                _b Queens 256065 / Brooklyn 186668 / SI 106374, avg 79312.5723 / 73675.9770 / 94029.3278
--                _c Queens 252846 / Brooklyn 177132 / SI 106374, avg 79366.738417851182 / 73555.190987512138 / 94029.327833869179
--                _d avg only: 79312.572258 / 73675.976969 / 94029.327834
-- local041 gold: _a 78.1473, _b 82.649376
.headers on
.mode list
.print ## L040 R1: raw trees INNER JOIN raw income_trees (both duplicate sets fan out), med>0 AND mean>0
SELECT t.boroname, count(*) n, round(avg(i.Estimate_Mean_income), 6) avg_mean FROM trees t JOIN income_trees i ON i.zipcode=t.zipcode
 WHERE i.Estimate_Median_income>0 AND i.Estimate_Mean_income>0 AND t.boroname IS NOT NULL AND t.boroname<>'' GROUP BY 1 ORDER BY 2 DESC LIMIT 3;
.print ## L040 R2: raw trees JOIN DISTINCT income_trees
SELECT t.boroname, count(*) n, round(avg(i.Estimate_Mean_income), 6) avg_mean FROM trees t JOIN (SELECT DISTINCT * FROM income_trees) i ON i.zipcode=t.zipcode
 WHERE i.Estimate_Median_income>0 AND i.Estimate_Mean_income>0 GROUP BY 1 ORDER BY 2 DESC LIMIT 3;
.print ## L040 R3: DISTINCT trees JOIN DISTINCT income_trees
SELECT t.boroname, count(*) n, round(avg(i.Estimate_Mean_income), 6) avg_mean FROM (SELECT DISTINCT * FROM trees) t JOIN (SELECT DISTINCT * FROM income_trees) i ON i.zipcode=t.zipcode
 WHERE i.Estimate_Median_income>0 AND i.Estimate_Mean_income>0 GROUP BY 1 ORDER BY 2 DESC LIMIT 3;
.print ## L040 R4: DISTINCT trees JOIN raw income_trees
SELECT t.boroname, count(*) n, round(avg(i.Estimate_Mean_income), 6) avg_mean FROM (SELECT DISTINCT * FROM trees) t JOIN income_trees i ON i.zipcode=t.zipcode
 WHERE i.Estimate_Median_income>0 AND i.Estimate_Mean_income>0 GROUP BY 1 ORDER BY 2 DESC LIMIT 3;
.print ## L040 R5: all trees per borough (no income filter), raw and distinct
SELECT boroname, count(*) raw, count(DISTINCT idx) dist FROM trees GROUP BY 1 ORDER BY 2 DESC;
.print ## L040 R6: avg of mean income over DISTINCT zip rows per borough (zip-level average, zip borough from trees)
SELECT b, count(*) zips, round(avg(m), 6) avg_mean FROM (SELECT DISTINCT t.boroname b, i.zipcode z, i.Estimate_Mean_income m FROM trees t JOIN income_trees i ON i.zipcode=t.zipcode WHERE i.Estimate_Median_income>0 AND i.Estimate_Mean_income>0) GROUP BY 1 ORDER BY 1;
.print ## L041 R1: raw rows, Bronx, health='Good' / all Bronx rows
SELECT round(100.0*sum(health='Good')/count(*), 6) pct, count(*) n FROM trees WHERE boroname='Bronx';
.print ## L041 R2: distinct trees
SELECT round(100.0*sum(health='Good')/count(*), 6) pct, count(*) n FROM (SELECT DISTINCT * FROM trees) WHERE boroname='Bronx';
.print ## L041 R3: raw, denominator = rows with non-NULL health
SELECT round(100.0*sum(health='Good')/count(health), 6) pct, count(health) n FROM trees WHERE boroname='Bronx';
.print ## L041 R4: distinct, denominator = non-NULL health
SELECT round(100.0*sum(health='Good')/count(health), 6) pct FROM (SELECT DISTINCT * FROM trees) WHERE boroname='Bronx';
.print ## L041 R5: status='Alive' only, raw and distinct
SELECT round(100.0*sum(health='Good')/count(*), 6) pct FROM trees WHERE boroname='Bronx' AND status='Alive';
SELECT round(100.0*sum(health='Good')/count(*), 6) pct FROM (SELECT DISTINCT * FROM trees) WHERE boroname='Bronx' AND status='Alive';
