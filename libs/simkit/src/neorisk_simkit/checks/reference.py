"""Reference implementations: plain-Python replays that re-derive what a std recipe must have
done, independently of the recipe and of the Polars laws. Tests run them against real packs
on forced-path fixtures.
"""

from __future__ import annotations

import polars as pl

from neorisk_simkit.checks import Data


def holds_ledger(d: Data) -> list[str]:
    """Replay hold rows in seq order: each hold is placed once, then resolved at most once,
    by the same partition, for the same amount and purpose, never before it was placed."""
    rows = pl.concat([d.ev(e).select("seq", "event_type", "partition_id", "hold_id", "amount",
                                     "purpose")
                      for e in ("hold_placed", "hold_committed", "hold_released")]).sort("seq")
    open_: dict[int, tuple[int, int, str]] = {}
    seen: set[int] = set()
    errs = []
    for seq, kind, part, hid, amt, purpose in rows.iter_rows():
        if kind == "hold_placed":
            if hid in seen:
                errs.append(f"seq {seq}: hold {hid} placed twice")
            seen.add(hid)
            open_[hid] = (part, amt, purpose)
            continue
        if hid not in open_:
            errs.append(f"seq {seq}: {kind} of hold {hid}, which is not open")
            continue
        p0, a0, u0 = open_.pop(hid)
        if (p0, a0, u0) != (part, amt, purpose):
            errs.append(f"seq {seq}: {kind} of hold {hid} as {(part, amt, purpose)}, "
                        f"placed as {(p0, a0, u0)}")
    return errs


def order_book(d: Data, symbol: str) -> list[str]:
    """Replay one symbol's accepted orders, user cancels and FOK rejections through a plain
    price-time matcher (no self-trades) and compare every trade with the emitted ones."""
    from collections import deque

    def rows(ev, *cols):
        df = d.ev(ev).filter(pl.col("symbol") == symbol)
        if ev == "order_rejected":
            df = df.filter(pl.col("reason") == "fok_unfillable")
        return df.select("seq", pl.lit(ev).alias("_e"), *cols).with_columns(
            pl.col(pl.Enum).cast(pl.String))
    u = pl.concat([
        rows("order_accepted", "order_id", "trader_id", "side", "type", "price", "qty"),
        rows("order_cancelled", "order_id", "trader_id", pl.lit(None, pl.String).alias("side"),
             pl.col("reason").cast(pl.String).alias("type"),
             pl.lit(None, pl.Int64).alias("price"),
             pl.col("qty_left").alias("qty")),
        rows("order_rejected", "order_id", "trader_id", "side", "type", "price", "qty")
        .filter(pl.col("type") == "fok"),
    ], how="vertical_relaxed").sort("seq")
    book = {"buy": {}, "sell": {}}           # side -> price -> deque[[order, trader, left]]
    got: list[tuple] = []
    errs: list[str] = []

    def best(side: str, limit: int) -> list[int]:
        prices = sorted(book[side], reverse=(side == "buy"))
        return [p for p in prices if (p <= limit if side == "sell" else p >= limit)]

    for seq, ev, oid, tid, side, typ, px, qty in u.iter_rows():
        if ev == "order_cancelled":
            if typ == "user":
                for sd in ("buy", "sell"):
                    for p in list(book[sd]):
                        lv = book[sd][p]
                        for o in list(lv):
                            if o[0] == oid:
                                lv.remove(o)
                        if not lv:
                            del book[sd][p]
            continue
        other = "sell" if side == "buy" else "buy"
        if ev == "order_rejected":
            avail = sum(o[2] for p in best(other, px) for o in book[other][p] if o[1] != tid)
            if avail >= qty:
                errs.append(f"seq {seq}: FOK {oid} rejected but {avail} >= {qty} was fillable")
            continue
        left = qty
        for p in best(other, px):
            for o in list(book[other][p]):
                if left == 0:
                    break
                if o[1] == tid:
                    continue
                f = min(left, o[2])
                got.append((o[0], oid, p, f))
                o[2] -= f
                left -= f
                if o[2] == 0:
                    book[other][p].remove(o)
            if not book[other][p]:
                del book[other][p]
        if left and typ == "gtc":
            book[side].setdefault(px, deque()).append([oid, tid, left])
    emitted = [tuple(r) for r in d.ev("trade").filter(pl.col("symbol") == symbol).sort("seq")
               .select("maker_order", "taker_order", "price", "qty").iter_rows()]
    if emitted != got:
        k = next((i for i, (a, b) in enumerate(zip(emitted, got, strict=False)) if a != b),
                 min(len(emitted), len(got)))
        errs.append(f"trades differ from the reference at #{k}: "
                    f"{emitted[k:k + 1]} vs {got[k:k + 1]} ({len(emitted)} vs {len(got)})")
    return errs


def l1_envelope(d: Data, gas_price: int) -> list[str]:
    """Replay the chain from its rows with a plain envelope: at each block, process the queued
    transactions in arrival order; drop on a bad nonce or funds below max fee + value;
    otherwise bump the nonce, charge used gas (transfers 21k, calls 3/4 of the limit), and
    move the value only if the transaction succeeded (reverts are hidden draws, so the
    reference takes success/revert from the row and checks everything else)."""
    rows = pl.concat([
        d.ev("genesis_allocated").select("seq", pl.lit("g").alias("e"),
                                         pl.col("account_id").alias("tx"),
                                         pl.col("amount").alias("a"), pl.lit(None).alias("b")),
        d.ev("tx_received").select("seq", pl.lit("r").alias("e"), pl.col("tx_id").alias("tx"),
                                   pl.lit(None).alias("a"), pl.lit(None).alias("b")),
        d.ev("tx_included").select("seq", pl.lit("o").alias("e"), pl.col("tx_id").alias("tx"),
                                   pl.lit(None).alias("a"), pl.col("block").alias("b")),
        d.ev("tx_dropped").select("seq", pl.lit("o").alias("e"), pl.col("tx_id").alias("tx"),
                                  pl.lit(None).alias("a"), pl.col("block").alias("b")),
    ], how="vertical_relaxed").sort("seq")
    rec = {r["tx_id"]: r for r in d.ev("tx_received").iter_rows(named=True)}
    inc = {r["tx_id"]: r for r in d.ev("tx_included").iter_rows(named=True)}
    drop = {r["tx_id"]: r for r in d.ev("tx_dropped").iter_rows(named=True)}
    bal: dict[int, int] = {}
    nonce: dict[int, int] = {}
    queue: list[int] = []
    block = None
    errs: list[str] = []
    for _, e, tx, a, b in rows.iter_rows():
        if e == "g":
            bal[tx] = a
        elif e == "r":
            queue.append(tx)
        elif b != block:                              # a new block: process the whole queue
            block = b
            for t in queue:
                r = rec[t]
                src = r["from_account"]
                n, have = nonce.get(src, 0), bal.get(src, 0)
                why = ("bad_nonce" if r["nonce"] != n else
                       "insufficient_funds" if have < r["gas_limit"] * gas_price + r["value"]
                       else None)
                if why:
                    if t not in drop or drop[t]["reason"] != why or drop[t]["block"] != b:
                        errs.append(f"tx {t}: reference drops ({why}) in block {b}")
                    continue
                if t not in inc or inc[t]["block"] != b:
                    errs.append(f"tx {t}: reference includes it in block {b}")
                    continue
                used = r["gas_limit"] if r["kind"] == "transfer" else r["gas_limit"] * 3 // 4
                if inc[t]["gas_used"] != used or inc[t]["fee"] != used * gas_price:
                    errs.append(f"tx {t}: gas/fee differ from the reference")
                nonce[src] = n + 1
                bal[src] = have - used * gas_price
                if inc[t]["status"] == "success" and r["value"]:
                    bal[src] -= r["value"]
                    bal[r["to_account"]] = bal.get(r["to_account"], 0) + r["value"]
            queue = []
    return errs[:20]
