-- Run: sqlite3 -readonly data/spider2/modern_data.sqlite < docs/research/spider2/scripts/modern_misc/01_inventory.sql
.headers on
.mode list
.print ## statistics: counts, states, dates
SELECT count(*) n, count(DISTINCT state) states, count(DISTINCT date) dates, min(date), max(date), count(DISTINCT date||'|'||state) keys FROM statistics;
SELECT state, count(*) n, count(DISTINCT date) d, min(date), max(date) FROM statistics GROUP BY 1;
.print ## statistics: storage types, date formats
SELECT typeof(date), typeof(state), typeof(total_cases), typeof(total_deaths), length(date), count(*) FROM statistics GROUP BY 1,2,3,4,5;
SELECT substr(date, 11) suffix, count(*) FROM statistics GROUP BY 1;
.print ## statistics: duplicate (date, state) keys and full-row duplicates
SELECT count(*) dup_keys, sum(n) rows FROM (SELECT date, state, count(*) n FROM statistics GROUP BY 1,2 HAVING n>1);
SELECT count(*) distinct_full_rows FROM (SELECT DISTINCT * FROM statistics);
SELECT rowid, * FROM statistics WHERE (date, state) IN (SELECT date, state FROM statistics GROUP BY 1,2 HAVING count(*)>1) ORDER BY state, date, rowid LIMIT 40;
.print ## statistics: missing days per state (gaps in the daily calendar)
WITH s AS (SELECT DISTINCT state, substr(date,1,10) d FROM statistics),
g AS (SELECT state, d, lag(d) OVER (PARTITION BY state ORDER BY d) p FROM s)
SELECT state, sum(julianday(d)-julianday(p) > 1) gaps, max(julianday(d)-julianday(p)) max_gap_days FROM g GROUP BY 1;
.print ## statistics: cumulative monotonicity (distinct rows, by state and date)
WITH s AS (SELECT DISTINCT * FROM statistics),
g AS (SELECT state, date, total_cases c, total_deaths dd, lag(total_cases) OVER (PARTITION BY state ORDER BY date) pc, lag(total_deaths) OVER (PARTITION BY state ORDER BY date) pd FROM s)
SELECT state, sum(c<pc) case_drops, sum(dd<pd) death_drops, sum(c=pc) case_flat, min(c), max(c), max(dd) FROM g GROUP BY 1;
WITH s AS (SELECT DISTINCT * FROM statistics),
g AS (SELECT state, date, total_cases c, total_deaths dd, lag(total_cases) OVER (PARTITION BY state ORDER BY date) pc, lag(total_deaths) OVER (PARTITION BY state ORDER BY date) pd FROM s)
SELECT * FROM g WHERE c<pc OR dd<pd;
.print ## statistics: physical order
SELECT sum(b.date>a.date) asc_, sum(b.date<a.date) desc_, sum(b.date=a.date) eq FROM statistics a JOIN statistics b ON b.rowid=a.rowid+1;
SELECT rowid, * FROM statistics WHERE rowid<=6 OR rowid>=(SELECT max(rowid)-3 FROM statistics);
.print ## word_list: counts, NULL, empty, distinct, duplicates
SELECT count(*) n, count(words) nonnull, sum(words='') empty, count(DISTINCT words) d, sum(words<>trim(words)) untrimmed FROM word_list;
SELECT count(*) dup_words, sum(n) rows, max(n) FROM (SELECT words, count(*) n FROM word_list GROUP BY 1 HAVING n>1);
SELECT min(rowid), max(rowid) FROM word_list WHERE rowid IN (SELECT min(rowid) FROM word_list GROUP BY words HAVING count(*)>1);
SELECT count(DISTINCT lower(words)) d_lower FROM word_list;
.print ## word_list: character classes
SELECT sum(words GLOB '*[^a-z]*') non_lower, sum(words GLOB '*[A-Z]*') has_upper, sum(words GLOB '*[0-9]*') has_digit, sum(words GLOB '*[^a-zA-Z0-9]*') has_other FROM word_list;
SELECT typeof(words), count(*) FROM word_list GROUP BY 1;
SELECT length(words) len, count(*) FROM word_list GROUP BY 1 ORDER BY 1 LIMIT 40;
.print ## word_list: physical order (rows after the duplicate block)
SELECT sum(b.words>a.words) asc_, sum(b.words<a.words) desc_, sum(b.words=a.words) eq FROM word_list a JOIN word_list b ON b.rowid=a.rowid+1;
SELECT rowid, words FROM word_list WHERE rowid<=5 OR rowid>=(SELECT max(rowid)-2 FROM word_list);
