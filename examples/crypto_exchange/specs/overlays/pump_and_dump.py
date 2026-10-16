"""Pump and dump: a group accumulates a low-cap token, a crowd of followers buys, the group dumps.

A scheme is one organizer plus 3-15 insiders under one scheme owner
(execution_owner="scheme_id"). Insiders accumulate the target quietly with passive limit buys,
then market-buy at the pump time and sell into the followers' demand. Followers are existing
retail traders (a share, no new IDs) who keep their base behavior and get one extra machine:
buy the target minutes after the pump, maybe sell later.

Coordination without cross-owner messages: each scheme's pump time is drawn once, at cohort
creation, into a read-only schedule (o.schedule). Insiders and followers both read it; no
mutable state crosses owners. The price impact is endogenous: followers' market buys walk a
thin book, and market makers skew their quotes as they get short inventory. Base traders share
the target's book shard, so changed base outcomes are reported as interference.

    datagen run examples/crypto_exchange --profile full --overlay pump_and_dump \
        --set pump_and_dump.size=8 --set pump_and_dump.followers=0.004
"""

from neorisk_simkit.spec import Overlay, dist, std


def apply(o: Overlay,
          size: int = 6,                                        # schemes
          insiders: dist.Dist = dist.uniform_int(3, 15),
          share_device: float = 0.3,
          arrive: dist.Dist = dist.burst(start="day 10", span="45d"),
          symbol_tier: str = "small",
          seed_usdt: dist.Dist = dist.lognormal_minor(median=25_000, sigma=0.8,
                                                      min=2_000, max=400_000),  # per insider
          pump_after: dist.Dist = dist.gamma(mean_days=8, shape=3.0),   # after the scheme forms
          accumulate_every: dist.Dist = dist.exp(mean_s=1_200),
          accumulate_share: dist.Dist = dist.beta(a=1.5, b=12.0),       # of insider's USDT
          accumulate_offset_bps: dist.Dist = dist.uniform(-60.0, -5.0),  # passive, below ref
          followers: float = 0.003,                             # share of active retail
          follower_join_p: float = 0.55,                        # followers who act on it
          follower_delay: dist.Dist = dist.lognormal(median_s=150, sigma=1.0),
          follower_buy_share: dist.Dist = dist.beta(a=2.0, b=3.0),      # of available USDT
          follower_exit_p: float = 0.45,
          follower_exit_after: dist.Dist = dist.lognormal(median_s=4 * 3_600, sigma=1.2),
          dump_every: dist.Dist = dist.exp(mean_s=25),
          dump_share: dist.Dist = dist.uniform(0.05, 0.25),     # of insider's base per sell
          dump_span: str = "3h") -> None:

    scheme = o.cohort("pump_scheme", table="trader", size=size, arrivals=arrive,
                      execution_owner="scheme_id",              # organizer + insiders = one owner
                      suppress=["trader_activity", "funding", "onboarding", "api_access"],
                      attrs={"segment": "retail"},
                      refs={"device": std.device_pool(per_owner=dist.uniform_int(2, 6))})
    target = o.pick_symbols(tier=symbol_tier, n=1, per_owner=True, by="lowest_volume")
    pump_at = o.schedule("pump_at", per=scheme, at=std.after_arrival(pump_after))  # read-only

    # ---------------------------------------------------------------- organizer
    org = o.machine("scheme_organizer", members=scheme, initial="new")
    org.state("new", branch={"funding": (
        1.0, dist.lognormal(median_s=3_600),
        o.base.register.then(o.base.upgrade_kyc.with_params(level=1)).then(
            std.spawn_members("insider", n=insiders, via=o.base.register,
                              refs={"device": std.share_with_parent(share_device)},
                              stagger=dist.exp(mean_s=3_600))))})
    org.state("funding", join={"accumulating": ("funded", "all_spawned")},
              timer={"accumulating": "2d"}, late="ignore")
    org.state("accumulating", repeat=(accumulate_every, 1.0,
              o.base.place_order.with_params(
                  account=std.pick_member("insider", rotate=True), symbol=target, side="buy",
                  type="limit", tif="GTC", offset_bps=accumulate_offset_bps,
                  share=accumulate_share, cancel_after="1h")),
              until=std.time_reached(pump_at), then="pumping")
    org.state("pumping", branch={"dumping": (
        1.0, None,
        std.each_member("insider", o.base.place_order.with_params(
            symbol=target, side="buy", type="market", share=0.25)))})
    org.state("dumping", repeat=(dump_every, 1.0,
              o.base.place_order.with_params(
                  account=std.pick_member("insider", rotate=True), symbol=target, side="sell",
                  type="market", share=dump_share)),
              until=std.balance_below(std.base_of(target), share=0.05, of="peak"),
              timer={"cashing_out": dump_span}, then="cashing_out")
    org.state("cashing_out", branch={"gone": (
        1.0, dist.gamma(mean_days=0.5, shape=2.0),
        std.each_member("insider", o.base.withdraw.with_params(asset="USDT", share=0.9)))})
    org.final("gone", status="dormant")

    # ---------------------------------------------------------------- insiders
    ins = o.machine("insider", members=scheme.spawned("insider"), initial="registered")
    ins.state("registered", branch={"depositing": (
        1.0, dist.lognormal(median_s=7_200),
        o.base.deposit.with_params(asset="USDT", amount_usdt=seed_usdt))})
    ins.state("depositing", until=std.seen("deposit_credited", n=1), then="ready",
              timer={"ready": "1d"})
    ins.state("ready", branch={"idle": (1.0, None, std.send_parent("funded"))})
    ins.final("idle")                                           # organizer drives it from here

    # ---------------------------------------------------------------- followers (existing)
    crowd = o.cohort("pump_follower", table="trader", share=followers,
                     where="segment == 'retail' and status == 'active'", existing=True)
    o.link(crowd, scheme, by="hash")                            # each follower watches one scheme

    fol = o.machine("follower", members=crowd, initial="waiting")
    fol.state("waiting", branch={
        "bought": (follower_join_p, std.at(std.linked(pump_at), plus=follower_delay),
                   o.base.login.then(o.base.place_order.with_params(
                       symbol=std.linked(target), side="buy", type="market",
                       share=follower_buy_share))),
        "otherwise": (1 - follower_join_p, None, None),
    })
    fol.state("bought", branch={
        "exited": (follower_exit_p, follower_exit_after,
                   o.base.place_order.with_params(symbol=std.linked(target), side="sell",
                                                  type="market", share=1.0)),
        "held": (1 - follower_exit_p, None, None),
    })
    fol.final("exited", "held", "otherwise")

    # ---------------------------------------------------------------- labels (hidden)
    o.label(scheme, role={"organizer", "insider"}, outcome=("accumulated", "pumped", "dumped"),
            available_at=std.after("dumping", dist.gamma(mean_days=10, shape=2.0)))
    o.label(crowd, role={"follower"}, outcome=("bought", "exited", "held"),
            available_at=std.after("bought", dist.gamma(mean_days=14, shape=2.0)))
