# datagen

Command line for the e-commerce event simulator (`neorisk_simkit.ecommerce`, built on
`neorisk_simkit.sim`, a heap-based discrete-event loop in plain Python).

```bash
uv run datagen run --out data/legacy-run [--users 5000] [--days 60] [--seed 7]
uv run datagen export data/legacy-run --legacy-fraud --out data/fraud
```

`run` writes one parquet file per table, plus `manifest.json`:
- **Event tables:** `user_signed_up`, `session_started`, `product_viewed`, `order_placed`, `order_returned`, `address_changed`, `referral_bonus_paid` and `referral_bonus_rejected`.
- **Entity tables:** `users`, `devices`, `skus` and `labels`. The labels are the bounty-hunter rings' ground truth.

Shoppers sign up, browse, check out, return orders and move region. A referred shopper's first qualifying order pays its inviter a bonus from a monthly budget, after a delay. Bounty hunters run rings of zombie accounts on shared devices, all invited by the hunter, and cash the bonuses out.

Cost is O(E log Q) time and O(E) memory, where E is the number of events emitted and Q is the number of pending events. That is linear in users for a fixed span. `libs/simkit/tests/test_simkit_sim.py` asserts this as a scaling ratio, not as an absolute time.

`export --legacy-fraud` writes the shape `bench` reads:
- **`events.parquet`:** orders as `event_type` 0 and inviter bonuses as `event_type` 1, with the invitee as `user_id`. Attributes are integer codes; `user_state` is the user's region as of the event; `label` marks rows whose user, or whose inviter on invite rows, is a ring member.
- **`golden.parquet`:** strictly-past rolling features (`u_amt_*`, `dev_users_*`, `inv_bonus_*`, `invr_bonus_*`, `amt_ratio_30d`) plus the ground truth (`invitee_is_zombie`, `actor_role`, `score`).
- **`meta.json`:** run metadata.

It exits 2 without `--legacy-fraud`.
