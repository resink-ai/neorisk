"""Per column: storage classes (typeof), NULL / '' / '\\N' counts, distinct values, min/max,
and the distinct text shapes of time-like columns (digits replaced by 9).

Usage: python3 -I p1_types.py DB
"""
import re, sqlite3, sys
from collections import Counter

con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
tables = [r[0] for r in con.execute("select name from sqlite_master where type='table' order by name")]
for t in tables:
    n = con.execute(f'select count(*) from "{t}"').fetchone()[0]
    print(f"== {t} ({n} rows)")
    for _, c, decl, *_ in con.execute(f'pragma table_info("{t}")'):
        ty = dict(con.execute(f'select typeof("{c}"), count(*) from "{t}" group by 1').fetchall())
        nul, emp, bsn, dist = con.execute(
            f"""select sum("{c}" is null), sum("{c}"=''), sum("{c}"='\\N'), count(distinct "{c}") from "{t}" """).fetchone()
        mn, mx = con.execute(f'select min("{c}"), max("{c}") from "{t}"').fetchone()
        line = f"  {c:22} {decl:22} types={ty} null={nul} empty={emp} bsN={bsn} distinct={dist}"
        if decl.upper() != "BLOB":
            line += f" min={mn!r:.40} max={mx!r:.40}"
        print(line)
        if any(k in c for k in ("date", "update")):
            shapes = Counter(re.sub(r"\d", "9", str(v)) for (v,) in con.execute(f'select "{c}" from "{t}"'))
            print(f"    shapes: {dict(shapes.most_common(6))}")
