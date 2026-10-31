-- name: ticket_no_vs_book_date
-- consecutive ticket_no: is book_date non-decreasing?
select count(*), sum(b2.book_date >= b1.book_date) nondecreasing, sum(t2.book_ref = t1.book_ref) same_booking from
 (select ticket_no, book_ref, row_number() over (order by ticket_no) rn from tickets) t1
 join (select ticket_no, book_ref, row_number() over (order by ticket_no) rn from tickets) t2 on t2.rn=t1.rn+1
 join bookings b1 on b1.book_ref=t1.book_ref join bookings b2 on b2.book_ref=t2.book_ref;
-- name: ticket_no_gaps
select count(*), max(cast(ticket_no as integer)) - min(cast(ticket_no as integer)) + 1 span from tickets;
-- name: book_ref_format
select length(book_ref) l, sum(book_ref glob '[0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F]') hex, count(*) from bookings group by 1;
-- name: passenger_id_format
select sum(passenger_id glob '[0-9][0-9][0-9][0-9] [0-9][0-9][0-9][0-9][0-9][0-9]') fmt, count(*) from tickets;
-- name: class_same_across_booking_per_leg
select count(*), sum(nc=1), sum(na=1) from (select t.book_ref, tf.flight_id, count(distinct tf.fare_conditions) nc, count(distinct tf.amount) na from tickets t join ticket_flights tf using(ticket_no) group by 1,2 having count(*)>1);
-- name: ticket_amount_vs_booking_parts
-- multi-ticket bookings: do all tickets have the same total?
select count(*), sum(n=1) from (select t.book_ref, count(distinct s) n from (select ticket_no, sum(amount) s from ticket_flights group by 1) x join tickets t using(ticket_no) group by 1 having count(*)>1);
-- name: legs_shape_overall
-- ticket returns to origin? first dep airport == last arr airport
select legs, sum(f1.departure_airport = fl.arrival_airport) returns_home, count(*) from
 (select ticket_no, count(*) legs, min(f.scheduled_departure) d1, max(f.scheduled_departure) dl from ticket_flights tf join flights f using(flight_id) group by 1) t
 join ticket_flights a on a.ticket_no=t.ticket_no join flights f1 on f1.flight_id=a.flight_id and f1.scheduled_departure=t.d1
 join ticket_flights b on b.ticket_no=t.ticket_no join flights fl on fl.flight_id=b.flight_id and fl.scheduled_departure=t.dl group by 1;
-- name: bp_window_fine
select f.flight_id, f.status, round((julianday(substr(f.scheduled_departure,1,19)) - julianday('2017-08-15 18:00:00'))*1440) min_to_dep, count(*) tf, count(bp.ticket_no) bp
from flights f join ticket_flights tf using(flight_id) left join boarding_passes bp on bp.ticket_no=tf.ticket_no and bp.flight_id=tf.flight_id
where f.scheduled_departure between '2017-08-15 19:25' and '2017-08-15 23:59' group by 1 order by 3;
-- name: seats_class_capacity_used_max
select f.aircraft_code, tf.fare_conditions, max(cnt) max_sold, (select count(*) from seats s where s.aircraft_code=f.aircraft_code and s.fare_conditions=tf.fare_conditions) cap
from (select flight_id, fare_conditions, count(*) cnt from ticket_flights group by 1,2) tf join flights f using(flight_id) group by 1,2;
-- name: haversine_check_local009
select max(d) from (select 2*6371*asin(sqrt(power(sin((radians(cast(substr(a2.coordinates, instr(a2.coordinates,',')+1, length(a2.coordinates)-instr(a2.coordinates,',')-1) as real)) - radians(cast(substr(a1.coordinates, instr(a1.coordinates,',')+1, length(a1.coordinates)-instr(a1.coordinates,',')-1) as real)))/2),2)
 + cos(radians(cast(substr(a1.coordinates, instr(a1.coordinates,',')+1, length(a1.coordinates)-instr(a1.coordinates,',')-1) as real)))*cos(radians(cast(substr(a2.coordinates, instr(a2.coordinates,',')+1, length(a2.coordinates)-instr(a2.coordinates,',')-1) as real)))
 * power(sin((radians(cast(substr(a2.coordinates,2,instr(a2.coordinates,',')-2) as real)) - radians(cast(substr(a1.coordinates,2,instr(a1.coordinates,',')-2) as real)))/2),2))) d
 from flights f join airports_data a1 on a1.airport_code=f.departure_airport join airports_data a2 on a2.airport_code=f.arrival_airport
 where json_extract(a1.city,'$.en')='Abakan' or json_extract(a2.city,'$.en')='Abakan');
