"""case_id (REAL) as a key: precision, text encodings, the 2001 date-coded format, and case_id vs date.
Usage: python3 -I p2_case_id.py   (from repo root; DB opened mode=ro)"""
import sqlite3, bisect
from datetime import date
DB = "data/spider2/California_Traffic_Collision.sqlite"
con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
T = ["collisions", "case_ids", "parties", "victims"]
allv = {}
for t in T:
    vals = [r[0] for r in con.execute(f"select case_id from {t}")]
    allv[t] = vals
    big = sum(v >= 2**53 for v in vals)
    nonint = sum(v != int(v) for v in vals)
    print(f"{t}: rows={len(vals)} distinct={len(set(vals))} >=2^53={big} non_integer={nonint} min={min(vals):.0f} max={max(vals):.0f}")
union = set().union(*allv.values())
print("union of distinct case_id over 4 tables:", len(union))
for t in T:
    others = set().union(*(set(allv[u]) for u in T if u != t))
    s = set(allv[t]); print(f"  {t}: distinct only here={len(s - others)}")
# text encodings: SQLite CAST AS TEXT (15 sig digits) vs printf('%.0f') (exact) vs Python repr
for enc, sql in [("cast_text", "cast(case_id as text)"), ("printf_.0f", "printf('%.0f', case_id)"), ("printf_.17g", "printf('%.17g', case_id)")]:
    rows = []
    for t in T:
        rows += con.execute(f"select case_id, {sql} from {t}").fetchall()
    m = {}
    for v, s in rows: m.setdefault(s, set()).add(v)
    collide = sum(len(x) > 1 for x in m.values())
    back = sum(float(s) == v for v, s in rows)
    print(f"encoding {enc}: distinct texts={len(m)} texts mapping to >1 value={collide} float(text)==value {back}/{len(rows)}")
# exactness of printf('%.0f') vs Python's exact integer of the double
rows = []
for t in T: rows += con.execute(f"select case_id, printf('%.0f', case_id) from {t}").fetchall()
print("printf('%.0f') == str(int(double)):", sum(s == str(int(v)) for v, s in rows), "/", len(rows))
# 2001 date-coded ids: 18-19 digits = jurisdiction + YYMMDDHHMM + tail
ok = n = 0; okt = 0
for cid, jur, d, tm in con.execute("select case_id, jurisdiction, collision_date, collision_time from collisions where case_id >= 1e17"):
    s = str(int(cid)); n += 1
    j = s[:-15]; rest = s[-15:]
    if jur is not None and int(j) == int(jur) and "20" + rest[:2] + "-" + rest[2:4] + "-" + rest[4:6] == d:
        ok += 1
        if tm is not None and rest[6:8] + ":" + rest[8:10] + ":00" == tm: okt += 1
print(f"date-coded ids (>=1e17) in collisions: {n}; jurisdiction+date decode matches {ok}; +HH:MM matches {okt}")
for t in ["parties", "victims", "case_ids"]:
    k = sum(v >= 1e17 for v in allv[t]); print(f"  {t}: date-coded ids {k}")
# case_id (7-8 digit counter) vs collision_date: how well does case_id predict the date?
pts = sorted((cid, date.fromisoformat(d).toordinal()) for cid, d in con.execute(
    "select case_id, collision_date from collisions where case_id < 1e17"))
inv = sum(pts[i][1] > pts[i + 1][1] for i in range(len(pts) - 1))
print(f"counter ids: {len(pts)}; adjacent (by case_id) pairs with date going backwards: {inv}")
# leave-one-out nearest-neighbour date error
errs = sorted(abs(pts[i][1] - (pts[i - 1][1] + pts[i + 1][1]) / 2) for i in range(1, len(pts) - 1))
q = lambda p: errs[int(p * (len(errs) - 1))]
print(f"  neighbour-interpolated date error, days: p50={q(.5)} p90={q(.9)} p99={q(.99)} max={errs[-1]}")
# by id range
for lo, hi in [(0, 1e7), (1e7, 9e7), (9e7, 1e9)]:
    sub = [p for p in pts if lo <= p[0] < hi]
    if sub: print(f"  ids [{lo:.0e},{hi:.0e}): n={len(sub)} dates {date.fromordinal(min(p[1] for p in sub))}..{date.fromordinal(max(p[1] for p in sub))}")
print("sqlite version:", sqlite3.sqlite_version)
