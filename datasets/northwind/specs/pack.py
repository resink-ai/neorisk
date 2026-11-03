"""Northwind: a food wholesaler. Customers place orders with a promised date; a shipper ships
them days later. Stage 1, schema only: the events are ingested from the Spider2 tables
(docs/research/spider2/northwind.md); stage 2 adds the behavior.

Money is held in cents and discounts in whole percent. The source holds float4 values printed
at 9 digits (32.38 is 32.3800011); the views print them back that way.
"""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, amount, f64, i64, opt, ref, text

SCHEMA_VERSION = 1


@dataclass
class Config:
    pass


def o():
    """A nullable text column (most Northwind text columns)."""
    return opt(text())


def define(p: Pack) -> None:
    p.entity("categories", key="category_id",
             cols={"ext_id": text(), "categoryname": text(), "description": o(),
                   "picture": opt(text(doc="Hex text '\\x…', not a blob"))})
    p.entity("suppliers", key="supplier_id",
             cols={"ext_id": text(), "companyname": text(), "contactname": o(),
                   "contacttitle": o(), "address": o(), "city": o(), "region": o(),
                   "postalcode": o(), "country": o(), "phone": o(), "fax": o(), "homepage": o()})
    p.entity("products", key="product_id", doc="State at the snapshot: list price, stock",
             cols={"ext_id": text(), "productname": text(), "supplier_id": ref("suppliers"),
                   "category_id": ref("categories"), "quantityperunit": o(),
                   "unitprice": amount("USD"), "unitsinstock": i64(), "unitsonorder": i64(),
                   "reorderlevel": i64(), "discontinued": i64()})
    p.entity("shippers", key="shipper_id",
             cols={"ext_id": text(), "companyname": text(), "phone": o()})
    p.entity("region", key="region_id", cols={"ext_id": text(), "regiondescription": text()})
    p.entity("territories", key="territory_id",
             cols={"ext_id": text(doc="Text id with leading zeros"),
                   "territorydescription": text(), "region_id": ref("region")})
    p.entity("employees", key="employee_id", doc="Created at their hire date",
             cols={"ext_id": text(), "lastname": text(), "firstname": text(), "title": o(),
                   "titleofcourtesy": o(), "birthdate": o(), "address": o(), "city": o(),
                   "region": o(), "postalcode": o(), "country": o(), "homephone": o(),
                   "extension": o(), "photo": opt(text(doc="Hex text '\\x…', not a blob")),
                   "notes": o(), "reportsto": opt(ref("employees")), "photopath": o()})
    p.entity("employeeterritories", key="et_id",
             cols={"ext_id": text(doc="'<employeeid>/<territoryid>'"),
                   "employee_id": ref("employees"), "territory_id": ref("territories")})
    p.entity("customers", key="customer_id",
             doc="Created at their first order; the 2 with none at the snapshot (rules)",
             cols={"ext_id": text(), "companyname": text(), "contactname": o(),
                   "contacttitle": o(), "address": o(), "city": o(), "region": o(),
                   "postalcode": o(), "country": o(), "phone": o(), "fax": o()})
    p.entity("usstates", key="state_id",
             cols={"ext_id": text(), "statename": o(), "stateabbr": o(), "stateregion": o()})
    p.entity("customergroupthreshold", key="group_id", doc="Spend bands added for Spider2",
             cols={"ext_id": text(doc="groupname"), "rangebottom": i64(),
                   "rangetop": f64(doc="Verbatim; neither cents nor float4")})
    p.event("order_placed", doc="With the promised (required) date and the ship-to address",
            cols={"customer_id": ref("customers"), "orderid": i64(),
                  "employee_id": ref("employees"),
                  "required_lead_days": i64(doc="Always 14, 28 or 42"),
                  "ship_via": ref("shippers"), "freight": amount("USD"), "ship_name": text(),
                  "ship_address": text(), "ship_city": text(), "ship_region": o(),
                  "ship_postal_code": o(), "ship_country": text()})
    p.event("order_line_added", doc="At its order's time",
            cols={"customer_id": ref("customers"), "orderid": i64(),
                  "product_id": ref("products"), "unit_price": amount("USD"),
                  "quantity": i64(min=1), "discount_pct": i64(min=0)})
    p.event("order_shipped", cols={"customer_id": ref("customers"), "orderid": i64()})
