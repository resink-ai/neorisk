-- name: fk_orphans
select 'albums.ArtistId->artists' fk, count(*) n, sum(a.ArtistId is null) orphans from albums al left join artists a using(ArtistId)
union all select 'tracks.AlbumId->albums', count(*), sum(a.AlbumId is null) from tracks t left join albums a using(AlbumId)
union all select 'tracks.GenreId->genres', count(*), sum(g.GenreId is null) from tracks t left join genres g using(GenreId)
union all select 'tracks.MediaTypeId->media_types', count(*), sum(m.MediaTypeId is null) from tracks t left join media_types m using(MediaTypeId)
union all select 'invoice_items.InvoiceId->invoices', count(*), sum(i.InvoiceId is null) from invoice_items ii left join invoices i using(InvoiceId)
union all select 'invoice_items.TrackId->tracks', count(*), sum(t.TrackId is null) from invoice_items ii left join tracks t using(TrackId)
union all select 'invoices.CustomerId->customers', count(*), sum(c.CustomerId is null) from invoices i left join customers c using(CustomerId)
union all select 'customers.SupportRepId->employees', count(*), sum(e.EmployeeId is null) from customers c left join employees e on e.EmployeeId=c.SupportRepId
union all select 'employees.ReportsTo->employees', count(*), sum(e.EmployeeId is null) from employees x left join employees e on e.EmployeeId=x.ReportsTo where x.ReportsTo is not null
union all select 'playlist_track.PlaylistId->playlists', count(*), sum(p.PlaylistId is null) from playlist_track pt left join playlists p using(PlaylistId)
union all select 'playlist_track.TrackId->tracks', count(*), sum(t.TrackId is null) from playlist_track pt left join tracks t using(TrackId);
-- name: parents_without_children
select 'artists without albums' w, count(*) from artists a where not exists (select 1 from albums x where x.ArtistId=a.ArtistId)
union all select 'albums without tracks', count(*) from albums a where not exists (select 1 from tracks x where x.AlbumId=a.AlbumId)
union all select 'tracks never sold', count(*) from tracks t where not exists (select 1 from invoice_items x where x.TrackId=t.TrackId)
union all select 'tracks in no playlist', count(*) from tracks t where not exists (select 1 from playlist_track x where x.TrackId=t.TrackId)
union all select 'playlists empty', count(*) from playlists p where not exists (select 1 from playlist_track x where x.PlaylistId=p.PlaylistId)
union all select 'customers without invoices', count(*) from customers c where not exists (select 1 from invoices x where x.CustomerId=c.CustomerId)
union all select 'invoices without lines', count(*) from invoices i where not exists (select 1 from invoice_items x where x.InvoiceId=i.InvoiceId)
union all select 'employees supporting customers', count(distinct SupportRepId) from customers
union all select 'genres unused', count(*) from genres g where not exists (select 1 from tracks x where x.GenreId=g.GenreId)
union all select 'tracks sold more than once', count(*) from (select TrackId from invoice_items group by TrackId having count(*)>1)
union all select 'tracks sold twice in one invoice', count(*) from (select InvoiceId, TrackId from invoice_items group by 1,2 having count(*)>1);
-- name: total_vs_lines_float
-- Total compared with the float sum, the cent sum and SQLite's printed value
with s as (select InvoiceId, sum(UnitPrice*Quantity) fsum, sum(cast(round(UnitPrice*100) as integer)*Quantity) csum, count(*) n from invoice_items group by InvoiceId)
select count(*) invoices,
  sum(i.Total = s.fsum) float_equal,
  sum(cast(round(i.Total*100) as integer) = s.csum) cents_equal,
  sum(i.Total = round(i.Total, 2)) total_on_cent_grid,
  sum(abs(i.Total - s.fsum) > 0) float_diff_nonzero,
  max(abs(i.Total - s.fsum)) max_abs_float_diff,
  sum(round(s.fsum,2) = i.Total) round2_fsum_equal
from invoices i join s using(InvoiceId);
-- name: total_float_mismatch_examples
with s as (select InvoiceId, sum(UnitPrice*Quantity) fsum, count(*) n from invoice_items group by InvoiceId)
select i.InvoiceId, n, printf('%.17g', i.Total) total17, printf('%.17g', s.fsum) fsum17 from invoices i join s using(InvoiceId) where i.Total <> s.fsum limit 8;
-- name: unit_price_on_cent_grid
select 'invoice_items' t, count(*), sum(UnitPrice = round(UnitPrice,2)) on_grid, group_concat(distinct UnitPrice) vals from invoice_items
union all select 'tracks', count(*), sum(UnitPrice = round(UnitPrice,2)), group_concat(distinct UnitPrice) from tracks;
-- name: quantity_values
select Quantity, count(*) from invoice_items group by 1;
-- name: line_price_vs_track_price
select count(*) n, sum(ii.UnitPrice = t.UnitPrice) equal from invoice_items ii join tracks t using(TrackId);
-- name: price_by_media
select m.Name, t.UnitPrice, count(*) from tracks t join media_types m using(MediaTypeId) group by 1,2 order by 1,2;
-- name: total_values
select Total, count(*) n, min(nl), max(nl) from (select i.Total, (select count(*) from invoice_items x where x.InvoiceId=i.InvoiceId) nl from invoices i) group by Total order by n desc;
-- name: lines_per_invoice
select nl, count(*) from (select InvoiceId, count(*) nl from invoice_items group by 1) group by 1 order by 1;
-- name: invoices_per_customer
select k, count(*) customers from (select CustomerId, count(*) k from invoices group by 1) group by 1;
-- name: billing_equals_customer_address
select count(*) n,
 sum(i.BillingAddress is c.Address) addr, sum(i.BillingCity is c.City) city, sum(i.BillingState is c.State) state,
 sum(i.BillingCountry is c.Country) country, sum(i.BillingPostalCode is c.PostalCode) pc,
 sum(i.BillingAddress is c.Address and i.BillingCity is c.City and i.BillingState is c.State and i.BillingCountry is c.Country and i.BillingPostalCode is c.PostalCode) all5
from invoices i join customers c using(CustomerId);
-- name: support_rep_load
select SupportRepId, count(*) customers from customers group by 1;
-- name: playlist_dups
select p.PlaylistId, p.Name, count(pt.TrackId) n from playlists p left join playlist_track pt using(PlaylistId) group by 1 order by 2,1;
-- name: playlist_pairs_same_tracks
select a.PlaylistId, b.PlaylistId, a.Name,
  (select count(*) from playlist_track x where x.PlaylistId=a.PlaylistId and x.TrackId in (select TrackId from playlist_track y where y.PlaylistId=b.PlaylistId)) common
from playlists a join playlists b on a.Name=b.Name and a.PlaylistId<b.PlaylistId;
-- name: playlist_track_rowid_order
select count(*) pairs, sum(cur >= prev) nondecreasing from (select (PlaylistId*100000+TrackId) cur, lag(PlaylistId*100000+TrackId) over (order by rowid) prev from playlist_track) where prev is not null;
-- name: playlist_track_rowid_vs_pk
select count(*) rows_, min(rowid), max(rowid) from playlist_track;
