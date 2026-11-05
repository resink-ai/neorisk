"""Probe: rebuild drives from results with a run-length rule; report mismatches.
Usage: python3 -I p4_drives_probe.py data/spider2/f1.sqlite"""
import sqlite3, sys, collections
con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
src = collections.Counter(con.execute("select * from drives"))
rows = con.execute("""select ra.year, r.driver_id, ra.round, r.constructor_id, r.result_id from results r join races ra using(race_id)
                      order by ra.year, r.driver_id, ra.round, r.result_id""").fetchall()
by = collections.defaultdict(list)
for y, d, rd, c, rid in rows: by[(y, d)].append((rd, c))
def build(gap_rows=True, same_team_gap_breaks=False):
    out = collections.Counter()
    for (y, d), lst in by.items():
        runs = []
        for rd, c in lst:
            if runs and runs[-1][0] == c and not (same_team_gap_breaks and rd > runs[-1][2] + 1):
                runs[-1][2] = rd
            else:
                runs.append([c, rd, rd])
        n = len(runs); k = 0
        for i, (c, f, l) in enumerate(runs):
            k += 1
            out[(y, d, k, c, f, l, int(i == 0), int(i == n - 1))] += 1
            if gap_rows and i + 1 < n and runs[i + 1][1] > l + 1:
                out[(y, d, -1, -1, l + 1, runs[i + 1][1] - 1, 0, 0)] += 1
    return out
for args in [(True, False), (True, True), (False, False)]:
    b = build(*args)
    miss = src - b; extra = b - src
    print(f"gap_rows={args[0]} same_team_gap_breaks={args[1]}: rebuilt {sum(b.values())} src {sum(src.values())} src-not-rebuilt {sum(miss.values())} rebuilt-not-src {sum(extra.values())}")
    print("   e.g. missing", list(miss)[:5]); print("   e.g. extra  ", list(extra)[:5])
# Which driver-seasons differ under the best rule, and do they all have one round with 2+ constructors?
b = build(True, False)
bad = {(k[0], k[1]) for k in (src - b) + (b - src)}
multi = {(y, d) for (y, d), lst in by.items() if len({c for rd, c in lst if sum(1 for r2, c2 in lst if r2 == rd and c2 != c)}) > 0}
print("driver-seasons", len(by), "differing", len(bad), "of which with a round driven for 2+ constructors", len(bad & multi),
      "| driver-seasons with such a round", len(multi), "that still match", len(multi - bad))
src_rows_in_bad = sum(v for k, v in src.items() if (k[0], k[1]) in bad)
print("drives rows in differing driver-seasons:", src_rows_in_bad, "of", sum(src.values()))
print("differing:", sorted(bad))
