"""Prove the Matches rebuild rule.
Rule: the scraper ran R = 7 times. Run r visits every card whose first run is <= r, in card id order,
and appends that card's distinct matches (its first block, in position order). Matches.id is the
running row number. So Matches = f(77,567 distinct matches, each card's first_run).
Also: per run, the newly seen cards and their dates (a lower bound for when that run happened).
Usage: python3 -I p2_rebuild_matches.py DB"""
import sqlite3, sys
from collections import defaultdict, Counter

con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
cols = "card_id, winner_id, win_type, loser_id, match_type_id, duration, title_id, title_change"
rows = con.execute(f"SELECT id, {cols} FROM Matches ORDER BY id").fetchall()
blocks = defaultdict(list)          # card -> list of blocks (each a list of payload tuples)
prev = None
for r in rows:
    if r[1] != prev:
        blocks[r[1]].append([])
        prev = r[1]
    blocks[r[1]][-1].append(r[1:])
R = max(len(b) for b in blocks.values())
first_run = {c: R - len(b) + 1 for c, b in blocks.items()}
distinct = {c: b[0] for c, b in blocks.items()}
print("runs R =", R, "; cards with matches", len(blocks), "; distinct matches", sum(map(len, distinct.values())))
print("cards by first_run:", sorted(Counter(first_run.values()).items()))

# Rebuild
out, i = [], 0
for r in range(1, R + 1):
    for c in sorted(k for k in distinct if first_run[k] <= r):
        for p in distinct[c]:
            i += 1
            out.append((i,) + p)
src = Counter(rows); reb = Counter(out)
print("rebuilt rows", len(out), "; source rows", len(rows))
print("multiset equal:", src == reb, "; rows only in source:", sum((src - reb).values()), "; only in rebuilt:", sum((reb - src).values()))

# first_run versus card id: is it a step function of the id?
cards = dict(con.execute("SELECT id, event_date FROM Cards").fetchall())
by_run = defaultdict(list)
for c, k in first_run.items(): by_run[k].append(c)
print("run | new cards | card id range | event_date range | latest date known after the run")
latest = ""
for k in sorted(by_run):
    ids = sorted(by_run[k]); ds = sorted(cards[c] for c in ids)
    latest = max(latest, ds[-1])
    print(k, len(ids), ids[0], ids[-1], ds[0], ds[-1], latest)
# Is first_run monotone in card id?
order = sorted(first_run)
print("first_run decreases along card id:", sum(1 for a, b in zip(order, order[1:]) if first_run[b] < first_run[a]))
# The card without matches: where does its id sit?
nomatch = [c for c in cards if c not in blocks]
print("cards without matches:", nomatch)
# Position of each match inside its card (1-based) -- max matches per card
print("matches per card (distinct): max", max(map(len, distinct.values())),
      "dist", sorted(Counter(len(v) for v in distinct.values()).items())[:40])
