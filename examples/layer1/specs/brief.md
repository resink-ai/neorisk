# Brief: account-based layer-1 chain

An Ethereum-like, account-based public chain: externally owned wallets sign transactions, a
single canonical chain includes them in 12-second blocks under an EIP-1559 fee market, and a
small set of contracts (tokens, AMM pools behind one router, NFT collections, bridges, one
airdrop distributor) produce logs. We want transaction, receipt and log data realistic enough
to build and benchmark wallet-clustering, sybil-detection and fee-forecasting models, including
an airdrop-farming campaign that the base population doesn't contain.

## Actors

- **Wallets (EOAs).** Sign and submit transactions, learn outcomes from receipts, and keep
  their own view of their nonce and balance; they never see chain state directly, only what
  receipts and RPC queries return. Four kinds:
  - *Retail* (about 88%): a few sessions a month, one to three transactions per session, wait
    for each receipt before the next. Low priority fees.
  - *Traders* (about 11.5%): daily sessions, more swaps, a couple of transactions in flight.
  - *Bots* (about 0.5%): sessions every minute or two, dozens of swaps per session with tight
    slippage, high priority fees, up to 16 transactions in flight. Most reverts come from them.
  - *Exchange hot wallets* (about a dozen): pay out user withdrawals in batches and receive
    deposits. Huge balances.
- **Balances.** Heavy-tailed: the median funded retail wallet holds about 0.05 ETH, the top 1%
  of non-exchange wallets hold most of the supply.
- **Contracts.** Eight ERC-20-style tokens, one constant-product pool per token (ETH/token,
  0.3% fee) reached through one router, about 40 NFT collections with staggered mint openings
  and fixed supply, four bridge contracts to rollups, and one airdrop distributor.
- **Chain.** One canonical chain. A block every 12-second slot (about 0.8% of slots are
  missed), gas limit 30M, gas target 15M. Builders order by priority fee. Priority fees go to
  the slot's fee recipient; base fees are burned; a small consensus-layer issuance is credited
  to validator accounts each block.

## Flows

1. **Onboarding.** New wallets appear daily. About 70% ask an exchange for a withdrawal right
   away (lognormal, median 0.3 ETH), which the exchange pays out within minutes to hours; the
   rest are funded by peers or stay empty.
2. **Session.** Wallets sync their balance by RPC when their view is older than a day, then
   send a burst of transactions. The type mix is set by the wallet kind (below).
3. **Submission.** The wallet uses its believed next nonce, sets `max_fee = 2 × believed base
   fee + tip`, and holds the worst-case cost against its believed balance. If the believed base
   fee is above the wallet's personal ceiling it waits (demand reacts to fees). Transactions
   propagate to the chain in 200 ms or more.
4. **Swaps.** The wallet asks for a quote (RPC, 80 ms or more), then submits with a slippage
   limit. Prices move between quote and inclusion, so some swaps revert.
5. **Inclusion.** Each block takes pending transactions in priority-fee order, one nonce at a
   time per sender, until the gas limit. A transaction whose nonce is already used, or whose
   sender can't cover `gas_limit × max_fee + value`, is dropped. A transaction with a nonce gap
   or a fee cap below the base fee waits, and is dropped after 3 hours.
6. **Execution.** Included transactions always advance the nonce and pay gas. A reverted
   transaction pays gas but moves no value and emits no logs. Reasons: slippage, sold out,
   insufficient token balance, out of gas, airdrop not eligible / already claimed / closed /
   exhausted, other contract logic.
7. **Receipts.** The wallet sees the receipt 100 ms or more after inclusion or drop, and
   updates its nonce and balance view from it.
8. **Airdrop.** One protocol (the router's pools) announces an airdrop: interactions before a
   snapshot (day 18) count; at least 3 qualify, with three allocation tiers; claims open on day
   21 for 30 days from a fixed token pool. Ordinary wallets that qualified claim it.

## Rates we know (to calibrate against)

| Metric | Target | Source |
|---|---|---|
| Transactions per block (at 30M gas) | 100–200, i.e. `gas_limit / 300k` to `gas_limit / 150k` | public block explorers, 2025 daily averages |
| Gas used / gas limit, mean | 45–55% (EIP-1559 steers to the 50% target) | EIP-1559; explorers |
| Gas per included transaction, mean | 80k–130k | explorers |
| Reverted share of included transactions | 2–5% | explorers ("failed" txs) |
| Dropped share of submitted transactions | 0.5–2% | node operators' mempool stats |
| Daily active wallets / funded wallets | 8–14% | explorers (daily active addresses) |
| Transactions per active wallet per day | median 1, p90 4–8 | explorers |
| Type mix: native / token / swap / NFT mint / bridge | 35–45 / 25–35 / 12–22 / 3–8 / 2–5 % | explorer method-id breakdowns |
| Priority fee (effective), median | 0.03–1 gwei; p99 above 5 gwei | fee trackers |
| Submission → receipt, median | 4–15 s; p95 under 2 min | wallet telemetry |
| Top 1% of non-exchange wallets' share of their ETH | 70–90% | rich lists |

## Things that must never happen

- A sender's included nonces skip or repeat a value.
- A balance (native or token) below zero.
- ETH created or destroyed other than issuance (credited) and base-fee burn (destroyed).
- A block using more gas than its limit, or a base fee that doesn't follow EIP-1559.
- A reverted transaction with value transfers or logs.
- A transaction both included and dropped, included twice, or neither by the horizon without
  being reported as pending.

## Abuse to simulate separately (overlays)

- **Airdrop sybils.** A farmer funds tens to hundreds of fresh wallets from one funder (fan-out,
  sometimes through a short peel chain), makes each perform the same scripted handful of router
  swaps and a bridge deposit before the snapshot, claims with all of them when claims open, and
  consolidates the proceeds into one collector that cashes out to an exchange. Sybils draw on
  the same fixed airdrop pool as everyone else; we want to see legitimate claims fail when it
  runs out.
- **Mint rush.** A hyped NFT drop: for an hour, a crowd of wallets and bots mint one
  collection with high tips. Blocks fill, the base fee climbs about 12.5% per block, ordinary
  transactions with low fee caps wait and expire, and most mints revert as sold out.

## Out of scope

Consensus and fork choice, mempool gossip and replacement (speed-ups, cancels), EVM execution
and arbitrary contracts, MEV extraction, token approvals (folded into the router, permit-style),
L2 execution, gas-limit changes during the run, contract deployment.
