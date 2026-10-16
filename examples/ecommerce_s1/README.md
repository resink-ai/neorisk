# E-commerce marketplace, S1 slice

The slice of [`examples/ecommerce`](../ecommerce/) that the S1 engine runs: shoppers browse in
sessions, keep a one-line cart and check out a single SKU against the inventory shard that owns
it. Every behavior is a handwritten kernel. See [`specs/brief.md`](specs/brief.md).

## Model

| Partition | Kind | Holds | Processes |
|---|---|---|---|
| `user` | owner | profile, KYC level; cart scratch, checkout and KYC flow in flight (kernel locals) | `shopper` (kernel) |
| `inventory` × `sku_groups` | shard | `on_hand`, `reserved` per SKU in the group | `inventory_desk` (kernel), `restock` (kernel, weekly, 64-SKU sub-steps) |

Read tables: `sku` (`std.catalog`: category, price, group, view weights) and `device`
(`std.devices`: built with the population, one to three per shopper, some shared).
Checkout sends a `reserve` request to the SKU's inventory shard (δ = 150 ms); the shard decides
at the request's time and answers `granted` or `rejected`. After payment the shopper sends a
one-way `commit` or `release`.

Cross-device KYC (`std.handoff`): on a desktop session of a shopper who has not done KYC and
owns a phone, a `kyc_started` handoff token is shown; the phone scans it before it expires
(300 s), a face check follows and `kyc_completed` lands back on the desktop session. A scan at
exactly the expiry instant counts as expired, and a second scan of a used token is rejected as
`already_redeemed`. Completion writes the `user_kyc` change group (`kyc_level`, `kyc_device`)
to `history/user_kyc/`.

**Events (19):** `user_signed_up`, `session_started`, `product_viewed` (12 property columns),
`cart_item_added`, `checkout_started`, `checkout_failed`, `payment_authorized`,
`payment_failed`, `order_placed`, `kyc_started`, `kyc_handoff_redeemed`,
`kyc_handoff_rejected`, `kyc_handoff_expired`, `kyc_completed`; from the inventory shards
`stock_reserved`, `stock_rejected`, `stock_committed`, `stock_released`, `restocked`.

**History:** `user_kyc` (one row per completed KYC).

## Run

```bash
datagen validate examples/ecommerce_s1
datagen run      examples/ecommerce_s1 --profile sample          # 20k users, 21 days
datagen run      examples/ecommerce_s1 --profile full            # the S1 benchmark shape
datagen schema   examples/ecommerce_s1 --format sql --dialect postgres
datagen replay   examples/ecommerce_s1/out/sample-s42 --preset peek
datagen replay   examples/ecommerce_s1/out/sample-s42 --types order_placed --last 100
```

`out/`, `reports/` and `logs/` are empty until the first run.
