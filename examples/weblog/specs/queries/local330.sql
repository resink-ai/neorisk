-- local330: sessions per page as landing and/or exit page (ORDER BY stamp; ties in row order).
-- Written from the question (no gold SQL); matches gold CSV _a. Depends on the row order of ties.
WITH r AS (SELECT session, path,
   row_number() OVER (PARTITION BY session ORDER BY stamp) f, row_number() OVER (PARTITION BY session ORDER BY stamp DESC) l FROM activity_log),
 p AS (SELECT session, path FROM r WHERE f=1 UNION SELECT session, path FROM r WHERE l=1)
SELECT path, count(DISTINCT session) n FROM p GROUP BY path ORDER BY n DESC, path;
