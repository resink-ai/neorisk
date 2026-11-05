"""lap_time_stats vs lap_times: which formula reproduces avg/stdev exactly (bitwise) or within 1e-9 rel.
Usage: python3 -I p2_lap_time_stats.py data/spider2/f1.sqlite"""
import sqlite3, sys, math, statistics
con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
laps = {}
for r, d, ms in con.execute("select race_id, driver_id, milliseconds from lap_times order by race_id, driver_id, lap"):
    laps.setdefault((r, d), []).append(ms)
# SQLite's own aggregates, as a candidate
sq = {(r, d): (am, asec) for r, d, am, asec in con.execute(
    "select race_id, driver_id, avg(milliseconds), avg(seconds) from lap_times group by 1,2")}
sq_var = {(r, d): v for r, d, v in con.execute(
    "with a as (select race_id, driver_id, avg(milliseconds) m from lap_times group by 1,2) "
    "select l.race_id, l.driver_id, avg((l.milliseconds-a.m)*(l.milliseconds-a.m)) from lap_times l join a using(race_id, driver_id) group by 1,2")}
stats = list(con.execute("select race_id, driver_id, avg_milliseconds, avg_seconds, stdev_milliseconds, stdev_seconds from lap_time_stats"))
print("rows lap_time_stats", len(stats), "pairs in lap_times", len(laps),
      "pairs missing", len(set(laps) - {(s[0], s[1]) for s in stats}), "extra", len({(s[0], s[1]) for s in stats} - set(laps)))
def close(a, b): return a == b or abs(a - b) <= 1e-9 * max(abs(a), abs(b))
cands = {
  "avg_ms = sqlite avg(ms)":            lambda k, s: (sq[k][0], s[2]),
  "avg_ms = python mean(ms) fsum/n":    lambda k, s: (math.fsum(laps[k]) / len(laps[k]), s[2]),
  "avg_s = sqlite avg(seconds)":        lambda k, s: (sq[k][1], s[3]),
  "avg_s = avg_ms/1000":                lambda k, s: (s[2] / 1000, s[3]),
  "stdev_ms = sqrt(sqlite avg((x-m)^2)) [population]": lambda k, s: (math.sqrt(sq_var[k]), s[4]),
  "stdev_ms = statistics.pstdev":       lambda k, s: (statistics.pstdev(laps[k]), s[4]),
  "stdev_ms = sqrt(E[x^2]-m^2)":        lambda k, s: (math.sqrt(max(0, sum(x*x for x in laps[k]) / len(laps[k]) - (sum(laps[k]) / len(laps[k]))**2)), s[4]),
  "stdev_ms = statistics.stdev [sample]": lambda k, s: (statistics.stdev(laps[k]) if len(laps[k]) > 1 else 0.0, s[4]),
  "stdev_s = stdev_ms/1000":            lambda k, s: (s[4] / 1000, s[5]),
  "avg_s = statistics.mean(ms/1000)":   lambda k, s: (statistics.mean([x / 1000 for x in laps[k]]), s[3]),
  "avg_s = sum(ms/1000)/n":             lambda k, s: (sum(x / 1000 for x in laps[k]) / len(laps[k]), s[3]),
  "avg_s = fsum(ms/1000)/n":            lambda k, s: (math.fsum(x / 1000 for x in laps[k]) / len(laps[k]), s[3]),
  "stdev_s = statistics.pstdev(ms/1000)": lambda k, s: (statistics.pstdev([x / 1000 for x in laps[k]]), s[5]),
}
for name, f in cands.items():
    ex = cl = 0
    for s in stats:
        k = (s[0], s[1]); a, b = f(k, s)
        ex += (a == b); cl += close(a, b)
    print(f"{name:55s} exact {ex:6d}/{len(stats)}  within1e-9 {cl:6d}/{len(stats)}")
print("single-lap pairs", sum(1 for v in laps.values() if len(v) == 1),
      "their stdev values", sorted({s[4] for s in stats if len(laps[(s[0], s[1])]) == 1})[:5])
