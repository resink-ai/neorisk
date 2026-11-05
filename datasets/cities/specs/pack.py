"""World cities: a cleaned world-cities table with a synthetic insert date, and country,
currency and language lookups (Jaime M. Shaker's SQL Coding Challenge). Stage 1, schema only:
the entities are ingested from the Spider2 tables (docs/research/spider2/cities.md); stage 2
adds the behavior.

A city's creation is its insertion (`city_inserted`), at `insert_date`. Its capital flag and
population are snapshot columns at N = 2024-07-18, the countries' `created_on`. The source's `latitude` holds longitudes
and `longitude` latitudes; both are carried as stored, never repaired.
"""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, f64, i64, opt, ref, text

SCHEMA_VERSION = 1


@dataclass
class Config:
    pass


def define(p: Pack) -> None:
    p.entity("countries", key="country_key", doc="Created at the catalog start 2021-01-01 (rule)",
             cols={"ext_id": text(doc="country_code_2"),
                   "country_id": i64(doc="Carried: 15 gaps up to 256 from the upstream dedup"),
                   "country_name": text(), "country_code_3": text(), "region": text(),
                   "sub_region": opt(text()), "intermediate_region": opt(text())})
    p.entity("currencies", key="currency_key", doc="Created at the catalog start (rule)",
             cols={"ext_id": text(doc="Source currency_id"), "country": ref("countries"),
                   "currency_name": text(), "currency_code": opt(text())})
    p.entity("languages", key="language_key", doc="Created at the catalog start (rule)",
             cols={"ext_id": text(doc="Source language_id"), "language": text(),
                   "country": ref("countries")})
    p.entity("cities", key="city_key", doc="Created when inserted: insert_date, UTC midnight",
             cols={"ext_id": text(doc="Source city_id; local070 picks the lowest per date"),
                   "city_name": opt(text(doc="NULL for city 9272, the town 'nan'")),
                   "latitude": f64(doc="Holds the longitude, as stored"),
                   "longitude": f64(doc="Holds the latitude, as stored"),
                   "country": ref("countries")})
    p.event("countries_snapshot", doc="The load stamp created_on: the event's date, 2024-07-18",
            cols={"country": ref("countries")})
    p.event("cities_snapshot", doc="State at N: the capital flag and the population",
            cols={"city": ref("cities"), "capital": i64(doc="0 or 1"),
                  "population": opt(i64(doc="Whole people; the source stores REAL"))})
