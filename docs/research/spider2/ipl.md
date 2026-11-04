# IPL (Spider 2.0-lite): reverse-engineered event log

Source: `data/spider2/IPL.sqlite` (12 MB), opened read-only. `scripts/ipl/rq.py` copies the file into an in-memory SQLite and runs named blocks; the file itself is never written.

Every number below comes from one of these scripts:
- a named query in `scripts/ipl/q*.sql`;
- `p1_columns.py` (per-column storage classes, NULLs, `''`, whitespace, ranges);
- `p2_time_rule.py` (checks the per-ball time rule).

The raw outputs are in `scripts/ipl/out_*.txt`. A reference such as `[q3:ball_coverage]` means file `q3_balls.sql`, block `-- name: ball_coverage`. Gold SQL and answer CSVs are in `scripts/ipl/gold/`.

## 0. What this catalog is

- **Dataset.** Ball-by-ball records of the **Indian Premier League, seasons 1–9 (2008-04-18 .. 2016-05-29)**: 567 matches, 134,703 deliveries [q1:row_counts, q1:matches_per_season].
- **Likely lineage.** The Kaggle **"IPL SQLite Database"** by HarshVardhan (`harsha547/ipldatabase`), described as "577 matches, players & teams attributes". That page could not be opened, so the link is **unverified**. The evidence:
  - The ball data is split into `ball_by_ball`, `batsman_scored`, `extra_runs` and `wicket_taken`, all keyed by (match, over, ball, innings). That is a normalised SQLite layout, not the one-row-per-ball Cricsheet CSV.
  - Lookup ids have been resolved into text: `venue`, `country_name`, `batting_hand`, `bowling_skill`, `kind_out`, `extra_type`, `role`, `toss_decision`, `win_type` and `outcome_type` are words, not ids. Spider's port evidently joined the source's lookup tables and dropped them. There is no season, venue, umpire or city table.
  - Match ids (335987 .. 981024) are in ESPNcricinfo's id range.
- **What was dropped, measured.** 567 + 1 orphan = 568 matches have balls, against the 577 the source page states. All 567 match rows are `outcome_type = 'Result'` with `win_type` ∈ {runs, wickets} [q1:cats_match]: ties, super overs (innings 3/4) and no-results are absent. **No column has a single NULL** [p1_columns]. Row-wise NULL dropping would explain the missing matches, the missing team 1, player 35 and match 419136 (§1), but that is a hypothesis.
- **Row counts** [q1:row_counts]: player 468, team 12, match 567, player_match 12,495, ball_by_ball 134,703, batsman_scored 131,259, wicket_taken 6,618, extra_runs 7,349. Total 293,471.
- **Licence.** Unstated in the Spider2 metadata. The Kaggle page's licence was not checked.
- **Nature.** **Real** sports data: real players, real scores, real dates. It is not anonymised or generated.

### 0.1 How Spider 2.0 uses it

11 questions use db `IPL`. Gold SQL exists only for local022 and local023. Every question has one or more exec_result CSVs (`_a`, `_b`, …), and an answer may match any of them.

| id | asks | gold SQL? | reproduced |
|---|---|---|---|
| local020 | lowest bowling average per wicket | no | ✔ AC Gilchrist, 0 runs for 1 wicket [q5:local020] |
| local021 | average career runs of strikers with any > 50 in a match | no | ✔ 1130.516129 [q5:local021] |
| local022 | ≥ 100 runs in a match for the losing team | yes | ✔ the same 7 names [q5:local022_gold_sql] |
| local023 | top 5 average runs per match in season 5 | yes | ✔ the gold SQL gives CH Gayle 52.357 …; the CSV's extra `batting_average` column (runs / dismissals: 61.0833 …) also reproduced [q5:local023_csv_variant] |
| local024 | top 5 countries by the mean of player averages | no | not attempted (2 CSVs disagree after the top row) |
| local025 | per-match top over (bat + extras), its bowler, the mean of the maxima | no | not attempted (CSV: 19.426) |
| local026 | top 3 bowlers among each match's most expensive over | no | ✔ P Parameswaran 501252 37; RS Bopara 419144 33; P Awana 734052 33 [q5:local026] |
| local228 | per season top 3 run scorers and top 3 wicket takers, paired | no | ✔ all 27 rows equal `local228_a.csv` [q5:local228] |
| local229 | top partnership per match | no | not attempted |
| local258 | bowler wickets, economy, strike rate, best figures | no | not attempted |
| local259 | full career line per player | no | not attempted |

Every question joins the four ball tables on the 4-column key, and most join to `player_match` and `match` as well. The round trip must keep that key and the absent rows exactly as they are. For example, a wide with no `batsman_scored` row must stay absent, not become `runs_scored = 0`, or `COUNT(*)`-based "balls faced" changes.

## 1. Inventory, keys, joins

Declared PKs hold, with 0 duplicates [q2:pk_unique]. No FKs are declared. The table below gives the measured joins.

| Table | Rows | Key | Kind |
|---|---:|---|---|
| player | 468 | player_id 1..469; **35 is missing** [q1:player_id_gaps] | entity (static biography) |
| team | 12 | team_id 2..13; **team 1 is missing** [q1:team_rows] | entity |
| match | 567 | match_id | match lifecycle: fixture, toss, result |
| player_match | 12,495 | (match_id, player_id) | team sheet |
| ball_by_ball | 134,703 | (match, over, ball, innings) | delivery |
| batsman_scored | 131,259 | same key | delivery outcome: runs off the bat |
| extra_runs | 7,349 | same key | delivery outcome: extras |
| wicket_taken | 6,618 | same key | delivery outcome: dismissal |

Orphans. All of them are real refs to rows missing from their tables:
- **Team 1** is used 16,703 times across match teams, `player_match` and `ball_by_ball` [q1:team_ids_used_not_in_team]. It is in 13–17 matches every season, and plays 51 matches at Eden Gardens [q6:team1_home_venues], so it is Kolkata Knight Riders. The name is not in the source.
- **Player 35** is used in 124 `player_match` rows, as striker 1,312 times, non-striker 1,386, bowler 1,727, player_out 67 and man of the match 7 [q1:player_ids_used_not_in_player]. His teams run RR 2008–09, Kochi 2011, CSK 2012–15 and Gujarat 2016 [q2:player_35_usage], which fits R. Jadeja. That identification is unverified.
- **Match 419136** has 250 ball rows, 242 batsman_scored, 15 extra_runs, 13 wicket_taken and 22 player_match rows, but no `match` row [q1:match_ids_not_in_match]. It is team 6 (DD) 177/4 against team 1 (KKR) 137/9 [q6:m419136_totals]. Its id falls between 419135 (2010-03-28) and 419137 (2010-03-30), and no source match is on 2010-03-29 [p2].
- **One `extra_runs` row has no `ball_by_ball` row:** 335987 innings 1, over 1, ball 1, a leg-bye of 1. It is the first delivery of the first match. That match's ball keys in innings 1 start at ball 2 [q3:er_without_ball, q3:ball_id_gap_detail]. This is the only ball-id gap in the file. `batsman_scored` and `wicket_taken` have 0 rows without a ball [q2:child_without_ball].
- Player 448 (SS Mundhe) appears nowhere else [q4:unused_player].

How the four ball tables cover a delivery [q3:ball_coverage]:

| has bat-runs row | has extras row | has wicket row | deliveries |
|:-:|:-:|:-:|---:|
| ✔ | – | – | 120,767 |
| ✔ | – | ✔ | 6,588 |
| ✔ | ✔ | – | 3,897 |
| ✔ | ✔ | ✔ | 7 |
| – | ✔ | – | 3,421 |
| – | ✔ | ✔ | 23 |

A delivery without a `batsman_scored` row is always a wide: 3,444 of the 4,091 wides [q3:no_bs_extra_types]. The other 647 wides do have a row, and 645 of those record 0 [q2:bs_by_extra_type]. So **the presence of a runs row is data**, not a function of the extra type.

Other joins:
- Every `player_match` team is one of the match's two teams. Every match has 2 sides [q2:pm_team_in_match, q2:teams_per_match_pm].
- The batting and bowling teams are always the match's two teams and never equal [q2:bbb_teams_vs_match].
- `match_winner` and `toss_winner` are always one of the two teams, and the man of the match always played [q2:winner_in_match, q2:motm_in_match].
- A delivery's striker, non-striker and bowler are all in the team sheets except on 178 / 178 / 169 deliveries [q2:ball_players_in_pm]:
  - 169 come from three mislabelled innings (§4);
  - 9 come from match 501274, where team 1's sheet has 10 players and its opener, player 40, is missing from it [q4:m501274_not_in_pm, q4:side_10_players].

  Every `player_out` is the striker or the non-striker of that delivery [q2:ball_players_in_pm].

**No table is a copy of another, and none is derived** (§3).

## 2. Event catalogue

The catalog is a **natural event stream at match grain and ball grain**. The order within a match is natural: innings, then `over_id`, then `ball_id`. **The time of day is not**: the source has dates only, so every intraday time comes from the rule below.

**Time rule** (checked by `p2_time_rule.py`):
- A match starts at **20:00** on `match_date`. On the 164 days that have two matches, the lower `match_id` starts at **16:00** [p2]. Times are stored as UTC labels, following the source-wall-clock convention.
- **Match 419136** is placed on **2010-03-29**: it has no match row, and the day between its id neighbours is free [p2].
- **Deliveries:** the union of the four ball tables' keys gives 134,704 deliveries. They are numbered k = 1..n per innings, in (over, ball) order.
  - `t = start + (innings − 1) × 110 min + (k − 1) × 40 s`
  - The longest innings has 134 deliveries, about 87 min, so innings 1 never runs into innings 2.
  - No two deliveries share a time.
- **Before the start:** the fixture, toss and team sheet are at start − 30 min, in that order by `ord`.
- **Result:** at the last delivery + 5 min.
- **Checks:** no match crosses midnight, and no 16:00 match ends after the 20:00 match's toss (0 cases) [p2].
- **N = 2016-05-29 23:17:00**, the last result [p2].

| # | Event | Owner | Time | Attributes | Source rows | Count |
|---|---|---|---|---|---|---:|
| E1 | `match_scheduled` | match_id | rule: start − 30 min (its date is `match_date`) | match_id, team_1 (ref), team_2 (ref), season_id, venue | match | 567 |
| E2 | `toss_decided` | match_id (ord after E1) | = E1 | toss_winner (ref), toss_decision | match | 567 |
| E3 | `player_named` | match_id (ord = player_id) | = E1 | player_id (ref), team_id (ref), role | player_match | 12,495 (22 are match 419136, timed by the 2010-03-29 rule) |
| E4 | `innings_started` | match_id (ord = innings) | rule: first delivery − 0 | innings_no, team_batting (ref), team_bowling (ref) | distinct (match, innings) in ball_by_ball | 1,136 |
| E5 | `ball_bowled` | match_id (ord = innings·10⁴ + over·100 + ball) | rule above | innings_no, over_id, ball_id; striker, non_striker, bowler (opt ref); striker_batting_position (opt); teams_swapped (0/1); has_ball_row; runs_scored (opt); extra_type, extra_runs (opt); player_out (opt ref), kind_out (opt) | union of the 4 ball tables | 134,704 |
| E6 | `match_completed` | match_id | rule: last delivery + 5 min | match_winner (ref), win_type, win_margin, outcome_type, man_of_the_match (ref) | match | 567 |

**Total events: 150,036.**

Why E5 is one event per delivery, with optional parts, and not four events:
- A delivery is the natural atom, as in Cricsheet: runs, extras and wicket are its outcome, not later happenings.
- A NULL in E5 means "no row in that table". The source has no NULLs at all, so this encoding is lossless.
- The four-table split is the alternative: 279,929 events, 1:1 with the tables, and also exact.

**Entities** (2 types, 482 rows):
- **`players` (469):** 468 rows plus one placeholder for id 35, which has NULL attributes and `listed = 0`.
  - created_at = 00:00 on the date of first appearance in a team sheet. No player is in ball data before his first sheet [q6:first_appearance_in_bbb_before_pm].
  - The unused player 448 takes the catalog start, 2008-04-18.
- **`teams` (13):** 12 rows plus a placeholder for id 1 (`listed = 0`). created_at = 00:00 of the team's first match.
- Player and team attributes (`dob`, hand, skill, country, name) are static biography, so **no snapshot columns** are needed.

What is **not** an entity or event, and why:
- **Match** is not an entity. It is a lifecycle (E1, E2, E6) owned by `match_id`, as the flights are in `airlines`.
- **Season** (1..9) and **venue** (35 strings) have no table. They are attributes of E1.
- **Innings** is E4, because the batting side is fixed per innings (§3.3). Over-level facts such as the bowler are not separate events: 16 overs change bowler mid-over [q3:bowler_per_over].
- **Fielders**, umpires and the per-ball wall clock do not exist in the source.

## 3. Rebuild rules and blockers to an exact round trip

1. **Integers and text only.** There is no REAL column and no NULL anywhere, and no `''`, `'\N'` or padded text [p1_columns]. Every value rebuilds verbatim.
2. **Dates.** `match_date` and `dob` are valid `YYYY-MM-DD` in every row [q1:date_formats].
   - `match_date` = `strftime('%Y-%m-%d', E1.event_time)`. This is exact because start − 30 min is 15:30 or 19:30 on the same day.
   - `dob` is carried as text, or as a `ts` at midnight. Both are exact.
3. **Batting and bowling teams are not constant per innings.** In 3 matches the innings-2 deliveries flip between the two labels:

   | match | correct label | wrong label |
   |---|---:|---:|
   | 392202 | 48 | 47 |
   | 392207 | 52 | 68 |
   | 419119 | 49 | 54 |

   The strikers on all those balls belong to one side [q3:mixed_team_innings, q4:mixed_striker_team, q4:mixed_overs_shared].
   - **Rule:** E4's team_batting is the strikers' team from `player_match`, and `team_bowling` is the other side. That holds with 0 exceptions in the other 1,133 innings [q2:innings_batting_team_constant, q2:bbb_teams_vs_match].
   - E5 has `teams_swapped = 1` on the **169** mislabelled deliveries (47 + 68 + 54). The view swaps both columns back.
   - Carrying both teams on every E5 is the trivially exact fallback.
4. **Absent rows are data:**
   - `batsman_scored` = E5 where `runs_scored IS NOT NULL` (131,259);
   - `extra_runs` = E5 where `extra_type IS NOT NULL` (7,349);
   - `wicket_taken` = E5 where `kind_out IS NOT NULL` (6,618);
   - `ball_by_ball` = E5 where `has_ball_row = 1` (134,703). The one leg-bye at 335987/1/1.1 has no ball row, so its striker and bowler are NULL in the log.
5. **Orphan refs.** The refdata rule "an unmatched ref is an error" fails on team 1, player 35 and match 419136.
   - **Proposal:** placeholder entities with `listed = 0` for team 1 and player 35. The `team` and `player` views filter on `listed = 1`.
   - Match 419136 needs no placeholder: `match_id` is an owner value (`i64`), not a ref. It simply has no E1, E2 or E6, so `match` rebuilds to 567 rows while its balls and sheet rebuild.
   - **Alternative:** keep player and team columns as `i64` instead of `ref`. This is simpler, but loses ref checking in stage 2.
6. **Not derivable, so carried.**
   - `win_type`, `win_margin` and `match_winner` disagree with the scorecard in 22 matches [q7:result_vs_score]. These are rain-shortened (D/L) games, such as 336027 with 11 v 8 overs, plus ones whose ball data is incomplete. For example, 980992 sums to 244 against the recorded 144-run margin over 104.
   - The wicket margin does equal 10 − wickets in all 307 chases [q4:wickets_margin], but carry it anyway for uniformity.
   - `striker_batting_position` is constant per (match, innings, striker) and unique within an innings [q3:batting_position_constant, q3:batting_position_unique_in_innings]. It is not a simple first-appearance rank (1,723 of 8,493 differ [q3:batting_position_rule]), so carry it on E5. It could move to a `batter_came_in` event later.
7. **Times the source lacks:** all intraday times, plus match 419136's date. Both come from the rule in §2 and cannot affect any table, because only dates are stored.

**Verdict:** exact, with caveats. The caveats are the placeholder entities and the 169-row `teams_swapped` flag. There are no floats and no text-format traps.

## 4. Measured quirks

- **Mislabelled innings:** 3 matches, 169 deliveries (§3.3). They are 2009-04-27, 2009-04-30 and 2010-03-17 [q4:mixed_matches_meta].
- **Missing first ball** of the whole file, 335987 1.1 innings 1 (§1). This is a classic "first data row lost" fingerprint.
- **The missing rows:** team 1, player 35 and match 419136's `match` row. 9 matches against the source's stated 577 (ties, super overs and no-results). The team sheet of 501274 / team 1 has 10 players [q4:side_10_players].
- **Captains:** 2 sides have no `Captain*` role, both in 501274 and 829762. Side 829762 / 2 has two captains: player 8 as `Captain` and player 88 as `CaptainKeeper` [q4:sides_no_captain_or_2].
- **Over structure** [q3:legal_balls_per_over]:
  - legal balls per over, which is wides and no-balls excluded: 6 in 21,489 overs;
  - fewer than 6 in 336 overs (innings ends);
  - **7 in 3 overs**, a scorer error: 335999/2/11, 392203/2/11 and 419160/1/19 [q4:legal_7_overs];
  - 0 in 4 overs that consist of a single wide [q4:legal_0_overs].

  ball_id runs to 9 [q3:ball_id_per_over].
- **Bowlers.** No bowler bowls two consecutive overs, and none bowls more than 4 in an innings [q3:consecutive_overs_same_bowler, q3:bowler_overs_max]. Both are the laws of the game, and they hold.
- **Strike rotation obeys the laws** [q3:striker_rotation_rule]:
  - Within an over, an odd run total swaps the ends in 43,398 of 43,423 cases and an even total keeps them in 64,012 of 64,026.
  - At the end of an over the ends swap, unless the total is odd.
  - 51 exceptions remain out of 127,173 cases, an error of 4·10⁻⁴.
- **Wides of 5:** 182 rows, which are wide + 4 byes [q1:cats_extra]. **Penalty:** 1 row of 5.
  - 5-run no-balls occur 6 times.
  - Bat runs of 5 occur 41 times, and one leg-bye delivery has 6 bat runs [q2:bs_by_extra_type]. These are scorer artefacts; keep them.
- **Dismissals** [q1:cats_kind_out]:
  - caught 3,894, bowled 1,234, run out 677, lbw 393, stumped 219, caught and bowled 184;
  - retired hurt 8, hit wicket 8, obstructing the field 1.
  - Stumpings happen on wides 18 times, and run-outs on wides 7 times [q4:wicket_on_wide_kinds].
  - No one is dismissed twice, and no dismissed batter bats again [q3:player_out_twice, q3:batter_after_out].
- **Id versus date.** `match_id` is not in date order: 16 inversions within seasons [q1:match_id_date_inversions]. Row order is key order in every table [q1:rowid_order].
- **Text quirks:** country `Zimbabwea` (2 players) [q1:country_typo]. Bowling skill `Right-arm bowler` occurs once.
- **Team order:** `team_1` is the side batting first in only 304 of 567 matches [q4:team1_is_batting_first]. The toss winner's decision always matches who bats first, 567 of 567 [q4:toss_vs_batting_first].

## 5. Distributions to fit (stage 2)

| Quantity | Value |
|---|---|
| matches | 56–74 per season. Seasons run ~6–8 weeks in April–May; 2010 started 03-12 [q1:matches_per_season]. Days between match days: 1 (367), 2 (26), 3 (1) [q6:days_between_matches]. 164 double-headers, 239 single days. Weekend heavy: Sun 115, Sat 108, weekdays 57–76 [q6:weekday_mix] |
| toss | field 309 / bat 258, drifting to field (2016: 49 / 11) [q6:toss_decision_by_season]. The toss winner wins 287 of 567 (50.6%) [q6:toss_winner_wins] |
| result | chasing side wins 307, side batting first 260. Margins: runs p25 11, p50 23, p75 39, max 144; wickets p25 5, p50 6, p75 8 [q6:margin_quantiles] |
| deliveries per innings | min 30, p10 106, p50 123, p90 127, max 134, mean 118.6 [q6:deliveries_per_innings_quantiles] |
| innings total | first innings p10 119 / p50 160 / p90 193 (max 263); second innings p10 106 / p50 147 / p90 182 [q6:innings_totals_quantiles] |
| innings end | first innings: all out 40, 20 overs 513, short 15. Second innings: all out 56, 20 overs 303, target reached or D/L 209 [q6:all_out_or_20] |
| per delivery | extras 5.46%, wickets 4.91%, bat runs 1.215 [q6:per_delivery_rates]. Bat runs mix 0: 51,688; 1: 49,427; 2: 8,687; 3: 466; 4: 15,212; 5: 41; 6: 5,738 [q1:runs_dist] |
| over profile | runs per over 5.9 (over 1) → 8.1 (powerplay end) → 6.7 (over 7) → 9.9 (over 20). Wickets per over 0.20 → 0.77 at over 20 [q6:run_rate_by_over] |
| extras mix | wides 4,091, legbyes 2,317, noballs 567, byes 373, penalty 1 [q1:cats_extra] |
| dismissal mix | §4. Run outs are 394 of 3,447 (11.4%) innings-1 and 283 of 3,171 (8.9%) innings-2 dismissals [q6:dismissal_mix_by_innings] |
| squads | 11 per side (1 exception). Roles: Player 10,471, Keeper 889, Captain 888, CaptainKeeper 247 [q1:cats_role] |
| players | 33 play once, 22 play over 100 matches (max SK Raina 145) [q6:appearances_per_player]. 1–6 teams per career (265 one team); 1 mid-season move [q6:team_change_within_season]. New players per season 163, 59, 54, 47, 40, 37, 20, 17, 31 [q6:player_created_rule]. Age at debut 16.6–41.6, mean 25.9 [q6:dob_range_age_at_first] |
| player mix | India 261 of 468, then Australia 72, South Africa 39 [q1:cats_player]. Right-hand bat 343, left-hand 125 |

## 6. simkit mapping sketch

```python
p.entity("teams", key="team_key", cols={"ext_id": text(), "name": opt(text()), "listed": i32()})
p.entity("players", key="player_key", cols={"ext_id": text(), "player_name": opt(text()), "dob": opt(text()),
         "batting_hand": opt(cat("Left-hand bat", "Right-hand bat")), "bowling_skill": opt(text()),
         "country_name": opt(text()), "listed": i32()})
p.event("match_scheduled", cols={"match_id": i64(), "team_1": ref("teams"), "team_2": ref("teams"),
        "season_id": i32(), "venue": text()})
p.event("toss_decided", cols={"match_id": i64(), "toss_winner": ref("teams"), "toss_decision": cat("bat", "field")})
p.event("player_named", cols={"match_id": i64(), "player_id": ref("players"), "team_id": ref("teams"),
        "role": cat("Player", "Captain", "Keeper", "CaptainKeeper")})
p.event("innings_started", cols={"match_id": i64(), "innings_no": i32(), "team_batting": ref("teams"),
        "team_bowling": ref("teams")})
p.event("ball_bowled", cols={"match_id": i64(), "innings_no": i32(), "over_id": i32(), "ball_id": i32(),
        "has_ball_row": i32(), "teams_swapped": i32(), "striker": opt(ref("players")),
        "non_striker": opt(ref("players")), "bowler": opt(ref("players")), "striker_batting_position": opt(i32()),
        "runs_scored": opt(i32()), "extra_type": opt(cat("wides", "legbyes", "noballs", "byes", "penalty")),
        "extra_runs": opt(i32()), "player_out": opt(ref("players")), "kind_out": opt(cat(...9 kinds))})
p.event("match_completed", cols={"match_id": i64(), "match_winner": ref("teams"), "win_type": cat("runs", "wickets"),
        "win_margin": i32(), "outcome_type": cat("Result"), "man_of_the_match": ref("players")})
```

Ingest:
- The entities are `ORDER BY player_id` and `team_id`, with the placeholders 35 and 1 added by `UNION ALL` with NULL attributes.
- Every event has `owner=match_id`.
- E1, E2 and E3 share a time: E1 and E2 sort by block position, and E3 has `ord=player_id`. Each block is `ORDER BY match_id, …`.
- E4 has `ord=innings_no`. E5 has `ord = innings_no*10000 + over_id*100 + ball_id`, over the 4-way `UNION` of keys, LEFT JOINed to each table. Its time is distinct anyway.
- `event_time` comes from the §2 rule, computed in the ingest SQL with window `row_number()` per (match, innings), and the double-header rank per date.

`build.sql`:
- `team` and `player`: the creation views `WHERE listed = 1`.
- `match`: E1 ⋈ E2 ⋈ E6 on match_id, with `match_date = strftime(E1.event_time, '%Y-%m-%d')`.
- `player_match`: E3.
- `ball_by_ball`: E5 `WHERE has_ball_row = 1`, joined to E4, with `team_batting = CASE WHEN teams_swapped = 1 THEN E4.team_bowling ELSE E4.team_batting END`, and the reverse for `team_bowling`.
- `batsman_scored`, `extra_runs` and `wicket_taken`: E5 filtered on its non-NULL part (§3.4).

Stage-2 owners:
- the **match**, as a shard that plays a fixture list (season calendar, double-headers);
- the toss, then 2 innings of a ball process: an over/ball state machine with strike rotation, per-over run and wicket hazards (§5), and the bowler quota of ≤ 4 overs with no consecutive overs;
- **players** are drawn from team squads that change between seasons.

The volume is ~150k events, so no sample profile is needed.

## 7. Open questions and risks

- **Lineage and licence.** Kaggle `harsha547/ipldatabase` is inferred, not opened. Why exactly team 1 (KKR), player 35 and match 419136's row are missing is unknown. Spider's NULL-dropping is the leading hypothesis.
- **Placeholder entities versus `i64` refs.** This is a design call (§3.5). Placeholders keep the refs whole, but put two rows in the log that no table shows. Confirm before building.
- **The per-ball clock is invented.** The 16:00/20:00 starts, 40 s per delivery and 110 min per innings are not data. Stage 2 must not fit inter-ball gaps from them; only the order is real. The double-header assignment by lower match_id is also a guess.
- **Match 419136's date** (2010-03-29) is a rule. It fits the id gap and a free day, and the scorecard (DD 177/4 beat KKR 137/9) is consistent with the 2010 fixture, but it is unverified.
- **Scorecard defects.** 22 matches disagree with their recorded margins [q7:result_vs_score], there are 3 seven-ball overs, and 169 mislabelled deliveries. Laws on totals versus results, or "6 legal balls per over", would fail on real data. Write them as ≥ 99.9% rules, not invariants.
- **Gold answers for local024 and local025** have several CSV variants. Saved queries should pick one variant, and compare floats with the 1e-9 tolerance.
- **Alternative E5 split** into four event types is equally exact. Choose one per the project's stream semantics.

## Summary

- Exact round trip: **yes, with caveats**. These are 2 placeholder entities (team 1, player 35) behind `listed = 0`, a 169-row `teams_swapped` flag, and NULL-means-absent parts on `ball_bowled`. There are no floats, NULLs or format traps.
- Dataset name: **`ipl`**.
- **6 event types** (match_scheduled, toss_decided, player_named, innings_started, ball_bowled, match_completed: 150,036 events) and **2 entities** (players 469, teams 13).
- Event-shaped: **natural** in order and content (match lifecycle and every delivery). **Imposed** only for the intraday clock, since the source has dates only.
- Hardest blocker: **dangling refs.** Team 1, player 35 and match 419136 are referenced thousands of times but missing from their tables. Second to that, innings whose batting-team labels flip ball by ball.
