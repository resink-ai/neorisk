"""Flash sale: a one-day promotion on one category.

Not a new kind of actor: a share of ordinary shoppers gets an extra session on the sale day,
biased toward a few hot SKUs that all live in one inventory group. That concentrates reserve
requests on one shard, which is the point: it stress-tests a hot shard and produces realistic
out-of-stock failures. No labels; the overlay only changes traffic.

    datagen run examples/ecommerce --profile full --overlay flash_sale \
        --set flash_sale.day=2026-02-14 --set flash_sale.lift=8
"""

from neorisk_simkit.spec import Overlay, dist, std


def apply(o: Overlay,
          day: str = "day 45",
          category: str = "electronics",
          hot_skus: int = 12,
          lift: float = 8.0,                                    # traffic multiplier on the day
          participants: float = 0.15,                           # share of active shoppers
          hot_view_share: float = 0.6,                          # views landing on hot SKUs
          stock_multiplier: float = 3.0) -> None:

    hot = o.pick_skus(category=category, n=hot_skus, same_group=True, by="popularity")
    o.adjust_stock(hot, multiply=stock_multiplier, at=std.before(day, "1d"))

    crowd = o.cohort("flash_sale_crowd", table="user", share=participants,
                     where="status == 'active'", existing=True)  # existing users; no new IDs

    m = o.machine("flash_visit", members=crowd, initial="waiting")
    m.state("waiting", branch={"visiting": (
        1.0, dist.intraday(day, peak="12:00", sd_h=3.0, lift=lift),
        o.base.session.with_params(bias=std.view_bias(hot, share=hot_view_share),
                                   checkout_p=0.22))})
    m.final("visiting")
