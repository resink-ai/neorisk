# Brief: e-commerce marketplace

A general-merchandise marketplace selling physical goods to consumers in one country, through a
web site and a mobile app. We want event data realistic enough to build and benchmark fraud,
conversion and inventory models, including a referral-abuse ring that the base population
doesn't contain.

## Actors

- **Shoppers.** Sign up, browse in sessions, add items to a cart, check out, receive orders,
  sometimes return them. Activity is heavy-tailed: most shoppers visit a few times a quarter,
  a small share visit daily. Each shopper uses one to three devices; some devices are shared
  within a household.
- **Catalog.** About 50,000 SKUs in 24 categories with log-normal prices (median about $25).
  Popularity follows a Zipf-like curve: the top 1% of SKUs take about 20% of views.
- **Inventory.** Stock is tracked per SKU, grouped into inventory groups (a warehouse zone).
  Popular SKUs sell out; restocks arrive on a weekly cycle with lead-time noise.
- **Referral program.** Any shopper can invite friends. When an invitee's first order of at
  least $30 is paid, the invitee gets a $10 credit and the inviter gets $10 credit. The
  program has a monthly budget; when it is spent, new claims are rejected until next month.

## Flows

1. **Signup.** Organic (most) or through an invite link. Signup collects country, age band,
   acquisition channel, and the first device.
2. **Session.** Starts on a device, views 1–30 products (geometric, mean 6), adds some to the
   cart. About 8% of sessions start a checkout.
3. **Checkout.** The cart holds 1–5 lines. Checkout reserves stock for every line; if any line
   is out of stock, the whole checkout fails and the shopper may pick a substitute or leave.
   Payment is authorized after stock is reserved; about 3% of authorizations fail. A failed
   payment releases the stock.
4. **Fulfillment.** Shipped within 1–3 days (gamma), delivered 2–6 days later. About 1.5% of
   orders are lost or delayed past 14 days.
5. **Returns.** About 6% of delivered orders are returned within 30 days; apparel returns at
   about three times the base rate. The refund equals the returned lines' amounts.
6. **Referral.** About 4% of shoppers send invites (1–5, geometric). About 35% of invitees sign
   up within 7 days, and about 40% of those place a qualifying first order within 30 days.

## Rates we know (to calibrate against)

| Metric | Target | Source |
|---|---|---|
| Session → checkout started | 6–10% | internal analytics, Q2 |
| Checkout started → order placed | 70–85% | internal analytics, Q2 |
| Payment authorization failure | 2–4% | PSP monthly report |
| Return rate (delivered orders) | 5–8%, apparel 15–20% | returns team |
| Orders per active shopper per 90 days | median 1, p90 5 | internal analytics |
| Out-of-stock checkout failures | 1–3% of checkouts | inventory team |

## Things that must never happen

- Stock below zero, or a unit sold twice.
- A refund larger than what was paid for the order.
- A referral bonus paid twice for the same invitee, or beyond the monthly budget.
- An order shipped before it was paid, or delivered before it was shipped.

## Abuse to simulate separately (overlays)

- **Bounty hunters.** Small rings (a few hundred people in total) sign up, invite 5–30 fake
  invitees from a handful of shared devices, make each invitee place one order just above the
  $30 minimum, collect both bonuses, then go dormant. Some rings arrive when the budget is
  already low and drain it, so ordinary referrals get rejected; we want to see that effect.

A flash-sale overlay (one day of about 8× traffic on a few hot SKUs) is deferred (D93).

## Out of scope

Seller-side behavior, pricing changes during the run, search ranking, shipping carriers'
internal events, taxes, multi-currency.
