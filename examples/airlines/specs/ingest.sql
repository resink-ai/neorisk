-- Airlines: source tables → events (refdata ingest). '+03' wall clock is stored as UTC;
-- N = '2017-08-15 18:00:00' caps every invented time.

-- entity: aircrafts
SELECT aircraft_code AS ext_id, model, range FROM aircrafts_data ORDER BY aircraft_code;

-- entity: airports
SELECT airport_code AS ext_id, airport_name, city, coordinates, timezone
FROM airports_data ORDER BY airport_code;

-- entity: seats
SELECT aircraft_code || '/' || seat_no AS ext_id, aircraft_code AS aircraft_key, seat_no,
       fare_conditions
FROM seats ORDER BY aircraft_code, seat_no;

-- event: flight_scheduled owner=flight_id
SELECT MIN(datetime(substr(scheduled_departure, 1, 19), '-30 days'), '2017-08-15 18:00:00')
           AS event_time,
       flight_id, flight_no, substr(scheduled_departure, 1, 19) AS scheduled_departure,
       substr(scheduled_arrival, 1, 19) AS scheduled_arrival,
       departure_airport, arrival_airport, aircraft_code AS aircraft_key
FROM flights ORDER BY flight_id;

-- event: flight_cancelled owner=flight_id ord=k
SELECT MIN(datetime(substr(scheduled_departure, 1, 19), '-30 days'), '2017-08-15 18:00:00')
           AS event_time, flight_id, 1 AS k
FROM flights WHERE status = 'Cancelled' ORDER BY flight_id;

-- event: checkin_opened owner=flight_id
SELECT datetime(substr(scheduled_departure, 1, 19), '-24 hours') AS event_time, flight_id
FROM flights WHERE status IN ('On Time', 'Delayed', 'Departed', 'Arrived') ORDER BY flight_id;

-- event: flight_delayed owner=flight_id ord=k
SELECT datetime(substr(scheduled_departure, 1, 19), '-24 hours') AS event_time, flight_id,
       1 AS k
FROM flights WHERE status = 'Delayed' ORDER BY flight_id;

-- event: flight_departed owner=flight_id
SELECT substr(actual_departure, 1, 19) AS event_time, flight_id FROM flights
WHERE actual_departure <> '\N' ORDER BY flight_id;

-- event: flight_arrived owner=flight_id
SELECT substr(actual_arrival, 1, 19) AS event_time, flight_id FROM flights
WHERE actual_arrival <> '\N' ORDER BY flight_id;

-- event: booking_created owner=book_ref
SELECT substr(book_date, 1, 19) AS event_time, book_ref FROM bookings ORDER BY book_ref;

-- event: ticket_issued owner=book_ref ord=k
SELECT substr(b.book_date, 1, 19) AS event_time, t.ticket_no, t.book_ref, t.passenger_id,
       1 AS k
FROM tickets t JOIN bookings b USING (book_ref) ORDER BY t.ticket_no;

-- event: segment_sold owner=book_ref ord=k
SELECT substr(b.book_date, 1, 19) AS event_time, tf.ticket_no, tf.flight_id,
       tf.fare_conditions, tf.amount * 100 AS amount, t.book_ref, 2 AS k
FROM ticket_flights tf JOIN tickets t USING (ticket_no) JOIN bookings b USING (book_ref)
ORDER BY tf.ticket_no, tf.flight_id;

-- event: passenger_checked_in owner=flight_id ord=boarding_no
SELECT MIN(strftime('%Y-%m-%d %H:%M:%f', substr(f.scheduled_departure, 1, 19),
                    printf('%+.3f seconds', -7800 + 2400.0 * bp.boarding_no / n.n)),
           '2017-08-15 18:00:00.000') AS event_time,
       bp.ticket_no, bp.flight_id, bp.boarding_no, bp.seat_no
FROM boarding_passes bp JOIN flights f USING (flight_id)
JOIN (SELECT flight_id, COUNT(*) AS n FROM boarding_passes GROUP BY flight_id) n USING (flight_id)
ORDER BY bp.flight_id, bp.boarding_no;
