"""Can SalaryDataset.Salary be split into (currency, integer amount, period) and printed back
byte-exact with Indian (lakh) digit grouping? Also: does StaffHours cycle members in rowid order?
Read-only. Usage: python3 -I f2_salary_text.py DB"""
import re, sqlite3, sys
from collections import Counter

con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
sal = [r[0] for r in con.execute("SELECT Salary FROM SalaryDataset ORDER BY rowid")]
pat = re.compile(r"^(\D+?)([0-9][0-9,]*)/(yr|mo|hr)$")
def lakh(n: int) -> str:
    s = str(n)
    if len(s) <= 3: return s
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:]); head = head[:-2]
    if head: parts.insert(0, head)
    return ",".join(parts + [tail])
parsed = [pat.match(s) for s in sal]
print("rows", len(sal), "match currency+digits+period", sum(m is not None for m in parsed))
print("currencies", Counter(m.group(1) for m in parsed if m))
ok = sum(m is not None and f"{m.group(1)}{lakh(int(m.group(2).replace(',', '')))}/{m.group(3)}" == s for m, s in zip(parsed, sal))
print("rebuilt byte-exact with lakh grouping", ok)
bad = [s for m, s in zip(parsed, sal) if not (m and f"{m.group(1)}{lakh(int(m.group(2).replace(',', '')))}/{m.group(3)}" == s)]
print("non-matching examples", bad[:10])
amts = sorted(int(m.group(2).replace(',', '')) for m in parsed if m and m.group(3) == "yr" and m.group(1) == "₹")
q = lambda p: amts[int(p * (len(amts) - 1))]
print("rupee /yr amount quantiles p10 %d p25 %d p50 %d p75 %d p90 %d p99 %d max %d min %d" % (q(.1), q(.25), q(.5), q(.75), q(.9), q(.99), amts[-1], amts[0]))
mo = sorted(int(m.group(2).replace(',', '')) for m in parsed if m and m.group(3) == "mo" and m.group(1) == "₹")
print("rupee /mo amount p50 %d, p10 %d, p90 %d, n %d" % (mo[len(mo)//2], mo[int(.1*(len(mo)-1))], mo[int(.9*(len(mo)-1))], len(mo)))
# StaffHours member cycle
mem = [r[0] for r in con.execute("SELECT StaffMember FROM StaffHours ORDER BY rowid")]
step = Counter((ord(b) - ord(a)) % 26 for a, b in zip(mem, mem[1:]))
print("StaffHours: next-member letter step counts (mod 26)", sorted(step.items(), key=lambda kv: -kv[1])[:6])
types = [r[0] for r in con.execute("SELECT EventType FROM StaffHours ORDER BY rowid")]
print("StaffHours: rowid alternates Enter/Exit", sum(a != b for a, b in zip(types, types[1:])), "of", len(types) - 1)
