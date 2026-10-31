-- name: hi_fare_explainers
-- for (flight_no, class) groups with two amounts: is the higher amount tied to one specific flight date or to the ticket?
select count(*) groups_x_flights, sum(nam=1) flights_single_amount from
 (select tf.flight_id, tf.fare_conditions, count(distinct tf.amount) nam from ticket_flights tf join flights f using(flight_id)
  join (select f2.flight_no, tf2.fare_conditions from ticket_flights tf2 join flights f2 using(flight_id) group by 1,2 having count(distinct tf2.amount)=2) g
    on g.flight_no=f.flight_no and g.fare_conditions=tf.fare_conditions group by 1,2);
-- name: hi_fare_vs_class_mix_of_ticket
-- higher amount when the ticket mixes classes?
select x.mixed, tf.amount=g.hi is_hi, count(*) from ticket_flights tf join flights f using(flight_id)
 join (select f2.flight_no, tf2.fare_conditions, max(tf2.amount) hi from ticket_flights tf2 join flights f2 using(flight_id) group by 1,2 having count(distinct tf2.amount)=2) g
   on g.flight_no=f.flight_no and g.fare_conditions=tf.fare_conditions
 join (select ticket_no, count(distinct fare_conditions)>1 mixed from ticket_flights group by 1) x using(ticket_no)
group by 1,2;
-- name: hi_fare_vs_lead
select cast(julianday(substr(f.scheduled_departure,1,19)) - julianday(substr(b.book_date,1,19)) as int)/5*5 lead5, sum(tf.amount=g.hi) hi, count(*) n
from ticket_flights tf join flights f using(flight_id) join tickets t using(ticket_no) join bookings b using(book_ref)
 join (select f2.flight_no, tf2.fare_conditions, max(tf2.amount) hi from ticket_flights tf2 join flights f2 using(flight_id) group by 1,2 having count(distinct tf2.amount)=2) g
   on g.flight_no=f.flight_no and g.fare_conditions=tf.fare_conditions group by 1 order by 1;
-- name: two_leg_shape
-- 2-leg tickets: is it A->B, B->A (round trip) or A->B->C (connection)?
select case when f1.arrival_airport=f2.departure_airport and f2.arrival_airport=f1.departure_airport then 'roundtrip'
            when f1.arrival_airport=f2.departure_airport then 'connection' else 'other' end shape, count(*),
 avg(julianday(substr(f2.scheduled_departure,1,19))-julianday(substr(f1.scheduled_arrival,1,19))) avg_gap_days,
 min(julianday(substr(f2.scheduled_departure,1,19))-julianday(substr(f1.scheduled_arrival,1,19)))*24 min_gap_h,
 max(julianday(substr(f2.scheduled_departure,1,19))-julianday(substr(f1.scheduled_arrival,1,19))) max_gap_d
from (select ticket_no, min(f.scheduled_departure) d1, max(f.scheduled_departure) d2 from ticket_flights join flights f using(flight_id) group by 1 having count(*)=2) t
 join ticket_flights a on a.ticket_no=t.ticket_no join flights f1 on f1.flight_id=a.flight_id and f1.scheduled_departure=t.d1
 join ticket_flights b on b.ticket_no=t.ticket_no join flights f2 on f2.flight_id=b.flight_id and f2.scheduled_departure=t.d2
group by 1;
-- name: connection_gaps_all
-- consecutive legs on any ticket: gap between arrival and next departure, connecting (same airport) only
select case when gap_h < 24 then 'connection<24h' else 'stay>=24h' end k, count(*), min(gap_h), avg(gap_h), max(gap_h) from (
 select (julianday(substr(nf.scheduled_departure,1,19)) - julianday(substr(f.scheduled_arrival,1,19)))*24 gap_h
 from (select tf.ticket_no, f.flight_id, f.scheduled_departure, row_number() over (partition by tf.ticket_no order by f.scheduled_departure) rn
       from ticket_flights tf join flights f using(flight_id)) a
 join (select tf.ticket_no, f.flight_id, row_number() over (partition by tf.ticket_no order by f.scheduled_departure) rn
       from ticket_flights tf join flights f using(flight_id)) b on b.ticket_no=a.ticket_no and b.rn=a.rn+1
 join flights f on f.flight_id=a.flight_id join flights nf on nf.flight_id=b.flight_id) group by 1;
-- name: tickets_spanning_now
select count(*) from (select tf.ticket_no, min(f.scheduled_departure) d1, max(f.scheduled_departure) d2 from ticket_flights tf join flights f using(flight_id) group by 1)
where d1 < '2017-08-15 18:00' and d2 >= '2017-08-15 18:00';
-- name: boarding_no_consecutive
select count(*) flights, sum(mx=n and mn=1) consecutive from (select flight_id, max(boarding_no) mx, min(boarding_no) mn, count(*) n from boarding_passes group by 1);
-- name: boarding_order_vs_class
select s.fare_conditions, avg(1.0*bp.boarding_no/x.n) avg_rel_boarding_no, count(*)
from boarding_passes bp join (select flight_id, count(*) n from boarding_passes group by 1) x using(flight_id)
join flights f using(flight_id) join seats s on s.aircraft_code=f.aircraft_code and s.seat_no=bp.seat_no group by 1;
-- name: boarding_order_vs_ticket_no
-- Spearman-ish: share of consecutive boarding_no pairs where ticket_no increases
select count(*), sum(b.ticket_no > a.ticket_no) inc from boarding_passes a join boarding_passes b on b.flight_id=a.flight_id and b.boarding_no=a.boarding_no+1;
-- name: boarding_order_vs_book_date
select count(*), sum(bb.book_date > ba.book_date) later, sum(bb.book_date = ba.book_date) same from boarding_passes a join boarding_passes b on b.flight_id=a.flight_id and b.boarding_no=a.boarding_no+1
 join tickets ta on ta.ticket_no=a.ticket_no join bookings ba on ba.book_ref=ta.book_ref
 join tickets tb on tb.ticket_no=b.ticket_no join bookings bb on bb.book_ref=tb.book_ref;
-- name: boarding_same_booking_adjacent
select count(*), sum(ta.book_ref=tb.book_ref) same_booking from boarding_passes a join boarding_passes b on b.flight_id=a.flight_id and b.boarding_no=a.boarding_no+1
 join tickets ta on ta.ticket_no=a.ticket_no join tickets tb on tb.ticket_no=b.ticket_no;
-- name: seat_order_example
select bp.boarding_no, bp.seat_no, s.fare_conditions, bp.ticket_no from boarding_passes bp join flights f using(flight_id) join seats s on s.aircraft_code=f.aircraft_code and s.seat_no=bp.seat_no where flight_id=30625 order by boarding_no limit 40;
-- name: seat_rowid_order_vs_boarding
-- is seat chosen = next free seat in the seats table order? compare seat rank (rowid in seats) with boarding_no rank inside class
select count(*), sum(sr_next > sr) increasing from (
 select a.flight_id, sa.rowid sr, sb.rowid sr_next from boarding_passes a join boarding_passes b on b.flight_id=a.flight_id and b.boarding_no=a.boarding_no+1
 join flights f on f.flight_id=a.flight_id join seats sa on sa.aircraft_code=f.aircraft_code and sa.seat_no=a.seat_no
 join seats sb on sb.aircraft_code=f.aircraft_code and sb.seat_no=b.seat_no where sa.fare_conditions=sb.fare_conditions);
