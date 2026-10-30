-- name: typeof_and_nulls
select 'flights.actual_departure' c, typeof(actual_departure) t, count(*) from flights group by 2
union all select 'flights.actual_arrival', typeof(actual_arrival), count(*) from flights group by 2
union all select 'bookings.total_amount', typeof(total_amount), count(*) from bookings group by 2
union all select 'ticket_flights.amount', typeof(amount), count(*) from ticket_flights group by 2
union all select 'bookings.book_date', typeof(book_date), count(*) from bookings group by 2
union all select 'flights.flight_id', typeof(flight_id), count(*) from flights group by 2;
-- name: backslash_N_counts
select sum(actual_departure='\N') ad_N, sum(actual_arrival='\N') aa_N, sum(actual_departure is null) ad_null, sum(actual_arrival is null) aa_null from flights;
-- name: tz_suffixes
select 'sched_dep' c, substr(scheduled_departure,20) s, count(*) from flights group by 2
union all select 'sched_arr', substr(scheduled_arrival,20), count(*) from flights group by 2
union all select 'act_dep', substr(actual_departure,20), count(*) from flights group by 2
union all select 'book_date', substr(book_date,20), count(*) from bookings group by 2;
-- name: pk_uniqueness
select 'aircrafts' t, count(*), count(distinct aircraft_code) from aircrafts_data
union all select 'airports', count(*), count(distinct airport_code) from airports_data
union all select 'seats', count(*), count(distinct aircraft_code||'/'||seat_no) from seats
union all select 'flights', count(*), count(distinct flight_id) from flights
union all select 'flights(no,date)', count(*), count(distinct flight_no||substr(scheduled_departure,1,10)) from flights
union all select 'bookings', count(*), count(distinct book_ref) from bookings
union all select 'tickets', count(*), count(distinct ticket_no) from tickets
union all select 'ticket_flights', count(*), count(distinct ticket_no||'/'||flight_id) from ticket_flights
union all select 'boarding_passes', count(*), count(distinct ticket_no||'/'||flight_id) from boarding_passes
union all select 'bp(flight,boarding_no)', count(*), count(distinct flight_id||'/'||boarding_no) from boarding_passes
union all select 'bp(flight,seat)', count(*), count(distinct flight_id||'/'||seat_no) from boarding_passes;
-- name: fk_coverage
select 'tickets.book_ref->bookings' fk, count(*) n, sum(b.book_ref is not null) ok from tickets t left join bookings b using(book_ref)
union all select 'bookings with >=1 ticket', count(*), sum(exists(select 1 from tickets t where t.book_ref=b.book_ref)) from bookings b
union all select 'ticket_flights.ticket_no->tickets', count(*), sum(t.ticket_no is not null) from ticket_flights tf left join tickets t using(ticket_no)
union all select 'tickets with >=1 ticket_flight', count(*), sum(exists(select 1 from ticket_flights tf where tf.ticket_no=t.ticket_no)) from tickets t
union all select 'ticket_flights.flight_id->flights', count(*), sum(f.flight_id is not null) from ticket_flights tf left join flights f using(flight_id)
union all select 'flights with >=1 ticket_flight', count(*), sum(exists(select 1 from ticket_flights tf where tf.flight_id=f.flight_id)) from flights f
union all select 'bp->ticket_flights', count(*), sum(tf.ticket_no is not null) from boarding_passes bp left join ticket_flights tf on tf.ticket_no=bp.ticket_no and tf.flight_id=bp.flight_id
union all select 'bp seat in seats of aircraft', count(*), sum(s.seat_no is not null) from boarding_passes bp join flights f using(flight_id) left join seats s on s.aircraft_code=f.aircraft_code and s.seat_no=bp.seat_no
union all select 'flights.aircraft->aircrafts', count(*), sum(a.aircraft_code is not null) from flights f left join aircrafts_data a using(aircraft_code)
union all select 'flights.dep->airports', count(*), sum(a.airport_code is not null) from flights f left join airports_data a on a.airport_code=f.departure_airport
union all select 'flights.arr->airports', count(*), sum(a.airport_code is not null) from flights f left join airports_data a on a.airport_code=f.arrival_airport
union all select 'seats.aircraft->aircrafts', count(*), sum(a.aircraft_code is not null) from seats s left join aircrafts_data a using(aircraft_code);
-- name: aircrafts_with_seats
select a.aircraft_code, json_extract(a.model,'$.en') model, a.range, count(s.seat_no) seats,
 sum(s.fare_conditions='Business') bus, sum(s.fare_conditions='Comfort') comf, sum(s.fare_conditions='Economy') eco,
 (select count(*) from flights f where f.aircraft_code=a.aircraft_code) flights
from aircrafts_data a left join seats s using(aircraft_code) group by 1 order by 1;
-- name: airports_summary
select count(*) n, count(distinct timezone) tzs, count(distinct json_extract(city,'$.en')) cities, sum(json_valid(airport_name)) valid_json from airports_data;
-- name: multi_airport_cities
select json_extract(city,'$.en') city, group_concat(airport_code) from airports_data group by 1 having count(*)>1;
-- name: time_ranges
select 'sched_dep' c, min(scheduled_departure), max(scheduled_departure) from flights
union all select 'actual_dep', min(actual_departure), max(case when actual_departure<>'\N' then actual_departure end) from flights where actual_departure<>'\N'
union all select 'actual_arr', min(actual_arrival), max(actual_arrival) from flights where actual_arrival<>'\N'
union all select 'book_date', min(book_date), max(book_date) from bookings;
-- name: status_counts
select status, count(*), sum(actual_departure<>'\N') has_ad, sum(actual_arrival<>'\N') has_aa,
 min(scheduled_departure), max(scheduled_departure) from flights group by 1 order by 2 desc;
-- name: routes
select count(distinct flight_no) flight_nos, count(distinct departure_airport||arrival_airport) od_pairs,
 (select count(*) from (select flight_no from flights group by 1 having count(distinct departure_airport||arrival_airport||aircraft_code)>1)) flightno_varying
from flights;
-- name: ticket_no_format
select substr(ticket_no,1,6) pfx, count(*), min(ticket_no), max(ticket_no) from tickets group by 1;
-- name: passenger_id_reuse
select count(*) n, count(distinct passenger_id) distinct_pid from tickets;
