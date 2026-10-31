"""Compare Spider2's chinook invoices/invoice_items with upstream lerocha/chinook-database master
(ChinookDatabase/DataSources/Chinook_Sqlite.sql, v1.4.5), whose invoice dates are shifted.
Usage: python3 -I c5_upstream.py DB UPSTREAM_SQL"""
import re, sqlite3, sys
from collections import Counter

con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
up = open(sys.argv[2], encoding="utf-8-sig", errors="replace").read()
def block(table):
    out = []
    for m in re.finditer(rf"INSERT INTO \[{table}\] \([^)]*\) VALUES\s*(.*?);\s*\n", up, re.S):
        out += re.findall(r"^\s*\((.*)\)[,]?\s*$", m.group(1), re.M)
    return out
inv = block("Invoice"); lines = block("InvoiceLine")
print("upstream invoices", len(inv), "lines", len(lines))
src = {r[0]: r for r in con.execute("select InvoiceId, CustomerId, InvoiceDate, Total from invoices")}
shift = Counter(); same_cust = same_total = 0
for row in inv:
    f = [x.strip() for x in re.split(r",(?=(?:[^']*'[^']*')*[^']*$)", row)]
    iid, cid, date, total = int(f[0]), int(f[1]), f[2].strip("'"), float(f[-1])
    s = src[iid]
    same_cust += s[1] == cid; same_total += s[3] == total
    shift[(int(date[:4]) - int(s[2][:4]), date[4:] == s[2][4:])] += 1
print("same customer", same_cust, "same total", same_total, "year shift (years, same month-day-time):", dict(shift))
sl = Counter(con.execute("select InvoiceLineId||','||InvoiceId||','||TrackId||','||UnitPrice||','||Quantity from invoice_items").fetchall())
ul = Counter((",".join(x.strip() for x in l.split(",")),) for l in lines)
print("invoice lines identical:", sum((sl & ul).values()), "of", sum(sl.values()))
