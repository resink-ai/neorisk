# Brief: e-commerce marketplace, S1 slice

The shopper, catalog and inventory parts of [`examples/ecommerce`](../../ecommerce/specs/brief.md),
cut down to what the S1 engine runs: handwritten kernels, one owner type and one shard type.

## Actors

- **Shoppers.** Sign up, browse in sessions and check out. Activity is heavy-tailed: gaps
  between sessions follow a Pareto tail (alpha 1.2, at least 30 h). Each shopper uses one to
  three devices; some devices are shared within a household (about 12% of shoppers also use
  a device of another shopper).
- **Catalog.** SKUs in 24 categories with log-normal prices (median about $25). Popularity
  follows a Zipf-like curve (s = 1.07) over a random order of the SKUs.
- **Inventory.** Stock is tracked per SKU, grouped into inventory groups (one shard each).
  Popular SKUs start with more stock; restocks arrive on a weekly cycle with lead-time noise
  (normal, sd 18 h) and suppliers short-ship (a restock fills a random part of the gap to the
  initial stock level).

## Flows

1. **Signup.** Population owners arrive on a weekly pattern with a slight upward trend; the
   signup records the age band, acquisition channel and first device. The first session
   follows about an hour later.
2. **Session.** Starts on one of the shopper's devices (web on a desktop, app otherwise) and
   views 1–30 products (geometric, mean 6) about 40 s apart, picked by popularity.
3. **Cart.** Each view adds the product with probability 0.18. The cart holds one line in S1:
   adding a product replaces it.
4. **Checkout.** When a session ends with a non-empty cart, the shopper checks out with
   probability 0.35, about 25 s later. Checkout reserves the line's stock at its inventory
   group; if it is out of stock the checkout fails and the shopper browses for a substitute
   with probability 0.45.
5. **Payment.** About 2.5 s after the stock is reserved the payment is authorized; about 3% of
   authorizations fail and release the stock. A successful payment commits the stock and
   places the order.

## Things that must never happen

- Stock below zero, or a unit sold twice.
- A checkout with two outcomes (an order and a failure, or two failures).

## Scope

Left for `examples/ecommerce` at M3: multi-line carts and multi-SKU reservations, fulfillment
(shipping, delivery, lost orders), returns and refunds, the referral program and its budget
shard, and the `bounty_hunters` and `flash_sale` overlays.
