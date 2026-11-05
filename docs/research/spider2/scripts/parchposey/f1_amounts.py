"""Can the four REAL money columns of web_orders be rebuilt exactly from the three quantities?
Tries candidate float rules in Python (same IEEE doubles as SQLite and DuckDB). Read-only.
Usage: python3 -I f1_amounts.py DB"""
import sqlite3, sys
from decimal import Decimal

con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
rows = con.execute("SELECT id, standard_qty, gloss_qty, poster_qty, standard_amt_usd, gloss_amt_usd, "
                   "poster_amt_usd, total_amt_usd FROM web_orders").fetchall()
P = {"std": (1, 4, 4.99, 499), "gl": (2, 5, 7.49, 749), "po": (3, 6, 8.12, 812)}
n = len(rows)
print("rows", n)
for k, (qi, ai, price, cents) in P.items():
    r_mul = sum(r[qi] * price == r[ai] for r in rows)
    r_cents = sum(r[qi] * cents / 100 == r[ai] for r in rows)
    r_round = sum(round(r[qi] * price, 2) == r[ai] for r in rows)
    r_dec = sum(float(Decimal(r[qi]) * Decimal(str(price))) == r[ai] for r in rows)
    print(f"{k}: qty*{price} == stored {r_mul}; qty*{cents}/100 {r_cents}; round(qty*price,2) {r_round}; decimal-exact {r_dec}")
cand = {
    "a+b+c (stored parts, left to right)": lambda r: r[4] + r[5] + r[6],
    "(qs*499+qg*749+qp*812)/100": lambda r: (r[1] * 499 + r[2] * 749 + r[3] * 812) / 100,
    "decimal-exact sum": lambda r: float(Decimal(r[1]) * Decimal("4.99") + Decimal(r[2]) * Decimal("7.49") + Decimal(r[3]) * Decimal("8.12")),
    "round(a+b+c,2)": lambda r: round(r[4] + r[5] + r[6], 2),
}
for name, f in cand.items():
    print(f"total_amt_usd == {name}: {sum(f(r) == r[7] for r in rows)}")
# are all stored amounts the shortest decimal for a cent value?
for k, (qi, ai, price, cents) in P.items():
    print(f"{k}: stored == float(cents_int/100 via str) {sum(float(f'{round(r[ai]*100)/100:.2f}') == r[ai] for r in rows)}")
print(f"total: stored == float(cents/100 via str) {sum(float(f'{round(r[7]*100)/100:.2f}') == r[7] for r in rows)}")
bad = [r for r in rows if float(Decimal(r[1]) * Decimal('4.99') + Decimal(r[2]) * Decimal('7.49') + Decimal(r[3]) * Decimal('8.12')) != r[7]]
print("total mismatches vs decimal-exact:", len(bad))
for r in bad[:10]:
    print("  ", r, "decimal:", Decimal(r[1]) * Decimal('4.99') + Decimal(r[2]) * Decimal('7.49') + Decimal(r[3]) * Decimal('8.12'))
