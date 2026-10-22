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
   - A leak test checks that the user id and every remaining single column score a ring AUC
     under 0.8, the same bar the scorer-labels design used.

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

## Out of scope

- A noisy or biased reviewer, and an LLM reviewer (see above).
- Several worlds, ring sizes or blur levels. One world, seed 42.
- A second fraud pattern.
- Training `bench compare` models on discovered labels. This is a natural follow-up: it measures
  how much a label method's mistakes cost the downstream model.
