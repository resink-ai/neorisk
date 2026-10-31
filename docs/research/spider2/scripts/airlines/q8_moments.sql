-- name: lead_moments
with l as (select julianday(min(substr(f.scheduled_departure,1,19))) - julianday(substr(b.book_date,1,19)) x
  from bookings b join tickets t using(book_ref) join ticket_flights tf using(ticket_no) join flights f using(flight_id) group by b.book_ref)
select count(*), avg(x), sqrt(avg(x*x)-avg(x)*avg(x)) sd from l;
-- name: lead_moments_unaffected_by_edges
-- only bookings whose first flight departs 2017-07-20..2017-08-19 (both window edges >= 29 days away)
with l as (select min(substr(f.scheduled_departure,1,19)) d1, julianday(min(substr(f.scheduled_departure,1,19))) - julianday(substr(b.book_date,1,19)) x
  from bookings b join tickets t using(book_ref) join ticket_flights tf using(ticket_no) join flights f using(flight_id) group by b.book_ref)
select count(*), avg(x), sqrt(avg(x*x)-avg(x)*avg(x)) sd, min(x), max(x) from l where d1 between '2017-07-20' and '2017-08-19';
-- name: return_gap_roundtrip_days
with legs as (select tf.ticket_no, f.scheduled_departure d, f.scheduled_arrival a, f.departure_airport dep, f.arrival_airport arr,
   row_number() over (partition by tf.ticket_no order by f.scheduled_departure) rn, count(*) over (partition by tf.ticket_no) n from ticket_flights tf join flights f using(flight_id))
select cast(julianday(substr(b.d,1,19))-julianday(substr(a.a,1,19)) as int) gap_d, count(*) from legs a join legs b on b.ticket_no=a.ticket_no and b.rn=2 and a.rn=1 where a.n=2 group by 1 order by 1;
-- name: connection_gap_hours_hist
with legs as (select tf.ticket_no, f.scheduled_departure d, f.scheduled_arrival a, f.arrival_airport arr, f.departure_airport dep,
   row_number() over (partition by tf.ticket_no order by f.scheduled_departure) rn from ticket_flights tf join flights f using(flight_id))
select cast((julianday(substr(b.d,1,19))-julianday(substr(a.a,1,19)))*24/2 as int)*2 gap_h2, count(*) from legs a join legs b on b.ticket_no=a.ticket_no and b.rn=a.rn+1
where (julianday(substr(b.d,1,19))-julianday(substr(a.a,1,19))) < 1 group by 1 order by 1;
-- name: total_amount_hist
select case when total_amount<20000 then 'a<20k' when total_amount<50000 then 'b20-50k' when total_amount<100000 then 'c50-100k' when total_amount<200000 then 'd100-200k' else 'e>=200k' end b, count(*) from bookings group by 1 order by 1;
-- name: economy_fare_by_flight_hours
-- base (lower) Economy fare vs scheduled block minutes, by 60-minute band
select cast(m/60 as int) hours, count(*) flight_nos, min(lo), avg(lo), max(lo), round(avg(1.0*lo/m),1) rub_per_min from
 (select f.flight_no, (julianday(substr(min(f.scheduled_arrival),1,19))-julianday(substr(min(f.scheduled_departure),1,19)))*1440 m, min(tf.amount) lo
  from ticket_flights tf join flights f using(flight_id) where tf.fare_conditions='Economy' group by 1) group by 1 order by 1;
