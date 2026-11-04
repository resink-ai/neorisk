-- SWITRS: events → source tables (refdata rebuild, DuckDB). case_id always comes from the
-- payload (f64), never from the log's entity key. Party, victim and case_ids times are rules
-- and are dropped: none of those tables has a time column.

-- table: collisions
-- One collision_occurred and one collision_processed per case (case_id is unique).
SELECT o.* EXCLUDE (event_id, event_type, event_time, seq, partition_id, cause_id, action_id,
                    time_known),
       strftime(o.event_time AT TIME ZONE 'UTC', '%Y-%m-%d') AS collision_date,
       CASE WHEN o.time_known = 1
            THEN strftime(o.event_time AT TIME ZONE 'UTC', '%H:%M:%S') END AS collision_time,
       strftime(p.event_time AT TIME ZONE 'UTC', '%Y-%m-%d') AS process_date
FROM collision_occurred o JOIN collision_processed p ON p.case_id = o.case_id;

-- table: case_ids
SELECT case_id, db_year FROM case_indexed;

-- table: parties
SELECT * EXCLUDE (event_id, event_type, event_time, seq, partition_id, cause_id, action_id)
FROM party_recorded;

-- table: victims
SELECT * EXCLUDE (event_id, event_type, event_time, seq, partition_id, cause_id, action_id)
FROM victim_recorded;
