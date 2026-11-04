"""Baseball: Sean Lahman's Baseball Database, 2015 edition (seasons 1871-2015, Hall of Fame
ballots to 2016). Every fact table is a season, stint or postseason-round aggregate; no game
or play grain exists. Stage 1, schema only: the events are ingested from the Spider2 tables
(docs/research/spider2/baseball.md); stage 2 adds the behavior.

No source cell is NULL: '' is the only missing marker. A numeric column holding '' next to
integers travels as a null integer and is rebuilt as SQLite's text ('' or the digits). The 4
holding reals (pitching.baopp and era, pitching_postseason.era, player_award_vote.votes_first)
travel as SQLite's own CAST AS TEXT, which also hides baopp's 17-digit float noise.

Times are rules except debuts, home-game spans and all-star game dates: S(y) = <y>-11-01 for
the regular season, P(y) = <y>-11-02 for the postseason, A(y) = <y>-11-30 for awards,
H(y) = <y>-01-15 for Hall of Fame ballots; T0 = 1871-01-01 and N = 2016-02-18.
"""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, amount, cat, f64, i64, opt, ref, text

SCHEMA_VERSION = 1


@dataclass
class Config:
    pass


def _i(names: str) -> dict:
    return {n: i64() for n in names.split()}


def _n(names: str) -> dict:
    """A numeric column with '' for missing: null here, '' again in the rebuild."""
    return {n: opt(i64()) for n in names.split()}


def _t(names: str) -> dict:
    return {n: text() for n in names.split()}


def _ot(names: str) -> dict:
    """Text that is null only on a stub entity."""
    return {n: opt(text()) for n in names.split()}


def _f(names: str) -> dict:
    return {n: f64() for n in names.split()}


def _c(names: str) -> dict:
    """Reals next to '': SQLite's CAST AS TEXT ('0.246', '', 'inf'), verbatim."""
    return {n: text(doc="SQLite's CAST AS TEXT") for n in names.split()}


def define(p: Pack) -> None:
    team = ref("team_franchise", doc="Owner: the franchise of team (year, team_id)")
    p.entity("player", key="player_key",
             doc="A person (player, manager, executive); 12 stubs are ids used only in fact "
                 "rows. created_at: min(debut, first owned event), else T0",
             cols={"ext_id": text(doc="player_id, verbatim"),
                   "stub": cat("0", "1", doc="1: an orphan id, not in player"),
                   **_n("birth_year birth_month birth_day"),
                   **_ot("birth_country birth_state birth_city name_first name_last name_given"),
                   **_n("weight height"), **_ot("bats throws"),
                   "debut": opt(text(doc="YYYY-MM-DD or ''; later than created_at for 49")),
                   **_ot("retro_id bbref_id")})
    p.entity("team_franchise", key="franchise_key",
             doc="created_at: Jan 1 of its first team-season (rule)",
             cols={"ext_id": text(doc="franchise_id"),
                   **_t("franchise_name"), "active": text(doc="Y, N or '': its state at N"),
                   **_t("na_assoc")})
    p.entity("park", key="park_key", doc="created_at: its first home game, else T0",
             cols={"ext_id": text(doc="park_id"),
                   **_t("park_name park_alias city state country")})
    p.entity("college", key="college_key", doc="All at T0 (rule)",
             cols={"ext_id": text(doc="college_id"),
                   "stub": cat("0", "1", doc="1: an unknown id in player_college"),
                   **_ot("name_full city state country")})
    p.entity("season", key="season_key", doc="An owner shard only; no results table",
             cols={"ext_id": text(doc="The year")})

    p.event("team_season_reported", doc="One team-season's record, at S(year)",
            cols={**_i("year"), **_t("league_id team_id"), "franchise_id": ref("team_franchise"),
                  **_t("div_id"), **_i("rank g"), **_n("ghome"), **_i("w l"),
                  **_t("div_win wc_win lg_win ws_win"), **_i("r ab h double triple hr bb"),
                  **_n("so sb cs hbp sf"), **_i("ra er"),
                  "era": f64(doc="= round(27 er / ipouts, 2) on every row; carried"),
                  **_i("cg sho sv ipouts ha hra bba soa e"), **_n("dp"), **_f("fp"),
                  **_t("name park"), **_n("attendance"), **_i("bpf ppf"),
                  **_t("team_id_br team_id_lahman45 team_id_retro")})
    p.event("team_half_reported", doc="A 1981 split-season half, at S(year)",
            cols={"franchise": team, **_i("year"), **_t("league_id team_id"), **_i("half"),
                  **_t("div_id div_win"), **_i("rank g w l")})
    p.event("manager_stint_reported", doc="One manager stint, at S(year)",
            cols={"player_id": ref("player"), **_i("year"), **_t("team_id league_id"),
                  **_i("inseason g w l"), **_n("rank"), **_t("plyr_mgr")})
    p.event("manager_half_reported", doc="A manager's split-season half, at S(year)",
            cols={"player_id": ref("player"), **_i("year"), **_t("team_id league_id"),
                  **_i("inseason half g w l rank")})
    p.event("appearances_reported", doc="Games by position for a player-team-season, at S(year)",
            cols={**_i("year"), **_t("team_id league_id"), "player_id": ref("player"),
                  **_n("g_all gs"), **_i("g_batting"), **_n("g_defense"),
                  **_i("g_p g_c g_1b g_2b g_3b g_ss g_lf g_cf g_rf g_of"),
                  **_n("g_dh g_ph g_pr")})
    p.event("batting_line_reported", doc="One season-stint batting line, at S(year)",
            cols={"player_id": ref("player"), **_i("year stint"), **_t("team_id league_id"),
                  **_i("g"), **_n("ab r h double triple hr rbi sb cs bb so ibb hbp sh sf g_idp")})
    p.event("pitching_line_reported", doc="One season-stint pitching line, at S(year)",
            cols={"player_id": ref("player"), **_i("year stint"), **_t("team_id league_id"),
                  **_i("w l g gs cg sho sv"), **_n("ipouts"), **_i("h er hr bb so"),
                  **_c("baopp era"), **_n("ibb wp hbp"), **_i("bk"), **_n("bfp gf"), **_i("r"),
                  **_n("sh sf g_idp")})
    p.event("fielding_line_reported", doc="One season-stint-position fielding line, at S(year)",
            cols={"player_id": ref("player"), **_i("year stint"), **_t("team_id league_id pos"),
                  **_i("g"), **_n("gs inn_outs po a e dp pb wp sb cs zr")})
    p.event("outfield_split_reported", doc="LF/CF/RF games of a season-stint (1871-1955), "
                                           "at S(year)",
            cols={"player_id": ref("player"), **_i("year stint"), **_n("glf gcf grf")})
    p.event("salary_reported", doc="A season salary (1985-2015), at S(year)",
            cols={**_i("year"), **_t("team_id league_id"), "player_id": ref("player"),
                  "salary": amount("USD", doc="Whole dollars, as cents")})
    p.event("home_games_reported", doc="A team-season's home games at one park, at span_last "
                                       "(natural)",
            cols={"franchise": team, **_i("year"), **_t("league_id team_id"),
                  "park_id": ref("park"), **_t("span_first span_last"),
                  **_i("games openings attendance")})
    p.event("all_star_selected", doc="A selection to an all-star game, at the game date in "
                                     "game_id (natural); 1945, with no game, at 1945-07-10",
            cols={"player_id": ref("player"), **_i("year game_num"),
                  **_t("game_id team_id league_id"), **_n("gp starting_pos")})
    p.event("postseason_series_decided", doc="A postseason series result, at P(year)",
            cols={"season": ref("season", doc="Owner"), **_i("year"),
                  **_t("round team_id_winner league_id_winner team_id_loser league_id_loser"),
                  **_i("wins losses ties")})
    p.event("batting_postseason_reported", doc="A postseason-round batting line, at P(year)",
            cols={**_i("year"), **_t("round"), "player_id": ref("player"),
                  **_t("team_id league_id"), **_i("g ab r h double triple hr rbi sb"),
                  **_n("cs"), **_i("bb so"), **_n("ibb hbp sh sf g_idp")})
    p.event("pitching_postseason_reported", doc="A postseason-round pitching line, at P(year)",
            cols={"player_id": ref("player"), **_i("year"), **_t("round team_id league_id"),
                  **_i("w l g gs cg sho sv ipouts h er hr bb so"),
                  "baopp": text(doc="A TEXT column: '0.x', '0'..'31', '-', '', verbatim"),
                  **_c("era"), **_n("ibb wp hbp bk bfp"), **_i("gf r"), **_n("sh sf g_idp")})
    p.event("fielding_postseason_reported", doc="A postseason-round fielding line, at P(year)",
            cols={"player_id": ref("player"), **_i("year"), **_t("team_id league_id round pos"),
                  **_i("g"), **_n("gs inn_outs"), **_i("po a e dp tp"), **_n("pb sb cs")})
    p.event("player_award_won", doc="A player award, at A(year)",
            cols={"player_id": ref("player"), **_t("award_id"), **_i("year"),
                  **_t("league_id tie notes")})
    p.event("player_award_vote_received", doc="A player's award vote share, at A(year)",
            cols={**_t("award_id"), **_i("year"), **_t("league_id"), "player_id": ref("player"),
                  "points_won": f64(doc="Halves on 6 split votes"), **_i("points_max"),
                  **_c("votes_first")})
    p.event("manager_award_won", doc="A manager award, at A(year)",
            cols={"player_id": ref("player"), **_t("award_id"), **_i("year"),
                  **_t("league_id tie"), "notes": text(doc="'' on every row")})
    p.event("manager_award_vote_received", doc="A manager's award vote share, at A(year)",
            cols={**_t("award_id"), **_i("year"), **_t("league_id"), "player_id": ref("player"),
                  **_i("points_won points_max votes_first")})
    p.event("hof_ballot_recorded", doc="A Hall of Fame ballot result, at H(yearid)",
            cols={"player_id": ref("player"), **_i("yearid"), **_t("votedby"),
                  **_n("ballots needed votes"), **_t("inducted category needed_note")})
    p.event("college_attended", doc="A college year, at the player's creation (rule)",
            cols={"player_id": ref("player"), "college_id": ref("college"), **_i("year")})
    p.event("player_snapshot_taken", doc="Lifetime values, at N = 2016-02-18",
            cols={"player_id": ref("player"), **_t("final_game"),
                  **_n("death_year death_month death_day"),
                  **_t("death_country death_state death_city")})
