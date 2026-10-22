# Label-discovery benchmark

## Problem

`bench compare` asks "given labels, which model predicts best?". In practice the labels come first,
and they are discovered rather than given: a risk team starts from a few reported cases, expands
them by connection and behaviour, has an analyst confirm or reject each candidate, and repeats.
The [Seeds to Labels guide](https://claude.ai/artifact/9WiCYXjzTSMpfNw8KYz3wA) lists the methods.
This benchmark measures them: hide the true labels, give each method the same few seeds and the
same review budget, and score what it recovers.

## Decisions (from the interview, 2026-10-21)

| question | answer |
|---|---|
| hidden truth | ring roles: hunters and zombies, stealth members included. Promoters and their friends are good. |
| the human | a budgeted oracle: each round a method picks up to K accounts, and a simulated reviewer reveals their true label |
| seeds | a few "reported" cases, drawn from non-stealth members whose label is known by the report date |
| data | reuse the `bench` profile run (seed 42, blurred ring). No new world; one small change to record stealth. |

## Taking the human out

A human reviewer makes two things unrepeatable: what gets reviewed, and what the review says. The
benchmark fixes both:

| human role | replaced by | why it is fair |
|---|---|---|
| decides who to review next | the method's own `propose(k)` | this is what we are comparing |
| judges a case | the oracle: returns the true label | same answer for every method, every run |
| capacity | budget: K reviews per round, R rounds | methods compete at equal analyst cost |
| domain experience | frozen labeling functions written from the public reward rules, never tuned on truth | codified once, identical across runs |
| tuning hyperparameters | defaults fixed before the first scored run | no method gets fitted to the hidden labels |

R = 0 is the zero-feedback case: one-shot expansion from the seeds. It falls out of the same loop.

Options considered and left for later: a noisy or biased reviewer (it errs at a rate, or misses
stealth members), and an LLM analyst that reads case evidence. The LLM option is the realistic
end state, but it is non-deterministic and paid, so it would blur the comparison this first
version needs.

## Data

The `bench` run already writes everything the methods need:

- **entities:** `users` (acquisition, invited_by), `devices`, `orders`, `order_lines`, `skus`.
- **events:** `session_started` (user × device), `product_viewed`, `order_placed`, `order_returned`,
  `referral_bonus_paid`, `address_changed`, `user_signed_up`.
- **hidden:** `labels` (931 users: 100 hunters and 831 zombies), and `cases` (cohort: promoter
  and promoted_friend).

Two problems block it as-is:

1. **Stealth is not recorded.** The overlay decides stealth in `ctx.local`, and no output keeps it.
   Seeds must avoid stealth members and the report splits recall by stealth.
   - **Change:** `ctx.label(..., variant="stealth")`, a new nullable `variant` column in `labels`.
   - This changes the labels schema for every run (the column is null outside stealth). The
     legacy export and its byte-parity are untouched, because they select the columns they use.
2. **The raw run leaks the truth.** Ring users have overlay-namespace ids (`1000000003`…),
   and `partition_id`, `action_id` and `cause_id` name the overlay, the action (`cash_out`) and the
   causal chain.
   - **Fix:** build a **world view** for the methods:
     - permute every id with the existing seeded Feistel map (`io/public_ids.py`);
     - drop `partition_id`, `action_id`, `cause_id` and `seq`;
     - drop `labels` and `cases`.
   - A leak test checks that the user id, the other id columns and row order each score a ring
     AUC under 0.8, the same bar the scorer-labels design used. Behaviour columns are
     informative on purpose and are not part of the test.

## Protocol

```
truth  = hidden labels + variant + cohort, keyed by world user id
world  = the leak-free view
seeds  = n_seeds (5) bad, non-stealth users with label_available_at <= t_report (day 30)
known  = {seed: 1}
for round in 1..R:
    ids = method.propose(world, known, K)      # unreviewed users only
    known |= oracle.review(ids)                # true 0/1, counts against the budget
scores = method.score(world, known)            # a number per user, for the final ranking
```

- **Defaults:** K = 50 and R = 10, so 500 reviews. The world has about 52.8k users and 931 bad
  (1.8%).
- **Seed repeats:** each method runs over 5 seed draws. The report gives the mean and spread.
- **Budget sweep:** R ∈ {0, 2, 5, 10} at K = 50.

## Methods

Every method implements `propose` and `score`. Each has no human step and no tuning on truth.

| key | family (guide section) | idea |
|---|---|---|
| `random` | baseline | review uniformly at random; the lower bound |
| `perfect` | baseline | the true ranking; the ceiling |
| `connection` | graph | personalized PageRank from known bad over shared device and invite edges, with device hubs down-weighted by degree |
| `money_flow` | graph | walk bonus edges: the inviter of a known bad, and the invitees of a bad inviter, weighted by bonus count |
| `similarity` | behaviour | kNN in a per-user behaviour vector, scored by distance to known bad minus distance to known good |
| `pu_learn` | behaviour | positive-unlabeled classifier: known bad against a random unlabeled sample, logistic regression |
| `sync` | behaviour | lockstep: users whose signup → first order → bonus timing and SKU match a known bad's within a window |
| `rules` | heuristics | 6 frozen labeling functions, combined by majority vote |
| `label_model` | weak supervision | the same labeling functions combined by a Dawid-Skene label model, plus the known labels |
| `active` | AI in the loop | each round, fit a gradient-boosted model on the known labels and review the top-K; uses all the features above |
| `vote` | ensemble | rank by how many of `connection`, `money_flow`, `similarity`, `sync` and `rules` place the user in their top 2% |

### Labeling functions

The labeling functions are written from the reward rules a platform would publish, not from the
overlay code. They are frozen before the first scored run.

1. All orders are qualifying-minimum orders on the cheapest qualifying SKU.
2. Invited, one order, then no session after the bonus.
3. Signed up on a device that the inviter also uses.
4. Inviter with 3 or more paid bonuses whose invitees average under 2 orders.
5. Views per order is below the population's 5th percentile.
6. Abstain otherwise. Benign votes come from "2 or more orders on non-qualifying SKUs".

### Behaviour vector

These features are computed once from the world and shared by `similarity`, `pu_learn` and
`active`:

- order count;
- share of orders on qualifying SKUs;
- share of orders on the cheapest SKU;
- views per order;
- sessions;
- distinct devices, and the largest number of users seen on any of them;
- acquisition;
- invites sent and bonuses earned;
- time from signup to first order.

## Metrics

All metrics are scored against the full hidden truth.

**Analyst efficiency** (the bottleneck):
- **Discovery curve:** bad found against reviews spent.
- **Hit rate** per round.
- **Recall at the full budget.**

**Final ranking:** `score` over users not yet reviewed:
- ROC and PR curves together;
- AUC, PR-AUC, and precision and recall at the top 931.

**By segment:**
- recall on non-stealth and stealth members, separately;
- false-alarm rate among promoters, promoted friends and ordinary users.

**Risk view:** treat the top of the ranking as a block list, then plot approval rate against the
bad share among approved users.

## Running it

```
bench discover --generate examples/ecommerce --profile bench --overlay bounty_hunters --seed 42 --out DIR
bench discover --run RUN_DIR --out DIR      # reuse an existing run
```

The command writes the following to `DIR`:
- `discover.json`: every metric, method and seed draw;
- `discover.html`: a single-file report with the discovery curves, ROC/PR, the segment table and
  the risk view;
- a console summary table.

## Changes made during implementation

- **Report day 45, not 30.** Labels become available 30 days after the act, so by day 30 there
  are almost no seed candidates.
- **Label model.** It is a two-class Dawid-Skene, initialised from the majority vote. The
  one-coin version could not credit rules that only ever vote "bad", and its ranking came out
  inverted (AUC 0.45). Found on the first scored run and fixed, with a test.
- **`active`:**
  - its graph features leave out each seed's own restart mass, which let it memorise the seeds;
  - it uses `min_child_weight` 0.05, so 5 seeds can split a node.
  Both were fixed before freezing.
- **Leak test.** It covers id and row-order columns. Behaviour columns such as `acquisition`
  are informative on purpose.
- **Budget sweep.** One 10-round run per method with snapshots at 0, 2 and 5 rounds, rather than
  separate runs.

## Results (seed 42, `bench` profile, 5 seed draws)

The world has 52,796 users and 931 bad (464 stealth). Each run starts from 5 seeds and has 926
bad users to find with 500 reviews (50 × 10).

"Label set" means the known bad plus the top-ranked unreviewed users: 931 users in total,
so precision equals recall. ROC and PR are measured over unreviewed users.

| method | found in 500 reviews | label-set recall | AUC | PR-AUC | visible recall | stealth recall | false alarm, promoters | false alarm, promoted friends |
|---|---|---|---|---|---|---|---|---|
| similarity | 445 ± 23 | 0.565 | 0.712 | 0.145 | 1.00 | 0.13 | 0.874 | 0.091 |
| pu_learn | 469 ± 9 | 0.556 | 0.812 | 0.061 | 1.00 | 0.11 | 0.155 | 0.211 |
| vote | 227 ± 7 | 0.536 | **0.867** | **0.281** | 0.71 | **0.36** | 0.215 | 0.234 |
| rules | 413 ± 0 | 0.455 | 0.573 | 0.028 | 0.90 | 0.01 | 0.055 | 0.286 |
| label_model | 413 ± 0 | 0.450 | 0.597 | 0.027 | 0.89 | 0.00 | 0.000 | 0.306 |
| active | 259 ± 69 | 0.410 | 0.666 | 0.190 | 0.48 | 0.33 | 0.010 | 0.040 |
| connection | 120 ± 7 | 0.166 | 0.506 | 0.028 | 0.18 | 0.15 | 0.012 | 0.020 |
| money_flow | 120 ± 7 | 0.166 | 0.506 | 0.028 | 0.18 | 0.15 | 0.012 | 0.020 |
| sync | 16 ± 5 | 0.044 | 0.505 | 0.018 | 0.05 | 0.04 | 0.015 | 0.017 |
| random | 10 ± 3 | 0.035 | 0.499 | 0.018 | 0.04 | 0.03 | 0.016 | 0.016 |
| perfect (truth) | 500 | 1.000 | 1.000 | 1.000 | 1.00 | 1.00 | 0 | 0 |

**Label-set recall by budget (rounds 0 / 2 / 5 / 10):**
- vote: 0.29 / 0.40 / 0.46 / 0.54
- active: 0.19 / 0.30 / 0.35 / 0.41
- similarity: 0.45 / 0.45 / 0.45 / 0.56
- pu_learn: 0.52 / 0.54 / 0.54 / 0.56
- rules and label_model: flat at 0.45

Score ties in the label set and the risk view go to the lower world id, which is random with
respect to the ring. Each budget is a snapshot of one 10-round run, and a test checks that it
equals a separate shorter run.

**What it shows:**
- **The visible half of the ring is easy; the stealth half is not.**
  - Similarity, PU learning and the rules find almost every visible member without a single
    review (label-set recall 0.45–0.52 at 0 rounds) and spend their reviews confirming them.
  - None of them catches more than 13% of stealth members.
- **Agreement finds stealth members best.**
  - `vote` has the best ranking (AUC 0.867, PR-AUC 0.28) and the best stealth recall (0.36).
  - `active` is second on stealth (0.33) and improves with every round of reviews.
  - But `active` is the least stable method: ± 0.19 recall and ± 69 users found across seed
    draws. With a handful of labels, its trees fit whichever seeds they got.
- **The promoters cost precision.**
  - Similarity flags 87% of genuine promoters, because inviting many people looks like a hunter.
  - The rules flag 29–31% of promoted friends, who share devices and open with the cheapest
    qualifying order.
  - The blur added in the scorer-labels work is doing its job.
- **Graph expansion is exact but stuck.** Every ring is its own island:
  - each holds the hunter and zombies only, with no device or invite links to other rings or to
    ordinary users;
  - so `connection` and `money_flow` find their seeds' rings at full precision;
  - after that every other user scores zero, and both proposals and the label set fall back to
    world-id order, which is effectively random (AUC 0.51).
  - They tie with each other because both walk the same islands.
  - This is a finding about the data: the world has no cross-ring bridges and no shared-device
    hubs. That makes graph methods look worse at reach, and better at precision, than they
    would be on real data.
- **`sync` is near random.** Its 2-hour window is much tighter than the 0–2 day spread
  between a hunter and its zombies. Its default was frozen before scoring, so it stays.

## Anomaly-anchored methods (2026-10-22)

Plan: `docs/superpowers/plans/2026-10-22-anomaly-anchored-discovery.md`.

An analyst starts from why a confirmed bad user is bad (repeated failed checks, probing the
threshold), then looks for that behaviour in others and follows the connections it leads to.
Before this change, no method did that. The rules encoded anomalies but ignored the seeds;
similarity and the graph used the seeds but not what is anomalous about them.

**Explaining the seed (`bench.discover.explain`).**
- Every user gets a tail excess per signal: −log P(at least this suspicious) − log(1/0.2),
  floored at 0. A value shared by more than 20% of users explains nothing.
- The signals:
  - 8 oriented behaviour features;
  - the 5 bad-voting rules;
  - failed identity checks (count, distinct reasons, per reason);
  - an order under the referral minimum followed by a qualifying one within a day.
- The weights are the mean excess of the known bad, less that of the reviewed good.

**The anchored methods:**
- `reason_sim` scores users on the seeds' anomalies.
- `reason_hop` restarts personalised PageRank from the seeds plus the top 1% by `reason_sim`, on
  a graph where every edge keeps max(rank of its two ends)^8 of its weight.
- `reason_rules` weights the rules by how often they fire on the known bad.
- `anomaly` uses no seeds.
- `pu_learn`, `active` and `vote` take the anomaly profile, or anchored members. Their old forms
  stay as `*_plain`.

**New data (`probe` profile):**
- 80% of visible and 15% of stealth ring members fail identity checks and retry. Zombies on the
  hunter's device trip `device_limit` / `phone_reused`.
- Visible zombies try an order just under the minimum first.
- 3% of genuine users fail a check once.
- `stealth_p = probe_p = 0` runs stay byte-identical, checked on three runs.

**Correction to the table above.** `vote`'s rank percentiles broke ties by row order, which is
sign-up time; most users tie at zero for `sync` and `connection`. With average ranks, the same
five members (`vote_plain`) score a label-set recall of 0.756, not 0.536, and a stealth recall
of 0.55, not 0.36. The tie noise was hurting `vote`, not inflating it.

### Results (seed 42, 5 seed draws, 500 reviews)

Before → after. Rec = label-set recall, Stealth = stealth recall, FA = false alarm.

`bench` data (no probing, same run as above):

| pair | found | rec | AUC | stealth | FA promoters | FA promoted friends |
|---|---|---|---|---|---|---|
| connection → reason_hop | 120 → **391** | 0.165 → **0.632** | 0.506 → **0.992** | 0.15 → 0.27 | 0.012 → 0.240 | 0.020 → 0.162 |
| similarity → reason_sim | 445 → 473 | 0.565 → 0.536 | 0.712 → 0.874 | 0.13 → 0.07 | 0.874 → **0.000** | 0.091 → 0.256 |
| rules → reason_rules | 413 → 419 | 0.457 → 0.457 | 0.573 → 0.592 | 0.01 → 0.01 | 0.055 → 0.000 | 0.286 → 0.302 |
| pu_learn_plain → pu_learn | 469 → 462 | 0.556 → 0.556 | 0.812 → 0.782 | 0.11 → 0.11 | 0.155 → 0.335 | 0.211 → 0.178 |
| active_plain → active | 259 → 287 | 0.407 → 0.347 | 0.666 → 0.613 | 0.33 → 0.34 | 0.010 → 0.009 | 0.040 → 0.026 |
| vote_plain → vote | 463 → 447 | **0.756** → 0.682 | 0.928 → 0.948 | **0.55** → 0.37 | 0.200 → 0.447 | 0.086 → 0.108 |
| anomaly (no seeds) | 484 | 0.554 | 0.865 | 0.11 | 0.775 | 0.156 |

`probe` data (52,778 users, 913 bad, 454 stealth):

| pair | found | rec | AUC | stealth | FA promoters | FA promoted friends |
|---|---|---|---|---|---|---|
| connection → reason_hop | 115 → **425** | 0.158 → **0.667** | 0.506 → **0.993** | 0.16 → 0.33 | 0.020 → 0.236 | 0.019 → 0.113 |
| similarity → reason_sim | 468 → 486 | 0.543 → 0.581 | 0.869 → 0.871 | 0.08 → 0.16 | 0.396 → **0.005** | 0.193 → 0.166 |
| rules → reason_rules | 225 → 302 | 0.469 → 0.469 | 0.674 → 0.666 | 0.03 → 0.03 | 0.195 → 0.002 | 0.227 → 0.267 |
| pu_learn_plain → pu_learn | 454 → 474 | 0.560 → 0.618 | 0.817 → 0.849 | 0.11 → 0.23 | 0.086 → 0.232 | 0.211 → 0.113 |
| active_plain → active | 278 → 252 | 0.374 → 0.490 | 0.593 → 0.656 | 0.27 → 0.36 | 0.031 → 0.015 | 0.055 → 0.038 |
| vote_plain → vote | 456 → 442 | 0.757 → **0.767** | 0.928 → **0.958** | 0.56 → 0.53 | 0.204 → 0.151 | 0.096 → 0.078 |
| anomaly (no seeds) | 477 | 0.566 | 0.872 | 0.13 | 0.695 | 0.151 |

The seeds' top reasons in draw 1:
- `bench`: few views per order, few sessions, silent after the bonus, a crowded device, the
  cheapest minimum order.
- `probe`: few views per order, few sessions, distinct failure reasons, failed checks, an order
  under the minimum before a qualifying one.

**What it shows:**
- **Anchoring the graph on the anomaly breaks it out of the seeds' rings.**
  - `reason_hop` finds 391–425 ring members against `connection`'s 115–120, and has the best
    ranking of any method (AUC 0.99, PR-AUC 0.42–0.44).
  - It reaches stealth members (0.27–0.33) by walking from anomalous hunters to the zombies they
    invited.
  - With no reviews at all, its label set already holds 81–85% of the ring.
- **Anchoring similarity on the anomaly removes the promoter false alarms.**
  - `similarity` flags 87% (`bench`) or 40% (`probe`) of genuine promoters; `reason_sim` flags
    0–0.5%, with recall within ±0.04 of `similarity`.
  - `anomaly` with no seeds already finds the visible half (0.55–0.57) but flags 70–78% of
    promoters. What the seeds add is mostly the explanation that excludes them.
  - The same holds for the rules: `reason_rules` drops the promoter false alarms to 0.
- **The probing signal helps the learners.** On `probe` data:
  - `pu_learn` rises from 0.560 to 0.618 and doubles its stealth recall;
  - `active` rises from 0.374 to 0.490;
  - `label_model` rises to 0.539.
  - On `bench` data, with no probing, the anomaly inputs cost `pu_learn` and `active` a little.
- **`vote` is mixed.** On `probe` data the anchored `vote` is best (0.767, AUC 0.958). On `bench`
  data it is worse than `vote_plain` (0.682 against 0.756): it trades `vote_plain`'s stealth
  recall for promoter false alarms.

**Problems found, not fixed (fixing them now would tune on the scored run):**
- **The explanation drifts as labels arrive.**
  - `reason_hop`'s recall falls from 0.81 with no reviews to 0.63 at 500, although 78% of its
    reviews are hits.
  - The weights average every confirmed bad user. The seeds' specific tells (crowded device,
    cheapest minimum order) are diluted by hundreds of later finds into generic low activity.
    Reviewed promoters, who share some tells, subtract them further.
  - `reason_rules` shows the same thing at round 2 (0.45 → 0.18 → 0.46).
  - Proposed follow-up: a per-pattern explanation, where a candidate matches some confirmed
    user's own reasons (max over the known bad, or clusters of reasons) instead of their
    average.
- **Reason precision does not discriminate.** It is 0.97–1.00 for every non-random method,
  because "carries any of the seeds' anomaly" is too loose a test. It needs a threshold, such as
  overlap ≥ half the seeds' weight, to say anything.

## Out of scope

- A noisy or biased reviewer, and an LLM reviewer (see above).
- Several worlds, ring sizes or blur levels. One world, seed 42.
- A second fraud pattern.
- Training `bench compare` models on discovered labels. This is a natural follow-up: it measures
  how much a label method's mistakes cost the downstream model.
