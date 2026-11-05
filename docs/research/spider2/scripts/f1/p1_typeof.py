"""Per table: row count; per column (incl. generated, via table_xinfo): declared type, typeof mix,
count of NULL, '' and '\\N', and distinct count. Read-only.
Usage: python3 -I p1_typeof.py data/spider2/f1.sqlite"""
import sqlite3, sys
con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
tabs = [r[0] for r in con.execute("select name from sqlite_master where type='table' order by rowid")]
for t in tabs:
    n = con.execute(f'select count(*) from "{t}"').fetchone()[0]
    print(f"## {t}  rows={n}")
    for cid, name, decl, notnull, dflt, pk, hidden in con.execute(f'pragma table_xinfo("{t}")'):
        mix = con.execute(f'select typeof("{name}"), count(*) from "{t}" group by 1 order by 2 desc').fetchall()
        empty = con.execute(f'select count(*) from "{t}" where "{name}" = \'\'').fetchone()[0]
        bsn = con.execute(f'select count(*) from "{t}" where "{name}" = \'\\N\'').fetchone()[0]
        nd = con.execute(f'select count(distinct "{name}") from "{t}"').fetchone()[0]
        gen = " GENERATED" if hidden in (2, 3) else ""
        print(f"  {name:28s} {decl or '(none)':14s}{gen:10s} pk={pk} {dict(mix)} empty={empty} \\N={bsn} distinct={nd}")
