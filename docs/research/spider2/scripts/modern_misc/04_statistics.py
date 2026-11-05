"""statistics (daily cumulative COVID cases/deaths for 4 states): increments and weekday effect.

Run: python3 -I docs/research/spider2/scripts/modern_misc/04_statistics.py
Uses the 1000 distinct rows (rows 11.. ; rows 1-10 are prepended copies).
"""
import datetime as dt
import sqlite3
import statistics as st
from collections import defaultdict

con = sqlite3.connect("file:data/spider2/modern_data.sqlite?mode=ro", uri=True)
print("rows 1-10 all recur in rows 11..:",
      con.execute("SELECT count(*) FROM statistics a WHERE rowid<=10 AND EXISTS (SELECT 1 FROM statistics b WHERE b.rowid>10 AND b.date=a.date AND b.state=a.state AND b.total_cases=a.total_cases AND b.total_deaths=a.total_deaths)").fetchone()[0])
print("rows 11.. distinct (date,state):",
      con.execute("SELECT count(*), count(DISTINCT date||state) FROM statistics WHERE rowid>10").fetchone())
print("rows 11.. physical order = (state, date):",
      con.execute("SELECT sum((b.state, b.date) < (a.state, a.date)) FROM statistics a JOIN statistics b ON b.rowid=a.rowid+1 WHERE a.rowid>10").fetchone()[0], "descents")
by = defaultdict(list)
for d, s, c, k in con.execute("SELECT date, state, total_cases, total_deaths FROM statistics WHERE rowid>10 ORDER BY state, date"):
    by[s].append((dt.date.fromisoformat(d[:10]), c, k))
for s, xs in by.items():
    inc = [b[1] - a[1] for a, b in zip(xs, xs[1:])]
    dinc = [b[2] - a[2] for a, b in zip(xs, xs[1:])]
    wd = defaultdict(list)
    for (a, b) in zip(xs, xs[1:]):
        wd[b[0].weekday()].append(b[1] - a[1])
    wkd = {k: round(st.mean(v)) for k, v in sorted(wd.items())}
    print(f"{s}: days {len(xs)} first {xs[0][0]} cases0 {xs[0][1]} last {xs[-1][0]} cases {xs[-1][1]} deaths {xs[-1][2]}"
          f" | new cases median {st.median(inc)} max {max(inc)} neg {sum(i<0 for i in inc)} | new deaths median {st.median(dinc)} neg {sum(i<0 for i in dinc)}"
          f" | CFR {xs[-1][2]/xs[-1][1]:.4f} | mean new cases by weekday(Mon=0) {wkd}")
