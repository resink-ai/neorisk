"""Generator fingerprints in aliens / aliens_details / aliens_location:
- the Mockaroo email pattern: lower(first initial + last name, letters only) + base36(id - 1) + '@' + domain
- uniformity of categorical columns and of birth_year, independence between tables (chi-square-ish summaries)
Usage: python3 -I f1_generator.py DB"""
import re, sqlite3, sys
from collections import Counter

con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)

def b36(n):
    s = "0123456789abcdefghijklmnopqrstuvwxyz"; out = ""
    while True:
        n, r = divmod(n, 36); out = s[r] + out
        if n == 0: return out

rows = con.execute("select id, first_name, last_name, email from aliens").fetchall()
ok_suffix = ok_local = 0; bad = []
for i, fn, ln, em in rows:
    local, _, dom = em.partition("@")
    suf = b36(i - 1)
    if local.endswith(suf): ok_suffix += 1
    stem = re.sub(r"[^a-z]", "", (fn[0] + ln).lower())
    if local == stem + suf: ok_local += 1
    elif len(bad) < 5: bad.append((i, fn, ln, em))
print(f"emails: {len(rows)}; local part ends with base36(id-1): {ok_suffix}; equals lower(initial+last letters)+base36(id-1): {ok_local}")
print("  non-matching examples:", bad)
doms = Counter(e.split("@")[1] for *_, e in rows)
print(f"distinct email domains {len(doms)}; top {doms.most_common(5)}")

def mix(sql, label):
    c = con.execute(sql).fetchall(); n = sum(x[1] for x in c)
    vals = [x[1] for x in c]
    print(f"{label}: {len(c)} values, min {min(vals)} max {max(vals)} (mean {n/len(c):.1f}); {c[:10]}")

mix("select type, count(*) from aliens group by 1 order by 2 desc", "type")
mix("select gender, count(*) from aliens group by 1 order by 2 desc", "gender")
mix("select feeding_frequency, count(*) from aliens_details group by 1 order by 2 desc", "feeding_frequency")
mix("select aggressive, count(*) from aliens_details group by 1", "aggressive")
mix("select state, count(*) from aliens_location group by 1 order by 2 desc", "state")
mix("select occupation, count(*) from aliens_location group by 1 order by 2 desc", "occupation")
mix("select current_location, count(*) from aliens_location group by 1 order by 2 desc", "current_location")
mix("select favorite_food, count(*) from aliens_details group by 1 order by 2 desc", "favorite_food")
by = Counter(r[0] for r in con.execute("select birth_year from aliens"))
v = sorted(by.values())
print(f"birth_year: {len(by)} distinct years {min(by)}..{max(by)}; per-year count min {v[0]} median {v[len(v)//2]} max {v[-1]}")
# independence: aggressive share by type, and by feeding_frequency
for sql, lab in (("select a.type, avg(d.aggressive), count(*) from aliens a join aliens_details d on d.detail_id = a.id group by 1", "aggressive share by type"),
                 ("select d.feeding_frequency, avg(d.aggressive), count(*) from aliens_details d group by 1", "aggressive share by feeding_frequency"),
                 ("select a.type, avg(a.birth_year), count(*) from aliens a group by 1", "mean birth_year by type")):
    print(lab + ":", [(r[0], round(r[1], 4), r[2]) for r in con.execute(sql)])
# city/state consistency: does a city name map to one state?
c = con.execute("select count(*), sum(n > 1) from (select current_location, count(distinct state) n from aliens_location group by 1)").fetchone()
print(f"current_location values {c[0]}, of which mapped to >1 state: {c[1]}")
ex = con.execute("select current_location, group_concat(distinct state) from aliens_location group by 1 having count(distinct state) > 1 limit 5").fetchall()
print("  examples:", ex)
