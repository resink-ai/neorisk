-- name: reservation_groups
select (select count(*) from (select distinct t.book_ref, tf.flight_id from tickets t join ticket_flights tf using(ticket_no))) booking_flight,
       (select count(*) from (select distinct t.book_ref, tf.flight_id, tf.fare_conditions from tickets t join ticket_flights tf using(ticket_no))) booking_flight_class;
-- name: flight_id_vs_schedule
select count(*), sum(b.scheduled_departure >= a.scheduled_departure) nondecreasing, sum(b.flight_no=a.flight_no) same_flightno from flights a join flights b on b.flight_id=a.flight_id+1;
-- name: checkin_open_events
select sum(status in ('On Time','Delayed')) open_now, sum(status in ('Departed','Arrived')) departed, sum(status='Arrived') arrived from flights;
-- name: small_network_candidate
-- share of segments whose both endpoints are in the top-N airports by traffic
with top as (select ap from (select departure_airport ap, count(*) n from flights group by 1 order by n desc limit 15))
select (select group_concat(ap) from top) top15, sum(f.departure_airport in top and f.arrival_airport in top) seg_in, count(*) seg from ticket_flights tf join flights f using(flight_id);
-- name: closed_tickets_in_top15
with top as (select ap from (select departure_airport ap, count(*) n from flights group by 1 order by n desc limit 15))
select count(*) tickets, sum(bad=0) closed from (select tf.ticket_no, sum(not(f.departure_airport in top and f.arrival_airport in top)) bad from ticket_flights tf join flights f using(flight_id) group by 1);
