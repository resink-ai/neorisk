# Scorer labels for the legacy fraud export

## Problem

Before D89 the benchmark's labels were sampled: `XGBScorer` scored the golden features,
`calibrate` shifted the scores to a target bad rate, and `sample_labels` drew 0/1 from them. The
labels were noisy, so models separated and the ranking metrics meant something.

D89 retired that scenario. `datagen export --legacy-fraud` now labels a row 1 exactly when its user
(or its inviter) is a bounty-hunter ring member. The `scorer` module survived but nothing calls it.

Measured on `examples/ecommerce --profile full --overlay bounty_hunters --seed 42` (4,590 rows,
5.4% bad), `bench compare` still runs end to end, but all five models score AUC 1.0000. The ring
is a deterministic tell: hunters and zombies always buy the cheapest qualifying SKU for about the
referral minimum, so `product_price`, `amount` and `device_model` together give the label away.
No single column is above AUC 0.79, so this is not a leak; the labels are simply noise-free.

## Design

Keep role labels as the default, so existing outputs and parity tests stay identical. Add
scorer labels as an option on the export.

```
datagen export RUN --legacy-fraud --out DIR [--labels roles|xgb|mlp] [--bad-rate 0.02]
```

`neorisk_simkit.io.legacy.rescore(ds, kind, bad_rate, seed) -> Dataset`:

1. **Scorer inputs:** the golden frame plus `is_ring = actor_role > 0`. The ring's ground
   truth is one weighted input among several, the way `inv_zombie_mean_30d` was before.
2. **Score:** `p = calibrate(scorer.score(x), bad_rate)`.
   - `xgb`: `XGBScorer(SCORER_WEIGHTS, seed)`.
   - `mlp`: `MLPScorer(list(SCORER_WEIGHTS), seed=seed)`.
3. **Labels:** `label = sample_labels(p, default_rng(seed))`.
4. **Golden `score`:** `p`. It stays out of the oracle, as before.
5. **Meta:** `labels: {source, scorer, weights, target_bad_rate}`. Role exports carry no `labels`
   key, so their meta is unchanged.

The seed is the run's seed, so one run and one flag set give one dataset.

`SCORER_WEIGHTS` keeps the old weights for every golden feature that still exists. It drops
`addr_chg_sum_30d`, which is no longer a golden column, and replaces the two `*_zombie_mean_30d`
features with `is_ring`.

| feature | weight |
|---|---|
| `amt_ratio_30d` | 1.0 |
| `u_amt_count_7d` | 0.3 |
| `u_amt_max_30d` | 0.4 |
| `dev_users_n_unique_7d` | 0.8 |
| `inv_bonus_count_30d` | 0.8 |
| `inv_bonus_sum_30d` | 1.0 |
| `invr_bonus_count_30d` | 0.8 |
| `invr_bonus_sum_30d` | 1.0 |
| `is_ring` | 1.5 |

## Data size: the `bench` profile

`--profile full` (5,000 users) yields only about 4.6k rows. The `examples/ecommerce` `bench` profile
scales the run to 50,000 users and rescales what a 10× population would otherwise break:

| setting | why |
|---|---|
| `stock_mean = 500` | At the default 30, 33% of checkouts fail on stock, against the brief's < 2%. |
| `checkout_p = 0.07` | Once stock stops binding, signup→order is 0.43, above the brief's 0.28–0.42. This brings it to 0.39. |
| `monthly_budget_cents = 20000000` | At the default budget, every claim after about day 45 is rejected, so the test split has no invites and no ring activity. |
| `run.max_events = 10000000` | The run emits about 2.6M events; the default guard is 1M. |

All 23 `datagen check` checks pass, and the run takes about 10 s.

## Blurring the ring (`bench` profile)

Role labels stayed trivial (AUC 0.998–0.999) because every ring member followed the same script.
Two `bounty_hunters` knobs now add deliberate overlap. Both default to 0 and draw no random numbers
when off, so every other profile is byte-identical.

| knob | `bench` | effect | error type |
|---|---|---|---|
| `stealth_p` | 0.5 | Ring member signs up on its own device, buys a popularity-drawn qualifying SKU at list price, keeps browsing; stealth hunters cash out on ordinary SKUs | labeled but normal-looking: misses |
| `promoters_share` | 0.004 | Genuine users invite about 8 friends; half share the promoter's device and 60% open with the cheapest qualifying order, then shop normally | ring-looking but unlabeled: false alarms |

Settings tried on the `bench` profile (role labels, five-model test AUC / PR-AUC):

| `stealth_p` | `promoters_share` | AUC | PR-AUC |
|---|---|---|---|
| 0 | 0 | 0.998–0.999 | 0.97–0.98 |
| 0.3 | 0.002 | 0.957–0.984 | 0.50–0.62 |
| 0.5 | 0.004 | 0.909–0.942 | 0.44–0.52 |
| 0.7 | 0.006 | 0.896–0.946 | 0.43–0.57 |

The `bench` profile uses 0.5 / 0.004. Beyond that the gains are small, because the remaining tells
are structural: ring members join by invitation (`user_segment`), and non-stealth zombies still buy
the cheapest SKU (`product_price`).

## Results (seed 42, `bench` profile, 45,605 rows)

| labels | bad rate | test positives | ceiling AUC | five models, test AUC |
|---|---|---|---|---|
| roles | 6.0% | 149 | 1.000 | 0.909–0.942 (XGB best) |
| xgb | 2.0% | 95 | 0.836 | 0.78–0.82 (XGB 0.818, LR 0.812, large ANN 0.814, small ANN 0.808, RF 0.784) |
| mlp | 2.0% | 167 | 0.625 | 0.55–0.63 |

The ceiling is the AUC of the golden `score` on the test split.

- The test split's bad rate is below the overall rate, because sign-ups end around day 30
  (`arrive_share = 0.5`) and rings stop arriving at 80% of the run.
- Before blurring, the XGB-scorer validation AUC (about 0.83) sat well above test AUC
  (0.65–0.72), and XGBoost early-stopped at round 1. With blurring, validation is about 0.86 and
  test 0.78–0.82, and XGBoost trains for 12 rounds.

## Out of scope

- No change to `bench`.
- No change to the pack. The overlay gains the two knobs above, off by default.
