"""Reproduce Spider2 gold CSVs for local284 and local285 (no gold SQL exists for either).
Each output column is computed under several plausible readings; we report which reading matches
each CSV variant (cell equality after rounding to 2 dp, or 1e-9 relative for unrounded cells).
Usage: python3 -I p1_gold.py DB"""
import csv, math, os, sqlite3, statistics, sys

here = os.path.dirname(os.path.abspath(__file__))
src = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
con = sqlite3.connect(":memory:"); src.backup(con); src.close()

# ---- local284 ----
loss = [r[0] for r in con.execute('select "loss_rate_%" from veg_loss_rate_df')]
mu = statistics.fmean(loss)
for name, sd in (("sample", statistics.stdev(loss)), ("population", statistics.pstdev(loss))):
    below = sum(x < mu - sd for x in loss); above = sum(x > mu + sd for x in loss)
    print(f"local284 [{name} sd] avg={mu!r} sd={sd!r} below={below} within={len(loss)-below-above} above={above}")
for f in ("local284_a.csv", "local284_b.csv"):
    print(" ", f, list(csv.reader(open(os.path.join(here, "gold", f))))[1])

# ---- local285 ----
con.execute("create index t1 on veg_txn_df(txn_date, item_code)")
con.execute("create index w1 on veg_whsle_df(whsle_date, item_code)")
base = """
select substr(t.txn_date,1,4) y, c.category_name cat, t."qty_sold(kg)" q, t."unit_selling_px_rmb/kg" px, t."discount(%)" disc,
       w."whsle_px_rmb-kg" wp, l."loss_rate_%" lr
from veg_txn_df t join veg_whsle_df w on w.whsle_date = t.txn_date and w.item_code = t.item_code
join veg_cat c on c.item_code = t.item_code join veg_loss_rate_df l on l.item_code = t.item_code"""
agg = {}
for y, cat, q, px, disc, wp, lr in con.execute(base):
    a = agg.setdefault((y, cat), dict(wp=[], lr=[], wp_s=[], lr_s=[], sell=0.0, sell_disc=0.0, whole=0.0, loss=0.0, q=0.0,
                                      sell_s=0.0, sell_disc_s=0.0, whole_s=0.0, loss_s=0.0, q_s=0.0, lrq_s=0.0))
    a["wp"].append(wp); a["lr"].append(lr)
    a["sell"] += q * px; a["sell_disc"] += q * px * (1 - disc / 100); a["whole"] += q * wp; a["loss"] += q * wp * lr / 100; a["q"] += q
    if q > 0:  # sale rows only (returns excluded)
        a["wp_s"].append(wp); a["lr_s"].append(lr); a["q_s"] += q; a["lrq_s"] += q * lr
        a["sell_s"] += q * px; a["sell_disc_s"] += q * px * (1 - disc / 100); a["whole_s"] += q * wp; a["loss_s"] += q * wp * lr / 100
# wholesale-table-only stats per year/category
wt = {}
for y, cat, wp in con.execute("""select substr(w.whsle_date,1,4), c.category_name, w."whsle_px_rmb-kg" from veg_whsle_df w join veg_cat c using (item_code)"""):
    wt.setdefault((y, cat), []).append(wp)
# item-level average loss per category (unweighted, over items in veg_cat)
item_lr = {}
for cat, lr in con.execute('select c.category_name, l."loss_rate_%" from veg_cat c join veg_loss_rate_df l using (item_code)'):
    item_lr.setdefault(cat, []).append(lr)

yr_items, yr_witems, wt_lr = {}, {}, {}
for y, cat, lr in con.execute('''select y, c.category_name, l."loss_rate_%" from (select distinct substr(txn_date,1,4) y, item_code from veg_txn_df) t
                                join veg_cat c using (item_code) join veg_loss_rate_df l using (item_code)'''):
    yr_items.setdefault((y, cat), []).append(lr)
for y, cat, lr in con.execute('''select y, c.category_name, l."loss_rate_%" from (select distinct substr(whsle_date,1,4) y, item_code from veg_whsle_df) t
                                join veg_cat c using (item_code) join veg_loss_rate_df l using (item_code)'''):
    yr_witems.setdefault((y, cat), []).append(lr)
for y, cat, lr in con.execute('''select substr(w.whsle_date,1,4), c.category_name, l."loss_rate_%" from veg_whsle_df w join veg_cat c using (item_code) join veg_loss_rate_df l using (item_code)'''):
    wt_lr.setdefault((y, cat), []).append(lr)
cands = {}
for k, a in agg.items():
    cands[k] = {
        "avg_wp_joined_rows": statistics.fmean(a["wp"]), "avg_wp_whsle_table": statistics.fmean(wt[k]),
        "max_wp_joined": max(a["wp"]), "max_wp_whsle_table": max(wt[k]),
        "min_wp_joined": min(a["wp"]), "min_wp_whsle_table": min(wt[k]),
        "total_whole": a["whole"], "sell_no_disc": a["sell"], "sell_disc_pct": a["sell_disc"],
        "avg_lr_joined_rows": statistics.fmean(a["lr"]), "avg_lr_items": statistics.fmean(item_lr[k[1]]),
        "total_loss": a["loss"],
        "avg_wp_sale_rows": statistics.fmean(a["wp_s"]), "avg_wp_qty_weighted_sales": a["whole_s"] / a["q_s"],
        "avg_lr_sale_rows": statistics.fmean(a["lr_s"]), "avg_lr_qty_weighted_sales": a["lrq_s"] / a["q_s"],
        "avg_lr_items_sold_in_year": statistics.fmean(yr_items[k]), "avg_lr_items_priced_in_year": statistics.fmean(yr_witems[k]),
        "avg_lr_whsle_rows": statistics.fmean(wt_lr[k]),
        "total_whole_sales": a["whole_s"], "sell_sales": a["sell_s"], "sell_disc_sales": a["sell_disc_s"], "total_loss_sales": a["loss_s"],
    }

def r2(x): return round(x + 0.0, 2)
cols = ["avg", "max", "min", "diff", "total_whole", "total_sell", "avg_loss", "total_loss", "profit"]
for f in ("local285_a.csv", "local285_b.csv", "local285_c.csv", "local285_d.csv"):
    rows = list(csv.reader(open(os.path.join(here, "gold", f))))
    hdr, body = rows[0], rows[1:]
    yi = [i for i, h in enumerate(hdr) if h.lower() == "year"][0]; ci = [i for i, h in enumerate(hdr) if h.lower() == "category_name"][0]
    vals = [i for i in range(len(hdr)) if i not in (yi, ci)]
    hits = {c: {} for c in cols}
    for r in body:
        k = (r[yi], r[ci]); c = cands[k]; g = [float(r[i]) for i in vals]
        opts = {
            "avg": {n: c[n] for n in ("avg_wp_joined_rows", "avg_wp_whsle_table", "avg_wp_sale_rows", "avg_wp_qty_weighted_sales")},
            "max": {n: c[n] for n in ("max_wp_joined", "max_wp_whsle_table")},
            "min": {n: c[n] for n in ("min_wp_joined", "min_wp_whsle_table")},
            "diff": {"joined": c["max_wp_joined"] - c["min_wp_joined"], "whsle_table": c["max_wp_whsle_table"] - c["min_wp_whsle_table"]},
            "total_whole": {"sum_q_wp": c["total_whole"], "sum_q_wp_sales_only": c["total_whole_sales"]},
            "total_sell": {"no_discount": c["sell_no_disc"], "discount_1pct": c["sell_disc_pct"],
                           "no_discount_sales_only": c["sell_sales"], "discount_1pct_sales_only": c["sell_disc_sales"]},
            "avg_loss": {n: c[n] for n in ("avg_lr_joined_rows", "avg_lr_items", "avg_lr_sale_rows", "avg_lr_qty_weighted_sales",
                                           "avg_lr_items_sold_in_year", "avg_lr_items_priced_in_year", "avg_lr_whsle_rows")},
            "total_loss": {"sum_q_wp_lr": c["total_loss"], "sum_q_wp_lr_sales_only": c["total_loss_sales"]},
            "profit": {"sell_minus_whole_minus_loss": c["sell_no_disc"] - c["total_whole"] - c["total_loss"],
                       "disc_sell_minus_whole_minus_loss": c["sell_disc_pct"] - c["total_whole"] - c["total_loss"],
                       "sales_only": c["sell_sales"] - c["total_whole_sales"] - c["total_loss_sales"],
                       "sales_only_disc": c["sell_disc_sales"] - c["total_whole_sales"] - c["total_loss_sales"]},
        }
        for col, gv in zip(cols, g):
            for n, v in opts[col].items():
                hits[col][n] = hits[col].get(n, 0) + (abs(r2(v) - gv) <= 0.0100001)
    print(f"{f}: {len(body)} rows; per column, rows matched (|round2 - gold| <= 0.01) by each reading")
    for col in cols:
        print(f"   {col:12s} " + ", ".join(f"{n}={m}" for n, m in hits[col].items()))
