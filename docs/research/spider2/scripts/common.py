"""Shared loader: in-memory indexed copy of delivery_center + moment parsing."""
import re, sqlite3
from datetime import datetime
DB = "data/spider2/delivery_center.sqlite"
MOMENTS = ["created", "accepted", "ready", "collected", "in_expedition", "delivering", "delivered", "finished"]
METRICS = ["collected_time", "paused_time", "production_time", "walking_time", "expediton_speed_time", "transit_time", "cycle_time"]
FMT = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4}) (\d{1,2}):(\d{2}):(\d{2}) (AM|PM)$")

def connect():
    src = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con = sqlite3.connect(":memory:")
    src.backup(con)
    return con

def parse(s):
    """Return epoch seconds (naive, treated as UTC) or None; raise on unknown format."""
    if s is None:
        return None
    m = FMT.match(s)
    if not m:
        raise ValueError(repr(s))
    mo, d, y, h, mi, se, ap = m.groups()
    h = int(h) % 12 + (12 if ap == "PM" else 0)
    return datetime(int(y), int(mo), int(d), h, int(mi), int(se)).timestamp() if False else \
        (datetime(int(y), int(mo), int(d), h, int(mi), int(se)) - datetime(1970, 1, 1)).total_seconds()

def fmt(t):
    """Inverse of parse: epoch seconds -> 'M/D/YYYY h:mm:ss AM'."""
    from datetime import timedelta
    dt = datetime(1970, 1, 1) + timedelta(seconds=t)
    h12 = dt.hour % 12 or 12
    return f"{dt.month}/{dt.day}/{dt.year} {h12}:{dt.minute:02d}:{dt.second:02d} {'AM' if dt.hour < 12 else 'PM'}"

def load_orders(con):
    cols = ["order_id", "store_id", "channel_id", "order_status", "order_amount", "order_delivery_fee",
            "order_delivery_cost", "order_created_hour", "order_created_minute", "order_created_day",
            "order_created_month", "order_created_year"] + [f"order_moment_{m}" for m in MOMENTS] + \
           [f"order_metric_{m}" for m in METRICS]
    rows = con.execute(f"select {','.join(cols)} from orders").fetchall()
    return cols, rows
