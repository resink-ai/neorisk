"""How far are driver_standings / constructor_standings / constructor_results functions of results (+ sprint_results)?
Usage: python3 -I p6_standings_probe.py data/spider2/f1.sqlite"""
import sqlite3, sys, collections
con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
races = {rid: (y, rd) for rid, y, rd in con.execute("select race_id, year, round from races")}
res = con.execute("select race_id, driver_id, constructor_id, points, position from results").fetchall()
spr = con.execute("select race_id, driver_id, constructor_id, points, position from sprint_results").fetchall()
def per_race(rows, who):  # who: 1 driver, 2 constructor
    pts = collections.defaultdict(float); wins = collections.defaultdict(int)
    for r in rows:
        pts[(r[0], r[who])] += r[3]
        if r[4] == 1: wins[(r[0], r[who])] += 1
    return pts, wins
def check(table, idcol, who):
    st = con.execute(f"select race_id, {idcol}, points, position, position_text, wins from {table}").fetchall()
    stk = {(r, i): (p, pos, pt, w) for r, i, p, pos, pt, w in st}
    for label, rows in (("results only", res), ("results + sprint", res + spr)):
        pts, wins = per_race(rows, who)
        # cumulative within season, in round order
        season = collections.defaultdict(list)
        for rid, (y, rd) in races.items(): season[y].append((rd, rid))
        cum_p, cum_w = {}, {}
        for y, lst in season.items():
            acc_p = collections.defaultdict(float); acc_w = collections.defaultdict(int)
            for rd, rid in sorted(lst):
                for (r, i), p in pts.items():
                    pass
            # (faster below)
        by_race = collections.defaultdict(list)
        for (r, i), p in pts.items(): by_race[r].append(i)
        for y, lst in season.items():
            acc_p = collections.defaultdict(float); acc_w = collections.defaultdict(int)
            for rd, rid in sorted(lst):
                for i in by_race.get(rid, []):
                    acc_p[i] += pts[(rid, i)]; acc_w[i] += wins.get((rid, i), 0)
                for i in acc_p: cum_p[(rid, i)] = acc_p[i]; cum_w[(rid, i)] = acc_w[i]
        ok_p = sum(1 for k, v in stk.items() if k in cum_p and abs(cum_p[k] - v[0]) < 1e-9)
        ok_w = sum(1 for k, v in stk.items() if k in cum_w and cum_w[k] == v[3])
        have = sum(1 for k in stk if k in cum_p)
        print(f"{table:22s} {label:17s} rows {len(stk)}  key present {have}  points=cum {ok_p}  wins=cum {ok_w}")
        bad_years = collections.Counter(races[k[0]][0] for k, v in stk.items() if not (k in cum_p and abs(cum_p[k] - v[0]) < 1e-9))
        print("     years with point mismatches (year: rows):", dict(sorted(bad_years.items())))
    # position = rank by (points desc, ...)? check: is position consistent with points order within race
    inv = 0
    by = collections.defaultdict(list)
    for (r, i), v in stk.items(): by[r].append(v)
    for r, lst in by.items():
        lst.sort(key=lambda v: v[1])
        inv += sum(1 for a, b in zip(lst, lst[1:]) if a[0] < b[0] - 1e-9)
    print(f"     position order vs points: {inv} adjacent pairs where a better position has fewer points")
    pt_bad = sum(1 for v in stk.values() if v[2] != str(v[1]))
    print(f"     position_text != str(position): {pt_bad}; values {collections.Counter(v[2] for v in stk.values() if v[2] != str(v[1]))}")
check("driver_standings", "driver_id", 1)
check("constructor_standings", "constructor_id", 2)
# constructor_results: per race constructor points = sum over its results (+ sprint?)
cr = con.execute("select race_id, constructor_id, points, status from constructor_results").fetchall()
for label, rows in (("results only", res), ("results + sprint", res + spr)):
    pts, _ = per_race(rows, 2)
    ok = sum(1 for r, c, p, s in cr if (r, c) in pts and abs(pts[(r, c)] - p) < 1e-9)
    print(f"constructor_results {label}: {ok}/{len(cr)} equal; keys in results {sum(1 for r,c,p,s in cr if (r,c) in pts)}; (race,constructor) pairs in results {len(pts)}")
    bad = collections.Counter(races[r][0] for r, c, p, s in cr if not ((r, c) in pts and abs(pts[(r, c)] - p) < 1e-9))
    print("     years with mismatches:", dict(sorted(bad.items())))
