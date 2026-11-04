"""oraclesql: the PRACTICAL demo schema of Kim Berg Hansen's book Practical Oracle SQL
(Apress, 2020). A fictional craft-beer trader: brewery purchases put away as warehouse lots,
customer orders picked FIFO, monthly sales and budgets, staff hire periods, plus a webshop's
counters and visits, server heartbeats and a stock ticker.
Stage 1, schema only: the events are ingested from the Spider2 tables
(docs/research/spider2/oraclesql.md); stage 2 adds the behavior.
"""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, amount, f64, i64, opt, ref, text

SCHEMA_VERSION = 1


@dataclass
class Config:
    pass


def define(p: Pack) -> None:
    # masters: created 2016-01-01, the first purchase (a rule), unless stated
    p.entity("product_groups", key="group_key", cols={"ext_id": text(), "name": text()})
    p.entity("products", key="product_key", doc="product_alcohol folded in (10 of 10)",
             cols={"ext_id": text(), "name": text(), "group_id": ref("product_groups"),
                   "sales_volume": i64(), "abv": f64(doc="Halves, 4.0-8.5")})
    p.entity("breweries", key="brewery_key", cols={"ext_id": text(), "name": text()})
    p.entity("customers", key="customer_key", cols={"ext_id": text(), "name": text()})
    p.entity("packaging", key="packaging_key", cols={"ext_id": text(), "name": text()})
    p.entity("packaging_relations", key="prel_key",
             cols={"ext_id": text(doc="'<packaging_id>:<contains_id>'"),
                   "packaging_id": ref("packaging"), "contains_id": ref("packaging"),
                   "qty": i64()})
    p.entity("employees", key="employee_key",
             doc="Created at their first hire period's start, else 2016-01-01 (a rule)",
             cols={"ext_id": text(), "name": text()})
    p.entity("web_apps", key="app_key", cols={"ext_id": text(), "name": text()})
    p.entity("web_pages", key="page_key",
             cols={"ext_id": text(doc="'<app_id>:<page_no>'"), "app_id": ref("web_apps"),
                   "page_no": i64(), "friendly_url": text()})
    p.entity("stock", key="stock_key", cols={"ext_id": text(doc="symbol"), "company": text()})
    p.entity("channels_dim", key="channel_key",
             cols={"ext_id": text(), "name": text(), "shortcut": text()})
    p.entity("gender_dim", key="gender_key", cols={"ext_id": text(doc="letter"), "name": text()})

    # brewery trading
    p.event("purchase_received", doc="A brewery delivery, on its date",
            cols={"brewery_id": ref("breweries"), "purchase_id": i64(),
                  "product_id": ref("products"), "qty": i64(), "cost": amount("EUR")})
    p.event("lot_stored", doc="A lot put on a shelf, at its purchase's date (a rule)",
            cols={"product_id": ref("products"), "inventory_id": i64(),
                  "location_id": i64(), "purchase_id": i64(), "qty": i64()})
    p.event("monthly_sales_reported", doc="A month's sales, at the month's first day",
            cols={"product_id": ref("products"), "qty": i64()})
    p.event("budget_set", doc="A month's budget, at Jan 1 of its year (a rule)",
            cols={"product_id": ref("products"), "mth": text(), "qty": i64()})
    p.event("order_placed", doc="delivery is NULL in every row",
            cols={"customer_id": ref("customers"), "order_id": i64()})
    p.event("order_line_added", doc="At its order's time",
            cols={"customer_id": ref("customers"), "orderline_id": i64(), "order_id": i64(),
                  "product_id": ref("products"), "qty": i64(), "amount": amount("EUR")})
    # warehouse staff and picking
    p.event("picklist_created", cols={"picker_emp_id": ref("employees"), "picklist_id": i64()})
    p.event("pick_line_planned", doc="At its picklist's creation (a rule)",
            cols={"picker_emp_id": ref("employees"), "picklist_id": i64(), "line_no": i64(),
                  "location_id": i64(), "order_id": i64(), "product_id": ref("products"),
                  "qty": i64()})
    for e, d in (("picker_arrived", "picking_log 'A'"), ("line_picked", "picking_log 'P'"),
                 ("picker_departed", "picking_log 'D'")):
        p.event(e, doc=d, cols={"picker_emp_id": ref("employees"), "picklist_id": i64(),
                                "location_id": opt(i64()), "pickline_no": opt(i64())})
    p.event("hire_period_started", cols={"employee_id": ref("employees"), "title": text()})
    p.event("hire_period_ended", doc="Links to its period by start date",
            cols={"employee_id": ref("employees"), "start": text(doc="'YYYY-MM-DD'")})
    # web analytics and the ticker
    p.event("page_counter_read", doc="A page's cumulative counter, daily",
            cols={"page_id": ref("web_pages"), "counter": i64()})
    p.event("page_visited", cols={"client_ip": text(), "page_id": ref("web_pages"),
                                  "src_rowid": i64()})
    p.event("heartbeat_received", doc="To the minute", cols={"server": text()})
    p.event("device_counts_reported", doc="A day's visits by device",
            cols={"app_id": ref("web_apps"), "pc": i64(), "tablet": i64(), "phone": i64()})
    p.event("demographics_reported", doc="A day's visits by gender and channel",
            cols={"app_id": ref("web_apps"), "m_tw_cnt": i64(), "m_tw_qty": i64(),
                  "m_fb_cnt": i64(), "m_fb_qty": i64(), "f_tw_cnt": i64(), "f_tw_qty": i64(),
                  "f_fb_cnt": i64(), "f_fb_qty": i64()})
    p.event("price_quoted", doc="A weekday close", cols={"stock_id": ref("stock"),
                                                          "price": f64(doc="Tenths")})
    # snapshot columns, at N = 2019-05-02 (a rule)
    p.event("customers_snapshot", doc="customer_favorites and customer_reviews",
            cols={"customer_id": ref("customers"), "favorite_list": opt(text()),
                  "review_list": opt(text())})
    p.event("employees_snapshot",
            cols={"employee_id": ref("employees"), "title": text(),
                  "supervisor_id": opt(ref("employees"))})
    p.event("products_snapshot", doc="product_minimums",
            cols={"product_id": ref("products"), "qty_minimum": i64(), "qty_purchase": i64()})
