"""Compare legislators / legislators_terms with Tanimura's sql_book CSVs, cell by cell, in row order.
CSV empty cell -> NULL; numeric CSV cells compare by value with the stored INTEGER/REAL.
Usage: python3 -I cmp_tanimura.py DB CSVDIR"""
import csv, sqlite3, sys
from collections import Counter

db, d = sys.argv[1], sys.argv[2]
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)

for t in ("legislators", "legislators_terms"):
    rows = list(csv.reader(open(f"{d}/{t}.csv", encoding="utf-8", newline="")))
    hdr, body = rows[0], rows[1:]
    cols = [r[1] for r in con.execute(f'pragma table_info("{t}")')]
    db_rows = con.execute(f'select * from "{t}" order by rowid').fetchall()
    print(f"### {t}: csv {len(body)} rows, db {len(db_rows)} rows, header equal: {hdr == cols}")
    diff_cells = Counter(); diff_rows = 0; examples = []
    for i, (cr, dr) in enumerate(zip(body, db_rows)):
        bad = False
        for c, cv, dv in zip(cols, cr, dr):
            if cv == "":
                ok = dv is None
            elif isinstance(dv, (int, float)) and not isinstance(dv, bool):
                try: ok = float(cv) == float(dv)
                except ValueError: ok = False
            else:
                ok = cv == dv
            if not ok:
                diff_cells[c] += 1; bad = True
                if len(examples) < 8: examples.append((i + 1, c, cv, dv))
        diff_rows += bad
    print(f"rows differing (row order aligned): {diff_rows}; per column: {dict(diff_cells)}")
    for e in examples: print("  example", e)
    # CSV quoting fingerprint: is every non-empty text cell quoted? (raw line check on first 1000 lines)
print()
# also: does pandas-style typing explain the REAL columns? count CSV numeric cells with a decimal point
for t, c in (("legislators", "id_icpsr"), ("legislators_terms", "district")):
    rows = list(csv.DictReader(open(f"{d}/{t}.csv", encoding="utf-8", newline="")))
    vals = [r[c] for r in rows if r[c] != ""]
    print(f"{t}.{c}: {len(vals)} non-empty csv cells, {sum('.' in v for v in vals)} contain '.', "
          f"{len(rows) - len(vals)} empty -> NULL")
