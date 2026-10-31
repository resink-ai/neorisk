-- name: local198_median_country_sales
with c as (select Country, count(*) n from customers group by 1 having count(*) > 4),
s as (select i.BillingCountry Country, sum(i.Total) tot from invoices i join c on c.Country = i.BillingCountry group by 1),
r as (select tot, row_number() over (order by tot) k, count(*) over () m from s)
select avg(tot) median_total_sales, group_concat(round(tot,2)) totals from r where k in ((m+1)/2, (m+2)/2);
-- name: local054_best_artist_under_1
with a as (select al.ArtistId, sum(ii.UnitPrice*ii.Quantity) s from invoice_items ii join tracks t using(TrackId) join albums al using(AlbumId) group by 1 order by s desc limit 1),
c as (select i.CustomerId, sum(ii.UnitPrice*ii.Quantity) spent from invoice_items ii join invoices i using(InvoiceId) join tracks t using(TrackId) join albums al using(AlbumId)
      where al.ArtistId = (select ArtistId from a) group by 1)
select cu.FirstName, round(spent,2) spent, (select ArtistId from a) artist from c join customers cu using(CustomerId) where spent < 1 order by 1;
-- name: local054_top_artists
select ar.Name, al.ArtistId, round(sum(ii.UnitPrice*ii.Quantity),2) s, count(*) lines from invoice_items ii join tracks t using(TrackId) join albums al using(AlbumId) join artists ar using(ArtistId) group by 2 order by 3 desc limit 4;
-- name: local055_reading_a
-- artist ranking by line revenue; ties alphabetical; spend per customer on that artist; avg over customers who bought
with ar as (select al.ArtistId, ar.Name, sum(ii.UnitPrice*ii.Quantity) s from invoice_items ii join tracks t using(TrackId) join albums al using(AlbumId) join artists ar using(ArtistId) group by 1),
top as (select ArtistId from ar order by s desc, Name asc limit 1), bot as (select ArtistId from ar order by s asc, Name asc limit 1),
cs as (select al.ArtistId, i.CustomerId, sum(ii.UnitPrice*ii.Quantity) spent from invoice_items ii join invoices i using(InvoiceId) join tracks t using(TrackId) join albums al using(AlbumId) group by 1,2)
select (select Name from ar where ArtistId=(select ArtistId from top)) top_artist, (select Name from ar where ArtistId=(select ArtistId from bot)) bottom_artist,
  (select avg(spent) from cs where ArtistId=(select ArtistId from top)) avg_top, (select avg(spent) from cs where ArtistId=(select ArtistId from bot)) avg_bot,
  abs((select avg(spent) from cs where ArtistId=(select ArtistId from top)) - (select avg(spent) from cs where ArtistId=(select ArtistId from bot))) diff;
-- name: local055_reading_b
-- every artist ranked, including the 71 without albums and others with no sales (sales 0); the bottom artist then has no buyers, avg taken as 0
with ar as (select a.ArtistId, a.Name, coalesce((select sum(ii.UnitPrice*ii.Quantity) from invoice_items ii join tracks t using(TrackId) join albums al using(AlbumId) where al.ArtistId=a.ArtistId),0) s from artists a),
top as (select ArtistId from ar order by s desc, Name asc limit 1), bot as (select ArtistId from ar order by s asc, Name asc limit 1),
cs as (select al.ArtistId, i.CustomerId, sum(ii.UnitPrice*ii.Quantity) spent from invoice_items ii join invoices i using(InvoiceId) join tracks t using(TrackId) join albums al using(AlbumId) group by 1,2)
select (select Name from ar where ArtistId=(select ArtistId from top)) top_artist, (select Name from ar where ArtistId=(select ArtistId from bot)) bottom_artist,
  (select avg(spent) from cs where ArtistId=(select ArtistId from top)) avg_top, coalesce((select avg(spent) from cs where ArtistId=(select ArtistId from bot)),0) avg_bot,
  abs((select avg(spent) from cs where ArtistId=(select ArtistId from top)) - coalesce((select avg(spent) from cs where ArtistId=(select ArtistId from bot)),0)) diff,
  (select count(*) from ar where s = 0) artists_with_zero_sales;
-- name: local055_bottom_ties
with ar as (select al.ArtistId, ar.Name, sum(ii.UnitPrice*ii.Quantity) s, count(*) n from invoice_items ii join tracks t using(TrackId) join albums al using(AlbumId) join artists ar using(ArtistId) group by 1)
select Name, round(s,2), n from ar order by s asc, Name limit 6;
