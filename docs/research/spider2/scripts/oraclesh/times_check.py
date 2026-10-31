"""Which `times` columns are pure calendar arithmetic of time_id?
Usage: python3 -I times_check.py DB
For each column: rows where a stated formula of time_id reproduces the stored value exactly
(same type and text). Also: which columns are a function of the fiscal month / week group."""
import calendar, datetime as dt, sqlite3, sys
from collections import defaultdict

con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
cur = con.execute("select * from times")
cols = [d[0] for d in cur.description]
rows = [dict(zip(cols, r)) for r in cur.fetchall()]
D = lambda s: dt.date.fromisoformat(s)
iso = lambda d: d.isoformat()

def qend(d):
    q = (d.month - 1) // 3; m = 3 * q + 3
    return dt.date(d.year, m, calendar.monthrange(d.year, m)[1])
def qdays(d):
    q = (d.month - 1) // 3
    return sum(calendar.monthrange(d.year, m)[1] for m in range(3 * q + 1, 3 * q + 4))

F = {  # column -> formula of the date d
    "day_name": lambda d: d.strftime("%A"),
    "day_number_in_week": lambda d: d.isoweekday(),                          # Mon=1 .. Sun=7
    "day_number_in_month": lambda d: d.day,
    "calendar_week_number": lambda d: (d.timetuple().tm_yday - 1) // 7 + 1,  # Oracle 'WW'
    "week_ending_day": lambda d: iso(d + dt.timedelta(days=7 - d.isoweekday())),  # next Sunday
    "calendar_month_number": lambda d: d.month,
    "calendar_month_desc": lambda d: f"{d.year}-{d.month:02d}",
    "days_in_cal_month": lambda d: calendar.monthrange(d.year, d.month)[1],
    "end_of_cal_month": lambda d: iso(dt.date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])),
    "calendar_month_name": lambda d: d.strftime("%B"),
    "calendar_quarter_desc": lambda d: f"{d.year}-{(d.month - 1) // 3 + 1:02d}",
    "calendar_quarter_number": lambda d: (d.month - 1) // 3 + 1,
    "days_in_cal_quarter": qdays,
    "end_of_cal_quarter": lambda d: iso(qend(d)),
    "calendar_year": lambda d: d.year,
    "days_in_cal_year": lambda d: 366 if calendar.isleap(d.year) else 365,
    "end_of_cal_year": lambda d: f"{d.year}-12-31",
    # fiscal columns tested against calendar formulas, to show where they differ
    "fiscal_week_number": lambda d: (d.timetuple().tm_yday - 1) // 7 + 1,
}
print("## calendar formulas (matches / 1826)")
for c, f in F.items():
    ok = sum(1 for r in rows if f(D(r["time_id"])) == r[c])
    bad = [(r["time_id"], r[c], f(D(r["time_id"]))) for r in rows if f(D(r["time_id"])) != r[c]][:4]
    print(f"{c:28s} {ok:5d}  {'' if ok == len(rows) else bad}")

# id columns: linear in the description?
print("## id columns as linear functions")
def lin(desc_col, id_col, key):
    m = {}
    for r in rows: m[r[desc_col]] = r[id_col]
    ks = sorted(m, key=key)
    base = m[ks[0]]
    ok = sum(1 for i, k in enumerate(ks) if m[k] == base + i)
    print(f"{id_col:22s} {len(ks)} groups, {ok} equal base+rank (base {base}); first break at",
          next(((k, m[k]) for i, k in enumerate(ks) if m[k] != base + i), None))
for a, b in [("calendar_month_desc", "calendar_month_id"), ("fiscal_month_desc", "fiscal_month_id"),
             ("calendar_quarter_desc", "calendar_quarter_id"), ("fiscal_quarter_desc", "fiscal_quarter_id"),
             ("calendar_year", "calendar_year_id"), ("fiscal_year", "fiscal_year_id")]:
    lin(a, b, str)

# fiscal structure: given the fiscal month of each day (data), are the other fiscal columns derivable?
print("## fiscal columns derived from (fiscal_year, fiscal_month_number) of each day")
g = defaultdict(list)
for r in rows: g[(r["fiscal_year"], r["fiscal_month_number"])].append(r)
def chk(name, pred):
    ok = sum(1 for r in rows if pred(r))
    print(f"{name:40s} {ok:5d} / {len(rows)}")
chk("fiscal_month_desc = YYYY-MM of fiscal", lambda r: r["fiscal_month_desc"] == f"{r['fiscal_year']}-{r['fiscal_month_number']:02d}")
chk("fiscal_month_name = name(fiscal_month)", lambda r: r["fiscal_month_name"] == calendar.month_name[r["fiscal_month_number"]])
chk("fiscal_quarter_number = ceil(m/3)", lambda r: r["fiscal_quarter_number"] == (r["fiscal_month_number"] - 1) // 3 + 1)
chk("fiscal_quarter_desc = YYYY-0Q", lambda r: r["fiscal_quarter_desc"] == f"{r['fiscal_year']}-{r['fiscal_quarter_number']:02d}")
chk("end_of_fis_month = last day in group", lambda r: r["end_of_fis_month"] == max(x["time_id"] for x in g[(r["fiscal_year"], r["fiscal_month_number"])]))
chk("days_in_fis_month = group size", lambda r: r["days_in_fis_month"] == len(g[(r["fiscal_year"], r["fiscal_month_number"])]))
gq = defaultdict(list); gy = defaultdict(list)
for r in rows: gq[r["fiscal_quarter_desc"]].append(r); gy[r["fiscal_year"]].append(r)
chk("days_in_fis_quarter = group size", lambda r: r["days_in_fis_quarter"] == len(gq[r["fiscal_quarter_desc"]]))
chk("end_of_fis_quarter = last day in group", lambda r: r["end_of_fis_quarter"] == max(x["time_id"] for x in gq[r["fiscal_quarter_desc"]]))
chk("days_in_fis_year = group size", lambda r: r["days_in_fis_year"] == len(gy[r["fiscal_year"]]))
chk("end_of_fis_year = last day in group", lambda r: r["end_of_fis_year"] == max(x["time_id"] for x in gy[r["fiscal_year"]]))
chk("fiscal_week_number = calendar_week_number", lambda r: r["fiscal_week_number"] == r["calendar_week_number"])
# fiscal month lengths in days (pattern 4-4-5 weeks = 28/28/35?)
seq = [len(g[k]) for k in sorted(g)]
print("fiscal month lengths in days:", seq)
# fiscal month boundaries: on which weekday does a fiscal month end?
ends = defaultdict(int)
for k in sorted(g): ends[D(max(x["time_id"] for x in g[k])).strftime("%a")] += 1
print("weekday of the last day of each fiscal month:", dict(ends))

# week_ending_day_id: is it a function of a week that ends on another weekday?
print("## week_ending_day_id vs weeks ending on each weekday")
for wd in range(1, 8):
    m = defaultdict(set)
    for r in rows:
        d = D(r["time_id"]); end = d + dt.timedelta(days=(wd - d.isoweekday()) % 7)
        m[end].add(r["week_ending_day_id"])
    print(f"week ending on isoweekday {wd}: {len(m)} weeks, {sum(len(v) > 1 for v in m.values())} with >1 id")
