"""Reproduce the Spider2 pizza questions (local065, local066, local073) and match them
against the accepted gold result CSVs (values copied below from
https://raw.githubusercontent.com/xlang-ai/Spider2/main/spider2-lite/evaluation_suite/gold/exec_result/<id>_<v>.csv,
fetched 2026-10-30). Gold SQL exists for local065 and local066 only.

Run: python3 -I docs/research/spider2/scripts/pizzarunner/04_gold.py [data/spider2/modern_data.sqlite]
"""
import sqlite3
import sys
from collections import Counter

db = sys.argv[1] if len(sys.argv) > 1 else "data/spider2/modern_data.sqlite"
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)

GOLD_065 = {"a": 144, "b": 142}
GOLD_066 = {
    "a": dict(BBQ_Sauce=8, Bacon=12, Beef=9, Cheese=10, Chicken=9, Mushrooms=11, Onions=3, Pepperoni=9, Peppers=3, Salami=9, Tomato_Sauce=3, Tomatoes=3),
    "b": dict(Bacon=13, Cheese=11, Mushrooms=11, Beef=9, Chicken=9, Pepperoni=9, Salami=9, BBQ_Sauce=8, Onions=3, Peppers=3, Tomato_Sauce=3, Tomatoes=3),
    "c": dict(BBQ_Sauce=9, Bacon=13, Beef=9, Cheese=11, Chicken=9, Mushrooms=12, Onions=3, Pepperoni=9, Peppers=3, Salami=9, Tomato_Sauce=3, Tomatoes=3),
}
GOLD_073_ROW14 = "Meatlovers: 2x Bacon, 2x Cheese, Beef, Chicken, Pepperoni, Salami"

top = {i: n.replace(" ", "_") for i, n in con.execute("SELECT topping_id, topping_name FROM pizza_toppings")}
topname = {i: n for i, n in con.execute("SELECT topping_id, topping_name FROM pizza_toppings")}
rec = {p: [int(x) for x in t.split(",")] for p, t in con.execute("SELECT pizza_id, toppings FROM pizza_recipes")}
pname = dict(con.execute("SELECT pizza_id, pizza_name FROM pizza_names"))
canc = {o: c for o, c in con.execute("SELECT order_id, cancellation FROM pizza_runner_orders")}
lines = con.execute("SELECT rowid, order_id, customer_id, pizza_id, exclusions, extras FROM pizza_customer_orders ORDER BY rowid").fetchall()
sp = lambda s: [int(x) for x in s.split(",")] if s else []
order_excl = {}
for _, o, _, _, ex, _ in lines:
    order_excl.setdefault(o, set()).update(sp(ex))

# local065: gold SQL run verbatim
gold065_sql = open(__file__.replace("04_gold.py", "04_local065_gold.sql")).read()
v = con.execute(gold065_sql).fetchone()[0]
print("local065 gold SQL ->", v, "matches variant", [k for k, g in GOLD_065.items() if g == v])
base = sum(12 if p == 1 else 10 for _, o, _, p, _, _ in lines if canc[o] is None)
ext_deliv = sum(len(sp(e)) for _, o, _, _, _, e in lines if canc[o] is None)
ext_all = sum(len(sp(e)) for *_, e in lines)
print("local065 base delivered", base, "+ extras delivered", ext_deliv, "=", base + ext_deliv,
      "; + extras incl. cancelled", ext_all, "=", base + ext_all)


def usage(delivered_only, per_order_excl, extras_on):
    c = Counter()
    for _, o, _, p, ex, e in lines:
        if delivered_only and canc[o] is not None:
            continue
        drop = order_excl[o] if per_order_excl else set(sp(ex))
        for t in rec[p]:
            if t not in drop:
                c[top[t]] += 1
        if extras_on:
            for t in sp(e):
                c[top[t]] += 1
    return dict(c)


print()
for dlv in (True, False):
    for po in (False, True):
        for ex in (True, False):
            u = usage(dlv, po, ex)
            m = [k for k, g in GOLD_066.items() if g == u]
            print(f"local066 delivered_only={dlv!s:5} per_order_excl={po!s:5} extras={ex!s:5} Bacon={u.get('Bacon')} Cheese={u.get('Cheese')} total={sum(u.values())} matches={m}")
gold066 = dict((r[0].replace(" ", "_"), r[1]) for r in con.execute(open(__file__.replace("04_gold.py", "04_local066_gold.sql")).read()))
print("local066 gold SQL ->", gold066, "matches", [k for k, g in GOLD_066.items() if g == gold066])

# local073: per line recipe - own exclusions + own extras, "2x" first, then alphabetical
print()
out = []
for r, o, cust, p, ex, e in lines:
    c = Counter(t for t in rec[p] if t not in sp(ex))
    for t in sp(e):
        c[t] += 1
    dbl = sorted(topname[t] for t, n in c.items() if n > 1)
    one = sorted(topname[t] for t, n in c.items() if n == 1)
    out.append((r, o, cust, pname[p], f"{pname[p]}: " + ", ".join([f"2x {x}" for x in dbl] + one)))
for row in out:
    print("local073", *row, sep=" | ")
print("local073 row 14 equals gold_a:", out[-1][4] == GOLD_073_ROW14)
print("local073 extras already in recipe (2x rows):", sum("2x" in x[4] for x in out))

# full comparison of local073 against the gold CSVs saved in gold/ (copied from the URL above)
import csv, os
gdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gold")
for v in ("a", "b"):
    g = [tuple(r) for r in csv.reader(open(os.path.join(gdir, f"local073_{v}.csv")))][1:]
    mine = [(str(r), str(o), str(c), n, s) for r, o, c, n, s in out]
    mine_b = [(a, b, c, d, s.replace("2x ", "2x")) for a, b, c, d, s in mine]
    print(f"local073 all 14 rows equal gold_{v}:", g == mine, "| with '2x' (no space):", g == mine_b)
