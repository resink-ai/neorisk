"""Distributions to fit and quirks, over DISTINCT matches (each card's first copy; see p2) and cards.
Usage: python3 -I p4_dists.py DB"""
import sqlite3, sys, datetime as dt
from collections import Counter, defaultdict
from statistics import quantiles, mean

con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
promo = dict(con.execute("SELECT id, name FROM Promotions"))
belt = dict(con.execute("SELECT id, name FROM Belts"))
mt = dict(con.execute("SELECT id, name FROM Match_Types"))
wr = dict(con.execute("SELECT id, name FROM Wrestlers"))
cards = {r[0]: r[1:] for r in con.execute("SELECT id, promotion_id, event_date, event_id, location_id FROM Cards")}
first, done, prev = defaultdict(list), set(), None
for r in con.execute("SELECT id, card_id, winner_id, win_type, loser_id, match_type_id, duration, title_id, title_change FROM Matches ORDER BY id"):
    if r[1] != prev:
        if prev is not None: done.add(prev)
        prev = r[1]
    if r[1] not in done: first[r[1]].append(r)
M = [m for v in first.values() for m in v]
print("distinct matches", len(M))

def q(xs, n=10): return [round(x, 1) for x in quantiles(xs, n=n)]

# cards per year by promotion
py = defaultdict(Counter)
for c, (p, d, e, l) in cards.items(): py[promo[p]][d[:4]] += 1
for p in py:
    ys = sorted(py[p]); print("cards/year", p, ys[0], "-", ys[-1], "min", min(py[p].values()), "max", max(py[p].values()),
                              "median", sorted(py[p].values())[len(ys)//2])
# five-year totals
fy = Counter();
for c, (p, d, e, l) in cards.items(): fy[d[:3] + "0s"] += 1
print("cards by decade:", sorted(fy.items()))
# weekday mix
wd = Counter(dt.date.fromisoformat(d).strftime("%a") for (p, d, e, l) in cards.values())
print("card weekday:", wd.most_common())
# gaps between consecutive card dates per promotion (days)
for p in promo:
    ds = sorted(dt.date.fromisoformat(d) for (pp, d, e, l) in cards.values() if pp == p)
    if len(ds) < 3: continue
    g = [(b - a).days for a, b in zip(ds, ds[1:])]
    print("gap days", promo[p], "n", len(g), "zero-gaps", sum(x == 0 for x in g), "quantiles(10)", q(g), "max", max(g))
# matches per card by promotion
for p in promo:
    n = [len(first.get(c, [])) for c, v in cards.items() if v[0] == p]
    if n: print("matches/card", promo[p], "mean", round(mean(n), 2), "quantiles(4)", q(n, 4), "max", max(n))
# win type over distinct
print("win_type:", Counter(m[3] for m in M).most_common())
# duration
secs = [int(m[6][:2]) * 60 + int(m[6][3:]) for m in M if m[6]]
print("duration present", len(secs), "of", len(M), "; seconds quantiles(10)", q(secs), "max", max(secs))
dp = defaultdict(lambda: [0, 0])
for m in M:
    y = cards[m[1]][1][:3] + "0s"; dp[y][0] += 1; dp[y][1] += bool(m[6])
print("duration present share by decade:", sorted((k, round(v[1] / v[0], 3)) for k, v in dp.items()))
sec_mod = Counter(s % 60 for s in secs)
print("seconds==00 share", round(sec_mod[0] / len(secs), 4), "(uniform would be 0.0167)")
# titles
tm = [m for m in M if m[7] != "1"]
print("title matches", len(tm), "share", round(len(tm) / len(M), 4), "; title_change among title matches", sum(m[8] for m in tm),
      "; title_change on a no-title match", sum(m[8] for m in M if m[7] == "1"))
print("top belts:", Counter(belt[int(m[7])] for m in tm).most_common(8))
print("compound belt names (contain two 'Title'/'Championship'):",
      sum(1 for b in belt.values() if b.count("Title") + b.count("Championship") >= 2), "of", len(belt))
# match types
print("match_type top:", Counter(mt[int(m[5])] for m in M).most_common(12))
# sides: size of a side (members) and appearances
size = Counter(len(wr[int(x)].split(" & ")) for m in M for x in (m[2], m[4]))
print("side size (members, from ' & ' split):", sorted(size.items())[:12], "... max", max(size))
app = Counter(x for m in M for x in (m[2], m[4]))
a = sorted(app.values())
print("appearances per Wrestlers row: n", len(a), "quantiles(10)", q(a), "max", a[-1], "; once:", sum(x == 1 for x in a))
top = sorted(app.items(), key=lambda kv: -kv[1])[:8]
print("most frequent sides:", [(wr[int(k)], v) for k, v in top])
wins = Counter(m[2] for m in M); loss = Counter(m[4] for m in M)
print("dup payload within a card (same row twice):", sum(len(v) - len(set(x[1:] for x in v)) for v in first.values()))
print("winner == loser (distinct):", sum(m[2] == m[4] for m in M), Counter(wr[int(m[2])] for m in M if m[2] == m[4]).most_common(5))
print("empty win_type (distinct):", sum(m[3] == "" for m in M))
# cards per Events row / location
print("cards per location: quantiles(10)", q(sorted(Counter(v[3] for v in cards.values()).values())))
