"""Physical row order of the three companies_* tables.

Run: python3 -I docs/research/spider2/scripts/unicorns/02_order.py
Compares the rowid sequence of company_id between tables with difflib, to see
whether rows 12.. are one common permutation and where they differ.
"""
import difflib
import sqlite3

con = sqlite3.connect("file:data/spider2/modern_data.sqlite?mode=ro", uri=True)
seq = {
    t: [r[0] for r in con.execute(f"SELECT company_id FROM companies_{t} ORDER BY rowid")]
    for t in ("funding", "dates", "industries")
}
for t, s in seq.items():
    head = s[:11]
    rest = s[11:]
    pos = {c: i + 12 for i, c in enumerate(rest)}
    print(f"{t}: rows 1-11 = {head}")
    print(f"  rowid of the second copy of each: {[pos[c] for c in head]}")
    print(f"  rows 12.. distinct: {len(set(rest))} of {len(rest)}")

for a, b in (("dates", "industries"), ("dates", "funding")):
    sm = difflib.SequenceMatcher(None, seq[a][11:], seq[b][11:], autojunk=False)
    ops = [op for op in sm.get_opcodes() if op[0] != "equal"]
    print(f"\n{a} vs {b} (rows 12..): {len(ops)} non-equal opcodes")
    for tag, i1, i2, j1, j2 in ops:
        print(f"  {tag} {a}[{i1+12}:{i2+12}]={seq[a][11+i1:11+i2]} {b}[{j1+12}:{j2+12}]={seq[b][11+j1:11+j2]}")
