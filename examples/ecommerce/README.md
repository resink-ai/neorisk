# E-commerce marketplace

Shoppers browse in sessions, fill carts, and check out against per-group inventory. Orders
ship, deliver and sometimes come back. A referral program with a monthly budget pays both
sides when an invitee's first order qualifies. See [`specs/brief.md`](specs/brief.md).

## Model

| Partition | Kind | Holds | Processes |
|---|---|---|---|
| `user` | owner | profile, credit and credit hold, orders, cart scratch | `shopper_journey` (kernel), `fulfillment`, `inviter`, `invitee` (machines) |
| `inventory` × 512 | shard | `on_hand`, `reserved` per SKU in the group | reservations (`std.reservations`), `restock` (kernel, 64-SKU sub-steps) |
| `referral_pool` | shard | remaining monthly budget | claims (`std.capped_pool`) |

Checkout holds credit on the user, sends one `reserve` per cart line to each line's inventory
shard (δ = 150 ms), joins on the responses with a 30 s timeout, then commits all or releases
all. This is the "recurring shopper" trace in the design doc.

**Events (18 + 5 from std):** `user_signed_up`, `session_started`, `product_viewed`,
`cart_item_added`, `checkout_started`, `checkout_failed`, `payment_authorized`,
`payment_failed`, `order_placed`, `order_shipped`, `order_delivered`, `order_lost`,
`return_requested`, `refund_issued`, `invite_sent`, `referral_bonus_paid`,
`referral_bonus_rejected`, `restocked`; `stock_reserved`, `stock_rejected`,
`stock_committed`, `stock_released`, `stock_expired`; plus `pool_claim_granted` and
`pool_claim_rejected`.

## Overlays

| Overlay | Adds | Key parameters |
|---|---|---|
| `bounty_hunters` | Rings of one hunter + 5–30 zombies under one campaign owner; zombies order just above the $30 minimum, both bonuses are claimed, everyone goes dormant. Hidden labels: role, outcome, `label_available_at` | `size`, `zombies`, `share_device`, `arrive`, `qualify_timeout` |
| `flash_sale` | One day of 8× traffic on a few hot SKUs in one inventory group (hot-shard stress) | `day`, `category`, `hot_skus`, `lift`, `participants` |

## Run

```bash
datagen validate examples/ecommerce
datagen run      examples/ecommerce --profile sample           # ~20k users, 21 days
datagen check    examples/ecommerce --profile sample           # -> reports/sample-s42/report.html
datagen run      examples/ecommerce --profile abuse            # 2M users + both overlays
datagen run      examples/ecommerce --profile full --overlay bounty_hunters --set bounty_hunters.size=500
datagen schema   examples/ecommerce --format sql --dialect postgres --with-fks
datagen replay   examples/ecommerce/out/sample-s42 --preset peek
datagen replay   examples/ecommerce/out/full-s42+bounty_hunters --types order_placed,referral_bonus_paid \
                 --with-labels --preset kafka_dev
```

`out/`, `reports/` and `logs/` are empty until the first run.
