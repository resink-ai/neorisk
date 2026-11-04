"""Results column types and mixed columns per the dataset contract, using the repo's own rule
(apps/dataset/src/dataset/tables.py). Run from the repo root: uv run python <this> DB"""
import sqlite3, sys
from dataset.tables import column_types, detect_mixed
con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
for (t,) in con.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name"):
    ty = column_types(con, t)
    mixed = detect_mixed(con, t)
    print(f"{t}: " + ", ".join(f"{c}={v}" for c, v in ty.items()) + (f"  MIXED={sorted(mixed)}" if mixed else ""))
