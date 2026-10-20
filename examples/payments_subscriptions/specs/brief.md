# Brief: subscription billing (a payments variant)

**Business.** A streaming service sells monthly plans (basic $8, standard $13, premium $20). New subscribers get a 14-day free trial. When the trial ends, and every 30 days after that, the card is charged through the payment processor. A failed charge enters dunning: retries 3, 5 and 7 days after the failure. After the third failed retry, the subscription is cancelled (involuntary churn). Some subscribers cancel during the trial, and some cancel at a renewal (voluntary churn).

**Who acts.** Subscribers (owners), each running a subscription lifecycle; the payment processor (a shard) that approves or declines charges.

**Abuse to model (overlay on `payments`, separately).** Card testers buy lists of stolen cards and test them with bursts of tiny authorizations at one weak merchant. The cards that pass are then used for one large purchase elsewhere.

## Rates we know

| # | Fact | Value |
|---|------|-------|
| 1 | Trials that convert to paid | 65–80% |
| 2 | Charges declined at first attempt | 6–12% |
| 3 | Dunning recoveries (a retry succeeds) | 40–70% of dunned subscriptions |
| 4 | Voluntary churn at each renewal | about 4% |
| 5 | Plan mix basic/standard/premium | about 40/40/20 |
