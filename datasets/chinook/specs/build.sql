-- Chinook: events → source tables (refdata rebuild, DuckDB).

-- table: genres
SELECT CAST(ext_id AS BIGINT) AS GenreId, name AS Name FROM genres;

-- table: media_types
SELECT CAST(ext_id AS BIGINT) AS MediaTypeId, name AS Name FROM media_types;

-- table: artists
SELECT CAST(ext_id AS BIGINT) AS ArtistId, name AS Name FROM artists;

-- table: albums
SELECT CAST(a.ext_id AS BIGINT) AS AlbumId, a.title AS Title, CAST(r.ext_id AS BIGINT) AS ArtistId
FROM albums a JOIN artists r USING (artist_id);

-- table: tracks
SELECT CAST(t.ext_id AS BIGINT) AS TrackId, t.name AS Name, CAST(a.ext_id AS BIGINT) AS AlbumId,
       CAST(m.ext_id AS BIGINT) AS MediaTypeId, CAST(g.ext_id AS BIGINT) AS GenreId,
       t.composer AS Composer, t.milliseconds AS Milliseconds, t.bytes AS Bytes,
       t.unit_price / 100.0 AS UnitPrice
FROM tracks t LEFT JOIN albums a USING (album_id) JOIN media_types m USING (media_type_id)
LEFT JOIN genres g USING (genre_id);

-- table: playlists
SELECT CAST(ext_id AS BIGINT) AS PlaylistId, name AS Name FROM playlists;

-- table: playlist_track
SELECT CAST(p.ext_id AS BIGINT) AS PlaylistId, CAST(t.ext_id AS BIGINT) AS TrackId
FROM playlist_track x JOIN playlists p USING (playlist_id) JOIN tracks t USING (track_id);

-- table: employees
SELECT CAST(e.ext_id AS BIGINT) AS EmployeeId, e.last_name AS LastName, e.first_name AS FirstName,
       e.title AS Title, CAST(b.ext_id AS BIGINT) AS ReportsTo, e.birth_date AS BirthDate,
       strftime(e.created_at AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S') AS HireDate,
       e.address AS Address, e.city AS City, e.state AS State, e.country AS Country,
       e.postal_code AS PostalCode, e.phone AS Phone, e.fax AS Fax, e.email AS Email
FROM employees e LEFT JOIN employees b ON b.employee_id = e.reports_to;

-- table: customers
SELECT CAST(c.ext_id AS BIGINT) AS CustomerId, c.first_name AS FirstName, c.last_name AS LastName,
       c.company AS Company, c.address AS Address, c.city AS City, c.state AS State,
       c.country AS Country, c.postal_code AS PostalCode, c.phone AS Phone, c.fax AS Fax,
       c.email AS Email, CAST(e.ext_id AS BIGINT) AS SupportRepId
FROM customers c LEFT JOIN employees e ON e.employee_id = c.support_rep_id;

-- table: invoices
-- Billing address is the customer's; Total is the line cents / 100.0, never a float sum.
SELECT i.invoice_id AS InvoiceId, CAST(c.ext_id AS BIGINT) AS CustomerId,
       strftime(i.event_time AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S') AS InvoiceDate,
       c.address AS BillingAddress, c.city AS BillingCity, c.state AS BillingState,
       c.country AS BillingCountry, c.postal_code AS BillingPostalCode,
       (SELECT sum(l.unit_price * l.quantity) FROM invoice_line_added l
        WHERE l.invoice_id = i.invoice_id) / 100.0 AS Total
FROM invoice_issued i JOIN customers c USING (customer_id);

-- table: invoice_items
SELECT invoice_line_id AS InvoiceLineId, invoice_id AS InvoiceId, CAST(t.ext_id AS BIGINT) AS TrackId,
       l.unit_price / 100.0 AS UnitPrice, l.quantity AS Quantity
FROM invoice_line_added l JOIN tracks t USING (track_id);
