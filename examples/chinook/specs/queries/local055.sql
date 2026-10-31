-- local055: top and bottom artist by album sales (ties alphabetical), the average spend of
-- each one's buyers, and the absolute difference. Written from the question (no gold SQL);
-- ranks only artists with sales, matching gold CSV _b.
with ar as (select al.ArtistId, ar.Name, sum(ii.UnitPrice*ii.Quantity) s from invoice_items ii join tracks t using(TrackId) join albums al using(AlbumId) join artists ar using(ArtistId) group by 1),
top as (select ArtistId from ar order by s desc, Name asc limit 1), bot as (select ArtistId from ar order by s asc, Name asc limit 1),
cs as (select al.ArtistId, i.CustomerId, sum(ii.UnitPrice*ii.Quantity) spent from invoice_items ii join invoices i using(InvoiceId) join tracks t using(TrackId) join albums al using(AlbumId) group by 1,2)
select (select Name from ar where ArtistId=(select ArtistId from top)) top_artist, (select Name from ar where ArtistId=(select ArtistId from bot)) bottom_artist,
  (select avg(spent) from cs where ArtistId=(select ArtistId from top)) avg_top, (select avg(spent) from cs where ArtistId=(select ArtistId from bot)) avg_bot,
  abs((select avg(spent) from cs where ArtistId=(select ArtistId from top)) - (select avg(spent) from cs where ArtistId=(select ArtistId from bot))) diff;
