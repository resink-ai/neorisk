-- Baseball (Lahman 2015): events → source tables (refdata rebuild, DuckDB).
-- A null integer of a mixed column goes back as ''; text and reals verbatim.

-- table: player
SELECT p.ext_id AS player_id, coalesce(CAST(p."birth_year" AS VARCHAR), '') AS "birth_year",
       coalesce(CAST(p."birth_month" AS VARCHAR), '') AS "birth_month",
       coalesce(CAST(p."birth_day" AS VARCHAR), '') AS "birth_day", p."birth_country",
       p."birth_state", p."birth_city",
       coalesce(CAST(s."death_year" AS VARCHAR), '') AS "death_year",
       coalesce(CAST(s."death_month" AS VARCHAR), '') AS "death_month",
       coalesce(CAST(s."death_day" AS VARCHAR), '') AS "death_day", s."death_country",
       s."death_state", s."death_city", p."name_first", p."name_last", p."name_given",
       coalesce(CAST(s."weight" AS VARCHAR), '') AS "weight",
       coalesce(CAST(s."height" AS VARCHAR), '') AS "height", s."bats", p."throws", p."debut",
       s."final_game", p."retro_id", p."bbref_id"
FROM player p LEFT JOIN player_snapshot s ON s.player_id = p.player_key
WHERE p.stub = '0';

-- table: team_franchise
SELECT f.ext_id AS franchise_id, s.franchise_name, s.active, f.na_assoc
FROM team_franchise f LEFT JOIN team_franchise_snapshot s ON s.franchise_id = f.franchise_key;

-- table: park
SELECT p.ext_id AS park_id, s.park_name, s.park_alias, p.city, p.state, p.country
FROM park p LEFT JOIN park_snapshot s ON s.park_id = p.park_key;

-- table: college
SELECT c.ext_id AS college_id, s.name_full, c.city, c.state, c.country
FROM college c LEFT JOIN college_snapshot s ON s.college_id = c.college_key WHERE c.stub = '0';

-- table: team
SELECT e."year", e."league_id", e."team_id", f.ext_id AS franchise_id, e."div_id", e."rank", e."g",
       coalesce(CAST(e."ghome" AS VARCHAR), '') AS "ghome", e."w", e."l", e."div_win", e."wc_win",
       e."lg_win", e."ws_win", e."r", e."ab", e."h", e."double", e."triple", e."hr", e."bb",
       coalesce(CAST(e."so" AS VARCHAR), '') AS "so", coalesce(CAST(e."sb" AS VARCHAR), '') AS "sb",
       coalesce(CAST(e."cs" AS VARCHAR), '') AS "cs",
       coalesce(CAST(e."hbp" AS VARCHAR), '') AS "hbp",
       coalesce(CAST(e."sf" AS VARCHAR), '') AS "sf", e."ra", e."er", e."era", e."cg", e."sho",
       e."sv", e."ipouts", e."ha", e."hra", e."bba", e."soa", e."e",
       coalesce(CAST(e."dp" AS VARCHAR), '') AS "dp", e."fp", e."name", e."park",
       coalesce(CAST(e."attendance" AS VARCHAR), '') AS "attendance", e."bpf", e."ppf",
       e."team_id_br", e."team_id_lahman45", e."team_id_retro"
FROM team_season_reported e
JOIN team_franchise f ON f.franchise_key = e.franchise_id;

-- table: team_half
SELECT e."year", e."league_id", e."team_id", e."half", e."div_id", e."div_win", e."rank", e."g",
       e."w", e."l"
FROM team_half_reported e;

-- table: manager
SELECT pl.ext_id AS player_id, e."year", e."team_id", e."league_id", e."inseason", e."g", e."w",
       e."l", coalesce(CAST(e."rank" AS VARCHAR), '') AS "rank", e."plyr_mgr"
FROM manager_stint_reported e
JOIN player pl ON pl.player_key = e.player_id;

-- table: manager_half
SELECT pl.ext_id AS player_id, e."year", e."team_id", e."league_id", e."inseason", e."half", e."g",
       e."w", e."l", e."rank"
FROM manager_half_reported e
JOIN player pl ON pl.player_key = e.player_id;

-- table: appearances
SELECT e."year", e."team_id", e."league_id", pl.ext_id AS player_id,
       coalesce(CAST(e."g_all" AS VARCHAR), '') AS "g_all",
       coalesce(CAST(e."gs" AS VARCHAR), '') AS "gs", e."g_batting",
       coalesce(CAST(e."g_defense" AS VARCHAR), '') AS "g_defense", e."g_p", e."g_c", e."g_1b",
       e."g_2b", e."g_3b", e."g_ss", e."g_lf", e."g_cf", e."g_rf", e."g_of",
       coalesce(CAST(e."g_dh" AS VARCHAR), '') AS "g_dh",
       coalesce(CAST(e."g_ph" AS VARCHAR), '') AS "g_ph",
       coalesce(CAST(e."g_pr" AS VARCHAR), '') AS "g_pr"
FROM appearances_reported e
JOIN player pl ON pl.player_key = e.player_id;

-- table: batting
SELECT pl.ext_id AS player_id, e."year", e."stint", e."team_id", e."league_id", e."g",
       coalesce(CAST(e."ab" AS VARCHAR), '') AS "ab", coalesce(CAST(e."r" AS VARCHAR), '') AS "r",
       coalesce(CAST(e."h" AS VARCHAR), '') AS "h",
       coalesce(CAST(e."double" AS VARCHAR), '') AS "double",
       coalesce(CAST(e."triple" AS VARCHAR), '') AS "triple",
       coalesce(CAST(e."hr" AS VARCHAR), '') AS "hr",
       coalesce(CAST(e."rbi" AS VARCHAR), '') AS "rbi",
       coalesce(CAST(e."sb" AS VARCHAR), '') AS "sb", coalesce(CAST(e."cs" AS VARCHAR), '') AS "cs",
       coalesce(CAST(e."bb" AS VARCHAR), '') AS "bb", coalesce(CAST(e."so" AS VARCHAR), '') AS "so",
       coalesce(CAST(e."ibb" AS VARCHAR), '') AS "ibb",
       coalesce(CAST(e."hbp" AS VARCHAR), '') AS "hbp",
       coalesce(CAST(e."sh" AS VARCHAR), '') AS "sh", coalesce(CAST(e."sf" AS VARCHAR), '') AS "sf",
       coalesce(CAST(e."g_idp" AS VARCHAR), '') AS "g_idp"
FROM batting_line_reported e
JOIN player pl ON pl.player_key = e.player_id;

-- table: pitching
SELECT pl.ext_id AS player_id, e."year", e."stint", e."team_id", e."league_id", e."w", e."l", e."g",
       e."gs", e."cg", e."sho", e."sv", coalesce(CAST(e."ipouts" AS VARCHAR), '') AS "ipouts",
       e."h", e."er", e."hr", e."bb", e."so", e."baopp", e."era",
       coalesce(CAST(e."ibb" AS VARCHAR), '') AS "ibb",
       coalesce(CAST(e."wp" AS VARCHAR), '') AS "wp",
       coalesce(CAST(e."hbp" AS VARCHAR), '') AS "hbp", e."bk",
       coalesce(CAST(e."bfp" AS VARCHAR), '') AS "bfp",
       coalesce(CAST(e."gf" AS VARCHAR), '') AS "gf", e."r",
       coalesce(CAST(e."sh" AS VARCHAR), '') AS "sh", coalesce(CAST(e."sf" AS VARCHAR), '') AS "sf",
       coalesce(CAST(e."g_idp" AS VARCHAR), '') AS "g_idp"
FROM pitching_line_reported e
JOIN player pl ON pl.player_key = e.player_id;

-- table: fielding
SELECT pl.ext_id AS player_id, e."year", e."stint", e."team_id", e."league_id", e."pos", e."g",
       coalesce(CAST(e."gs" AS VARCHAR), '') AS "gs",
       coalesce(CAST(e."inn_outs" AS VARCHAR), '') AS "inn_outs",
       coalesce(CAST(e."po" AS VARCHAR), '') AS "po", coalesce(CAST(e."a" AS VARCHAR), '') AS "a",
       coalesce(CAST(e."e" AS VARCHAR), '') AS "e", coalesce(CAST(e."dp" AS VARCHAR), '') AS "dp",
       coalesce(CAST(e."pb" AS VARCHAR), '') AS "pb", coalesce(CAST(e."wp" AS VARCHAR), '') AS "wp",
       coalesce(CAST(e."sb" AS VARCHAR), '') AS "sb", coalesce(CAST(e."cs" AS VARCHAR), '') AS "cs",
       coalesce(CAST(e."zr" AS VARCHAR), '') AS "zr"
FROM fielding_line_reported e
JOIN player pl ON pl.player_key = e.player_id;

-- table: fielding_outfield
SELECT pl.ext_id AS player_id, e."year", e."stint", coalesce(CAST(e."glf" AS VARCHAR), '') AS "glf",
       coalesce(CAST(e."gcf" AS VARCHAR), '') AS "gcf",
       coalesce(CAST(e."grf" AS VARCHAR), '') AS "grf"
FROM outfield_split_reported e
JOIN player pl ON pl.player_key = e.player_id;

-- table: salary
SELECT e."year", e."team_id", e."league_id", pl.ext_id AS player_id, e.salary // 100 AS salary
FROM salary_reported e
JOIN player pl ON pl.player_key = e.player_id;

-- table: home_game
SELECT e."year", e."league_id", e."team_id", pk.ext_id AS park_id, e."span_first", e."span_last",
       e."games", e."openings", e."attendance"
FROM home_games_reported e
JOIN park pk ON pk.park_key = e.park_id;

-- table: all_star
SELECT pl.ext_id AS player_id, e."year", e."game_num", e."game_id", e."team_id", e."league_id",
       coalesce(CAST(e."gp" AS VARCHAR), '') AS "gp",
       coalesce(CAST(e."starting_pos" AS VARCHAR), '') AS "starting_pos"
FROM all_star_selected e
JOIN player pl ON pl.player_key = e.player_id;

-- table: postseason
SELECT e."year", e."round", e."team_id_winner", e."league_id_winner", e."team_id_loser",
       e."league_id_loser", e."wins", e."losses", e."ties"
FROM postseason_series_decided e;

-- table: batting_postseason
SELECT e."year", e."round", pl.ext_id AS player_id, e."team_id", e."league_id", e."g", e."ab",
       e."r", e."h", e."double", e."triple", e."hr", e."rbi", e."sb",
       coalesce(CAST(e."cs" AS VARCHAR), '') AS "cs", e."bb", e."so",
       coalesce(CAST(e."ibb" AS VARCHAR), '') AS "ibb",
       coalesce(CAST(e."hbp" AS VARCHAR), '') AS "hbp",
       coalesce(CAST(e."sh" AS VARCHAR), '') AS "sh", coalesce(CAST(e."sf" AS VARCHAR), '') AS "sf",
       coalesce(CAST(e."g_idp" AS VARCHAR), '') AS "g_idp"
FROM batting_postseason_reported e
JOIN player pl ON pl.player_key = e.player_id;

-- table: pitching_postseason
SELECT pl.ext_id AS player_id, e."year", e."round", e."team_id", e."league_id", e."w", e."l", e."g",
       e."gs", e."cg", e."sho", e."sv", e."ipouts", e."h", e."er", e."hr", e."bb", e."so",
       e."baopp", e."era", coalesce(CAST(e."ibb" AS VARCHAR), '') AS "ibb",
       coalesce(CAST(e."wp" AS VARCHAR), '') AS "wp",
       coalesce(CAST(e."hbp" AS VARCHAR), '') AS "hbp",
       coalesce(CAST(e."bk" AS VARCHAR), '') AS "bk",
       coalesce(CAST(e."bfp" AS VARCHAR), '') AS "bfp", e."gf", e."r",
       coalesce(CAST(e."sh" AS VARCHAR), '') AS "sh", coalesce(CAST(e."sf" AS VARCHAR), '') AS "sf",
       coalesce(CAST(e."g_idp" AS VARCHAR), '') AS "g_idp"
FROM pitching_postseason_reported e
JOIN player pl ON pl.player_key = e.player_id;

-- table: fielding_postseason
SELECT pl.ext_id AS player_id, e."year", e."team_id", e."league_id", e."round", e."pos", e."g",
       coalesce(CAST(e."gs" AS VARCHAR), '') AS "gs",
       coalesce(CAST(e."inn_outs" AS VARCHAR), '') AS "inn_outs", e."po", e."a", e."e", e."dp",
       e."tp", coalesce(CAST(e."pb" AS VARCHAR), '') AS "pb",
       coalesce(CAST(e."sb" AS VARCHAR), '') AS "sb", coalesce(CAST(e."cs" AS VARCHAR), '') AS "cs"
FROM fielding_postseason_reported e
JOIN player pl ON pl.player_key = e.player_id;

-- table: player_award
SELECT pl.ext_id AS player_id, e."award_id", e."year", e."league_id", e."tie", e."notes"
FROM player_award_won e
JOIN player pl ON pl.player_key = e.player_id;

-- table: player_award_vote
SELECT e."award_id", e."year", e."league_id", pl.ext_id AS player_id, e."points_won",
       e."points_max", e."votes_first"
FROM player_award_vote_received e
JOIN player pl ON pl.player_key = e.player_id;

-- table: manager_award
SELECT pl.ext_id AS player_id, e."award_id", e."year", e."league_id", e."tie", e."notes"
FROM manager_award_won e
JOIN player pl ON pl.player_key = e.player_id;

-- table: manager_award_vote
SELECT e."award_id", e."year", e."league_id", pl.ext_id AS player_id, e."points_won",
       e."points_max", e."votes_first"
FROM manager_award_vote_received e
JOIN player pl ON pl.player_key = e.player_id;

-- table: hall_of_fame
SELECT pl.ext_id AS player_id, e."yearid", e."votedby",
       coalesce(CAST(e."ballots" AS VARCHAR), '') AS "ballots",
       coalesce(CAST(e."needed" AS VARCHAR), '') AS "needed",
       coalesce(CAST(e."votes" AS VARCHAR), '') AS "votes", e."inducted", e."category",
       e."needed_note"
FROM hof_ballot_recorded e
JOIN player pl ON pl.player_key = e.player_id;

-- table: player_college
SELECT pl.ext_id AS player_id, c.ext_id AS college_id, e.year
FROM college_attended e
JOIN player pl ON pl.player_key = e.player_id
JOIN college c ON c.college_key = e.college_id;
