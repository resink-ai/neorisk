"""Wash traders: rings of linked accounts that trade with each other to inflate volume.

A ring is one organizer plus 2-6 accounts that share devices and IPs. Organizer and accounts
run under one ring owner (execution_owner="ring_id"), so the organizer can drive both legs of
a wash trade without cross-owner messages. Each round, one account posts a GTC limit at the
reference price in the ring's illiquid symbol and another account takes it with an IOC at the
same price. The legs are separate place requests: the owner suspends on the first until the
book answers (>= 2 ms), so another trader can take the resting leg first; the GTC leg is
cancelled after `leg_timeout` if that happens. Self-trade prevention does not stop it: the
accounts are different traders. Rings share the book shard with everyone else, so base trades
in the target symbol are reported as interference.

    datagen run examples/crypto_exchange --profile full --overlay wash_traders \
        --set wash_traders.size=60 --set wash_traders.accounts=4
"""

from neorisk_simkit.spec import Overlay, dist, std


def apply(o: Overlay,
          size: int = 40,                                       # rings
          accounts: dist.Dist = dist.uniform_int(2, 6),         # trading accounts per ring
          share_device: float = 0.8,                            # account reuses ring device
          share_ip: float = 0.9,
          devices_per_ring: dist.Dist = dist.uniform_int(1, 3),
          arrive: dist.Dist = dist.burst(start="day 5", span="40d"),
          symbol_tier: str = "small",
          seed_usdt: dist.Dist = dist.lognormal_minor(median=15_000, sigma=0.6,
                                                      min=3_000, max=80_000),   # whole USDT
          seed_base_usdt: dist.Dist = dist.lognormal_minor(median=10_000, sigma=0.6,
                                                           min=2_000, max=50_000),
          round_every: dist.Dist = dist.exp(mean_s=50),
          rounds: dist.Dist = dist.negbinom(mean=6_000, disp=0.6, min=500, max=40_000),
          round_notional_usdt: dist.Dist = dist.lognormal_minor(median=600, sigma=0.7,
                                                                min=50, max=8_000),
          offset_bps: dist.Dist = dist.uniform(-15.0, 15.0),    # jitter around the reference
          leg_timeout: str = "20s",
          cash_out_share: float = 0.95) -> None:

    ring = o.cohort("wash_ring", table="trader", size=size, arrivals=arrive,
                    execution_owner="ring_id",                  # organizer + accounts = one owner
                    suppress=["trader_activity", "funding", "onboarding", "api_access"],
                    attrs={"segment": "pro",
                           "country": dist.categorical({"other": .5, "TR": .2, "VN": .15,
                                                        "NG": .15})},
                    refs={"device": std.device_pool(per_owner=devices_per_ring),
                          "ip": std.ip_pool(per_owner=dist.uniform_int(1, 2), kind="vpn")})
    target = o.pick_symbols(tier=symbol_tier, n=1, per_owner=True, by="lowest_volume")
    pair = std.pick_pair("wash_account", rotate=True)          # two distinct accounts per round

    # ---------------------------------------------------------------- organizer
    org = o.machine("ring_organizer", members=ring, initial="new")
    org.state("new", branch={"funding": (
        1.0, dist.lognormal(median_s=1_800),
        o.base.register.then(o.base.upgrade_kyc.with_params(level=1)).then(
            std.spawn_members("wash_account", n=accounts, via=o.base.register,
                              refs={"device": std.share_with_parent(share_device),
                                    "ip": std.share_with_parent(share_ip),
                                    "address": std.share_with_parent(1.0)},
                              stagger=dist.exp(mean_s=900))))})
    org.state("funding", join={"washing": ("funded", "all_spawned")},
              timer={"washing": "3d"}, late="ignore")
    org.state("washing", repeat=(round_every, 1.0,
              o.base.place_order.with_params(                  # leg 1: rests on the book
                  account=pair.a, symbol=target, side=pair.side_a, type="limit", tif="GTC",
                  offset_bps=offset_bps, notional_usdt=round_notional_usdt,
                  cancel_after=leg_timeout)
              .then(o.base.place_order.with_params(             # leg 2: takes it, same price
                  account=pair.b, symbol=target, side=pair.side_b, type="limit", tif="IOC",
                  price=std.last("price"), qty=std.last("qty")))),
              max_repeats=rounds, then="unwinding")
    org.state("unwinding", branch={"gone": (
        1.0, dist.gamma(mean_days=1.5, shape=2.0),
        std.each_member("wash_account", o.base.withdraw.with_params(
            asset="USDT", share=cash_out_share, address=std.shared_ref("address"))))})
    org.final("gone", status="dormant")

    # ---------------------------------------------------------------- accounts
    acct = o.machine("wash_account", members=ring.spawned("wash_account"), initial="registered")
    acct.state("registered", branch={"depositing": (
        1.0, dist.lognormal(median_s=3_600),
        o.base.deposit.with_params(asset="USDT", amount_usdt=seed_usdt).then(
            o.base.deposit.with_params(asset=std.base_of(target),
                                       amount_usdt=seed_base_usdt)))})
    acct.state("depositing", until=std.seen("deposit_credited", n=2), then="ready",
               timer={"ready": "1d"})
    acct.state("ready", branch={"idle": (1.0, None, std.send_parent("funded"))})
    acct.final("idle")                                          # organizer drives it from here

    # ---------------------------------------------------------------- labels (hidden)
    o.label(ring, role={"organizer", "account"}, outcome=("funded", "washing", "cashed_out"),
            available_at=std.after("washing", dist.gamma(mean_days=21, shape=2.0)))
