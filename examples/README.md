# Example projects

Each folder is a datagen project: `datagen.toml` (run profiles), `specs/` (the only folder an agent edits: `brief.md`, `pack.py`, `expectations.yaml`, `overlays/`), and the git-ignored `out/` and `reports/`. How to write one: [AGENTS.md](AGENTS.md).

| Project | Domain | What it exercises | Overlays |
|---|---|---|---|
| `ecommerce` | Shoppers, referrals | Owners and shards, multi-SKU reservations with a TTL and a hot SKU group, a capped monthly bonus pool, `bench`'s legacy export | `bounty_hunters` (shares the pool and stock), `window_shoppers` (shares nothing) |
| `payments` | Card payments | Credit holds, capture/expiry races, idempotent captures, refunds that hold the refundable amount, disputes as a child process, merchant settlement shards, label delay | `card_testing` |
| `payments_subscriptions` | Subscription billing | The whole lifecycle as a state machine: trial, renewals, dunning, churn | |
| `crypto_exchange` | Spot exchange | An order-book shard per symbol with isolated sub-balances, price-time matching, GTC/IOC/FOK with a read-only preflight, cancels; checked against a reference matcher | |
| `layer1` | A chain's envelope | One chain shard building blocks: nonce and fee validity, drops, reverts that pay gas but move nothing; checked against a reference envelope | |
| `social` | A follow graph | Degree-corrected follows with reciprocity as a shared input; cascades owned by their root post with fan-out and per-cascade dedup | |

```bash
uv run datagen run examples/payments --profile sample --overlay card_testing
uv run datagen check examples/payments/out/sample-s7+card_testing
```
