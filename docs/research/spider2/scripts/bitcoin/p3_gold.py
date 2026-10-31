"""Compare q4_spider.sql results with the Spider2 gold CSVs in gold/ (fetched from
xlang-ai/Spider2 spider2-lite/evaluation_suite/gold/exec_result/; no gold SQL exists for either id).

Run: python3 -I docs/research/spider2/scripts/bitcoin/p3_gold.py DB
Matching: numeric cells by relative tolerance 1e-9, or by the CSV's own rounding when it has
fewer decimals (variant _c of local156 rounds to 2 dp); empty cell = NULL.
"""
import csv, os, sqlite3, subprocess, sys

here = os.path.dirname(os.path.abspath(__file__))
db = sys.argv[1]
out = subprocess.run([sys.executable, "-I", os.path.join(here, "bq.py"), db, os.path.join(here, "q4_spider.sql")],
                     capture_output=True, text=True, check=True).stdout
res, cur = {}, None
for line in out.splitlines():
    if line.startswith("### "): cur = line.split()[1]; res[cur] = []; hdr = True; continue
    if cur and line.strip():
        if hdr: hdr = False; continue
        res[cur].append([None if x == "None" else x for x in line.split(" | ")])

def close(a, b):
    if a is None or b in ("", None): return (a is None) == (b in ("", None))
    try: fa, fb = float(a), float(b)
    except ValueError: return a == b
    decs = len(b.split(".")[1]) if "." in b else 0
    return abs(fa - fb) <= 1e-9 * max(1, abs(fb)) or (decs <= 2 and round(fa, decs) == fb)

def compare(name, mine, gold_file, drop_first_year_change=False, drop_rows=None):
    rows = list(csv.reader(open(os.path.join(here, "gold", gold_file))))[1:]
    m = [r for r in mine if not (drop_rows and drop_rows(r))]
    if drop_first_year_change:
        m = [r[:4] + ([None] if r[0] == "2018" else [r[4]]) for r in m]
    ok = len(m) == len(rows) and all(len(a) == len(b) and all(close(x, y) for x, y in zip(a, b)) for a, b in zip(m, rows))
    print(f"{gold_file:16s} vs {name:18s} rows mine={len(m)} gold={len(rows)} match={ok}")

no2017 = lambda r: r[0] == "2017"
q156a, q156b = res["local156_no_fee"], res["local156_with_fee"]
compare("local156_no_fee", q156a, "local156_a.csv", drop_rows=no2017)
compare("local156_no_fee", q156a, "local156_d.csv", drop_rows=no2017, drop_first_year_change=True)
compare("local156_with_fee", q156b, "local156_b.csv", drop_rows=no2017)
compare("local156_with_fee", q156b, "local156_c.csv", drop_rows=no2017, drop_first_year_change=True)
compare("local156_no_fee", q156a, "local156_b.csv", drop_rows=no2017)
q157 = [[r[0], r[1], r[4]] for r in res["local157"]]
compare("local157", q157, "local157_c.csv")
compare("local157 (08-01 null)", [r if r[1] != "2021-08-01" else r[:2] + [None] for r in q157], "local157_a.csv")
compare("local157 (no 08-01)", [r for r in q157 if r[1] != "2021-08-01"], "local157_b.csv")
