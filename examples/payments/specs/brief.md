# Brief: card payments for a payment processor

We are an acquirer / payment service provider (PSP). Tens of thousands of merchants send us
card payments, online and in store; we screen each one, forward it to the card network and the
issuer, capture it, settle it to the merchant the next day, process refunds and handle
disputes. We want event data realistic enough to build and benchmark authorization-risk,
refund-abuse and dispute models, including a card-testing attack and a friendly-fraud group
that the base population doesn't contain.

We see payments, not people. A cardholder is never visible to us: we see a card token, its
BIN, the merchant, and for online payments a device fingerprint.

## Actors

- **Cardholders.** Each holds one to three cards (credit, debit, prepaid) and uses one to three
  devices for online purchases. Activity is heavy-tailed: most cards show up at our merchants
  once or twice a month, a few dozen times for heavy users. About 93% of purchases are at
  merchants in the cardholder's own country.
- **Merchants.** About 40,000 merchants in 12 merchant category codes (MCC), in 8 countries,
  sized small / mid / large / enterprise. Volume is concentrated: the top 1% of merchants take
  about 35–45% of captured volume. Each merchant has a daily refund limit set by its size and a
  merchant discount rate (MDR) of 1.8–2.9% plus 30 cents.
- **Card issuers and networks.** External; not simulated as actors. The issuer's approve or
  decline answer arrives about half a second after we forward a payment.
- **Our risk engine.** Screens every authorization within about 80–150 ms using velocity
  counters it keeps per card, per device and per merchant over the last hour. It approves,
  declines, or asks for 3-D Secure (3DS) step-up on online payments.

## Flows

1. **Authorization.** A purchase sends us an authorization request with an idempotency key.
   Risk screens it (δ ≈ 80 ms). On a challenge, the cardholder completes a 3DS challenge
   (about 45 s median; most pass, some fail or abandon). Then the issuer approves or declines
   (insufficient funds, do not honor, suspected fraud, limit exceeded; closed or expired cards
   are always declined). An approved authorization is valid for 7 days.
2. **Client retries.** About 2% of merchant integrations time out and resend the same request
   with the same idempotency key, usually within seconds. We must return the first result
   and never authorize twice.
3. **Capture.** Most merchants capture within hours; hotels and travel capture days later, and a
   few of those miss the 7-day window. About 5% of captures are partial (split shipment,
   adjusted tip). Merchants void about 3–4% of authorizations instead. A capture that arrives
   after expiry is rejected; a capture at exactly the expiry instant counts as expired.
4. **Settlement.** Captured payments settle in a daily batch at 02:00 UTC: the network pays us,
   we pay the merchant minus fees. We keep a double-entry ledger of every money movement.
5. **Refunds.** About 3–6% of captured payments get refunded, by count, within a few weeks;
   most refunds are full, some partial, occasionally several partial refunds. A refund needs
   the remaining captured amount and the merchant's daily refund headroom. Refunds are
   rejected while a dispute is open.
6. **Disputes.** About 0.3–0.7% of captured payments are disputed by the cardholder through the
   issuer, up to 120 days later. The amount is debited from the merchant provisionally. About
   70% of merchants contest with evidence within 20 days; the rest accept. The issuer rules
   within about 75 days; contested disputes are won by the merchant about 30–45% of the time.
   A lost dispute becomes a chargeback with a $15 fee.

## Rates we know (to calibrate against)

| Metric | Target | Source |
|---|---|---|
| Authorization approval rate (first attempts) | 85–91% | PSP monthly report; consistent with public card-not-present approval benchmarks |
| 3DS challenge rate (of authorization requests) | 4–10% | risk team |
| 3DS challenge success | 75–88% | risk team; public EMV 3DS success-rate reports |
| Capture / void / expiry of approved authorizations | 92–96% / 2–5% / 1–4% | operations |
| Refund rate (captured payments, by count) | 3–6% | merchant operations |
| Dispute rate (captured payments, by count) | 0.3–0.7% | disputes team; card network monitoring thresholds (Visa/Mastercard, ~0.9–1.5%) must never be reached by the base |
| Merchant win rate (contested disputes) | 30–45% | disputes team |
| Dispute filing lag after capture | median 15–35 days, never after 120 days | card network dispute timelines (Visa/Mastercard rules, 120 days) |
| Payments per active card per 30 days | median 1–3, p90 7–13 | analytics |
| Client retries with a reused idempotency key | 1–3% of authorizations | API gateway logs |
| Authorization latency without 3DS | median 0.5–1.5 s | API gateway logs |

## Things that must never happen

- A capture larger than the authorization, or after the authorization expired.
- Refunds plus chargebacks larger than what was captured; a refund while a dispute is open.
- Two authorizations, or two different answers, for one idempotency key.
- A ledger entry whose debits and credits don't balance.
- Settlement totals that disagree with the settled payments.
- A payment, refund or dispute skipping a step of its lifecycle.
- Risk counters that disagree with the decisions they were computed from.

## Abuse to simulate separately (overlays)

- **Card testing.** Rings (around a hundred) buy lists of stolen card numbers, most of them
  already closed. From a handful of devices, each ring fires bursts of tiny authorizations
  (50 cents to 3 dollars) against a few small charity and digital-goods merchants to find the
  cards that still work. Most attempts are declined. Hours later the ring uses some working
  cards for large electronics and gift-card purchases; the real cardholders dispute most of
  those as fraud. The bursts also inflate our risk counters at the targeted merchants, so their
  honest customers get challenged more; we want to see that effect.
- **Friendly fraud.** A small share of ordinary cardholders (about 0.4%) dispute legitimate,
  delivered purchases ("not received", "fraud") instead of asking the merchant for a refund.
  A few do it repeatedly. Many claim "not received", which merchants holding delivery evidence
  often win; the label is known only once the dispute resolves.

## Out of scope

Issuer-side decisions beyond a decline rate, network fees per scheme, multi-currency and FX,
interchange tables, netting and payout scheduling beyond a daily batch, pre-arbitration and
arbitration, recurring billing schedules, merchant onboarding and underwriting.
