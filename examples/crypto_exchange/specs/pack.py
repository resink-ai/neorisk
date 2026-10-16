"""Centralized crypto exchange (spot) pack.

Partitions
    owner  trader   one account: KYC, per-asset balances (available, held), orders mirror,
                    deposits, withdrawals and its processes
    shard  book     one symbol's order book: resting orders, their locks, the active taker

Boundaries (immutable request/response or notification, latency >= delta)
    trader -> book    place / cancel an order                       delta 2 ms (order entry)
    book -> trader    fill / done notifications (user data stream)  delta 1 ms, FIFO per pair
    no owner-to-owner messages in the base pack

Hold/fill flow: the trader holds the order's lock on its own balance (quote for buys, base for
sells) and sends the lock amount inside the immutable `place` payload. The book matches against
that lock only, never against the trader's balance. Each fill is reported to both traders; the
trader settles on receipt (held -> spent, credit the received asset minus fee). When an order
closes, one `done` notification returns whatever lock is left.
"""

from dataclasses import dataclass, field

from neorisk_simkit.spec import Pack, dist, law, std
from neorisk_simkit.spec.types import (amount, boolean, cat, f64, i16, i32, i64, opt, ref, text,
                                       ts)

from . import kernels as k

PACK = "crypto_exchange"
SCHEMA_VERSION = 1

TIERS = ("major", "large", "mid", "small")
SEGMENTS = ("retail", "pro", "market_maker")
CHANNELS = ("web", "app", "api")
COUNTRIES = ("BR", "DE", "FR", "GB", "ID", "IN", "JP", "KR", "NG", "PH", "TR", "US", "VN",
             "other")

# Ledger quantum per asset (decimals). Amounts are int64 at this quantum, checked arithmetic.
# The ledger quantum is the exchange's, not the chain's: ETH is kept at 1e-8, not in wei, and
# on-chain amounts are rounded down to it at deposit.
#        code      dec  chain        confirmations  block_s  withdraw_fee (whole units)
ASSETS = (
    ("USDT",   6, "tron",       20,   3,    1.0),
    ("BTC",    8, "bitcoin",     2, 600,    0.0001),
    ("ETH",    8, "ethereum",   12,  12,    0.0008),
    ("SOL",    8, "solana",      1,   1,    0.002),
    ("XRP",    6, "xrpl",        1,   4,    0.2),
    ("BNB",    8, "bsc",        15,   3,    0.0005),
    ("DOGE",   8, "dogecoin",   40,  60,    4.0),
    ("ADA",    6, "cardano",    15,  20,    1.0),
    ("TRX",    6, "tron",       20,   3,    1.0),
    ("AVAX",   8, "avalanche",   1,   2,    0.01),
    ("LINK",   8, "ethereum",   12,  12,    0.3),
    ("TON",    8, "ton",         1,   5,    0.05),
    ("DOT",    8, "polkadot",    1,   6,    0.1),
    ("LTC",    8, "litecoin",    6, 150,    0.001),
    ("BCH",    8, "bitcoincash", 6, 600,    0.0005),
    ("NEAR",   8, "near",        1,   1,    0.05),
    ("UNI",    8, "ethereum",   12,  12,    0.6),
    ("ATOM",   6, "cosmos",      1,   6,    0.02),
    ("XLM",    7, "stellar",     1,   5,    0.5),
    ("APT",    8, "aptos",       1,   1,    0.01),
    ("ARB",    8, "arbitrum",   12,   1,    0.5),
    ("OP",     8, "optimism",   12,   2,    0.3),
    ("FIL",    8, "filecoin",   10,  30,    0.05),
    ("ETC",    8, "etc",        40,  13,    0.05),
    ("INJ",    8, "injective",   1,   1,    0.03),
    ("SUI",    8, "sui",         1,   1,    0.1),
    # fictional low-cap tokens (exchange-listed, thin books); used by the abuse overlays
    ("AURX",   8, "ethereum",   12,  12,   20.0),
    ("BRYX",   8, "bsc",        15,   3,   50.0),
    ("CINDR",  8, "ethereum",   12,  12,   80.0),
    ("DUSKY",  8, "solana",      1,   1,   40.0),
    ("EMBR",   8, "bsc",        15,   3,  100.0),
    ("FYNE",   8, "ethereum",   12,  12,   30.0),
    ("GLYPH",  8, "solana",      1,   1,   60.0),
    ("HALOQ",  8, "bsc",        15,   3,   25.0),
    ("IRIDX",  8, "ethereum",   12,  12,   15.0),
)
DECIMALS = {a[0]: a[1] for a in ASSETS}

# Price is an int64 in 10^-price_dec quote units per one whole base unit; qty is in the base
# asset's ledger quantum and must be a multiple of the lot (10^(base_dec - lot_dec)).
#          symbol        base    quote   tier     price_dec lot_dec init_price
SYMBOLS = (
    ("BTC-USDT",   "BTC",  "USDT", "major", 2, 5, 65_000.0),
    ("ETH-USDT",   "ETH",  "USDT", "major", 2, 4,  3_200.0),
    ("SOL-USDT",   "SOL",  "USDT", "large", 2, 3,    150.0),
    ("XRP-USDT",   "XRP",  "USDT", "large", 4, 0,      0.55),
    ("BNB-USDT",   "BNB",  "USDT", "large", 1, 3,    580.0),
    ("DOGE-USDT",  "DOGE", "USDT", "large", 5, 0,      0.14),
    ("ADA-USDT",   "ADA",  "USDT", "large", 4, 1,      0.45),
    ("TRX-USDT",   "TRX",  "USDT", "large", 5, 1,      0.13),
    ("AVAX-USDT",  "AVAX", "USDT", "large", 2, 2,     30.0),
    ("LINK-USDT",  "LINK", "USDT", "large", 3, 2,     15.0),
    ("TON-USDT",   "TON",  "USDT", "large", 3, 2,      6.0),
    ("DOT-USDT",   "DOT",  "USDT", "mid",   3, 2,      6.5),
    ("LTC-USDT",   "LTC",  "USDT", "mid",   2, 3,     80.0),
    ("BCH-USDT",   "BCH",  "USDT", "mid",   1, 3,    400.0),
    ("NEAR-USDT",  "NEAR", "USDT", "mid",   3, 1,      5.5),
    ("UNI-USDT",   "UNI",  "USDT", "mid",   3, 2,      8.0),
    ("ATOM-USDT",  "ATOM", "USDT", "mid",   3, 2,      7.0),
    ("XLM-USDT",   "XLM",  "USDT", "mid",   5, 0,      0.11),
    ("APT-USDT",   "APT",  "USDT", "mid",   3, 2,      8.0),
    ("ARB-USDT",   "ARB",  "USDT", "mid",   4, 1,      0.9),
    ("OP-USDT",    "OP",   "USDT", "mid",   4, 1,      1.8),
    ("FIL-USDT",   "FIL",  "USDT", "mid",   3, 2,      5.0),
    ("ETC-USDT",   "ETC",  "USDT", "mid",   2, 2,     25.0),
    ("INJ-USDT",   "INJ",  "USDT", "mid",   2, 2,     22.0),
    ("SUI-USDT",   "SUI",  "USDT", "mid",   4, 1,      1.2),
    ("ETH-BTC",    "ETH",  "BTC",  "large", 5, 4,      0.049),
    ("SOL-BTC",    "SOL",  "BTC",  "mid",   7, 2,      0.0023),
    ("XRP-BTC",    "XRP",  "BTC",  "mid",   8, 0,      0.0000085),
    ("BNB-BTC",    "BNB",  "BTC",  "mid",   6, 3,      0.0089),
    ("LTC-BTC",    "LTC",  "BTC",  "mid",   6, 2,      0.00123),
    ("LINK-BTC",   "LINK", "BTC",  "mid",   7, 1,      0.00023),
    ("AURX-USDT",  "AURX", "USDT", "small", 5, 0,      0.42),
    ("BRYX-USDT",  "BRYX", "USDT", "small", 6, 0,      0.031),
    ("CINDR-USDT", "CINDR", "USDT", "small", 6, 0,     0.0185),
    ("DUSKY-USDT", "DUSKY", "USDT", "small", 5, 0,     0.27),
    ("EMBR-USDT",  "EMBR", "USDT", "small", 6, 0,      0.0094),
    ("FYNE-USDT",  "FYNE", "USDT", "small", 5, 0,      0.66),
    ("GLYPH-USDT", "GLYPH", "USDT", "small", 6, 0,     0.052),
    ("HALOQ-USDT", "HALOQ", "USDT", "small", 5, 0,     0.13),
    ("IRIDX-USDT", "IRIDX", "USDT", "small", 5, 0,     0.88),
)


def _symbol_rows(n: int) -> list[dict]:
    """Static symbol rows; notional_div turns price × qty into the quote's ledger quantum."""
    rows = []
    for code, base, quote, tier, pdec, ldec, px in SYMBOLS[:n]:
        rows.append({
            "code": code, "base": base, "quote": quote, "tier": tier, "price_dec": pdec,
            "lot": 10 ** (DECIMALS[base] - ldec),
            "notional_div": 10 ** (pdec + DECIMALS[base] - DECIMALS[quote]),   # always >= 1
            "min_notional": 5 * 10 ** DECIMALS["USDT"] if quote == "USDT" else 10_000,
            "init_price": round(px * 10 ** pdec),
        })
    return rows


# --------------------------------------------------------------------------- config
@dataclass(frozen=True)
class Retail:
    """Retail and pro trading behavior; consumed by kernels.trader_activity."""
    session_gap_alpha: float = 1.15         # Pareto tail of gaps between sessions
    session_gap_min_h: float = 5.0
    pro_activity: float = 10.0              # pro sessions come this many times more often
    decisions_mean: float = 3.0             # order decisions per session (geometric)
    decide_gap: dist.Dist = dist.lognormal(median_s=45, sigma=1.1)
    trade_p: float = 0.4                    # a decision ends in an order (else just looks)
    attention_gain: float = 35.0            # symbol weight × (1 + gain × |1h return|)
    momentum: float = 4.0                   # buy tilt per unit of 1h return (trend following)
    market_p: float = 0.58                  # market vs limit, retail
    pro_market_p: float = 0.30
    ioc_p: float = 0.06                     # among limit orders
    fok_p: float = 0.01
    limit_offset_bps: dist.Dist = dist.lognormal(median=30, sigma=1.0)   # passive distance
    patience: dist.Dist = dist.lognormal(median_s=6 * 3600, sigma=1.6)   # cancel open GTC after
    buy_share: dist.Dist = dist.beta(a=2.0, b=4.0)    # share of available quote spent
    sell_share: dist.Dist = dist.beta(a=2.0, b=2.5)   # share of available base sold
    fee_maker_ppm: int = 1_000              # 0.10%
    fee_taker_ppm: int = 1_000
    pro_fee_maker_ppm: int = 600
    pro_fee_taker_ppm: int = 800


@dataclass(frozen=True)
class MarketMaking:
    """Quoting accounts; consumed by kernels.market_maker. Only used when fidelity == matched."""
    accounts: int = 60
    symbols_per_mm: dist.Dist = dist.uniform_int(4, 14)
    requote_every: dist.Dist = dist.lognormal(median_s=12, sigma=0.5)   # per symbol
    levels: int = 3                          # quote levels per side
    half_spread_bps: tuple = (0.7, 3.0, 8.0, 30.0)      # by tier: major, large, mid, small
    level_step_bps: tuple = (0.5, 2.0, 5.0, 30.0)
    level_notional_usdt: tuple = (40_000, 8_000, 2_500, 400)   # whole USDT per level
    requote_threshold: float = 0.5           # requote when ref moved > this × half spread
    inventory_skew_bps: float = 6.0          # quote shift at 100% inventory deviation, × tier
    inventory_usdt: tuple = (2_000_000, 400_000, 120_000, 20_000)  # starting inventory per symbol
    fee_maker_ppm: int = 0
    fee_taker_ppm: int = 400


@dataclass(frozen=True)
class Funding:
    """Deposits, withdrawals and KYC; consumed by kernels.funding and the machines."""
    first_deposit_p: float = 0.72            # registered traders who ever deposit
    first_deposit_delay: dist.Dist = dist.lognormal(median_s=2_400, sigma=1.5)
    topup_gap: dist.Dist = dist.pareto(alpha=1.3, min_days=4)
    deposit_usdt: dist.Dist = dist.lognormal_minor(median=350, sigma=1.5, min=10,
                                                   max=2_000_000)   # whole USDT equivalent
    deposit_asset: dist.Dist = dist.categorical({"USDT": .58, "BTC": .18, "ETH": .12,
                                                 "SOL": .05, "other": .07})
    withdraw_gap: dist.Dist = dist.exp(mean_days=24)
    withdraw_share: dist.Dist = dist.beta(a=2.0, b=1.5)
    withdraw_limit_usdt: tuple = (0, 50_000, 2_000_000)      # per request, by KYC level 0/1/2
    kyc1_p: float = 0.88
    kyc1_delay: dist.Dist = dist.gamma(mean_days=0.15, shape=1.2)
    kyc2_p: float = 0.22
    kyc2_delay: dist.Dist = dist.gamma(mean_days=6, shape=1.5)
    auto_review_p: float = 0.82              # approved by rules within a minute
    manual_review: dist.Dist = dist.gamma(mean_days=0.2, shape=2.0)
    withdraw_reject_p: float = 0.02
    broadcast_delay: dist.Dist = dist.lognormal(median_s=240, sigma=0.8)
    api_key_p: dict = field(default_factory=lambda: {"retail": 0.03, "pro": 0.7,
                                                     "market_maker": 1.0})


@dataclass(frozen=True)
class Matching:
    """Book shard rules; consumed by kernels.match and kernels.ticker."""
    fidelity: str = "matched"                # matched | external_liquidity
    fills_per_substep: int = 64              # fixed fan-out sub-step (design 05)
    max_resting: int = 250_000               # per book; a GTC that would exceed it is rejected
    stp_mode: str = "cancel_maker"           # cancel_maker | cancel_taker | cancel_both | off
    price_band: float = 0.10                 # limit price within ±10% of the reference price
    market_collar: float = 0.05              # market orders stop at ±5% from the reference
    entry_latency: dist.Dist = dist.shifted_lognormal(min_ms=2, median_ms=5)
    report_latency: dist.Dist = dist.shifted_lognormal(min_ms=1, median_ms=3)
    ticker_every: str = "1m"
    external_half_spread_bps: tuple = (1.0, 4.0, 10.0, 60.0)   # external_liquidity only
    external_depth_usdt: tuple = (5_000_000, 600_000, 150_000, 15_000)


@dataclass(frozen=True)
class Prices:
    """Exogenous reference price per symbol (jump diffusion), shared read-only input."""
    vol_annual: tuple = (0.55, 0.75, 0.90, 1.60)     # by tier
    jump_rate_daily: tuple = (0.3, 0.5, 0.6, 1.2)
    jump_size: dist.Dist = dist.laplace(scale=0.015)
    market_factor: float = 0.65              # loading on one common market factor
    tick: str = "1s"


@dataclass(frozen=True)
class Config:
    traders: int = 1_000_000                 # population at the end of the span (excl. MMs)
    initial_share: float = 0.7               # share that exists at the start
    pro_share: float = 0.025
    symbols: int = 40                        # book shards: the first N of SYMBOLS
    device_share: float = 0.05               # devices reused across accounts (households)
    ip_share: float = 0.18                   # IPs shared (carrier NAT, offices)
    address_share: float = 0.01              # withdrawal addresses shared (same person/OTC)
    retail: Retail = field(default_factory=Retail)
    mm: MarketMaking = field(default_factory=MarketMaking)
    funding: Funding = field(default_factory=Funding)
    matching: Matching = field(default_factory=Matching)
    prices: Prices = field(default_factory=Prices)
    execution_owner: str = "trader_id"       # overlays group cohort members under another owner


# --------------------------------------------------------------------------- pack
def define(p: Pack, cfg: Config) -> None:
    rt, mm, f, m, px = cfg.retail, cfg.mm, cfg.funding, cfg.matching, cfg.prices

    # ---------------------------------------------------------------- read inputs
    asset = p.table("asset", key="asset_id", mutable=False, doc="Listed assets, fixed", cols={
        "code": text(),
        "decimals": i16(),                   # ledger quantum = 10^-decimals
        "chain": text(),
        "confirmations": i16(),              # required before a deposit is credited
        "block_s": i32(),
        "withdraw_fee": amount(asset_from="asset_id"),
    }, source=std.rows([{"code": c, "decimals": d, "chain": ch, "confirmations": n,
                         "block_s": b, "withdraw_fee": round(fee * 10 ** d)}
                        for c, d, ch, n, b, fee in ASSETS]))

    symbol = p.table("symbol", key="symbol_id", mutable=False, doc="Spot pairs, fixed", cols={
        "code": text(),
        "base": ref("asset"),
        "quote": ref("asset"),
        "tier": cat(*TIERS),
        "price_dec": i16(),
        "lot": i64(min=1),                   # qty step in base quantum
        "notional_div": i64(min=1),          # quote = price × qty / notional_div (128-bit mid)
        "min_notional": amount(asset_from="quote"),
        "init_price": i64(min=1),
        "popularity": f64(),                 # attention weight; Zipf by listing order
    }, source=std.rows(_symbol_rows(cfg.symbols),
                       popularity=dist.zipf(s=1.15), resolve={"base": asset, "quote": asset}))

    device = p.table("device", key="device_id", mutable=False, doc="Trader devices", cols={
        "os": cat("ios", "android", "windows", "macos", "linux"),
        "kind": cat("phone", "tablet", "desktop"),
        "first_seen": ts(),
    })
    ip = p.table("ip", key="ip_id", mutable=False, doc="Source IPs (hashed)", cols={
        "country": cat(*COUNTRIES),
        "kind": cat("residential", "mobile", "datacenter", "vpn"),
    })
    address = p.table("address", key="address_id", mutable=False,
                      doc="External on-chain addresses (deposit sources, withdrawal targets)",
                      cols={"chain": text(), "kind": cat("self_custody", "other_exchange",
                                                         "otc", "unknown")})

    # Reference prices: exogenous, read-only for every partition (traders and books alike)
    ref_price = std.timeline(
        p, "ref_price", key=symbol, start="init_price", tick=px.tick,
        model=dist.jump_diffusion(vol_annual=std.by_tier(px.vol_annual),
                                  jump_rate_daily=std.by_tier(px.jump_rate_daily),
                                  jump_size=px.jump_size),
        factor=std.common_factor(loading=px.market_factor),
        usd_quote=("USDT", "BTC-USDT"))      # .usd(asset, t) for notional_usdt
    attention = std.attention_index(ref_price, weight="popularity", gain=rt.attention_gain,
                                    window="1h")

    # ---------------------------------------------------------------- owner state
    trader = p.table("trader", key="trader_id", mutable=True, doc="An exchange account", cols={
        "registered_at": ts(),
        "country": cat(*COUNTRIES),
        "segment": cat(*SEGMENTS),
        "kyc_level": i16(),                  # 0 none, 1 basic, 2 full
        "api_keys": i16(),
        "status": cat("active", "dormant", "closed"),
        "open_orders": i32(),
        "first_trade_at": opt(ts()),
    })
    p.table("balance", key=("trader_id", "asset_id"), mutable=True, child_of="trader",
            dense_key="asset_id", doc="One row per asset, laid out densely next to the trader",
            cols={
                "available": amount(asset_from="asset_id"),
                "held": amount(asset_from="asset_id"),   # open-order locks + pending withdrawals
            })
    p.table("order", key="order_id", mutable=True, child_of="trader",
            retire_when="status in ('filled', 'cancelled', 'rejected')",   # freed next step
            doc="Owner-side mirror of an order; the book holds the matching copy", cols={
                "symbol_id": ref("symbol"),
                "side": cat("buy", "sell"),
                "type": cat("limit", "market"),
                "tif": cat("GTC", "IOC", "FOK"),
                "post_only": boolean(),
                "price": opt(i64(min=1)),
                "qty": opt(amount(asset_from="symbol_id.base")),
                "quote_qty": opt(amount(asset_from="symbol_id.quote")),   # market buy budget
                "filled_qty": amount(asset_from="symbol_id.base"),
                "lock_asset": ref("asset"),
                "lock_remaining": amount(asset_from="lock_asset"),
                "status": cat("pending", "open", "filled", "cancelled", "rejected"),
                "cancel_pending": boolean(),
                "submitted_at": ts(),
            })
    p.table("deposit", key="deposit_id", mutable=True, child_of="trader", cols={
        "asset_id": ref("asset"), "amount": amount(asset_from="asset_id"),
        "address_id": ref("address"), "status": cat("detected", "credited"),
    })
    p.table("withdrawal", key="withdrawal_id", mutable=True, child_of="trader", cols={
        "asset_id": ref("asset"), "amount": amount(asset_from="asset_id"),
        "fee": amount(asset_from="asset_id"), "address_id": ref("address"),
        "requested_at": ts(),
        "status": cat("pending", "approved", "sent", "rejected"),
    })

    p.owner("trader", table="trader", execution_owner=cfg.execution_owner,
            max_live=cfg.traders + mm.accounts,
            children=["balance", "order", "deposit", "withdrawal"])

    p.population(
        trader, n=cfg.traders,
        initial=cfg.initial_share,
        arrivals=dist.poisson_daily(weekly=(1.0, 1.0, 1.0, 1.0, 1.05, 0.9, 0.85),
                                    trend=0.001, shocks=std.follow_timeline(ref_price,
                                                                            gain=8.0)),
        attrs={
            "segment": dist.categorical({"retail": 1 - cfg.pro_share, "pro": cfg.pro_share}),
            "country": dist.categorical({"US": .14, "TR": .09, "KR": .08, "IN": .08, "VN": .07,
                                         "BR": .07, "NG": .06, "GB": .05, "DE": .05, "ID": .05,
                                         "PH": .04, "JP": .04, "FR": .03, "other": .15}),
            "kyc_level": 0,
        },
        refs={"device": std.devices(per_user=dist.categorical({1: .55, 2: .35, 3: .10}),
                                    table=device, share=cfg.device_share),
              "ip": std.ips(per_user=dist.categorical({1: .4, 2: .35, 3: .15, 4: .1}),
                            table=ip, share=cfg.ip_share),
              "address": std.addresses(per_user=dist.geometric(mean=1.5, max=6),
                                       table=address, share=cfg.address_share)},
    )
    p.population(                            # institutional quoting accounts, all from day 0
        trader, n=mm.accounts if m.fidelity == "matched" else 0, initial=1.0,
        name="market_makers",
        attrs={"segment": "market_maker", "country": "other", "kyc_level": 2},
        refs={"ip": std.ips(per_user=dist.uniform_int(2, 6), table=ip, kind="datacenter"),
              "address": std.addresses(per_user=dist.uniform_int(2, 4), table=address),
              "quoted_symbols": std.assign_subset(symbol, k=mm.symbols_per_mm,
                                                  weight="popularity", cover_all=True)},
    )

    # ---------------------------------------------------------------- shards
    book = p.shard("book", key="symbol_id", n=cfg.symbols, doc="One symbol's order book", state={
        "levels": std.price_levels(cap=m.max_resting, fields={
            "order_id": "ref", "trader_id": "ref", "stp_id": "ref", "qty": "i64",
            "left": "i64", "lock": "i64", "fee_maker_ppm": "i32", "seq": "i64",
        }),                                   # bids/asks: price -> FIFO, best pointers, id index
        "tk": std.struct(active="bool", order_id="ref", trader_id="ref", stp_id="ref",
                         side="i8", type="i8", tif="i8", price="i64", qty="i64", left="i64",
                         budget="i8", lock="i64", filled="i64", fee_maker_ppm="i32",
                         fee_taker_ppm="i32", seq="i64"),   # the taker being matched
        "seq": "i64",                         # book sequence (time priority)
        "last_price": "i64",
    })

    # ---------------------------------------------------------------- boundaries
    # Requests from one trader to one book are FIFO (one order-entry session per pair), so a
    # cancel never overtakes the place it refers to.
    place = p.request("place", frm="trader", to="book", reply_to="order_settlement", fifo=True,
                      doc="Order entry; the lock is already held on the trader",
                      payload={
                          "order_id": ref("order"), "trader_id": ref("trader"),
                          "stp_id": ref("trader"), "side": "i8", "type": "i8", "tif": "i8",
                          "post_only": "bool", "price": "i64", "qty": "i64",
                          "quote_qty": "i64", "lock": "i64",
                          "fee_maker_ppm": "i32", "fee_taker_ppm": "i32",
                      },
                      responses=("accepted", "rejected"),
                      latency=m.entry_latency)
    cancel = p.request("cancel", frm="trader", to="book", reply_to="order_settlement", fifo=True,
                       payload={"order_id": ref("order"), "trader_id": ref("trader")},
                       responses=("cancelled", "cancel_rejected"),
                       latency=m.entry_latency)
    # Shard -> owner notifications (no request outstanding on the maker side). FIFO with the
    # responses on the same (book, trader) pair, so `accepted` precedes the order's fills.
    fill = p.message("fill", frm="book", to="trader", deliver_to="order_settlement", fifo=True,
                    payload={"order_id": ref("order"), "trade_id": ref("trade"),
                             "side": "i8", "qty": "i64", "quote": "i64", "fee": "i64",
                             "lock_used": "i64"},
                    latency=m.report_latency)
    done = p.message("done", frm="book", to="trader", deliver_to="order_settlement", fifo=True,
                    payload={"order_id": ref("order"), "status": "i8", "release": "i64"},
                    latency=m.report_latency)

    fees = p.accumulator("exchange_fees", "i64[asset]")         # additive; no decision reads it
    external = p.accumulator("external_flow", "i64[asset]")     # external_liquidity counterparty

    # ---------------------------------------------------------------- events: trader
    common = {"trader_id": ref("trader")}
    p.event("trader_registered", owner="trader", doc="An account is opened", cols={
        **common, "segment": cat(*SEGMENTS), "country": cat(*COUNTRIES),
        "channel": cat(*CHANNELS), "device_id": opt(ref("device")), "ip_id": ref("ip"),
    })
    p.event("login", owner="trader", doc="A session or API connection starts", cols={
        **common, "channel": cat(*CHANNELS), "device_id": opt(ref("device")), "ip_id": ref("ip"),
    })
    p.event("kyc_upgraded", owner="trader", cols={
        **common, "from_level": i16(), "to_level": i16(),
        "method": cat("document", "video", "institutional"),
    })
    p.event("api_key_created", owner="trader", cols={
        **common, "api_key_id": ref("api_key"),
        "permissions": cat("read", "trade", "trade_withdraw"), "ip_whitelist": boolean(),
    })
    p.event("deposit_detected", owner="trader", doc="An on-chain transfer to the account is seen",
            cols={**common, "deposit_id": ref("deposit"), "asset_id": ref("asset"),
                  "amount": amount(asset_from="asset_id"), "address_id": ref("address"),
                  "confirmations_required": i16()})
    p.event("deposit_credited", owner="trader", doc="Enough confirmations; balance credited",
            cols={**common, "deposit_id": ref("deposit"), "asset_id": ref("asset"),
                  "amount": amount(asset_from="asset_id"),
                  "amount_usdt": amount(asset="USDT")})
    p.event("order_submitted", owner="trader", doc="Lock held, order sent to the book", cols={
        **common, "order_id": ref("order"), "symbol_id": ref("symbol"),
        "side": cat("buy", "sell"), "type": cat("limit", "market"),
        "tif": cat("GTC", "IOC", "FOK"), "post_only": boolean(),
        "price": opt(i64(min=1)), "qty": opt(amount(asset_from="symbol_id.base")),
        "quote_qty": opt(amount(asset_from="symbol_id.quote")),
        "lock": amount(asset_from="lock_asset"), "lock_asset": ref("asset"),
        "notional_usdt": amount(asset="USDT"),        # estimate at the reference price
        "channel": cat(*CHANNELS), "device_id": opt(ref("device")), "ip_id": ref("ip"),
    })
    p.event("balance_settled", owner="trader",
            doc="Trader applies a fill (held -> spent, credit minus fee) or a lock release",
            cols={**common, "order_id": ref("order"), "trade_id": opt(ref("trade")),
                  "kind": cat("fill", "release"),
                  "debit_asset": ref("asset"), "debit": amount(asset_from="debit_asset"),
                  "credit_asset": ref("asset"), "credit": amount(asset_from="credit_asset"),
                  "fee": amount(asset_from="credit_asset")})
    p.event("withdrawal_requested", owner="trader", doc="Amount moved to held for review", cols={
        **common, "withdrawal_id": ref("withdrawal"), "asset_id": ref("asset"),
        "amount": amount(asset_from="asset_id"), "available_before": amount(asset_from="asset_id"),
        "amount_usdt": amount(asset="USDT"), "address_id": ref("address"),
        "device_id": opt(ref("device")), "ip_id": ref("ip"),
    })
    p.event("withdrawal_approved", owner="trader", cols={
        **common, "withdrawal_id": ref("withdrawal"), "review": cat("auto", "manual"),
    })
    p.event("withdrawal_rejected", owner="trader", cols={
        **common, "withdrawal_id": ref("withdrawal"),
        "reason": cat("risk_review", "address_screening", "travel_rule"),
    })
    p.event("withdrawal_sent", owner="trader", doc="Broadcast on chain; held amount spent", cols={
        **common, "withdrawal_id": ref("withdrawal"), "asset_id": ref("asset"),
        "amount": amount(asset_from="asset_id"), "fee": amount(asset_from="asset_id"),
        "address_id": ref("address"),
    })

    # ---------------------------------------------------------------- events: book
    book_cols = {"symbol_id": ref("symbol"), "order_id": ref("order"), "trader_id": ref("trader")}
    p.event("order_accepted", shard="book", doc="Order passed validation and entered matching",
            cols={**book_cols, "side": cat("buy", "sell"), "type": cat("limit", "market"),
                  "tif": cat("GTC", "IOC", "FOK"), "post_only": boolean(),
                  "price": opt(i64(min=1)), "qty": opt(amount(asset_from="symbol_id.base")),
                  "quote_qty": opt(amount(asset_from="symbol_id.quote")),
                  "book_seq": i64()})
    p.event("order_rejected", shard="book", cols={
        **book_cols, "reason": cat("price_band", "lot_size", "min_notional",
                                   "post_only_would_cross", "book_full", "fok_quote_budget"),
    })
    p.event("order_cancelled", shard="book", doc="Order closed with a remainder", cols={
        **book_cols, "reason": cat("user", "ioc_remainder", "fok_killed", "stp",
                                   "market_no_liquidity"),
        "filled_qty": amount(asset_from="symbol_id.base"),
    })
    p.event("order_filled", shard="book", doc="Order closed fully filled", cols={
        **book_cols, "role": cat("maker", "taker"),
        "filled_qty": amount(asset_from="symbol_id.base"),
    })
    p.event("cancel_rejected", shard="book", doc="Cancel arrived after the order closed", cols={
        **book_cols, "reason": cat("unknown_order", "not_owner"),
    })
    p.event("trade", shard="book", doc="One fill between a resting maker and a taker", cols={
        "symbol_id": ref("symbol"), "trade_id": ref("trade"),
        "price": i64(min=1), "qty": amount(asset_from="symbol_id.base"),
        "quote_amount": amount(asset_from="symbol_id.quote"),
        "notional_usdt": amount(asset="USDT"),
        "taker_side": cat("buy", "sell"),
        "taker_order_id": opt(ref("order")), "taker_trader_id": opt(ref("trader")),  # null:
        # external taker (ticker sweep); maker null: external maker (external_liquidity)
        "maker_order_id": opt(ref("order")), "maker_trader_id": opt(ref("trader")),
        "buyer_fee": amount(asset_from="symbol_id.base"),     # fee in the received asset
        "seller_fee": amount(asset_from="symbol_id.quote"),
        "liquidity": cat("book", "external"),
        "book_seq": i64(),
    })
    p.event("book_ticker", shard="book", doc="Top of book, sampled every minute", cols={
        "symbol_id": ref("symbol"),
        "best_bid": opt(i64()), "best_ask": opt(i64()),
        "bid_qty": amount(asset_from="symbol_id.base"),
        "ask_qty": amount(asset_from="symbol_id.base"),
        "spread_bps": opt(f64()), "ref_price": i64(), "last_price": opt(i64()),
        "resting_orders": i32(),
    })

    # ---------------------------------------------------------------- processes: trader
    reads = {"symbol": symbol, "asset": asset, "device": device, "ref_price": ref_price,
             "attention": attention}
    p.process("trader_activity", owner="trader", kernel=k.trader_activity, config=rt,
              start=p.on_created("trader", where="segment != 'market_maker'"),
              requests={"place": place, "cancel": cancel}, reads=reads,
              commands=k.ACTIVITY_COMMANDS)
    p.process("market_maker", owner="trader", kernel=k.market_maker, config=mm,
              start=p.on_created("trader", where="segment == 'market_maker'"),
              enabled=m.fidelity == "matched",
              requests={"place": place, "cancel": cancel}, reads=reads,
              commands=k.MM_COMMANDS)
    p.process("order_settlement", owner="trader", kernel=k.settle,   # never suppressed
              responses=(place, cancel), messages=(fill, done),
              requests={"cancel": cancel}, reads={"symbol": symbol},
              writes={"exchange_fees": fees}, commands=k.SETTLE_COMMANDS)
    p.process("funding", owner="trader", kernel=k.funding, config=f,
              start=p.on_created("trader"), reads=reads, commands=k.FUNDING_COMMANDS)

    # Onboarding: common behavior, so a state machine
    ob = p.machine("onboarding", owner="trader",
                   start=p.on_created("trader", where="segment != 'market_maker'"),
                   initial="new")
    ob.state("new", branch={"registered": (1.0, None, k.register)})
    ob.state("registered", branch={
        "kyc1":      (f.kyc1_p, f.kyc1_delay, k.upgrade_kyc.with_params(level=1)),
        "otherwise": (1 - f.kyc1_p, None, None),
    })
    ob.state("kyc1", branch={
        "kyc2":      (f.kyc2_p, f.kyc2_delay, k.upgrade_kyc.with_params(level=2)),
        "otherwise": (1 - f.kyc2_p, None, None),
    })
    ob.final("kyc2", "otherwise")

    api = p.machine("api_access", owner="trader", start=p.on_event("trader_registered"),
                    initial="maybe")
    api.state("maybe", branch={
        "created":   (std.by_segment(f.api_key_p), dist.lognormal(median_s=86_400, sigma=1.5),
                      k.create_api_key),
        "otherwise": (None, None, None),     # unpicked mass
    })
    api.final("created", "otherwise")

    # Deposits: detected by the funding kernel, credited after the asset's confirmations
    dep = p.machine("deposit", owner="trader", instance="deposit",
                    start=p.on_event("deposit_detected"), initial="confirming")
    dep.state("confirming", branch={
        "credited": (1.0, std.confirmation_delay(asset, shape=4.0), k.credit_deposit),
    })
    dep.final("credited")

    # Withdrawals: held at request, reviewed, then broadcast or rejected (hold released)
    wd = p.machine("withdrawal", owner="trader", instance="withdrawal",
                   start=p.on_event("withdrawal_requested"), initial="review")
    wd.state("review", branch={
        "approved": (1 - f.withdraw_reject_p,
                     dist.mixture({dist.lognormal(median_s=25, sigma=0.6): f.auto_review_p,
                                   f.manual_review: 1 - f.auto_review_p}),
                     k.approve_withdrawal),
        "rejected": (f.withdraw_reject_p, f.manual_review, k.reject_withdrawal),
    })
    wd.state("approved", branch={"sent": (1.0, f.broadcast_delay, k.send_withdrawal)})
    wd.final("sent", "rejected")

    # ---------------------------------------------------------------- processes: book
    p.process("match", shard=book, kernel=k.match, config=m, serves=(place, cancel),
              sends=(fill, done), reads={"symbol": symbol, "ref_price": ref_price},
              writes={"external_flow": external}, commands=k.MATCH_COMMANDS)
    p.process("ticker", shard=book, kernel=k.ticker, config=m, every=m.ticker_every,
              sends=(fill, done), reads={"symbol": symbol, "ref_price": ref_price},
              writes={"external_flow": external})

    # ---------------------------------------------------------------- enrichment
    # Cross-owner features, computed after each step seals on canonical order; go to golden/
    p.feature("device_distinct_traders_24h",
              std.rolling_distinct("trader_id", by="device_id", window="24h"),
              on=["login", "withdrawal_requested"], into="golden")
    p.feature("ip_distinct_traders_24h",
              std.rolling_distinct("trader_id", by="ip_id", window="24h"),
              on=["login", "order_submitted", "withdrawal_requested"], into="golden")
    p.feature("trader_notional_24h",
              std.rolling_sum("trade.notional_usdt", by=("maker_trader_id", "taker_trader_id"),
                              window="24h"),
              on=["order_submitted", "withdrawal_requested"], into="golden")
    p.feature("counterparty_top_share_7d",
              std.rolling_top_share("trade.notional_usdt", by="taker_trader_id",
                                    of="maker_trader_id", window="7d"),
              on=["trade"], into="golden")

    # ---------------------------------------------------------------- laws
    p.check("chk.available_never_negative", law.never_negative("balance.available"),
            required=True)
    p.check("chk.held_never_negative", law.never_negative("balance.held"), required=True)
    p.check("chk.held_equals_locks",
            law.equals_sum("balance.held", by=("trader_id", "asset_id"), of=(
                ("order.lock_remaining", "lock_asset", "status in ('pending', 'open')"),
                ("withdrawal.amount", "asset_id", "status in ('pending', 'approved')"),
            )), required=True)
    p.check("chk.locks_reconcile",            # book copy == owner mirror once in-flight lands
            law.reconciles("book.levels.lock", "order.lock_remaining", key="order_id",
                           in_flight=(fill, done)), required=True)
    p.check("chk.trade_conservation",
            law.conserved(key="trade_id", where="liquidity == 'book'",
                          debit="balance_settled.debit", credit=("balance_settled.credit",
                                                                 "balance_settled.fee"),
                          by_asset=True, legs=2, against="trade",
                          censor="in_flight_at_horizon"), required=True)
    p.check("chk.fill_le_order",
            law.sum_le("trade.qty", "order_accepted.qty", by=("taker_order_id", "maker_order_id"),
                       where="qty is not null"), required=True)
    p.check("chk.price_time_priority",
            law.price_time_priority(accepted="order_accepted", trades="trade",
                                    closed=("order_cancelled", "order_filled"),
                                    book="symbol_id", seq="book_seq",
                                    reference=std.reference_matcher(stp=m.stp_mode)),
            required=True)
    p.check("chk.no_self_trade",
            law.never("trade", where="maker_trader_id == taker_trader_id"),
            required=m.stp_mode != "off")
    p.check("chk.fok_all_or_nothing",
            law.all_or_nothing("trade.qty", per="taker_order_id", total="order_accepted.qty",
                               where="tif == 'FOK'"), required=True)
    p.check("chk.order_lifecycle", law.lifecycle("order_id", edges={
        "order_submitted": ("order_accepted", "order_rejected"),
        "order_accepted": ("order_filled", "order_cancelled"),
    }, terminal=("order_rejected", "order_filled", "order_cancelled"),
       open_at_horizon="censored"), required=True)
    p.check("chk.withdrawal_le_available",
            law.row("withdrawal_requested", "amount <= available_before"), required=True)
    p.check("chk.withdrawal_lifecycle", law.lifecycle("withdrawal_id", edges={
        "withdrawal_requested": ("withdrawal_approved", "withdrawal_rejected"),
        "withdrawal_approved": ("withdrawal_sent",),
    }), required=True)
    p.check("chk.deposit_credited_once",
            law.at_most_once("deposit_credited", key="deposit_id"), required=True)

    # ---------------------------------------------------------------- extension points
    # Named actions overlays may call (validate checks them against the resolved plan).
    # Under a grouped execution_owner, `account=` picks which member trader row acts.
    p.expose(
        register=k.register, login=k.login, upgrade_kyc=k.upgrade_kyc,
        create_api_key=k.create_api_key, deposit=k.deposit, withdraw=k.withdraw,
        place_order=k.place_order, cancel_order=k.cancel_order,
    )
    p.expose_param("matching.price_band", m.price_band)
    p.expose_param("matching.market_collar", m.market_collar)
