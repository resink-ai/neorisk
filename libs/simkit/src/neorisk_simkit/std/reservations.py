"""Shard-side reservations with a TTL (§06 multi-shard decisions): an inventory shard grants a
unit on request and holds it until the owner commits or releases it, or the TTL frees it.

    @dataclass
    class Inventory(reservations.Stock): ...
    inv = p.shard("inventory", state=Inventory, latency=Latency(0.2, 0.5))
    reservations.install(p, inv, item="sku_id", item_ref="skus", ttl=600)

    # owner side: reserve in each shard, join on the replies, then commit all or release all
    ctx.request(shard, "reserve", reply="reserved", item=sku, qty=1, timeout=30)
    ctx.send(shard, "commit_reservation", reservation=rid)     # or "release_reservation"

Rows: reservation_granted / _declined / _committed / _released (reason released | expired).
Laws: every grant is committed or released by its TTL (`checks.laws.reservations_resolved`);
stock never goes negative.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from neorisk_simkit.spec.pack import Kind, Pack
from neorisk_simkit.spec.types import cat, i32, i64, ref


@dataclass
class Stock:
    units: dict[int, int] = field(default_factory=dict)              # item -> available
    held: dict[int, tuple[int, int, int]] = field(default_factory=dict)   # id -> item, qty, owner


def install(p: Pack, kind: Kind, *, item: str = "item_id", item_ref: str | None = None,
            ttl: float = 600.0) -> None:
    item_t = ref(item_ref) if item_ref else i64()
    base = {"reservation_id": i64(), item: item_t, "qty": i32(min=1),
            "owner_partition": i64(doc="The requesting partition")}
    p.event("reservation_granted", cols={**base, "expires_in": i64(doc="TTL in seconds")},
            doc=f"A {kind.name} shard holds units for an owner")
    p.event("reservation_declined", cols={item: item_t, "qty": i32(min=1),
                                          "owner_partition": i64(),
                                          "reason": cat("out_of_stock")})
    p.event("reservation_committed", cols=base)
    p.event("reservation_released", cols={**base, "reason": cat("released", "expired")})
    proc = kind.process("reservations", doc="Grant, commit, release and expire unit holds")

    @proc.action
    def reserve(ctx, s, cmd):
        it, qty = cmd.item, cmd.qty
        if s.units.get(it, 0) < qty:
            ctx.emit("reservation_declined", **{item: it}, qty=qty, owner_partition=cmd.sender,
                     reason="out_of_stock")
            return ctx.decline("out_of_stock", item=it)
        s.units[it] -= qty
        rid = ctx.new_id("reservation")
        s.held[rid] = (it, qty, cmd.sender)
        ctx.emit("reservation_granted", reservation_id=rid, **{item: it}, qty=qty,
                 owner_partition=cmd.sender, expires_in=int(ttl))
        ctx.after(ttl, "expire_reservation", reservation=rid)
        return ctx.reply(reservation=rid, item=it, qty=qty)

    def _free(ctx, s, rid: int, event: str, reason: str | None):
        if rid not in s.held:
            return ctx.reject("not_held")                 # already expired or resolved
        it, qty, owner = s.held.pop(rid)
        if reason is not None:
            s.units[it] += qty
        extra = {"reason": reason} if reason is not None else {}
        ctx.emit(event, reservation_id=rid, **{item: it}, qty=qty, owner_partition=owner,
                 **extra)

    @proc.action
    def commit_reservation(ctx, s, cmd):
        return _free(ctx, s, cmd.reservation, "reservation_committed", None)

    @proc.action
    def release_reservation(ctx, s, cmd):
        return _free(ctx, s, cmd.reservation, "reservation_released", "released")

    @proc.action
    def expire_reservation(ctx, s, cmd):
        if cmd.reservation not in s.held:
            return ctx.commit()                          # resolved before its TTL: the norm
        return _free(ctx, s, cmd.reservation, "reservation_released", "expired")
