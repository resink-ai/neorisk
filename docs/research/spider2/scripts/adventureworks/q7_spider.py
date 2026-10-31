"""Reproduce Spider2-lite local141 (AdventureWorks) against both gold exec_result CSVs.
There is no gold SQL (404); the CSVs are fetched from the Spider2 repo.
Usage: python3 -I q7_spider.py DB"""
import csv
import io
import sqlite3
import sys
import subprocess

BASE = "https://raw.githubusercontent.com/xlang-ai/Spider2/main/spider2-lite/evaluation_suite/gold/"
for path in ("sql/local141.sql", "exec_result/local141_a.csv", "exec_result/local141_b.csv"):
    out = subprocess.run(["curl", "-sS", "-w", "%{http_code}", BASE + path], capture_output=True, text=True).stdout
    print(f"{path}: HTTP {out[-3:]}, {len(out) - 3} bytes")

con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
SQL = """
with s as (select salespersonid sp, cast(strftime('%Y', orderdate) as int) y, sum(totaldue) total
           from salesorderheader where salespersonid <> '' group by 1, 2),
     q as (select BusinessEntityID sp, cast(strftime('%Y', QuotaDate) as int) y, sum(SalesQuota) quota
           from SalesPersonQuotaHistory group by 1, 2)
select s.sp, s.y, s.total, q.quota, s.total - q.quota diff from s join q using (sp, y) order by 1, 2
"""
mine = con.execute(SQL).fetchall()
print(f"local141 rows: {len(mine)}")
fetch = lambda p: subprocess.run(["curl", "-sS", BASE + p], capture_output=True, text=True).stdout
gold = list(csv.DictReader(io.StringIO(fetch("exec_result/local141_b.csv"))))
gold_a = list(csv.DictReader(io.StringIO(fetch("exec_result/local141_a.csv"))))
print(f"gold rows: b={len(gold)} a={len(gold_a)}")
mine_k = {(r[0], r[1]) for r in con.execute(SQL)}
print("gold_b keys not in inner-join answer:", [(g["salespersonid"], g["year"], g["total_sales"], g["annual_quota"])
      for g in gold if (int(g["salespersonid"]), int(g["year"])) not in mine_k])
ok = 0
gold = [g for g in gold if (int(g["salespersonid"]), int(g["year"])) in mine_k]
for (sp, y, tot, quo, diff), g in zip(mine, gold):
    same = (sp == int(g["salespersonid"]) and y == int(g["year"]) and abs(tot - float(g["total_sales"])) < 1e-6
            and abs(quo - float(g["annual_quota"])) < 1e-6 and abs(diff - float(g["difference"])) < 1e-6)
    ok += same
print(f"inner-join answer matches local141_b.csv on the shared keys: {ok}/{len(gold)}")
for row in mine[:4] + mine[-2:]:
    print("  ", row)
# what the question would look like without the quota join (salesperson-years with sales but no quota)
extra = con.execute("""select count(*) from (select salespersonid, strftime('%Y', orderdate) y from salesorderheader
  where salespersonid<>'' group by 1,2) s where not exists (select 1 from SalesPersonQuotaHistory q
  where q.BusinessEntityID=s.salespersonid and strftime('%Y', q.QuotaDate)=s.y)""").fetchone()[0]
print(f"salesperson-years with sales but no quota row: {extra}")
akeys = {}
for g in gold_a:
    akeys.setdefault((g["Salesperson"], g["Year"]), []).append(g["Difference"])
print("local141_a rows per key > 1:", {k: v for k, v in akeys.items() if len(v) > 1})
print("local141_a keys:", len(akeys))
mine_d = {(float(r[0]), str(r[1])): r[4] for r in mine}
named = {k: v for k, v in akeys.items() if k[0] != ""}
a_ok = sum(any(abs(float(d) - mine_d.get((float(k[0]), k[1]), 1e99)) < 1e-6 for d in v) for k, v in named.items())
print(f"local141_a salesperson keys whose difference matches the totaldue answer: {a_ok}/{len(named)}")
nosp = {k[1]: float(v[0]) for k, v in akeys.items() if k[0] == ""}
online = dict(con.execute("select strftime('%Y', orderdate), sum(totaldue) from salesorderheader "
                          "where salespersonid = '' group by 1"))
print("local141_a rows with an empty salesperson (year, gold, sum(totaldue) of orders without one):",
      [(y, g, round(online[y], 4), abs(g - online[y]) < 1e-6) for y, g in sorted(nosp.items())])
