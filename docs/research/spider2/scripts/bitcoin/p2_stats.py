"""Fingerprints and distributions for the bitcoin_* tables.

Run: uv run --no-sync python -I docs/research/spider2/scripts/bitcoin/p2_stats.py DB
Source opened read-only (mode=ro).
"""
import hashlib, sqlite3, sys
from collections import Counter, defaultdict
from datetime import datetime
import numpy as np
from scipy import stats

db = sys.argv[1]
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
M = con.execute("select rowid, member_id, first_name, region from bitcoin_members order by rowid").fetchall()
T = con.execute("select txn_id, member_id, ticker, txn_type, quantity, percentage_fee, txn_time from bitcoin_transactions order by txn_id").fetchall()
P = con.execute("select ticker, substr(market_date,7,4)||'-'||substr(market_date,4,2)||'-'||substr(market_date,1,2), price, open, high, low, volume, change from bitcoin_prices").fetchall()

print("## md5 fingerprint: member_id == md5(str(rowid))[:6]")
hits = [(r, mid, hashlib.md5(str(r).encode()).hexdigest()[:6]) for r, mid, *_ in M]
print("  matches:", sum(m == h for _, m, h in hits), "/", len(M))
ids_md5 = {hashlib.md5(str(n).encode()).hexdigest()[:6]: n for n in range(1, 100001)}
print("  any txn ids that are md5 too? n/a (txn_id is an integer)")

body = [t for t in T if t[0] > 28]
print(f"\n## body = {len(body)} transactions after the 28 opening buys")

ts = np.array([datetime.strptime(t[6], "%Y-%m-%dT%H:%M:%S.%fZ").timestamp() for t in body])
g = np.diff(ts)
print("## global inter-arrival gaps (s)")
print(f"  n={len(g)} mean={g.mean():.1f} sd={g.std():.1f} cv={g.std()/g.mean():.3f} p50={np.median(g):.0f} p90={np.quantile(g,.9):.0f} max={g.max():.0f}")
ks = stats.kstest(g, "expon", args=(0, g.mean()))
print(f"  KS vs Exp(mean): D={ks.statistic:.4f} p={ks.pvalue:.3g}")
span_days = (ts[-1] - ts[0]) / 86400
print(f"  rate = {len(body)/span_days:.2f} per day over {span_days:.1f} days")
# per day counts: Poisson?
days = Counter(t[6][:10] for t in body)
c = np.array(list(days.values()))
print(f"  per-day counts: days={len(c)} mean={c.mean():.3f} var={c.var():.3f} (Poisson: var=mean)")

print("\n## quantity (body): Uniform(0,10)?")
for tk in ("BTC", "ETH"):
    for ty in ("BUY", "SELL"):
        q = np.array([t[4] for t in body if t[2] == tk and t[3] == ty])
        k = stats.kstest(q, "uniform", args=(0, 10))
        print(f"  {tk} {ty}: n={len(q)} mean={q.mean():.4f} sd={q.std():.4f} (U(0,10) sd=2.8868) KS D={k.statistic:.4f} p={k.pvalue:.3g}")
q = np.array([t[4] for t in body])
r9 = np.round(q, 9)
print(f"  quantity == round(quantity, 9): {int((r9 == q).sum())}/{len(q)}")

print("\n## fee: 0.3 w.p. ~0.70, else uniform on {0.00..0.29}?")
f = Counter(round(t[5], 2) for t in T)
low = [f[round(i / 100, 2)] for i in range(30)]
print(f"  P(0.3)={f[0.3]/len(T):.4f}; low-fee counts min={min(low)} max={max(low)}; chi2 uniform p={stats.chisquare(low).pvalue:.3g}")
print(f"  fee 0.00 count={f[0.0]} (lowest bucket), 0.01..0.29 mean={np.mean(low[1:]):.1f}")
# chi2 excluding 0.00
print(f"  chi2 uniform over 0.01..0.29 p={stats.chisquare(low[1:]).pvalue:.3g}")
# hypothesis: fee = min(round(U(0,1), 2), 0.30)  ->  P(0.00)=0.005, P(0.01..0.29)=0.01 each, P(0.30)=0.705
n = len(T)
exp = [0.005 * n] + [0.01 * n] * 29 + [0.705 * n]
obs = low + [f[0.3]]
print(f"  min(round(U(0,1),2),0.3): expected 0.00={exp[0]:.1f} each low={exp[1]:.1f} 0.30={exp[-1]:.1f}; "
      f"observed 0.00={obs[0]} 0.30={obs[-1]}; chi2 p={stats.chisquare(obs, exp).pvalue:.3g}")
body_btc = sum(t[2] == 'BTC' for t in T if t[0] > 28)
print(f"  body BTC share={body_btc / (len(T) - 28):.4f}, SELL share={sum(t[3] == 'SELL' for t in T) / (len(T) - 28):.4f}")

print("\n## member choice: uniform over 14?")
mc = Counter(t[1] for t in body)
print(f"  counts min={min(mc.values())} max={max(mc.values())}; chi2 uniform p={stats.chisquare(list(mc.values())).pvalue:.3g}")
print("\n## per-member mixes (body)")
by = defaultdict(list)
for t in body: by[t[1]].append(t)
name = {m[1]: m[2] for m in M}
for mid in [m[1] for m in M]:
    rows = by[mid]
    print(f"  {mid} {name[mid]:8s} n={len(rows):5d} share={len(rows)/len(body):.4f} btc_share={sum(r[2]=='BTC' for r in rows)/len(rows):.3f} sell_share={sum(r[3]=='SELL' for r in rows)/len(rows):.3f}")
# within member: ticker and side independent?
tab = np.array([[sum(1 for r in body if r[2] == tk and r[3] == ty) for ty in ("BUY", "SELL")] for tk in ("BTC", "ETH")])
print("  overall ticker×side table", tab.tolist(), "chi2 independence p=%.3g" % stats.chi2_contingency(tab)[1])

print("\n## do trades react to prices? (body, per ticker-day)")
px = {(p[0], p[1]): p for p in P}
for tk in ("BTC", "ETH"):
    d = defaultdict(lambda: [0, 0])
    for t in body:
        if t[2] == tk: d[t[6][:10]][t[3] == "SELL"] += 1
    keys = sorted(d)
    chg = np.array([float(px[(tk, k)][7][:-1]) for k in keys])
    n = np.array([sum(d[k]) for k in keys]); sell = np.array([d[k][1] for k in keys])
    print(f"  {tk}: corr(change, n_trades)={np.corrcoef(chg, n)[0,1]:.4f} corr(change, sell share)={np.corrcoef(chg, sell/n)[0,1]:.4f}")
    qty = defaultdict(list)
    for t in body:
        if t[2] == tk: qty[t[6][:10]].append(t[4])
    lvl = np.array([px[(tk, k)][2] for k in keys]); mq = np.array([np.mean(qty[k]) for k in keys])
    print(f"       corr(close price, mean qty)={np.corrcoef(lvl, mq)[0,1]:.4f}  -> the notional per trade scales with price")
    notional = np.array([t[4] * px[(tk, t[6][:10])][2] for t in body if t[2] == tk])
    print(f"       notional per trade at close (USD): p10={np.quantile(notional,.1):,.0f} p50={np.median(notional):,.0f} p90={np.quantile(notional,.9):,.0f} max={notional.max():,.0f}")

print("\n## holdings at the end (units) and sells relative to holdings")
h = defaultdict(float)
frac = []
for t in T:
    k = (t[1], t[2])
    if t[3] == "SELL": frac.append(t[4] / h[k]); h[k] -= t[4]
    else: h[k] += t[4]
print(f"  min final holding={min(h.values()):.3f} max={max(h.values()):.3f}; sell/holding p50={np.median(frac):.4f} p99={np.quantile(frac,.99):.4f} max={max(frac):.4f}")

print("\n## daily prices: log returns (close to close)")
for tk in ("BTC", "ETH"):
    s = sorted((p for p in P if p[0] == tk), key=lambda p: p[1])
    c = np.array([p[2] for p in s]); r = np.diff(np.log(c))
    print(f"  {tk}: n={len(r)} mean={r.mean():.5f} sd={r.std():.5f} skew={stats.skew(r):.3f} ex_kurt={stats.kurtosis(r):.2f} min={r.min():.4f} max={r.max():.4f} first={c[0]} last={c[-1]}")
    v = np.array([p[6] for p in s])
    vol = np.array([np.nan if x == "-" else float(x[:-1]) * (1e3 if x[-1] == "K" else 1e6) for x in v])
    lv = np.log(vol[~np.isnan(vol)])
    print(f"       log10 volume: p10={np.quantile(lv,.1)/np.log(10):.2f} p50={np.median(lv)/np.log(10):.2f} p90={np.quantile(lv,.9)/np.log(10):.2f}")
    hl = np.array([(p[4] - p[5]) / p[2] for p in s])
    print(f"       (high-low)/close: p50={np.median(hl):.4f} p90={np.quantile(hl,.9):.4f}")
    by_year = defaultdict(list)
    for p, x in zip(s, vol): by_year[p[1][:4]].append(x)
    print("       median volume by year:", {y: f"{np.nanmedian(x):,.0f}" for y, x in sorted(by_year.items())})
