"""Are the REAL columns clean short decimals? For each value v, the shortest repr and the smallest
number of decimals d (0..6) with float(f'{v:.{d}f}') == v. Usage: python3 -I f1_floats.py DB"""
import sqlite3, sys
from collections import Counter
con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
for t, c in [("Student_Schedules", "Grade"), ("Students", "StudGPA"), ("Staff", "Salary"), ("Faculty_Subjects", "ProficiencyRating")]:
    vals = [r[0] for r in con.execute(f'select "{c}" from "{t}"')]
    dp = Counter(next(d for d in range(7) if float(f"{v:.{d}f}") == v) for v in vals)
    print(f"{t}.{c}: {len(vals)} values, decimals needed {dict(sorted(dp.items()))}, all integral-cents-exact: "
          f"{all(round(v*100)/100 == v for v in vals)}, all repr-roundtrip: {all(float(repr(v)) == v for v in vals)}")
