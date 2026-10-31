"""Compare Pagila.sqlite and sqlite-sakila.sqlite: file hash, schema, and every table row by row.

Usage: python3 -I p0_copies.py DIR      (DIR = data/spider2)
Read-only (mode=ro). For each table: row counts, rows in A not in B and B not in A (multiset,
with typeof() kept so 1 and '1' differ), and rowid-aligned mismatches.
"""
import hashlib, sqlite3, sys
from collections import Counter

d = sys.argv[1]
a_path, b_path = f"{d}/Pagila.sqlite", f"{d}/sqlite-sakila.sqlite"
for p in (a_path, b_path):
    print(p, hashlib.sha256(open(p, "rb").read()).hexdigest())

A = sqlite3.connect(f"file:{a_path}?mode=ro", uri=True)
B = sqlite3.connect(f"file:{b_path}?mode=ro", uri=True)
sa = A.execute("select type,name,sql from sqlite_master order by type,name").fetchall()
sb = B.execute("select type,name,sql from sqlite_master order by type,name").fetchall()
print("schema objects:", len(sa), len(sb), "identical:", sa == sb)

tables = [r[0] for r in A.execute("select name from sqlite_master where type='table' order by name")]
print(f"{'table':24} {'rows A':>8} {'rows B':>8} {'A-B':>5} {'B-A':>5} {'rowid mism':>10}")
for t in tables:
    cols = [r[1] for r in A.execute(f'pragma table_info("{t}")')]
    sel = ", ".join(f'typeof("{c}"), "{c}"' for c in cols)
    ra = A.execute(f'select rowid, {sel} from "{t}" order by rowid').fetchall()
    rb = B.execute(f'select rowid, {sel} from "{t}" order by rowid').fetchall()
    ca, cb = Counter(r[1:] for r in ra), Counter(r[1:] for r in rb)
    mism = sum(1 for x, y in zip(ra, rb) if x != y) + abs(len(ra) - len(rb))
    print(f"{t:24} {len(ra):8} {len(rb):8} {sum((ca-cb).values()):5} {sum((cb-ca).values()):5} {mism:10}")
