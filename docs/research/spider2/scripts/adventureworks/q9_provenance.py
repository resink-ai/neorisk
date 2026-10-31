"""Provenance: compare the Spider2 file with Microsoft's current install CSVs (sql-server-samples,
master, the SQL Server 2025 refresh whose README says "Dates have been adjusted").
Downloads into a fresh temp dir with curl; the CSVs are tab-separated, no header.
Usage: python3 -I q9_provenance.py DB"""
import csv
import sqlite3
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import date
from pathlib import Path

BASE = ("https://raw.githubusercontent.com/microsoft/sql-server-samples/master/samples/databases/"
        "adventure-works/oltp-install-script/")
tmp = Path(tempfile.mkdtemp())
con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
csv.field_size_limit(10**8)


def get(name, enc="utf-8"):
    p = tmp / name
    subprocess.run(["curl", "-sS", "-o", str(p), BASE + name], check=True)
    raw = p.read_bytes()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        enc = "utf-16"
    return list(csv.reader(raw.decode(enc).splitlines(), delimiter="\t"))


d = lambda s: date.fromisoformat(s[:10])

# SalesOrderHeader: 0 id, 1 rev, 2 order, 3 due, 4 ship, 5 status, 6 online, 7 SO number, 8 PO, 9 account,
# 10 customer, 11 salesperson, ... 19 subtotal, 20 tax, 21 freight, 22 totaldue, 23 comment, 24 rowguid, 25 mod
ms = {int(r[0]): r for r in get("SalesOrderHeader.csv")}
sp = {r[0]: r for r in con.execute("select salesorderid, revisionnumber, orderdate, shipdate, subtotal, taxamt, "
                                     "freight, totaldue, rowguid, purchaseordernumber, accountnumber, "
                                     "salespersonid from salesorderheader")}
print(f"SalesOrderHeader: ms rows={len(ms)} spider rows={len(sp)} common ids={len(ms.keys() & sp.keys())}")
same_guid = sum(ms[i][24].lower() == s[8] for i, s in sp.items())
same_money = sum(float(ms[i][19]) == s[4] and float(ms[i][20]) == s[5] and float(ms[i][21]) == s[6]
                 and float(ms[i][22]) == s[7] for i, s in sp.items())
same_po = sum(ms[i][8] == s[9] and ms[i][9] == s[10] for i, s in sp.items())
shift = Counter((d(ms[i][2]) - d(s[2])).days for i, s in sp.items())
rev = Counter((int(ms[i][1]), s[1]) for i, s in sp.items())
print(f"  rowguid equal (case-folded): {same_guid}; subtotal/tax/freight/totaldue equal: {same_money}; "
      f"PO and account equal: {same_po}")
print(f"  orderdate shift (ms - spider, days): {shift.most_common(6)}")
print(f"  (ms revision, spider revision): {sorted(rev.items())}")
print(f"  ms rowguid case: upper={sum(r[24] == r[24].upper() for r in ms.values())}")

q = get("SalesPersonQuotaHistory.csv")
sq = {r[3].strip("{}").upper(): r for r in con.execute("select * from SalesPersonQuotaHistory")}
print(f"SalesPersonQuotaHistory: ms rows={len(q)}; rowguid found in spider: "
      f"{sum(r[3].upper() in sq for r in q)}; amount equal: "
      f"{sum(r[3].upper() in sq and float(r[2]) == sq[r[3].upper()][2] for r in q)}")
qs = Counter((d(r[1]) - d(sq[r[3].upper()][1])).days for r in q if r[3].upper() in sq)
print(f"  QuotaDate shift (ms - spider, days): {sorted(qs.items())}")

det = get("SalesOrderDetail.csv")
sd = {r[0]: r for r in con.execute("select salesorderdetailid, unitprice, orderqty, rowguid, carriertrackingnumber "
                                     "from salesorderdetail")}
print(f"SalesOrderDetail: ms rows={len(det)}; rowguid equal: "
      f"{sum(int(r[1]) in sd and r[9].lower() == sd[int(r[1])][3] for r in det)}; unitprice and qty equal: "
      f"{sum(int(r[1]) in sd and float(r[6]) == sd[int(r[1])][1] and int(r[3]) == sd[int(r[1])][2] for r in det)}")
print(f"  ms detail columns: {len(det[0])}, first row: {det[0]}")
from decimal import Decimal as D, ROUND_HALF_UP
lt_ok = sum(D(r[8]) == D(r[6]) * (1 - D(r[7])) * int(r[3]) for r in det)
print(f"  ms LineTotal (col 9, 6 dp) == unitprice*(1-discount)*qty exactly: {lt_ok}/{len(det)}")
