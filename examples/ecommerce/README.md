# E-commerce marketplace

Shoppers browse in sessions, fill carts, and check out against per-group inventory. Orders
ship, deliver and sometimes come back. A referral program with a budget per period pays both
sides when an invitee's first order qualifies. See [`specs/brief.md`](specs/brief.md).

## Model

| Partition | Kind | Holds | Processes |
|---|---|---|---|
| `user` | owner (population, exposed to overlays) | profile, credit and its hold, region, cart scratch | `shopper` (kernel) |
| `order` | owner (created at checkout, one per placed order) | amount, lines, category, credit used, refunded, status | `fulfillment` (machine, compiled into `mx_order`) |
| `inventory` × `sku_groups` | shard | `on_hand`, `reserved` per SKU, a 64-slot hold table | `inventory_desk` (kernel), `restock` (kernel, every `restock_period`) |
| `referral_pool` × 1 | shard | `remaining`, `granted`, current period window | `pool_desk` (kernel; the budget resets every `referral.period`) |

Boundaries (immutable, latency ≥ δ):

| Boundary | From → to | Kind | δ |
|---|---|---|---|
| `reserve` | `user` → `inventory` | request (`granted` / `rejected`) | 150 ms |
| `commit`, `release` | `user` → `inventory` | message | 150 ms |
| `claim` | `user` → `referral_pool` | request (`granted` / `rejected`) | 300 ms |
| `claim_refund` | `user` → `referral_pool` | message (gives back a late grant, D67) | 300 ms |
| `inviter_credit` | `user` → `user` | owner-to-owner message (D73) | 1 day |

Checkout holds credit on the user, sends one `reserve` per cart line (up to 5) to that line's
inventory shard, then authorizes payment and commits every hold, or releases them all. A placed
order creates an `order` owner, and its `fulfillment` machine moves it through
`placed → shipped → delivered → (returning → returned | kept)` or `placed → lost`; branch
probabilities (`fulfil.*`, apparel and shoes return more) are config. A referred shopper's first
order of at least `referral.min_order` claims both bonuses from the pool. When the claim is
granted, the invitee is paid at once. The inviter is credited by an `inviter_credit` message at
least one day later, and that credit's `cause_id` is the invitee's payout event. Inviters are
among the first users, so they exist from the start. Users never retire, so no credit is late.

**Events (26):** `user_signed_up`, `session_started`, `product_viewed`, `cart_item_added`,
`checkout_started`, `checkout_failed`, `payment_authorized`, `payment_failed`,
`order_placed`, `referral_bonus_paid`, `referral_bonus_rejected` (owner `user`);
`order_shipped`, `order_delivered`, `order_lost`, `return_requested`, `refund_issued`
(owner `order`); `stock_reserved`, `stock_rejected`, `stock_committed`, `stock_released`,
`stock_expired`, `stock_commit_late`, `restocked` (shard `inventory`); `bonus_granted`,
`bonus_rejected`, `bonus_refunded` (shard `referral_pool`). Address changes of `user`
(`region`) are written to `history/address`.

**Laws (10, all required):** `chk.stock_never_negative`, `chk.reserved_never_negative`,
`chk.holds_resolved`, `chk.refund_le_paid`, `chk.order_lifecycle`,
`chk.referral_once_per_invitee`, `chk.referral_budget`, `chk.credit_never_negative`,
`chk.hold_never_negative`, `chk.pool_never_negative`. Statistical targets are in
[`specs/expectations.yaml`](specs/expectations.yaml).

**Extension points (for overlays):** owner `user` (`p.expose_owner`); actions `signup`,
`signup_invited`, `quick_order`, `pay_referral`, `claim_bonus` (`p.expose`); parameter
`referral.min_order` (`p.expose_param`).

## Overlays

| Overlay | Adds | Key parameters |
|---|---|---|
| `bounty_hunters` | Rings of one hunter and its zombies under one campaign owner. Zombies order just above the minimum, both bonuses are claimed, and everyone goes dormant. Hidden labels give role, outcome and `label_available_at`. *Not yet in `specs/overlays/`: it is rewritten for the real pack in the next step of M3.* | `size`, `zombies_mean`, `share_device`, `arrive_day`, `arrive_span_days`, `qualify_timeout`, `order_above_min`, `zombie_order_p` |

Deferred: the flash sale (one day of 8× traffic on a few hot SKUs). It needs cohorts of
existing base owners and shard-state hooks (D93).

## Calibration

`datagen check` against [`specs/expectations.yaml`](specs/expectations.yaml) (seed 42; `legacy`
is checked with `bounty_hunters` against its `--no-overlays` run as the baseline). R = required.

| Metric | Target | Measured `sample` | Measured `legacy` |
|---|---|---|---|
| R `exp.session_to_checkout` | 0.06–0.10 | 0.085 | 0.085 |
| R `exp.checkout_to_order` | 0.70–0.85 | **0.952 (fail, unreachable)** | **0.952 (fail, unreachable)** |
| R `exp.auth_failure_rate` | 0.02–0.04 | 0.029 | 0.031 |
| R `exp.return_rate` (30 d) | 0.05–0.08 | 0.064 | 0.062 |
| `exp.return_rate_apparel` | 0.15–0.20 | 0.170 (inconclusive, 834 < 2000 cases) | 0.186 (inconclusive, 414 cases) |
| `exp.orders_per_shopper` | p50 1, p90 4–6 | p50 1, p90 4 | p50 1, p90 3 (fail; 60-day run, the brief counts 90 days) |
| R `exp.oos_failures` | 0.01–0.03 | 0.019 | 0.018 |
| `exp.sku_view_concentration` | 0.17–0.23 | 0.193 | 0.177 |
| `exp.delivery_lag` | median 3–4.5 d, p99 < 14 d | 3.16 d, 9.95 d | 3.15 d, 9.83 d |
| R `exp.bh.campaigns` | = `size` (7) | – | 7 |
| `exp.bh.min_order_hugging` | p50 $30.00–31.50 | – | $30.76 (inconclusive, 7 campaigns) |
| R `exp.bh.interference_reported` | reported | – | reported: base `referral_bonus_rejected` 24 → 43, `referral_bonus_paid` 456 → 418 |

All ten laws pass in every run. Seeds 7 and 99 give the same pass/fail pattern.

**`exp.checkout_to_order` cannot be reached by configuration.** The shopper kernel has no
checkout abandonment: a started checkout fails only when a line is out of stock (1–3%) or the
payment is declined (2–4%), so about 95% of checkouts become orders whatever the knobs. The
brief's 70–85% needs a third exit (a shopper leaving at payment), which is a kernel change
(spec §16: fix the model, not the expectation). `test_example_ecom_calibration.py` pins every
other required check and keeps a strict `xfail` on the full pass.

What was set (`specs/pack.py` defaults and literals, `datagen.toml` profile values):

| Knob | Value | Why |
|---|---|---|
| `journey.add_to_cart_p` / `checkout_p` | 0.06 / 0.12 | session → checkout 8.5%; carts average 2.6 of 5 lines |
| `journey.session_gap_alpha` / `session_gap_min_h` | 0.38 / 0.8 | heavy-tailed revisits: half of buyers order once in 90 days |
| `journey.signup_delay` | exp, mean 1 day | spreads the initial shoppers' first sessions (`full`, `abuse`) |
| `fulfil.return_p` | 0.052 | return rate 6%; apparel (0.18) about 3× |
| SKU view weights `dist.zipf(s=)` | 0.69 | top 1% of SKUs ≈ 20% of views at 2k, 5k and 50k SKUs |
| initial stock `negbinom(mean=)`, `by_weight` | 39, 11.0 | out-of-stock checkouts ≈ 2% at about 4 shoppers per SKU |
| `sample` span | 90 d | the 30-day return window and the brief's 90-day order counts need it |
| `legacy` users | 16,000 | demand per SKU close to `sample`'s, so out-of-stock lands in band |
| `legacy` `referral.monthly_budget` | 300,000 cents | tight enough that the rings drain it and ordinary claims get rejected |
| `legacy` `bounty_hunters` | size 7, `zombies_mean` 6, `arrive_span_days` 40 | label rate ≈ 1% (≈ 4% at the parity test's 3,000 users) and rings in the test split |
| `full`, `abuse` `engine.step` | 1h | 1.2M initial shoppers would overflow `max_step_rows` in a 1-day first step |

Stock is a per-SKU level, so out-of-stock depends on shoppers per SKU: `full` (2M users,
50k SKUs, 40 per SKU) is far from this calibration (a 3-day `abuse` probe saw about 40% of
checkouts fail on stock). Timer nodes: `legacy` runs with 60,000 nodes and `sample` with
300,000, so the configured 600,000 and 2,000,000 leave 10× and 6× headroom over the campaign
machines' per-command reservation (32 creates and 32+ timers).

## Run

```bash
datagen validate examples/ecommerce
datagen run      examples/ecommerce --profile sample
datagen check    examples/ecommerce --profile sample            # -> reports/sample-s42/report.html
datagen run      examples/ecommerce --profile legacy            # 16k users + bounty_hunters
datagen export   examples/ecommerce/out/legacy-s42+bounty_hunters --legacy-fraud --out data/fraud
datagen validate examples/ecommerce --dump-machines /tmp/machines   # the generated machine code
datagen schema   examples/ecommerce --format sql --dialect postgres --with-fks
datagen replay   examples/ecommerce/out/sample-s42 --preset peek
```

Today `validate`, `run --profile sample|full`, `--dump-machines`, `schema` and `replay` work.
`datagen check`, the `legacy` and `abuse` profiles (which need `bounty_hunters`) and
`export --legacy-fraud` land later in M3. `--overlay NAME` adds an overlay to the profile's
list and `--no-overlays` clears that list. Overlays never add event tables or columns (D74).
`schema --overlay NAME` adds only that overlay's cohort entity and label tables (D95).

`out/`, `reports/` and `logs/` are empty until the first run.
