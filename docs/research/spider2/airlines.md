# Airlines (Spider 2.0-lite): reverse-engineered event log

Source: `spider2db/Airlines.sqlite` (104 MB), opened read-only. `scripts/airlines/aq.py` copies the file into an in-memory SQLite and adds indexes (the file has none). The file itself is never written. Every number below comes from a named query in `scripts/airlines/q*.sql`, and the raw outputs are in `scripts/airlines_out_q*.txt`. A reference such as `[q2:overbooking]` means file `q2_quirks.sql`, block `-- name: overbooking`.

## 0. Provenance

- **Dataset.** This is the Postgres Pro demo database "Airlines" (schema `bookings`), English edition, **demo-small, version 2017-08-15**.
  - The row counts match the small edition: 33,121 flights, 262,788 bookings, 366,733 tickets, 1,045,726 ticket_flights, 579,686 boarding_passes [q1:pk_uniqueness].
  - The snapshot time `bookings.now()` is **2017-08-15 18:00:00+03**. This is the latest `book_date` and the latest `actual_arrival` [q1:time_ranges].
  - The flights cover now ±30 days (2017-07-16 to 2017-09-14), which is the "one month of flight data" of the small edition.
- **Docs.**
  - Appendix "Demo Database Airlines": https://postgrespro.com/docs/postgrespro/12/demodb-bookings-installation. It lists small = one month, medium = three months, big = one year, and calls the download "virtually … a backup copy created with pg_dump".
  - Schema objects: https://postgrespro.com/docs/postgrespro/12/demodb-schema-objects. It gives the status definitions (quoted in §2), says bookings are made "not earlier than one month before the flight", says `total_amount` is "the total cost of all tickets included into the booking", says boarding passes are numbered "in the order of check-ins", and describes `bookings.now()` as the snapshot time that "determines the version".
  - The community page https://postgrespro.com/community/demodb now serves the **2025-09-01** release, which is a different and larger world network with a 2025-12-01 snapshot. It describes the 2017-08-15 edition as a previous release.
- **How it was generated.** The data is synthetic. Postgres Pro built it with an in-house PL/pgSQL generator that simulates bookings and flights and then cut a snapshot at `now()`. The generator for the 2017 edition was not published with the dump; the 2025 page mentions a generator without describing it. This is why the data is so regular (§4).
- **Spider changes from the original.**
  - `tickets.passenger_name` and `tickets.contact_data` are **dropped**.
  - Nulls are the literal text `\N`: 16,348 in `actual_departure` and 16,406 in `actual_arrival`. There are no SQL NULLs [q1:backslash_N_counts].
  - `model`, `airport_name` and `city` are JSON text `{"en":…, "ru":…}`, and all 104 values are valid JSON [q1:airports_summary].
  - `coordinates` is the text `(lon,lat)`.
  - Every timestamp is text `YYYY-MM-DD HH:MM:SS+03` (Moscow time), at minute granularity [q1:tz_suffixes, q3:book_minute_granularity].
  - Amounts are integers in whole roubles, all multiples of 100 [q2:amounts_rounding].
  - The views (`flights_v`, `routes`, `aircrafts` and `airports` with a language setting) are absent.

## 1. Table inventory, keys, joins

| Table | Rows | Key (verified unique) | Kind |
|---|---|---|---|
| aircrafts_data | 9 | aircraft_code | static |
| airports_data | 104 (101 cities; Moscow = SVO, VKO, DME; Ulyanovsk = ULY, ULV; 17 time zones) | airport_code | static |
| seats | 1,339 | (aircraft_code, seat_no) | static (cabin layout) |
| flights | 33,121 | flight_id; also (flight_no, date) | activity, with a mutable status |
| bookings | 262,788 | book_ref (6 hex characters) | activity |
| tickets | 366,733 | ticket_no (13 digits, `000543…`); passenger_id is unique per ticket (366,733 distinct) | activity |
| ticket_flights | 1,045,726 | (ticket_no, flight_id) | activity |
| boarding_passes | 579,686 | (ticket_no, flight_id); also (flight_id, boarding_no) and (flight_id, seat_no) | activity |

Sources: [q1:pk_uniqueness, q1:passenger_id_reuse, q1:multi_airport_cities, q6:book_ref_format]

**Join coverage** [q1:fk_coverage]. Every foreign key resolves at 100%:
- tickets → bookings
- ticket_flights → tickets and flights
- boarding_passes → ticket_flights
- the seat on each boarding pass exists in the `seats` of that flight's aircraft
- flights → aircraft and airports

The reverse direction:
- Every booking has at least one ticket, and every ticket has at least one leg.
- Only **22,226 of 33,121 flights (67.1%)** have any ticket.
- Aircraft 320 (A320) has seats but **0 flights** [q1:aircrafts_with_seats].

**Seat counts** [q1:aircrafts_with_seats]:

| Aircraft | Seats | Business / Comfort / Economy | Flights |
|---|---|---|---|
| 319 | 116 | 20 / 0 / 96 | 1,239 |
| 320 | 140 | 20 / 0 / 120 | 0 |
| 321 | 170 | 28 / 0 / 142 | 1,952 |
| 733 | 130 | 12 / 0 / 118 | 1,274 |
| 763 | 222 | 30 / 0 / 192 | 1,221 |
| 773 | 402 | 30 / 48 / 324 | 610 |
| CN1 | 12 | Economy only | 9,273 |
| CR2 | 50 | Economy only | 9,048 |
| SU9 | 97 | 12 / 0 / 85 | 8,504 |

**Timetable** [q5:sched_duration_constant_per_flightno, q5:dep_time_constant_per_flightno, q5:weekly_pattern]:
- There are 710 flight_nos over 618 ordered airport pairs [q1:routes].
- Each flight_no has a fixed origin, destination, aircraft, departure clock time and block time (710 of 710).
- 482 flight_nos fly daily (61 flights). The rest fly on 1, 2 or 3 weekdays (8, 9, 17, 18, 26 or 27 flights).

The flights table is therefore an expansion of a static timetable.

**flight_id** is grouped by flight_no rather than by time. Of consecutive ids, 25,790 of 33,120 share a flight_no, and only 16,536 are non-decreasing in departure time [q9:flight_id_vs_schedule]. A rebuild has to keep flight_id as data.

## 2. Event catalog and derivation rules

The dataset's "now" is **N = 2017-08-15 18:00+03**. All derived times are in +03.

Status definitions from the docs:
- **Scheduled:** "available for booking … one month before the planned departure date".
- **On Time:** "open for check-in (in twenty-four hours before the scheduled departure) and is not delayed".
- **Delayed:** the same, but delayed.
- **Departed:** airborne.
- **Arrived:** at the destination.
- **Cancelled:** cancelled.

| # | Event | Owner | Time | Attributes | Produces |
|---|---|---|---|---|---|
| E1 | `flight_scheduled` | flight | sched_dep − 30 d (the docs' "one month"). All sales are at least 4.7 d and at most 28.5 d before the first leg, so −30 d is consistent | flight_id, flight_no, sched dep/arr, dep/arr airport, aircraft_code | a `flights` row, status `Scheduled`, actuals `\N` |
| E2 | `flight_cancelled` | flight | **not observable**. Rule: at E1 + 0, because a cancelled flight never has tickets (§4) | flight_id | status `Cancelled` |
| E3 | `checkin_opened` | flight | sched_dep − 24 h (`On Time` spans −0.08 h to +24.0 h, `Scheduled` starts at +24.08 h [q5:status_windows]) | flight_id | status `On Time` |
| E4 | `flight_delayed` | flight | sched_dep − 24 h, with E3. `Delayed` appears across the whole window, from −2.75 h to +23.4 h [q5:status_windows] | flight_id | status `Delayed` |
| E5 | `flight_departed` | flight | actual_departure | flight_id, actual_departure | `actual_departure`, status `Departed` |
| E6 | `flight_arrived` | flight | actual_arrival | flight_id, actual_arrival | `actual_arrival`, status `Arrived` |
| E7 | `booking_created` | booking | book_date | book_ref, n_tickets, total_amount (derived) | a `bookings` row |
| E8 | `ticket_issued` | booking | **book_date** (no own time) | ticket_no, book_ref, passenger_id | a `tickets` row |
| E9 | `segment_sold` | booking → flight seat inventory | **book_date** (no own time) | ticket_no, flight_id, fare_conditions, amount | a `ticket_flights` row |
| E10 | `passenger_checked_in` | flight (counter and seat map) | **synthetic**: inside the check-in window before sched_dep (§3, §5), monotone in boarding_no within a flight, and ≤ N | ticket_no, flight_id, boarding_no, seat_no | a `boarding_passes` row |

**Projection at N.**
- `flights.status` is the latest of E1–E6 with t ≤ N. The order is Scheduled < On Time/Delayed < Departed < Arrived; Cancelled overrides.
- `actual_*` is set only if E5 or E6 happened by N, otherwise `\N`.
- `bookings.total_amount` = Σ E9.amount over the booking. This matches exactly for 262,788 of 262,788 bookings, with a maximum difference of 0 [q2:total_amount_vs_sum].

**Inverse derivation** (tables → log):
- E1 for every flight.
- E2 iff status = Cancelled.
- E3 iff status ∈ {On Time, Delayed, Departed, Arrived}. For Departed and Arrived it is implied, since every one of them had check-in.
- E4 iff status = Delayed. Optionally also for past flights with a departure delay of 2 h or more, but that is not needed for the round trip.
- E5 iff actual_departure ≠ `\N`, and E6 iff actual_arrival ≠ `\N`.
- E7, E8 and E9 at book_date, ordered booking → tickets (by ticket_no) → segments (by scheduled departure).
- E10 per boarding pass, at `sched_dep − W + (boarding_no / n_bp) · w`, capped below N. Here W ≈ 130 min and w ≈ 40 min (§5).

## 3. Rebuild rules and blockers to an exact round trip

1. **Snapshot semantics.** The log must stop at N, and the derived tables are the state at N. Rows straddle N:
   - 65,234 tickets have legs both before and after N [q4:tickets_spanning_now]. Their past legs have boarding passes and their future legs have none.
   - One flight arrived exactly at N (`actual_arrival` = 18:00). The cut is therefore **t ≤ N inclusive** [q5:departed_arrived_vs_now].
2. **Cancelled flights with actuals.** 8 past `Cancelled` flights carry real actual_departure and actual_arrival values, such as flight 27951, 3 h 44 min late [q2:cancelled_with_actuals]. To rebuild them exactly, emit E5 and E6 and then E2. Cancelled must override, or E2 must carry the actuals as attributes. This is a generator artifact, not a valid lifecycle.
3. **Timestamps that are not observable.**
   - E8 and E9 (= book_date) are a modelling choice.
   - E2 has no time.
   - E10 times are synthetic, so only their *order* (boarding_no) is data.
   - The rebuild is exact on the table contents but not on these times.
4. **Identifiers are data, not derivable.**
   - flight_id is grouped by flight_no (§1).
   - ticket_no is not in booking-time order. Only 237,731 of 366,732 consecutive pairs have a non-decreasing book_date, and ticket numbers span 3,998,887 values for 366,733 tickets, so there are gaps [q6:ticket_no_vs_book_date, q6:ticket_no_gaps].
   - book_ref is random hex.
   - passenger_id is a random `#### ######` string [q6:passenger_id_format].
   - All of these must travel as event attributes.
5. **Seat assignment.** seat_no is unique per flight and always in the right class: 579,686 of 579,686 match the class of the ticket_flights row [q2:bp_seat_class_matches_tf_class]. A rebuild copies it. A simulator needs a rule (§5.7).
6. **Formatting.** Write `\N` rather than NULL, the `+03` suffix, minute granularity and integer roubles. The JSON columns must be written back exactly, with `{"en": …, "ru": …}` key order and spacing.
7. **Dropped columns.** passenger_name and contact_data are absent, so they cannot be rebuilt, and none are needed for Spider.

## 4. Measured quirks

- **Null actuals by status** [q1:status_counts]:

  | Status | Flights | With actual_departure | With actual_arrival |
  |---|---|---|---|
  | Arrived | 16,707 | 16,707 | 16,707 |
  | Departed | 58 | 58 | 0 |
  | Scheduled | 15,383 | 0 | 0 |
  | On Time | 518 | 0 | 0 |
  | Delayed | 41 | 0 | 0 |
  | Cancelled | 414 | 8 | 8 |

  - All 58 Departed flights would land after N, based on actual_departure plus the scheduled block time [q5:departed_expected_arrival].
  - 4 Delayed flights had a scheduled departure before N (−2.75 h to −1 h) and still no actual departure [q5:delayed_flights].
- **Cancelled flights have no tickets and no boarding passes**, in the past (8) and in the future (406) [q2:cancelled_by_period]. Either cancellations happen before sales, or the generator deleted their segments with no refund trace.
  - The cancellation rate is **2.48% in the future (406/16,343) but 0.05% in the past (8/16,778)** [q5:cancelled_rate_past_future].
  - This suggests that most past cancellations were rewritten or removed. It is a sim-vs-data asymmetry to reproduce deliberately.
  - By aircraft, the rate is highest for CR2 (2.0%) and 319 (1.9%), and lowest for 321 (0.15%) and 773 (0.16%) [q5:cancelled_rate_by_aircraft_period].
- **No no-shows.** Every ticket_flights row on a departed flight has a boarding pass:

  | Status | Segments with a pass |
  |---|---|
  | Arrived | 574,830 of 574,830 |
  | Departed | 2,275 of 2,275 |
  | On Time | 2,457 of 20,828 |
  | Delayed | 124 of 1,428 |
  | Scheduled | 0 |

  No Arrived flight has a partial set of passes (11,438 of 11,438 are complete) [q2:tf_bp_by_status, q2:arrived_flights_partial_bp]. Tickets without boarding passes occur only on flights that have not departed.
- **No overbooking.** Sold seats ≤ seats per class for every (flight, class); 0 of 34,494 pairs are oversold and the maximum ratio is 1.0 [q2:overbooking]. 164 flights are 100% full, and some classes hit their cap exactly [q6:seats_class_capacity_used_max]. No segment is sold in a class the aircraft lacks [q2:tf_class_not_on_aircraft].
- **Unsold flights.** 10,481 non-cancelled flights have no tickets.
  - 8,339 of them belong to **227 flight_nos that never sell** [q5:unsold_flights_vs_unsold_flightnos, q3:flightnos_without_any_tickets].
  - Unsold flights are concentrated on CN1: 3,328 of 4,674 Arrived CN1 flights have no tickets [q3:no_ticket_flights_by_aircraft_status].
  - Model this as a per-route demand weight of 0 for about 32% of flight_nos.
- **Edge effects in the window** [q5:load_factor_by_week, q3:bookings_per_day]:
  - Bookings ramp up from 3 per day (Jun 21) to about 5,500 per day (from Jul 5). They are flat until about Aug 4, then rise to 6,787 on Aug 14. Aug 15 has 5,335, but only up to 18:00.
  - The load factor of flights with sales by week is 0.27 and 0.35 in the first two weeks, 0.52–0.60 in the middle, and 0.48, 0.25 and 0.10 in the future weeks, which are still on sale.
  - The first weeks are truncated because the booking history starts on Jun 21. Either bookings for itineraries starting before Jul 16 were dropped, or the simulation started around then.
- **Booking structure.** All tickets in a booking share an identical itinerary: 89,398 of 89,398 multi-ticket bookings [q3:same_itinerary_within_booking].
  - The class can differ per passenger and per leg. 198,091 of 254,789 (booking, flight) groups with several tickets have a single class [q6:class_same_across_booking_per_leg].
  - 27.5% of tickets mix classes across legs: 265,917 of 366,733 have a single class [q3:same_class_within_ticket].
- **Fare consistency.** (flight_no, class) determines the fare up to a two-level tier.
  - 320 of 741 groups have a single amount, and the rest have exactly 2 [q2:fare_consistency_flightno_class].
  - The high tier is about 1.10× the low one (1.075–1.119, mean 1.0996) [q4:hi_lo_ratio].
  - The tier applies **per segment**, not per ticket: within affected tickets, 46,066 mix tiers, 306,727 are all low and 3,750 are all high [q5:hi_fare_ticket_level].
  - The high tier is about 5.9% of segments and is flat across lead time (5.1–5.9%), weekday (5.6–6.0%), legs per ticket and class-mixing [q4:hi_fare_vs_lead, q5:hi_fare_by_dow, q3:amount_vs_legs, q4:hi_fare_vs_class_mix_of_ticket]. The trigger is unexplained, so treat it as random.
  - Within a flight both tiers occur: only 3,546 of 19,658 (flight, class) pairs in two-tier groups have a single amount [q4:hi_fare_explainers].
  - The fare per (origin, destination, class) is single-valued for only 293 of 698 groups [q2:fare_per_od_class].

## 5. Distributions to fit later

1. **Booking lead time**, from book_date to the first leg's scheduled departure [q3:lead_time_days_first_leg, q8:lead_moments*]:
   - All bookings: mean 15.75 d, sd 2.74, min 4.53 d (108.6 h), max 28.45 d.
   - Bookings whose first leg is clear of the window edges: mean 15.55 d, sd 2.74, range 4.69–28.45 d.
   - The histogram is unimodal and close to a normal truncated to [4.5, 28.5] d, with modes at 15–16 d. There are **no last-minute bookings**.
   - Booking hour of day is flat, with 10,619–11,268 bookings per hour [q3:book_hour_of_day]. Minutes are uniform and seconds are always 00.
2. **Tickets per booking** [q3:tickets_per_booking]:

   | Tickets | 1 | 2 | 3 | 4 | 5 |
   |---|---|---|---|---|---|
   | Share | 65.98% | 28.84% | 4.83% | 0.34% | 0.01% |

3. **Legs per ticket** [q3:legs_per_ticket, q6:legs_shape_overall, q4:two_leg_shape]:

   | Legs | 1 | 2 | 3 | 4 | 5 | 6 |
   |---|---|---|---|---|---|---|
   | Share | 6.34% | 49.99% | 0.12% | 41.40% | 0.01% | 2.13% |

   - Even-leg tickets are round trips: 100% of 2- and 6-leg tickets and 151,782 of 151,815 4-leg tickets return to the origin.
   - The 2-leg tickets are 177,847 round trips and 5,491 one-way connections.
   - **Return gap** (round trips, from first arrival to return departure): mode 7–8 d, 0–20 d. The day counts are 0:4,749, 3:4,418, 5:17,129, 7:28,949, 8:28,821, 10:17,413, 12:5,606 and 15:404 [q8:return_gap_roundtrip_days].
   - **Connection gap** (< 24 h): bimodal, with 2–8 h (about 129k) and 12–24 h overnight (about 161k). The minimum is 15 min [q8:connection_gap_hours_hist, q4:connection_gaps_all].
4. **Fares** [q2:fare_by_class, q2:fare_ratio_by_class, q2:fare_comfort_ratio, q8:economy_fare_by_flight_hours]:
   - Class mix: Economy 88.05%, Business 10.29%, Comfort 1.65% [q2:class_mix].
   - Economy base ≈ 108–127 roubles per scheduled block minute, rounded to 100. It ranges from 3,000 to 74,500, with a mean of 15,960.
   - **Business = 3.0× Economy** (2.97–3.03, n = 248 flight_nos). **Comfort = 1.70×** (1.694–1.707, n = 10).
   - The high tier is ×1.10 on about 5.9% of segments.
   - Booking total_amount: min 3,400, mean 79,026, max 1,204,500. The bands are < 20k: 27,740; 20–50k: 90,566; 50–100k: 80,008; 100–200k: 46,943; ≥ 200k: 17,531 [q3:total_amount_quantiles, q8:total_amount_hist].
5. **Load factor** (sold ÷ seats; departed or arrived flights with at least one ticket) [q5:load_factor_by_aircraft, q5:load_factor_hist]:
   - By aircraft: 319 0.463 · 321 0.523 · 733 0.616 · 763 0.513 · 773 0.659 · CN1 0.501 · CR2 0.430 · SU9 0.586.
   - The histogram is roughly uniform from 10% to 90%: 679 flights at 0–10%, 1,107–1,342 per decile up to 90%, 948 at 90–99%, and 164 full.
   - Plus 32% of flight_nos with zero demand.
6. **Delays** (departed and arrived flights, n = 16,765) [q5:delay_hist, q5:arr_minus_dep_delay]:
   - **Departure delay is bimodal.** 95.2% are 0–10 min: 0–1 min 2,966; 2–3 min 7,290; 4–5 min 4,453; 6–10 min 1,255. Then 2 at 11 min, none from 12 to 123 min, and **799 (4.8%) at 124–277 min**.
   - **Block time** is the scheduled block ± a few minutes: 95.8% within ±3 min, the rest within ±14 min, with a mean of about 0.
   - **Delayed status share** among flights departing in the next 24 h: 37 of 551 (6.7%) [q5:delayed_share_among_checkin_window]. This matches the 4.8% rate of long delays plus noise.
7. **Check-in and boarding** [q2:per_flight_bp_fraction_near_now, q6:bp_window_fine, q4:boarding_*, q4:seat_rowid_order_vs_boarding]:
   - **Check-in window.** Flights departing up to N + 90 min are 100% checked in. At N + 110 to 115 min, 22–32% are checked in, and 1 of 45 at N + 125 min. Flights at N + 160 min and later have no check-ins.
   - So check-in happens about 2 h 10 min to 1 h 30 min before the scheduled departure, not across the 24 h window the docs suggest. Only 9 flights near N show it, so the window is uncertain.
   - boarding_no runs 1..n with no gaps on all 11,518 flights.
   - **boarding_no follows the seat map, not the booking**:
     - The mean relative boarding_no is 0.08 for Business, 0.14 for Comfort and 0.57 for Economy.
     - In 85.3% of consecutive same-class pairs the seat moves later in the `seats` order (478,047 of 560,193).
     - Relative to ticket_no the order is random (50.1% increasing); relative to book_date it is 49.4%.
     - Adjacent boarding numbers from the same booking occur only 1.25% of the time (7,131 of 568,168).
   - Generator reading: seats are assigned roughly front to back with jitter, and boarding_no is (nearly) the seat order. Sim rule: at each check-in, take a random free seat from the first k free seats of the class, and number the boarding passes in check-in order.

## 6. simkit mapping sketch

- **Static entities (Source).**
  - `aircraft`, `airports` and `seats`: `src.insert` from embedded tuples. The airports are only 104 rows; for a synthetic network, generate them.
  - `src.share("timetable", …)` holds the 710 flight_nos: origin, destination, aircraft, departure minute, block minutes, weekday mask, base Economy fare and demand weight.
- **Flight owner: shard `flight`, one per flight, with key flight_id.**
  - State: `reservations.Stock` with units keyed by class (Business, Comfort, Economy → seat counts), the boarding counter and the free-seat list per class.
  - `reservations.install(p, flight, item="fare_class", ttl=600)` is directly analogous to the ecommerce SKU groups.
  - **Status machine** on `flight`:
    - `scheduled` (on_enter emits E1; branch `cancelled` p = cfg.cancel_p, delay 0).
    - → timer at (sched_dep − 24 h − now) → `checkin_open`. The branch here gives `delayed` with p ≈ 0.048 (delay lognormal 2–4.6 h), otherwise `on_time` (delay 0–10 min).
    - → timer to the actual departure → `departed` → timer for the block ± noise → `arrived` (retire).
    - `cancelled` should arrive before the first sale, or decline future reserves with `out_of_stock`.
  - The flights themselves come from a Source that walks the timetable per day and calls `src.create("flight", at=sched_dep−30d, key=…)`.
- **Booking process: owner `booking`.**
  - A Source arrival process creates them: the rate is about 5,500 per day for the full size, at a uniform minute of day, with no ramp.
  - On start, draw:
    - n_pax from §5.2;
    - the itinerary type from §5.3: one-way, round trip, or round trip with a connection;
    - the destination by route demand weight;
    - the first departure = now + lead ~ N(15.6 d, 2.7 d) truncated to [4.5, 28.5];
    - the return gap from §5.3;
    - the class per passenger per leg.
  - Then `ctx.request(flight_pid, "reserve", item=class, qty=k)` for each (leg, class) group, join on the replies, and commit all or release all.
  - On commit, emit E7, E8 × n_pax and E9 × legs × pax with the fare rule (base × class multiplier × 1.1 with p 0.059).
  - All rejected reserves mean the booking fails. The data has no visible trace of failed bookings, so log `reservation_declined` only.
  - For each ticket leg, `ctx.at(sched_dep − U(90, 130) min, "check_in")` sends to the flight shard. The shard assigns boarding_no++ and a seat (§5.7) and emits E10. Skip the check-in if the flight is cancelled.
- **Checks.**
  - `reservations_resolved`.
  - Seats never negative: `running_nonneg` per (flight, class).
  - `unique(passenger_checked_in, [flight_id, seat_no])` and `[flight_id, boarding_no]`.
  - `consecutive(passenger_checked_in, flight_id, boarding_no)`.
  - lifecycle `flight_scheduled → checkin_opened → flight_departed → flight_arrived`, and `cancelled` only from scheduled. The data's 8 anomalies would be an overlay or `required=False`.
  - Booking total = Σ segments, as a custom law.
- **Overlays.** Natural risk overlays here are seat-spinning or inventory hoarding (a cohort holding seats until the TTL expires), duplicate passenger IDs, or fare manipulation. They share flight inventory, so the regression rule's "after first contact" applies.
- **Volume.**
  - The real tables hold about 2.34M rows: 33k flights × about 3 status events, plus 263k bookings, 367k tickets, 1.046M segments and 580k boarding passes.
  - In simkit, add reservations: 806,535 (booking, flight, class) groups [q9:reservation_groups], each with a grant and a commit.
  - **Total ≈ 4.0–4.5M events, about 15–18 s.**
  - Suggested **`sample` profile at 1/10 demand on a closed sub-network**: keep about 70 flight_nos among the top hub airports, with seats unchanged so the load factor is preserved. That gives about 3.3k flights, 26k bookings, 105k segments, 58k passes and ≈ 400k events, in about 2 s. In the real data only 28% of tickets stay entirely within the top-15 airports [q9:closed_tickets_in_top15], so the sub-network is a re-sampling of demand, not a filter of real rows.
  - The run needs about 61 days: 30 days of selling before the first departure, and 30 days past N, so that the snapshot projection exists.

## 7. Open questions and risks

- **Licence.**
  - The 2025 release page says "distributed under the MIT license".
  - The 2017 docs page states no licence; its footer has a Postgres Pro EULA link.
  - Spider 2.0 redistributes the data, and its repository is MIT. Fitting statistics is low-risk, but confirm before redistributing the rows.
- **Check-in window (§5.7).** It is inferred from only 9 flights near N. The docs' 24 h figure contradicts the data.
- **Cancellations.** The asymmetry between past (0.05%) and future (2.5%), and the 8 cancelled-but-flown flights, are probably generator post-processing. Decide whether to reproduce them.
- **Unexplained fares and network.** The 1.1× fare tier and the 227 never-sold flight_nos have no observable driver.
- **Edge-effect truncation.** It is unclear whether bookings were dropped or the simulation started on Jun 21. Ignore the first and last 2 weeks when fitting the load factor.
- **No repeat customers.** passenger_id is unique per ticket, and names are dropped, so there is no customer entity. An owner per booking, not per person, is faithful.
- **Spider usage.** There are 2 tasks: `local009` (longest Abakan route) and `local010` (city-pair distance buckets). Both use only static and timetable data: airports' coordinates and city JSON, and flights' origin and destination. The external knowledge is `haversine_formula.md` (r = 6371 km, lexicographic city pair, average distance per pair).
  - **local009** reproduced the gold value 3484.1504600096 exactly [q6:haversine_check_local009].
  - **local010** gives buckets 0:92, 1000:93, 2000:37, 3000:20, 4000:6, 5000:3, 6000+:7, so the fewest is 3 pairs, but the gold CSV says `6256` [q7:local010_*]. The gold looks unreliable or uses a different reading.
  - No gold SQL was found under `evaluation_suite/gold/sql` for these ids. Only `exec_result/local009_a.csv` and `local010.csv` exist.
  - Validation checks for a synthetic pack: the timetable must give 618 ordered airport pairs and 710 flight_nos, the haversine maximum through Abakan must be 3484.15 km, and the bucket counts above must hold if the real airports and timetable are reused.
