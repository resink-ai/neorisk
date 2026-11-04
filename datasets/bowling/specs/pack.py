"""bowling: the Bowling League of *SQL Queries for Mere Mortals* (Viescas and Hernandez).
Eight teams of four bowl a double round robin over 14 weekly tournaments: 3 games a match.
Stage 1, schema only: the events are ingested from the Spider2 tables
(docs/research/spider2/bowling.md); stage 2 adds the behavior.
"""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, i64, opt, ref, text

SCHEMA_VERSION = 1


@dataclass
class Config:
    pass


def define(p: Pack) -> None:
    p.entity("teams", key="team_id", doc="Created at T0, the first tournament date (a rule)",
             cols={"ext_id": text(), "team_name": text(), "captain_id": ref("bowlers")})
    p.entity("bowlers", key="bowler_id", doc="Created at T0; the 4 stats columns are derived",
             cols={"ext_id": text(), "last_name": text(), "first_name": text(),
                   "middle_init": opt(text()), "address": text(), "city": text(),
                   "state": text(), "zip": text(), "phone": text(), "team_id": ref("teams")})
    p.entity("tournaments", key="tourney_id", doc="Scheduled, created at T0; 6 never held",
             cols={"ext_id": text(), "tourney_date": text(doc="'YYYY-MM-DD'"),
                   "tourney_location": text()})
    p.entity("wazips", key="zip_id", doc="Washington ZIP codes, a static lookup at T0",
             cols={"ext_id": text(doc="the ZIP"), "city": text(), "state": text()})
    p.event("match_scheduled", doc="At its tournament's date (a rule: no own time)",
            cols={"tourney_id": ref("tournaments"), "match_id": i64(), "lanes": text(),
                  "odd_lane_team_id": ref("teams"), "even_lane_team_id": ref("teams")})
    p.event("game_bowled", doc="One bowler's game, at its tournament's date (a rule)",
            cols={"bowler_id": ref("bowlers"), "match_id": i64(), "game_number": i64(min=1),
                  "raw_score": i64(), "handicap_score": i64(), "won_game": i64()})
