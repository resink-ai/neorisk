-- name: cancelled_with_actuals
select flight_id, flight_no, scheduled_departure, actual_departure, actual_arrival, status from flights where status='Cancelled' and actual_departure<>'\N';
-- name: cancelled_by_period
select case when scheduled_departure < '2017-08-15 18:00' then 'past' else 'future' end per, count(*),
 sum(exists(select 1 from ticket_flights tf where tf.flight_id=f.flight_id)) with_tickets,
 sum(exists(select 1 from boarding_passes bp where bp.flight_id=f.flight_id)) with_bp
from flights f where status='Cancelled' group by 1;
-- name: status_ticket_bp_coverage
select status, count(*) flights,
 sum(exists(select 1 from ticket_flights tf where tf.flight_id=f.flight_id)) with_tf,
 sum(exists(select 1 from boarding_passes bp where bp.flight_id=f.flight_id)) with_bp
from flights f group by 1 order by 2 desc;
-- name: tf_bp_by_status
select f.status, count(*) tf_rows, sum(bp.ticket_no is not null) with_bp, round(1.0*sum(bp.ticket_no is not null)/count(*),4) share
from ticket_flights tf join flights f using(flight_id) left join boarding_passes bp on bp.ticket_no=tf.ticket_no and bp.flight_id=tf.flight_id
group by 1 order by 2 desc;
-- name: arrived_flights_partial_bp
-- among Arrived flights with tickets: share of ticket_flights without a boarding pass
select count(*) n_flights, sum(nbp=ntf) all_have_bp, sum(nbp=0) none_have_bp, sum(nbp>0 and nbp<ntf) partial
from (select f.flight_id, count(tf.ticket_no) ntf, count(bp.ticket_no) nbp from flights f join ticket_flights tf using(flight_id)
      left join boarding_passes bp on bp.ticket_no=tf.ticket_no and bp.flight_id=tf.flight_id where f.status='Arrived' group by 1);
-- name: bp_window_by_hours_to_departure
-- for not-yet-departed flights, share of ticket_flights with a boarding pass by hours to scheduled departure from now
select cast((julianday(substr(f.scheduled_departure,1,19)) - julianday('2017-08-15 18:00:00'))*24 as int) h, f.status,
 count(*) tf, count(bp.ticket_no) bp
from flights f join ticket_flights tf using(flight_id) left join boarding_passes bp on bp.ticket_no=tf.ticket_no and bp.flight_id=tf.flight_id
where f.scheduled_departure >= '2017-08-15 16:00' and f.scheduled_departure < '2017-08-17' group by 1,2 order by 1,2;
-- name: overbooking
-- tickets sold per flight vs aircraft seat count, per class
select count(*) flight_class_pairs, sum(sold > cap) oversold, max(1.0*sold/cap) max_ratio
from (select tf.flight_id, tf.fare_conditions, count(*) sold,
        (select count(*) from seats s where s.aircraft_code=f.aircraft_code and s.fare_conditions=tf.fare_conditions) cap
      from ticket_flights tf join flights f using(flight_id) group by 1,2);
-- name: tf_class_not_on_aircraft
select f.aircraft_code, tf.fare_conditions, count(*) from ticket_flights tf join flights f using(flight_id)
where not exists (select 1 from seats s where s.aircraft_code=f.aircraft_code and s.fare_conditions=tf.fare_conditions) group by 1,2;
-- name: bp_seat_class_matches_tf_class
select count(*) n, sum(s.fare_conditions=tf.fare_conditions) matched from boarding_passes bp join ticket_flights tf using(ticket_no, flight_id)
 join flights f using(flight_id) join seats s on s.aircraft_code=f.aircraft_code and s.seat_no=bp.seat_no;
-- name: total_amount_vs_sum
select count(*) n, sum(b.total_amount = x.s) equal, sum(b.total_amount > x.s) greater, sum(b.total_amount < x.s) less, max(abs(b.total_amount-x.s)) maxdiff
from bookings b join (select t.book_ref, sum(tf.amount) s from tickets t join ticket_flights tf using(ticket_no) group by 1) x using(book_ref);
-- name: amounts_rounding
select sum(amount % 100 = 0) mult100, count(*), min(amount), max(amount) from ticket_flights;
-- name: fare_consistency_flightno_class
-- does (flight_no, fare_conditions) determine amount?
select count(*) groups, sum(n_amounts=1) single_amount, max(n_amounts) max_amounts from
 (select f.flight_no, tf.fare_conditions, count(distinct tf.amount) n_amounts from ticket_flights tf join flights f using(flight_id) group by 1,2);
-- name: fare_multi_examples
select f.flight_no, tf.fare_conditions, tf.amount, count(*) from ticket_flights tf join flights f using(flight_id)
where f.flight_no in (select f2.flight_no from ticket_flights tf2 join flights f2 using(flight_id) group by f2.flight_no, tf2.fare_conditions having count(distinct tf2.amount)>1 limit 3)
group by 1,2,3 order by 1,2,3;
-- name: fare_per_od_class
select count(*) groups, sum(n=1) single from (select f.departure_airport, f.arrival_airport, tf.fare_conditions, count(distinct tf.amount) n from ticket_flights tf join flights f using(flight_id) group by 1,2,3);
-- name: fare_ratio_by_class
-- per flight_no: median-ish ratio Business/Economy using min amounts
select round(avg(1.0*b/e),3) avg_bus_over_eco, min(1.0*b/e), max(1.0*b/e), count(*) from
 (select f.flight_no, min(case when fare_conditions='Business' then amount end) b, min(case when fare_conditions='Economy' then amount end) e
  from ticket_flights tf join flights f using(flight_id) group by 1) where b is not null and e is not null;
-- name: fare_comfort_ratio
select round(avg(1.0*c/e),3), min(1.0*c/e), max(1.0*c/e), count(*) from
 (select f.flight_no, min(case when fare_conditions='Comfort' then amount end) c, min(case when fare_conditions='Economy' then amount end) e
  from ticket_flights tf join flights f using(flight_id) group by 1) where c is not null and e is not null;
-- name: fare_by_class
select fare_conditions, count(*), min(amount), avg(amount), max(amount) from ticket_flights group by 1;
-- name: class_mix
select fare_conditions, count(*), round(1.0*count(*)/(select count(*) from ticket_flights),4) from ticket_flights group by 1;
-- name: per_flight_bp_fraction_near_now
select f.flight_id, f.status, f.scheduled_departure, f.actual_departure,
 round((julianday(substr(f.scheduled_departure,1,19)) - julianday('2017-08-15 18:00:00'))*1440) min_to_sched_dep,
 count(*) tf, count(bp.ticket_no) bp
from flights f join ticket_flights tf using(flight_id) left join boarding_passes bp on bp.ticket_no=tf.ticket_no and bp.flight_id=tf.flight_id
where f.scheduled_departure >= '2017-08-15 17:00' and f.scheduled_departure < '2017-08-15 21:30' group by 1 order by 3;
