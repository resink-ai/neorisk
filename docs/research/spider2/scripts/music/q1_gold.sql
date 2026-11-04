-- name: local244
WITH s AS (SELECT min(Milliseconds) mn, avg(Milliseconds) av, max(Milliseconds) mx FROM Track),
t AS (SELECT t.TrackId, t.Milliseconds, CASE WHEN t.Milliseconds < (s.mn+s.av)/2 THEN 'short' WHEN t.Milliseconds < (s.av+s.mx)/2 THEN 'medium' ELSE 'long' END cat FROM Track t, s),
r AS (SELECT TrackId, sum(UnitPrice*Quantity) rev FROM InvoiceLine GROUP BY 1)
SELECT cat AS CATEGORY, min(Milliseconds)/60000.0 AS MIN_DURATION_MINUTES, max(Milliseconds)/60000.0 AS MAX_DURATION_MINUTES, total(rev) AS TOTAL_REVENUE
FROM t LEFT JOIN r USING (TrackId) GROUP BY cat;
-- name: thresholds
SELECT min(Milliseconds) mn, avg(Milliseconds) av, max(Milliseconds) mx, (min(Milliseconds)+avg(Milliseconds))/2 t1, (avg(Milliseconds)+max(Milliseconds))/2 t2 FROM Track;
-- name: system_tables
SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'sqlite_%';
-- name: rowid_order_vs_pk
SELECT 'PlaylistTrack' t, count(*) n, sum(a=b) same FROM (SELECT row_number() OVER (ORDER BY rowid) a, row_number() OVER (ORDER BY PlaylistId, TrackId) b FROM PlaylistTrack)
UNION ALL SELECT 'InvoiceLine', count(*), sum(a=b) FROM (SELECT row_number() OVER (ORDER BY rowid) a, row_number() OVER (ORDER BY InvoiceLineId) b FROM InvoiceLine);
-- name: date_range
SELECT min(InvoiceDate), max(InvoiceDate), count(*) FROM Invoice;
