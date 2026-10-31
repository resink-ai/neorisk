"""Search for the rule behind payment.amount for returned rentals.

Candidates: amount = rental_rate + max(0, D - rental_duration) * fee, with D one of several
day-count definitions. Also checks the open (unreturned) rentals and amount as k × rental_rate.
Usage: python3 -I p5_fee_rule.py DB
"""
import math, sqlite3, sys
from collections import Counter
from datetime import datetime

con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
rows = con.execute("""select p.payment_id, p.amount, f.rental_rate, f.rental_duration, r.rental_date, r.return_date
  from payment p join rental r using(rental_id) join inventory i using(inventory_id) join film f using(film_id)""").fetchall()
P = lambda s: datetime.strptime(s, "%Y-%m-%d %H:%M:%S.%f")
ret = [(pid, a, rate, dur, P(rd), P(rt)) for pid, a, rate, dur, rd, rt in rows if rt is not None]
opn = [(pid, a, rate, dur) for pid, a, rate, dur, rd, rt in rows if rt is None]

defs = {
    "floor(days)": lambda s, e: math.floor((e - s).total_seconds() / 86400),
    "ceil(days)": lambda s, e: math.ceil((e - s).total_seconds() / 86400),
    "round(days)": lambda s, e: round((e - s).total_seconds() / 86400),
    "calendar days (date(e)-date(s))": lambda s, e: (e.date() - s.date()).days,
}
print(f"returned rentals with payment: {len(ret)}")
for name, D in defs.items():
    resid = Counter(round(a - (rate + max(0, D(s, e) - dur)), 2) for _, a, rate, dur, s, e in ret)
    print(f"  {name:34} exact={resid.get(0.0, 0):6}  residuals={dict(sorted(resid.items()))}")

# Best rule: calendar days. Where does it fail?
D = defs["calendar days (date(e)-date(s))"]
bad = [(pid, a, rate, dur, s, e, D(s, e)) for pid, a, rate, dur, s, e in ret if abs(a - (rate + max(0, D(s, e) - dur))) > 1e-9]
print(f"calendar-day rule failures: {len(bad)}")
for b in bad[:15]:
    print("   ", b)

# Is the late fee capped? (days late distribution under the calendar rule)
late = Counter(max(0, D(s, e) - dur) for _, a, rate, dur, s, e in ret)
print("days late (calendar rule):", dict(sorted(late.items())))

# Open rentals: amount / rental_rate
print(f"open rentals with payment: {len(opn)}")
print("  amount / rental_rate:", dict(sorted(Counter(round(a / rate, 3) for _, a, rate, dur in opn).items())))
