-- name: cents_rebuild_exact
-- Total rebuilt as integer cents / 100.0 equals the stored REAL exactly; same for line prices
with s as (select InvoiceId, sum(cast(round(UnitPrice*100) as integer)*Quantity) csum from invoice_items group by InvoiceId)
select count(*) n, sum(i.Total = s.csum/100.0) total_eq, (select sum(UnitPrice = cast(round(UnitPrice*100) as integer)/100.0) from invoice_items) line_eq,
       (select sum(UnitPrice = cast(round(UnitPrice*100) as integer)/100.0) from tracks) track_eq,
       sum(cast(i.Total as text) = printf('%.2f', i.Total)) text_2dp, sum(cast(i.Total as text) = rtrim(rtrim(printf('%.2f', i.Total),'0'),'.')) text_shortest
from invoices i join s using(InvoiceId);
-- name: date_format
select length(InvoiceDate) len, substr(InvoiceDate, 12) timepart, count(*) from invoices group by 1,2;
-- name: date_range
select min(InvoiceDate), max(InvoiceDate), count(distinct substr(InvoiceDate,1,10)) days,
  julianday(max(InvoiceDate)) - julianday(min(InvoiceDate)) span_days from invoices;
-- name: id_vs_date_order
select count(*) pairs, sum(d >= pd) date_nondecreasing, sum(d > pd) strictly from (select InvoiceDate d, lag(InvoiceDate) over (order by InvoiceId) pd from invoices) where pd is not null;
-- name: same_day_invoices
select k, count(*) days from (select substr(InvoiceDate,1,10) d, count(*) k from invoices group by 1) group by 1;
-- name: gap_days_between_consecutive_invoices
select g, count(*) from (select julianday(InvoiceDate) - julianday(lag(InvoiceDate) over (order by InvoiceId)) g from invoices) where g is not null group by 1 order by 1;
-- name: per_customer_gaps
select g, count(*) from (select julianday(InvoiceDate) - julianday(lag(InvoiceDate) over (partition by CustomerId order by InvoiceId)) g from invoices) where g is not null group by 1 order by 2 desc;
-- name: customer_step
select step, count(*) from (select (CustomerId - lag(CustomerId) over (order by InvoiceId) + 59) % 59 step from invoices) where step is not null group by 1 order by 2 desc limit 10;
-- name: lines_cycle
select nl, lag_nl, count(*) from (select InvoiceId, nl, lag(nl) over (order by InvoiceId) lag_nl from (select InvoiceId, count(*) nl from invoice_items group by 1)) group by 1,2 order by 3 desc;
-- name: lines_by_customer_invoice_rank
select k, nl, count(*) from (select i.CustomerId, row_number() over (partition by i.CustomerId order by i.InvoiceId) k, (select count(*) from invoice_items x where x.InvoiceId=i.InvoiceId) nl from invoices i) group by 1,2 order by 1,2;
-- name: customer_with_6_invoices
select CustomerId, group_concat(nl) from (select i.CustomerId, i.InvoiceId, (select count(*) from invoice_items x where x.InvoiceId=i.InvoiceId) nl from invoices i order by i.InvoiceId) group by CustomerId having count(*)=6;
-- name: line_id_order
select count(*) pairs, sum(InvoiceId >= p) inv_nondecr, sum(TrackId > pt and InvoiceId = p) track_incr_within from (select InvoiceId, TrackId, lag(InvoiceId) over (order by InvoiceLineId) p, lag(TrackId) over (order by InvoiceLineId) pt from invoice_items) where p is not null;
-- name: track_step_within_invoice
select TrackId - pt step, count(*) from (select InvoiceId, TrackId, lag(TrackId) over (partition by InvoiceId order by InvoiceLineId) pt from invoice_items) where pt is not null group by 1 order by 2 desc limit 10;
-- name: track_step_between_invoices
select first - plast step, count(*) from (select InvoiceId, min(TrackId) first, max(TrackId) last, lag(max(TrackId)) over (order by InvoiceId) plast from invoice_items group by InvoiceId) where plast is not null group by 1 order by 2 desc limit 10;
-- name: track_wraps
select count(*) from (select InvoiceId, min(TrackId) first, lag(max(TrackId)) over (order by InvoiceId) plast from invoice_items group by InvoiceId) where first < plast;
-- name: monthly_invoices
select substr(InvoiceDate,1,7) m, count(*) n, round(sum(Total),2) rev from invoices group by 1 order by 1;
-- name: yearly
select substr(InvoiceDate,1,4) y, count(*) n, round(sum(Total),2) rev, sum(Total <> cast(Total*100 as int)/100.0) odd from invoices group by 1;
-- name: per_month_counts_dist
select n, count(*) months from (select substr(InvoiceDate,1,7) m, count(*) n from invoices group by 1) group by 1;
-- name: weekday
select strftime('%w', InvoiceDate) dow, count(*) from invoices group by 1;
-- name: invoice_vs_hire_birth
select (select min(InvoiceDate) from invoices) first_inv, (select max(HireDate) from employees) last_hire, (select min(HireDate) from employees) first_hire;
-- name: video_lines
select count(*) lines_199, count(distinct InvoiceId) invoices_with_199 from invoice_items where UnitPrice = 1.99;
-- name: tracks_sold_distribution
select k, count(*) tracks from (select t.TrackId, (select count(*) from invoice_items x where x.TrackId=t.TrackId) k from tracks t) group by 1;
-- name: genre_sales
select g.Name, count(*) lines, round(sum(ii.UnitPrice),2) rev from invoice_items ii join tracks t using(TrackId) join genres g using(GenreId) group by 1 order by 2 desc limit 10;
-- name: country_customers
select Country, count(*) customers, (select round(sum(Total),2) from invoices i where i.BillingCountry=c.Country) rev from customers c group by 1 order by 2 desc, 1;
-- name: customer_spend
select min(s), max(s), avg(s) from (select CustomerId, sum(Total) s from invoices group by 1);
-- name: track_catalog_stats
select m.Name, count(*), min(Milliseconds), cast(avg(Milliseconds) as int), max(Milliseconds), min(Bytes), max(Bytes) from tracks t join media_types m using(MediaTypeId) group by 1;
-- name: tracks_per_album
select k, count(*) albums from (select AlbumId, count(*) k from tracks group by 1) group by 1 order by 1;
-- name: albums_per_artist
select k, count(*) artists from (select ArtistId, count(*) k from albums group by 1) group by 1 order by 1;
-- name: track_id_album_contiguous
select count(*) pairs, sum(AlbumId = pa) same_album, sum(AlbumId < pa) album_goes_back from (select AlbumId, lag(AlbumId) over (order by TrackId) pa from tracks) where pa is not null;
-- name: employee_dates
select EmployeeId, BirthDate, HireDate, ReportsTo, Title from employees;
-- name: cycle_rules_by_lines
-- for each invoice: its line count, the step from the previous invoice's customer, date gap, and track steps
with inv as (select i.InvoiceId, i.CustomerId, i.InvoiceDate, count(*) nl, min(ii.TrackId) ft, max(ii.TrackId) lt
             from invoices i join invoice_items ii using(InvoiceId) group by 1),
x as (select *, (CustomerId - lag(CustomerId) over (order by InvoiceId) + 59) % 59 cstep,
             julianday(InvoiceDate) - julianday(lag(InvoiceDate) over (order by InvoiceId)) gap,
             ft - lag(lt) over (order by InvoiceId) tstep from inv)
select nl, cstep, gap, tstep, count(*) n from x group by 1,2,3,4 order by n desc limit 20;
-- name: within_step_by_lines
with s as (select InvoiceId, TrackId - lag(TrackId) over (partition by InvoiceId order by InvoiceLineId) st, count(*) over (partition by InvoiceId) nl from invoice_items)
select nl, st, count(*) from s where st is not null group by 1,2 order by 1, 3 desc;
