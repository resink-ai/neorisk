# Baseball (Spider 2.0-lite): reverse-engineered event log

Source: `data/spider2/Baseball.sqlite` (29 MB, 26 tables, 553,693 rows), opened read-only. `scripts/baseball/rq.py` copies the file into an in-memory SQLite and runs named blocks. Blocks named `setup*` only create indexes on that in-memory copy. The file itself is never written.

Every number below comes from one of these scripts:
- a named block in `scripts/baseball/q*.sql`;
- `p1_profile.py`, which profiles every column: typeof counts, `''` counts, distinct values, min and max;
- `f1_floats.py` and `f2_noise_years.py`, which check mixed columns, REAL text forms and derived columns;
- `d1_dists.py` (distributions);
- `g2_local007_search.py`, which searches for the computation behind the local007 gold answers.

The raw outputs are in `scripts/baseball/out_*.txt`. A reference such as `[q2:player_fk_orphans]` means file `q2_joins.sql`, block `-- name: player_fk_orphans`. Gold files are in `scripts/baseball/gold/`.

## 0. What this catalog is

- **Dataset.** This is **Sean Lahman's Baseball Database**, the 2015 edition: seasons 1871–2015, plus Hall of Fame voting through 2016. It reached Spider in the form of **Kaggle's "The History of Baseball"** `database.sqlite`. The evidence:
  - The 26 tables are Lahman's tables renamed to snake_case: `Master` → `player`, `AllstarFull` → `all_star`, `SeriesPost` → `postseason`, `TeamsFranchises` → `team_franchise`, `FieldingOF` → `fielding_outfield`, `Schools` → `college`, `CollegePlaying` → `player_college`, `AwardsSharePlayers` → `player_award_vote`, and so on. Columns follow the same pattern: `yearID` → `year`, `2B` → `double`, `GIDP` → `g_idp`.
  - The data ends in the 2015 season: years run 1871–2015 [p1]. The last `final_game` is 2015-10-04, on 501 players [q3:snapshot_dates]. The last `hall_of_fame.yearid` is 2016 [p1], and the last death is 2016-02-18 [q6:death_max]. That fits the Lahman 2015 release of early 2016.
  - **There is no NULL in any cell. Every missing value is `''`** [f1: "NULL cells in the whole catalog: 0"]. Values are typed by column affinity, so NUMERIC columns hold integers, reals and `''`. That is the fingerprint of a CSV loaded through a pandas-style or `.import` path that wrote missing fields as empty strings. It matches the Kaggle export.
  - Known Lahman 2015 errata survive: `Cabremi01` with a capital C in one vote row, orphan 2014 ids (`arrueba01` and others), team `WSN` in 1892–1899 appearances, and player `johnsbi01` born in 1961 but dead in 1942 (§4).
- **Row counts** [p1]:

  | Table | Rows | Table | Rows |
  |---|---:|---|---:|
  | fielding | 170,526 | hall_of_fame | 4,120 |
  | batting | 101,332 | manager | 3,405 |
  | appearances | 100,951 | home_game | 2,944 |
  | pitching | 44,139 | team | 2,805 |
  | salary | 25,575 | college | 1,207 |
  | player | 18,846 | manager_award_vote | 414 |
  | player_college | 17,350 | postseason | 307 |
  | fielding_postseason | 12,311 | park | 250 |
  | fielding_outfield | 12,028 | manager_award | 177 |
  | batting_postseason | 11,690 | team_franchise | 120 |
  | player_award_vote | 6,795 | manager_half | 93 |
  | player_award | 6,078 | team_half | 52 |
  | pitching_postseason | 5,109 | all_star | 5,069 |

  The total is 553,693. There are no views, indexes or declared keys; `sqlite_master` holds only the 26 tables [p1].
- **Licence.** Lahman publishes the database under **CC BY-SA 3.0**. The Kaggle page's own licence field was not checked (§7).
- **Nature.** These are **real historical records**, compiled by hand and by community research (SABR, Retrosheet, Baseball-Reference). They are neither generated nor anonymised; players are named real people. Every fact table is **pre-aggregated** to a season, a season stint or a postseason round. **No game-level or play-level grain exists anywhere.**

### 0.1 How Spider 2.0 uses it

Two questions use db `Baseball`. Both touch only `player` and `batting`.

| id | what it asks | gold SQL? | gold answer | reproduced |
|---|---|---|---|---|
| local007 | average career span: \|Δyears\| + \|Δmonths\|/12 + \|Δdays\|/365 between `debut` and `final_game`, each part rounded to 2 decimals | no; two CSVs | `_a` 4.85; `_b` 5.09966563 (`_b`'s header is the literal `AVG(ROUND(ABS(YEARS),2)+ROUND(ABS(MONTHS)/12.0,2)+ROUND(ABS(DAYS)/365.0,2))`) | **✘ not reproduced.** The literal field-wise reading gives 4.92375 over the 18,653 players with a debut, and 4.87333 when the 193 `''` rows count as 0 [q4:local007_variant_b_debut_nonempty, q4:local007_variant_all_rows]. Ten other readings (total days, borrowed months, joins weighted by batting rows, …) give 4.72–4.83 or 8.8–14.5 [g2, q4:local007_weighted_by_join]. None gives 4.85 or 5.0997 |
| local008 | given name of the career leader in games, runs, hits and home runs (Σ over `batting`), with the value | yes | Peter Edward 3,562 g and 4,256 h; Rickey Nelson Henley 2,295 r; Barry Lamar 762 hr (both CSVs) | **✔ exactly**, with the gold SQL [q4:local008_gold_sql] |

- **local008** depends on SQLite summing `''` as 0. `SUM(r)` over the column returns a **real**, 1912795.0, because of the text cells. With `''` turned into NULL it returns the integer 1912795 [q4:local008_sum_types]. The values compare equal, so either rebuild passes, but the results must keep `''` to be byte-faithful.
- **local007** needs `debut` and `final_game` verbatim as `YYYY-MM-DD` text, `''` included. Its gold value is probably from another data version or another date-difference function (§7).

## 1. Inventory, keys, joins

No PK or FK is declared. Every candidate key below is unique, measured [q1:key_uniqueness]. There are 0 full-row duplicates in any of the 11 tables checked [q1:full_row_duplicates].

| Table | Key (verified unique) | Kind |
|---|---|---|
| player | player_id (also unique under `lower()`) | entity: person (players, managers, executives, umpires) |
| team_franchise | franchise_id | entity |
| park | park_id | entity (249 of 250 used) [q2:park_used] |
| college | college_id | entity (1,034 of 1,207 used) [q2:college_used] |
| batting / pitching | (player_id, year, stint) | season-stint aggregate |
| fielding | (player_id, year, stint, pos) | season-stint-position aggregate |
| fielding_outfield | (player_id, year, stint) | LF/CF/RF split, 1871–1955 only |
| appearances | (year, team_id, player_id) | season games by position |
| salary | (year, team_id, player_id); 104 player-years have 2 teams | season fact, 1985–2015 |
| team | (year, team_id) | team-season aggregate |
| team_half / manager_half | (year, team_id, half) / (player_id, year, team_id, half) | 1981 strike-split halves (and 1892 for managers) |
| manager | (year, team_id, inseason) | manager stint aggregate |
| home_game | (year, team_id, park_id) | team-season-park aggregate with first and last dates |
| all_star | (player_id, year, game_num) | selection to an all-star game |
| batting_ / pitching_postseason | (year, round, player_id) | postseason-round aggregate |
| fielding_postseason | (player_id, year, round, pos) | same |
| postseason | (year, round) | series result |
| player_award / manager_award | (player_id, award_id, year, league_id) | award won |
| player_award_vote / manager_award_vote | (award_id, year, league_id, player_id) | vote share |
| hall_of_fame | (player_id, yearid, votedby); not (player_id, yearid): 4,120 vs 3,988 | ballot result |
| player_college | (player_id, college_id, year) | link, one row per college year |

**Joins and orphans** [q2:*, q3:*]:
- **player_id → player.** There are 12 distinct orphan ids [q8:orphan_ids_distinct]:
  - appearances 7 rows, all from 2014 (`arrueba01`, `castiru02`, `furcara02`, `harriwi10`, `pricebr10`, `rosajo01`, `smithch09`);
  - salary 8 rows (5 of those same ids);
  - all_star 1 (`carperma01`, 2014);
  - hall_of_fame 1 (`nomohid01`);
  - manager 1 (`cammebi99`);
  - manager_award 1 (`maddojo01`, 2015);
  - player_award_vote 1 (`Cabremi01`, the 2005 NL MVP row of `cabremi01`) [q8:cabremi_vote].

  Batting, pitching, fielding and every postseason table resolve 100%.
- **(year, team_id) → team.**
  - batting, pitching, fielding, manager, home_game, team_half, manager_half and all three postseason line tables resolve 100%.
  - appearances has 276 rows in 9 team-seasons that are missing: `WSN` 1892–1899 (the team table says `WAS`) and `KCR` 2014 (the team table says `KCA`).
  - all_star has 8 (`TBA` 1996, `TBR` 2009, `ARL` and `BIS` 2011, `SFG` 2015).
  - postseason has 4 winners and 8 losers, the 1884–1892 series, which use Baseball-Reference codes [q3:appearances_team_orphans, q3:team_year_orphan_detail, q3:postseason_team_orphans].
  - Adding `league_id` to the join breaks 1 more appearances row and 2 salary rows (CLE 2014 as `NL`, ARI 2015 as `AL`) [q2:league_mismatch_detail].
- **team.franchise_id → team_franchise:** 0 orphans, and all 120 franchises are used. **home_game.park_id → park:** 0 orphans.
- **player_college.college_id → college:** 10 orphan rows, 4 ids: `caallia`, `ctpostu`, `txrange`, `txutper` [q3:college_orphans].
- **team.park** is free text. 789 of the 2,771 non-empty values match neither `park.park_name` nor `park_alias`, so it is not a join [q2:other_fk].
- **team_id is a code, not an identity:**
  - 149 codes, 120 franchises;
  - `HOU` plays in 2 leagues; `PH4` and `WAS` belong to 2 franchises each;
  - 20 codes have more than one team name [q2:team_id_functional, q3:team_ids_multi_franchise].

**Copies and derived tables.** No table is a copy of another or a pure function of other tables. Every candidate fails on real rows [q5:*]:

| candidate | rows | equal |
|---|---:|---:|
| `fielding_outfield` vs Σ appearances g_lf, g_cf, g_rf per player-year | 11,283 | 11,047 |
| team r, h, hr, ab, bb vs Σ batting | 2,805 | 2,390 (all 5 equal) |
| team w vs Σ pitching w | 2,805 | 2,748 |
| team w vs Σ manager w | 2,805 | 2,801 |
| team attendance vs Σ home_game attendance | 2,496 present | 447 |
| team_half Σ (w, l, g) vs team | 26 | 19 |
| appearances g_batting vs batting g | 100,651 | 84,707 |

- `manager_half` sums to `manager` on all 55 groups. But it is the finer grain, so it is a source table, not a derived one.
- The catalog is **not a copy** of any batch 1 or 2 catalog.

**Row order.** Rowid order is year-major in batting, pitching, fielding, appearances, salary and team: 0 year breaks [q2:rowid_order]. `player` is in player_id order.

## 2. Event catalog

**What is natural and what is a rule.**
- These timestamps are **natural**:
  - `player.debut` (18,653 rows);
  - `home_game.span_first` and `span_last`;
  - the all-star game date encoded in `game_id`. `ALS193307060` means 1933-07-06; the game_id year equals `year` in 5,020 of 5,020 rows, and every encoded date is valid [q3:allstar_gameid_date].
- Every other fact row has only a **year**, so its time is a **rule**. The rule dates are set so that every natural in-season date falls before them: the latest `span_last` and `final_game` are on 11-01, and the latest debut on 10-30 [q6:natural_dates_mmdd].

| Rule | Date | Applied to |
|---|---|---|
| S(y) | `<y>-11-01T00:00:00Z` | regular-season aggregates and salary |
| P(y) | `<y>-11-02T00:00:00Z` | postseason lines and series |
| A(y) | `<y>-11-30T00:00:00Z` | awards and award votes |
| H(y) | `<yearid>-01-15T00:00:00Z` | Hall of Fame ballots. BBWAA results are announced in January, which also keeps yearid 2016 before N |

Within one instant, the order is set by the ingest blocks (§6).

**Entities**:

| Entity | Rows | created_at | Time is | Attributes |
|---|---:|---|---|---|
| `player` | 18,846 + 12 stubs | min(`debut`, first owned event). For no debut: first event (190 players, years 1871–2015); never used (3: `crossjo01`, `mondera02`, `sulliwi01`): catalog start T0 = 1871-01-01 [q7:no_debut_first_event, q7:never_used_players] | natural for 18,604; rule for 242 | ext_id, birth_* (6, `opt i64` / text), name_first, name_last, name_given, weight, height, bats, throws, debut (text), retro_id, bbref_id. **Snapshot columns:** `final_game` (it is a lifetime value; for 1,076 players it is September 2015 or later, so still open at N) and the 6 `death_*` columns |
| `team_franchise` | 120 | `<first team year>-01-01` (rule) | rule | ext_id, franchise_name, na_assoc. **Snapshot:** `active` (current state) |
| `park` | 250 | min(span_first) over home_game; the unused FOR02 gets T0 | natural for 249 | ext_id, park_name, park_alias, city, state, country |
| `college` | 1,207 | T0 (rule) | rule | ext_id, name_full, city, state, country |
| `season` | 145 (1871–2015) | `<y>-01-01` (rule) | rule | year. An **owner shard only**: it has no results table and exists because `postseason` has no resolvable team owner (12 orphan codes) |

**The 12 orphan player ids** become **stub** `player` entities with `stub = true`. They are created at their first event, and `build.sql` drops them from `player`. This keeps every `player_id` a typed ref. The text-ref alternative is in §7.

**Business events**. All are "reported" aggregates unless marked natural:

| # | Event | Owner | Time | Attributes | Source | Count |
|---|---|---|---|---|---|---:|
| E1 | `batting_line_reported` | player | S(year) | year, stint, team_id (cat), league_id, g, 16 counting stats (`opt i64`) | batting | 101,332 |
| E2 | `pitching_line_reported` | player | S(year) | year, stint, team, league, 23 stats, era and baopp (text, §3) | pitching | 44,139 |
| E3 | `fielding_line_reported` | player | S(year) | year, stint, team, league, pos (cat 11), g, 11 stats | fielding | 170,526 |
| E4 | `outfield_split_reported` | player | S(year) | year, stint, glf, gcf, grf | fielding_outfield | 12,028 |
| E5 | `appearances_reported` | player | S(year) | year, team, league, 17 g_* counts | appearances | 100,951 |
| E6 | `salary_reported` | player | S(year) | year, team, league, salary (`amount` USD, whole dollars) | salary | 25,575 |
| E7 | `manager_stint_reported` | player | S(year) | year, team, league, inseason, g, w, l, rank, plyr_mgr | manager | 3,405 |
| E8 | `manager_half_reported` | player | S(year) | the same, plus half | manager_half | 93 |
| E9 | `team_season_reported` | team_franchise | S(year) | year, league, team_id, div_id, rank, the remaining team stat columns, the 4 *_win flags (text Y/N/''), name, park, attendance, bpf, ppf, 3 alternate ids | team | 2,805 |
| E10 | `team_half_reported` | team_franchise (via team) | S(year) | year, league, team, half, div_id, div_win, rank, g, w, l | team_half | 52 |
| E11 | `home_games_reported` | team_franchise (via team) | **`span_last`** (natural) | year, league, team, park (ref), span_first (text), games, openings, attendance | home_game | 2,944 |
| E12 | `all_star_selected` | player | **game date from game_id** (natural, 5,020); rule 1945-07-10 for the 49 rows of 1945, which have `game_id = ''` (no game was played) | year, game_num, game_id (text), team, league, gp, starting_pos | all_star | 5,069 |
| E13 | `postseason_series_decided` | season | P(year) | round, winner and loser team and league codes, wins, losses, ties | postseason | 307 |
| E14–E16 | `batting_` / `pitching_` / `fielding_postseason_reported` | player | P(year) | round, team, league, stats | 3 postseason tables | 11,690 / 5,109 / 12,311 |
| E17 | `player_award_won` | player | A(year) | award_id (cat 27), league, tie, notes | player_award | 6,078 |
| E18 | `player_award_vote_received` | player | A(year) | award_id, league, points_won (`f64`), points_max, votes_first (text) | player_award_vote | 6,795 |
| E19 | `manager_award_won` | player | A(year) | award_id, league, tie, notes | manager_award | 177 |
| E20 | `manager_award_vote_received` | player | A(year) | award_id, league, points_won, points_max, votes_first | manager_award_vote | 414 |
| E21 | `hof_ballot_recorded` | player | H(yearid) | votedby (cat 9), ballots, needed, votes, inducted, category, needed_note | hall_of_fame | 4,120 |
| E22 | `college_attended` | player | the player's created_at (rule, ord after creation) | college (ref), year | player_college | 17,350 |

- **Business events: 533,270.** That is every non-entity source row, one event each. Entity creations: 20,580 (18,858 players, 120 franchises, 250 parks, 1,207 colleges, 145 seasons). Player snapshots: 18,846. **The log totals about 572.7k events.**
- **Rule conflicts measured** [q7:events_before_debut, q7:players_with_event_before_debut]. Only **54 rows on 49 players** have a rule time before their debut:
  - 45 salary rows: the player was paid while on the roster before debuting;
  - morgabi02's 1882 batting line, against a 1883 debut;
  - 2 award rows, such as `ayalabo01`'s 1954 award with a 1992 debut. These look like id collisions.

  This is why `created_at` is min(debut, first owned event) and not plain debut. For those 49 players, `debut` on the creation event is a value from the future (§7).
- **E22 is imposed.** 16,930 of 17,277 college rows have a year before the player's debut [q7:events_before_debut]. A college year is not observed as a dated event, so the history is attached when the player is created.

**What is not an entity or an event, and why:**
- **team_id and league_id** are codes, not entities. They are not stable identities (§1), and they would leave about 290 orphan refs. They ride as `cat` text, and `team_franchise` is the team entity.
- **Births and deaths are not events.** Births are partial (321 lack a month or day, 143 a year), and every one precedes the catalog [q3:birth_death_partial]. Deaths are partial too (2 lack a day), and 496 Hall of Fame rows are posthumous [q6:events_after_death]. Both stay player attributes: birth on creation, death in the snapshot.
- **No game, play or transaction grain exists.** Trades show only as stint numbers (1–5 per player-year: 86,865 single-stint player-years, 6,655 with 2 stints) [d1].
- **team.era is derived exactly** (§3.3). It is still carried, because team is a source table and the gain is one column.

**Snapshot N = 2016-02-18**, the last death date and the latest dated fact [q6:death_max]. Every event time is at most H(2016) = 2016-01-15, which is earlier.

## 3. Rebuild rules and blockers to an exact round trip

1. **`''` is the only missing marker, and NULL never occurs** [f1]. So `''` ↔ JSON `null` is lossless:
   - numeric fields: `opt(i64)` in, `coalesce(CAST(x AS TEXT), '')` out;
   - text fields keep `''` verbatim as `text()`.

   Spider's local008 sums are equal under either form (§0.1).
2. **91 of the 230 numeric-affinity columns are "mixed"** [f1]. Each is a NUMERIC column holding integers or reals next to `''`. Examples: batting has 16 of them, player has 8 (birth, death, weight, height), and team has 8. No INTEGER-declared or REAL-declared column holds text.
   - **Per the contract, they are written as string results** of `CAST(x AS TEXT)`. `build.sql` must therefore produce SQLite's text: `'5'` for an integer, `''` for missing.
   - 87 of the 91 are integers-or-`''`, and DuckDB's `CAST(BIGINT AS VARCHAR)` gives the same text.
   - **Non-empty text in a numeric column:** exactly one cell, `pitching_postseason.era = 'inf'`. `manager_award.notes` (NUMERIC) is `''` in all 177 rows.
3. **Floats.**
   - Four mixed columns hold reals: `pitching.baopp`, `pitching.era`, `pitching_postseason.era` and `player_award_vote.votes_first`.
   - **`pitching.baopp` carries 17-digit float noise** in 2,518 of 41,524 reals [f1, f2]:
     - for example, 0.24600000000000002, whose SQLite `CAST AS TEXT` is `'0.246'` (`%.15g`);
     - the noise is only in 2000–2015 rows;
     - it takes 90 distinct values.

     Because the column is mixed, the result is the text `'0.246'`. **Carry these 4 columns as payload text equal to SQLite's `CAST(x AS TEXT)`.** Carrying them as `f64` would need a `%.15g` printer in every engine; DuckDB prints the shortest round-trip form, `0.24600000000000002`.
   - The non-mixed REAL columns `team.era`, `team.fp` and `player_award_vote.points_won` are carried as `f64` verbatim. `team.fp` has 80 noisy values (0.9790000000000001 …), all from 2000 on; shortest-repr JSON round-trips them exactly [f1, f2]. All 6 real `points_won` values are halves (10.5, 0.5, …), from split Rookie-of-the-Year votes [q3:real_points_won].
4. **Derived columns**, proven [f1]:
   - `team.era = round(27·er/ipouts, 2)` on **2,805 of 2,805** rows. It is an exact function, and `build.sql` may compute it.
   - `pitching.era` is within ±0.005 of 27·er/ipouts on 44,049 of 44,049 rows, but equals `round(…, 2)` on only 43,935. The difference is half-way rounding in Lahman's tooling, for example 13·27/120 = 2.925 → 2.93. Carry it verbatim.
   - `pitching.era = ''` means ipouts = 0 in 89 of 90 rows; the exception is `leblawa01` 2014, where ipouts is `''` too [q8:leblawa01_era].
   - `pitching.baopp` matches `round(h/(bfp−bb−hbp−sh−sf), 3)` on 11,206 of 11,233 rows where every input is present, and has 2 decimals on 32,971 of 42,614 rows (pre-modern rows). Carry it verbatim.
   - `pitching_postseason.era` is `''` or `'inf'` on all 55 rows with ipouts = 0, but also `''` on 214 rows with ipouts > 0. It is not derivable.
   - `pitching_postseason.baopp` is TEXT, with forms `'0.x'` (4,441), single digits `'0'`–`'9'` (576), `'1.0'` (1), 22 values from `'11'` to `'31'`, one `'-'` and 68 `''` [q3:ps_baopp_forms]. Keep it byte-exact as text.
5. **Dates.**
   - `debut`, `final_game`, `span_first` and `span_last` are all strict `YYYY-MM-DD`, with `date(x) = x` on every non-empty cell [q3:date_formats]. Carry them as text. `debut` and `span_last` can instead rebuild from the event time with `%Y-%m-%d`, but only where the time is natural.
   - `game_id` must stay text, because its date is embedded, and `''` for 1945.
6. **Text quirks to keep byte-exact** [q3:award_id_case, q3:player_award_notes]:
   - `award_id` `'Mgr of the Year'` (81 rows) next to `'Mgr of the year'` (333);
   - `'BBWAA Manager of the year'`;
   - player_award notes `'Ss'` (1 row) next to `'SS'`;
   - `player_award_vote.player_id = 'Cabremi01'`.

   No leading or trailing whitespace exists in any text cell [p1: ws=0 everywhere].
7. **No duplicates, and no rows without a year.** Every fact row has a year. The only true time gaps are the 49 rows of 1945 all-star selections.

**Verdict:** exact with caveats. The cell values round-trip once mixed columns are rebuilt as SQLite cast text, and the 4 real-bearing mixed columns travel as that text. The caveats concern time: 525k of the 533k business events sit on rule dates, and the 12 orphan ids need stub entities.

## 4. Measured quirks

- **Orphans and errata** (§1):
  - 12 orphan player ids, concentrated in 2014–2015 rows;
  - `WSN`/`WAS` and `KCR`/`KCA` code splits in appearances;
  - old postseason codes;
  - 4 unknown colleges;
  - `Cabremi01`.
- **Impossible person** `johnsbi01` (Lefty Johnson): born 1961-09-28, died 1942, debut 1884-06-27 [q8:johnsbi01, q6:birth_after_debut_detail]. It is the only death-before-birth row, and it causes the 5 "batting before birth year" rows [q6:birth_vs_events].
- **Debut and final_game agree with the stat years** for 18,649 of 18,653 players [q3:debut_vs_stats]. One player has final_game < debut. The block [q3:debut_mismatch_examples] lists the 8 players whose debut year or final year differs from their batting years.
- **Empty-league era.** league_id is `''` for all 1871–1875 rows: team 50, batting 737, appearances 737, fielding 1,503. That is the National Association, which Lahman leaves blank [q3:empty_league_years].
- **Coverage changes by era**, which shows as columns that are empty for whole periods:
  - batting `ibb` is empty on 41,712 rows;
  - fielding `pb`, `wp`, `sb`, `cs` and `zr` are empty on 159k–166k of 170k rows;
  - `fielding_outfield` exists only for 1871–1955;
  - salary exists only for 1985–2015;
  - award votes start in 1911 (players) and 1983 (managers) [p1, q3:year_coverage].
- **1981 split season.** team_half has only 1981 (52 rows); manager_half has 1892 and 1981. 7 of 26 team_half groups do not sum to the team row [q5:team_half_vs_team].
- **Hall of Fame vote fields** are `''` by design for the non-BBWAA committees (Veterans, Old Timers, Negro League, Centennial, Special Election): 193 rows. `needed` is also `''` for Run Off and Nominating Vote [q3:hof_categories].
- **Team flags** `div_win`, `wc_win`, `lg_win` and `ws_win` are Y, N or `''`. `''` means the concept did not exist yet, and it is not missing data: 28 teams have all four `''` [q3:team_flags].
- **Zeros.** `home_game.attendance = 0` on 449 rows (unrecorded) [q3:home_game_spans], and `salary = 0` on 2 rows [q3:salary_values].
- **Spans are consistent:** span_last ≥ span_first and both fall in `year`, on 2,944 of 2,944 rows [q3:home_game_spans].
- **Generator fingerprint.** The 17-digit noise appears only in 2000+ `baopp` and `fp` [f2], which points to a different upstream pipeline for recent seasons. All-`''`, no-NULL storage points to a CSV load.

## 5. Distributions to fit (stage 2)

| Quantity | Value [d1] |
|---|---|
| debuts per decade | 448 (1870s) … 1,546 (1910s) … 2,077 (2000s); 1,366 in 2010–2015 |
| debut month | Apr 4,810 and Sep 5,156 (the September call-ups) dominate; May–Aug about 2,000 each; Mar 49, Oct 309 |
| teams per season | 9 (1871), 8 (1876, 1900), 16 (1901, 1950), 24 (1914, Federal League), 18 (1961), 24 (1969), 26 (1977), 28 (1993), 30 (1998, 2015) |
| batting lines per season | 115 (1871), 577 (1950), 1,384 (2000), 1,486 (2015) |
| stints per player-year | 1: 86,865; 2: 6,655; 3: 355; 4: 22; 5: 1 |
| seasons per player | p50 3, p75 7, p90 12, p99 19, max 27; 5,157 players have one season |
| career span (final − debut) | p25 137 d, p50 1,165 d, p90 4,478 d; 1,007 one-day careers |
| AB per line | p25 7, p50 57, p75 251, p99 618, max 716; 9,773 lines with ab = 0 |
| HR per line | p75 3, p90 10, p99 32, max 73 |
| fielding position mix | P 44,141, OF 28,079, 3B 13,854, 1B 13,468, 2B 12,685, LF 11,986, SS 11,518, C 11,116, RF 10,763, CF 7,867, DH 5,049 |
| salary by year | 1985: p50 400k, max 2.13M; 2015: p50 1.88M, p90 12.5M, max 32.6M; heavy right tail; 84% are multiples of 1,000 |
| ERA (ipouts ≥ 150) | p5 2.18, p50 3.77, p90 5.34, p99 6.97, max 10.64 |
| team win % | p5 0.338, p50 0.506, p90 0.610, p99 0.702, max 0.899 |
| managers per team-season | 1: 2,347; 2: 350; 3: 87; up to 9 |
| HoF ballots per candidate | 1: 757 … 15: 40 (the 15-year eligibility cap shows); 312 of 4,120 rows inducted |
| colleges per player | 1: 5,651; 2: 873; 3: 51; college years 1–4 mostly |
| body | height p50 72 in; weight p50 185 lb; bats R 11,615, L 4,877, B 1,163, `''` 1,191 |
| birth country | USA 16,504, D.R. 643, Venezuela 341, P.R. 253, CAN 244, Cuba 198 |

## 6. simkit mapping sketch

```python
NUM = opt(i64())                       # '' <-> null; rebuilt as coalesce(CAST(x AS TEXT), '')
p.entity("team_franchise", key="franchise_key", cols={"ext_id": text(), "franchise_name": text(), "na_assoc": text()},
         snapshot={"active": text()})
p.entity("park", key="park_key", cols={"ext_id": text(), "park_name": text(), "park_alias": text(), "city": text(),
         "state": text(), "country": cat("US", "CA", "AU", "JP", "MX", "PR")})
p.entity("college", key="college_key", cols={"ext_id": text(), "name_full": text(), "city": text(), "state": text(), "country": text()})
p.entity("season", key="season_key", cols={"ext_id": i32()})                       # owner shard only
p.entity("player", key="player_key", cols={"ext_id": text(), "stub": cat("0", "1"),
         "birth_year": NUM, "birth_month": NUM, "birth_day": NUM, "birth_country": text(), "birth_state": text(), "birth_city": text(),
         "name_first": text(), "name_last": text(), "name_given": text(), "weight": NUM, "height": NUM,
         "bats": text(), "throws": text(), "debut": text(), "retro_id": text(), "bbref_id": text()},
         snapshot={"final_game": text(), "death_year": NUM, "death_month": NUM, "death_day": NUM,
                   "death_country": text(), "death_state": text(), "death_city": text()})
p.event("batting_line_reported", cols={"player": ref("player"), "year": i32(), "stint": i32(), "team_id": cat(...),
        "league_id": text(), "g": i64(), "ab": NUM, "r": NUM, "h": NUM, "double": NUM, ..., "g_idp": NUM})
p.event("pitching_line_reported", cols={..., "ipouts": NUM, "era": text(), "baopp": text(), ...})   # era/baopp = SQLite cast text
p.event("team_season_reported", cols={"franchise": ref("team_franchise"), "year": i32(), "team_id": text(),
        "era": f64(), "fp": f64(), "attendance": NUM, "name": text(), "park": text(), ...})
p.event("home_games_reported", cols={"franchise": ref("team_franchise"), "park": ref("park"), "span_first": text(), ...})
p.event("all_star_selected", cols={"player": ref("player"), "game_id": text(), "game_num": i32(), "gp": NUM, "starting_pos": NUM, ...})
p.event("postseason_series_decided", cols={"season": ref("season"), "round": cat(14 codes), "team_id_winner": text(), ...})
p.event("player_award_vote_received", cols={"player": ref("player"), "award_id": cat("Cy Young", "MVP", "Rookie of the Year"),
        "points_won": f64(), "points_max": i64(), "votes_first": text()})
p.event("college_attended", cols={"player": ref("player"), "college": ref("college"), "year": i32(), "college_ext": text()})
# … E3–E8, E10, E14–E21 follow the same pattern
```

**Ingest.**
- The event time comes from the rule table in §2, or from the natural column for E11, E12 and the player's debut.
- Owners:
  - `owner = player` for player tables;
  - `owner = franchise`, through `team.franchise_id` on (year, team_id), for E9–E11. This join is 0-orphan for team_half and home_game;
  - `owner = season` for E13.
- `ORDER BY` follows each table's natural key: batting by (year, player_id, stint), fielding by (year, player_id, stint, pos), and so on.
- At the same instant S(y), the block order sets `ord`: E9 and E10 (team) → E7 and E8 → E5 → E1 → E2 → E3 → E4 → E6. At P(y): E13 → E14–E16. At A(y): E17 → E18 → E19 → E20. E22 follows the owner's creation (ord = creation + 1 + rank of (year, college_id)).
- Orphan college ids (4) become college stubs on the same pattern as player stubs, with `college_ext` kept as text.

**build.sql.**
- **Each fact table is** `SELECT` of the payload fields from its own event type. Every `NUM` field is `coalesce(CAST(f AS TEXT), '')`; the 4 real-bearing mixed columns are the payload text as is.
- `player` comes from creation plus snapshot `WHERE stub = '0'`; likewise `college`. `park`, `team_franchise` and `college` come from creation events.
- `season` produces no table.
- `team.era` can be `round(27.0*er/ipouts, 2)` (exact on 2,805 of 2,805) or carried; carrying it is recommended for engine-independence.

**Stage 2.**
- Owners:
  - **player** (lifecycle: debut → 1–27 seasons → final game, then possibly HoF ballots);
  - **franchise** (one team-season per year);
  - **season** (postseason bracket, award voting).
- A season tick at S(y) emits each active player's stints, drawn from the §5 mixes. The sim must keep the identities Σ fielding g ≈ appearances, and team w = Σ manager w (2,801 of 2,805).
- About 573k events; a `sample` profile (for example 1990–2015 only, about 25% of rows) is advisable for CI.

## 7. Open questions and risks

- **local007 gold is not reproduced.** No reading of the question over this file gives 4.85 or 5.09966563 (§0.1, [g2]). The gold was likely run on a different copy (Spider2's BigQuery or Snowflake variant of the Lahman data) or with a different date function. Treat local007 as an unverifiable saved query, or keep our own answer (4.92375275) as the expected output.
- **Mixed-column cast text across engines.** Exactness relies on SQLite's `CAST(real AS TEXT)` (`%.15g`) for 4 columns. That is solved by carrying them as text. But any engine that rebuilds the 87 integer mixed columns must print integers without `.0`. DuckDB does; Spark's `CAST(double AS STRING)` would not, if a column were ever widened to double.
- **The 12 orphan player ids and 4 orphan colleges** force stub entities, or else refs carried as text. Stubs keep refs typed but add 16 entities that `build.sql` must filter. Decide one convention across Spider2 datasets.
- **Rule dates dominate.** Only E11 (2,944) and the dated part of E12 (5,020) are naturally timed, so 525,306 of 533,270 business events (98.5%) sit on S, P, A or H year dates or, for E22, on the player's created_at. Inter-event gaps are therefore meaningless within a season. Stage 2 should model seasons as ticks, not as arrival processes.
- **`debut` is a future value** at creation for the 49 players with pre-debut rows (54 rows). The alternative is to make `debut` a snapshot column too, which local007 does not mind. Also check the 2 suspicious award-before-debut rows (`ayalabo01` 1954, `carpech02` 2009); they look like id collisions in the source.
- **The 1945 all-star rule date** (1945-07-10, the cancelled game) is a convention. It should be confirmed or replaced with S(1945).
- **Licence.** Lahman's CC BY-SA 3.0 requires attribution and share-alike for redistributed rows. Confirm the Kaggle page's stated licence before shipping `results/`.
- **`season` as an owner** is a structure we impose; no source table carries it. An alternative is to own postseason series by the winner's franchise, after mapping the 4 old winner codes by hand.

**Summary**
- Exact round trip: **yes, with caveats**: 91 mixed columns are rebuilt as SQLite cast text, and the 4 real-bearing ones (with 2,518 noisy `baopp` floats and one `'inf'`) travel as text.
- Proposed dataset name: **`baseball`**.
- **22 event types** (533,270 events) and **5 entity types** (player with 12 stubs, team_franchise, park, college, season: 20,580 rows), plus a player snapshot.
- Event-shaped: **mostly imposed**. Every fact table is a season or round aggregate on a year rule date (98.5% of business events); only debuts, home-game spans and all-star game dates are natural.
- Hardest blocker: there is no time below the season, plus the `''`-for-missing storage that makes 91 numeric columns mixed text. The local007 gold also cannot be reproduced from this file.
