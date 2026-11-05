"""Sakila: a DVD rental chain. Customers rent a copy, pay at checkout (the amount already holds
the late fee of the later return), and return it. Stage 1, schema only: the events are ingested
from the Spider2 tables (docs/research/spider2/pagila.md); stage 2 adds the behavior.

`last_update` is the port's load clock (2021-03-06), carried verbatim as text everywhere; on
entities it is a snapshot column. Snapshots are at N = 2006-02-15 00:00:00, the day after the
last rental and payment (a rule).
"""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, amount, i64, opt, ref, text

SCHEMA_VERSION = 1


@dataclass
class Config:
    pass


def define(p: Pack) -> None:
    lu = {"last_update": text(doc="Load clock, verbatim")}
    p.entity("language", key="language_id", cols={"ext_id": text(), "name": text()})
    p.entity("country", key="country_id", cols={"ext_id": text(), "country": text()})
    p.entity("city", key="city_id",
             cols={"ext_id": text(), "city": text(), "country_id": ref("country")})
    p.entity("address", key="address_id",
             cols={"ext_id": text(), "address": text(), "address2": opt(text()),
                   "district": text(), "city_id": ref("city"), "postal_code": opt(text())})
    p.entity("store", key="store_id", cols={"ext_id": text()})
    p.entity("staff", key="staff_id", doc="picture is always NULL",
             cols={"ext_id": text(), "first_name": text(), "last_name": text(),
                   "store_id": ref("store", doc="Kept: it places every rental (local199)"),
                   "username": text()})
    p.entity("customer", key="customer_id",
             cols={"ext_id": text(), "first_name": text(), "last_name": text(),
                   "address_id": ref("address", doc="Kept: it places every rental (local039)")})
    p.entity("actor", key="actor_id",
             cols={"ext_id": text(), "first_name": text(), "last_name": text()})
    p.entity("category", key="category_id", cols={"ext_id": text(), "name": text()})
    p.entity("film", key="film_id", doc="Each film has exactly one category (film_category)",
             cols={"ext_id": text(), "title": text(), "description": opt(text()),
                   "release_year": opt(text()), "language_id": ref("language"),
                   "original_language_id": opt(ref("language")), "length": opt(i64()),
                   "rating": opt(text()), "special_features": opt(text()),
                   "category_id": ref("category")})
    p.entity("film_actor", key="film_actor_id",
             cols={"ext_id": text(doc="'<actor_id>/<film_id>'"), "actor_id": ref("actor"),
                   "film_id": ref("film")})
    p.entity("inventory", key="inventory_id",
             cols={"ext_id": text(), "film_id": ref("film"),
                   "store_id": ref("store", doc="Kept: it places every rental of the copy")})
    p.event("rental_started",
            cols={"customer_id": ref("customer"), "rental_id": i64(),
                  "inventory_id": ref("inventory"), "staff_id": ref("staff"), **lu})
    p.event("payment_taken", doc="At checkout; the amount includes the later return's late fee",
            cols={"customer_id": ref("customer"), "payment_id": i64(),
                  "rental_id": opt(i64(doc="NULL for the 5 payments of deleted rentals")),
                  "staff_id": ref("staff"), "amount": amount("USD"), **lu})
    p.event("rental_returned", cols={"customer_id": ref("customer"), "rental_id": i64()})
    for e in ("language", "country", "city", "actor", "category", "film_actor", "inventory"):
        p.event(f"{e}_snapshot", doc="State at N: the load clock",
                cols={f"{e}_id": ref(e), **lu})
    p.event("address_snapshot", doc="State at N: the phone and the load clock",
            cols={"address_id": ref("address"), "phone": text(), **lu})
    p.event("store_snapshot", doc="State at N: the manager, the address and the load clock",
            cols={"store_id": ref("store"), "manager_staff_id": ref("staff"),
                  "address_id": ref("address"), **lu})
    p.event("staff_snapshot", doc="State at N: address, e-mail, active flag, password",
            cols={"staff_id": ref("staff"), "address_id": ref("address"), "email": opt(text()),
                  "active": i64(), "password": opt(text()), **lu})
    p.event("customer_snapshot", doc="State at N: store, e-mail, active flag, the load stamps",
            cols={"customer_id": ref("customer"), "store_id": ref("store"),
                  "email": opt(text()), "active": text(doc="'0' or '1'"),
                  "create_date": text(doc="Verbatim; a load stamp later than every rental"),
                  **lu})
    p.event("film_snapshot", doc="State at N: the rental terms, the prices and the load clocks",
            cols={"film_id": ref("film"), "rental_duration": i64(doc="Days included in the rate"),
                  "rental_rate": amount("USD"), "replacement_cost": amount("USD"), **lu,
                  "film_category_last_update": text(doc="film_category's load clock")})
