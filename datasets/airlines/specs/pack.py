"""Airlines: flights opening for sale, check-in and departure; bookings that buy tickets with
one or more flight segments; boarding passes. Stage 1, schema only: the events are ingested
from the Spider2 tables (docs/research/spider2/airlines.md, E1–E10); stage 2 adds the behavior.

The log ends at the snapshot time N = 2017-08-15 18:00 (+03), and the tables are the state
at N. Times the source does not have are chosen by rule: a flight is scheduled 30 days before
departure (capped at N) and cancelled at that moment; check-in opens 24 h before departure;
tickets and segments are bought at the booking; a passenger checks in 130 to 90 minutes
before departure in boarding-number order (capped at N). Only the contents are exact.
"""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, amount, cat, i64, ref, text, ts

SCHEMA_VERSION = 1

CLASSES = ("Business", "Comfort", "Economy")


@dataclass
class Config:
    pass


def define(p: Pack) -> None:
    p.entity("aircrafts", key="aircraft_key", doc="Aircraft models",
             cols={"ext_id": text(doc="aircraft_code"), "model": text(doc="JSON text, verbatim"),
                   "range": i64(doc="km")})
    p.entity("airports", key="airport_key", doc="Airports",
             cols={"ext_id": text(doc="airport_code"), "airport_name": text(doc="JSON text"),
                   "city": text(doc="JSON text"), "coordinates": text(doc="'(lon,lat)' text"),
                   "timezone": text()})
    p.entity("seats", key="seat_key", doc="Seat maps per aircraft",
             cols={"ext_id": text(doc="aircraft_code/seat_no"), "aircraft_key": ref("aircrafts"),
                   "seat_no": text(), "fare_conditions": cat(*CLASSES)})

    p.event("flight_scheduled", doc="E1: a flight opens for sale",
            cols={"flight_id": i64(), "flight_no": text(), "scheduled_departure": ts(),
                  "scheduled_arrival": ts(), "departure_airport": ref("airports"),
                  "arrival_airport": ref("airports"), "aircraft_key": ref("aircrafts")})
    p.event("flight_cancelled", doc="E2: overrides any other status", cols={"flight_id": i64()})
    p.event("checkin_opened", doc="E3: 24 h before departure (status On Time)",
            cols={"flight_id": i64()})
    p.event("flight_delayed", doc="E4: status Delayed", cols={"flight_id": i64()})
    p.event("flight_departed", doc="E5: at the actual departure", cols={"flight_id": i64()})
    p.event("flight_arrived", doc="E6: at the actual arrival", cols={"flight_id": i64()})
    p.event("booking_created", doc="E7: total_amount is the sum of its segments",
            cols={"book_ref": text()})
    p.event("ticket_issued", doc="E8: one passenger's ticket in the booking",
            cols={"ticket_no": text(), "book_ref": text(), "passenger_id": text()})
    p.event("segment_sold", doc="E9: a seat of a class on one flight, for the ticket",
            cols={"ticket_no": text(), "book_ref": text(), "flight_id": i64(),
                  "fare_conditions": cat(*CLASSES),
                  "amount": amount("RUB", doc="Minor units; the source has whole roubles")})
    p.event("passenger_checked_in", doc="E10: boarding pass and seat",
            cols={"ticket_no": text(), "flight_id": i64(), "boarding_no": i64(),
                  "seat_no": text()})
