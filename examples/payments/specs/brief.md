# Brief: card payments

**Business.** A card acquirer serving about 120 merchants. Customers pay by card at a steady rate. Every payment is authorized by the issuer, then captured about an hour later, or the authorization expires after 7 days. Merchants refund some payments, partially, up to three times. Some payments are disputed weeks later. Merchants are paid out daily, net of refunds, chargebacks and fees (2.9% + 30¢). Customers pay their statement every 30 days.

**Who acts.** Customers and payments (owners); the issuer, the refund processor and the merchant accounts (shards).

**Fraud.** About 0.5% of payments are fraudulent. Most of them are disputed for fraud weeks later, and that is when the label becomes known.

## Rates we know

| # | Fact | Value |
|---|------|-------|
| 1 | Declined at authorization | 1.5–3% |
| 2 | Authorizations that expire uncaptured | 5–7% |
| 3 | Captures refunded at least once | 8–13% |
| 4 | Captures disputed (in a 60-day window) | 0.3–0.7% |
| 5 | Captures retried with the same idempotency key | about 5% |
| 6 | Volume on the top 10% of merchants | 55–62% |
