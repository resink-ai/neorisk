"""Matches is a repeated scrape: each card's matches appear as several contiguous blocks of ids.
Measure the blocks ("passes"): how many per card, whether the copies are identical, and how the
passes sit in the global id range.  Usage: python3 -I p1_passes.py DB"""
import sqlite3, sys
from collections import Counter, defaultdict

con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
rows = con.execute("SELECT id, card_id, winner_id, win_type, loser_id, match_type_id, duration, title_id, title_change "
                   "FROM Matches ORDER BY id").fetchall()
# runs of equal card_id in id order
runs = []  # (card_id, first_id, last_id, tuple_of_payloads)
cur = None
for r in rows:
    if cur is None or r[1] != cur[0]:
        if cur: runs.append(cur)
        cur = [r[1], r[0], r[0], []]
    cur[2] = r[0]
    cur[3].append(r[2:])
runs.append(cur)
print("rows", len(rows), "runs", len(runs))
by_card = defaultdict(list)
for i, (c, lo, hi, p) in enumerate(runs):
    by_card[c].append((i, lo, hi, tuple(p)))
print("cards", len(by_card))
print("blocks per card:", sorted(Counter(len(v) for v in by_card.values()).items()))
ident = sum(all(b[3] == v[0][3] for b in v) for v in by_card.values())
print("cards whose blocks are all identical:", ident)
nonid = [(c, [len(b[3]) for b in v]) for c, v in by_card.items() if not all(b[3] == v[0][3] for b in v)]
print("non-identical cards (card, block sizes) first 20:", nonid[:20])
# For non-identical: is each block a prefix/permutation of the largest one?
perm = sum(all(sorted(b[3]) == sorted(v[0][3]) for b in v) for c, v in by_card.items())
print("cards whose blocks are equal as multisets:", perm)
# Pass structure: label each run with its pass number = its index among that card's blocks
pass_of = {}
for c, v in by_card.items():
    for k, b in enumerate(v):
        pass_of[b[0]] = k + 1
# global: where does pass k start/end in id space
span = defaultdict(lambda: [10**9, 0, 0, 0])
for i, (c, lo, hi, p) in enumerate(runs):
    k = pass_of[i]
    s = span[k]; s[0] = min(s[0], lo); s[1] = max(s[1], hi); s[2] += 1; s[3] += len(p)
print("pass: first_id last_id runs rows")
for k in sorted(span): print(k, *span[k])
# Is the sequence of pass numbers non-decreasing along id order?
seq = [pass_of[i] for i in range(len(runs))]
print("pass-number decreases along id order:", sum(1 for a, b in zip(seq, seq[1:]) if b < a))
# Distinct matches if we keep one block per card
distinct = sum(len(v[0][3]) for v in by_card.values())
print("rows in first block of each card:", distinct)
# Within one card's first block, exact duplicate rows (a real rematch on the same card or a dup)
d = sum(len(v[0][3]) - len(set(v[0][3])) for v in by_card.values())
print("duplicate payload rows inside a first block:", d)
# Cards with matches only in the later pass region: cards ordered by first id - same order in each pass?
orders = defaultdict(list)
for i, (c, lo, hi, p) in enumerate(runs):
    orders[pass_of[i]].append(c)
base = orders[1]
pos = {c: j for j, c in enumerate(base)}
for k in sorted(orders):
    o = [pos[c] for c in orders[k]]
    print("pass", k, "cards", len(o), "order inversions vs pass 1:", sum(1 for a, b in zip(o, o[1:]) if b < a))
# Tail: list runs from the first one whose card is not in pass-1 order position, around the decreases
first_dec = next(j for j in range(1, len(seq)) if seq[j] < seq[j-1])
print("first pass-number decrease at run", first_dec, "id", runs[first_dec][1])
# Per pass: the last run index of the "regular" region
for k in sorted(orders):
    idx = [i for i in range(len(runs)) if pass_of[i] == k]
    print("pass", k, "run idx range", idx[0], idx[-1], "contiguous?", idx[-1]-idx[0]+1 == len(idx))
print("tail runs (idx, card, pass, lo, hi, n):")
tail_start = min(i for i in range(len(runs)) if pass_of[i] == 7 and runs[i][1] > 0) 
cards_late = sorted({c for c, v in by_card.items() if len(v) < 7})
print("cards with < 7 blocks:", len(cards_late), "card id range", cards_late[0], cards_late[-1])
for i in range(len(runs)):
    if runs[i][0] in set(cards_late) and i < 88131:
        pass
late = set(cards_late)
segs = []  # compress the run sequence into segments of (late?, pass)
for i in range(len(runs)):
    key = (runs[i][0] in late, pass_of[i])
    if segs and segs[-1][0] == key: segs[-1][1] += 1; segs[-1][3] = runs[i][2]
    else: segs.append([key, 1, runs[i][1], runs[i][2]])
print("segments (late_card?, pass) n_runs first_id last_id:")
for s in segs: print(*s)
