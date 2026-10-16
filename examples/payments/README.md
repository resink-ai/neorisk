# Card payments (acquirer / PSP)

A payment processor's view of card payments across 40,000 merchants. Each purchase becomes a
payment that is risk-screened, maybe stepped up with 3-D Secure, authorized by the issuer,
captured (or voided, or left to expire), settled in a daily batch, and sometimes refunded or
disputed through to a chargeback. Every money movement is posted to a double-entry ledger.
See [`specs/brief.md`](specs/brief.md).

## Model

| Partition | Kind | Holds | Processes |
|---|---|---|---|
| `cardholder` | owner | profile, purchase rate, counters (not exported: an acquirer can't see people) | `cardholder_purchases` (kernel) |
| `payment` | owner | amounts (authorized, captured, refunded, `refund_hold`, `disputed`, charged back), status, idempotency key and first result; children `refund`, `dispute` | `authorize_payment`, `refund_flow` (kernels), `payment_lifecycle`, `dispute` (machines) |
| `merchant_risk` × 256 | shard | 1-hour velocity counters per card, device and merchant; daily refund headroom per merchant | `risk_decide`, `refund_check` (request handlers) |

**Why a payment is its own owner.** A payment lives up to 120 days (the dispute window) and
does all its work alone: capture racing expiry, refunds, the dispute child process, idempotent
replays. Making it an owner keeps the cardholder small and lets millions of payments run in
parallel. A purchase creates the payment with a creation message; the new owner starts in the
next round of the same step. Nothing flows back to the cardholder in the base pack.

**Boundaries.** A payment sends `authorize` to its merchant's `merchant_risk` shard
(δ = 80 ms, median 110 ms) and waits; the shard decides from its own counters and the copied
payload, emits `risk_evaluated` at its decision time, and answers approve / decline /
challenge. The issuer and the 3DS challenge are external, modeled as timers inside the
payment.

**Refunds are a hold.** The payment holds the refund amount against what is still refundable
(captured − refunded − held − disputed − charged back), the shard decides on the merchant's
daily refund headroom (`refund_check`, δ = 80 ms), and the payment then commits or releases.
If a dispute opened while the shard was deciding, the payment releases and emits
`refund_rejected(dispute_open)`: the race is real and the law still holds.

**Capture races expiry.** `payment_lifecycle` waits in `authorized` for a capture or void branch
and a 7-day expiry timer; the earliest wins and leaving cancels the rest. The state declares
`precedence=("expired", "captured", "voided")`, so a capture at exactly the expiry instant
counts as expired. Some merchants still send the capture later; it is rejected
(`capture_rejected`).

**Money.** Capture, settlement, refund, dispute and chargeback each post balanced two-row
entries to `postings/` (accounts: scheme receivable, merchant payable, fee revenue, disputes
pending, settlement cash). Settlement totals per merchant and batch date are an accumulator
written to `settlement/`; no decision ever reads them.

**Velocity is per merchant group.** Card and device counters live in the shard of the merchant
being paid, so they count a card's activity within one merchant group only. Cross-merchant
card velocity is a cross-owner feature (`card_distinct_merchants_24h`) computed after each step
seals and written to `golden/`, never a decision input.

**Events (19 owner + 2 shard):** `authorization_requested`, `three_ds_challenged`,
`three_ds_completed`, `authorization_approved`, `authorization_declined`, `idempotent_replay`,
`authorization_voided`, `authorization_expired`, `capture_succeeded`, `capture_rejected`,
`payment_settled`, `refund_requested`, `refund_succeeded`, `refund_rejected`,
`dispute_opened`, `dispute_evidence_submitted`, `dispute_won`, `dispute_lost`,
`chargeback_posted`; shard: `risk_evaluated`, `refund_screened`. Plus `postings/` rows from
`std.ledger` and `settlement/` rows from the accumulator.

## Overlays

| Overlay | Adds | Key parameters |
|---|---|---|
| `card_testing` | Rings, one owner each, probe hundreds of stolen cards with 50¢–$3 authorizations from 1–4 devices against a few small charity / digital-goods merchants; probe payments report back next step; working cards are cashed out on electronics and gift cards, then disputed as fraud by the victims. Hidden labels: probe / cashout, outcome, `ring_id`, `label_available_at`. Interference: honest customers of targeted merchants get challenged more | `size`, `cards_per_ring`, `live_card_share`, `target_merchants`, `probe_gap`, `cashout_share`, `victim_dispute_p` |
| `friendly_fraud` | A share of existing cardholders (`existing=True`) with a per-member propensity to dispute legitimate captured purchases instead of asking for a refund. The decision runs inside each payment they created. Labels become available when the dispute resolves | `share`, `propensity`, `min_amount`, `reasons`, `skip_refunds` |

## Run

```bash
datagen validate examples/payments
datagen run      examples/payments --profile sample           # ~20k cardholders, 21 days
datagen check    examples/payments --profile sample           # -> reports/sample-s42/report.html
datagen run      examples/payments --profile abuse            # 2M cardholders + both overlays
datagen run      examples/payments --profile full --overlay card_testing --set card_testing.size=200
datagen schema   examples/payments --format sql --dialect postgres --with-fks
datagen replay   examples/payments/out/sample-s42 --preset peek
datagen replay   examples/payments/out/full-s42+card_testing \
                 --types authorization_requested,authorization_declined,dispute_opened \
                 --with-labels --preset kafka_dev
```

`out/`, `reports/` and `logs/` are empty until the first run.
