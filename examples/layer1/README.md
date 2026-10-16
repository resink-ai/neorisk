# Account-based layer-1 chain

Wallets sign transactions and learn their fate from receipts; one canonical chain includes them
in 12-second blocks under an EIP-1559 fee market. Included transactions always pay gas and
advance the nonce; reverted ones move no value and emit no logs. A few contracts (tokens,
constant-product pools behind a router, NFT collections, bridges, an airdrop distributor)
produce the logs. See [`specs/brief.md`](specs/brief.md).

## Model

| Partition | Kind | Holds | Processes |
|---|---|---|---|
| `wallet` | owner | profile; *beliefs*: next nonce, balance and token view, base fee, in-flight holds; exchange payout queue | `wallet_activity`, `cex_hot_wallet` (kernels), `onboarding` (machine) |
| `chain` × 1 | shard | every account's balance, nonce and token balances; NFT mint counts; airdrop eligibility; pending pool; block in progress | `admit_tx`, `query_account`, `query_quote` (request handlers), `build_block`, `expire_pending` (kernels, 64-tx sub-steps) |

**Request and receipt flow.** A wallet uses its believed nonce, sets `max_fee = 2 × believed
base fee + tip`, places a hold for the worst-case cost (`gas_limit × max_fee + value`) on its
own balance view, emits `tx_submitted` and sends `submit_tx` to the chain (propagation δ =
200 ms). `admit_tx` drops it at once if it can't enter the pool; otherwise it waits. At each
slot `build_block` takes pending txs in priority-fee order, one nonce at a time per sender, and
runs the envelope: validity first (nonce matches, balance covers the worst case; else
`tx_dropped`), then gas (base fee burned, tip to the slot's fee recipient, nonce + 1), then
effects only on success. The receipt is the deferred response to `submit_tx`, arriving 100 ms
or more after the decision; `apply_receipt` runs in the wallet before any process sees it,
releases the hold and resets the wallet's view from the chain's numbers. Swaps first ask
`query_quote` (δ = 80 ms) and submit with a slippage limit, so prices that move before
inclusion cause realistic reverts. Wallets never read chain state; joint constraints are the
owner-side hold plus the chain's own check.

**Hot shard.** All inclusion goes through the one `chain` shard, so it serializes, exactly as a
real chain does. That is the point: this pack is a shard-dominated workload like S2-pool, and
its throughput is bounded by the chain loop (fixed 64-tx sub-steps, about 25 per full block at
30M gas). Wallets still run in parallel between their requests.

**Amounts.** One declared quantum, 10⁶ wei (0.001 gwei), checked int64: 1 ETH = 10¹² quanta,
9.2M ETH per account at most (validate checks the genesis). Gas prices use the same quantum, so
`gas_used × price` is exact. Supply-wide sums are accumulated by the checker in 128 bits.

**Events (13):** `wallet_created`, `cex_withdrawal_requested`, `tx_submitted`,
`receipt_received` (wallet side); `tx_included`, `tx_dropped`, `block_produced`, `transfer`,
`token_transfer`, `swap`, `nft_minted`, `bridge_deposit`, `airdrop_claimed` (chain side, at the
block's time). Logs carry `sender`, `block_number` and `log_index`.

**Laws:** nonce sequence +1 per sender with no gaps, native and token balances never negative,
native conservation (balances + burned = genesis + issuance) and per-token conservation, block
gas ≤ limit and = sum of tx gas, base fee follows EIP-1559, base fee ≤ effective price ≤ max
fee, reverted txs have no transfers or logs, every submitted tx included or dropped once (or
pending at the horizon), receipts after decisions, NFT supply caps, one airdrop claim per
account.

## Overlays

| Overlay | Adds | Key parameters |
|---|---|---|
| `airdrop_sybils` | Campaigns of one funder + one collector + 10–400 sybil wallets under one campaign owner. The funder withdraws from an exchange and fans out (or peel-chains) funding; every sybil runs the campaign's script of router swaps (no slippage limit, fixed tip) before the snapshot, claims, sells or forwards the tokens, and sweeps its ETH to the collector, which cashes out to its exchange. Claims share the distributor's balance with everyone. Hidden labels: role, outcome, `label_available_at` | `size`, `sybils`, `peel_chain_share`, `swaps`, `consolidate`, `arrive` |
| `mint_rush` | One hyped NFT drop: existing wallets and most bots mint with high tips for about an hour; blocks fill, the base fee climbs, ordinary low-cap txs expire, most mints revert as sold out (hot-shard and fee-market stress) | `at`, `supply`, `participants`, `bot_participants`, `tip` |

## Run

```bash
datagen validate examples/layer1
datagen run      examples/layer1 --profile sample           # 40k wallets, scaled 300k-gas blocks, 30 days
datagen check    examples/layer1 --profile sample           # -> reports/sample-s42/report.html
datagen run      examples/layer1 --profile abuse            # 4M wallets + both overlays
datagen run      examples/layer1 --profile full --overlay airdrop_sybils --set airdrop_sybils.size=80
datagen schema   examples/layer1 --format sql --dialect postgres --with-fks
datagen replay   examples/layer1/out/sample-s42 --preset peek
datagen replay   examples/layer1/out/full-s42+airdrop_sybils --types tx_included,transfer,airdrop_claimed \
                 --with-labels --preset kafka_dev        # topics l1.<event_type>, key = sender
```

`out/`, `reports/` and `logs/` are empty until the first run.

## Modeling choices

- **Receipts are deferred responses.** A transaction's answer comes when a block decides it,
  not after a fixed latency; `submit_tx` declares `deferred=True` with a propagation minimum and
  a reply minimum, so every hop still has δ > 0 and the safe horizon still holds.
- **The pending pool is a declared queue, not a mempool model:** no gossip, no replacement or
  cancel, a per-sender slot limit and a 3 h TTL. Expiry reasons tell nonce gaps from priced-out
  txs.
- **Contracts are profiles, not EVM:** gas means and spreads per contract, state-driven reverts
  (slippage, sold out, token balance, airdrop rules), a small residual "contract logic" revert
  rate, and out-of-gas when the wallet's estimate was low.
- **Missed slots** produce no block and leave the base fee unchanged; issuance is a per-block
  credit to validator accounts, the only ETH that enters the system.
- **Sample runs use a scaled chain** (gas limit proportional to the population) so the fee market
  clears near its target; the laws read the configured limit.
