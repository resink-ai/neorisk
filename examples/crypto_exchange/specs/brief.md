# Brief: centralized crypto exchange (spot)

A mid-sized centralized exchange offering spot trading in about 40 pairs to retail and
professional customers worldwide, through a web site, a mobile app and an API. We want event
data realistic enough to build and benchmark market-surveillance, AML and customer models,
including wash-trading rings and a pump-and-dump scheme that the base population doesn't
contain.

## Actors

- **Retail traders.** Register, verify identity (KYC), deposit crypto, trade a few times a
  week to a few times a quarter, and withdraw. Activity is heavy-tailed and follows the market:
  big price moves bring people back. Most use the app; a few create API keys. Each uses one to
  three devices and a few IPs; devices are sometimes shared within a household and IPs often
  shared behind mobile carriers.
- **Professional traders.** About 2.5% of accounts. Trade roughly ten times as often, use
  more limit orders, often through the API, and pay lower fees.
- **Market makers.** About 60 institutional accounts, fully verified, connected by API from
  data centers. Each quotes 4–14 symbols with post-only ladders around a fair price, cancels
  and replaces quotes when the price moves, and leans its quotes against its inventory. Every
  symbol is quoted by at least one market maker. They pay no maker fee.
- **Listed assets and pairs.** 26 real assets plus 9 low-cap tokens (fictional names in this
  brief), 40 pairs: 34 against USDT (9 of them the low-cap tokens) and 6 against BTC.
  Pairs come in four tiers by liquidity: major (BTC, ETH), large, mid, small. Attention and
  volume are very concentrated in the first few pairs.
- **Reference prices.** Each pair follows an external market price (other venues): a jump
  diffusion with a common market factor, more volatile and jumpier for smaller tiers. Market
  makers and retail limit prices anchor to it; the exchange uses it for price bands.

## Flows

1. **Registration and KYC.** Registration records country, channel, device and IP. About 88%
   pass basic KYC within hours; about 22% of those later complete full KYC. Withdrawals need
   KYC: per-request limits are 0 (none), 50,000 USDT (basic) and 2,000,000 USDT (full).
2. **Deposits.** About 72% of registered traders deposit, the first one typically within an
   hour (log-normal), then top up at heavy-tailed intervals. Deposits are mostly USDT, then BTC
   and ETH. A deposit is credited after the asset's required confirmations (BTC 2 blocks,
   about 20 minutes; ETH 12 blocks, a few minutes; Tron 20 blocks, about a minute).
3. **Placing an order.** The exchange first locks the funds the order could spend (quote for a
   buy, base for a sell) on the trader's balance, then sends the order to the matching engine.
   Order types: limit (GTC, IOC, FOK, optional post-only) and market (buy by quote amount, sell
   by base quantity). Order entry latency is a few milliseconds, never below 2 ms.
4. **Matching.** Price/time priority. Market orders stop at a ±5% collar around the reference
   price; limit prices must be within ±10% of it. FOK orders fill in full or not at all.
   Post-only orders that would cross are rejected. Self-trade prevention cancels the resting
   order when a trader would trade with itself. Each fill is reported to both sides within a
   few milliseconds; fees are charged in the asset received (0.10% retail, lower for pros;
   market makers 0% maker / 0.04% taker).
5. **Settlement.** On each fill the locked funds are spent and the received asset, minus the
   fee, becomes available. When an order closes (filled, cancelled, rejected), any lock left
   over is returned.
6. **Cancels.** Retail traders cancel a resting order after hours (log-normal patience);
   market makers cancel and replace constantly. A cancel can arrive after the order filled; it
   is then rejected.
7. **Withdrawals.** The amount is held at request. About 82% are approved automatically within
   a minute, the rest after manual review (hours); about 2% are rejected and the hold returned.
   Approved withdrawals are broadcast a few minutes later; the network fee is deducted.

## Rates we know (to calibrate against)

| Metric | Target | Source |
|---|---|---|
| Quoted spread, BTC-USDT and ETH-USDT (median of 1-minute samples) | 1–4 bps | market data team |
| Quoted spread, small-cap pairs (median) | 20–90 bps | market data team |
| Trades per pair per day (full scale) | top pair 150k–600k, median pair 2k–20k | internal analytics, Q3 |
| Share of book volume where a market maker is the maker | 60–80% | MM program report |
| User cancels / accepted orders | all 85–97%, retail 15–35% | internal analytics, Q3 |
| Top 5 pairs' share of notional | 65–85% | internal analytics, Q3 |
| Top 1% of traders' share of notional | 55–80% | internal analytics, Q3 |
| First deposit credited → first order | median 15–90 min; 55–75% within 24 h | growth team |
| Orders rejected by the matching engine | 0.3–2% | matching engine ops |
| Market orders among retail orders | 50–65% | internal analytics, Q3 |
| Withdrawals rejected | 1–3% | compliance monthly report |
| Weekend vs weekday notional (per day) | 0.65–0.90 | internal analytics, Q3 |
| BTC deposit detected → credited | median 15–35 min | wallet ops |

## Things that must never happen

- A negative available or held balance, in any asset.
- Held funds that don't match the open orders' locks plus pending withdrawals.
- A trade that creates or destroys money: base and quote are conserved, minus fees.
- A fill that skips a better-priced or earlier resting order (price/time priority).
- A trader trading with itself while self-trade prevention is on.
- A fill-or-kill order that fills partially.
- An order that neither fills, cancels, nor stays open at the end; an order filled beyond its
  quantity.
- A withdrawal larger than the available balance at request, or a deposit credited twice.

## Abuse to simulate separately (overlays)

- **Wash traders.** Small rings (a few dozen in total) of 2–6 accounts controlled by one person,
  sharing devices, IPs and withdrawal addresses. They fund the accounts, then trade with each
  other in one illiquid pair for weeks (one account rests an order at the reference price,
  another takes it immediately) to inflate its volume, and finally withdraw. We want to see
  their share of the pair's volume and the effect on ordinary traders in that pair.
- **Pump and dump.** A group (an organizer and 3–15 insiders) quietly buys a low-cap token
  for about a week, then at a set time market-buys while a crowd of ordinary retail traders who
  follow the group's channel (a fraction of a percent of active retail) piles in within
  minutes. The group sells into that demand over a few hours and withdraws. Followers who don't
  exit in time hold the loss.

## Out of scope

Fiat on/off ramps, margin and futures, lending and earn products, on-chain internals (mempool,
reorgs), deposit failures, address screening internals, maker rebates, fee tiers by volume,
trading halts, multiple matching-engine instances per pair.
