"""E-commerce scenario with referrals and bounty-hunter rings, on `sim.Simulation`.

Shoppers sign up, run sessions (view products, sometimes check out), place orders, sometimes
return them, and sometimes move region. A referred shopper's first qualifying order pays its
inviter a bonus from a monthly budget, after a delay. Bounty hunters run rings: zombies sign
up on shared devices, invited by the hunter, each places one order just above the minimum, and
the hunter is paid through the same delayed credit path as everyone else (no timing tell).
Hunters and zombies are labeled.

Work is O(events): each user schedules a bounded number of sessions per day of span.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import polars as pl

from neorisk_simkit.sim import DAY, Simulation

AGE_BANDS = ["18-24", "25-34", "35-44", "45-54", "55+"]
REGIONS = ["CA", "TX", "NY", "FL", "WA", "IL", "PA", "OH"]
CHANNELS = ["organic", "ads", "social", "invite"]
OSES = ["ios", "android", "windows", "macos"]
KINDS = ["phone", "tablet", "desktop"]
CATEGORIES = ["books", "electronics", "home", "fashion", "toys", "grocery"]


@dataclass
class Config:
    users: int = 2000
    days: float = 30.0
    seed: int = 7
    start: datetime = datetime(2026, 1, 1)
    skus: int = 400
    sku_zipf: float = 1.1
    sessions_per_day: float = 0.25
    views_mean: float = 3.0
    checkout_p: float = 0.08
    order_p: float = 0.8          # checkout -> order (the rest abandon or fail payment)
    return_p: float = 0.06
    move_p_per_day: float = 0.002
    referred_share: float = 0.3
    min_order_cents: int = 3000
    bonus_cents: int = 1000
    monthly_budget_cents: int = 2_000_000
    credit_delay_days: tuple[float, float] = (1.0, 3.0)
    ring_share: float = 0.002     # rings per base user
    zombies_mean: float = 8.0
    ring_arrive_span: float = 0.8   # rings arrive over this share of the span


@dataclass
class World:
    cfg: Config
    sim: Simulation
    users: dict[str, list] = field(default_factory=lambda: {
        "user_id": [], "age_band": [], "region": [], "acquisition": [], "invited_by": []})
    devices: dict[str, list] = field(default_factory=lambda: {
        "device_id": [], "user_id": [], "os": [], "kind": []})
    labels: dict[str, list] = field(default_factory=lambda: {"user_id": [], "role": []})
    user_devices: dict[int, list[int]] = field(default_factory=dict)
    region: dict[int, int] = field(default_factory=dict)
    paid_invitees: set[int] = field(default_factory=set)
    budget_used: dict[int, int] = field(default_factory=dict)
    hunters: dict[int, tuple[int, int]] = field(default_factory=dict)  # uid -> (device, sku)


def _pick(rng: np.random.Generator, n: int) -> int:
    return int(rng.integers(n))


def _new_device(w: World, uid: int) -> int:
    rng = w.sim.rng
    did = w.sim.next_id("device")
    for k, v in (("device_id", did), ("user_id", uid), ("os", _pick(rng, len(OSES))),
                 ("kind", _pick(rng, len(KINDS)))):
        w.devices[k].append(v)
    w.user_devices.setdefault(uid, []).append(did)
    return did


def _new_user(w: World, invited_by: int | None, channel: int | None = None) -> int:
    rng = w.sim.rng
    uid = w.sim.next_id("user")
    region = _pick(rng, len(REGIONS))
    w.region[uid] = region
    acq = channel if channel is not None else (
        CHANNELS.index("invite") if invited_by else _pick(rng, len(CHANNELS) - 1))
    for k, v in (("user_id", uid), ("age_band", _pick(rng, len(AGE_BANDS))), ("region", region),
                 ("acquisition", acq), ("invited_by", invited_by)):
        w.users[k].append(v)
    return uid


def _signup(w: World, uid: int, device: int) -> None:
    i = uid - 1
    w.sim.emit("user_signed_up", user_id=uid, device_id=device,
               invited_by=w.users["invited_by"][i], acquisition=w.users["acquisition"][i])


def _sku_price(skus: pl.DataFrame, sku: int) -> int:
    return int(skus["price"][sku - 1])


# ---------------------------------------------------------------- shoppers

def _session(w: World, uid: int, skus: pl.DataFrame, weights: np.ndarray) -> None:
    sim, cfg, rng = w.sim, w.cfg, w.sim.rng
    devs = w.user_devices[uid]
    device = devs[_pick(rng, len(devs))]
    sid = sim.next_id("session")
    sim.emit("session_started", user_id=uid, device_id=device, session_id=sid)
    viewed = rng.choice(len(weights), size=1 + rng.poisson(cfg.views_mean - 1), p=weights) + 1
    for sku in viewed:
        sim.emit("product_viewed", user_id=uid, device_id=device, session_id=sid, sku_id=int(sku))
    if rng.random() < cfg.checkout_p and rng.random() < cfg.order_p:
        sku = int(viewed[-1])
        qty = 1 + int(rng.poisson(0.3))
        _order(w, uid, device, sku, qty * _sku_price(skus, sku))
    if rng.random() < cfg.move_p_per_day / max(cfg.sessions_per_day, 1e-9):
        w.region[uid] = _pick(rng, len(REGIONS))
        sim.emit("address_changed", user_id=uid, region=w.region[uid])
    sim.after(rng.exponential(DAY / cfg.sessions_per_day), _session, w, uid, skus, weights)


def _order(w: World, uid: int, device: int, sku: int, amount: int) -> None:
    sim, cfg, rng = w.sim, w.cfg, w.sim.rng
    oid = sim.next_id("order")
    sim.emit("order_placed", user_id=uid, device_id=device, order_id=oid, sku_id=sku,
             amount=amount)
    if rng.random() < cfg.return_p:
        sim.after(rng.uniform(1, 20) * DAY, _return, w, uid, oid, amount)
    inviter = w.users["invited_by"][uid - 1]
    if inviter and uid not in w.paid_invitees and amount >= cfg.min_order_cents:
        w.paid_invitees.add(uid)
        lo, hi = cfg.credit_delay_days
        sim.after(rng.uniform(lo, hi) * DAY, _credit, w, inviter, uid)


def _return(w: World, uid: int, oid: int, amount: int) -> None:
    w.sim.emit("order_returned", user_id=uid, order_id=oid, amount=amount)


def _credit(w: World, inviter: int, invitee: int) -> None:
    sim, cfg = w.sim, w.cfg
    month = int(sim.now // (30 * DAY))
    if w.budget_used.get(month, 0) + cfg.bonus_cents > cfg.monthly_budget_cents:
        sim.emit("referral_bonus_rejected", user_id=inviter, invitee_id=invitee)
        return
    w.budget_used[month] = w.budget_used.get(month, 0) + cfg.bonus_cents
    sim.emit("referral_bonus_paid", user_id=inviter, invitee_id=invitee, amount=cfg.bonus_cents)
    if inviter in w.hunters:                      # hunters cash bonuses out in orders
        device, sku = w.hunters[inviter]
        sim.after(sim.rng.uniform(0.2, 2.0) * DAY, _order, w, inviter, device, sku,
                  cfg.bonus_cents + int(sim.rng.integers(0, 500)))


def _arrive(w: World, uid: int, skus: pl.DataFrame, weights: np.ndarray) -> None:
    device = _new_device(w, uid)
    if w.sim.rng.random() < 0.3:
        _new_device(w, uid)
    _signup(w, uid, device)
    _session(w, uid, skus, weights)


# ---------------------------------------------------------------- bounty hunters

def _ring(w: World, skus: pl.DataFrame) -> None:
    sim, cfg, rng = w.sim, w.cfg, w.sim.rng
    hunter = _new_user(w, None)
    w.labels["user_id"].append(hunter)
    w.labels["role"].append("hunter")
    shared = [_new_device(w, hunter) for _ in range(1 + int(rng.integers(2)))]
    _signup(w, hunter, shared[0])
    cheap = skus.filter(pl.col("price") >= cfg.min_order_cents).sort("price")["sku_id"][0]
    w.hunters[hunter] = (shared[0], int(cheap))
    for _ in range(1 + int(rng.poisson(cfg.zombies_mean - 1))):
        sim.after(rng.uniform(0, 2) * DAY, _zombie, w, hunter, shared, int(cheap))


def _zombie(w: World, hunter: int, shared: list[int], sku: int) -> None:
    sim, rng = w.sim, w.sim.rng
    uid = _new_user(w, hunter)
    w.labels["user_id"].append(uid)
    w.labels["role"].append("zombie")
    device = shared[_pick(rng, len(shared))]
    w.user_devices[uid] = [device]
    _signup(w, uid, device)
    sim.after(rng.uniform(0.1, 1.0) * DAY, _zombie_order, w, uid, device, sku)


def _zombie_order(w: World, uid: int, device: int, sku: int) -> None:
    sid = w.sim.next_id("session")
    w.sim.emit("session_started", user_id=uid, device_id=device, session_id=sid)
    w.sim.emit("product_viewed", user_id=uid, device_id=device, session_id=sid, sku_id=sku)
    _order(w, uid, device, sku, w.cfg.min_order_cents + int(w.sim.rng.integers(0, 150)))


# ---------------------------------------------------------------- run

def simulate(cfg: Config) -> dict[str, pl.DataFrame]:
    """Run the scenario; returns entity tables (`users`, `devices`, `skus`, `labels`) and one
    table per event type."""
    sim = Simulation(cfg.seed, cfg.start, cfg.days)
    w = World(cfg, sim)
    rng = sim.rng
    skus = pl.DataFrame({
        "sku_id": np.arange(1, cfg.skus + 1),
        "category": rng.integers(0, len(CATEGORIES), cfg.skus),
        "price": (np.exp(rng.normal(np.log(2500), 0.8, cfg.skus))).astype(np.int64) + 99,
    })
    weights = 1.0 / np.arange(1, cfg.skus + 1) ** cfg.sku_zipf
    weights /= weights.sum()

    for _ in range(cfg.users):
        uid = _new_user(w, None)
        if uid > 1 and rng.random() < cfg.referred_share:
            inviter = 1 + _pick(rng, uid - 1)
            w.users["invited_by"][-1] = inviter
            w.users["acquisition"][-1] = CHANNELS.index("invite")
        sim.at(rng.uniform(0, cfg.days * 0.5) * DAY, _arrive, w, uid, skus, weights)
    for _ in range(max(1, round(cfg.users * cfg.ring_share))):
        sim.at(rng.uniform(0, cfg.days * cfg.ring_arrive_span) * DAY, _ring, w, skus)

    sim.run()
    out = sim.tables()
    out["users"] = pl.DataFrame(w.users, schema_overrides={"invited_by": pl.Int64})
    out["devices"] = pl.DataFrame(w.devices)
    out["skus"] = skus
    out["labels"] = pl.DataFrame(w.labels, schema={"user_id": pl.Int64, "role": pl.String})
    return out


def write(tables: dict[str, pl.DataFrame], out_dir, cfg: Config) -> None:
    import json
    from dataclasses import asdict
    from pathlib import Path

    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.write_parquet(d / f"{name}.parquet")
    (d / "manifest.json").write_text(json.dumps(
        {"scenario": "ecommerce", "config": asdict(cfg),
         "counts": {k: v.height for k, v in tables.items()}}, indent=2, default=str))
