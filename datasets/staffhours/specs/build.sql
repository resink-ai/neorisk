-- Staff hours: events → source table (refdata rebuild, DuckDB), in source rowid order.

-- table: StaffHours
SELECT s.ext_id AS StaffMember,
       coalesce(c.date_text, strftime(c.event_time AT TIME ZONE 'UTC', '%Y-%m-%d')) AS EventDate,
       strftime(c.event_time AT TIME ZONE 'UTC', '%H:%M') AS EventTime, c.direction AS EventType
FROM staff_clocked c JOIN staff s USING (staff_id) ORDER BY c.src_rowid;
