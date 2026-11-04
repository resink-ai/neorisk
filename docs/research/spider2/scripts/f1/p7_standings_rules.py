"""Refined rules: constructor points 1958-1978 = best car only; standings position = rank by points then countback.
Usage: python3 -I p7_standings_rules.py data/spider2/f1.sqlite"""
import sqlite3, sys, collections
con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
races = {rid: (y, rd) for rid, y, rd in con.execute("select race_id, year, round from races")}
rows = con.execute("select race_id, driver_id, constructor_id, points, position, 'R' from results union all "
                   "select race_id, driver_id, constructor_id, points, position, 'S' from sprint_results").fetchall()
def cons_race_points(best_car_years):
    acc = collections.defaultdict(list)
    for r, d, c, p, pos, kind in rows: acc[(r, c)].append(p)
    return {k: (max(v) if races[k[0]][0] in best_car_years else sum(v)) for k, v in acc.items()}
best = set(range(1958, 1979))
for label, yrs in (("sum of cars", set()), ("best car only 1958-1978", best)):
    crp = cons_race_points(yrs)
    cr = con.execute("select race_id, constructor_id, points from constructor_results").fetchall()
    bad = [(r, c, p, crp.get((r, c))) for r, c, p in cr if crp.get((r, c)) is None or abs(crp[(r, c)] - p) > 1e-9]
    print(f"constructor_results, {label}: {len(cr)-len(bad)}/{len(cr)} equal; mismatches by year {dict(sorted(collections.Counter(races[b[0]][0] for b in bad).items()))}")
    if yrs: print("   remaining:", bad[:12])
    # cumulative standings
    st = {(r, c): p for r, c, p in con.execute("select race_id, constructor_id, points from constructor_standings")}
    season = collections.defaultdict(list)
    for rid, (y, rd) in races.items(): season[y].append((rd, rid))
    byrace = collections.defaultdict(list)
    for (r, c) in crp: byrace[r].append(c)
    cum = {}
    for y, lst in season.items():
        a = collections.defaultdict(float)
        for rd, rid in sorted(lst):
            for c in byrace.get(rid, []): a[c] += crp[(rid, c)]
            for c in a: cum[(rid, c)] = a[c]
    bad = [k for k, p in st.items() if k not in cum or abs(cum[k] - p) > 1e-9]
    print(f"constructor_standings points, {label}: {len(st)-len(bad)}/{len(st)}; mismatches by year {dict(sorted(collections.Counter(races[k[0]][0] for k in bad).items()))}")
# constructor_results vs constructor pairs present in results
cr_keys = {(r, c) for r, c in con.execute("select race_id, constructor_id from constructor_results")}
res_keys = {(r, c) for r, d, c, p, pos, k in rows if k == 'R'}
print("constructor_results keys", len(cr_keys), "results (race,constructor) pairs", len(res_keys), "in cr not results", len(cr_keys - res_keys), "in results not cr", len(res_keys - cr_keys),
      "years of results-not-cr", dict(sorted(collections.Counter(races[k[0]][0] for k in res_keys - cr_keys).items())))
# standings keys vs results drivers so far in the season
ds = con.execute("select race_id, driver_id, points, position, wins from driver_standings").fetchall()
# position = rank by points desc, then countback of race finishing positions (1sts, 2nds, ...) so far
fin = collections.defaultdict(list)  # (year, driver) -> [(round, position)]
for r, d, c, p, pos, k in rows:
    if k == 'R' and pos is not None: fin[(races[r][0], d)].append((races[r][1], pos))
by = collections.defaultdict(list)
for r, d, p, pos, w in ds: by[r].append((d, p, pos))
ok = tot = 0; okp = 0
for r, lst in by.items():
    y, rd = races[r]
    def cb(d):
        c = collections.Counter(pos for rr, pos in fin[(y, d)] if rr <= rd)
        return tuple(-c[i] for i in range(1, 40))
    srt = sorted(lst, key=lambda t: (-t[1], cb(t[0])))
    for i, (d, p, pos) in enumerate(srt, 1):
        tot += 1; ok += (i == pos)
    # points-only rank (min rank on ties)
    for d, p, pos in lst:
        okp += (1 + sum(1 for d2, p2, _ in lst if p2 > p + 1e-9)) == pos
print(f"driver_standings position = rank by (points desc, countback): {ok}/{tot}; = rank(min) by points alone: {okp}/{tot}")
