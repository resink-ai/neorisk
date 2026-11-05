"""Web and app logs: the sample tables of a SQL-recipes book for log analysis. Each source log
stays one event type; the user and product masters become change events. Stage 1, schema only:
the events are ingested from the Spider2 tables (docs/research/spider2/weblog.md).

Ids are text everywhere (no user or session entity): ids conflict across tables, users have
2 versions, and 19 access_log rows are column-shifted. Every log keeps its source rowid, the
order among equal stamps that the benchmark questions depend on. Money is whole yen.
"""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, i64, opt, ref, text

SCHEMA_VERSION = 1


@dataclass
class Config:
    pass


def t():
    """Nullable verbatim text: the logs are deliberately dirty."""
    return opt(text())


def define(p: Pack) -> None:
    row = {"src_rowid": i64(doc="Source rowid: the order among equal stamps")}
    for name, doc in (("app1_users", "app1_mst_users"), ("app2_users", "app2_mst_users")):
        other = "email" if name == "app1_users" else "phone"
        p.entity(name, key=f"{name}_key",
                 doc=f"{doc}; untimed, created by rule at 2016-01-01; the {other} is a snapshot",
                 cols={"ext_id": text(doc="user_id"), "name": t()})
        p.event(f"{name}_snapshot", doc=f"State at N: the {other}",
                cols={f"{name}_key": ref(name), other: t()})
    p.entity("user_cards", key="user_card_key", doc="Card holders; the card is a snapshot",
             cols={"ext_id": text(doc="user_id")})
    p.event("user_cards_snapshot", doc="State at N: the masked card number ('dddd' + 12 'x')",
            cols={"user_card_key": ref("user_cards"), "card_number": t()})
    p.entity("product_sales", key="product_sales_key",
             doc="An untimed sales aggregate; the total is a snapshot",
             cols={"ext_id": text(doc="product_id"), "category_name": t()})
    p.event("product_sales_snapshot", doc="State at N: the lifetime sales total",
            cols={"product_sales_key": ref("product_sales"), "sales": opt(i64())})
    p.event("access_logged", doc="19 rows are column-shifted: the time is in `session`",
            cols={"user_id": t(), "session": t(), "action": t(),
                  "shifted": i64(doc="1 when stamp holds a path, not a time"),
                  "path_in_stamp": t(), **row})
    p.event("action_logged",
            cols={"session": t(), "user_id": t(), "action": t(), "category": t(),
                  "products": t(), "amount": opt(i64(doc="Yen")), **row})
    p.event("action_with_ip_logged",
            cols={"session": t(), "user_id": t(), "action": t(), "ip": t(), **row})
    p.event("noisy_action_logged", doc="Empty in this copy",
            cols={"session": t(), "action": t(), "products": t(), "url": t(), "ip": t(),
                  "user_agent": t(), **row})
    p.event("dup_action_logged",
            cols={"session": t(), "user_id": t(), "action": t(), "products": t(), **row})
    p.event("invalid_action_logged", doc="One stamp is NULL: its time is a rule",
            cols={"stamp_null": i64(doc="1 when the source stamp is NULL"), "session": t(),
                  "user_id": t(), "action": t(), "category": t(), "products": t(),
                  "amount": opt(i64(doc="Yen")), **row})
    p.event("activity_logged",
            cols={"session": t(), "action": t(), "option": t(), "path": t(),
                  "search_type": t(), **row})
    p.event("read_logged", cols={"session": t(), "action": t(), "url": t(), **row})
    p.event("form_viewed",
            cols={"session": t(), "action": t(), "path": t(), "status": t(), **row})
    p.event("form_error_logged",
            cols={"session": t(), "form": t(), "field": t(), "error_type": t(), "value": t(),
                  **row})
    p.event("purchase_logged",
            cols={"user_id": t(), "purchase_id": i64(), "amount": opt(i64(doc="Yen")), **row})
    p.event("user_registered", doc="One per mst_users row, duplicates and versions included",
            cols={"user_id": t(), "sex": t(), "birth_date": t(), "register_device": t(),
                  "withdraw_date": t(), **row})
    p.event("category_named", cols={"id": i64(), "name": t(), **row})
    p.event("product_updated", doc="A product's name and price from this time on",
            cols={"product_id": text(), "name": t(), "price": opt(i64(doc="Yen"))})
    p.event("product_deleted", doc="Time is a rule: the first snapshot's cut",
            cols={"product_id": text()})
