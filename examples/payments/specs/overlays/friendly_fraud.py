"""Friendly fraud: ordinary cardholders who dispute legitimate, delivered purchases.

Not a new kind of actor: a small share of existing cardholders (existing=True, no new IDs)
keep their normal purchase behavior, but some of their captured payments get disputed
("not received", "fraud") instead of refunded. The decision runs inside each payment owner
the member created, so no message crosses an owner boundary. Each member has its own
propensity, so a few of them dispute again and again.

The overlay touches no shared decision state (disputes and refunds of a payment live in that
payment), so base rows outside the cohort's payments must be identical with and without it.

    datagen run examples/payments --profile full --overlay friendly_fraud \
        --set friendly_fraud.share=0.006 --set friendly_fraud.skip_refunds=false
"""

from neorisk_simkit.spec import Overlay, dist, std


def apply(o: Overlay,
          share: float = 0.004,                                 # of active cardholders
          propensity: dist.Dist = dist.beta(a=2.0, b=6.0),      # per member; mean 0.25
          min_amount: int = 2_000,                              # cents; small tickets aren't worth it
          reasons: dict = None,
          delay: dist.Dist = dist.gamma(mean_days=40, shape=2.5, max_days=115),
          skip_refunds: bool = True,                            # dispute instead of asking the merchant
          label_review: dist.Dist = dist.gamma(mean_days=10, shape=2.0)) -> None:

    reasons = reasons or {"not_received": 0.45, "fraud": 0.35, "not_as_described": 0.20}

    ff = o.cohort("friendly_fraudster", table="cardholder", share=share, existing=True,
                  where="status == 'active' and purchases >= 3",
                  attrs={"dispute_p": propensity})

    pays = ff.created("payment", where=f"amount >= {min_amount} and channel == 'ecom'",
                      suppress=["refund_flow"] if skip_refunds else [])

    m = o.machine("buyers_remorse", members=pays, start=o.on_event("capture_succeeded"),
                  initial="captured")
    m.state("captured", branch={
        "disputing": (std.member_attr("dispute_p", of="creator"), delay,
                      o.base.open_dispute.with_params(reason=dist.categorical(reasons))),
        "otherwise": (None, None, None),                        # unpicked mass
    })
    m.final("disputing", "otherwise")

    # ---------------------------------------------------------------- labels (hidden)
    # Known only once the dispute resolves and the disputes team reviews the evidence.
    o.label(pays, only=std.reached("disputing"), role="friendly_fraud",
            outcome=("disputed", "won_by_merchant", "charged_back"),
            available_at=std.after(("dispute_won", "chargeback_posted"), label_review))
    o.label(ff, role="friendly_fraudster", outcome=("disputed", "never_disputed"),
            available_at=std.after("dispute_opened", dist.gamma(mean_days=45, shape=3.0)))
