-- local054: first names of customers who spent < $1 on albums by the best-selling artist,
-- with the amount. Written from the question (no gold SQL); matches the gold CSV.
with a as (select al.ArtistId, sum(ii.UnitPrice*ii.Quantity) s from invoice_items ii join tracks t using(TrackId) join albums al using(AlbumId) group by 1 order by s desc limit 1),
c as (select i.CustomerId, sum(ii.UnitPrice*ii.Quantity) spent from invoice_items ii join invoices i using(InvoiceId) join tracks t using(TrackId) join albums al using(AlbumId)
      where al.ArtistId = (select ArtistId from a) group by 1)
select cu.FirstName, round(spent,2) spent, (select ArtistId from a) artist from c join customers cu using(CustomerId) where spent < 1 order by 1;
