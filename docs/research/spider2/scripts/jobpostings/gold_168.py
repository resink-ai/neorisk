"""local168: find which top-3 skill choice reproduces the gold answers (92689.2222 `_a`, 96521.7109 `_b`).
The 5 most frequent skill_ids in the cohort tie at 3 postings each, so the answer depends on tie-breaking.
Usage: python3 -I gold_168.py DB"""
import itertools, sqlite3, struct, sys

con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
coh = "job_title_short = 'Data Analyst' and salary_year_avg is not null and job_work_from_home = 1"
rows = con.execute(f"select p.job_id, p.salary_year_avg, s.skill_id from job_postings_fact p join skills_job_dim s using(job_id) where {coh}").fetchall()
names = dict(con.execute("select skill_id, skills from skills_dim"))
freq = {}
for _, _, k in rows: freq[k] = freq.get(k, 0) + 1
top = sorted(freq.items(), key=lambda kv: -kv[1])
print("cohort skill freq (top 8):", [(k, names.get(k), n) for k, n in top[:8]])
tied = [k for k, n in top if n == top[0][1]]
print("tied at the top:", tied)
f32 = lambda x: struct.unpack("f", struct.pack("f", x))[0]
for combo in itertools.combinations(tied, 3):
    sel = [(j, s) for j, s, k in rows if k in combo]
    over_rows = sum(s for _, s in sel) / len(sel)
    d = {j: s for j, s in sel}
    over_post = sum(d.values()) / len(d)
    print(f"skills {combo} ({[names.get(k) for k in combo]}): over (posting,skill) rows {over_rows:.10f} (n={len(sel)}), "
          f"over distinct postings {over_post:.10f} (n={len(d)}), float32 of rows-avg {f32(over_rows):.7f}")
# with skills_dim inner join (only skills present in skills_dim can rank)
present = [k for k, _ in top if k in names][:3]
sel = [(j, s) for j, s, k in rows if k in present]
print("inner join to skills_dim, top 3 present:", present, "avg over rows", sum(s for _, s in sel) / len(sel), "n", len(sel))
