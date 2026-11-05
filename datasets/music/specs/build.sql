-- music: events → source tables (refdata rebuild, DuckDB).
-- chinook's bodies, which read the pack's views; only the table headers are the source names.

-- table: Genre
SELECT CAST(ext_id AS BIGINT) AS GenreId, name AS Name FROM genres;

-- table: MediaType
SELECT CAST(ext_id AS BIGINT) AS MediaTypeId, name AS Name FROM media_types;

-- table: Artist
SELECT CAST(ext_id AS BIGINT) AS ArtistId, name AS Name FROM artists;

-- table: Album
SELECT CAST(a.ext_id AS BIGINT) AS AlbumId, a.title AS Title, CAST(r.ext_id AS BIGINT) AS ArtistId
FROM albums a JOIN artists r USING (artist_id);

-- table: Track
SELECT CAST(t.ext_id AS BIGINT) AS TrackId, t.name AS Name, CAST(a.ext_id AS BIGINT) AS AlbumId,
       CAST(m.ext_id AS BIGINT) AS MediaTypeId, CAST(g.ext_id AS BIGINT) AS GenreId,
       t.composer AS Composer, t.milliseconds AS Milliseconds, t.bytes AS Bytes,
       n.unit_price / 100.0 AS UnitPrice
FROM tracks t LEFT JOIN albums a USING (album_id) JOIN media_types m USING (media_type_id)
LEFT JOIN genres g USING (genre_id) LEFT JOIN tracks_snapshot n USING (track_id);

-- table: Playlist
SELECT CAST(ext_id AS BIGINT) AS PlaylistId, name AS Name FROM playlists;

-- table: PlaylistTrack
SELECT CAST(p.ext_id AS BIGINT) AS PlaylistId, CAST(t.ext_id AS BIGINT) AS TrackId
FROM playlist_track x JOIN playlists p USING (playlist_id) JOIN tracks t USING (track_id);

-- table: Employee
SELECT CAST(e.ext_id AS BIGINT) AS EmployeeId, e.last_name AS LastName, e.first_name AS FirstName,
       n.title AS Title, CAST(b.ext_id AS BIGINT) AS ReportsTo, e.birth_date AS BirthDate,
       strftime(e.created_at AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S') AS HireDate,
       n.address AS Address, n.city AS City, n.state AS State, n.country AS Country,
       n.postal_code AS PostalCode, n.phone AS Phone, n.fax AS Fax, n.email AS Email
FROM employees e LEFT JOIN employees_snapshot n USING (employee_id)
LEFT JOIN employees b ON b.employee_id = n.reports_to;

-- table: Customer
SELECT CAST(c.ext_id AS BIGINT) AS CustomerId, c.first_name AS FirstName, c.last_name AS LastName,
       n.company AS Company, c.address AS Address, c.city AS City, c.state AS State,
       c.country AS Country, c.postal_code AS PostalCode, n.phone AS Phone, n.fax AS Fax,
       n.email AS Email, CAST(e.ext_id AS BIGINT) AS SupportRepId
FROM customers c LEFT JOIN customers_snapshot n USING (customer_id)
LEFT JOIN employees e ON e.employee_id = n.support_rep_id;

-- table: Invoice
-- Billing address is the customer's; Total is the line cents / 100.0, never a float sum.
SELECT i.invoice_id AS InvoiceId, CAST(c.ext_id AS BIGINT) AS CustomerId,
       strftime(i.event_time AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S') AS InvoiceDate,
       c.address AS BillingAddress, c.city AS BillingCity, c.state AS BillingState,
       c.country AS BillingCountry, c.postal_code AS BillingPostalCode,
       (SELECT sum(l.unit_price * l.quantity) FROM invoice_line_added l
        WHERE l.invoice_id = i.invoice_id) / 100.0 AS Total
FROM invoice_issued i JOIN customers c USING (customer_id);

-- table: InvoiceLine
SELECT invoice_line_id AS InvoiceLineId, invoice_id AS InvoiceId, CAST(t.ext_id AS BIGINT) AS TrackId,
       l.unit_price / 100.0 AS UnitPrice, l.quantity AS Quantity
FROM invoice_line_added l JOIN tracks t USING (track_id);
