# Brief: e-commerce and payments, S2 slice

The S1 shopper journey (sessions, Pareto session gaps, devices, a Zipf catalog, restocks) with
the shard-heavy parts of `examples/ecommerce` and `examples/payments`, as handwritten kernels.

- **Carts** hold up to four lines. Checkout first holds the cart total on the shopper's credit
  limit, then sends one reserve request per line to the line's inventory group, waits for every
  answer, and commits all lines or releases the granted ones. About 2% of shoppers abandon a
  fully granted checkout; their holds expire after a 10-minute TTL.
- **One hot inventory group** (group 0) holds a small set of SKUs; about 5% of checkouts have
  at least one line in it (spec §10: "one hot SKU group taking 5% of checkouts").
- **Payments** are created by successful checkouts and by bill payments (each shopper pays a
  bill about every 20 days, median $60). Each payment is its own owner: it is authorized or
  declined (3%) at creation, and 93% of authorizations are captured after a lognormal delay
  (median 1 h). Capture races the authorization's 7-day expiry; at an equal instant expiry wins.
  A capture charges a 2.9% platform fee. Every authorization, capture and expiry writes
  balanced double-entry postings to the `ledger`; a captured payment stays live for its 90-day
  dispute window (refunds and disputes arrive with task 14).
