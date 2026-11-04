"""Per table: rows; per column: declared type, typeof() counts, '' count, distinct, min/max of non-empty.
Usage: python3 -I p1_profile.py DB"""
import sqlite3, sys
con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
tabs = [r[0] for r in con.execute("select name from sqlite_master where type='table' order by name")]
print("objects:", con.execute("select type, count(*) from sqlite_master group by type").fetchall())
tot = 0
for t in tabs:
    n = con.execute(f'select count(*) from "{t}"').fetchone()[0]; tot += n
    print(f"\n## {t}  rows={n}")
    for cid, c, decl, *_ in con.execute(f'pragma table_info("{t}")'):
        ty = dict(con.execute(f'select typeof("{c}"), count(*) from "{t}" group by 1').fetchall())
        emp = con.execute(f'select count(*) from "{t}" where "{c}" = \'\'').fetchone()[0]
        ws = con.execute(f'select count(*) from "{t}" where typeof("{c}")=\'text\' and "{c}"<>\'\' and "{c}"<>trim("{c}")').fetchone()[0]
        d = con.execute(f'select count(distinct "{c}") from "{t}"').fetchone()[0]
        mn, mx = con.execute(f'select min("{c}"), max("{c}") from "{t}" where "{c}"<>\'\'').fetchone()
        print(f"  {c:18s} {decl:8s} types={ty} empty={emp} ws={ws} distinct={d} min={mn!r} max={mx!r}")
print("\ntotal rows", tot)
