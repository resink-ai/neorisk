# E-commerce and payments, S2 slice

The slice of [`examples/ecommerce`](../ecommerce/) and [`examples/payments`](../payments/) that
the S2 engine runs (spec §18 S2). Shoppers browse in sessions as in
[`ecommerce_s1`](../ecommerce_s1/), but carts hold up to four lines. Checkout first holds the
cart total on the shopper's credit limit, then sends one reserve request per line to the line's
inventory group, waits for every answer, and commits all lines or releases the granted ones.
About 2% of shoppers abandon a fully granted checkout; their holds expire after a 10-minute TTL.
One hot inventory group (group 0) holds a small set of SKUs that about 5% of checkouts reach.
Payments, the capped bonus pool and bounty-hunter campaigns are added by later S2 tasks. See
[`specs/brief.md`](specs/brief.md).

## Model

| Partition | Kind | Holds | Processes |
|---|---|---|---|
| `user` | owner | profile, credit limit and credit hold; a cart of up to four lines and the checkout in flight (kernel locals) | `shopper` (kernel) |
| `inventory` × `sku_groups` | shard | `on_hand`, `reserved` per SKU in the group; a 64-slot hold table (kernel locals, `std.reservations`) | `inventory_desk` (kernel), `restock` (kernel, weekly, 64-SKU sub-steps) |

| Boundary | Kind | Carries | δ |
|---|---|---|---|
| `user` → `inventory` | `reserve` request, answered `granted` / `rejected` | SKU, quantity, cart line; the answer carries the hold ID and slot | 150 ms |
| `user` → `inventory` | `commit`, `release` one-way messages | the hold (SKU, quantity, hold ID, slot) | 150 ms |

Hold-table rules: a reserve takes the lowest free slot; a full table rejects the line as `busy`.
A hold's TTL is a shard timer. A commit at exactly the expiry instant is on time (messages run
before timers at an equal instant); a commit after expiry emits `stock_commit_late` and moves no
stock. Commit, release and expiry each free the slot.

Accumulator `hot_checkouts`: started checkouts with at least one line in group 0 (manifest
`accumulators.hot_checkouts`, exported steps).

Laws (required): `chk.stock_never_negative`, `chk.reserved_never_negative`,
`chk.user_hold_never_negative`, `chk.holds_resolved` (every `stock_reserved` hold is committed,
released or expired within 15 minutes).

## Run

```bash
datagen validate examples/ecommerce_s2
uv run --all-packages datagen run examples/ecommerce_s2 --profile sample
datagen schema   examples/ecommerce_s2 --format sql --dialect postgres
```

## Profiles

| Profile | Shape |
|---|---|
| `sample` | 20k users, 5,000 SKUs in 64 inventory groups, 21 days after a 3-day warm-up |

The `full` (benchmark `s2.toml`) and `pool` (benchmark `s2_pool.toml`) profiles arrive with
Task 20 of the S2 plan.

`out/`, `reports/` and `logs/` are empty until the first run.
