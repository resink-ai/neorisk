-- local360: sessions with the fewest non-empty-search events before the first /detail or /complete.
-- Written from the question (no gold SQL); the session set matches the gold CSVs, the path matches _c.
WITH o AS (SELECT rowid r, session, stamp, path, search_type, row_number() OVER (PARTITION BY session ORDER BY stamp, rowid) k FROM activity_log),
 f AS (SELECT session, min(k) k0 FROM o WHERE path IN ('/detail','/detail/','/complete') GROUP BY session),
 c AS (SELECT f.session, (SELECT count(*) FROM o WHERE o.session=f.session AND o.k<f.k0 AND o.search_type<>'') n_pre FROM f)
SELECT c.session, c.n_pre, o.path, o.search_type FROM c JOIN f USING (session) JOIN o ON o.session=f.session AND o.k=f.k0
WHERE c.n_pre = (SELECT min(n_pre) FROM c) ORDER BY c.session;
