-- Airlines: events → source tables at N (refdata rebuild, DuckDB).

-- table: aircrafts_data
SELECT ext_id AS aircraft_code, model, range FROM aircrafts;

-- table: airports_data
SELECT ext_id AS airport_code, airport_name, city, coordinates, timezone FROM airports;

-- table: seats
SELECT a.ext_id AS aircraft_code, s.seat_no, CAST(s.fare_conditions AS VARCHAR) AS fare_conditions
FROM seats s JOIN aircrafts a USING (aircraft_key);

-- table: flights
SELECT f.flight_id, f.flight_no,
       strftime(f.scheduled_departure AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S') || '+03'
           AS scheduled_departure,
       strftime(f.scheduled_arrival AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S') || '+03'
           AS scheduled_arrival,
       da.ext_id AS departure_airport, aa.ext_id AS arrival_airport,
       CASE WHEN c.flight_id IS NOT NULL THEN 'Cancelled'
            WHEN ar.flight_id IS NOT NULL THEN 'Arrived'
            WHEN dp.flight_id IS NOT NULL THEN 'Departed'
            WHEN dl.flight_id IS NOT NULL THEN 'Delayed'
            WHEN ck.flight_id IS NOT NULL THEN 'On Time'
            ELSE 'Scheduled' END AS status,
       ac.ext_id AS aircraft_code,
       COALESCE(strftime(dp.event_time AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S') || '+03', '\N')
           AS actual_departure,
       COALESCE(strftime(ar.event_time AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S') || '+03', '\N')
           AS actual_arrival
FROM flight_scheduled f
JOIN airports da ON da.airport_key = f.departure_airport
JOIN airports aa ON aa.airport_key = f.arrival_airport
JOIN aircrafts ac USING (aircraft_key)
LEFT JOIN flight_cancelled c USING (flight_id)
LEFT JOIN checkin_opened ck USING (flight_id)
LEFT JOIN flight_delayed dl USING (flight_id)
LEFT JOIN flight_departed dp USING (flight_id)
LEFT JOIN flight_arrived ar USING (flight_id);

-- table: bookings
SELECT b.book_ref,
       strftime(b.event_time AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S') || '+03' AS book_date,
       s.total // 100 AS total_amount
FROM booking_created b
JOIN (SELECT book_ref, SUM(amount) AS total FROM segment_sold GROUP BY book_ref) s
  USING (book_ref);

-- table: tickets
SELECT ticket_no, book_ref, passenger_id FROM ticket_issued;

-- table: ticket_flights
SELECT ticket_no, flight_id, CAST(fare_conditions AS VARCHAR) AS fare_conditions,
       amount // 100 AS amount
FROM segment_sold;

-- table: boarding_passes
SELECT ticket_no, flight_id, boarding_no, seat_no FROM passenger_checked_in;
