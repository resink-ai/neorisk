"""Profile every table of a Spider2 SQLite file, read-only.
Usage: python3 -I profile.py DB
Per table: rows, rowid-vs-PK order; per column: declared type, typeof mix, NULL, '', '\\N',
leading/trailing whitespace, distinct, min, max."""
import sqlite3, sys
db = sys.argv[1]
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
tabs = [r[0] for r in con.execute("select name from sqlite_master where type='table' order by name")]
for t in tabs:
    n = con.execute(f'select count(*) from "{t}"').fetchone()[0]
    print(f"## {t}  rows={n}")
    cols = con.execute(f'pragma table_info("{t}")').fetchall()
    pk = [c[1] for c in sorted(cols, key=lambda c: c[5]) if c[5]]
    if pk and t != 'sqlite_sequence':
        k = ",".join(f'"{c}"' for c in pk)
        try:
            ok = con.execute(f'select count(*) from (select rowid r, row_number() over (order by rowid) a, row_number() over (order by {k}) b from "{t}") where a=b').fetchone()[0]
            print(f"   pk={pk}  rowid order == pk order: {ok}/{n}")
        except Exception as e:
            print("   pk", pk, e)
    for c in cols:
        name, decl = c[1], c[2]
        q = f'"{name}"'
        types = con.execute(f'select typeof({q}), count(*) from "{t}" group by 1 order by 1').fetchall()
        empty = con.execute(f"select count(*) from \"{t}\" where {q} = ''").fetchone()[0]
        bsn = con.execute(f"select count(*) from \"{t}\" where {q} = '\\N'").fetchone()[0]
        ws = con.execute(f"select count(*) from \"{t}\" where typeof({q})='text' and ({q} <> trim({q}) or {q} like '%'||char(10)||'%')").fetchone()[0]
        d, mn, mx = con.execute(f'select count(distinct {q}), min({q}), max({q}) from "{t}"').fetchone()
        ts = ",".join(f"{a}:{b}" for a, b in types)
        print(f"   {name:<24} {decl:<16} [{ts}] empty={empty} \\N={bsn} ws={ws} distinct={d} min={mn!r} max={mx!r}")
    print()
