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

## Run

```bash
datagen validate examples/ecommerce
datagen run      examples/ecommerce --profile sample
datagen check    examples/ecommerce --profile sample            # -> reports/sample-s42/report.html
datagen run      examples/ecommerce --profile legacy            # 5k users + bounty_hunters
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
