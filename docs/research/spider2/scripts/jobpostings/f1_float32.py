"""Are the salary REALs float32 values widened to float64? For each value x:
- f32_exact: x == float64(float32(x))
- the shortest decimal d (0..4 places) with float32(d) == x, and how many values need k places
- rebuild rule: float64(float32(cents/100)) == x  (cents = round(d*100))
Usage: python3 -I f1_float32.py DB"""
import sqlite3, struct, sys
from collections import Counter
from decimal import Decimal

con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
f32 = lambda x: struct.unpack("f", struct.pack("f", x))[0]

def shortest(x):
    for k in range(0, 5):
        d = round(x, k)
        if f32(d) == x:
            return k, d
    return None, None

for col in ("salary_year_avg", "salary_hour_avg"):
    vals = [r[0] for r in con.execute(f"select {col} from job_postings_fact where {col} is not null")]
    exact = sum(v == f32(v) for v in vals)
    plain = sum(v == round(v, 2) for v in vals)
    places = Counter(); ok_cents = 0
    for v in vals:
        k, d = shortest(v)
        places[k] += 1
        if k is not None and k <= 2 and f32(round(d * 100) / 100) == v:
            ok_cents += 1
    print(f"{col}: {len(vals)} values; float32-exact {exact}; already a 2-place double {plain}; "
          f"shortest decimal places {dict(sorted(places.items(), key=lambda kv: (kv[0] is None, kv[0])))}; "
          f"float32(cents/100) rebuilds {ok_cents}")
    worst = [v for v in vals if shortest(v)[0] is None or shortest(v)[0] > 2][:5]
    print("  values needing > 2 places:", worst, [str(Decimal(w)) for w in worst[:2]])
