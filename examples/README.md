# Examples

Each folder is a self-contained **datagen project** for one business. A project is the
spec an agent writes and a human reviews, plus three folders that `datagen` fills.

> These specs are written against the architecture in
> `docs/superpowers/specs/2026-10-15-agentic-event-simulator-architecture.html`.
> The engine they target is not built yet; the specs are the design's worked examples.

| Project | What it simulates | Partitions | Overlays |
|---|---|---|---|
| [`ecommerce/`](ecommerce/) | Shoppers, carts, multi-SKU checkout, fulfillment, returns, referrals | owner `user` · shards `inventory`, `referral_pool` | `bounty_hunters`, `flash_sale` |
| [`ecommerce_s1/`](ecommerce_s1/) | S1 slice; superseded by `ecommerce/` at M3. Sessions, one-line carts, single-SKU checkout | owner `user` · shard `inventory` | — |
| [`ecommerce_s2/`](ecommerce_s2/) | S2 slice; superseded by `ecommerce/` and `payments/` at M3/M4. Multi-SKU carts with reservations, payments with refunds and disputes, a capped bonus pool, bounty-hunter campaigns | owners `user`, `payment`, `campaign` · shards `inventory`, `pool` | — |
| [`payments/`](payments/) | Card payments (acquirer view): risk, 3-D Secure, auth, capture, refund, dispute, ledger | owners `cardholder`, `payment` · shard `merchant_risk` | `card_testing`, `friendly_fraud` |
| [`crypto_exchange/`](crypto_exchange/) | Spot CEX: KYC, deposits, per-symbol order books, trades, withdrawals | owner `trader` · shard `book` per symbol | `wash_traders`, `pump_and_dump` |
| [`layer1/`](layer1/) | Account-based L1: wallets, EIP-1559 blocks, reverts, token/DEX/NFT logs, airdrop | owner `wallet` · shard `chain` (one, global) | `airdrop_sybils`, `mint_rush` |
| [`social/`](social/) | Microblogging: weekly follow graph, posts, cascades, likes, replies, moderation | owners `user`, `cascade` · shard `moderation` | `bot_farm` |

## Project layout

```
examples/<business>/
  README.md             # what is simulated, how to run, what each overlay adds
  datagen.toml          # project file: run profiles, budgets, overlay settings, replay presets
  specs/                # everything reviewed in a PR; nothing generated
    brief.md            #   the business brief in plain language: actors, flows, rates, sources
    expectations.yaml   #   statistical targets and laws, each traced to the brief or a public spec
    pack.py             #   tables, events, partitions, boundaries, processes, checks
    kernels.py          #   handwritten Numba kernels for behavior a state machine can't express
    overlays/*.py       #   optional groups with distinct behavior (cohorts), same event schema
  out/                  # datasets, one folder per run          (generated, git-ignored)
  reports/              # check reports, one folder per run     (generated, git-ignored)
  logs/                 # structured run logs, one file per run (generated, git-ignored)
```

`specs/` is the only folder an agent edits. `out/`, `reports/` and `logs/` are empty in the
repo and filled by `datagen`; only their `.gitkeep` files are tracked.

## Running a project

Every command takes the project folder. Profiles come from `datagen.toml`.

```bash
datagen validate examples/ecommerce                           # plan, partitions, latencies, memory caps
datagen run      examples/ecommerce --profile sample          # small, fast run for the authoring loop
datagen check    examples/ecommerce --profile sample          # laws + expectations -> reports/
datagen run      examples/ecommerce --profile full --overlay bounty_hunters --set bounty_hunters.size=500
datagen schema   examples/ecommerce --format sql --dialect postgres
datagen replay   examples/ecommerce/out/sample-s42 --first 100
datagen replay   examples/ecommerce/out/sample-s42 --preset kafka_dev
```

A run named `<profile>-s<seed>` writes:

| Where | What |
|---|---|
| `out/<profile>-s<seed>/` | the dataset: `manifest.json`, `schema/`, `_index/`, `events/<type>/date=…/step-*.parquet`, `entities/`, `labels/`, … |
| `reports/<profile>-s<seed>/` | `report.html`, `checks.json`, failing-row extracts |
| `logs/<profile>-s<seed>-<utc>.jsonl` | one JSON object per log line: steps, rounds, rates, caps, warnings |

Runs are deterministic, so rerunning the same profile and seed reproduces the same files;
`datagen run` refuses to overwrite an existing run folder unless `--force` is given.
Overlays and `--set` overrides are part of the run name: `full-s42+bounty_hunters` and the
exact overrides are recorded in `manifest.json`.

## Spec vocabulary (cheat sheet)

All five projects use the same small API. Five primitives: **Table, Process, Action, Source, Check**.

```python
from neorisk_simkit.spec import Pack, Overlay, dist, std, law, stat
from neorisk_simkit.spec.types import i16, i32, i64, f64, boolean, text, cat, ref, amount, ts, opt

def define(p: Pack, cfg: Config) -> None:
    # Tables: entity/state tables and append-only event tables
    p.table("user", key="user_id", cols={...}, mutable=True)         # per-owner state rows
    p.table("sku", key="sku_id", cols={...}, mutable=False)          # read-only input
    p.event("order_placed", owner="user", doc="...", cols={...})     # one exported event table

    # Partitions: every piece of mutable state belongs to exactly one
    p.owner("user", table="user", max_live=cfg.users)                # owner partition per row
    p.shard("inventory", key="sku_group", n=cfg.sku_groups, state={...})

    # Boundaries: immutable request/response with a minimum latency δ > 0
    p.request("reserve", frm="user", to="inventory", payload={...},
              responses=("granted", "rejected"),
              latency=dist.shifted_lognormal(min_ms=200, median_ms=320))

    # Sources: populations, arrivals, exogenous timelines, graphs
    p.population("user", n=cfg.users, attrs={...}, arrivals=dist.poisson_daily(...))

    # Processes: a handwritten kernel or a state machine, living in one partition
    p.process("shopper_journey", owner="user", kernel=k.shopper_journey, config=cfg.journey)
    m = p.machine("fulfillment", owner="user", start=p.on_event("order_placed"), initial="placed")
    m.state("placed", branch={...}, timer={...})

    # Checks: laws (exact) here; statistical expectations live in expectations.yaml
    p.check("chk.stock_never_negative", law.never_negative("inventory.on_hand"), required=True)
```

- **Kernels** (`kernels.py`) follow the action interface: validate → `out.reserve(...)` every
  resource → commit. `reject(...)` and `RETRY` are legal only before the first write. Random
  draws go through `ctx.rng.<dist>(site=N, ...)` with a distinct `site` per draw.
- **Messages between partitions:** a shard answers a request with
  `out.respond(cmd, "<response>", **payload)`. One-way messages are declared with
  `p.message(name, frm=, to=, payload=, latency= | delivery="next_step")` and sent with
  `out.send_<name>(t, to=..., **payload)`; owner-to-owner messages must use
  `delivery="next_step"`. `std.send_owner` is the state-machine form.
- **State machine operations:** `branch`, `timer`, `repeat`, `until … then`, `spawn`, `join`,
  `request`, `then` (sequential, not atomic).
- **Overlays** (`overlays/*.py`) define `apply(o: Overlay, size=..., ...)`, add a `cohort`,
  `suppress` base processes for its members, drive base-pack actions only, and add hidden
  `labels/` rows. They never add event columns.
- **`std`** recipes: ledger, holds, reservations, handoff, spawn/join, refs, graph, timelines,
  capped pools. **`law`** builds exact checks; **`stat`** builds statistical ones.
- The four domain projects use helpers beyond this cheat sheet (order-book levels, a tx pool,
  graph epochs, a ledger, more `law`/`stat` builders). They are part of the design exercise:
  when the engine is built, helpers used by two or more projects move into `std`, and the
  rest become project-local code in `kernels.py`.
