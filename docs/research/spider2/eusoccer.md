# EU_soccer (Spider 2.0-lite): reverse-engineered event log

Source: `data/spider2/EU_soccer.sqlite` (299 MB), opened read-only. The scripts open it with `mode=ro&immutable=1` and never copy or write it. `scripts/eusoccer/rq.py` runs named `-- name:` blocks; it prints SQL NULL as `NULL` and quotes the strings `''`, `'None'` and `'NULL'`, so a stored `'None'` cannot be mistaken for a NULL.

Every number below comes from one of these scripts:
- a named block in `scripts/eusoccer/q*.sql`;
- `p1_profile.py`: storage classes, NULLs, `''`, `'\N'` and padding, for every column;
- `p2_match_text.py`: the XML columns, the odds and `Player.height`;
- `p4_spider.py`: the gold answers;
- `p5_dists.py`: distributions, sizes and the creation rules.

The raw outputs are in `scripts/eusoccer/out_*.txt`. A reference such as `[q1:fk_orphans]` means file `q1_inventory.sql`, block `-- name: fk_orphans`. The gold SQL and CSVs are in `scripts/eusoccer/gold/`.

## 0. What this catalog is

- **Dataset.** This is the Kaggle **European Soccer Database** by Hugo Mathien (2016). It holds 11 top-flight leagues, 8 seasons (2008/09–2015/16), 25,979 matches, 11,060 players and 299 teams. The evidence:
  - The row counts are the well-known Kaggle figures: Match 25,979, Player 11,060, Player_Attributes 183,978, Team 299, Team_Attributes 1,458, and 11 each of Country and League [q1:row_counts]. These figures are recalled; I did not fetch the Kaggle page.
  - The odds column names (`B365H`, `BWD`, `IWA`, `LBH`, `PSH`, `WHH`, `SJH`, `VCH`, `GBH`, `BSH`) are **football-data.co.uk**'s bookmaker codes.
  - The eight XML columns use an incident schema (`event_incident_typefk`, `elapsed`, `elapsed_plus`, `sortorder`, `n`, `id`) that Kaggle credits to an enetscores feed [p2].
  - The player and team attributes are **EA Sports FIFA** ratings scraped from sofifa. The snapshot dates cluster on game-update days: 2007-02-22 (11,794 rows), 2013-09-20, 2011-08-30 and so on [q3:pa_dates_top]. The team tactics are on exactly six dates, 2010-02-22 … 2015-09-10 [q2:ta_dates].
- **Spider addition.** Spider added a **view `match_view`**, which joins Match with League, Team and 22 × Player names and passes `goal` and `card` through [p1 objects]. It has 25,979 rows, one per match [p4]. local219's gold SQL inlines the same text as a CTE.
- **System table.** `sqlite_sequence` has 7 rows [q1:sqlite_sequence_vs_max_id]. Unlike chinook's, its values are **not** the max ids:
  - Country, League and Match are all 51,958, which is 2 × 25,979;
  - Team is 103,916, which is 4 × 25,979;
  - only Player (11,075), Player_Attributes (183,978) and Team_Attributes (1,458) equal their max id.

  This is a fingerprint of how Mathien generated the ids (see §4). It is not data. **Treat it as chinook does: leave it out of `source.toml`.** A rebuild with the AUTOINCREMENT DDL will not reproduce these values, so it must not be compared.
- **Row counts.** The 7 data tables hold 222,796 rows: Match 25,979, Player 11,060, Player_Attributes 183,978, Team 299, Team_Attributes 1,458, Country 11, League 11.
- **Licence.** Kaggle lists the database as **ODbL 1.0** (recalled, not fetched; see §7). The underlying content (FIFA ratings, bookmaker odds, enetscores incidents) belongs to third parties.
- **Nature.** **Real data**, scraped and not anonymised: real matches, real players with names and birthdays, and real bookmaker odds. The player and team "attributes" are a video game's ratings, not measurements. It is neither generated nor course data, although a scraper's damage is visible (§4).

## 0.1 How Spider 2.0 uses it

Five questions use db `EU_soccer`. Only local219 has gold SQL; all five have exec_result CSVs.

| id | asks | gold SQL? | gold answer | reproduced |
|---|---|---|---|---|
| local218 | the median, over teams, of each team's best season goal total | no (CSV) | 48.000 | ✔ 48.0 over 299 teams [p4] |
| local219 | per league, the one team with the fewest wins (zero-win teams included; one team per league) | **yes** | 3 accepted CSVs (a, b, c) that differ only in how ties are broken | ✔ up to ties. The tied sets are Germany {Greuther Fürth, Arminia Bielefeld} at 4, Italy {Novara, Reggio Calabria, Pescara} at 6 and Portugal {Feirense, Penafiel, Trofense} at 5. Running the gold SQL here gives a fourth combination that equals none of the CSVs, because `ROW_NUMBER()` over ties depends on the query plan [p4] |
| local220 | the player in the most won matches and the player in the most lost matches (non-NULL lineup slots; draws excluded) | no (CSV) | Cristiano Ronaldo 199 wins; Gorka Iraizoz Moreno 107 losses | ✔ exactly, including CSV b's extra columns: 27 losses and 114 wins [p4] |
| local221 | the top 10 teams by wins | no (CSV) | FC Barcelona 234 … FC Basel 180 | ✔ all 10 rows, in order [p4] |
| local283 | the champion of each league-season on 3/1/0 points, with its league, country and points | no (CSV) | 88 rows | ✔ all 88 gold rows are champions here. There are 2 ties for first: Standard de Liège with Anderlecht (Belgium 2008/09, 77 points), and Manchester United with Manchester City (2011/12, 89). Gold kept one of each [p4] |

Every question reads only Match's scores and team ids, the lineup columns, and the names in Team, League, Country and Player. **None reads the XML, the odds or either attributes table.** Two saved queries are tie-sensitive: local219 (ROW_NUMBER) and local283 (ties for first). They need a deterministic tie-break, or a multiset comparison against "any tied team", before they can be saved queries (§7).

## 1. Inventory, keys, joins

Declared keys are `id INTEGER PRIMARY KEY AUTOINCREMENT` on every table, plus UNIQUE constraints on `Player.player_api_id`, `Player.player_fifa_api_id`, `Team.team_api_id`, `Match.match_api_id`, `League.name` and `Country.name`. FKs are declared but not enforced, so all of them are measured below [q1:key_uniqueness, q1:fk_orphans].

| Table | Rows | Key | Kind |
|---|---:|---|---|
| Match | 25,979 | id 1..25,979 dense; match_api_id unique; (league, season, stage, home team) unique | activity: one row per match, with score, lineups, XML incidents and odds |
| Player_Attributes | 183,978 | id 1..183,978 dense; (player_api_id, date) **not** unique: 183,142 distinct | dated attribute snapshots |
| Team_Attributes | 1,458 | id 1..1,458; (team_api_id, date) **not** unique: 1,457 distinct | dated attribute snapshots |
| Player | 11,060 | id 1..11,075 with 15 gaps; player_api_id and player_fifa_api_id unique; player_name **not** unique (163 names on 375 rows, at most 7 rows per name) [q2:player_name_dupes_count] | master |
| Team | 299 | id 1..51,606, sparse; team_api_id unique; team_fifa_api_id 288 non-NULL with 285 distinct; long name 296 distinct | master |
| League | 11 | id = country_id = Country.id | lookup |
| Country | 11 | id ∈ {1, 1729, 4769, …, 24558} | lookup |

Joins and orphans:
- These all have 0 orphans [q1:fk_orphans]:
  - Match → Country and League;
  - Match → Team, for home and away;
  - Player_Attributes → Player on `player_api_id`;
  - Team_Attributes → Team on both ids;
  - the 542,281 filled lineup slots → Player [q1:match_player_orphans].
- `Match.country_id` always equals its league's `country_id` (0 differ). Home is never the same team as away.
- **`Player_Attributes.player_fifa_api_id` is unreliable.** 49 rows point to no Player, and 212 rows (9 players) disagree with the player's own fifa id. Of those, 163 rows carry *another* player's fifa id [q1:fk_orphans, q2:pa_fifa_mismatch_summary]. It must be carried verbatim, not derived from the player ref.
- `Team_Attributes.team_fifa_api_id` always equals the team's own (0 differ), so it is **derivable** from the team ref.
- **Coverage.** Every player has attributes and appears in a lineup. Every team plays. 288 teams have attributes; **11 teams have none, and they are exactly the 11 with NULL `team_fifa_api_id`** [q1:coverage, q1:team_fifa_null].
- **The same club under two `team_api_id`s.** Widzew Łódź (8244/8024), Polonia Bytom (8031/8020) and Royal Excel Mouscron (9996/274581) each share one fifa id, with different short names [q1:team_fifa_dupes, q1:team_longname_dupes]. Questions that group by `team_long_name` merge them.
- **Derived or copied tables:** none. `match_view` is a view, not a table, so it has no `results/` table. `sqlite_sequence` is system data (§0).

## 2. Event catalogue

The source has no clock time: every date is `YYYY-MM-DD 00:00:00`, in 25,979, 183,978, 1,458 and 11,060 of 11,060 rows [q2:date_formats]. Kick-off times do not exist.

| # | Event | Owner | Time | Attributes | Source rows | Count |
|---|---|---|---|---|---|---:|
| E1 | `match_played` | league (ord = Match.id) | `Match.date`, natural (to the day) | match_id (i64 = Match.id), match_api_id, league_id (ref), season, stage, home_team_id / away_team_id (refs), home_team_goal, away_team_goal; 22 lineup refs (opt), 44 lineup coordinates X/Y (opt i64); 8 XML texts (opt text, verbatim); 30 odds (opt f64) | Match | 25,979 |
| E2 | `player_rated` | player (ord = Player_Attributes.id) | `Player_Attributes.date`, natural (a FIFA update) | attr_id (i64), player_fifa_api_id (i64 verbatim), overall_rating, potential, preferred_foot, attacking/defensive_work_rate (opt text), 33 skill columns (opt i64) | Player_Attributes | 183,978 |
| E3 | `team_rated` | team (ord = Team_Attributes.id) | `Team_Attributes.date`, natural | attr_id (i64), 8 numeric tactics (buildUpPlayDribbling opt), 3 positioning/line classes (cat). The 9 `…Class` columns of numeric tactics are derived (§3) | Team_Attributes | 1,458 |

**Business events: 211,415.**

Entities (4 tables, 11,381 rows). The created_at times all come from a rule:

| Entity | ext_id | created_at (rule) | Attributes |
|---|---|---|---|
| countries (11) | Country.id | the country's first match: 2008-07-18 … 2008-08-30 [p5] | name |
| leagues (11) | League.id | the league's first match, the same times | country_id (ref), name |
| teams (299) | team_api_id | min(first match, first Team_Attributes date). 51 teams are rated before they first play, so the first match alone would date a `team_rated` before its team exists [p5, q3:team_attr_before_first_match] | team_row_id (i64 = Team.id), team_fifa_api_id (opt), team_long_name, team_short_name |
| players (11,060) | player_api_id | the first Player_Attributes date: 2007-02-22 for 11,059 players, 2007-08-30 for 1. It is never after the player's first lineup (11,060 of 11,060) [q3:player_first_seen, q3:player_first_attr_dates] | player_row_id (i64 = Player.id), player_name, player_fifa_api_id, birthday (text verbatim) |

`players_snapshot` (11,060) carries **height and weight at N** as snapshot columns. They are sofifa's 2016 values on a player created in 2007, so by the contract's "when in doubt" rule they are snapshot columns. **Total log: 211,415 + 11,381 + 11,060 = 233,856 events.**

Snapshot **N = 2016-07-07**, the last Player_Attributes date. The last match is 2016-05-25 [q3:snapshot_dates_global].

What is **not** an event, and why:
- **Birthdays.** `birthday` (1967–1999) is an attribute, not `created_at`. A player enters the catalogue at his first FIFA rating, between 7.8 and 40.1 years after birth [q3:birthday_vs_first_attr].
- **XML incidents.** The 1,065,285 player refs and 917,815 `<value>` incidents inside the XML (goals, shots, fouls, cards, crosses, corners, possession) look like natural in-match events [p2]. They are **not** split out in v1:
  - they have only a minute (`elapsed`, `elapsed_plus`), and no kick-off time exists;
  - their child-tag order varies (34 orders for `goal` alone);
  - 5,653 refs point to players not in Player, and 4 are the text `Unknown player`.

  So E1 carries the eight XML texts verbatim (see §3 for the byte-exactness evidence). Splitting them out is a stage-2 option (§7).
- **Odds.** The 191,970 bookmaker quote triplets [p5] are pre-match prices, but with no time of their own. They ride on E1. A per-bookmaker `odds_quoted` event at the match date would be imposed, not natural.
- **Lineups** are pre-kick-off facts with no time of their own, so they ride on E1.
- **The match_view view and sqlite_sequence** produce no events.

How event-shaped the catalog is: E1, E2 and E3 are **natural**, a row per thing that happened on a real date, and they are 95% of the rows. Only the four masters' creation times are imposed by rule.

## 3. Rebuild rules and blockers to an exact round trip

1. **Results types** follow the stored classes (`apps/dataset/src/dataset/tables.py`, `column_types`):
   - **`Player.height` is declared INTEGER but holds REAL in all 11,060 rows** [p1], so it becomes `float64`, not int64.
   - The 30 odds columns are NUMERIC and hold integers (88,274 cells) mixed with reals [p1, p2], so they become `float64` and are not mixed.
   - **No column mixes text with numbers** (p1: every TEXT column is text or NULL, and every numeric column has no text). So `[results.mixed]` is empty.
2. **Derived columns.** Each is proved by a query with 0 differing rows, and `build.sql` computes it:
   - `Match.country_id` = League.country_id of `league_id` (0 differ) [q1:fk_orphans].
   - `Team_Attributes.team_fifa_api_id` = Team.team_fifa_api_id (0 differ) [q1:fk_orphans].
   - The 9 `…Class` columns of numeric tactics use a 3-band rule: ≤ 33 / 34–66 / ≥ 67 maps to Slow/Balanced/Fast, Little/Normal/Lots, Short/Mixed/Long, Safe/Normal/Risky, Deep/Medium/High, Contain/Press/Double and Narrow/Normal/Wide. There are 0 violations in each [q3:ta_class_rule_exact, q3:ta_class_thresholds].
     - **Exception:** where `buildUpPlayDribbling` is NULL (969 rows, every snapshot before 2014-09-19), the class is always `'Little'` [q3:ta_dribbling_null_class, q2:ta_dribbling_null_by_date].
     - The rule is `CASE WHEN x IS NULL THEN 'Little' WHEN x <= 33 … END`.
   - The three positioning/line classes (`buildUpPlayPositioningClass`, `chanceCreationPositioningClass`, `defenceDefenderLineClass`) have no numeric partner, so they are carried as `cat`.
   - `Player_Attributes.player_fifa_api_id` is **not** derivable (212 rows differ; §1). It is carried.
3. **Ids are not derivable from order. Carry each one.**
   - Match.id: rows are grouped by league in id order, with season ascending (0 breaks), but stage and date within a season are not in id order (261 and 5,725 breaks) [q1:match_id_order].
   - Player.id has 15 gaps [q2:player_id_gaps].
   - Team.id is sparse, up to 51,606 (§4).
   - Player_Attributes.id groups each player's rows in a block, except player 32968, which has 2 blocks [q2:pa_player_with_two_blocks]. Within a block the dates are descending, with 38 breaks [q1:pa_order].

   So `match_id`, `attr_id` and `*_row_id` ride on the events and entities.
4. **The XML text is byte-exact as text.**
   - It is ASCII only. Every value parses.
   - Re-serialising it with ElementTree gives back the same bytes for **14,216 of 14,217** non-NULL values in each of the 8 columns.
   - The one exception is **Match 3639**, whose 8 values are pretty-printed with tabs and newlines and end in a newline [p2].
   - The NULL pattern is all-or-nothing: either all 8 columns are NULL (11,762 matches) or none is (14,217).
   - The empty element `<goal />` (and its 7 siblings) is distinct from NULL: there are 993 empty goal values, and 441–5,798 in the other columns [p2].

   Carry the values as `opt(text())`, verbatim. NULL, `<x />` and Match 3639's whitespace all survive. **XML is 268,858,266 characters**, which is 90% of the file [p5]. It dominates the log size (§7).
5. **Odds are exact as `f64`.**
   - All 575,910 cells are positive. Their shortest repr has 0 decimals in 88,274 cells, 1 in 295,983, 2 in 191,558 and **3 in 95** (for example PS odds) [p2].
   - JSON shortest-repr floats read back exactly, and a value compares by value with its integer-class twin (2 = 2.0).
   - Integer thousandths ÷ 1000 would also be exact, but there is no reason to use them: they are not money.
   - A bookmaker's H/D/A prices are always all NULL or all present (0 partial) [p2].
6. **`Player.height` is exact as `f64`.** The 20 distinct values are inches × 2.54 printed to 2 decimals (157.48 … 208.28) [q2:height_values].
   - `inch * 2.54` in double reproduces only 9,664 of 11,060: 167.64 and 185.42 differ in the last bit [p2].
   - Carry the value as `f64` verbatim, or as integer hundredths ÷ 100 (11,060 of 11,060 are exact hundredths).
   - `weight` is integer pounds.
7. **Times.**
   - All four date columns are `YYYY-MM-DD 00:00:00`, valid under `date()` [q2:date_formats]. Read them as UTC midnight with `iso_time(text, '%Y-%m-%d %H:%M:%S')`, and format them back with `strftime('%Y-%m-%d %H:%M:%S')`.
   - `birthday` is an attribute, so carry it as text verbatim.
   - There are no time-zone suffixes and no `'\N'` (p1: 0 `'\N'` and 0 `''` anywhere).
8. **Duplicates.**
   - **836 Player_Attributes rows are all-NULL twins.** Each has a same-player, same-date row with real ratings: 835 groups covering 1,671 rows [q2:pa_duplicate_player_date, q2:pa_null_rating_rows]. 735 of them are on 2007-02-22.
   - They are kept as `player_rated` events with NULL payloads. Their distinct `attr_id` keeps the multiset exact.
   - Team_Attributes rows 860 and 861 are identical except for `id` [q2:ta_dup].
9. **Rows without time.** Only entities lack time, and their rules are in §2. No invented business times are needed.

**Verdict:** exact round trip **feasible**, with caveats. Every column is text verbatim, an integer, a shortest-repr f64, or a proved derivation. The caveats:
- the log's size, because of the XML;
- the two tie-sensitive saved queries;
- `match_view`, which `refdata rebuild` will not recreate. The saved queries must inline it, as local219's gold does.

## 4. Measured quirks

- **Generator fingerprints in the ids.**
  - **Country.id = League.id = the id of that country's first Match**, in 11 of 11 (1, 1729, 4769, …): Belgium's 1,728 matches are ids 1–1,728 [q2:country_id_is_first_match_id].
  - Team.id is sparse (1–18, then 614, 1034, …, 51606), and equals the team's first match id only once [q2:team_id_vs_first_match_id]. Together with `sqlite_sequence` = 2× and 4× the match count, this suggests the ids are positions in an intermediate Match-shaped list. The construction is unverified (§7).
- **Scraper damage in the work rates** [q2:work_rate_values]:
  - `attacking_work_rate` is `medium/high/low` in 176,462 rows, but also holds the string **`'None'`** (3,639, distinct from 3,230 NULLs) and fragments: `norm` 348, `y` 106, `le` 104, `stoc` 89.
  - `defensive_work_rate` holds digits `0`–`9` (2,232), `_0` 2,394, `o` 1,550, `ormal`, `es`, `ean` and `tocky`: column-shifted pieces of "normal", "yes", "lean" and "stocky".
  - All of them must be carried verbatim as text, not as `cat(low, medium, high)`.
- **A NULL block of 7 late-added skills.** `volleys`, `curve`, `agility`, `balance`, `jumping`, `vision` and `sliding_tackle` are NULL together in 1,877 rated rows, all dated 2007-02-22 … 2010-02-22 [q2:pa_partial_null, q2:pa_partial_null_dates]. These are skills older FIFA editions did not have.
- **Incomplete seasons** [q3:matches_per_league_season, q3:double_round_robin_check]:
  - **Belgium 2013/14 has 12 of 240 matches**: 4 teams over 6 stages, 2014-03-29 … 05-03, which looks like the play-off round only [q3:belgium_2013]. This is why local283's 2013/14 Belgian "champion" is KV Oostende on 14 points.
  - Belgium 2009/10 has 210 matches with 15 teams, Italy 2011/12 has 358 and 2014/15 has 379, and Switzerland 2011/12 has 162.
  - Scotland plays 3–4 meetings per pair, with 228 matches for 12 teams, and Switzerland 4 (180 for 10). So (home, away, season) is not a key: 24,509 distinct out of 25,979 [q1:key_uniqueness, q3:pair_repeat_in_season].
- **Stage is not chronological.**
  - In 64 of 3,132 consecutive-stage pairs, the later stage comes earlier [q3:stage_vs_date].
  - One stage spans 218 days, because of postponed matches [q3:stage_date_spread].
  - No team ever plays twice on one day, or in two leagues in a season, and no team changes league [q3:team_two_matches_same_day, q3:team_two_leagues_same_season, q3:teams_change_league]. Promotion and relegation are therefore visible only as teams that are absent in some seasons.
- **Lineup errors.**
  - A player appears twice in one match in 14 cases, and on both sides in 13 [q3:player_in_both_lineups_or_twice].
  - Coordinates and player ids are NULL independently: 722 matches have a player but no coordinates, and 125 have coordinates but no player [q3:coords_without_player].
  - The goalkeeper sits at (1, 1) in 24,146 matches, at (0, 0) in 11 and at (2, 3) in 1 [q3:gk_coords].
  - 758 matches have no lineup at all, and 2,240 lack one slot [q3:lineup_null_pattern].
- **The XML is incomplete.**
  - It is present for 14,217 matches. Coverage is full for England, Germany and Spain; nearly full for Italy and France from 2012; and almost none for Belgium, Poland, Portugal, Scotland and Switzerland [p2].
  - The goal incidents, with `dg` (disallowed) skipped and own goals credited to the other side, reproduce the score in 13,476 matches and **differ in 741** [p2]. The score is therefore its own fact, never derived from the XML.
  - One team ref in the XML is neither the home nor the away team [p2].
- **Odds.** The B365 overround is 1.017–1.126, mean 1.062 [p2]. 3,382 matches have no odds from any bookmaker [p5].
- **Ratings.** potential < overall_rating in 1,071 rows [q3:pa_rating_vs_potential]. 836 rows have no rating at all (the NULL twins above).

## 5. Distributions to fit (stage 2)

| Quantity | Value |
|---|---|
| match arrivals | season-shaped: Aug–May; June has 23 matches and July 218 [q3:month_mix]. Weekdays: Sat 11,724, Sun 9,566, then Fri 1,561, Wed 1,432 and Mon 885 [q3:weekday_mix]. Matches per date: 1–40+, bimodal, from weekday singletons and weekend rounds [q3:matches_per_date] |
| league schedule | double round robin of 16–20 teams (18–38 stages). Scotland: 12 teams, 38 rounds; Switzerland: 10 teams, 36 rounds [q3:matches_per_league_season] |
| result mix | home 45.87%, draw 25.39%, away 28.74% [q3:result_mix]. By league, home wins run from 41.7% (Scotland) to 48.8% (Spain) [p5] |
| goals | home mean 1.545 (var 1.683), away 1.161 (var 1.304): near Poisson, slightly over-dispersed. P(0–0) = 0.076. Total goals: 2 is the mode (6,351); max 12 [p5, q3:goals_dist] |
| odds | B365 overround mean 1.062. The favourite wins 54.3% (home favourite, 16,408 matches) or 50.7% (away favourite, 6,154). Coverage per bookmaker runs from 11,168 (PS) to 22,592 (B365) matches [p5] |
| player snapshots | 2–56 per player, median 16 [q2:pa_rows_per_player, p5]. Gaps: 0 d 836 (the twins), 1–31 d 47,215, 32–92 d 32,061, 93–183 d 44,460, 184–366 d 37,674, > 366 d 10,672 [q3:pa_gap_days] |
| rating drift | the change between consecutive snapshots is 0 in 58.8%; p1 −4, p10 −1, p90 +2, p99 +8. Overall rating p50 69 (p1 51, p99 84); potential − rating p50 4, p99 19 [p5] |
| team tactics | 6 yearly snapshots; 189 teams have all 6 and 14 have 1 [q2:ta_per_team]. The classes follow the 33/66 band rule |
| players | birth year p50 1987 (p1 1974, p99 1997); height p50 182.88 cm on an inch grid; weight p50 168 lb; right foot 75.6% [p5] |
| lineup appearances | per player p50 30, p90 126, max 300 [p5] |
| team seasons | 91 teams play all 8 seasons and 52 play only 1 [p5] |

## 6. simkit mapping sketch

```python
p.entity("countries", key="country_id", cols={"ext_id": text(), "name": text()})
p.entity("leagues", key="league_id", cols={"ext_id": text(), "country_id": ref("countries"), "name": text()})
p.entity("teams", key="team_id", doc="ext_id = team_api_id",
         cols={"ext_id": text(), "team_row_id": i64(doc="Team.id, sparse"), "team_fifa_api_id": opt(i64()),
               "team_long_name": text(), "team_short_name": text()})
p.entity("players", key="player_id", doc="ext_id = player_api_id; height/weight in players_snapshot",
         cols={"ext_id": text(), "player_row_id": i64(), "player_name": text(), "player_fifa_api_id": i64(),
               "birthday": text(doc="'YYYY-MM-DD 00:00:00' verbatim"),
               "height": f64(doc="snapshot; cm, inch grid"), "weight": i64(doc="snapshot; lb")})
lineup = {f"{s}_player_{i}": opt(ref("players")) for s in ("home", "away") for i in range(1, 12)}
coords = {f"{s}_player_{a}{i}": opt(i64()) for s in ("home", "away") for a in "XY" for i in range(1, 12)}
xml = {c: opt(text(doc="XML verbatim")) for c in ("goal", "shoton", "shotoff", "foulcommit", "card", "cross", "corner", "possession")}
odds = {f"{b}{r}": opt(f64()) for b in ("B365","BW","IW","LB","PS","WH","SJ","VC","GB","BS") for r in "HDA"}
p.event("match_played", cols={"league_id": ref("leagues"), "match_id": i64(), "match_api_id": i64(),
        "season": text(), "stage": i64(), "home_team_id": ref("teams"), "away_team_id": ref("teams"),
        "home_team_goal": i64(), "away_team_goal": i64(), **coords, **lineup, **xml, **odds})
skills = {c: opt(i64()) for c in ("overall_rating", "potential", "crossing", ..., "gk_reflexes")}   # 35 ints
p.event("player_rated", cols={"player_id": ref("players"), "attr_id": i64(), "player_fifa_api_id": i64(doc="verbatim; 212 rows differ from the player's"),
        "preferred_foot": opt(text()), "attacking_work_rate": opt(text(doc="dirty; verbatim")),
        "defensive_work_rate": opt(text(doc="dirty; verbatim")), **skills})
p.event("team_rated", cols={"team_id": ref("teams"), "attr_id": i64(),
        "buildUpPlaySpeed": i64(), "buildUpPlayDribbling": opt(i64()), "buildUpPlayPassing": i64(),
        "chanceCreationPassing": i64(), "chanceCreationCrossing": i64(), "chanceCreationShooting": i64(),
        "defencePressure": i64(), "defenceAggression": i64(), "defenceTeamWidth": i64(),
        "buildUpPlayPositioningClass": cat("Free Form", "Organised"),
        "chanceCreationPositioningClass": cat("Free Form", "Organised"),
        "defenceDefenderLineClass": cat("Cover", "Offside Trap")})
```

Ingest:
- `match_played owner=league_id ord=match_id`, ORDER BY date, id. Time: `iso_time(date, '%Y-%m-%d %H:%M:%S')`.
- `player_rated owner=player_id ord=attr_id`, ORDER BY date, id.
- `team_rated owner=team_id ord=attr_id`, ORDER BY date, id.
- The entity blocks give `created_at` explicitly by the §2 rules:
  - players: `min(PA.date)`;
  - teams: `min(first match, first TA)`;
  - leagues and countries: the first match.

  The rule times tie with the first business event, and creation sorts first.
- Ids: `CAST(x AS TEXT)` for ext_ids and refs, as in sakila.

`build.sql` (DuckDB, over the log views):
- **Match:** one row per E1.
  - `country_id` comes from leagues → countries.ext_id.
  - The refs map back to ext_ids (`team_api_id` and `player_api_id`).
  - `date` = `strftime(event_time, '%Y-%m-%d %H:%M:%S')`.
  - XML and odds pass through unchanged.
- **Player_Attributes:** one row per E2. `player_api_id` comes from the player ref, `player_fifa_api_id` from the payload, and `date` is formatted as above.
- **Team_Attributes:** one row per E3.
  - `team_fifa_api_id` and `team_api_id` come from the team entity.
  - The 9 classes are rebuilt by the 33/66 CASE rule, with NULL dribbling giving `'Little'`.
- **Player:** creation joined with `players_snapshot` (height, weight). `id` = `player_row_id`.
- **Team:** `id` = `team_row_id`.
- **Country and League:** `id` = ext_id cast to integer.
- **`sqlite_sequence` and `match_view`** are not rebuilt, and the saved queries inline the view.

Stage-2 owners:
- **League shard:** generates each season's double round robin (or 3–4 meetings for Scotland and Switzerland) on weekend-heavy dates. It draws goals from a team-strength Poisson model, and odds from the same strengths plus a margin of about 6%.
- **Player:** rating snapshots on FIFA update dates, with drift as in §5.
- **Team:** 1 tactics snapshot a year.

## 7. Open questions and risks

- **Log size.** Carrying the XML verbatim puts about 269 M characters into E1 payloads [p5]: a ~300 MB log for 234k events. That is the hardest practical cost.
  - The options are to keep it (exact, simplest), or to move the XML to a side table of `match_incidents_reported` events.
  - Splitting each XML into incident events is **not** recommended for an exact rebuild. Their times would be imposed (date + minute, with no kick-off), and the varying child order would have to be carried per incident.
  - No Spider question uses the XML or the odds. A slimmer dataset `eusoccer_core`, without the XML and odds columns, would not meet "results/ holds every source table". Decide here.
- **Tie-sensitive saved queries.** local219's gold SQL picks a tied team with `ROW_NUMBER()` and no tie-break. Here it returned a combination that matches none of the three accepted CSVs [p4], so on the rebuilt file it can differ again. local283 has 2 ties for first. Before saving either query, add a deterministic tie-break (for example `ORDER BY wins, team_api_id`), or record all tied rows.
- **`match_view`.** `refdata rebuild` copies only table DDL, so a saved query that names `match_view` fails on the rebuilt file. Inline it, as local219's gold does. Alternatively, let `build.sql` emit views; that is not supported today.
- **Licence.** ODbL 1.0 on Kaggle is recalled, not fetched. The content is third-party (EA FIFA ratings, bookmaker odds, enetscores). Confirm before redistributing rows; fitting statistics should be fine.
- **Id construction.** Country.id = first Match.id is proven. Team.id's sparse values and `sqlite_sequence`'s 2× and 4× counts are unexplained. They are carried verbatim, so this is not a rebuild risk, but stage 2 cannot generate them.
- **Snapshot columns.** I classed only height and weight as snapshot columns. Team and player names could also have changed during 2008–2016 (for example the duplicated-club pairs), but the source has one value per row, so they stay on creation. Revisit if a law flags them.
- **Creation rules.** These are imposed, not data:
  - players at the first FIFA rating;
  - teams at min(first TA, first match);
  - leagues and countries at the first match.

  Stage 2 must not learn them as arrival times.
- **Dirty work-rate text and the all-NULL twin rows** are scraper artefacts. Stage 2 should either reproduce them deliberately or record them as deviations; a `cat(low, medium, high)` law would be broken by 4,286 attacking and 6,823 defensive values that are neither NULL nor low/medium/high [q2:work_rate_values].

---

**Summary**
- Exact round trip: **yes, with caveats.** The XML is byte-exact as text (Match 3639's pretty-printing included), the odds and heights are shortest-repr f64, and Match.country_id, Team_Attributes.team_fifa_api_id and the 9 tactic classes are proven derived.
- Proposed dataset name: **`eusoccer`**.
- 3 event types (`match_played`, `player_rated`, `team_rated`) plus 1 snapshot event (`players_snapshot`); 4 entities (countries, leagues, teams, players); 233,856 events.
- Event shape: **natural.** Matches and the dated FIFA rating snapshots are real dated events, 95% of the rows. Only the masters' creation times are imposed by rule.
- Hardest blocker: the 269 M characters of XML in the match payloads (log size), with the tie-sensitive saved queries (local219, local283) and the missing `match_view` as the correctness risks.
