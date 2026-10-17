"""Reference models of shard and owner decisions (spec §11: "Reference implementations for ...
holds run against the real kernels on fixtures in CI").

Each model is plain Python over one dataset's event tables (`io.read.read_events`). It merges
the tables one partition (or owner) writes, steps through them in execution order
`(event_time, lamport, seq)` with its own state, and predicts every decision the compiled kernel
made (`partition_id` in the sort key keeps the order canonical; every replayed stream is one
partition). A model returns one line per disagreement, naming the event, `partition_id`, `seq` and
the expected vs observed value; an empty list means the kernel agrees. The models assume the
stream holds the whole history (warm-up 0), so their state starts from the world's initial one.

- `replay_inventory`: the hold table and stock of each inventory group (D49, `std.reservations`).
- `replay_pool`: the capped bonus pool (§07, `std.capped_pool`).
- `replay_refunds`: refund holds, idempotency keys and the dispute sub-lifecycle of a payment
  (§09, D51).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import polars as pl

_ORDER = ("event_time", "lamport", "partition_id", "seq")     # the canonical key


def _rows(events: dict[str, pl.DataFrame], cols: dict[str, tuple[str, ...]],
          by: str | None) -> Iterator[dict[str, Any]]:
    """Rows of the tables `cols` (table -> columns wanted), tagged with their table in `_ev`
    and with `event_time` in UTC microseconds in `_t`, in
    `(by, event_time, lamport, partition_id, seq)` order; cat columns come back as strings."""
    frames = []
    for name, want in cols.items():
        f = events.get(name)
        if f is None or f.height == 0:
            continue
        keep = dict.fromkeys((*([by] if by else []), *_ORDER, *want))
        sel = [pl.col(c).cast(pl.String) if isinstance(f.schema[c], (pl.Categorical, pl.Enum))
               else pl.col(c) for c in keep]
        frames.append(f.select(sel).with_columns(pl.lit(name).alias("_ev"),
                                                 pl.col("event_time").dt.epoch("us").alias("_t")))
    if not frames:
        return iter(())
    merged = pl.concat(frames, how="diagonal_relaxed")
    return merged.sort([*([by] if by else []), *_ORDER]).iter_rows(named=True)


def _miss(r: dict[str, Any], what: str, expected: Any, observed: Any) -> str:
    return (f"{r['_ev']} (partition_id {r['partition_id']}, seq {r['seq']}): {what}: "
            f"expected {expected!r}, observed {observed!r}")


# ---------------------------------------------------------------------------- inventory
_INVENTORY = {
    "stock_reserved": ("sku_id", "checkout_id", "hold_id", "quantity"),
    "stock_rejected": ("sku_id", "checkout_id", "quantity", "reason"),
    "stock_committed": ("sku_id", "checkout_id", "hold_id", "quantity", "on_hand_after"),
    "stock_released": ("sku_id", "checkout_id", "hold_id", "quantity"),
    "stock_expired": ("sku_id", "checkout_id", "hold_id", "quantity"),
    "stock_commit_late": ("sku_id", "checkout_id", "hold_id", "quantity"),
    "restocked": ("sku_id", "quantity", "on_hand_after"),
}


def replay_inventory(events: dict[str, pl.DataFrame], on_hand0: dict[int, int],
                     slots: int, sku_group: dict[int, int] | None = None,
                     hold_ttl_us: int | None = None) -> list[str]:
    """Replay every inventory group's decisions. `on_hand0` maps public SKU IDs to their
    initial stock; `slots` is the hold-table size; `sku_group`, when given, maps public SKU IDs
    to their group, and every row's SKU must belong to the row's group. Every hold ID is issued
    once. With `hold_ttl_us`, TTL timing is replayed too: a hold expires exactly `hold_ttl_us`
    after its reserve and never outlives that instant, a commit or release at or before it is on
    time (messages run before the TTL timer at an equal instant, D49), a late commit comes after
    it. A reserve is granted iff
    `on_hand - reserved >= quantity` and fewer than `slots` holds are live; a rejection says
    `out_of_stock` when stock is short, else `busy`. Commits, releases and expiries name a live
    hold of that SKU, checkout and quantity and free it; `stock_commit_late` names a hold of this
    group, SKU, checkout and quantity that its TTL expired, and moves nothing; `on_hand_after`
    matches the model's stock."""
    out: list[str] = []
    on_hand = dict(on_hand0)
    reserved: dict[int, int] = {}
    live: dict[int, dict[int, tuple[int, int, int]]] = {}     # group -> hold -> (sku, ckt, qty)
    dead: dict[int, tuple[int, tuple[int, int, int], str]] = {}   # hold -> (group, hold, how)
    issued: set[int] = set()
    due: dict[int, int] = {}                                 # hold -> its TTL instant
    overdue: set[int] = set()                                # holds already reported overdue
    for r in _rows(events, _INVENTORY, "sku_group"):
        ev, sku, qty = r["_ev"], r["sku_id"], r["quantity"]
        holds = live.setdefault(r["sku_group"], {})
        t = r["_t"]
        if hold_ttl_us is not None:
            for h in holds:
                if due[h] < t and h not in overdue:
                    overdue.add(h)
                    out.append(_miss(r, f"hold {h} live past its TTL instant", due[h], t))
        if sku not in on_hand:
            out.append(_miss(r, "SKU of the group", "a SKU with initial stock", sku))
            continue
        if sku_group is not None and sku_group.get(sku) != r["sku_group"]:
            out.append(_miss(r, f"group of SKU {sku}", sku_group.get(sku), r["sku_group"]))
        free = on_hand[sku] - reserved.get(sku, 0)
        if ev == "restocked":
            if qty < 1:
                out.append(_miss(r, "restock quantity", ">= 1", qty))
            on_hand[sku] += qty
            if r["on_hand_after"] != on_hand[sku]:
                out.append(_miss(r, "on_hand_after", on_hand[sku], r["on_hand_after"]))
                on_hand[sku] = r["on_hand_after"]
        elif ev in ("stock_reserved", "stock_rejected"):
            short = free < qty
            grant = not short and len(holds) < slots
            if (ev == "stock_reserved") != grant:
                why = ("granted" if grant else
                       f"rejected ({'out_of_stock' if short else 'busy'})")
                out.append(_miss(r, f"decision (free {free}, live holds {len(holds)})", why,
                                 ev))
            if ev == "stock_rejected" and not grant:
                want = "out_of_stock" if short else "busy"
                if r["reason"] != want:
                    out.append(_miss(r, "reason", want, r["reason"]))
            if ev == "stock_reserved":
                hold = r["hold_id"]
                if hold in issued:
                    out.append(_miss(r, "hold_id", "a hold ID never issued before", hold))
                issued.add(hold)
                if hold_ttl_us is not None:
                    due[hold] = t + hold_ttl_us
                holds[hold] = (sku, r["checkout_id"], qty)
                reserved[sku] = reserved.get(sku, 0) + qty
        elif ev == "stock_commit_late":
            hold = r["hold_id"]
            want = (r["sku_group"], (sku, r["checkout_id"], qty), "stock_expired")
            if dead.get(hold) != want:
                got = dead.get(hold) or ("live" if hold in issued else "never issued")
                out.append(_miss(r, f"hold {hold} (group, (sku_id, checkout_id, quantity), "
                                 "ended by)", want, got))
            if hold_ttl_us is not None and hold in due and not t > due[hold]:
                out.append(_miss(r, "late commit time", f"> {due[hold]}", t))
        else:                                       # committed, released, expired
            hold = r["hold_id"]
            h = holds.pop(hold, None)
            if h is None:
                out.append(_miss(r, "hold", "a live hold", hold))
                continue
            dead[hold] = (r["sku_group"], h, ev)
            if hold_ttl_us is not None:
                on_time = t == due[hold] if ev == "stock_expired" else t <= due[hold]
                if not on_time:
                    out.append(_miss(r, "time", f"{'==' if ev == 'stock_expired' else '<='} "
                                     f"{due[hold]}", t))
            if h != (sku, r["checkout_id"], qty):
                out.append(_miss(r, "(sku_id, checkout_id, quantity)", h,
                                 (sku, r["checkout_id"], qty)))
            hsku, _, hqty = h
            reserved[hsku] = reserved.get(hsku, 0) - hqty
            if ev == "stock_committed":
                on_hand[hsku] -= hqty
                if r["on_hand_after"] != on_hand[hsku]:
                    out.append(_miss(r, "on_hand_after", on_hand[hsku], r["on_hand_after"]))
                    on_hand[hsku] = r["on_hand_after"]
    return out


# ---------------------------------------------------------------------------- pool
_POOL = {"bonus_granted": ("claim_id", "amount", "remaining_after"),
         "bonus_rejected": ("claim_id", "amount")}


def replay_pool(events: dict[str, pl.DataFrame], cap: int) -> list[str]:
    """Replay the pool's claims from `cap`: a claim is granted whole iff
    `0 < amount <= remaining`, else rejected; `remaining_after` matches the model."""
    out: list[str] = []
    remaining = int(cap)
    for r in _rows(events, _POOL, None):
        amt = r["amount"]
        grant = 0 < amt <= remaining
        if (r["_ev"] == "bonus_granted") != grant:
            out.append(_miss(r, f"decision (claim {amt}, remaining {remaining})",
                             "granted" if grant else "rejected", r["_ev"]))
        if r["_ev"] == "bonus_granted":
            remaining -= amt
            if r["remaining_after"] != remaining:
                out.append(_miss(r, "remaining_after", remaining, r["remaining_after"]))
                remaining = r["remaining_after"]
    return out


# ---------------------------------------------------------------------------- refunds
_PAYMENT = {
    "payment_captured": ("amount",),
    "payment_expired": ("amount",),
    "payment_declined": ("amount",),
    "refund_requested": ("refund_id", "amount"),
    "refund_rejected": ("refund_id", "reason"),
    "refund_settled": ("refund_id", "amount", "refunded_after"),
    "refund_failed": ("refund_id", "amount"),
    "refund_replayed": ("refund_id", "result"),
    "dispute_opened": ("amount",),
    "dispute_won": ("amount",),
    "dispute_lost": ("amount",),
}
IDEM_SLOTS = 4                            # refund idempotency keys per payment (S2 pack)


class _Pay:
    __slots__ = ("captured", "dispute", "disputed", "ended", "held", "keys", "refunded")

    def __init__(self) -> None:
        self.captured: int | None = None   # None until captured
        self.ended = False                 # expired or declined
        self.refunded = 0
        self.held = 0                      # Σ amounts of refunds requested, not yet settled/failed
        self.keys: dict[int, list] = {}    # refund_id -> [first result, amount, open]
        self.dispute = "none"              # none | open | won | lost
        self.disputed = 0


def replay_refunds(events: dict[str, pl.DataFrame]) -> list[str]:
    """Replay each payment's refunds and dispute (README "Refunds", kernels `payment_life`):

    - a refund request needs a captured payment and a fresh key (at most `IDEM_SLOTS`); it is
      rejected `dispute_open` while a dispute is open, else `nothing_left` when
      `left = captured - refunded - held <= 0` or after a lost dispute, else held for
      `0 < amount <= left`;
    - a held refund settles (commits: `refunded_after`) or fails (releases) once, for its held
      amount, whatever the dispute state;
    - a replayed key returns its first result (`requested` or `rejected`) and changes nothing;
    - a dispute opens once on a captured payment for `captured - refunded - held > 0` and
      resolves once for that amount.
    """
    out: list[str] = []
    pays: dict[int, _Pay] = {}
    for r in _rows(events, _PAYMENT, "payment_id"):
        ev = r["_ev"]
        p = pays.setdefault(r["payment_id"], _Pay())
        if ev == "payment_captured":
            if p.captured is not None or p.ended:
                out.append(_miss(r, "capture", "an authorized payment", "captured or ended"))
            p.captured = r["amount"]
            continue
        if ev in ("payment_expired", "payment_declined"):
            if p.captured is not None or p.ended:
                out.append(_miss(r, "status", "authorized", "captured or ended"))
            p.ended = True
            continue
        if p.captured is None:
            out.append(_miss(r, "status", "captured", "not captured"))
            continue
        left = p.captured - p.refunded - p.held
        rid = r.get("refund_id")
        if ev in ("refund_requested", "refund_rejected"):
            if rid in p.keys or len(p.keys) >= IDEM_SLOTS:
                out.append(_miss(r, "refund key", f"new, at most {IDEM_SLOTS}", rid))
            want = ("dispute_open" if p.dispute == "open" else
                    "nothing_left" if left <= 0 or p.dispute == "lost" else None)
            got = r["reason"] if ev == "refund_rejected" else None
            if want != got:
                out.append(_miss(r, f"decision (left {left}, dispute {p.dispute})",
                                 f"rejected {want}" if want else "requested",
                                 f"rejected {got}" if got else "requested"))
            if ev == "refund_requested":
                amt = r["amount"]
                if not 0 < amt <= left:
                    out.append(_miss(r, "refund amount", f"in (0, {left}]", amt))
                p.held += amt
                p.keys[rid] = ["requested", amt, True]
            else:
                p.keys[rid] = ["rejected", 0, False]
        elif ev in ("refund_settled", "refund_failed"):
            k = p.keys.get(rid)
            if k is None or not k[2]:
                out.append(_miss(r, "refund", "a held refund", rid))
                continue
            k[2] = False
            if r["amount"] != k[1]:
                out.append(_miss(r, "amount", k[1], r["amount"]))
            p.held -= k[1]
            if ev == "refund_settled":
                p.refunded += k[1]
                if r["refunded_after"] != p.refunded:
                    out.append(_miss(r, "refunded_after", p.refunded, r["refunded_after"]))
        elif ev == "refund_replayed":
            k = p.keys.get(rid)
            if k is None:
                out.append(_miss(r, "refund", "a known key", rid))
            elif r["result"] != k[0]:
                out.append(_miss(r, "result", k[0], r["result"]))
        elif ev == "dispute_opened":
            if p.dispute != "none":
                out.append(_miss(r, "dispute", "none open yet", p.dispute))
            if left <= 0 or r["amount"] != left:
                out.append(_miss(r, "dispute amount", f"{left} (> 0, else no dispute)",
                                 r["amount"]))
            p.dispute, p.disputed = "open", r["amount"]
        else:                                       # dispute_won, dispute_lost
            if p.dispute != "open":
                out.append(_miss(r, "dispute", "open", p.dispute))
            if r["amount"] != p.disputed:
                out.append(_miss(r, "amount", p.disputed, r["amount"]))
            p.dispute = "won" if ev == "dispute_won" else "lost"
    return out
