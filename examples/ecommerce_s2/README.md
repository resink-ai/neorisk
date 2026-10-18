# E-commerce and payments, S2 slice

The slice of [`examples/ecommerce`](../ecommerce/) and [`examples/payments`](../payments/) that
the S2 engine runs (spec §18 S2). Shoppers browse in sessions as in
[`ecommerce_s1`](../ecommerce_s1/), but carts hold up to four lines. Checkout first holds the
cart total on the shopper's credit limit, then sends one reserve request per line to the line's
inventory group, waits for every answer, and commits all lines or releases the granted ones.
About 2% of shoppers abandon a fully granted checkout; their holds expire after a 10-minute TTL.
One hot inventory group (group 0) holds a small set of SKUs that about 5% of checkouts reach.
Successful checkouts and bill payments create payments, each its own owner: authorized or
declined, then captured or expired (capture races expiry), with double-entry postings and a
platform fee; captured payments get refunds (held, then settled or failed, with idempotency
keys) and disputes. A referred shopper's first qualifying order claims a bonus from one global
capped pool, which bounty-hunter campaigns drain too. See [`specs/brief.md`](specs/brief.md).

## Model

| Partition | Kind | Holds | Processes |
|---|---|---|---|
| `user` | owner | profile, credit limit and credit hold; a cart of up to four lines and the checkout in flight (kernel locals) | `shopper` (kernel) |
| `payment` | owner, created | user, checkout (null for a bill), amount, method, source (`checkout` or `bill`; not `origin`, which `entities/` reserve); the lifecycle status, dispute window, refund hold, idempotency keys and dispute state (kernel locals) | `payment_life` (kernel) |
| `campaign` | owner | one bounty hunter's zombie count; members left, the member in flight, paid and denied counts (kernel locals) | `hunter` (kernel) |
| `inventory` × `sku_groups` | shard | `on_hand`, `reserved` per SKU in the group; a 64-slot hold table (kernel locals, `std.reservations`) | `inventory_desk` (kernel), `restock` (kernel, weekly, 64-SKU sub-steps) |
| `pool` × 1 | shard | `remaining`, `granted` (`std.capped_pool`) | `pool_desk`, `campaign_desk` (kernels) |

| Boundary | Kind | Carries | δ |
|---|---|---|---|
| `user` → `inventory` | `reserve` request, answered `granted` / `rejected` | SKU, quantity, cart line; the answer carries the hold ID and slot | 150 ms |
| `user` → `inventory` | `commit`, `release` one-way messages | the hold (SKU, quantity, hold ID, slot) | 150 ms |
| `user` → `pool` | `claim` request, answered `granted` / `rejected` | the bonus amount | 200 ms |
| `campaign` → `pool` | `campaign_claim` request, answered `granted` / `rejected` | the bonus amount | 200 ms |

Hold-table rules: a reserve takes the lowest free slot; a full table rejects the line as `busy`.
A hold's TTL is a shard timer. A commit at exactly the expiry instant is on time (messages run
before timers at an equal instant); a commit after expiry emits `stock_commit_late` and moves no
stock. Commit, release and expiry each free the slot.

Payments: a successful checkout (`checkout_succeeded.payment_id`) or a bill
(`bill_payment_started`, about every 20 days per shopper) creates a `payment` owner, which starts
at its creation time: `payment_declined` (3%, retires) or `payment_authorized`. An authorized
payment schedules its expiry (`pay.auth_expiry_s`, 7 days) and, 93% of the time, a capture after
a lognormal delay (median 1 h). Whichever comes first wins; at an equal instant expiry runs
first. `payment_captured` charges `pay.fee_bps` (290) as a platform fee and keeps the payment
live until its dispute window (`pay.dispute_window_days`, 90) closes; the expiry timer is never
cancelled, so a payment also lives until its expiry instant.

Refunds (§09): a captured payment requests a refund with probability `pay.refund_p` (4%) after
`pay.refund_gap` (mean 9 days), and each request may schedule another (same probability, at most
`pay.max_refunds` = 3). Each request gets a new `refund_id` (its idempotency key) and holds
`min(left, wanted)` against `left = captured - refunded - held` (`refund_requested`); after
`pay.refund_settle` (median 1 day) the processor commits the hold (`refund_settled`, 98%) or
releases it (`refund_failed`). A request while a dispute is open is `refund_rejected`
`dispute_open`; with nothing left, or after a lost dispute, `nothing_left`. A merchant retry of
the same key (`pay.duplicate_p`, 5%, ~30 s later) emits `refund_replayed` with the first result
(`requested` or `rejected`) and changes nothing. Disputes (D51, a sub-lifecycle in the payment
kernel): `pay.dispute_p` (0.6%) of captures open a dispute after `pay.dispute_delay` (gamma, mean
21 days) if that is inside the window, for the remainder no refund has claimed,
`captured - refunded - held` (`dispute_opened`); with nothing left no dispute opens. Refunds
already held when it opens still settle or fail on the processor's delay, so settled refunds
plus a lost dispute never exceed the capture. It resolves after `pay.dispute_resolve` (gamma,
mean 30 days), `dispute_won` with `pay.dispute_win_p` (55%) or `dispute_lost`. A payment has at
most `pay.max_refunds` refund requests, at most 4 (one idempotency slot each; the pack refuses
more).

Postings `ledger` (`postings/ledger/`, D45): authorization debits `customer_funds` and credits
`customer_held`; capture debits `customer_held` and credits `merchant` and `platform_fees`;
expiry returns `customer_held` to `customer_funds`; a settled refund debits `merchant` and
credits `refunds_payable`; a dispute moves the amount from `merchant` to `dispute_reserve`, and
back to `merchant` (won) or on to `customer_funds` (lost). Every commit balances.

Bonus pool (§07): the `pool` shard starts at `pool_cap` ($20,000). A referred shopper's first
successful checkout (`journey.min_order` = $20 or more) sends one `claim` for
`journey.invitee_bonus` ($10); the shopper only learns of it from the answer
(`referral_bonus_paid` / `referral_bonus_denied`). Claims run in the pool's own heap, so the cap
is exact: a claim is granted whole if it fits what is left (`bonus_granted`, with
`remaining_after`), else rejected (`bonus_rejected`); there are no partial grants. Both sources
are recorded (`source` = `user` or `campaign`).

Bounty hunters (D52): a `campaign` owner is one hunter and its zombie members. The population
is `max(1, round(users × hunt.share / (1 + hunt.zombies_mean)))` campaigns (20% at the start,
the rest arriving flat), so hunters plus zombies approximate `hunt.share` (1%) of users. A
campaign draws `zombies ~ geometric(mean 12)` (at most 30 used, `campaign_started`); every
`hunt.member_gap` (mean 15 min) a member joins (`member_joined`, a `member_id`), and 85% place
one qualifying $21 order (`member_ordered`) and claim `hunt.bonus` ($10) through
`campaign_claim`. The answer is recorded per member (`member_bonus_paid` /
`member_bonus_denied`); after the last member the campaign emits `campaign_finished` (paid and
denied counts) and retires. Hunters compete with normal referrals for the same pool, so once it
is drained normal users are rejected too.

Accumulators: `hot_checkouts` (started checkouts with at least one line in group 0) and
`platform_fees` (Σ capture fees); manifest `accumulators`, exported steps.

Laws (required): `chk.stock_never_negative`, `chk.reserved_never_negative`,
`chk.user_hold_never_negative`, `chk.holds_resolved` (every `stock_reserved` hold is committed,
released or expired within `desk.hold_ttl_s` plus 5 minutes: 15 minutes for the default
600 s TTL), `chk.postings_balanced` (`ledger` debits equal credits
per commit), `chk.one_capture` (at most one `payment_captured` per payment),
`chk.refunds_le_captured` (Σ `refund_settled.amount` ≤ `payment_captured.amount` per payment),
`chk.refund_settles_once` (at most one `refund_settled` per refund ID),
`chk.one_grant_per_claim` (at most one `bonus_granted` per claim ID), `chk.pool_cap`
(Σ `bonus_granted.amount` ≤ `pool_cap` over the run), `chk.pool_never_negative`
(`pool.remaining` ≥ 0).

## Run

```bash
uv run --all-packages datagen validate examples/ecommerce_s2
uv run --all-packages datagen run      examples/ecommerce_s2 --profile sample
uv run --all-packages datagen schema   examples/ecommerce_s2 --format sql --dialect postgres
```

## Profiles

| Profile | Shape |
|---|---|
| `sample` | 20k users, 5,000 SKUs in 64 inventory groups, 21 days after a 3-day warm-up; room for 60k live payments (`payments_live_ratio = 3`: none outlives its 90-day dispute window in 24 days) |
| `full` | [`benchmarks/s2.toml`](../../benchmarks/s2.toml): 20M users, 100,000 SKUs in 512 inventory groups, 90 days after the 14-day warm-up; first sessions spread over a week (`journey.signup_delay`). Calibrated (Task 21): one session per shopper in the run (`journey.session_gap_min_h = 5000`) with one view (`journey.views_mean = 1`), `journey.checkout_p = 0.2`, `journey.hot_pick_p = 0.05`, bills every 50 days on average (`journey.bill_gap`), so ~30M payments come mostly from bills; room for 36M live payments (`payments_live_ratio = 1.8`: 1.69 payments per user over the run, each live to its end), `budget.max_checker_keys = 80M` and `budget.memory = "40GB"` (the caps total 34.8 GiB); the base engine pools |
| `pool` | [`benchmarks/s2_pool.toml`](../../benchmarks/s2_pool.toml): 2M users, 20,000 SKUs in 128 inventory groups, 30 days after a 3-day warm-up; bounty hunters at `hunt.share` = 1% of users. Calibrated (Task 21): one short session per shopper (`journey.session_gap_min_h = 2000`, `journey.views_mean = 1.5`), every view adds a cart line (`journey.add_to_cart_p = 1.0`), half the sessions with a cart check out (`journey.checkout_p = 0.5`), bills pushed past the run (`journey.bill_gap` mean 10 years), 5% of shoppers referred (`referred_share = 0.05`; each first qualifying order claims from the pool), `pool_cap = 17_000_000` (the pool drains on exported day 20.6); room for 1M live payments (`payments_live_ratio = 0.5`); engine pools sized for 2M users (9M timer nodes, 2M payload rows, 2M messages per step, 200k admissions per step) and 6-hour first steps (`engine.step`) |

Measured results, the calibration runs and the gates' verdicts are in
[`benchmarks/README.md`](../../benchmarks/README.md).

`out/`, `reports/` and `logs/` are empty until the first run.
