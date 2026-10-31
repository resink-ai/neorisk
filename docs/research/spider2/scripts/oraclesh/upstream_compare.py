"""Compare complex_oracle.sqlite with the upstream Oracle SH v21/23.1 CSVs.
Usage: python3 -I upstream_compare.py DB UPSTREAM_DIR
UPSTREAM_DIR holds the files of github.com/oracle-samples/db-sample-schemas/tree/main/sales_history
(sales.csv, costs.csv, times.csv, customers.csv, promotions.csv, supplementary_demographics.csv,
sh_populate.sql). Values are normalised (strip; '' -> None; numbers by value) before a multiset compare,
and the raw empty-vs-NULL mapping is reported separately."""
import csv, re, sqlite3, sys
from collections import Counter

db, up = sys.argv[1], sys.argv[2]
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)

def norm(v):
    if v is None: return None
    if isinstance(v, (int, float)): return float(v)
    s = v.strip()
    if s == "": return None
    if re.fullmatch(r"-?\d+(\.\d*)?", s): return float(s)   # not float(): 'Nan' is a first name
    return s

def load_csv(name):
    with open(f"{up}/{name}.csv", newline="", encoding="utf-8") as f:
        r = csv.reader(f); hdr = [h.lower() for h in next(r)]
        return hdr, [row for row in r]

for t in ["sales", "costs", "times", "customers", "promotions", "supplementary_demographics"]:
    hdr, rows = load_csv(t)
    cols = ", ".join(f'"{h}"' for h in hdr)
    src = con.execute(f"select {cols} from {t}").fetchall()
    a = Counter(tuple(norm(v) for v in r) for r in rows)
    b = Counter(tuple(norm(v) for v in r) for r in src)
    only_up, only_sp = a - b, b - a
    print(f"## {t}: upstream {len(rows)} rows, sqlite {len(src)} rows; "
          f"equal after normalisation: {not only_up and not only_sp}; only-upstream {sum(only_up.values())}, only-sqlite {sum(only_sp.values())}")
    for k in list(only_up)[:3]: print("   up :", k)
    for k in list(only_sp)[:3]: print("   sq :", k)
    # empty-string mapping per column
    for i, h in enumerate(hdr):
        e_up = sum(1 for r in rows if r[i].strip() == "")
        n_null = con.execute(f'select sum("{h}" is null), sum("{h}" = \'\') from {t}').fetchone()
        pad = sum(1 for r in rows if r[i] != r[i].strip())
        if e_up or n_null[0] or n_null[1] or pad:
            print(f"   col {h}: upstream empty {e_up}, upstream padded {pad}; sqlite NULL {n_null[0]}, sqlite '' {n_null[1]}")
    # row order: is sqlite rowid order = csv order?
    same = sum(1 for x, y in zip(rows, src) if tuple(norm(v) for v in x) == tuple(norm(v) for v in y))
    print(f"   rows in the same position as the CSV: {same}/{len(src)}")

# products, countries, channels come from INSERTs in sh_populate.sql
t = open(f"{up}/sh_populate.sql", encoding="utf-8").read()
ids = re.findall(r"INSERT INTO products VALUES\s*\(\s*(\d+),\s*'([^']*)',\s*'([^']*)'", t)
up_ids = {int(i): (n, d) for i, n, d in ids}
sq = {r[0]: (r[1], r[2]) for r in con.execute("select prod_id, prod_name, prod_desc from products")}
print(f"## products: upstream {len(up_ids)}, sqlite {len(sq)}; in both {len(set(up_ids) & set(sq))}; "
      f"sqlite-only {sorted(set(sq) - set(up_ids))}; upstream-only {len(set(up_ids) - set(sq))}")
print("   name/desc differ on shared ids:", [(i, up_ids[i], sq[i]) for i in sorted(set(up_ids) & set(sq)) if up_ids[i] != sq[i]])
print("   upstream insert order of the sqlite ids:", [i for i, _, _ in ids if int(i) in sq])
cn = re.findall(r"INSERT INTO countries VALUES\s*\(\s*(\d+),\s*'(\w\w)',\s*'([^']*)'", t)
sqc = {r[0]: (r[1], r[2]) for r in con.execute("select country_id, country_iso_code, country_name from countries")}
print(f"## countries: upstream {len(cn)}, sqlite {len(sqc)}, equal (id, iso, name): {sorted((int(a), b, c) for a, b, c in cn) == sorted((k,) + v for k, v in sqc.items())}")
ch = re.findall(r"INSERT INTO channels VALUES\s*\(\s*(\d+),\s*'([^']*)'", t)
print("## channels upstream:", ch)
