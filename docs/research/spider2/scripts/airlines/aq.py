"""Run named SQL queries read-only against Airlines.sqlite and print results.
Usage: python3 -I aq.py DB QUERYFILE [names...]   (blocks separated by lines '-- name: X')"""
import sqlite3, sys, time

db, qf = sys.argv[1], sys.argv[2]
src = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
con = sqlite3.connect(":memory:")
src.backup(con); src.close()          # in-memory copy; the source file is never written
for ddl in ("create index i_t_b on tickets(book_ref)", "create index i_t_t on tickets(ticket_no)",
            "create index i_b_b on bookings(book_ref)", "create index i_tf_t on ticket_flights(ticket_no, flight_id)",
            "create index i_tf_f on ticket_flights(flight_id)", "create index i_f_f on flights(flight_id)",
            "create index i_bp_t on boarding_passes(ticket_no, flight_id)", "create index i_bp_f on boarding_passes(flight_id)",
            "create index i_s on seats(aircraft_code, seat_no)"):
    con.execute(ddl)
blocks, name, buf = [], None, []
for line in open(qf, encoding="utf-8"):
    if line.startswith("-- name:"):
        if name: blocks.append((name, "".join(buf)))
        name, buf = line.split(":", 1)[1].strip(), []
    else:
        buf.append(line)
if name: blocks.append((name, "".join(buf)))
only = set(sys.argv[3:])
for name, sql in blocks:
    if only and name not in only: continue
    t = time.time()
    cur = con.execute(sql)
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    sys.stdout.flush(); print(f"### {name}  ({len(rows)} rows, {time.time()-t:.1f}s)")
    print(" | ".join(cols))
    for r in rows[:80]:
        print(" | ".join(str(x) for x in r))
    print()
