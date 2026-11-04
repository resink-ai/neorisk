"""Are the 4 tables independent samples? Overlap-based sampling-fraction estimates, plus stage-2 distributions.
Usage: python3 -I p3_sampling_dists.py  (from repo root; DB mode=ro)"""
import sqlite3, statistics as st
from datetime import date
DB = "data/spider2/California_Traffic_Collision.sqlite"
con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
q = lambda s: con.execute(s).fetchall()
coll = {r[0] for r in q("select case_id from collisions")}
cids = {r[0] for r in q("select case_id from case_ids")}
par = q("select case_id, party_number from parties")
vic = q("select case_id, party_number from victims")
pkeys = set(par)
n_c = len(coll)
f_from_p = sum(c in coll for c, _ in par) / len(par)
f_from_v = sum(c in coll for c, _ in vic) / len(vic)
f_from_k = len(cids & coll) / len(cids)
g_from_v = sum(k in pkeys for k in vic) / len(vic)
print(f"collision sampling fraction estimated from parties overlap: {f_from_p:.4%}; from victims: {f_from_v:.4%}; from case_ids: {f_from_k:.4%}")
print(f"  implied full collisions table: {n_c/f_from_p:,.0f} / {n_c/f_from_v:,.0f} / {n_c/f_from_k:,.0f}")
print(f"party sampling fraction from victims->(case,party) overlap: {g_from_v:.4%}; implied full parties: {len(par)/g_from_v:,.0f}")
# expected collisions with >=1 sampled party if parties are an independent g-sample: sum over collisions of 1-(1-g)^party_count
pc = q("select party_count from collisions")
exp = sum(1 - (1 - g_from_v) ** k for (k,) in pc)
print(f"collisions with >=1 sampled party: observed {len(coll & {x for x, _ in par})}, expected under independence {exp:,.0f}")
def qs(xs, ps=(.05, .25, .5, .75, .95, .99)):
    xs = sorted(xs); return {p: xs[int(p * (len(xs) - 1))] for p in ps}
print("party_age quantiles:", qs([r[0] for r in q("select party_age from parties where party_age is not null")]))
print("victim_age quantiles (excl 999):", qs([r[0] for r in q("select victim_age from victims where victim_age is not null and victim_age<999")]))
print("vehicle_year quantiles:", qs([r[0] for r in q("select vehicle_year from parties where vehicle_year is not null")]))
print("distance (ft) quantiles:", qs([r[0] for r in q("select distance from collisions")]))
# arrivals: collisions per day mean/var (dispersion) by year block
days = {}
for (d,) in q("select collision_date from collisions"): days[d] = days.get(d, 0) + 1
d0, d1 = date(2001, 1, 1), date(2021, 5, 30)
counts = [days.get(date.fromordinal(o).isoformat(), 0) for o in range(d0.toordinal(), d1.toordinal() + 1)]
print(f"collisions/day over {len(counts)} days: mean {st.mean(counts):.2f} var {st.pvariance(counts):.2f} zero-days {counts.count(0)}")
m = {}
for (mo, n) in q("select substr(collision_date,6,2), count(*) from collisions where collision_date < '2021-01-01' group by 1"): m[mo] = n
print("month mix 2001-2020:", m)
# victims per injury severity vs collision severity (matched only)
print("matched victims degree x collision severity:", q("select c.collision_severity, v.victim_degree_of_injury, count(*) from victims v join collisions c using(case_id) group by 1,2 order by 1,3 desc")[:12])
