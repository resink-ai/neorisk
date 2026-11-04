"""Check the proposed per-ball time rule on IPL.sqlite (read-only).
Rule: a match starts at 20:00 on match_date; on a day with two matches the lower match_id starts at 16:00.
Match 419136 (balls but no match row) takes the day between its id-neighbours' dates (rule, checked below).
Deliveries: the union of the four ball tables' keys, ordered (innings, over, ball), get index k = 1..n per innings.
time = start + (innings-1)*110 min + (k-1)*40 s. Toss and team sheets at start - 30 min; result at last ball + 5 min.
Usage: python3 -I p2_time_rule.py DB"""
import sqlite3, sys, datetime as dt
from collections import defaultdict, Counter
c = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
keys = c.execute("""SELECT match_id, innings_no, over_id, ball_id FROM ball_by_ball UNION SELECT match_id, innings_no, over_id, ball_id FROM batsman_scored
 UNION SELECT match_id, innings_no, over_id, ball_id FROM extra_runs UNION SELECT match_id, innings_no, over_id, ball_id FROM wicket_taken ORDER BY 1,2,3,4""").fetchall()
print("delivery keys (union of 4 tables):", len(keys))
dates = dict(c.execute("SELECT match_id, match_date FROM match"))
day_matches = defaultdict(list)
for m, d in dates.items(): day_matches[d].append(m)
print("days with n matches:", Counter(len(v) for v in day_matches.values()))
print("2010-03-29 matches in source:", day_matches.get("2010-03-29"))
dates[419136] = "2010-03-29"; day_matches["2010-03-29"].append(419136)
start = {}
for d, ms in day_matches.items():
    ms.sort()
    for i, m in enumerate(ms):
        h = 20 if (len(ms) == 1 or i == 1) else 16
        start[m] = dt.datetime.fromisoformat(d) + dt.timedelta(hours=h)
k = defaultdict(int); times = []; per_inn = Counter(); last = {}
for m, inn, ov, b in keys:
    k[(m, inn)] += 1
    t = start[m] + dt.timedelta(minutes=110 * (inn - 1), seconds=40 * (k[(m, inn)] - 1))
    times.append((m, t)); per_inn[(m, inn)] += 1; last[m] = max(last.get(m, t), t)
print("max deliveries in an innings:", max(per_inn.values()), " min:", min(per_inn.values()))
print("innings 1 longest end offset (min):", max((per_inn[(m,1)]-1)*40/60 for m in start if (m,1) in per_inn))
ends = {m: last[m] + dt.timedelta(minutes=5) for m in last}
cross = [m for m in ends if ends[m].date() != start[m].date()]
print("matches whose result time crosses midnight:", len(cross))
inn1_over = [m for m in start if (m,1) in per_inn and (per_inn[(m,1)]-1)*40 >= 110*60]
print("innings 1 overruns the innings-2 start:", len(inn1_over))
# overlap between the 16:00 match's end and the 20:00 match's toss (19:30)
ov = 0
for d, ms in day_matches.items():
    if len(ms) == 2 and ends[ms[0]] > start[ms[1]] - dt.timedelta(minutes=30): ov += 1
print("double-header days where match 1 ends after match 2's toss:", ov)
tc = Counter(t for _, t in times)
print("delivery times shared by two deliveries:", sum(1 for v in tc.values() if v > 1))
print("last event (N):", max(ends.values()))
# on double-header days, is match_id order a plausible day order? compare with season-local id order only (no time in source)
print("double-header days:", sum(1 for v in day_matches.values() if len(v) == 2))
