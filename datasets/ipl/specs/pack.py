"""IPL: the Indian Premier League, seasons 1-9 (2008-2016), ball by ball. A match is
scheduled, the toss is decided and the team sheets are named; then each innings starts and
every delivery is bowled; then the result is recorded. Stage 1, schema only: the events are
ingested from the Spider2 tables (docs/research/spider2/ipl.md); stage 2 adds the behavior.

The source has dates only, so every time of day is a rule. Team 1 and player 35 are used
thousands of times but have no row: they are placeholder entities with `listed = 0`. Match
419136 has balls and a team sheet but no match row, so it has no scheduling, toss or result.
A delivery's optional parts are NULL when the source table has no row for it. A player's
bowling skill and country ride on one snapshot per listed player at N, the last result.
"""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, cat, i32, i64, opt, ref, text

SCHEMA_VERSION = 1

EXTRAS = ("wides", "legbyes", "noballs", "byes", "penalty")
KINDS_OUT = ("caught", "bowled", "run out", "lbw", "retired hurt", "stumped",
             "caught and bowled", "hit wicket", "obstructing the field")


@dataclass
class Config:
    pass


def define(p: Pack) -> None:
    listed = {"listed": i32(doc="1 for a source row, 0 for a placeholder of a missing id")}
    p.entity("teams", key="team_key", doc="Team 1 (Kolkata, by its venues) is a placeholder",
             cols={"ext_id": text(doc="team_id"), "name": opt(text()), **listed})
    p.entity("players", key="player_key", doc="Player 35 is a placeholder",
             cols={"ext_id": text(doc="player_id"), "player_name": opt(text()),
                   "dob": opt(text(doc="YYYY-MM-DD, verbatim")),
                   "batting_hand": opt(cat("Left-hand bat", "Right-hand bat")), **listed})
    p.event("players_snapshot", doc="State at N = 2016-05-29 23:17: bowling skill and country",
            cols={"player_key": ref("players"), "bowling_skill": opt(text()),
                  "country_name": opt(text())})
    p.event("match_scheduled", doc="Its date is the match_date",
            cols={"match_id": i64(), "team_1": ref("teams"), "team_2": ref("teams"),
                  "season_id": i32(), "venue": text()})
    p.event("toss_decided",
            cols={"match_id": i64(), "toss_winner": ref("teams"),
                  "toss_decision": cat("bat", "field")})
    p.event("player_named", doc="One team-sheet line",
            cols={"match_id": i64(), "player_id": ref("players"), "team_id": ref("teams"),
                  "role": cat("Player", "Captain", "Keeper", "CaptainKeeper")})
    p.event("innings_started", doc="The batting side is the strikers' team",
            cols={"match_id": i64(), "innings_no": i32(), "team_batting": ref("teams"),
                  "team_bowling": ref("teams")})
    p.event("ball_bowled", doc="One delivery: the union of the four ball tables' keys",
            cols={"match_id": i64(), "innings_no": i32(), "over_id": i32(), "ball_id": i32(),
                  "has_ball_row": i32(doc="1 when ball_by_ball has the row"),
                  "teams_swapped": i32(doc="1 when the source labels the sides the wrong way"),
                  "striker": opt(ref("players")), "non_striker": opt(ref("players")),
                  "bowler": opt(ref("players")), "striker_batting_position": opt(i32()),
                  "runs_scored": opt(i32(doc="NULL: no batsman_scored row")),
                  "extra_type": opt(cat(*EXTRAS, doc="NULL: no extra_runs row")),
                  "extra_runs": opt(i32()),
                  "player_out": opt(ref("players")),
                  "kind_out": opt(cat(*KINDS_OUT, doc="NULL: no wicket_taken row"))})
    p.event("match_completed", doc="Carried: 22 results disagree with the scorecard",
            cols={"match_id": i64(), "match_winner": ref("teams"),
                  "win_type": cat("runs", "wickets"), "win_margin": i32(),
                  "outcome_type": cat("Result"), "man_of_the_match": ref("players")})
