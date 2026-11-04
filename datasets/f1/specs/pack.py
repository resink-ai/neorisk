"""F1: the Ergast Formula 1 database, 1950 to mid-2024. Races are scheduled; drivers qualify,
complete laps, stop in the pit lane and are classified; constructors and drivers are scored
and the championship standings are published after each race. Stage 1, schema only: the
events are ingested from the Spider2 tables (docs/research/spider2/f1.md); stage 2 adds the
behavior.

Spider2's 11 derived tables (`*_ext`, `lap_time_stats`, `team_driver_ranks`, `drives`,
`retirements`, `lap_positions`) are rebuilt in build.sql and carry no events. The three
generated columns (`drivers.full_name`, `lap_times.seconds`, `pit_stops.seconds`) are computed
by SQLite. `race_id` is a plain id in every event: races are the `race_scheduled` event, not
an entity.
"""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, f64, i64, opt, ref, text

SCHEMA_VERSION = 1


@dataclass
class Config:
    pass


def _classified(rank: bool) -> dict:
    """The columns of a race or sprint classification (results / sprint_results)."""
    cols = {"driver_id": ref("drivers"), "result_id": i64(), "race_id": i64(),
            "constructor_id": ref("constructors"), "number": opt(i64()), "grid": i64(),
            "position": opt(i64()), "position_text": text(), "position_order": i64(),
            "points": f64(), "laps": i64(),
            "time": opt(text(doc="Verbatim: not a function of milliseconds")),
            "milliseconds": opt(i64()), "fastest_lap": opt(i64())}
    if rank:
        cols["rank"] = opt(i64(doc="0 for 250 rows with no fastest lap; NULL elsewhere"))
    cols |= {"fastest_lap_time": opt(text()),
             "fastest_lap_speed": opt(text(doc="Verbatim, trailing zeros kept")),
             "status_id": ref("status")}
    return cols


def _standing(owner: str, key: str) -> dict:
    return {owner: ref(owner.removesuffix("_id") + "s"), key: i64(), "race_id": i64(),
            "points": f64(), "position": opt(i64()), "position_text": opt(text()),
            "wins": i64()}


def define(p: Pack) -> None:
    p.entity("circuits", key="circuit_id",
             cols={"ext_id": text(doc="Ergast circuitId"), "circuit_ref": text(), "name": text(),
                   "location": opt(text()), "country": opt(text()), "lat": opt(f64()),
                   "lng": opt(f64()), "alt": opt(i64()), "url": text()})
    p.entity("constructors", key="constructor_id",
             cols={"ext_id": text(doc="Ergast constructorId"), "constructor_ref": text(),
                   "name": text(), "nationality": opt(text()), "url": text()})
    p.entity("drivers", key="driver_id", doc="number and code are today's (snapshot values)",
             cols={"ext_id": text(doc="Ergast driverId"), "driver_ref": text(),
                   "number": opt(i64()), "code": opt(text()), "forename": text(),
                   "surname": text(), "dob": opt(text(doc="YYYY-MM-DD")),
                   "nationality": opt(text()), "url": text()})
    p.entity("seasons", key="season_id",
             cols={"ext_id": text(doc="The year"), "url": text()})
    p.entity("status", key="status_id", cols={"ext_id": text(), "status": text()})
    p.entity("short_grand_prix_names", key="short_grand_prix_name_id", doc="Editorial lookup",
             cols={"ext_id": text(doc="The full Grand Prix name"), "short_name": text()})
    p.entity("short_constructor_names", key="short_constructor_name_id",
             doc="Editorial lookup",
             cols={"ext_id": text(doc="The constructor_ref"), "short_name": text()})
    p.entity("liveries", key="livery_id", doc="3 rows name 'benneton', no constructor",
             cols={"ext_id": text(doc="'<constructor_ref>/<start_year>'"),
                   "constructor_ref": text(), "start_year": i64(),
                   "end_year": opt(i64(doc="NULL while the livery is current")),
                   "primary_hex_code": text()})
    p.entity("tdr_overrides", key="tdr_override_id",
             doc="Hand judgements of a driver's rank in a team-season",
             cols={"ext_id": text(doc="'<year>/<constructor_ref>/<driver_ref>'"), "year": i64(),
                   "constructor_ref": text(), "driver_ref": text(),
                   "team_driver_rank": i64()})
    p.event("race_scheduled", doc="At Jan 1 of the season (rule)",
            cols={"circuit_id": ref("circuits"), "race_id": i64(), "year": i64(),
                  "round": i64(), "name": text(), "date": text(doc="YYYY-MM-DD"),
                  "time": opt(text(doc="UTC start HH:MM:SS; NULL before 2005")),
                  "url": opt(text()),
                  **{f"{s}_{k}": opt(text()) for s in ("fp1", "fp2", "fp3", "quali", "sprint")
                     for k in ("date", "time")}})
    p.event("qualifying_classified",
            doc="At the session (2021+), else the day before the race at 12:00 (rule)",
            cols={"driver_id": ref("drivers"), "qualify_id": i64(), "race_id": i64(),
                  "constructor_id": ref("constructors"), "number": i64(),
                  "position": opt(i64()), "q1": opt(text()),
                  "q2": opt(text(doc="'' and NULL differ")),
                  "q3": opt(text(doc="'' and NULL differ"))})
    p.event("sprint_classified", doc="At the sprint session, 12:00 when it has no time",
            cols=_classified(rank=False))
    p.event("lap_completed", doc="At race start + the running lap milliseconds",
            cols={"driver_id": ref("drivers"), "race_id": i64(), "lap": i64(),
                  "position": opt(i64()), "milliseconds": i64()})
    p.event("pit_stop_made", doc="At the in-lap's lap_completed time (rule)",
            cols={"driver_id": ref("drivers"), "race_id": i64(), "stop": i64(), "lap": i64(),
                  "time": text(doc="Local wall clock HH:MM:SS, verbatim"),
                  "milliseconds": i64()})
    p.event("race_result_classified", doc="At race day + 1, 00:00 (rule)",
            cols=_classified(rank=True))
    p.event("constructor_race_points_reported", doc="With the classification",
            cols={"constructor_id": ref("constructors"), "constructor_results_id": i64(),
                  "race_id": i64(), "points": f64(),
                  "status": opt(text(doc="'D' for 17 excluded rows"))})
    p.event("driver_standings_published", doc="Official: drop scores, penalties",
            cols=_standing("driver_id", "driver_standings_id"))
    p.event("constructor_standings_published", doc="Official: best-car rule, exclusions",
            cols=_standing("constructor_id", "constructor_standings_id"))
    p.event("drive_override_recorded",
            doc="At N: the source's drives rows for the 17 driver-seasons (shared 1950s cars) "
                "that the run-length rule does not give",
            cols={"driver_id": ref("drivers"), "year": i64(),
                  "drive_id": i64(doc="-1 on a gap row"),
                  "constructor_id": i64(doc="Source constructor id; -1 on a gap row"),
                  "first_round": i64(), "last_round": i64(),
                  "is_first_drive_of_season": i64(), "is_final_drive_of_season": i64()})
