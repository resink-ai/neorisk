"""Replay Jaime Shaker's cleaning (normalize_tables.sql + remove_duplicates.sql) on his raw CSVs in Python and
compare with the Spider tables, row by row by id.
  clean(x) = trim(lower(regexp_replace(x, '[^\\w\\s^. ]', '', 'gi')))   (Python re with Unicode \\w approximates Postgres)
  cities: latitude <- raw longitude, longitude <- raw latitude (Shaker's swap), capital::boolean, population::int
  countries: dedup on country_code_2 keeping the lowest id; created_on = current_date at load time
Usage: python3 -I cmp_shaker.py DB CSVDIR"""
import csv, re, sqlite3, sys
from collections import Counter

db, d = sys.argv[1], sys.argv[2]
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
rx = re.compile(r"[^\w\s^. ]")

def clean(x):
    if x is None or x == "":
        return None  # COPY ... CSV reads an unquoted empty field as NULL
    return rx.sub("", x).lower().strip()

def read(name):
    with open(f"{d}/{name}", encoding="utf-8-sig", newline="") as f:
        r = csv.reader(f); next(r)
        return [[None if c == "" else c for c in row] for row in r]

def num(x, f):
    return None if x is None else f(x)

def compare(table, keycol, src_rows):
    cols = [r[1] for r in con.execute(f'pragma table_info("{table}")')]
    db_rows = {r[0]: r for r in con.execute(f'select * from "{table}"')}
    diff = Counter(); ex = []
    missing = [k for k in src_rows if k not in db_rows]; extra = [k for k in db_rows if k not in src_rows]
    for k, s in src_rows.items():
        if k not in db_rows: continue
        for c, a, b in zip(cols, s, db_rows[k]):
            if not (a == b or (isinstance(a, (int, float)) and isinstance(b, (int, float)) and float(a) == float(b))):
                diff[c] += 1
                if len(ex) < 6: ex.append((k, c, a, b))
    print(f"### {table}: replayed {len(src_rows)}, db {len(db_rows)}, ids only in replay {len(missing)} {missing[:10]}, only in db {len(extra)}")
    print(f"  differing cells per column: {dict(diff)}")
    for e in ex: print("  example", e)

# countries
raw = read("countries.csv")
rows = {}
for i, r in enumerate(raw, 1):
    rows[i] = [i] + [clean(x) for x in r] + ["2024-07-18"]
seen = {}; dropped = []
for i in sorted(rows):
    cc = rows[i][2]
    if cc in seen: dropped.append(i)
    else: seen[cc] = i
for i in dropped: del rows[i]
print(f"countries.csv: {len(raw)} raw rows; dedup on cleaned country_code_2 drops {len(dropped)} ids: {dropped}")
compare("cities_countries", "country_id", rows)

# cities
raw = read("cities.csv")
rows = {}
for i, r in enumerate(raw, 1):
    name, lat, lon, cc, cap, pop, ins = r
    capv = None if cap is None else (1 if cap.strip().lower() in ("true", "t", "1", "yes", "y") else 0)
    rows[i] = [i, clean(name), num(lon, float), num(lat, float), clean(cc), capv, num(pop, lambda v: float(int(v))), ins]
print(f"cities.csv: {len(raw)} raw rows; capital raw values {Counter(r[4] for r in raw)}")
compare("cities", "city_id", rows)

raw = read("currencies.csv")
compare("cities_currencies", "currency_id", {i: [i, clean(r[0]), clean(r[1]), clean(r[2])] for i, r in enumerate(raw, 1)})
raw = read("languages.csv")
compare("cities_languages", "language_id", {i: [i, clean(r[0]), clean(r[1])] for i, r in enumerate(raw, 1)})

# insert_date in the raw file: format, range
ins = [r[6] for r in read("cities.csv")]
iso = all(re.fullmatch(r"\d{4}-\d\d-\d\d", x) for x in ins)
print(f"raw insert_date: {len(ins)} values, distinct {len(set(ins))}, min {min(ins)}, max {max(ins)}, "
      f"all YYYY-MM-DD {iso}")
