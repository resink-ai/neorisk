-- name: unsold_flights_vs_unsold_flightnos
select count(*) unsold_noncancelled,
 sum(f.flight_no in (select f2.flight_no from flights f2 where not exists(select 1 from ticket_flights tf where tf.flight_id=f2.flight_id) group by 1
       having count(*)=(select count(*) from flights f3 where f3.flight_no=f2.flight_no))) in_never_sold_flightno
from flights f where status<>'Cancelled' and not exists(select 1 from ticket_flights tf where tf.flight_id=f.flight_id);
-- name: unsold_by_date_edge
select substr(scheduled_departure,1,10) d, count(*) n, sum(not exists(select 1 from ticket_flights tf where tf.flight_id=f.flight_id)) unsold from flights f
where status<>'Cancelled' and (scheduled_departure < '2017-07-20' or scheduled_departure >= '2017-09-08') group by 1 order by 1;
-- name: hi_fare_ticket_level
-- among tickets with >=1 leg in a two-price group: are hi legs all-or-nothing within ticket?
select nhi = nlegs all_hi, nhi=0 none_hi, count(*) from (
 select tf.ticket_no, count(*) nlegs, sum(tf.amount=g.hi) nhi from ticket_flights tf join flights f using(flight_id)
 join (select f2.flight_no, tf2.fare_conditions, max(tf2.amount) hi from ticket_flights tf2 join flights f2 using(flight_id) group by 1,2 having count(distinct tf2.amount)=2) g
   on g.flight_no=f.flight_no and g.fare_conditions=tf.fare_conditions group by 1) group by 1,2;
-- name: hi_fare_by_dow
select strftime('%w', substr(f.scheduled_departure,1,19)) dow, sum(tf.amount=g.hi), count(*) from ticket_flights tf join flights f using(flight_id)
 join (select f2.flight_no, tf2.fare_conditions, max(tf2.amount) hi from ticket_flights tf2 join flights f2 using(flight_id) group by 1,2 having count(distinct tf2.amount)=2) g
   on g.flight_no=f.flight_no and g.fare_conditions=tf.fare_conditions group by 1;
-- name: load_factor_by_aircraft
-- sold seats / seats, flights with >=1 ticket, departed or arrived
select f.aircraft_code, count(*) flights, round(avg(1.0*x.sold/c.cap),3) avg_lf, min(1.0*x.sold/c.cap) min_lf, max(1.0*x.sold/c.cap) max_lf, sum(x.sold=c.cap) n_full
from flights f join (select flight_id, count(*) sold from ticket_flights group by 1) x using(flight_id)
join (select aircraft_code, count(*) cap from seats group by 1) c using(aircraft_code)
where f.status in ('Arrived','Departed') group by 1 order by 1;
-- name: load_factor_hist
select cast(10*1.0*x.sold/c.cap as int)*10 lf_pct, count(*) from flights f join (select flight_id, count(*) sold from ticket_flights group by 1) x using(flight_id)
join (select aircraft_code, count(*) cap from seats group by 1) c using(aircraft_code) where f.status in ('Arrived','Departed') group by 1 order by 1;
-- name: load_factor_future
select f.status, count(*), round(avg(1.0*x.sold/c.cap),3) from flights f join (select flight_id, count(*) sold from ticket_flights group by 1) x using(flight_id)
join (select aircraft_code, count(*) cap from seats group by 1) c using(aircraft_code) group by 1;
-- name: load_factor_by_week
select strftime('%Y-%W', substr(f.scheduled_departure,1,19)) wk, round(avg(1.0*x.sold/c.cap),3) lf, count(*) from flights f join (select flight_id, count(*) sold from ticket_flights group by 1) x using(flight_id)
join (select aircraft_code, count(*) cap from seats group by 1) c using(aircraft_code) group by 1 order by 1;
-- name: dep_delay_minutes
select (julianday(substr(actual_departure,1,19))-julianday(substr(scheduled_departure,1,19)))*1440 dmin, status from flights where actual_departure<>'\N' and status in ('Arrived','Departed');
-- name: delay_hist
select case when d<0 then '<0' when d<=1 then '0-1' when d<=3 then '2-3' when d<=5 then '4-5' when d<=10 then '6-10' when d<=30 then '11-30' when d<=60 then '31-60' when d<=180 then '61-180' else '>180' end b,
 count(*), min(d), max(d) from (select round((julianday(substr(actual_departure,1,19))-julianday(substr(scheduled_departure,1,19)))*1440) d from flights where actual_departure<>'\N' and status in ('Arrived','Departed')) group by 1 order by min(d);
-- name: arr_minus_dep_delay
-- actual block time minus scheduled block time, minutes
select case when x<-10 then '<-10' when x<-3 then '-10..-4' when x<=3 then '-3..3' when x<=10 then '4..10' else '>10' end b, count(*), min(x), max(x), avg(x) from
 (select round(((julianday(substr(actual_arrival,1,19))-julianday(substr(actual_departure,1,19))) - (julianday(substr(scheduled_arrival,1,19))-julianday(substr(scheduled_departure,1,19))))*1440) x
  from flights where status='Arrived') group by 1 order by min(x);
-- name: sched_duration_constant_per_flightno
select count(*), sum(nd=1) from (select flight_no, count(distinct (julianday(substr(scheduled_arrival,1,19))-julianday(substr(scheduled_departure,1,19)))*1440) nd,
 count(distinct substr(scheduled_departure,12,5)) nt from flights group by 1);
-- name: dep_time_constant_per_flightno
select count(*), sum(nt=1) from (select flight_no, count(distinct substr(scheduled_departure,12,5)) nt from flights group by 1);
-- name: frequency_per_flightno
select n, count(*) flight_nos from (select flight_no, count(*) n from flights group by 1) group by 1 order by 1;
-- name: weekly_pattern
-- days-of-week set per flight_no: number of distinct DOWs
select ndow, count(*) from (select flight_no, count(distinct strftime('%w', substr(scheduled_departure,1,19))) ndow from flights group by 1) group by 1 order by 1;
-- name: status_windows
select status, min((julianday(substr(scheduled_departure,1,19))-julianday('2017-08-15 18:00:00'))*24) min_h_from_now,
 max((julianday(substr(scheduled_departure,1,19))-julianday('2017-08-15 18:00:00'))*24) max_h_from_now,
 min((julianday(substr(scheduled_arrival,1,19))-julianday('2017-08-15 18:00:00'))*24) min_arr_h, max((julianday(substr(scheduled_arrival,1,19))-julianday('2017-08-15 18:00:00'))*24) max_arr_h
from flights group by 1;
-- name: departed_arrived_vs_now
select status, max(actual_departure), max(actual_arrival), min(actual_arrival) from flights where status in ('Departed','Arrived') and scheduled_departure > '2017-08-15 12:00' group by 1;
-- name: departed_expected_arrival
-- Departed: actual_departure + sched block > now?
select count(*), sum(julianday(substr(actual_departure,1,19)) + (julianday(substr(scheduled_arrival,1,19))-julianday(substr(scheduled_departure,1,19))) > julianday('2017-08-15 18:00:00')) arr_after_now from flights where status='Departed';
-- name: delayed_flights
select flight_id, scheduled_departure, round((julianday(substr(scheduled_departure,1,19))-julianday('2017-08-15 18:00:00'))*24,2) h from flights where status='Delayed' order by 2 limit 50;
-- name: cancelled_rate_by_aircraft_period
select aircraft_code, sum(status='Cancelled'), count(*), round(1.0*sum(status='Cancelled')/count(*),4) from flights group by 1;
-- name: cancelled_rate_past_future
select scheduled_departure < '2017-08-15 18:00' past, sum(status='Cancelled'), count(*) from flights group by 1;
-- name: delayed_share_among_checkin_window
select status, count(*) from flights where scheduled_departure > '2017-08-15 18:00' and scheduled_departure <= '2017-08-16 18:00' group by 1;
