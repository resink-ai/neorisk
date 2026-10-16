# E-commerce marketplace, S1 slice

The slice of [`examples/ecommerce`](../ecommerce/) that the S1 engine runs: shoppers browse in
sessions, keep a one-line cart and check out a single SKU against the inventory shard that owns
it. Every behavior is a handwritten kernel. See [`specs/brief.md`](specs/brief.md).

## Model

| Partition | Kind | Holds | Processes |
|---|---|---|---|
| `user` | owner | profile; cart scratch, checkout in flight (kernel locals) | `shopper` (kernel) |
| `inventory` × `sku_groups` | shard | `on_hand`, `reserved` per SKU in the group | `inventory_desk` (kernel), `restock` (kernel, weekly, 64-SKU sub-steps) |

Read tables: `sku` (`std.catalog`: category, price, group, view weights) and `device`
(`std.devices`: built with the population, one to three per shopper, some shared).
Checkout sends a `reserve` request to the SKU's inventory shard (δ = 150 ms); the shard decides
at the request's time and answers `granted` or `rejected`. After payment the shopper sends a
one-way `commit` or `release`.

**Events (14):** `user_signed_up`, `session_started`, `product_viewed` (12 property columns),
`cart_item_added`, `checkout_started`, `checkout_failed`, `payment_authorized`,
`payment_failed`, `order_placed`; from the inventory shards `stock_reserved`, `stock_rejected`,
`stock_committed`, `stock_released`, `restocked`.

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
