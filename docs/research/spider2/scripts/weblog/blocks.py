"""Find repeated row blocks in each table (rowid order) and diff the near-copies.
Usage: python3 -I blocks.py DB
A table is split greedily into runs: at each position, the longest block length L (1..n/2)
such that rows[i:i+L] == rows[i+L:i+2L] is taken and extended over as many copies as match."""
import sqlite3, sys
con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
tabs = [r[0] for r in con.execute("select name from sqlite_master where type='table' order by name")]

def runs(rows):
    out, i, n = [], 0, len(rows)
    while i < n:
        best = (1, 1)
        for L in range(1, (n - i) // 2 + 1):
            k = 1
            while rows[i:i+L] == rows[i+k*L:i+(k+1)*L]:
                k += 1
            if k > 1 and L * k > best[0] * best[1]:
                best = (L, k)
        L, k = best
        out.append((i + 1, L, k))
        i += L * k
    return out

for t in tabs:
    rows = [r[1:] for r in con.execute(f"select rowid, * from {t} order by rowid")]
    rs = runs(rows)
    if len(rs) == len(rows):
        print(f"{t}: {len(rows)} rows, no repeated block"); continue
    desc = []
    j = 0
    while j < len(rs):           # compress single rows into one span
        s, L, k = rs[j]
        if k == 1:
            e = s
            while j + 1 < len(rs) and rs[j+1][2] == 1:
                j += 1; e = rs[j][0]
            desc.append(f"rows {s}-{e} once")
        else:
            desc.append(f"rows {s}-{s+L*k-1} = {k} x block of {L}")
        j += 1
    print(f"{t}: {len(rows)} rows: " + "; ".join(desc))

def diff(t, a, b, L):
    rows = {r[0]: r[1:] for r in con.execute(f"select rowid, * from {t}")}
    cols = [r[1] for r in con.execute(f"pragma table_info({t})")]
    d = []
    for o in range(L):
        ra, rb = rows[a+o], rows[b+o]
        for c, x, y in zip(cols, ra, rb):
            if x != y: d.append((o, c, x, y))
    return d

print("\n## near-copy diffs (offset within block, column, first block value, second block value)")
for t, a, b, L in [("action_log", 1, 21, 20),
                   ("activity_log", 1, 65, 32), ("activity_log", 65, 173, 36),
                   ("mst_users", 71, 101, 30), ("mst_users", 1, 311, 10)]:
    d = diff(t, a, b, L)
    print(f"{t} rows {a}.. vs {b}..: {len(d)} differing cells")
    for x in d[:40]: print("  ", x)
