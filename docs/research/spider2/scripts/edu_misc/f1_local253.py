"""Try salary-cleaning rules against the three local253 gold CSVs (national average and top-5 lists).
Read-only. Usage: python3 -I f1_local253.py DB"""
import re, sqlite3, sys
from collections import defaultdict

con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
rows = con.execute("SELECT CompanyName, Location, Salary FROM SalaryDataset").fetchall()
CITIES = ("Hyderabad", "Mumbai", "New Delhi", "Pune")
def num(s): return float(re.sub(r"[^0-9]", "", s))
rules = {
    "digits only": lambda s: num(s),
    "annualise mo*12 hr*2080": lambda s: num(s) * (12 if s.endswith("/mo") else 2080 if s.endswith("/hr") else 1),
    "annualise mo*12 hr*2080, rupee only": lambda s: (num(s) * (12 if s.endswith("/mo") else 2080 if s.endswith("/hr") else 1)) if s.startswith("₹") else None,
    "annualise mo*12 hr*8*22*12": lambda s: num(s) * (12 if s.endswith("/mo") else 2112 if s.endswith("/hr") else 1),
    "yr rows only": lambda s: num(s) if s.endswith("/yr") else None,
    "mo*12, hr dropped": lambda s: num(s) * 12 if s.endswith("/mo") else None if s.endswith("/hr") else num(s),
    "annualise, company NULL kept": lambda s: num(s) * (12 if s.endswith("/mo") else 2080 if s.endswith("/hr") else 1),
}
for name, f in rules.items():
    vals = [(c, l, f(s)) for c, l, s in rows]
    vals = [v for v in vals if v[2] is not None]
    nat_rows = sum(v[2] for v in vals) / len(vals)
    by = defaultdict(list)
    for c, l, x in vals: by[(l, c)].append(x)
    comp = defaultdict(list)
    for c, l, x in vals: comp[c].append(x)
    nat_comp = sum(sum(v)/len(v) for v in comp.values()) / len(comp)
    nat_lc = sum(sum(v)/len(v) for v in by.values()) / len(by)
    print(f"{name}: national avg over rows {nat_rows:.6f}; over companies {nat_comp:.6f}; over (loc,company) {nat_lc:.6f}")
    for city in CITIES:
        top = sorted(((sum(v)/len(v), c) for (l, c), v in by.items() if l == city and c is not None), reverse=True)[:5]
        print("   ", city, "; ".join(f"{c} {a:.2f}" for a, c in top))
