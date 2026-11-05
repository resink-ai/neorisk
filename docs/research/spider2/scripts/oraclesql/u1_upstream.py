"""Compare every table of oracle_sql.sqlite with the INSERTs of Apress/practical-oracle-sql practical_fill_schema.sql.
Usage: python3 -I u1_upstream.py DB FILL_SQL
Parses `insert into T values (...)` lines (date '..', to_date('..', fmt), null, numbers, strings);
locations is the generated 2 warehouses x aisles A-D x positions 1-32, ids by row_number.
Compares as multisets: numbers by value, text byte-exact, NULL only to NULL. Also reports insert order vs SQLite rowid order."""
import sqlite3, sys, re, hashlib
from collections import Counter
db, fill = sys.argv[1], sys.argv[2]
print("fill sha256", hashlib.sha256(open(fill, 'rb').read()).hexdigest())
tok = re.compile(r"\s*(?:date\s*'([^']*)'|to_date\(\s*'([^']*)'\s*,\s*'[^']*'\s*\)|'((?:[^']|'')*)'|(null)|(-?[0-9]+(?:\.[0-9]+)?)|(,))", re.I)
ups = {}
for line in open(fill, encoding='utf-8-sig'):
    m = re.match(r"\s*insert into (\w+) values \((.*)\);\s*$", line, re.I)
    if not m: continue
    t, body = m.group(1).lower(), m.group(2).rstrip()
    vals, pos = [], 0
    while pos < len(body):
        mm = tok.match(body, pos)
        if not mm: raise SystemExit(f"parse fail {t}: {body[pos:]}")
        pos = mm.end()
        d, td, s, nul, num, comma = mm.groups()
        if comma: continue
        if d is not None: vals.append(d)
        elif td is not None: vals.append(td)
        elif s is not None: vals.append(s.replace("''", "'"))
        elif nul: vals.append(None)
        else: vals.append(float(num) if '.' in num else int(num))
    ups.setdefault(t, []).append(tuple(vals))
ups['locations'] = [(i + 1, w, a, p) for i, (w, a, p) in enumerate((w, a, p) for w in (1, 2) for a in 'ABCD' for p in range(1, 33))]
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
tabs = [r[0] for r in con.execute("select name from sqlite_master where type='table' order by rowid")]
def norm(r): return tuple(float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else x for x in r)
alleq = 0
for t in tabs:
    src = con.execute(f'select * from "{t}" order by rowid').fetchall()
    up = ups.get(t)
    if up is None:
        print(f"{t:22s} sqlite={len(src):4d} upstream=NO INSERTS"); continue
    a, b = Counter(map(norm, src)), Counter(map(norm, up))
    only_s, only_u = a - b, b - a
    same_order = [norm(r) for r in src] == [norm(r) for r in up]
    eq = not only_s and not only_u
    alleq += eq
    print(f"{t:22s} sqlite={len(src):4d} upstream={len(up):4d} multiset_equal={eq} rowid_order_equals_insert_order={same_order}")
    for r in list(only_s.elements())[:5]: print("   only sqlite  ", r)
    for r in list(only_u.elements())[:5]: print("   only upstream", r)
print("tables equal to upstream:", alleq, "of", len(tabs))
print("upstream tables with inserts not in sqlite:", sorted(set(ups) - set(tabs)))
