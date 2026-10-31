-- name: no_ticket_flights_by_aircraft_status
select f.aircraft_code, f.status, count(*) flights, sum(not exists(select 1 from ticket_flights tf where tf.flight_id=f.flight_id)) no_tickets
from flights f group by 1,2 order by 1,2;
-- name: no_ticket_flights_by_week
select strftime('%Y-%W', substr(scheduled_departure,1,19)) wk, count(*), sum(not exists(select 1 from ticket_flights tf where tf.flight_id=f.flight_id)) no_tickets
from flights f group by 1 order by 1;
-- name: flightnos_without_any_tickets
select count(*) from (select flight_no from flights f group by 1 having sum(exists(select 1 from ticket_flights tf where tf.flight_id=f.flight_id))=0);
-- name: tickets_per_booking
select n, count(*) bookings, round(1.0*count(*)/262788,4) share from (select count(*) n from tickets group by book_ref) group by 1 order by 1;
-- name: legs_per_ticket
select n, count(*) tickets, round(1.0*count(*)/366733,4) share from (select count(*) n from ticket_flights group by ticket_no) group by 1 order by 1;
-- name: same_itinerary_within_booking
-- do all tickets of a booking share the same set of flights?
select count(*) bookings_multi, sum(nsets=1) same_itin from
 (select book_ref, count(distinct fl) nsets from (select t.book_ref, t.ticket_no, group_concat(tf.flight_id) fl from tickets t join (select * from ticket_flights order by flight_id) tf using(ticket_no) group by 1,2) group by 1 having count(*)>1);
-- name: same_class_within_ticket
select count(*) tickets, sum(nc=1) single_class from (select ticket_no, count(distinct fare_conditions) nc from ticket_flights group by 1);
-- name: lead_time_days_first_leg
-- book_date to earliest scheduled departure in the booking
select cast(lead as int) d, count(*) from (select b.book_ref, julianday(min(substr(f.scheduled_departure,1,19))) - julianday(substr(b.book_date,1,19)) lead
  from bookings b join tickets t using(book_ref) join ticket_flights tf using(ticket_no) join flights f using(flight_id) group by 1) group by 1 order by 1;
-- name: lead_time_extremes
select min(lead)*24 min_h, max(lead) max_d, avg(lead) mean_d from (select b.book_ref, julianday(min(substr(f.scheduled_departure,1,19))) - julianday(substr(b.book_date,1,19)) lead
  from bookings b join tickets t using(book_ref) join ticket_flights tf using(ticket_no) join flights f using(flight_id) group by 1);
-- name: bookings_per_day
select substr(book_date,1,10) d, count(*) from bookings group by 1 order by 1;
-- name: book_minute_granularity
select substr(book_date,18,2) sec, count(*) from bookings group by 1;
-- name: book_hour_of_day
select substr(book_date,12,2) h, count(*) from bookings group by 1 order by 1;
-- name: total_amount_quantiles
select min(total_amount), avg(total_amount), max(total_amount) from bookings;
-- name: amount_vs_legs
-- Economy fare per flight_no: which tickets get the higher of two amounts
select legs, tf.amount = mx.hi is_hi, count(*) from ticket_flights tf
 join flights f using(flight_id)
 join (select f2.flight_no, tf2.fare_conditions, max(tf2.amount) hi, min(tf2.amount) lo from ticket_flights tf2 join flights f2 using(flight_id) group by 1,2 having count(distinct tf2.amount)=2) mx
   on mx.flight_no=f.flight_no and mx.fare_conditions=tf.fare_conditions
 join (select ticket_no, count(*) legs from ticket_flights group by 1) l using(ticket_no)
group by 1,2 order by 1,2;
-- name: hi_lo_ratio
select round(avg(1.0*hi/lo),4), min(1.0*hi/lo), max(1.0*hi/lo), count(*) from (select f2.flight_no, tf2.fare_conditions, max(tf2.amount) hi, min(tf2.amount) lo from ticket_flights tf2 join flights f2 using(flight_id) group by 1,2 having count(distinct tf2.amount)=2);
