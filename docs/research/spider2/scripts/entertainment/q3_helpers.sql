-- name: days_generated
-- ztblDays = every date from 2017-01-01 to 2020-01-01 inclusive
WITH RECURSIVE d(x) AS (SELECT '2017-01-01' UNION ALL SELECT date(x,'+1 day') FROM d WHERE x < '2020-01-01')
SELECT (SELECT count(*) FROM d) gen, (SELECT count(*) FROM (SELECT x FROM d EXCEPT SELECT DateField FROM ztblDays)) gen_minus_src, (SELECT count(*) FROM (SELECT DateField FROM ztblDays EXCEPT SELECT x FROM d)) src_minus_gen;
-- name: weeks_generated
-- ztblWeeks = Sunday-to-Saturday weeks, WeekStart from 2017-01-01 (a Sunday) for 156 weeks
WITH RECURSIVE w(s) AS (SELECT '2017-01-01' UNION ALL SELECT date(s,'+7 day') FROM w WHERE s < '2019-12-22'),
g AS (SELECT s AS WeekStart, date(s,'+6 day') AS WeekEnd FROM w)
SELECT strftime('%w','2017-01-01') dow_first, (SELECT count(*) FROM g) gen, (SELECT count(*) FROM (SELECT * FROM g EXCEPT SELECT * FROM ztblWeeks)) gen_minus_src, (SELECT count(*) FROM (SELECT * FROM ztblWeeks EXCEPT SELECT * FROM g)) src_minus_gen;
-- name: months_generated
WITH RECURSIVE m(s) AS (SELECT '2017-01-01' UNION ALL SELECT date(s,'+1 month') FROM m WHERE s < '2019-12-01'),
names(n, nm) AS (VALUES (1,'January'),(2,'February'),(3,'March'),(4,'April'),(5,'May'),(6,'June'),(7,'July'),(8,'August'),(9,'September'),(10,'October'),(11,'November'),(12,'December')),
g AS (SELECT nm || ' ' || strftime('%Y', s) MonthYear, CAST(strftime('%Y', s) AS INT) YearNumber, CAST(strftime('%m', s) AS INT) MonthNumber, s MonthStart, date(s,'+1 month','-1 day') MonthEnd,
  (n=1) January, (n=2) February, (n=3) March, (n=4) April, (n=5) May, (n=6) June, (n=7) July, (n=8) August, (n=9) September, (n=10) October, (n=11) November, (n=12) December
  FROM m JOIN names ON n = CAST(strftime('%m', s) AS INT))
SELECT (SELECT count(*) FROM g) gen, (SELECT count(*) FROM (SELECT * FROM g EXCEPT SELECT * FROM ztblMonths)) gen_minus_src, (SELECT count(*) FROM (SELECT * FROM ztblMonths EXCEPT SELECT * FROM g)) src_minus_gen;
-- name: months_sample
SELECT * FROM ztblMonths LIMIT 3;
-- name: skiplabels_generated
WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x < 60)
SELECT (SELECT count(*) FROM (SELECT x FROM n EXCEPT SELECT LabelCount FROM ztblSkipLabels)) gen_minus_src, (SELECT count(*) FROM (SELECT LabelCount FROM ztblSkipLabels EXCEPT SELECT x FROM n)) src_minus_gen;
-- name: helpers_cover_engagements
SELECT sum(StartDate BETWEEN '2017-01-01' AND '2020-01-01') starts_in_days, count(*) FROM Engagements;
