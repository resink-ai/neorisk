"""Card testing: rings that probe stolen cards with tiny authorizations, then cash out.

A ring is one owner (execution_owner="ring_id") holding a list of stolen card numbers and a few
devices. It fires bursts of tiny authorizations through the base `purchase` action against a
few small charity / digital-goods merchants. Every purchase is a creation message, so each
probe is an ordinary payment owner running the base authorization flow: same risk shard, same
issuer, same events. Each probe payment reports its answer back to the ring as an owner-to-
owner message (delivered at the next step boundary or later; the ring never waits on it within
a step). Hours later the ring spends some of the cards that worked on large electronics and
gift-card purchases; the real cardholders dispute most of those as fraud.

The probes land in the merchant_risk shards of the targeted merchants, so honest customers of
those merchants see more challenges and declines while a burst is running (reported as
interference).

    datagen run examples/payments --profile full --overlay card_testing \
        --set card_testing.size=200 --set card_testing.live_card_share=0.25
"""

from neorisk_simkit.spec import Overlay, dist, std


def apply(o: Overlay,
          size: int = 120,                                      # rings
          cards_per_ring: dist.Dist = dist.negbinom(mean=400, disp=0.6, min=50, max=3_000),
          live_card_share: float = 0.35,                        # stolen cards still active
          devices_per_ring: dist.Dist = dist.uniform_int(1, 4),
          target_merchants: int = 4,                            # per ring
          target_mcc: tuple = ("8398", "5815"),                 # charities, digital goods
          probe_amount: dist.Dist = dist.uniform_minor(min=50, max=300),
          probe_gap: dist.Dist = dist.exp(mean_s=12),
          arrive: dist.Dist = dist.burst(start="day 5", span="80d"),
          harvest_after: dist.Dist = dist.lognormal(median_h=20, sigma=0.8),
          cashout_share: float = 0.4,                           # worked cards spent
          cashout_mcc: tuple = ("5732", "5947"),                # electronics, gift cards
          cashout_amount: dist.Dist = dist.lognormal_minor(median=60_000, sigma=0.5,
                                                           max=250_000),
          victim_dispute_p: float = 0.7) -> None:

    ring = o.cohort("card_tester", table="cardholder", size=size, arrivals=arrive,
                    execution_owner="ring_id",                  # one owner per ring
                    suppress=["cardholder_purchases"],
                    attrs={"segment": "heavy"},
                    refs={"card": std.stolen_cards(n=cards_per_ring, live_share=live_card_share),
                          "device": std.device_pool(per_owner=devices_per_ring)})

    targets = o.pick_merchants(mcc=target_mcc, n=target_merchants, per_member=True,
                               where="size == 'small'")
    shops = o.pick_merchants(mcc=cashout_mcc, n=20, by="popularity")

    # ---------------------------------------------------------------- ring
    t = o.machine("tester", members=ring, initial="new")
    t.state("new", branch={"probing": (1.0, dist.lognormal(median_s=600), None)})
    t.state("probing", repeat=(probe_gap, 1.0, o.base.purchase.with_params(
        card_id=std.next_ref("card"), merchant_id=std.pick(targets),
        device_id=std.pick_ref("device"), amount=probe_amount, channel="ecom",
        holder_present=False)),
        until=std.refs_exhausted("card"), then="cooling")
    t.on_message("probe_result", std.collect(into="worked_cards", key="card_id",
                                             where="approved"))   # next step boundary or later
    t.state("cooling", branch={"cashing_out": (1.0, harvest_after, None)})
    t.state("cashing_out", repeat=(dist.exp(mean_s=90), 1.0, o.base.purchase.with_params(
        card_id=std.take("worked_cards", share=cashout_share), merchant_id=std.pick(shops),
        device_id=std.pick_ref("device"), amount=cashout_amount, channel="ecom",
        holder_present=False)),
        until=std.exhausted("worked_cards"), then="gone")
    t.final("gone", status="dormant")

    # ---------------------------------------------------------------- payments the ring created
    probes = ring.created("payment", via="probing")
    cashouts = ring.created("payment", via="cashing_out")

    r = o.machine("probe_report", members=probes,
                  start=o.on_event(("authorization_approved", "authorization_declined")),
                  initial="answered")
    r.state("answered", branch={"done": (1.0, None, std.send_creator(
        "probe_result", payload={"card_id": "card_id",
                                 "approved": std.is_event("authorization_approved")}))})
    r.final("done")

    v = o.machine("victim_dispute", members=cashouts, start=o.on_event("capture_succeeded"),
                  initial="captured")
    v.state("captured", branch={
        "disputed": (victim_dispute_p, dist.gamma(mean_days=18, shape=2.0, max_days=110),
                     o.base.open_dispute.with_params(reason="fraud")),
        "otherwise": (1 - victim_dispute_p, None, None),
    })
    v.final("disputed", "otherwise")

    # ---------------------------------------------------------------- labels (hidden)
    # Probes are found when risk ops review the burst; cashouts when the victim disputes,
    # or after a long tail when the issuer reports fraud without a dispute.
    o.label(probes, role="probe", outcome=("declined", "approved"), campaign="ring_id",
            available_at=std.after("authorization_requested", dist.gamma(mean_days=4, shape=2.0)))
    o.label(cashouts, role="cashout", outcome=("declined", "approved", "disputed",
                                               "charged_back"), campaign="ring_id",
            available_at=std.first_of(
                std.after("dispute_opened", dist.gamma(mean_days=2, shape=2.0)),
                std.after("authorization_requested", dist.gamma(mean_days=60, shape=3.0))))
