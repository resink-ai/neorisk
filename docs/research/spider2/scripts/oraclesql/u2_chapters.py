"""Which upstream chapter scripts reference each table. Usage: python3 -I u2_chapters.py DB REPO_DIR"""
import sqlite3, sys, re, glob, os
con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
tabs = [r[0] for r in con.execute("select name from sqlite_master where type='table' order by rowid")]
files = sorted(glob.glob(os.path.join(sys.argv[2], "Chapter*", "*.sql")))
txt = {os.path.basename(f): open(f, encoding="utf-8-sig", errors="replace").read().lower() for f in files}
for t in tabs:
    hits = [f.split("_")[0] for f, s in txt.items() if re.search(rf"\b{t}\b", s)]
    print(f"{t:22s} {' '.join(hits) or '-'}")
