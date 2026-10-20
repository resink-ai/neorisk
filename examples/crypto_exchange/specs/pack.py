"""A spot crypto exchange: two order books, market makers and retail traders.

Each symbol's book is a shard. It owns the resting orders and every trader's isolated
sub-balances for that symbol, so matching never reads another partition. Traders deposit
into a book, then send orders by request (order-entry latency). The book matches by price,
then time; a taker that sweeps many makers just loops. GTC remainders rest, IOC remainders
are cancelled, and FOK orders run a read-only preflight and are either filled in full or
rejected before anything is written. Traders cancel some resting orders later.

Prices are integer ticks of $0.01; quantities are integer lots.
"""

from __future__ import annotations

import bisect
from collections import deque
from dataclasses import dataclass, field
from types import MappingProxyType

import numpy as np
import polars as pl

from neorisk_simkit.engine import DAY, MINUTE
from neorisk_simkit.spec import Latency, Pack, cat, i64

NAME = "crypto_exchange"
SYMBOLS = ("BTC-USD", "ETH-USD")
ASSETS = ("USD", "BTC", "ETH")
START_PRICE = MappingProxyType({"BTC-USD": 6_000_000, "ETH-USD": 300_000})  # ticks, per lot


@dataclass
class Config:
    makers: int = 6
    traders: int = 120
    maker_quotes_per_hour: float = 6.0
    trader_orders_per_day: float = 4.0
    spread_ticks: int = 400
    vol_per_day: float = 0.03
    ioc_p: float = 0.2
    fok_p: float = 0.1
    cancel_p: float = 0.3
    deposit_usd: int = 50_000_000                  # ticks: $500k
    deposit_lots: int = 40


@dataclass
class Trader:
    tid: int = 0
    maker: bool = False


@dataclass
class Book:
    symbol: str = ""
    bids: dict[int, deque] = field(default_factory=dict)   # price -> deque of order ids
    asks: dict[int, deque] = field(default_factory=dict)
    bid_px: list[int] = field(default_factory=list)          # sorted ascending
    ask_px: list[int] = field(default_factory=list)
    orders: dict[int, list] = field(default_factory=dict)    # id -> [side, price, left, tid, pid]
    usd: dict[int, int] = field(default_factory=dict)         # trader -> available quote
    lots: dict[int, int] = field(default_factory=dict)        # trader -> available base


def define(p: Pack) -> None:
    p.entity("traders", key="trader_id", cols={"segment": cat("market_maker", "retail")})
    side, kind = cat("buy", "sell"), cat("gtc", "ioc", "fok")
    sym = {"symbol": cat(*SYMBOLS)}
    p.event("funds_deposited", cols={**sym, "trader_id": i64(), "asset": cat(*ASSETS),
                                     "amount": i64(min=1)})
    p.event("order_accepted", cols={**sym, "order_id": i64(), "trader_id": i64(), "side": side,
                                    "type": kind, "price": i64(min=1), "qty": i64(min=1)})
    p.event("order_rejected", cols={**sym, "order_id": i64(), "trader_id": i64(), "side": side,
                                    "type": kind, "price": i64(min=1), "qty": i64(min=1),
                                    "reason": cat("insufficient_balance", "fok_unfillable")})
    p.event("trade", doc="One fill between a resting maker and an incoming taker", cols={
        **sym, "trade_id": i64(), "maker_order": i64(), "taker_order": i64(),
        "buyer_id": i64(), "seller_id": i64(), "price": i64(min=1), "qty": i64(min=1),
        "taker_side": side})
    p.event("order_filled", cols={**sym, "order_id": i64(), "trader_id": i64()})
    p.event("order_cancelled", cols={**sym, "order_id": i64(), "trader_id": i64(),
                                     "qty_left": i64(min=1), "reason": cat("user", "ioc")})

    trader = p.owner("trader", state=Trader, latency=Latency(0.01, 0.05))
    book = p.shard("book", state=Book, latency=Latency(0.002, 0.02),
                   doc="One symbol: resting orders and isolated sub-balances")
    life = trader.process("trading", start="join")

    # --- traders ------------------------------------------------------------------------
    @life.action
    def join(ctx, s, cmd):
        cfg = ctx.cfg
        for symbol in SYMBOLS:
            k = 10 if s.maker else 1                  # makers bring deeper pockets
            ctx.send(ctx.find("book", symbol), "deposit", trader=s.tid,
                     usd=cfg.deposit_usd * k, lots=cfg.deposit_lots * k)
        rate = cfg.maker_quotes_per_hour * 24 if s.maker else cfg.trader_orders_per_day
        ctx.after(MINUTE + ctx.rng.exponential(DAY / rate), "decide")

    @life.action
    def decide(ctx, s, cmd):
        cfg, rng, fair = ctx.cfg, ctx.rng, ctx.shared.fair
        symbol = SYMBOLS[rng.integers(len(SYMBOLS))]
        mid = int(fair.price[SYMBOLS.index(symbol)][min(int(ctx.now // 3600),
                                                         fair.price.shape[1] - 1)])
        target = ctx.find("book", symbol)
        if s.maker:                                   # quote both sides around fair
            half = cfg.spread_ticks // 2 + int(rng.integers(0, cfg.spread_ticks))
            q = 1 + int(rng.integers(0, 4))
            for sd, px in (("buy", mid - half), ("sell", mid + half)):
                ctx.request(target, "submit", reply="answered", side=sd, kind="gtc", price=px,
                            qty=q, trader=s.tid)
            rate = cfg.maker_quotes_per_hour * 24
        else:                                         # retail: often marketable
            sd = "buy" if rng.random() < 0.5 else "sell"
            u = rng.random()
            kind = "fok" if u < cfg.fok_p else "ioc" if u < cfg.fok_p + cfg.ioc_p else "gtc"
            edge = int(rng.normal(0, cfg.spread_ticks))
            px = max(1, mid + edge if sd == "buy" else mid - edge)
            ctx.request(target, "submit", reply="answered", side=sd, kind=kind, price=px,
                        qty=1 + int(rng.integers(0, 3)), trader=s.tid)
            rate = cfg.trader_orders_per_day
        ctx.after(rng.exponential(DAY / rate), "decide")

    @life.action
    def answered(ctx, s, cmd):
        if cmd.ok and cmd.payload.get("resting") and ctx.rng.random() < ctx.cfg.cancel_p:
            ctx.after(ctx.rng.exponential(2 * 3600), "cancel", order=cmd.order,
                      book=cmd.sender)

    @life.action
    def cancel(ctx, s, cmd):
        ctx.request(cmd.book, "cancel_order", reply="cancel_answered", order=cmd.order,
                    trader=s.tid)

    @life.action
    def cancel_answered(ctx, s, cmd):
        return ctx.commit()                       # filled before the cancel arrived: fine

    # --- the book -----------------------------------------------------------------------
    def levels(s, sd):
        return (s.bids, s.bid_px) if sd == "buy" else (s.asks, s.ask_px)

    def crosses(sd, px, level_px):
        return level_px <= px if sd == "buy" else level_px >= px

    def opposite(s, sd):
        """Opposite price levels, best first."""
        book, prices = levels(s, "sell" if sd == "buy" else "buy")
        return book, (prices if sd == "buy" else prices[::-1])

    @book.action
    def deposit(ctx, s, cmd):
        base = s.symbol.split("-")[0]
        s.usd[cmd.trader] = s.usd.get(cmd.trader, 0) + cmd.usd
        s.lots[cmd.trader] = s.lots.get(cmd.trader, 0) + cmd.lots
        ctx.emit("funds_deposited", symbol=s.symbol, trader_id=cmd.trader, asset="USD",
                 amount=cmd.usd)
        ctx.emit("funds_deposited", symbol=s.symbol, trader_id=cmd.trader, asset=base,
                 amount=cmd.lots)

    @book.action
    def submit(ctx, s, cmd):
        sd, px, qty, tid = cmd.side, cmd.price, cmd.qty, cmd.trader
        oid = ctx.new_id("order")
        row = {"symbol": s.symbol, "order_id": oid, "trader_id": tid, "side": sd,
               "type": cmd.kind, "price": px, "qty": qty}
        # 1. validate (read-only): funds, then the FOK preflight
        need_usd = px * qty if sd == "buy" else 0
        need_lots = qty if sd == "sell" else 0
        if s.usd.get(tid, 0) < need_usd or s.lots.get(tid, 0) < need_lots:
            ctx.emit("order_rejected", **row, reason="insufficient_balance")
            return ctx.decline("insufficient_balance")
        book_, prices = opposite(s, sd)
        if cmd.kind == "fok":
            avail = 0
            for lp in prices:
                if not crosses(sd, px, lp) or avail >= qty:
                    break
                avail += sum(s.orders[o][2] for o in book_[lp] if s.orders[o][3] != tid)
            if avail < qty:
                ctx.emit("order_rejected", **row, reason="fok_unfillable")
                return ctx.decline("fok_unfillable")
        # 2. commit: lock funds, match (a plain loop over makers), rest or cancel the rest
        s.usd[tid] = s.usd.get(tid, 0) - need_usd
        s.lots[tid] = s.lots.get(tid, 0) - need_lots
        ctx.emit("order_accepted", **row)
        left = qty
        for lp in list(prices):
            if left == 0 or not crosses(sd, px, lp):
                break
            q = book_[lp]
            for mid in list(q):
                if left == 0:
                    break
                _, _, mleft, mtid, _ = s.orders[mid]
                if mtid == tid:
                    continue                          # no self-trade: skip own orders
                fill = min(left, mleft)
                buyer, seller = (tid, mtid) if sd == "buy" else (mtid, tid)
                ctx.emit("trade", symbol=s.symbol, trade_id=ctx.new_id("trade"),
                         maker_order=mid, taker_order=oid, buyer_id=buyer, seller_id=seller,
                         price=lp, qty=fill, taker_side=sd)
                # settle: buyer gets lots and its price improvement back; seller gets usd
                s.lots[buyer] = s.lots.get(buyer, 0) + fill
                s.usd[seller] = s.usd.get(seller, 0) + lp * fill
                if sd == "buy":
                    s.usd[tid] += (px - lp) * fill        # taker locked at its own limit
                left -= fill
                s.orders[mid][2] -= fill
                if s.orders[mid][2] == 0:
                    q.remove(mid)
                    del s.orders[mid]
                    ctx.emit("order_filled", symbol=s.symbol, order_id=mid, trader_id=mtid)
            if not q:
                del book_[lp]
                (s.ask_px if sd == "buy" else s.bid_px).remove(lp)
        if left == 0:
            ctx.emit("order_filled", symbol=s.symbol, order_id=oid, trader_id=tid)
            return ctx.reply(order=oid, resting=False)
        if cmd.kind == "gtc":
            mine, my_px = levels(s, sd)
            if px not in mine:
                mine[px] = deque()
                bisect.insort(my_px, px)
            mine[px].append(oid)
            s.orders[oid] = [sd, px, left, tid, cmd.sender]
            return ctx.reply(order=oid, resting=True)
        _unlock(s, sd, px, left, tid)                 # IOC (FOK never gets here)
        ctx.emit("order_cancelled", symbol=s.symbol, order_id=oid, trader_id=tid,
                 qty_left=left, reason="ioc")
        return ctx.reply(order=oid, resting=False)

    def _unlock(s, sd, px, left, tid):
        if sd == "buy":
            s.usd[tid] += px * left
        else:
            s.lots[tid] += left

    @book.action
    def cancel_order(ctx, s, cmd):
        o = s.orders.get(cmd.order)
        if o is None or o[3] != cmd.trader:
            return ctx.reject("not_resting")
        sd, px, left, tid, _ = o
        mine, my_px = levels(s, sd)
        mine[px] = deque(x for x in mine[px] if x != cmd.order)
        if not mine[px]:
            del mine[px]
            my_px.remove(px)
        del s.orders[cmd.order]
        _unlock(s, sd, px, left, tid)
        ctx.emit("order_cancelled", symbol=s.symbol, order_id=cmd.order, trader_id=tid,
                 qty_left=left, reason="user")
        return ctx.reply()

    # --- laws ---------------------------------------------------------------------------
    p.check("order_lifecycle", _order_lifecycle)
    p.check("balances_never_negative", _balances, group="law")
    p.check("conservation", _conservation, group="law")
    p.check("fok_all_or_nothing", _fok, group="law")

    @p.source
    def market(src):
        cfg, rng = src.cfg, src.rng
        hours = int(src.days * 24) + 2
        steps = rng.normal(0, cfg.vol_per_day / np.sqrt(24), (len(SYMBOLS), hours))
        start = np.array([[START_PRICE[s]] for s in SYMBOLS], dtype=float)
        src.share("fair", price=(start * np.exp(np.cumsum(steps, axis=1))).astype(np.int64))
        for s in SYMBOLS:
            src.create("book", key=s, symbol=s)
        for i in range(cfg.makers + cfg.traders):
            maker = i < cfg.makers
            t = 0.0 if maker else float(rng.uniform(0, 0.3 * src.days)) * DAY
            tid = src.insert("traders", at=t, segment="market_maker" if maker else "retail")
            src.create("trader", at=t, tid=tid, maker=maker)


CITE = ("partition_id", "seq", "action_id")


def _order_lifecycle(d):
    """Per order: accepted, then trades, then at most one of filled / cancelled; filled
    orders traded exactly their quantity."""
    acc = d.ev("order_accepted").select("symbol", "order_id", "qty", *CITE)
    tr = pl.concat([d.ev("trade").select("symbol", pl.col("maker_order").alias("order_id"),
                                         "qty"),
                    d.ev("trade").select("symbol", pl.col("taker_order").alias("order_id"),
                                         "qty")]).group_by("symbol", "order_id").agg(
        pl.col("qty").sum().alias("traded"))
    ends = pl.concat([d.ev("order_filled").select("symbol", "order_id"),
                      d.ev("order_cancelled").select("symbol", "order_id")]).group_by(
        "symbol", "order_id").len()
    filled = d.ev("order_filled").select("symbol", "order_id", pl.lit(True).alias("f"))
    j = (acc.join(tr, on=["symbol", "order_id"], how="left")
         .join(ends, on=["symbol", "order_id"], how="left")
         .join(filled, on=["symbol", "order_id"], how="left")
         .with_columns(pl.col("traded").fill_null(0)))
    bad = j.filter((pl.col("len") > 1) | (pl.col("traded") > pl.col("qty"))
                   | (pl.col("f").fill_null(False) & (pl.col("traded") != pl.col("qty"))))
    return acc.height, bad.select(*CITE, pl.lit("order lifecycle broken").alias("detail"))


def _balances(d):
    """Per trader and asset (in one book), deposits plus trade receipts minus trade payments
    never go negative (locked funds included)."""
    dep = d.ev("funds_deposited").select("seq", "symbol", "trader_id", "asset",
                                         pl.col("amount").alias("v"))
    t = d.ev("trade").with_columns(base=pl.col("symbol").cast(pl.String).str.split("-").list
                                   .first())
    legs = pl.concat([
        t.select("seq", "symbol", pl.col("buyer_id").alias("trader_id"),
                 pl.col("base").alias("asset"), pl.col("qty").alias("v")),
        t.select("seq", "symbol", pl.col("seller_id").alias("trader_id"),
                 pl.col("base").alias("asset"), (-pl.col("qty")).alias("v")),
        t.select("seq", "symbol", pl.col("buyer_id").alias("trader_id"),
                 pl.lit("USD").alias("asset"), (-pl.col("price") * pl.col("qty")).alias("v")),
        t.select("seq", "symbol", pl.col("seller_id").alias("trader_id"),
                 pl.lit("USD").alias("asset"), (pl.col("price") * pl.col("qty")).alias("v"))])
    u = pl.concat([dep.with_columns(pl.col("asset").cast(pl.String)), legs]).sort("seq")
    u = u.with_columns(run=pl.col("v").cum_sum().over("symbol", "trader_id", "asset"))
    bad = u.filter(pl.col("run") < 0)
    return u.height, bad.select("seq", pl.format("trader {} {} balance {}", "trader_id",
                                                 "asset", "run").alias("detail"))


def _conservation(d):
    """Every trade moves exactly qty lots and price*qty ticks between two different traders."""
    t = d.ev("trade")
    bad = t.filter(pl.col("buyer_id") == pl.col("seller_id"))
    return t.height, bad.select(*CITE, pl.lit("self trade").alias("detail"))


def _fok(d):
    """A FOK order is filled in full by its own matching step, or rejected; never partial."""
    acc = d.ev("order_accepted").filter(pl.col("type") == "fok").select("symbol", "order_id",
                                                                        "qty", *CITE)
    tr = d.ev("trade").group_by("symbol", pl.col("taker_order").alias("order_id")).agg(
        pl.col("qty").sum().alias("traded"))
    j = acc.join(tr, on=["symbol", "order_id"], how="left")
    bad = j.filter(pl.col("traded").fill_null(0) != pl.col("qty"))
    return acc.height, bad.select(*CITE, pl.lit("partial FOK").alias("detail"))
