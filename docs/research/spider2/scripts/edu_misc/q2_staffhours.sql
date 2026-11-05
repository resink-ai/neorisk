-- name: typeof
SELECT typeof(StaffMember) a, typeof(EventDate) b, typeof(EventTime) c, typeof(EventType) d, count(*) n FROM StaffHours GROUP BY 1,2,3,4;
-- name: formats
SELECT length(EventDate) ld, length(EventTime) lt, count(*) n, min(EventDate), max(EventDate), min(EventTime), max(EventTime) FROM StaffHours GROUP BY 1,2;
-- name: parse
SELECT sum(datetime(EventDate||' '||EventTime) IS NULL) unparsable, sum(time(EventTime) IS NULL) bad_time FROM StaffHours;
-- name: members
SELECT count(DISTINCT StaffMember) members, sum(EventType='Enter') enters, sum(EventType='Exit') exits FROM StaffHours;
-- name: per_member
SELECT StaffMember, count(*) n, sum(EventType='Enter') ent, sum(EventType='Exit') ex FROM StaffHours GROUP BY 1 ORDER BY 1;
-- name: dups
SELECT count(*) - (SELECT count(*) FROM (SELECT DISTINCT * FROM StaffHours)) full_dups, count(*) - (SELECT count(*) FROM (SELECT DISTINCT StaffMember, EventDate, EventTime FROM StaffHours)) same_moment FROM StaffHours;
-- name: dup_rows
SELECT StaffMember, EventDate, EventTime, group_concat(EventType) types, count(*) n FROM StaffHours GROUP BY 1,2,3 HAVING n > 1;
-- name: alternation
-- in time order per member: count consecutive same-type pairs (Enter,Enter) or (Exit,Exit)
SELECT sum(t = nt AND t='Enter') enter_enter, sum(t = nt AND t='Exit') exit_exit, sum(t <> nt) alternations, sum(t='Exit' AND pt IS NULL) starts_with_exit FROM (SELECT StaffMember, EventType t, lead(EventType) OVER w nt, lag(EventType) OVER w pt FROM StaffHours WINDOW w AS (PARTITION BY StaffMember ORDER BY EventDate, EventTime, rowid));
-- name: same_day_pairs
-- Enter followed by Exit on the same date
SELECT sum(t='Enter' AND nt='Exit' AND d=nd) same_day, sum(t='Enter' AND nt='Exit' AND d<>nd) cross_day FROM (SELECT EventType t, EventDate d, lead(EventType) OVER w nt, lead(EventDate) OVER w nd FROM StaffHours WINDOW w AS (PARTITION BY StaffMember ORDER BY EventDate, EventTime, rowid));
-- name: shift_hours
SELECT round((julianday(nd||' '||ntm) - julianday(d||' '||tm))*24, 2) hrs, count(*) n FROM (SELECT EventType t, EventDate d, EventTime tm, lead(EventType) OVER w nt, lead(EventDate) OVER w nd, lead(EventTime) OVER w ntm FROM StaffHours WINDOW w AS (PARTITION BY StaffMember ORDER BY EventDate, EventTime, rowid)) WHERE t='Enter' AND nt='Exit' GROUP BY 1 ORDER BY 2 DESC LIMIT 10;
-- name: rowid_order
SELECT sum(nk < k) desc_pairs, count(*) pairs FROM (SELECT EventDate||EventTime k, lead(EventDate||EventTime) OVER (ORDER BY rowid) nk FROM StaffHours) WHERE nk IS NOT NULL;
-- name: per_date
SELECT substr(EventDate,1,7) ym, count(*) n FROM StaffHours GROUP BY 1;
-- name: minute_grid
SELECT CAST(substr(EventTime,4,2) AS INT) % 5 = 0 on5, count(*) n FROM StaffHours GROUP BY 1;
-- name: hours
SELECT EventType, substr(EventTime,1,2) hh, count(*) n FROM StaffHours GROUP BY 1,2 ORDER BY 1,2;
-- name: rows_tail
SELECT rowid, * FROM StaffHours WHERE rowid > 200 LIMIT 36;
