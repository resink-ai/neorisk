"""Per-column storage classes, NULL / '' counts and text shapes for every table of oracle_sql.sqlite.
Usage: python3 -I t1_typeof.py data/spider2/oracle_sql.sqlite   (opened mode=ro)"""
import sqlite3, sys, re
con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
tabs = [r[0] for r in con.execute("select name from sqlite_master where type='table' order by rowid")]
tot = 0
for t in tabs:
    n = con.execute(f'select count(*) from "{t}"').fetchone()[0]; tot += n
    cols = con.execute(f'pragma table_info("{t}")').fetchall()
    print(f"## {t}  rows={n}")
    for c in cols:
        name, decl = c[1], c[2]
        cls = con.execute(f'select typeof("{name}"), count(*) from "{t}" group by 1 order by 1').fetchall()
        empty = con.execute(f'select count(*) from "{t}" where "{name}" = \'\'').fetchone()[0]
        bsn = con.execute(f'select count(*) from "{t}" where "{name}" = \'\\N\'').fetchone()[0]
        extra = ""
        if any(k == 'real' for k, _ in cls):
            nonint = con.execute(f'select count(*) from "{t}" where typeof("{name}")=\'real\' and "{name}" != cast("{name}" as integer)').fetchone()[0]
            extra += f" real_nonintegral={nonint}"
        if any(k == 'text' for k, _ in cls):
            shapes = {}
            for (v,) in con.execute(f'select "{name}" from "{t}" where typeof("{name}")=\'text\''):
                s = re.sub(r"[0-9]", "9", v); s = re.sub(r"[A-Za-z]+", "a", s)
                shapes[s] = shapes.get(s, 0) + 1
            top = sorted(shapes.items(), key=lambda kv: -kv[1])[:4]
            extra += f" shapes={top}" if len(shapes) <= 6 else f" n_shapes={len(shapes)} top={top}"
            ws = con.execute(f'select count(*) from "{t}" where typeof("{name}")=\'text\' and "{name}" != trim("{name}")').fetchone()[0]
            extra += f" untrimmed={ws}"
        print(f"  {name:16s} decl={decl or '(none)':8s} classes={cls} empty={empty} bslashN={bsn}{extra}")
print("TOTAL rows", tot, "tables", len(tabs))
