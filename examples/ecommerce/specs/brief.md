# Brief: e-commerce shoppers with a referral program

**Business.** A mid-size online store. Shoppers arrive over the first half of the period, browse in sessions, and sometimes check out one or two SKUs. Stock lives in inventory groups; one hot group holds the most viewed SKUs. A referred shopper's first order of at least $30 pays the inviter a $10 bonus, a few days later, from a monthly budget of $20,000.

**Who acts.** Shoppers (owners); inventory groups and the referral budget (shards).

**Abuse to model (overlay).** Bounty hunters run rings of zombie accounts on shared devices. Each zombie signs up through the hunter's invite and places one order just above the minimum. The hunter cashes out each bonus.

## Rates we know

| # | Fact | Value |
|---|------|-------|
| 1 | Shoppers who order within 30 days of signup | 30–40% |
| 2 | Orders returned within 30 days (censored at the end of the run) | 3–5% |
| 3 | Checkouts that fail for stock | under 2% |
| 4 | Views on the top 1% of SKUs | 35–42% |
| 5 | Orders per ordering shopper: median 1, p90 about 2 | |
| 6 | Orders per day (2,000 shoppers) | 25–35 |
| 7 | Rings: about one hunter per 500 shoppers, about 8 zombies each | |
