-- name: row_counts
select 'albums' t, count(*) n from albums union all select 'artists', count(*) from artists
union all select 'customers', count(*) from customers union all select 'employees', count(*) from employees
union all select 'genres', count(*) from genres union all select 'invoices', count(*) from invoices
union all select 'invoice_items', count(*) from invoice_items union all select 'media_types', count(*) from media_types
union all select 'playlists', count(*) from playlists union all select 'playlist_track', count(*) from playlist_track
union all select 'tracks', count(*) from tracks;
-- name: system_tables
select 'sqlite_sequence' t, name, seq, null idx, null stat from sqlite_sequence
union all select 'sqlite_stat1', tbl, null, idx, stat from sqlite_stat1;
-- name: seq_vs_max
select s.name, s.seq, case s.name when 'genres' then (select max(GenreId) from genres) when 'media_types' then (select max(MediaTypeId) from media_types)
 when 'artists' then (select max(ArtistId) from artists) when 'albums' then (select max(AlbumId) from albums) when 'tracks' then (select max(TrackId) from tracks)
 when 'employees' then (select max(EmployeeId) from employees) when 'customers' then (select max(CustomerId) from customers)
 when 'invoices' then (select max(InvoiceId) from invoices) when 'playlists' then (select max(PlaylistId) from playlists) when 'invoice_items' then (select max(InvoiceLineId) from invoice_items) end as max_id
from sqlite_sequence s;
-- name: invoice_items_max_id
select max(InvoiceLineId), count(*), min(InvoiceLineId) from invoice_items;
-- name: ids_dense
select 'albums' t, min(AlbumId), max(AlbumId), count(*) from albums union all select 'artists', min(ArtistId), max(ArtistId), count(*) from artists
union all select 'tracks', min(TrackId), max(TrackId), count(*) from tracks union all select 'customers', min(CustomerId), max(CustomerId), count(*) from customers
union all select 'invoices', min(InvoiceId), max(InvoiceId), count(*) from invoices union all select 'invoice_items', min(InvoiceLineId), max(InvoiceLineId), count(*) from invoice_items
union all select 'playlists', min(PlaylistId), max(PlaylistId), count(*) from playlists;
-- name: typeof_columns
select 'invoices.Total' c, typeof(Total) t, count(*) from invoices group by 2
union all select 'invoices.InvoiceDate', typeof(InvoiceDate), count(*) from invoices group by 2
union all select 'invoice_items.UnitPrice', typeof(UnitPrice), count(*) from invoice_items group by 2
union all select 'invoice_items.Quantity', typeof(Quantity), count(*) from invoice_items group by 2
union all select 'tracks.UnitPrice', typeof(UnitPrice), count(*) from tracks group by 2
union all select 'tracks.Bytes', typeof(Bytes), count(*) from tracks group by 2
union all select 'tracks.Milliseconds', typeof(Milliseconds), count(*) from tracks group by 2
union all select 'tracks.Composer', typeof(Composer), count(*) from tracks group by 2
union all select 'tracks.AlbumId', typeof(AlbumId), count(*) from tracks group by 2
union all select 'tracks.GenreId', typeof(GenreId), count(*) from tracks group by 2
union all select 'employees.BirthDate', typeof(BirthDate), count(*) from employees group by 2
union all select 'employees.HireDate', typeof(HireDate), count(*) from employees group by 2
union all select 'employees.ReportsTo', typeof(ReportsTo), count(*) from employees group by 2
union all select 'customers.SupportRepId', typeof(SupportRepId), count(*) from customers group by 2
union all select 'customers.PostalCode', typeof(PostalCode), count(*) from customers group by 2
union all select 'invoices.BillingPostalCode', typeof(BillingPostalCode), count(*) from invoices group by 2;
-- name: null_and_empty_customers
select sum(Company is null) company_null, sum(Company='') company_empty, sum(State is null) state_null, sum(State='') state_empty,
 sum(PostalCode is null) pc_null, sum(PostalCode='') pc_empty, sum(Phone is null) phone_null, sum(Fax is null) fax_null, sum(Fax='') fax_empty,
 sum(Address is null) addr_null, sum(City is null) city_null, sum(SupportRepId is null) rep_null from customers;
-- name: null_and_empty_invoices
select sum(BillingAddress is null) a_null, sum(BillingCity is null) c_null, sum(BillingState is null) s_null, sum(BillingState='') s_empty,
 sum(BillingCountry is null) co_null, sum(BillingPostalCode is null) pc_null, sum(BillingPostalCode='') pc_empty from invoices;
-- name: null_and_empty_tracks
select sum(AlbumId is null) album_null, sum(GenreId is null) genre_null, sum(Composer is null) composer_null, sum(Composer='') composer_empty,
 sum(Bytes is null) bytes_null from tracks;
-- name: text_whitespace
select 'tracks.Name' c, sum(Name<>trim(Name)) untrimmed, sum(Name glob '*[^ -~]*') non_ascii, sum(instr(Name, char(10))>0) lf from tracks
union all select 'tracks.Composer', sum(Composer<>trim(Composer)), sum(Composer glob '*[^ -~]*'), sum(instr(Composer, char(10))>0) from tracks
union all select 'albums.Title', sum(Title<>trim(Title)), sum(Title glob '*[^ -~]*'), 0 from albums
union all select 'artists.Name', sum(Name<>trim(Name)), sum(Name glob '*[^ -~]*'), 0 from artists
union all select 'customers.*', sum(FirstName<>trim(FirstName) or LastName<>trim(LastName) or coalesce(Address,'')<>trim(coalesce(Address,''))), sum((FirstName||LastName||coalesce(Address,'')||coalesce(City,'')) glob '*[^ -~]*'), 0 from customers
union all select 'invoices.Billing*', sum(coalesce(BillingAddress,'')<>trim(coalesce(BillingAddress,''))), sum((coalesce(BillingAddress,'')||coalesce(BillingCity,'')) glob '*[^ -~]*'), 0 from invoices;
-- name: dup_names
select 'artists' t, count(*) - count(distinct Name) dup from artists
union all select 'albums.Title', count(*) - count(distinct Title) from albums
union all select 'albums(Title,ArtistId)', count(*) - count(distinct Title||'|'||ArtistId) from albums
union all select 'tracks.Name', count(*) - count(distinct Name) from tracks
union all select 'tracks(Name,AlbumId)', count(*) - count(distinct Name||'|'||AlbumId) from tracks
union all select 'playlists.Name', count(*) - count(distinct Name) from playlists
union all select 'customers.Email', count(*) - count(distinct Email) from customers;
