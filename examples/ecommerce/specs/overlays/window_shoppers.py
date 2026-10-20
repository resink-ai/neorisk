"""Window shoppers: visitors who sign up and browse but never check out.

They share no decision-relevant state with the base pack (no inventory, no referral pool), so
the regression rule requires every base row to be identical with and without them.
"""

from __future__ import annotations

import numpy as np

from neorisk_simkit.engine import DAY
from neorisk_simkit.spec.overlay import Overlay


def apply(o: Overlay, size: int = 40, sessions_per_day: float = 1.0) -> None:
    o.cohort("window_shopper", kind="user", size=size, suppress=["shopper"])
    browse = o.process("user", "browsing", cohort="window_shopper", start="arrive_to_look")

    @browse.action
    def arrive_to_look(ctx, s, cmd):
        ctx.call("signup")
        ctx.call("look")

    @browse.action
    def look(ctx, s, cmd):
        rng, cat = ctx.rng, ctx.shared.catalog
        device = s.devices[0]
        sid = ctx.new_id("session")
        ctx.emit("session_started", user_id=s.uid, device_id=device, session_id=sid)
        for sku in np.searchsorted(cat.cdf, rng.random(1 + rng.poisson(4)), side="right") + 1:
            ctx.emit("product_viewed", user_id=s.uid, device_id=device, session_id=sid,
                     sku_id=int(sku))
        ctx.after(rng.exponential(DAY / sessions_per_day), "look")
