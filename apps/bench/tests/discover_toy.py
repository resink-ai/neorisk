"""A 30-user world built by hand: 25 ordinary shoppers (five share a café device, one invites
two friends) and a ring of 5 (a hunter and 4 zombies on the hunter's device, in lockstep)."""

from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl

from bench.discover.world import World

T0 = datetime(2026, 1, 1, tzinfo=UTC)
RING = [26, 27, 28, 29, 30]
PRICES = {1: 1000, 2: 3200, 3: 5000, 4: 8000}       # sku 2: cheapest qualifying (min 3000)


def _t(h: float) -> datetime:
    return T0 + timedelta(hours=h)


def toy_world() -> World:
    users, devices, sess, views, signups, orders, bonuses = [], [], [], [], [], [], []
    sid, oid = [1000], [5000]

    def session(u, d, h, skus):
        sid[0] += 1
        sess.append((_t(h), u, d, sid[0]))
        views.extend((_t(h + 0.01 * k), u, d, sid[0], s) for k, s in enumerate(skus))

    def order(u, h, sku, amount):
        oid[0] += 1
        orders.append((oid[0], _t(h), u, sku, 1, 1, amount))

    for u in range(1, 26):
        inviter = 1 if u in (2, 3) else None
        h = u * 5.0
        users.append((u, _t(h), "25-34", "west", "invite" if inviter else "organic", inviter))
        devices.append((100 + u, _t(h), u, "ios", "phone"))
        signups.append((_t(h), u, 100 + u, inviter, "invite" if inviter else "organic"))
        for k, sku in enumerate((3, 4, 1)):
            d = 200 if 10 <= u <= 14 and k == 1 else 100 + u          # the café device
            session(u, d, h + 10 + 30 * k, [1, 2, 3, 4])
            order(u, h + 10.5 + 30 * k, sku, PRICES[sku])
        if inviter:
            bonuses.append((_t(h + 20), 1, u, 1000))
    devices.append((200, _t(0), 10, "android", "tablet"))
    users.append((26, _t(200), "18-24", "east", "ads", None))
    devices.append((300, _t(200), 26, "android", "phone"))
    signups.append((_t(200), 26, 300, None, "ads"))
    session(26, 300, 200.2, [2])
    for z in RING[1:]:
        h = 200 + (z - 26) * 0.5
        users.append((z, _t(h), "18-24", "east", "invite", 26))
        signups.append((_t(h), z, 300, 26, "invite"))
        session(z, 300, h + 0.1, [2])
        order(z, 210 + (z - 26) * 0.2, 2, 3050)
        bonuses.append((_t(212 + (z - 26) * 0.1), 26, z, 1000))
    order(26, 230, 2, 3080)

    u = pl.DataFrame(users, orient="row", schema=["user_id", "created_at", "age_band", "region",
                                                  "acquisition", "invited_by"])
    return World(
        users=u.sort("created_at", "user_id"),
        devices=pl.DataFrame(devices, orient="row",
                             schema=["device_id", "created_at", "user_id", "os", "kind"]),
        skus=pl.DataFrame([(s, T0, "c", p) for s, p in PRICES.items()], orient="row",
                          schema=["sku_id", "created_at", "category", "price"]),
        orders=pl.DataFrame(orders, orient="row", schema=["order_id", "created_at", "user_id",
                                                          "sku_id", "quantity", "lines", "amount"]),
        sessions=pl.DataFrame(sess, orient="row",
                              schema=["event_time", "user_id", "device_id", "session_id"]),
        views=pl.DataFrame(views, orient="row", schema=["event_time", "user_id", "device_id",
                                                        "session_id", "sku_id"]),
        signups=pl.DataFrame(signups, orient="row", schema=["event_time", "user_id", "device_id",
                                                            "invited_by", "acquisition"]),
        returns=pl.DataFrame(schema={"event_time": pl.Datetime("us", "UTC"),
                                     "user_id": pl.Int64, "order_id": pl.Int64,
                                     "amount": pl.Int64}),
        bonuses=pl.DataFrame(bonuses, orient="row",
                             schema=["event_time", "user_id", "invitee_id", "amount"]),
        addresses=pl.DataFrame(schema={"event_time": pl.Datetime("us", "UTC"),
                                       "user_id": pl.Int64, "region": pl.String}),
        user_ids=u.sort("created_at", "user_id")["user_id"].to_numpy(),
        min_order_cents=3000,
    )


def ring_mask(world: World) -> np.ndarray:
    return np.isin(world.user_ids, RING)
