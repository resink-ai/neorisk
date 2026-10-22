# Anomaly-anchored label discovery: audit and plan

**Goal:** every discovery method first explains why a confirmed bad user is bad, meaning which of
its behaviours are anomalous. It then expands only along that explanation, to users with the same
anomaly and to connections reached through it.

**Status:** plan for review. Nothing is implemented. Branch `feat/label-discovery`.

## 1. Audit: is the anomaly built into each method?

The question for each method: does it look at what is unusual about the seed, or at the seed as
a whole?

| Method | Anchored on the seed's anomaly? | What it actually does | Symptom in the results (500 reviews) |
|---|---|---|---|
| `similarity` | **No** | kNN over all 11 features, equally weighted. A seed's ordinary traits (sessions, device count) count as much as its tell (minimum-sized order on the cheapest SKU). | Flags 87% of genuine promoters |
| `pu_learn` | Partly, implicitly | One logistic model, seeds vs. unlabeled, over the same 11 features. It learns weights, but globally: one model for all seeds, with no per-seed reason and no explanation. | AUC 0.81, stealth recall 0.11 |
| `connection` | **No** | Personalised PageRank along every device and invite edge from the seed. An invite to a real friend counts the same as one to a zombie; only crowded devices are down-weighted (1/log). | Runs dry at 120: it stays inside the seeds' own rings |
| `money_flow` | **No** | The same walk on the bonus-weighted invite graph | Same as `connection` |
| `sync` | **No** | Any milestone within 2 hours of a seed's, anomalous or not | Close to random |
| `rules` | Anomalies yes, seeds no | Six hand-written anomaly rules applied to everyone. They never ask which rules fire on this seed. | Visible members 0.90, stealth 0.01 |
| `label_model` | Anomalies yes, seeds barely | The same rules weighted by Dawid–Skene. Seeds are only clamped. | Same as `rules` |
| `active` | Partly, implicitly | XGBoost on features, graph and rule counts. It can learn the anomaly after enough reviews, but gives no explanation, and 5 seeds are too few. | 0.19→0.41, least stable |
| `vote` | Inherits its members | Pools the top 2% of five members | Best so far, but it pools unanchored signals |

**Verdict:** no method does the step you describe, "this user is bad because of X, now find X
elsewhere".
- The rules encode anomalies but ignore the seeds.
- Similarity and the graph use the seeds but ignore what is anomalous about them.
- The promoter false alarms and the dry graph runs are both direct consequences.

**A second gap is in the data itself.** The behaviour you described (failed KYC, retries, probing
the defences) does not exist in the simulator:
- The ring never fails, retries or gets rejected.
- The only failures are stock checkouts (`checkout_failed`) and budget rejections
  (`referral_bonus_rejected`), and the world view loads neither.

Today the ring's only anomalies are the cheapest minimum-sized order, a shared device, silence
after the bonus, and a hunter whose invitees barely buy. Stealth members drop all of them.

**What anchoring should fix:** the hunter is anomalous even when its zombies are stealthy, and
stealth zombies are still invited by the hunter. So the path your process implies is:
1. Explain the seed.
2. Find other users with the same anomaly. This reaches other rings' hunters and zombies.
3. Follow their connections. This reaches the stealth members.

No current method makes that jump from one ring to the next. That is why the graph runs dry and
why similarity over-reaches.

## 2. Plan

Estimate: about 8.5 h of agent time. If a milestone runs past twice its estimate, I stop and
report.

The old methods stay registered unchanged, as the "before" side of a before/after comparison.

### M1: Explain the seed (1.5 h)

New file: `discover/explain.py`.
- `anomaly_profile(world) -> (surprisal matrix, names)`:
  - for each user and each signal, how far into the population's tail they sit, as −log
    percentile;
  - each signal is direction-aware (for example, few views per order is the anomalous direction);
  - it is unsupervised and computed once per world.
- The signals:
  - the 11 behaviour features;
  - the 6 rule firings;
  - edge anomalies: whether the user shares a crowded device, and whether they are an inviter
    whose invitees barely buy.
  - It also reads the probing signals from M3 when they exist.
- `explain(world, known) -> reasons`: for each confirmed bad user, the signals where it is in the
  top 1% tail, plus a combined seed explanation (each signal weighted by how many bad seeds share
  it).
- Tests on the toy world:
  - a zombie's reasons include `near_min_share` and `cheapest_share`;
  - a normal shopper has no reasons;
  - the explanation never reads truth (covered by the existing AST scan).

### M2: Anchor the methods on the explanation (2.5 h)

New methods sit next to the old ones:

| New key | Replaces | Change |
|---|---|---|
| `reason_sim` | `similarity` | Distance only on the seeds' anomalous signals, weighted by surprisal. A candidate must share the anomaly, not just look ordinary in the same way. |
| `reason_hop` | `connection`, `money_flow` | Two steps. (1) Find users with the seeds' anomaly (`reason_sim`), which reaches other rings. (2) Run PageRank from the seeds plus those anomalous users, walking only edges that carry an anomaly (crowded shared devices, invites from anomalous inviters). |
| `reason_rules` | `rules` | Only the rules that fire on the confirmed bad users vote, weighted by how many they fire on. |
| (in place) `pu_learn`, `active` | — | Add the surprisal matrix as inputs, and report the top features as the explanation. Their old versions stay as `pu_learn_plain` and `active_plain` for the before/after. |
| `vote` | — | Members become `reason_sim`, `reason_hop`, `reason_rules`, `sync` and `connection`. The old vote stays as `vote_plain`. |
| `anomaly` (new baseline) | — | Pure unsupervised anomaly score, no seeds. It shows how much the seeds add. |

Defaults are frozen before the first scored run, as before. Each new method gets a toy-world
sanity test.

### M3: Put probing behaviour in the data (2 h, needs your OK)

Overlay knobs in `bounty_hunters` (off by default, on in the bench profile):
- `probe_p`: a ring member probes the defences before it succeeds:
  - a checkout below the minimum is rejected, then retried just above it (`checkout_failed`,
    reason `below_minimum`);
  - a sign-up from a device already over its account limit is rejected, then retried from a new
    device (new `signup_rejected` event);
  - a bonus claim is rejected, then re-claimed.
- Stealth members probe at a lower rate (`stealth_probe_p`). Genuine users also fail and retry
  occasionally (`genuine_retry_p`), so retries are a strong signal but not a perfect one.
- `world.py` loads the failure tables, and `explain.py` derives `failed_attempts`,
  `retry_after_fail_minutes` and `distinct_reject_reasons`.
- Tests:
  - `stealth_p = probe_p = 0` keeps the legacy export byte-identical;
  - ring members fail more often than base users.

### M4: Bench and report (1.5 h)

- The report gets a "Why is the seed bad?" panel: the top reasons for the seeds of the first draw.
- Every method row shows before and after.
- One new metric, **reason precision**: the share of each label set whose own top reasons overlap
  the seeds' reasons. It is computed from the world only, so it is a sanity check rather than a
  truth metric.
- Truth metrics stay as they are; promoter false alarms and stealth recall are the two to watch.

### M5: Run and write up (1 h)

- Seed 42 and 5 seed draws, run on two datasets:
  - the current data, which isolates the method change;
  - the data with probing, which shows what the new signal adds.
- Expected:
  - `reason_sim` cuts promoter false alarms well below 0.87, at similar recall;
  - `reason_hop` breaks past 120 by jumping to other rings;
  - stealth recall gains come mainly through `reason_hop`, because stealth members carry few
    anomalies of their own.
  - If these don't happen, the write-up says so.
- Suite, ruff, spec results section, README; then "mobile it" for the new results.

## 3. Open questions

1. **M3 (probing data):** include it? Recommended. Without it, the bench can test anchoring only
   on today's mild anomalies, and not on the retry and probing signal you rely on in practice.
2. **Before/after:** keep the old methods registered (recommended), or replace them in place?
