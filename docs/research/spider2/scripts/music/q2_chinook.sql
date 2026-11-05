-- name: local244_chinook
WITH s AS (SELECT min(Milliseconds) mn, avg(Milliseconds) av, max(Milliseconds) mx FROM tracks),
t AS (SELECT t.TrackId, t.Milliseconds, CASE WHEN t.Milliseconds < (s.mn+s.av)/2 THEN 'short' WHEN t.Milliseconds < (s.av+s.mx)/2 THEN 'medium' ELSE 'long' END cat FROM tracks t, s),
r AS (SELECT TrackId, sum(UnitPrice*Quantity) rev FROM invoice_items GROUP BY 1)
SELECT cat AS CATEGORY, min(Milliseconds)/60000.0 AS MIN_DURATION_MINUTES, max(Milliseconds)/60000.0 AS MAX_DURATION_MINUTES, total(rev) AS TOTAL_REVENUE
FROM t LEFT JOIN r USING (TrackId) GROUP BY cat;
-- name: rowid_order_vs_pk
SELECT 'playlist_track' t, count(*) n, sum(a=b) same FROM (SELECT row_number() OVER (ORDER BY rowid) a, row_number() OVER (ORDER BY PlaylistId, TrackId) b FROM playlist_track);
