"""AdventureWorks: a bicycle maker's online and reseller sales orders, with quotas, reviews and
daily currency rates. Stage 1, schema only: the events are ingested from the Spider2 tables
(docs/research/spider2/adventureworks.md); stage 2 adds the behavior.

Order money is 4-decimal, held as integers of 1e-4 ("e4"); the views add them and divide once.
Columns that mix numbers with '' (the source's NULL) are carried as text: the source DDL's
affinity turns '274' back into 274 and leaves '' as text. Dimension timestamps are load stamps
in Postgres text ('…10:03:55.51'), carried verbatim.
"""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, f64, i64, ref, text

SCHEMA_VERSION = 1


@dataclass
class Config:
    pass


def define(p: Pack) -> None:
    stamp = {"rowguid": text(), "modifieddate": text(doc="Verbatim")}
    p.entity("product_categories", key="product_category_id",
             cols={"ext_id": text(), "name": text(), **stamp})
    p.entity("product_subcategories", key="product_subcategory_id",
             cols={"ext_id": text(), "product_category_id": ref("product_categories"),
                   "name": text(), **stamp})
    p.entity("products", key="product_id", doc="All 25 source columns, verbatim",
             cols={"ext_id": text(), "name": text(), "productnumber": text(),
                   "makeflag": text(doc="'t' or 'f'"), "finishedgoodsflag": text(),
                   "color": text(), "safetystocklevel": i64(), "reorderpoint": i64(),
                   "standardcost": f64(), "listprice": f64(), "size": text(),
                   "sizeunitmeasurecode": text(doc="nchar: keeps trailing spaces"),
                   "weightunitmeasurecode": text(), "weight": text(doc="Number or ''"),
                   "daystomanufacture": i64(), "productline": text(), "class": text(),
                   "style": text(), "productsubcategoryid": text(doc="Id or ''"),
                   "productmodelid": text(doc="Id or ''"), "sellstartdate": text(),
                   "sellenddate": text(), "discontinueddate": text(), **stamp})
    p.entity("product_descriptions", key="product_description_id",
             doc="A description and its one model/culture link row",
             cols={"ext_id": text(), "description": text(), **stamp,
                   "productmodelid": i64(), "cultureid": text(),
                   "link_modifieddate": text(doc="The link row's modifieddate")})
    p.entity("territories", key="territory_id", doc="Year-to-date counters are a stale snapshot",
             cols={"ext_id": text(), "name": text(), "countryregioncode": text(),
                   "group": text(), "salesytd": f64(), "saleslastyear": f64(),
                   "costytd": f64(), "costlastyear": f64(), **stamp})
    p.entity("salespersons", key="salesperson_id", doc="Counters are a stale snapshot",
             cols={"ext_id": text(), "territoryid": text(doc="Id or ''"),
                   "salesquota": text(doc="Number or ''"), "bonus": i64(),
                   "commissionpct": f64(), "salesytd": f64(), "saleslastyear": f64(),
                   **stamp})
    p.entity("country_currencies", key="country_currency_id",
             cols={"ext_id": text(doc="'<country>/<currency>'"), "countryregioncode": text(),
                   "currencycode": text(), "modifieddate": text()})
    p.event("order_placed", doc="Tax and freight are carried: reseller tax follows no rule",
            cols={"salesorderid": i64(), "revisionnumber": i64(),
                  "duedate": text(doc="The promise; always ship + 5 days"),
                  "onlineorderflag": text(), "purchaseordernumber": text(),
                  "accountnumber": text(), "customerid": i64(),
                  "salespersonid": text(doc="Id or ''"), "territory_id": ref("territories"),
                  "billtoaddressid": i64(), "shiptoaddressid": i64(), "shipmethodid": i64(),
                  "creditcardid": text(doc="Id or ''"), "creditcardapprovalcode": text(),
                  "currencyrateid": text(doc="Id or ''"), "taxamt_e4": i64(min=0),
                  "freight_e4": i64(min=0), "comment": text(), "rowguid": text()})
    p.event("order_line_added", doc="At its order's time",
            cols={"salesorderid": i64(), "salesorderdetailid": i64(),
                  "carriertrackingnumber": text(doc="One per reseller order, '' online"),
                  "orderqty": i64(min=1), "product_id": ref("products"),
                  "specialofferid": i64(), "unitprice_e4": i64(min=0),
                  "discount_pct": i64(min=0), "rowguid": text()})
    p.event("order_shipped", doc="Status becomes '5' (shipped)", cols={"salesorderid": i64()})
    p.event("currency_rate_published", doc="An exogenous daily rate from USD",
            cols={"tocurrencycode": text(), "currencyrateid": i64(),
                  "fromcurrencycode": text(), "averagerate": f64(), "endofdayrate": f64(),
                  "modifieddate": text(doc="Verbatim")})
    p.event("quota_set", doc="At ModifiedDate, 45 days before the quarter it sets",
            cols={"salesperson_id": ref("salespersons"), "quotadate": text(),
                  "salesquota": f64(), "rowguid": text(doc="Braced, upper case")})
    p.event("product_reviewed",
            cols={"product_id": ref("products"), "productreviewid": i64(),
                  "reviewername": text(), "emailaddress": text(), "rating": i64(),
                  "comments": text(doc="Contains LF")})
