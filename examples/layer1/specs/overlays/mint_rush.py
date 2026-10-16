"""Mint rush: a hyped NFT drop that congests the chain for about an hour.

Not a new kind of actor: a share of existing active wallets, plus most bots, mint one
collection when it opens, with high tips and generous fee caps. Blocks fill to the gas limit,
so the EIP-1559 base fee climbs about 12.5% per block; ordinary transactions whose fee caps were
set against the old base fee wait in the pool and expire, and most mints revert as sold out.
It stress-tests the hot chain shard (full 64-tx sub-steps every slot) and the fee-market laws.
No labels; the overlay only changes traffic.

    datagen run examples/layer1 --profile full --overlay mint_rush \
        --set mint_rush.at="day 12 17:00" --set mint_rush.supply=5000
"""

from neorisk_simkit.spec import Overlay, dist, std

GWEI = 1_000                                                    # quanta


def apply(o: Overlay,
          at: str = "day 12 17:00",                             # mint opens
          supply: int = 8_000,
          price_milli_eth: int = 80,
          participants: float = 0.02,                           # share of active wallets
          bot_participants: float = 0.6,                        # share of bots
          mints_per_wallet: dist.Dist = dist.geometric(mean=1.5, max=5),
          tip: dist.Dist = dist.lognormal_minor(median=8 * GWEI, sigma=1.0, max=500 * GWEI),
          bot_tip: dist.Dist = dist.lognormal_minor(median=60 * GWEI, sigma=0.8,
                                                    max=2_000 * GWEI),
          spread: dist.Dist = dist.exp(mean_min=4)) -> None:    # arrival after the opening

    hot = o.pick_contracts(kind="nft_collection", n=1, by="popularity")
    o.adjust_contract(hot, supply=supply, price=price_milli_eth * 1_000_000_000, opens_at=at)

    crowd = o.cohort("mint_rush_crowd", table="wallet", share=participants,
                     where="status == 'active' and kind in ('retail', 'trader')",
                     existing=True)                             # existing wallets; no new IDs
    bots = o.cohort("mint_rush_bots", table="wallet", share=bot_participants,
                    where="kind == 'bot'", existing=True)

    # Members keep their ordinary activity; the rush is extra. Gas limit is left to the
    # wallet's estimate; the fee cap is pinned high so the rising base fee doesn't price
    # them out (they pay it), while ordinary wallets' caps follow their stale belief.
    for cohort, tips, cap in ((crowd, tip, 300 * GWEI), (bots, bot_tip, 1_000 * GWEI)):
        m = o.machine(f"{cohort.name}_mint", members=cohort, initial="waiting")
        m.state("waiting", branch={"minting": (
            1.0, std.after(at, spread), o.base.sync_account)})
        m.state("minting", repeat=(dist.exp(mean_s=20), 1.0, o.base.mint_nft.with_params(
                    contract=hot, tip=tips, max_fee=cap)),
                max_repeats=mints_per_wallet, then="done",
                timer={"done": "2h"})
        m.final("done")
