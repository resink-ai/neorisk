"""Airdrop sybils: farmers fan funds out to fresh wallets, farm the airdrop, then consolidate.

A campaign is one funder, one collector and the sybil wallets the funder pays. All of them run
under one campaign owner (execution_owner="campaign_id"), so the funder can wait on its sybils
and the collector can wait on the funder without cross-owner messages. Each member is still its
own wallet with its own nonce and beliefs, and every transaction goes through the chain shard
like anyone else's. Claims draw on the same distributor balance as ordinary wallets' claims, so
large campaigns can exhaust it and make legitimate claims revert (reported as interference).

Timeline: funding and farming before airdrop.snapshot_at; claims after airdrop.claim_opens;
then each sybil sells or forwards the tokens and sweeps its ETH to the collector, and the
collector cashes out to its exchange.

    datagen run examples/layer1 --profile full --overlay airdrop_sybils \
        --set airdrop_sybils.size=80 --set airdrop_sybils.peel_chain_share=0.5
"""

from neorisk_simkit.spec import Overlay, dist, std

MILLI_ETH = 1_000_000_000                                       # quanta (1 quantum = 1e6 wei)


def apply(o: Overlay,
          size: int = 40,                                       # campaigns
          sybils: dist.Dist = dist.negbinom(mean=60, disp=0.6, min=10, max=400),
          arrive: dist.Dist = dist.burst(start="day 2", span="10d"),
          funding: dist.Dist = dist.lognormal_minor(median=40 * MILLI_ETH, sigma=0.35),
          peel_chain_share: float = 0.3,                        # campaigns funding via a chain
          peel_hops: dist.Dist = dist.uniform_int(2, 4),
          swaps: dist.Dist = dist.uniform_int(3, 6),            # scripted target interactions
          bridge_p: float = 0.5,                                # script includes one deposit
          step_gap: dist.Dist = dist.lognormal(median_h=6, sigma=0.8),
          claim_delay: dist.Dist = dist.exp(mean_h=4),
          consolidate: str = "swap_then_send",                  # or "send_token"
          tip: int = 50) -> None:                               # quanta per gas, fixed by script

    camp = o.cohort("airdrop_farm", table="wallet", size=size, arrivals=arrive,
                    execution_owner="campaign_id",              # funder + collector + sybils
                    suppress=["wallet_activity", "onboarding"],
                    attrs={"kind": "bot", "activity": "heavy", "origin": "new"})   # the funder

    # One script per campaign: the same ordered steps for every sybil, with per-member jitter.
    # Scripted farmers set no slippage limit (min_out=0) and a fixed tip: realistic tells.
    script = std.campaign_script(per="campaign", order="shuffled_once", steps={
        o.base.swap.with_params(value=std.share_of_belief(0.12), min_out=0, tip=tip,
                                contract=std.campaign_pick("pool")): swaps,
        o.base.bridge_deposit.with_params(value=std.share_of_belief(0.10), tip=tip,
                                          contract=std.campaign_pick("bridge")):
            dist.bernoulli(bridge_p),
    })

    # ---------------------------------------------------------------- funder
    f = o.machine("funder", members=camp, initial="new")
    f.state("new", branch={"funding": (
        1.0, dist.lognormal(median_s=600),
        std.emit("wallet_created")
        .then(std.spawn_members("collector", n=1, attrs={"kind": "retail", "origin": "new"},
                                on_create=std.emit("wallet_created")))
        .then(o.base.cex_withdraw.with_params(
            amount=std.per_member_total(funding, members="sybil", n=sybils, margin=1.25))))})
    f.state("funding", repeat=(dist.exp(mean_min=20), 1.0, o.base.sync_account),
            until=std.believed_balance_at_least(std.per_member_total(funding, members="sybil")),
            then="fanning", timer={"abandoned": "3d"})
    f.state("fanning", branch={"waiting": (
        1.0, dist.lognormal(median_s=300),
        std.spawn_members(
            "sybil", n=sybils, attrs={"kind": "retail", "activity": "casual", "origin": "new"},
            on_create=std.emit("wallet_created"),
            via=o.base.send_native.with_params(to_wallet=std.spawned(), value=funding, tip=tip),
            topology=std.topology(peel_chain=peel_chain_share, hops=peel_hops),
            start_on="included", stagger=dist.exp(mean_s=45)))})
    f.state("waiting", join={"cashing_out": ("sybil_done", "all_spawned")},
            timer={"cashing_out": "45d"}, late="count")
    f.state("cashing_out", branch={"gone": (1.0, None, std.send_member("collector", "cash_out"))})
    f.final("gone", "abandoned", status="dormant")

    # ---------------------------------------------------------------- sybil
    sy = o.machine("sybil", members=camp.spawned("sybil"), initial="funded")
    sy.state("funded", request={"farming": o.base.sync_account},       # learn the funding
             on_reject="gone", timeout="10m")
    sy.state("farming", repeat=(step_gap, 1.0, std.next_step(script)),
             max_repeats=std.script_len(script), then="waiting_claim",
             timer={"waiting_claim": std.before("airdrop.snapshot_at", "2h")})
    sy.state("waiting_claim", branch={"claiming": (
        1.0, std.after("airdrop.claim_opens", claim_delay), None)})
    sy.state("claiming", request={"claimed": o.base.claim_airdrop.with_params(tip=tip)},
             on_reject="sweeping", on_revert="sweeping", timeout="12h")
    if consolidate == "swap_then_send":
        sy.state("claimed", request={"sweeping": o.base.swap.with_params(
                     value=0, token_amount=std.ALL, min_out=0, tip=tip,
                     contract=std.contract_ref(kind="pool", token_of="airdrop"))},
                 on_reject="sweeping", on_revert="sweeping", timeout="12h")
    else:                                                              # "send_token"
        sy.state("claimed", request={"sweeping": o.base.send_token.with_params(
                     to_wallet=std.member_ref("collector"), token_amount=std.ALL, tip=tip,
                     contract=std.contract_ref(kind="token", token_of="airdrop"))},
                 on_reject="sweeping", on_revert="sweeping", timeout="12h")
    sy.state("sweeping", request={"consolidated": o.base.send_native.with_params(
                 to_wallet=std.member_ref("collector"), value=std.ALL, tip=tip)},
             on_reject="gone", timeout="12h")
    sy.state("consolidated", branch={"gone": (1.0, None, std.send_parent("sybil_done"))})
    sy.final("gone", status="dormant")

    # ---------------------------------------------------------------- collector
    c = o.machine("collector", members=camp.spawned("collector"), initial="idle")
    after_sync = "selling" if consolidate == "send_token" else "cashing_out"
    c.state("idle", until=std.received("cash_out"), then="syncing")
    c.state("syncing", request={after_sync: o.base.sync_account}, on_reject="idle",
            timeout="10m")
    if consolidate == "send_token":                                    # sell the pooled tokens
        c.state("selling", request={"cashing_out": o.base.swap.with_params(
                    value=0, token_amount=std.ALL, min_out=0, tip=tip,
                    contract=std.contract_ref(kind="pool", token_of="airdrop"))},
                on_reject="cashing_out", on_revert="cashing_out", timeout="12h")
    c.state("cashing_out", request={"gone": o.base.send_native.with_params(
                to_wallet=std.ref_of("exchange"), value=std.ALL, tip=tip)},
            on_reject="gone", timeout="12h")
    c.final("gone", status="dormant")

    # ---------------------------------------------------------------- labels (hidden)
    o.label(camp, role={"funder", "sybil", "collector"},
            outcome=("funded", "farmed", "claimed", "consolidated"),
            available_at=std.after("airdrop.claim_opens", dist.gamma(mean_days=14, shape=2.0)))
