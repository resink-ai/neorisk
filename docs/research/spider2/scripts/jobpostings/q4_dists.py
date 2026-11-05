"""Distributions for stage 2: postings per day, inter-arrival gaps, salary quantiles, weekday mix, link-time rule counts.
Usage: python3 -I q4_dists.py DB"""
import sqlite3, sys
from collections import Counter
from datetime import datetime

con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
ts = sorted(datetime.strptime(r[0], "%Y-%m-%d %H:%M:%S") for r in con.execute("select job_posted_date from job_postings_fact"))
q = lambda xs, p: xs[min(len(xs) - 1, int(p * len(xs)))]
days = Counter(t.date() for t in ts)
per_day = sorted(days.values())
print(f"days with postings {len(days)}; per day p5 {q(per_day,.05)} p50 {q(per_day,.5)} p95 {q(per_day,.95)} max {per_day[-1]}")
print("top days:", days.most_common(5))
gaps = sorted((b - a).total_seconds() for a, b in zip(ts, ts[1:]))
print(f"inter-arrival seconds: zero {sum(g == 0 for g in gaps)}; p50 {q(gaps,.5)} p90 {q(gaps,.9)} p99 {q(gaps,.99)} max {gaps[-1]}")
wd = Counter(t.strftime("%a") for t in ts)
print("weekday:", dict(wd))
for col in ("salary_year_avg", "salary_hour_avg"):
    v = sorted(r[0] for r in con.execute(f"select {col} from job_postings_fact where {col} is not null"))
    print(f"{col}: n {len(v)} p5 {q(v,.05)} p25 {q(v,.25)} p50 {q(v,.5)} p75 {q(v,.75)} p95 {q(v,.95)} max {v[-1]}")
    print(f"  most common: {Counter(v).most_common(5)}")
# link-entity created_at rule: matched links take the posting time, orphans take the catalog start
m = con.execute("select count(*) from skills_job_dim s where s.job_id in (select job_id from job_postings_fact)").fetchone()[0]
n = con.execute("select count(*) from skills_job_dim").fetchone()[0]
print(f"skills_job links: {n}; created at posting time {m}; at catalog start (rule) {n - m}")
c_used = con.execute("select count(*) from job_company where company_id in (select company_id from job_postings_fact)").fetchone()[0]
print(f"job_company: created at first posting {c_used}; at catalog start (rule) {14003 - c_used}")
miss = con.execute("select count(distinct company_id) from job_postings_fact where company_id not in (select company_id from job_company)").fetchone()[0]
miss_rows = con.execute("select count(*) from job_postings_fact where company_id not in (select company_id from job_company)").fetchone()[0]
print(f"postings whose company is missing: {miss_rows} rows, {miss} distinct company ids")
mj = con.execute("select count(distinct job_id) from skills_job_dim where job_id not in (select job_id from job_postings_fact)").fetchone()[0]
ms = con.execute("select count(distinct skill_id) from skills_job_dim where skill_id not in (select skill_id from skills_dim)").fetchone()[0]
print(f"links: distinct missing job ids {mj}; distinct missing skill ids {ms}")
