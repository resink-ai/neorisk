# Brief: a spot crypto exchange

**Business.** Two markets, BTC-USD and ETH-USD. Market makers quote both sides around a drifting fair price. Retail traders send orders that often cross the spread: 70% good-till-cancelled, 20% immediate-or-cancel and 10% fill-or-kill. Some resting orders are cancelled within a few hours.

**Who acts.** Traders (owners). One book per symbol (a shard) holds the resting orders and every trader's isolated balances for that market.

## Rates we know

| # | Fact | Value |
|---|------|-------|
| 1 | Orders matched by price, then time | always |
| 2 | FOK orders filled in full or rejected | always |
| 3 | No trader trades with itself | always |
