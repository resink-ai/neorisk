"""European Soccer Database (Kaggle, Hugo Mathien 2016): 11 top-flight leagues over 8 seasons
(2008/09 to 2015/16). Each match is played in a league, with lineups, enetscores XML incidents
and bookmaker odds; players and teams get dated EA FIFA rating snapshots. Stage 1, schema
only: the events are ingested from the Spider2 tables (docs/research/spider2/eusoccer.md);
stage 2 adds the behavior.

The source has dates only. Masters are created by rule: countries and leagues at their first
match, teams at min(first match, first rating), players at their first rating. Height and
weight ride on a snapshot at N = 2016-07-07, the last rating date.
"""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, cat, f64, i64, opt, ref, text

SCHEMA_VERSION = 1

SIDES = ("home", "away")
XML = ("goal", "shoton", "shotoff", "foulcommit", "card", "cross", "corner", "possession")
BOOKMAKERS = ("B365", "BW", "IW", "LB", "PS", "WH", "SJ", "VC", "GB", "BS")
SKILLS = ("overall_rating", "potential", "crossing", "finishing", "heading_accuracy",
          "short_passing", "volleys", "dribbling", "curve", "free_kick_accuracy",
          "long_passing", "ball_control", "acceleration", "sprint_speed", "agility",
          "reactions", "balance", "shot_power", "jumping", "stamina", "strength", "long_shots",
          "aggression", "interceptions", "positioning", "vision", "penalties", "marking",
          "standing_tackle", "sliding_tackle", "gk_diving", "gk_handling", "gk_kicking",
          "gk_positioning", "gk_reflexes")


@dataclass
class Config:
    pass


def define(p: Pack) -> None:
    p.entity("countries", key="country_id", doc="Created at the country's first match",
             cols={"ext_id": text(doc="Country.id (= the id of its first Match)"),
                   "name": text()})
    p.entity("leagues", key="league_id", doc="Created at the league's first match",
             cols={"ext_id": text(doc="League.id (= its country's id)"),
                   "country_id": ref("countries"), "name": text()})
    p.entity("teams", key="team_id", doc="Created at min(first match, first team rating)",
             cols={"ext_id": text(doc="team_api_id"), "team_row_id": i64(doc="Team.id, sparse"),
                   "team_fifa_api_id": opt(i64(doc="NULL for the 11 teams never rated")),
                   "team_long_name": text(), "team_short_name": text()})
    p.entity("players", key="player_id", doc="Created at the first player rating",
             cols={"ext_id": text(doc="player_api_id"),
                   "player_row_id": i64(doc="Player.id, 15 gaps"), "player_name": text(),
                   "player_fifa_api_id": i64(),
                   "birthday": text(doc="'YYYY-MM-DD 00:00:00' verbatim")})
    p.event("players_snapshot", doc="sofifa's 2016 height and weight, at N = 2016-07-07",
            cols={"player_id": ref("players"),
                  "height": f64(doc="cm on an inch grid, verbatim"),
                  "weight": i64(doc="lb")})
    lineup = {f"{s}_player_{i}": opt(ref("players")) for s in SIDES for i in range(1, 12)}
    coords = {f"{s}_player_{a}{i}": opt(i64()) for s in SIDES for a in "XY"
              for i in range(1, 12)}
    xml = {c: opt(text(doc="enetscores XML, verbatim")) for c in XML}
    odds = {f"{b}{r}": opt(f64(doc="decimal odds")) for b in BOOKMAKERS for r in "HDA"}
    p.event("match_played", doc="One match, on its date; country_id derives from the league",
            cols={"league_id": ref("leagues"), "match_id": i64(doc="Match.id"),
                  "match_api_id": i64(), "season": text(), "stage": i64(),
                  "home_team_id": ref("teams"), "away_team_id": ref("teams"),
                  "home_team_goal": i64(), "away_team_goal": i64(),
                  **coords, **lineup, **xml, **odds})
    p.event("player_rated", doc="A FIFA rating snapshot; 836 are all-NULL twins",
            cols={"player_id": ref("players"), "attr_id": i64(doc="Player_Attributes.id"),
                  "player_fifa_api_id": i64(doc="Verbatim; 212 rows differ from the player's"),
                  "preferred_foot": opt(text()),
                  "attacking_work_rate": opt(text(doc="Scraper-damaged; verbatim")),
                  "defensive_work_rate": opt(text(doc="Scraper-damaged; verbatim")),
                  **{c: opt(i64()) for c in SKILLS}})
    p.event("team_rated", doc="A FIFA tactics snapshot; the 9 numeric classes derive (33/66)",
            cols={"team_id": ref("teams"), "attr_id": i64(doc="Team_Attributes.id"),
                  "buildUpPlaySpeed": i64(),
                  "buildUpPlayDribbling": opt(i64(doc="NULL before 2014-09-19")),
                  "buildUpPlayPassing": i64(), "chanceCreationPassing": i64(),
                  "chanceCreationCrossing": i64(), "chanceCreationShooting": i64(),
                  "defencePressure": i64(), "defenceAggression": i64(),
                  "defenceTeamWidth": i64(),
                  "buildUpPlayPositioningClass": cat("Free Form", "Organised"),
                  "chanceCreationPositioningClass": cat("Free Form", "Organised"),
                  "defenceDefenderLineClass": cat("Cover", "Offside Trap")})
