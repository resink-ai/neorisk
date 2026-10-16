# Centralized crypto exchange (spot)

Traders register, pass KYC, deposit crypto, trade 40 spot pairs against per-symbol order books,
and withdraw. Market makers quote post-only ladders around an exogenous reference price and
lean against their inventory; retail traders come back when prices move. See
[`specs/brief.md`](specs/brief.md).

## Model

| Partition | Kind | Holds | Processes |
|---|---|---|---|
| `trader` | owner | KYC level, `available` and `held` per asset, order mirror, deposits, withdrawals | `trader_activity`, `market_maker`, `funding`, `order_settlement` (kernels), `onboarding`, `api_access`, `deposit`, `withdrawal` (machines) |
| `book` × 40 | shard | price levels with resting orders and each order's remaining lock, the active taker, book sequence | `match` (kernel, 64-fill sub-steps), `ticker` (kernel, every minute) |

Read inputs: `asset` (ledger quantum, confirmations, withdrawal fee), `symbol` (tier, lot,
`notional_div`), `device`, `ip`, `address`, and the `ref_price` timeline (jump diffusion with a
common market factor), shared read-only by traders and books.

**Hold → fill → settle.** The trader checks its own `available`, moves the order's lock to
`held` (quote for a buy, base for a sell; a limit buy locks `price × qty` rounded up), and
sends `place` to the symbol's book with the lock in the immutable payload (δ = 2 ms
order-entry latency). The book matches against that lock only: price/time priority, at most 64
maker touches per invocation, then a same-time continuation at top priority. FOK runs a
read-only preflight first; post-only orders that would cross are rejected; self-trade
prevention cancels the resting order. Each fill goes to both traders as a `fill` notification
(δ = 1 ms, FIFO with the responses on the same book-trader pair). The trader settles on
receipt: `held -= lock_used`, `available += received - fee`. When an order closes, one `done`
notification returns what is left of the lock. The book never reads a balance and the trader
never reads the book.

Amounts are int64 at a per-asset ledger quantum (BTC in satoshi, USDT in 1e-6, ETH at 1e-8);
`price × qty` uses a 128-bit intermediate, so buyer and seller see the same quote amount.

**Fidelity switch.** `matching.fidelity = "matched"` (default) matches traders against each
other with market makers providing liquidity. `"external_liquidity"` drops the market makers
and fills takers against an exogenous liquidity curve around the reference price; resting
limits fill when the curve crosses them (swept by `ticker`). The other leg goes to the
`external_flow` accumulator.

**Events (19):** trader side `trader_registered`, `login`, `kyc_upgraded`, `api_key_created`,
`deposit_detected`, `deposit_credited`, `order_submitted`, `balance_settled`,
`withdrawal_requested`, `withdrawal_approved`, `withdrawal_rejected`, `withdrawal_sent`; book
side `order_accepted`, `order_rejected`, `order_cancelled`, `order_filled`, `cancel_rejected`,
`trade`, `book_ticker`. Partial fills are `trade` rows; `order_filled` and `order_cancelled`
close an order.

## Overlays

| Overlay | Adds | Key parameters |
|---|---|---|
| `wash_traders` | Rings of one organizer + 2–6 accounts under one ring owner, sharing devices, IPs and withdrawal addresses. Each round one account rests a GTC at the reference price in an illiquid pair and another takes it with an IOC; cash out at the end. Hidden labels: role (`organizer`, `account`), outcome, `label_available_at` | `size`, `accounts`, `share_device`, `share_ip`, `symbol_tier`, `round_every`, `rounds`, `round_notional_usdt` |
| `pump_and_dump` | Schemes of one organizer + 3–15 insiders under one scheme owner accumulate a low-cap token, market-buy at a scheduled time, then dump into a crowd of existing retail followers (a share of active retail, linked to a scheme). Hidden labels: role (`organizer`, `insider`, `follower`), outcome | `size`, `insiders`, `pump_after`, `followers`, `follower_join_p`, `follower_exit_p`, `dump_span` |

Both overlays reach the book shards through the exposed `place_order` / `cancel_order`
actions, so base trades in the target pairs change and are reported as interference.

## Run

```bash
datagen validate examples/crypto_exchange
datagen run      examples/crypto_exchange --profile sample           # 20k traders, 40 books, 7 days
datagen check    examples/crypto_exchange --profile sample           # -> reports/sample-s42/report.html
datagen run      examples/crypto_exchange --profile external         # external_liquidity, no MMs
datagen run      examples/crypto_exchange --profile abuse            # 1M traders + both overlays
datagen run      examples/crypto_exchange --profile full --overlay wash_traders --set wash_traders.size=60
datagen schema   examples/crypto_exchange --format sql --dialect postgres --with-fks
datagen replay   examples/crypto_exchange/out/sample-s42 --preset peek
datagen replay   examples/crypto_exchange/out/full-s42+wash_traders --types trade,order_submitted \
                 --with-labels --preset kafka_dev
```

The `kafka_dev` preset keys every topic by `partition_id`: trader events by trader, book
events by symbol, so each trader's history and each symbol's tape stay ordered.

`out/`, `reports/` and `logs/` are empty until the first run.
