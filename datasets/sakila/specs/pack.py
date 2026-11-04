"""Sakila: a DVD rental chain. Customers rent a copy, pay at checkout (the amount already holds
the late fee of the later return), and return it. Stage 1, schema only: the events are ingested
from the Spider2 tables (docs/research/spider2/pagila.md); stage 2 adds the behavior.

`last_update` is the port's load clock (2021-03-06), carried verbatim as text everywhere.
"""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, amount, i64, opt, ref, text

SCHEMA_VERSION = 1


@dataclass
class Config:
    pass


def define(p: Pack) -> None:
    lu = {"last_update": text(doc="Load clock, verbatim")}
    p.entity("language", key="language_id", cols={"ext_id": text(), "name": text(), **lu})
    p.entity("country", key="country_id", cols={"ext_id": text(), "country": text(), **lu})
    p.entity("city", key="city_id",
             cols={"ext_id": text(), "city": text(), "country_id": ref("country"), **lu})
    p.entity("address", key="address_id",
             cols={"ext_id": text(), "address": text(), "address2": opt(text()),
                   "district": text(), "city_id": ref("city"), "postal_code": opt(text()),
                   "phone": text(), **lu})
    p.entity("store", key="store_id",
             cols={"ext_id": text(), "manager_staff_id": ref("staff"),
                   "address_id": ref("address"), **lu})
    p.entity("staff", key="staff_id", doc="picture is always NULL",
             cols={"ext_id": text(), "first_name": text(), "last_name": text(),
                   "address_id": ref("address"), "email": opt(text()), "store_id": ref("store"),
                   "active": i64(), "username": text(), "password": opt(text()), **lu})
    p.entity("customer", key="customer_id",
             cols={"ext_id": text(), "store_id": ref("store"), "first_name": text(),
                   "last_name": text(), "email": opt(text()), "address_id": ref("address"),
                   "active": text(doc="'0' or '1'"),
                   "create_date": text(doc="Verbatim; later than every rental"), **lu})
    p.entity("actor", key="actor_id",
             cols={"ext_id": text(), "first_name": text(), "last_name": text(), **lu})
    p.entity("category", key="category_id", cols={"ext_id": text(), "name": text(), **lu})
    p.entity("film", key="film_id", doc="Each film has exactly one category (film_category)",
             cols={"ext_id": text(), "title": text(), "description": opt(text()),
                   "release_year": opt(text()), "language_id": ref("language"),
                   "original_language_id": opt(ref("language")),
                   "rental_duration": i64(doc="Days included in the rate"),
                   "rental_rate": amount("USD"), "length": opt(i64()),
                   "replacement_cost": amount("USD"), "rating": opt(text()),
                   "special_features": opt(text()), **lu,
                   "category_id": ref("category"),
                   "film_category_last_update": text(doc="film_category's load clock")})
    p.entity("film_actor", key="film_actor_id",
             cols={"ext_id": text(doc="'<actor_id>/<film_id>'"), "actor_id": ref("actor"),
                   "film_id": ref("film"), **lu})
    p.entity("inventory", key="inventory_id",
             cols={"ext_id": text(), "film_id": ref("film"), "store_id": ref("store"), **lu})
    p.event("rental_started",
            cols={"customer_id": ref("customer"), "rental_id": i64(),
                  "inventory_id": ref("inventory"), "staff_id": ref("staff"), **lu})
    p.event("payment_taken", doc="At checkout; the amount includes the later return's late fee",
            cols={"customer_id": ref("customer"), "payment_id": i64(),
                  "rental_id": opt(i64(doc="NULL for the 5 payments of deleted rentals")),
                  "staff_id": ref("staff"), "amount": amount("USD"), **lu})
    p.event("rental_returned", cols={"customer_id": ref("customer"), "rental_id": i64()})
