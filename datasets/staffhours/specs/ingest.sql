-- Staff hours: source table → events (refdata ingest). Each row is one clock event.
-- One date is impossible (2013-02-29, rowid 100). Its time is SQLite's normalisation of the text
-- (2013-03-01, a rule), and the event carries the source date text verbatim.

-- entity: staff
SELECT StaffMember AS ext_id, min(datetime(EventDate || ' ' || EventTime)) AS created_at
FROM StaffHours GROUP BY StaffMember ORDER BY StaffMember;

-- event: staff_clocked owner=staff_id ord=src_rowid
SELECT datetime(EventDate || ' ' || EventTime) AS event_time, StaffMember AS staff_id,
       EventType AS direction,
       CASE WHEN date(EventDate) IS NOT EventDate THEN EventDate END AS date_text,
       rowid AS src_rowid
FROM StaffHours ORDER BY rowid;
