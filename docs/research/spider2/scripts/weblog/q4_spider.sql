-- Spider2 questions on db `log`: one reading each, with the tie-break among equal stamps made explicit.
-- "natural" = ORDER BY stamp only (SQLite then keeps scan order = rowid among ties, on this unindexed file).
-- name: local329
-- sessions with /regist/input followed (later stamp, or same stamp and later row) by /regist/confirm
SELECT count(DISTINCT i.session) n FROM form_log i JOIN form_log c ON c.session=i.session
WHERE i.path='/regist/input' AND c.path='/regist/confirm' AND (c.stamp > i.stamp OR (c.stamp = i.stamp AND c.rowid > i.rowid));
-- name: local330_natural
WITH r AS (SELECT session, path,
   row_number() OVER (PARTITION BY session ORDER BY stamp) f, row_number() OVER (PARTITION BY session ORDER BY stamp DESC) l FROM activity_log),
 p AS (SELECT session, path FROM r WHERE f=1 UNION SELECT session, path FROM r WHERE l=1)
SELECT path, count(DISTINCT session) n FROM p GROUP BY path ORDER BY n DESC, path;
-- name: local330_rowid_asc
-- first = (stamp, rowid) smallest; last = (stamp DESC, rowid ASC): ties broken by the earlier row both ways
WITH r AS (SELECT session, path,
   row_number() OVER (PARTITION BY session ORDER BY stamp, rowid) f, row_number() OVER (PARTITION BY session ORDER BY stamp DESC, rowid) l FROM activity_log),
 p AS (SELECT session, path FROM r WHERE f=1 UNION SELECT session, path FROM r WHERE l=1)
SELECT path, count(DISTINCT session) n FROM p GROUP BY path ORDER BY n DESC, path;
-- name: local330_strict_order
-- first = smallest (stamp, rowid); last = largest (stamp, rowid)
WITH r AS (SELECT session, path,
   row_number() OVER (PARTITION BY session ORDER BY stamp, rowid) f, row_number() OVER (PARTITION BY session ORDER BY stamp DESC, rowid DESC) l FROM activity_log),
 p AS (SELECT session, path FROM r WHERE f=1 UNION SELECT session, path FROM r WHERE l=1)
SELECT path, count(DISTINCT session) n FROM p GROUP BY path ORDER BY n DESC, path;
-- name: local331_natural
WITH s AS (SELECT session, path, lead(path,1) OVER w p1, lead(path,2) OVER w p2 FROM activity_log WINDOW w AS (PARTITION BY session ORDER BY stamp))
SELECT p2 third_page, count(*) n FROM s WHERE path='/detail' AND p1='/detail' AND p2 IS NOT NULL GROUP BY p2 ORDER BY n DESC, p2 LIMIT 3;
-- name: local331_rowid_desc
WITH s AS (SELECT session, path, lead(path,1) OVER w p1, lead(path,2) OVER w p2 FROM activity_log WINDOW w AS (PARTITION BY session ORDER BY stamp, rowid DESC))
SELECT p2 third_page, count(*) n FROM s WHERE path='/detail' AND p1='/detail' AND p2 IS NOT NULL GROUP BY p2 ORDER BY n DESC, p2 LIMIT 3;
-- name: local331_dedup
-- same on DISTINCT rows (one row per (session, stamp, path))
WITH d AS (SELECT DISTINCT session, stamp, path FROM activity_log),
 s AS (SELECT session, path, lead(path,1) OVER w p1, lead(path,2) OVER w p2 FROM d WINDOW w AS (PARTITION BY session ORDER BY stamp, path))
SELECT p2 third_page, count(*) n FROM s WHERE path='/detail' AND p1='/detail' AND p2 IS NOT NULL GROUP BY p2 ORDER BY n DESC, p2 LIMIT 3;
-- name: local358_by_reference_year
-- age = reference year - birth year (no birthday adjustment) over all 320 rows, for several reference years
WITH y(ref) AS (VALUES (2016),(2017),(2018),(2019),(2020),(2021),(2022),(2023),(2024),(2025)),
 a AS (SELECT ref, ref - CAST(substr(birth_date,1,4) AS INT) age FROM mst_users, y)
SELECT ref, sum(age BETWEEN 20 AND 29) s20, sum(age BETWEEN 30 AND 39) s30, sum(age BETWEEN 40 AND 49) s40,
       sum(age BETWEEN 50 AND 59) s50, sum(age<20 OR age>=60) others FROM a GROUP BY ref ORDER BY ref;
-- name: local358_exact_age_on_date
-- calendar-exact age on a reference date, over all 320 rows
WITH d(ref) AS (VALUES ('2017-01-01'),('2024-01-01'),('2024-06-30'),('2024-10-01'),('2025-01-01')),
 a AS (SELECT ref, CAST(substr(ref,1,4) AS INT) - CAST(substr(birth_date,1,4) AS INT) - (substr(ref,6) < substr(birth_date,6)) age FROM mst_users, d)
SELECT ref, sum(age BETWEEN 20 AND 29) s20, sum(age BETWEEN 30 AND 39) s30, sum(age BETWEEN 40 AND 49) s40,
       sum(age BETWEEN 50 AND 59) s50, sum(age<20 OR age>=60) others FROM a GROUP BY ref ORDER BY ref;
-- name: local360_sessions
-- per session: index of the first row with path in (/detail, /detail/, /complete) in (stamp, rowid) order,
-- and how many earlier rows have a non-empty search_type; keep sessions at the minimum
WITH o AS (SELECT rowid r, session, stamp, path, search_type, row_number() OVER (PARTITION BY session ORDER BY stamp, rowid) k FROM activity_log),
 f AS (SELECT session, min(k) k0 FROM o WHERE path IN ('/detail','/detail/','/complete') GROUP BY session),
 c AS (SELECT f.session, (SELECT count(*) FROM o WHERE o.session=f.session AND o.k<f.k0 AND o.search_type<>'') n_pre FROM f)
SELECT c.session, c.n_pre, o.path, o.search_type FROM c JOIN f USING (session) JOIN o ON o.session=f.session AND o.k=f.k0
WHERE c.n_pre = (SELECT min(n_pre) FROM c) ORDER BY c.session;
-- name: local331_norm_slash
-- with '/x/' folded to '/x' (root '/' kept), ties by rowid
WITH d AS (SELECT session, stamp, rowid r, CASE WHEN path='/' THEN '/' ELSE rtrim(path,'/') END path FROM activity_log),
 s AS (SELECT path, lead(path) OVER w p1, lead(path,2) OVER w p2 FROM d WINDOW w AS (PARTITION BY session ORDER BY stamp, r))
SELECT p2 third_page, count(*) n FROM s WHERE path='/detail' AND p1='/detail' AND p2 IS NOT NULL GROUP BY p2 ORDER BY n DESC, p2;
