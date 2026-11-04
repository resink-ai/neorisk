-- DuckDB: generate the four ztbl helpers and diff them with the source (attached read-only).
ATTACH '../../../../../data/spider2/EntertainmentAgency.sqlite' AS src (TYPE sqlite, READ_ONLY);
CREATE TEMP TABLE g_days AS SELECT strftime(d, '%Y-%m-%d') AS DateField FROM generate_series(DATE '2017-01-01', DATE '2020-01-01', INTERVAL 1 DAY) t(d);
CREATE TEMP TABLE g_weeks AS SELECT strftime(d, '%Y-%m-%d') AS WeekStart, strftime(d + INTERVAL 6 DAY, '%Y-%m-%d') AS WeekEnd FROM generate_series(DATE '2017-01-01', DATE '2019-12-22', INTERVAL 7 DAY) t(d);
CREATE TEMP TABLE g_months AS SELECT strftime(d, '%B %Y') AS MonthYear, year(d)::BIGINT AS YearNumber, month(d)::BIGINT AS MonthNumber, strftime(d, '%Y-%m-%d') AS MonthStart,
  strftime(last_day(d), '%Y-%m-%d') AS MonthEnd,
  (month(d)=1)::BIGINT AS January, (month(d)=2)::BIGINT AS February, (month(d)=3)::BIGINT AS March, (month(d)=4)::BIGINT AS April, (month(d)=5)::BIGINT AS May, (month(d)=6)::BIGINT AS June,
  (month(d)=7)::BIGINT AS July, (month(d)=8)::BIGINT AS August, (month(d)=9)::BIGINT AS September, (month(d)=10)::BIGINT AS October, (month(d)=11)::BIGINT AS November, (month(d)=12)::BIGINT AS December
  FROM generate_series(DATE '2017-01-01', DATE '2019-12-01', INTERVAL 1 MONTH) t(d);
CREATE TEMP TABLE g_skip AS SELECT range::BIGINT AS LabelCount FROM range(1, 61);
SELECT 'ztblDays' t, (SELECT count(*) FROM (SELECT * FROM g_days EXCEPT ALL SELECT DateField FROM src.ztblDays)) a, (SELECT count(*) FROM (SELECT DateField FROM src.ztblDays EXCEPT ALL SELECT * FROM g_days)) b
UNION ALL SELECT 'ztblWeeks', (SELECT count(*) FROM (SELECT * FROM g_weeks EXCEPT ALL SELECT WeekStart, WeekEnd FROM src.ztblWeeks)), (SELECT count(*) FROM (SELECT WeekStart, WeekEnd FROM src.ztblWeeks EXCEPT ALL SELECT * FROM g_weeks))
UNION ALL SELECT 'ztblMonths', (SELECT count(*) FROM (SELECT * FROM g_months EXCEPT ALL SELECT * FROM src.ztblMonths)), (SELECT count(*) FROM (SELECT * FROM src.ztblMonths EXCEPT ALL SELECT * FROM g_months))
UNION ALL SELECT 'ztblSkipLabels', (SELECT count(*) FROM (SELECT * FROM g_skip EXCEPT ALL SELECT * FROM src.ztblSkipLabels)), (SELECT count(*) FROM (SELECT * FROM src.ztblSkipLabels EXCEPT ALL SELECT * FROM g_skip));
