-- Chinook: source tables → events (refdata ingest). Money is in cents.

-- entity: genres
SELECT CAST(GenreId AS TEXT) AS ext_id, Name AS name FROM genres ORDER BY GenreId;

-- entity: media_types
SELECT CAST(MediaTypeId AS TEXT) AS ext_id, Name AS name FROM media_types ORDER BY MediaTypeId;

-- entity: artists
SELECT CAST(ArtistId AS TEXT) AS ext_id, Name AS name FROM artists ORDER BY ArtistId;

-- entity: albums
SELECT CAST(AlbumId AS TEXT) AS ext_id, Title AS title, CAST(ArtistId AS TEXT) AS artist_id
FROM albums ORDER BY AlbumId;

-- entity: tracks
SELECT CAST(TrackId AS TEXT) AS ext_id, Name AS name, CAST(AlbumId AS TEXT) AS album_id,
       CAST(MediaTypeId AS TEXT) AS media_type_id, CAST(GenreId AS TEXT) AS genre_id,
       Composer AS composer, Milliseconds AS milliseconds, Bytes AS bytes,
       CAST(round(UnitPrice * 100) AS INTEGER) AS unit_price
FROM tracks ORDER BY TrackId;

-- entity: playlists
SELECT CAST(PlaylistId AS TEXT) AS ext_id, Name AS name FROM playlists ORDER BY PlaylistId;

-- entity: playlist_track
SELECT PlaylistId || '/' || TrackId AS ext_id, CAST(PlaylistId AS TEXT) AS playlist_id,
       CAST(TrackId AS TEXT) AS track_id
FROM playlist_track ORDER BY PlaylistId, TrackId;

-- entity: employees
SELECT CAST(EmployeeId AS TEXT) AS ext_id, HireDate AS created_at, LastName AS last_name,
       FirstName AS first_name, Title AS title, CAST(ReportsTo AS TEXT) AS reports_to,
       BirthDate AS birth_date, Address AS address, City AS city, State AS state,
       Country AS country, PostalCode AS postal_code, Phone AS phone, Fax AS fax, Email AS email
FROM employees ORDER BY EmployeeId;

-- entity: customers
SELECT CAST(c.CustomerId AS TEXT) AS ext_id,
       (SELECT MIN(InvoiceDate) FROM invoices i WHERE i.CustomerId = c.CustomerId) AS created_at,
       FirstName AS first_name, LastName AS last_name, Company AS company, Address AS address,
       City AS city, State AS state, Country AS country, PostalCode AS postal_code,
       Phone AS phone, Fax AS fax, Email AS email, CAST(SupportRepId AS TEXT) AS support_rep_id
FROM customers c ORDER BY CustomerId;

-- event: invoice_issued owner=customer_id
SELECT InvoiceDate AS event_time, CAST(CustomerId AS TEXT) AS customer_id, InvoiceId AS invoice_id
FROM invoices ORDER BY InvoiceId;

-- event: invoice_line_added owner=customer_id ord=invoice_line_id
SELECT i.InvoiceDate AS event_time, CAST(i.CustomerId AS TEXT) AS customer_id, l.InvoiceId AS invoice_id,
       l.InvoiceLineId AS invoice_line_id, CAST(l.TrackId AS TEXT) AS track_id,
       CAST(round(l.UnitPrice * 100) AS INTEGER) AS unit_price, l.Quantity AS quantity
FROM invoice_items l JOIN invoices i USING (InvoiceId) ORDER BY l.InvoiceLineId;
