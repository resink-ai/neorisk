"""Are Northwind's REAL columns float4 values printed with 9 significant digits (PostgreSQL
extra_float_digits=3) and then parsed as float64? And do they rebuild exactly from integer
cents (money) or basis points (discount)?  Usage: python3 -I f1_float4.py DB"""
import sqlite3, struct, sys
from collections import Counter

con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
f32 = lambda x: struct.unpack("f", struct.pack("f", x))[0]
def pg_real(x):          # float4 -> text with 9 significant digits -> float64
    return float("%.9g" % f32(x))
cols = [("orders", "freight", 100), ("order_details", "unitprice", 100), ("order_details", "discount", 100),
        ("products", "unitprice", 100), ("customergroupthreshold", "rangetop", 10000)]
for t, c, scale in cols:
    vals = [r[0] for r in con.execute(f"select {c} from {t}")]
    n = len(vals)
    is_f4_9g = sum(v == pg_real(v) for v in vals)
    exact_f64_decimal = sum(v == round(v, 2) for v in vals)          # already the plain decimal double
    ints = [round(v * scale) for v in vals]
    rebuild = sum(v == pg_real(k / scale) for v, k in zip(vals, ints))   # value rebuilt from integer units
    text_digits = Counter(len(repr(v).replace(".", "").replace("-", "").lstrip("0").split("e")[0]) for v in vals)
    print(f"{t}.{c}: n={n} float4_9g_fixpoint={is_f4_9g} plain_decimal_double={exact_f64_decimal} "
          f"rebuilt_from_int_units(scale {scale})={rebuild} sig_digits={dict(sorted(text_digits.items()))}")
# examples of values that are not a plain decimal double
ex = [r for r in con.execute("select orderid, freight from orders limit 400") if r[1] != round(r[1], 2)][:5]
print("freight examples (float64 repr):", [(o, repr(v), round(v, 2)) for o, v in ex])
# line value: does SQLite's unitprice*quantity*(1-discount) land on cents?
rows = con.execute("select unitprice, quantity, discount from order_details").fetchall()
cent = sum(abs(u * q * (1 - d) * 100 - round(u * q * (1 - d) * 100)) < 1e-6 for u, q, d in rows)
cent_ideal = sum(((round(u * 100) * q * (100 - round(d * 100))) % 100) == 0 for u, q, d in rows)
print(f"order_details: line net on cent grid as stored floats={cent}/{len(rows)}; with exact cents and pct={cent_ideal}/{len(rows)}")
