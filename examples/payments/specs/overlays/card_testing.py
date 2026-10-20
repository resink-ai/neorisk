"""Card testing: fraudsters test lists of stolen cards with bursts of tiny authorizations at
one weak merchant, then use each card that passes for one large purchase elsewhere.

A tester is a customer-kind cohort member (its own id namespace) that skips the base wallet.
Each test holds the amount on the tester's own credit line (std holds, like any customer)
and creates a base `payment`. The payment's base actions emit every row, ask the issuer and
send `auth_result` back, which this overlay redirects to watch which cards pass. All of
these payments are fraudulent, so the base pack labels them; testers are labeled too.
Written from the brief with the public API only (examples/AGENTS.md).
"""

from __future__ import annotations

from neorisk_simkit.engine import DAY, MINUTE
from neorisk_simkit.spec.overlay import Overlay
from neorisk_simkit.std import holds

BRANDS = ("visa", "mastercard", "amex")


def apply(o: Overlay, size: int = 6, cards_per_burst: int = 25, bursts: int = 2,
          test_cents: tuple[int, int] = (100, 300), cashout_cents: int = 90_000,
          label_delay_days: float = 3.0) -> None:
    o.cohort("card_tester", kind="customer", size=size, arrive=(2.0, None),
             suppress=["wallet"], redirect={"auth_result": "tested"})
    t = o.process("customer", "card_testing", cohort="card_tester", start="set_up")

    @t.action
    def set_up(ctx, s, cmd):
        s.cid = ctx.insert("customers", segment="consumer", country="BR", credit_limit=10**9)
        s.limit = 10**9                     # stolen cards: the tester's own line is no limit
        ctx.emit("credit_line_opened", customer_id=s.cid, limit=s.limit)
        ctx.label(s.cid, "card_tester", table="customers", available_at=ctx.now + label_delay_days * DAY)
        m = ctx.shared.merchants
        ctx.local.update(weak=int(m.ids[-1 - ctx.rng.integers(len(m.ids) // 4)]),
                         bursts=0, card_of_hold={})
        ctx.after(ctx.rng.uniform(0, 6) * 3600, "burst")

    def pay(ctx, s, card: int, merchant: int, amt: int) -> None:
        hid = holds.place(ctx, s.credit, amt, free=s.limit - s.balance, purpose="purchase",
                          customer_id=s.cid, payment_id=None)
        ctx.local["card_of_hold"][hid] = card
        ctx.create("payment", customer=s.cid, customer_pid=ctx.self_id, merchant=merchant,
                   merchant_pid=ctx.find("merchant_account", merchant), card=card,
                   amount=amt, hold=hid, fraud=True)

    @t.action
    def burst(ctx, s, cmd):
        rng, loc = ctx.rng, ctx.local
        lo, hi = test_cents
        for _ in range(cards_per_burst):    # a burst: one stolen card after another
            card = ctx.insert("cards", customer_id=s.cid,
                              brand=BRANDS[rng.integers(len(BRANDS))])
            pay(ctx, s, card, loc["weak"], int(rng.integers(lo, hi)))
        loc["bursts"] += 1
        if loc["bursts"] < bursts:
            ctx.after(rng.uniform(1, 4) * DAY, "burst")

    @t.action
    def tested(ctx, s, cmd):
        ctx.call("auth_result", **cmd.payload)          # the base bookkeeping first
        card = ctx.local["card_of_hold"].pop(cmd.hold)
        tested_small = cmd.payload.get("approved") and not ctx.local.get(f"cashed_{card}")
        if tested_small:                                # the card works: use it once, big
            ctx.local[f"cashed_{card}"] = True
            ctx.after(ctx.rng.uniform(10, 120) * MINUTE, "cash_out", card=card)

    @t.action
    def cash_out(ctx, s, cmd):
        m, rng = ctx.shared.merchants, ctx.rng
        target = int(m.ids[rng.integers(min(10, len(m.ids)))])      # a busy merchant
        pay(ctx, s, cmd.card, target, cashout_cents + int(rng.integers(0, 40_000)))
