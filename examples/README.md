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

## Reference datasets (Spider 2.0)

These projects model real tables from the Spider 2.0 text-to-SQL benchmark. Their `pack.py` declares the event log behind the tables, but in stage 1 it has no behavior yet. The log comes from `refdata ingest`, not `datagen run`, and `refdata roundtrip` proves it rebuilds every source table exactly. Each project also holds `specs/source.toml`, `specs/ingest.sql`, `specs/views.sql` and the benchmark's questions in `specs/queries/`. See [apps/refdata](../apps/refdata/README.md) and the research in [docs/research/spider2](../docs/research/spider2/).

| Project | Source | Nature | Licence |
|---|---|---|---|
| `olist` | E_commerce: Olist marketplace orders, payments, reviews, seller leads | real, anonymised | CC BY-NC-SA 4.0 |
| `delivery_center` | delivery_center: food-delivery orders, payments, drivers | real, anonymised | "© original authors" |
| `airlines` | Airlines: Postgres Pro demo flights, bookings, boarding passes | generated | demo database |
| `databank` | bank_sales_trading: Data Bank nodes and ledger | synthetic course data | course material |
| `cliquebait` | bank_sales_trading: Clique Bait click log | synthetic course data | course material |

```bash
uv run refdata fetch                          # once: the Spider2 SQLite files → data/spider2/
uv run refdata roundtrip examples/olist       # exit 0 = every table and saved query matches
```
