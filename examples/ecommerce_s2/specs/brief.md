# Brief: e-commerce and payments, S2 slice

The S1 shopper journey (sessions, Pareto session gaps, devices, a Zipf catalog, restocks) with
the shard-heavy parts of `examples/ecommerce` and `examples/payments`, as handwritten kernels.

- **Carts** hold up to four lines. Checkout first holds the cart total on the shopper's credit
  limit, then sends one reserve request per line to the line's inventory group, waits for every
  answer, and commits all lines or releases the granted ones. About 2% of shoppers abandon a
  fully granted checkout; their holds expire after a 10-minute TTL.
- **One hot inventory group** (group 0) holds a small set of SKUs; about 5% of checkouts have
  at least one line in it (spec §10: "one hot SKU group taking 5% of checkouts").
- **Payments** (task 13 onward) are created by checkouts and by bill payments.
