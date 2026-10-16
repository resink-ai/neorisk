"""Handwritten kernels for the crypto_exchange pack.

Every kernel follows the action interface:
    1. validate   read state, maybe reject(...)       no writes yet
    2. reserve    out.reserve(...) for every resource  RETRY if the slab is full
    3. commit     mutate state, emit, schedule         cannot fail
Random draws use ctx.rng.<dist>(site=N, ...); each draw site has its own number, so edits to
one site never shift draws at another.

Amounts are int64 at the asset's ledger quantum. price × qty goes through
std.checked_muldiv (128-bit intermediate, floor unless round="ceil"), so BTC-sized notionals
never overflow and buyer and seller see the same quote amount.

Money flow for one order (all amounts immutable once sent):
    trader   available -> held (lock)  ──place(lock)──▶  book keeps lock per order
    book     fill: lock -= used        ──fill──▶  both traders: held -= used, credit - fee
    book     close: lock left          ──done──▶  trader: held -> available
"""

from neorisk_simkit.engine import COMMIT, RETRY, Local, Res, kernel, reject
from neorisk_simkit import std

# ------------------------------------------------------------------ enums (cat ordinals)
BUY, SELL = 0, 1
LIMIT, MARKET = 0, 1
GTC, IOC, FOK = 0, 1, 2
ST_PENDING, ST_OPEN, ST_FILLED, ST_CANCELLED, ST_REJECTED = 0, 1, 2, 3, 4
SEG_RETAIL, SEG_PRO, SEG_MM = 0, 1, 2
CH_WEB, CH_APP, CH_API = 0, 1, 2
A_USDT, A_BTC, A_ETH, A_SOL = 0, 1, 2, 3          # row order of pack.ASSETS
TIER_SMALL = 3

EXTERNAL = "external_liquidity"
STP_OFF, STP_CANCEL_MAKER, STP_CANCEL_TAKER, STP_CANCEL_BOTH = (
    "off", "cancel_maker", "cancel_taker", "cancel_both")

# ------------------------------------------------------------------ command ids
C_START = 0             # process start (delivered by start=...)
C_SESSION = 1           # timer: next session (login)
C_DECIDE = 2            # timer: next order decision inside a session
C_PATIENCE = 3          # timer: cancel a GTC order if it is still open
C_REQUOTE = 20          # timer: market maker re-quotes its next symbol
C_DEPOSIT = 31          # timer: next deposit
C_WITHDRAW = 32         # timer: next withdrawal decision
R_ACCEPTED = 40         # response: place accepted by the book
R_REJECTED = 41         # response: place rejected (whole lock comes back)
R_CANCELLED = 42        # response: cancel done (release arrives as `done`)
R_CANCEL_REJECTED = 43  # response: order already closed
N_FILL = 44             # notification: one fill on one of my orders
N_DONE = 45             # notification: my order closed; remaining lock released
Q_PLACE = 50            # book: place request
Q_CANCEL = 51           # book: cancel request
C_CONTINUE = 52         # book: same-time continuation of the active taker

ACTIVITY_COMMANDS = (C_START, C_SESSION, C_DECIDE)
MM_COMMANDS = (C_START, C_REQUOTE)
FUNDING_COMMANDS = (C_START, C_DEPOSIT, C_WITHDRAW)
SETTLE_COMMANDS = (R_ACCEPTED, R_REJECTED, R_CANCELLED, R_CANCEL_REJECTED, N_FILL, N_DONE,
                   C_PATIENCE)
MATCH_COMMANDS = (Q_PLACE, Q_CANCEL, C_CONTINUE)

# priorities at equal time (lower runs first): continuations, then messages, then timers
PRIO_CONTINUE, PRIO_RESPONSE, PRIO_TIMER = 0, 1, 5

REJ_STALE = 1
REJ_DORMANT = 2
REJ_SESSION_OVER = 3
REJ_FUNDS = 4
REJ_UNKNOWN_ORDER = 5
REJ_KYC = 6
REJ_NEVER_FUNDS = 7
REJ_LIMIT = 8

FILLS = 64                       # fixed fan-out sub-step: maker touches per invocation
MAX_NOTIFY = 3 * FILLS + 2       # per touch: 2 fills + 1 done; plus the taker's done
MAX_MM_SYMBOLS = 16
MAX_LEVELS = 4
PPM = 1_000_000
STOP_NONE, STOP_DONE, STOP_NO_LIQUIDITY, STOP_STP = 0, 1, 2, 3

MINUTE = 60_000_000      # µs
HOUR = 3_600_000_000


# ================================================================== shared order entry
def _fees(s, cfg):
    if s.segment == SEG_PRO:
        return cfg.pro_fee_maker_ppm, cfg.pro_fee_taker_ppm
    return cfg.fee_maker_ppm, cfg.fee_taker_ppm


def _lock_for(ctx, sym, side, otype, price, qty, qbudget):
    """Read-only: which asset an order locks and how much. Limit buys lock at the limit price,
    rounded up, so fills at that price or better (each rounded down) never exceed the lock."""
    sy = ctx.reads.symbol
    if side == SELL:
        return sy.base[sym], qty
    if otype == MARKET:
        return sy.quote[sym], qbudget
    return sy.quote[sym], std.checked_muldiv(price, qty, sy.notional_div[sym], round="ceil")


def _submit(ctx, s, out, sym, side, otype, tif, post_only, price, qty, qbudget, lock_asset,
            lock, fee_m, fee_t, channel, device, ip):
    """Commit half of order entry; the caller validated and reserved. Owner-side hold, mirror
    row, order_submitted, then the immutable place request carrying the lock."""
    sy = ctx.reads.symbol
    s.balance.available[lock_asset] = std.checked_sub(s.balance.available[lock_asset], lock)
    s.balance.held[lock_asset] = std.checked_add(s.balance.held[lock_asset], lock)
    s.open_orders += 1
    order = out.create_order(symbol_id=sym, side=side, type=otype, tif=tif, post_only=post_only,
                             price=price, qty=qty, quote_qty=qbudget, filled_qty=0,
                             lock_asset=lock_asset, lock_remaining=lock,
                             status=std.cat("pending"), cancel_pending=False, submitted_at=ctx.t)
    px = price if price > 0 else ctx.reads.ref_price.at(sym, ctx.t)
    notional = std.checked_muldiv(px, qty, sy.notional_div[sym]) if qty > 0 else qbudget
    out.emit_order_submitted(ctx.t, trader_id=ctx.self_id, order_id=order, symbol_id=sym,
                             side=side, type=otype, tif=tif, post_only=post_only, price=price,
                             qty=qty, quote_qty=qbudget, lock=lock, lock_asset=lock_asset,
                             notional_usdt=ctx.reads.ref_price.to_usdt(sy.quote[sym], notional,
                                                                       ctx.t),
                             channel=channel, device_id=device, ip_id=ip)   # 0 -> null
    out.request_place(ctx.t, shard=sym, order_id=order, trader_id=ctx.self_id,
                      stp_id=ctx.self_id, side=side, type=otype, tif=tif, post_only=post_only,
                      price=price, qty=qty, quote_qty=qbudget, lock=lock,
                      fee_maker_ppm=fee_m, fee_taker_ppm=fee_t)
    return order


# ================================================================== retail / pro trading
ACTIVITY_LOCAL = Local(device="ref", ip="ref", channel="i8", decisions_left="i16")


@kernel(state="trader", local=ACTIVITY_LOCAL, commands=ACTIVITY_COMMANDS,
        max=Res(records={"login": 1, "order_submitted": 1}, creates={"order": 1},
                timers=2, requests=1))
def trader_activity(ctx, s, loc, cmd, out):
    """Sessions driven by attention; each session makes a few order decisions."""
    cfg = ctx.cfg
    if cmd.kind == C_START or cmd.kind == C_SESSION:
        return _session(ctx, s, loc, out, cfg)
    if cmd.kind == C_DECIDE:
        return _decide(ctx, s, loc, out, cfg)
    return reject(REJ_STALE)


def _session(ctx, s, loc, out, cfg):
    if s.status != std.ACTIVE:
        return reject(REJ_DORMANT)
    if not out.reserve(records={"login": 1}, timers=2):
        return RETRY
    api = s.api_keys > 0 and s.segment == SEG_PRO
    loc.channel = CH_API if api else ctx.rng.categorical(site=1, p=(.36, .64))
    loc.device = 0 if api else ctx.refs.device.pick(ctx.self_id, ctx.rng.uniform(site=2))
    loc.ip = ctx.refs.ip.pick(ctx.self_id, ctx.rng.uniform(site=3))
    loc.decisions_left = 1 + ctx.rng.geometric(site=4, mean=cfg.decisions_mean)
    out.emit_login(ctx.t, trader_id=ctx.self_id, channel=loc.channel, device_id=loc.device,
                   ip_id=loc.ip)
    out.timer(ctx.t + ctx.rng.dist_us(site=5, d=cfg.decide_gap), C_DECIDE, prio=PRIO_TIMER)
    gap = ctx.rng.pareto_us(site=6, alpha=cfg.session_gap_alpha, min_h=cfg.session_gap_min_h)
    if s.segment == SEG_PRO:
        gap = gap // int(cfg.pro_activity)
    out.timer(ctx.t + gap, C_SESSION, prio=PRIO_TIMER)
    return COMMIT


def _decide(ctx, s, loc, out, cfg):
    if loc.decisions_left <= 0:
        return reject(REJ_SESSION_OVER)
    trades = ctx.rng.bernoulli(site=10, p=cfg.trade_p)
    sym, side, otype, tif, price, qty, qbudget, lock_asset, lock = _plan_retail(ctx, s, cfg)
    if not trades or lock == 0:                        # only looked, or nothing fits
        if not out.reserve(timers=1):
            return RETRY
        _next_decision(ctx, loc, out, cfg)
        return COMMIT
    if not out.reserve(records={"order_submitted": 1}, creates={"order": 1}, requests=1,
                       timers=2):
        return RETRY
    fee_m, fee_t = _fees(s, cfg)
    order = _submit(ctx, s, out, sym, side, otype, tif, False, price, qty, qbudget, lock_asset,
                    lock, fee_m, fee_t, loc.channel, loc.device, loc.ip)
    if otype == LIMIT and tif == GTC:                  # give up on it later if still open
        out.timer(ctx.t + ctx.rng.dist_us(site=19, d=cfg.patience), C_PATIENCE,
                  prio=PRIO_TIMER, tag=order, to="order_settlement")
    _next_decision(ctx, loc, out, cfg)
    return COMMIT


def _next_decision(ctx, loc, out, cfg):
    loc.decisions_left -= 1
    if loc.decisions_left > 0:
        out.timer(ctx.t + ctx.rng.dist_us(site=18, d=cfg.decide_gap), C_DECIDE, prio=PRIO_TIMER)


def _plan_retail(ctx, s, cfg):
    """Read-only: pick symbol (attention), side (momentum), type and size. lock == 0 means
    nothing sensible fits the trader's balances."""
    sy = ctx.reads.symbol
    sym = ctx.reads.attention.sample(ctx.t, ctx.rng.uniform(site=11))
    base, quote = sy.base[sym], sy.quote[sym]
    div, lot = sy.notional_div[sym], sy.lot[sym]
    ref = ctx.reads.ref_price.at(sym, ctx.t)
    r1h = ctx.reads.ref_price.ret(sym, ctx.t, HOUR)
    p_buy = min(0.85, max(0.15, 0.5 + cfg.momentum * r1h))
    has_base = s.balance.available[base] >= lot
    side = BUY if (not has_base or ctx.rng.bernoulli(site=12, p=p_buy)) else SELL
    market_p = cfg.pro_market_p if s.segment == SEG_PRO else cfg.market_p
    otype = MARKET if ctx.rng.bernoulli(site=13, p=market_p) else LIMIT
    tif, price = IOC, 0
    if otype == LIMIT:
        u = ctx.rng.uniform(site=14)
        tif = FOK if u < cfg.fok_p else (IOC if u < cfg.fok_p + cfg.ioc_p else GTC)
        off = ctx.rng.dist(site=15, d=cfg.limit_offset_bps)
        price = (std.shift_bps(ref, -off, round="down") if side == BUY
                 else std.shift_bps(ref, off, round="up"))
    qty, qbudget = 0, 0
    if side == BUY:
        spend = std.share_of(s.balance.available[quote], ctx.rng.dist(site=16, d=cfg.buy_share))
        if otype == MARKET:
            qbudget = spend
        else:
            qty = std.checked_muldiv(spend, div, price) // lot * lot
    else:
        qty = std.share_of(s.balance.available[base],
                           ctx.rng.dist(site=17, d=cfg.sell_share)) // lot * lot
    lock_asset, lock = _lock_for(ctx, sym, side, otype, price, qty, qbudget)
    notional = std.checked_muldiv(price if price > 0 else ref, qty, div) if qty > 0 else qbudget
    if lock <= 0 or notional < sy.min_notional[sym] or lock > s.balance.available[lock_asset]:
        lock = 0
    return sym, side, otype, tif, price, qty, qbudget, lock_asset, lock


# ================================================================== market makers
MM_LOCAL = Local(
    n_sym="i8", sym="i32[16]", cursor="i8",
    inv_target="i64[16]",           # base holdings at first quote; skew pulls back toward it
    quoted_ref="i64[16]",           # reference price at the last re-quote
    q_order="ref[128]",             # [symbol slot][side][level], MAX_MM_SYMBOLS × 2 × 4
    ip="ref",
)


@kernel(state="trader", local=MM_LOCAL, commands=MM_COMMANDS,
        max=Res(records={"login": 1, "order_submitted": 2 * MAX_LEVELS},
                creates={"order": 2 * MAX_LEVELS}, requests=4 * MAX_LEVELS, timers=1))
def market_maker(ctx, s, loc, cmd, out):
    """Post-only ladders around the reference price, skewed by inventory; cancel/replace when
    the reference moves or a quote has been filled. Visits one symbol per invocation."""
    cfg = ctx.cfg
    if cmd.kind == C_START:
        return _mm_start(ctx, s, loc, out, cfg)
    if cmd.kind == C_REQUOTE:
        return _requote(ctx, s, loc, out, cfg)
    return reject(REJ_STALE)


def _mm_start(ctx, s, loc, out, cfg):
    if not out.reserve(records={"login": 1}, timers=1):
        return RETRY
    n = ctx.refs.quoted_symbols.count(ctx.self_id)
    loc.n_sym = min(n, MAX_MM_SYMBOLS)
    for i in range(loc.n_sym):
        loc.sym[i] = ctx.refs.quoted_symbols.get(ctx.self_id, i)
    loc.ip = ctx.refs.ip.pick(ctx.self_id, ctx.rng.uniform(site=1))
    out.emit_login(ctx.t, trader_id=ctx.self_id, channel=CH_API, device_id=0, ip_id=loc.ip)
    # first quotes once the funding deposits have confirmed
    out.timer(ctx.t + 2 * HOUR + ctx.rng.exp_us(site=2, mean_s=600), C_REQUOTE, prio=PRIO_TIMER)
    return COMMIT


def _requote(ctx, s, loc, out, cfg):
    sy = ctx.reads.symbol
    i = loc.cursor
    sym = loc.sym[i]
    base, quote, tier = sy.base[sym], sy.quote[sym], sy.tier[sym]
    div, lot = sy.notional_div[sym], sy.lot[sym]
    ref = ctx.reads.ref_price.at(sym, ctx.t)
    half = cfg.half_spread_bps[tier]
    moved = std.abs_bps(ref, loc.quoted_ref[i])        # +inf when never quoted
    stale = False
    live = 0
    for j in range(2 * cfg.levels):
        oid = loc.q_order[i * 2 * MAX_LEVELS + j]
        if oid != 0:
            o = s.order.get(oid)
            if o is None or o.status > ST_OPEN:
                stale = True                           # filled or cancelled since last visit
            elif not o.cancel_pending:
                live += 1
    gap = ctx.rng.dist_us(site=10, d=cfg.requote_every) // max(1, loc.n_sym)
    if moved < cfg.requote_threshold * half and not stale:
        if not out.reserve(timers=1):
            return RETRY
        loc.cursor = (i + 1) % loc.n_sym
        out.timer(ctx.t + gap, C_REQUOTE, prio=PRIO_TIMER)
        return COMMIT

    holdings = std.checked_add(s.balance.available[base], s.balance.held[base])
    target = loc.inv_target[i] if loc.inv_target[i] > 0 else holdings
    dev = 0.0 if target == 0 else min(1.0, max(-1.0, (holdings - target) / target))
    skew = -cfg.inventory_skew_bps * (1 + tier) * dev   # long -> quote lower, sell more
    n_new = 2 * cfg.levels
    if not out.reserve(records={"order_submitted": n_new}, creates={"order": n_new},
                       requests=live + n_new, timers=1):
        return RETRY
    if loc.inv_target[i] == 0:
        loc.inv_target[i] = holdings
    for j in range(2 * cfg.levels):                    # cancel what is still live
        k = i * 2 * MAX_LEVELS + j
        oid = loc.q_order[k]
        if oid != 0:
            o = s.order.get(oid)
            if o is not None and o.status <= ST_OPEN and not o.cancel_pending:
                out.request_cancel(ctx.t, shard=sym, order_id=oid, trader_id=ctx.self_id)
                o.cancel_pending = True
            loc.q_order[k] = 0
    level_quote = ctx.reads.ref_price.from_usdt(quote, cfg.level_notional_usdt[tier] * PPM,
                                                ctx.t)
    for lvl in range(cfg.levels):
        bps = half + lvl * cfg.level_step_bps[tier]
        for side in (BUY, SELL):
            price = (std.shift_bps(ref, skew - bps, round="down") if side == BUY
                     else std.shift_bps(ref, skew + bps, round="up"))
            qty = std.checked_muldiv(level_quote, div, price) // lot * lot
            lock_asset, lock = _lock_for(ctx, sym, side, LIMIT, price, qty, 0)
            if qty == 0 or lock > s.balance.available[lock_asset]:
                continue                               # out of inventory on this side
            order = _submit(ctx, s, out, sym, side, LIMIT, GTC, True, price, qty, 0,
                            lock_asset, lock, cfg.fee_maker_ppm, cfg.fee_taker_ppm, CH_API, 0,
                            loc.ip)
            loc.q_order[i * 2 * MAX_LEVELS + 2 * lvl + side] = order
    loc.quoted_ref[i] = ref
    loc.cursor = (i + 1) % loc.n_sym
    out.timer(ctx.t + gap, C_REQUOTE, prio=PRIO_TIMER)
    return COMMIT


# ================================================================== settlement (owner side)
@kernel(state="trader", commands=SETTLE_COMMANDS,
        max=Res(records={"balance_settled": 1}, requests=1))
def settle(ctx, s, cmd, out):
    """Applies everything the book reports about this trader's orders, in arrival order. Also
    owns the patience timer, so overlays that suppress trader_activity keep cancel_after."""
    o = s.order.get(cmd.tag if cmd.kind == C_PATIENCE else cmd.order_id)
    if o is None:
        return reject(REJ_UNKNOWN_ORDER)               # mirror row already retired
    if cmd.kind == C_PATIENCE:
        return _patience_cancel(ctx, s, o, out)
    if cmd.kind == R_ACCEPTED:
        if o.status != ST_PENDING:
            return reject(REJ_STALE)
        if not out.reserve():
            return RETRY
        o.status = std.cat("open")
        return COMMIT
    if cmd.kind == R_CANCELLED or cmd.kind == R_CANCEL_REJECTED:
        if not out.reserve():
            return RETRY
        o.cancel_pending = False                       # the release travels in `done`
        return COMMIT
    if cmd.kind == R_REJECTED:
        return _release(ctx, s, o, out, o.lock_remaining, ST_REJECTED)
    if cmd.kind == N_FILL:
        return _apply_fill(ctx, s, o, cmd, out)
    if cmd.kind == N_DONE:
        return _release(ctx, s, o, out, cmd.release, cmd.status)
    return reject(REJ_STALE)


def _apply_fill(ctx, s, o, cmd, out):
    if o.status != ST_OPEN:
        return reject(REJ_STALE)                       # FIFO makes this unreachable; counted
    sy = ctx.reads.symbol
    base, quote = sy.base[o.symbol_id], sy.quote[o.symbol_id]
    if cmd.side == BUY:                                # spent quote, receive base minus fee
        debit_asset, credit_asset, gross = quote, base, cmd.qty
    else:                                              # spent base, receive quote minus fee
        debit_asset, credit_asset, gross = base, quote, cmd.quote
    if not out.reserve(records={"balance_settled": 1}):
        return RETRY
    credit = std.checked_sub(gross, cmd.fee)
    s.balance.held[debit_asset] = std.checked_sub(s.balance.held[debit_asset], cmd.lock_used)
    s.balance.available[credit_asset] = std.checked_add(s.balance.available[credit_asset], credit)
    o.lock_remaining = std.checked_sub(o.lock_remaining, cmd.lock_used)
    o.filled_qty = std.checked_add(o.filled_qty, cmd.qty)
    if s.first_trade_at == 0:
        s.first_trade_at = ctx.t
    out.accumulate("exchange_fees", credit_asset, cmd.fee)
    out.emit_balance_settled(ctx.t, trader_id=ctx.self_id, order_id=o.id, trade_id=cmd.trade_id,
                             kind=std.cat("fill"), debit_asset=debit_asset, debit=cmd.lock_used,
                             credit_asset=credit_asset, credit=credit, fee=cmd.fee)
    return COMMIT


def _release(ctx, s, o, out, amount, status):
    """held -> available for a closed order. The book's figure is applied as sent;
    chk.locks_reconcile proves it equals the mirror's lock_remaining."""
    if o.status > ST_OPEN:
        return reject(REJ_STALE)
    if not out.reserve(records={"balance_settled": 1}):
        return RETRY
    a = o.lock_asset
    s.balance.held[a] = std.checked_sub(s.balance.held[a], amount)
    s.balance.available[a] = std.checked_add(s.balance.available[a], amount)
    o.lock_remaining = std.checked_sub(o.lock_remaining, amount)
    o.status = status
    s.open_orders -= 1
    if amount > 0:
        out.emit_balance_settled(ctx.t, trader_id=ctx.self_id, order_id=o.id, trade_id=0,
                                 kind=std.cat("release"), debit_asset=a, debit=amount,
                                 credit_asset=a, credit=amount, fee=0)
    return COMMIT


def _patience_cancel(ctx, s, o, out):
    if o.status != ST_OPEN or o.cancel_pending:
        return reject(REJ_STALE)                       # filled, closed, or already cancelling
    if not out.reserve(requests=1):
        return RETRY
    out.request_cancel(ctx.t, shard=o.symbol_id, order_id=o.id, trader_id=ctx.self_id)
    o.cancel_pending = True
    return COMMIT


# ================================================================== funding
@kernel(state="trader", commands=FUNDING_COMMANDS,
        max=Res(records={"deposit_detected": MAX_MM_SYMBOLS + 1, "withdrawal_requested": 1},
                creates={"deposit": MAX_MM_SYMBOLS + 1, "withdrawal": 1}, timers=2))
def funding(ctx, s, cmd, out):
    """When money comes in (first deposit, Pareto top-ups) and goes out (withdrawals)."""
    cfg = ctx.cfg
    if cmd.kind == C_START:
        return _fund_start(ctx, s, out, cfg)
    if cmd.kind == C_DEPOSIT:
        return _topup(ctx, s, out, cfg)
    if cmd.kind == C_WITHDRAW:
        return _maybe_withdraw(ctx, s, out, cfg)
    return reject(REJ_STALE)


def _fund_start(ctx, s, out, cfg):
    if s.segment == SEG_MM:                            # inventory for every quoted symbol
        n = min(ctx.refs.quoted_symbols.count(ctx.self_id), MAX_MM_SYMBOLS)
        if not out.reserve(records={"deposit_detected": n + 1}, creates={"deposit": n + 1}):
            return RETRY
        sy, mm = ctx.reads.symbol, ctx.cfg_of("market_maker")
        usdt_total = 0
        for i in range(n):
            sym = ctx.refs.quoted_symbols.get(ctx.self_id, i)
            usdt = mm.inventory_usdt[sy.tier[sym]] * PPM
            usdt_total = std.checked_add(usdt_total, usdt)
            _detect(ctx, s, out, sy.base[sym],
                    ctx.reads.ref_price.from_usdt(sy.base[sym], usdt, ctx.t),
                    ctx.refs.address.pick(ctx.self_id, ctx.rng.uniform(site=1)))   # k-th draw
        _detect(ctx, s, out, A_USDT, usdt_total,
                ctx.refs.address.pick(ctx.self_id, ctx.rng.uniform(site=2)))
        return COMMIT
    if not ctx.rng.bernoulli(site=3, p=cfg.first_deposit_p):
        return reject(REJ_NEVER_FUNDS)                 # registers, never funds; no writes
    if not out.reserve(timers=2):
        return RETRY
    out.timer(ctx.t + ctx.rng.dist_us(site=4, d=cfg.first_deposit_delay), C_DEPOSIT,
              prio=PRIO_TIMER)
    out.timer(ctx.t + ctx.rng.dist_us(site=5, d=cfg.withdraw_gap), C_WITHDRAW, prio=PRIO_TIMER)
    return COMMIT


def _topup(ctx, s, out, cfg):
    if s.status != std.ACTIVE:
        return reject(REJ_DORMANT)
    if not out.reserve(records={"deposit_detected": 1}, creates={"deposit": 1}, timers=1):
        return RETRY
    a = ctx.rng.categorical(site=10, p=cfg.deposit_asset)
    asset = ctx.reads.attention.sample_asset(ctx.t, ctx.rng.uniform(site=11)) if a == 4 else a
    usdt = ctx.rng.dist(site=12, d=cfg.deposit_usdt) * PPM
    _detect(ctx, s, out, asset, ctx.reads.ref_price.from_usdt(asset, usdt, ctx.t),
            ctx.refs.address.pick(ctx.self_id, ctx.rng.uniform(site=13)))
    out.timer(ctx.t + ctx.rng.dist_us(site=14, d=cfg.topup_gap), C_DEPOSIT, prio=PRIO_TIMER)
    return COMMIT


def _maybe_withdraw(ctx, s, out, cfg):
    if s.status != std.ACTIVE:
        return reject(REJ_DORMANT)
    asset = std.largest_holding(s.balance.available, ctx.reads.ref_price, ctx.t)
    amount = std.share_of(s.balance.available[asset], ctx.rng.dist(site=20, d=cfg.withdraw_share))
    limit = ctx.reads.ref_price.from_usdt(asset, cfg.withdraw_limit_usdt[s.kyc_level] * PPM,
                                          ctx.t)
    amount = min(amount, limit)
    ok = amount > ctx.reads.asset.withdraw_fee[asset]
    if not out.reserve(records={"withdrawal_requested": 1 if ok else 0},
                       creates={"withdrawal": 1 if ok else 0}, timers=1):
        return RETRY
    if ok:
        _request_withdrawal(ctx, s, out, asset, amount,
                            ctx.refs.address.pick(ctx.self_id, ctx.rng.uniform(site=21)),
                            ctx.refs.device.last(ctx.self_id), ctx.refs.ip.last(ctx.self_id))
    out.timer(ctx.t + ctx.rng.dist_us(site=22, d=cfg.withdraw_gap), C_WITHDRAW, prio=PRIO_TIMER)
    return COMMIT


def _detect(ctx, s, out, asset, amount, address):
    dep = out.create_deposit(asset_id=asset, amount=amount, address_id=address,
                             status=std.cat("detected"))
    out.emit_deposit_detected(ctx.t, trader_id=ctx.self_id, deposit_id=dep, asset_id=asset,
                              amount=amount, address_id=address,
                              confirmations_required=ctx.reads.asset.confirmations[asset])


def _request_withdrawal(ctx, s, out, asset, amount, address, device, ip):
    """Owner-side hold for the review; the caller checked amount <= available and the limit."""
    before = s.balance.available[asset]
    s.balance.available[asset] = std.checked_sub(before, amount)
    s.balance.held[asset] = std.checked_add(s.balance.held[asset], amount)
    w = out.create_withdrawal(asset_id=asset, amount=amount,
                              fee=ctx.reads.asset.withdraw_fee[asset], address_id=address,
                              requested_at=ctx.t, status=std.cat("pending"))
    out.emit_withdrawal_requested(ctx.t, trader_id=ctx.self_id, withdrawal_id=w, asset_id=asset,
                                  amount=amount, available_before=before,
                                  amount_usdt=ctx.reads.ref_price.to_usdt(asset, amount, ctx.t),
                                  address_id=address, device_id=device, ip_id=ip)


# ================================================================== machine actions
@kernel(state="trader", instance="deposit", reads=("ref_price",),
        max=Res(records={"deposit_credited": 1}))
def credit_deposit(ctx, s, d, cmd, out):
    if d.status != std.cat("detected"):
        return reject(REJ_STALE)
    if not out.reserve(records={"deposit_credited": 1}):
        return RETRY
    s.balance.available[d.asset_id] = std.checked_add(s.balance.available[d.asset_id], d.amount)
    d.status = std.cat("credited")
    out.emit_deposit_credited(ctx.t, trader_id=ctx.self_id, deposit_id=d.id, asset_id=d.asset_id,
                              amount=d.amount,
                              amount_usdt=ctx.reads.ref_price.to_usdt(d.asset_id, d.amount, ctx.t))
    return COMMIT


@kernel(state="trader", instance="withdrawal", max=Res(records={"withdrawal_approved": 1}))
def approve_withdrawal(ctx, s, w, cmd, out):
    if w.status != std.cat("pending"):
        return reject(REJ_STALE)
    if not out.reserve(records={"withdrawal_approved": 1}):
        return RETRY
    w.status = std.cat("approved")
    review = std.cat("auto") if ctx.t - w.requested_at < 2 * MINUTE else std.cat("manual")
    out.emit_withdrawal_approved(ctx.t, trader_id=ctx.self_id, withdrawal_id=w.id, review=review)
    return COMMIT


@kernel(state="trader", instance="withdrawal", max=Res(records={"withdrawal_rejected": 1}))
def reject_withdrawal(ctx, s, w, cmd, out):
    if w.status != std.cat("pending"):
        return reject(REJ_STALE)
    if not out.reserve(records={"withdrawal_rejected": 1}):
        return RETRY
    s.balance.held[w.asset_id] = std.checked_sub(s.balance.held[w.asset_id], w.amount)
    s.balance.available[w.asset_id] = std.checked_add(s.balance.available[w.asset_id], w.amount)
    w.status = std.cat("rejected")
    out.emit_withdrawal_rejected(ctx.t, trader_id=ctx.self_id, withdrawal_id=w.id,
                                 reason=ctx.rng.categorical(site=1, p=(.6, .3, .1)))
    return COMMIT


@kernel(state="trader", instance="withdrawal", max=Res(records={"withdrawal_sent": 1}))
def send_withdrawal(ctx, s, w, cmd, out):
    if w.status != std.cat("approved"):
        return reject(REJ_STALE)
    if not out.reserve(records={"withdrawal_sent": 1}):
        return RETRY
    s.balance.held[w.asset_id] = std.checked_sub(s.balance.held[w.asset_id], w.amount)
    w.status = std.cat("sent")
    out.accumulate("exchange_fees", w.asset_id, w.fee)  # network fee kept; net goes on chain
    out.emit_withdrawal_sent(ctx.t, trader_id=ctx.self_id, withdrawal_id=w.id,
                             asset_id=w.asset_id, amount=w.amount, fee=w.fee,
                             address_id=w.address_id)
    return COMMIT


@kernel(state="trader", max=Res(records={"kyc_upgraded": 1}))
def upgrade_kyc(ctx, s, cmd, out):
    """Exposed. Params: level."""
    if s.kyc_level >= cmd.level:
        return reject(REJ_STALE)
    if not out.reserve(records={"kyc_upgraded": 1}):
        return RETRY
    method = (std.cat("institutional") if s.segment == SEG_MM
              else ctx.rng.categorical(site=1, p=(.8, .2)))     # document, video
    out.emit_kyc_upgraded(ctx.t, trader_id=ctx.self_id, from_level=s.kyc_level,
                          to_level=cmd.level, method=method)
    s.kyc_level = cmd.level
    return COMMIT


@kernel(state="trader", max=Res(records={"api_key_created": 1}))
def create_api_key(ctx, s, cmd, out):
    """Exposed. No params."""
    if s.kyc_level < 1 or s.api_keys >= 5:
        return reject(REJ_KYC)
    if not out.reserve(records={"api_key_created": 1}):
        return RETRY
    s.api_keys += 1
    out.emit_api_key_created(ctx.t, trader_id=ctx.self_id, api_key_id=out.new_id("api_key"),
                             permissions=ctx.rng.categorical(site=1, p=(.15, .7, .15)),
                             ip_whitelist=ctx.rng.bernoulli(site=2, p=0.45))
    return COMMIT


# ================================================================== exposed actions
@kernel(state="trader", reads=("symbol", "ref_price"),
        max=Res(records={"order_submitted": 1}, creates={"order": 1}, requests=1, timers=1))
def place_order(ctx, s, cmd, out):
    """Exposed. Params: symbol, side, type, tif (GTC), post_only (False), price (0 on a limit
    = at the reference, shifted by offset_bps), qty | quote_qty | notional_usdt | share (of
    available), cancel_after (0 = never), channel (api). Same hold/request path as every base
    order, so overlay orders are indistinguishable in the event schema."""
    sy = ctx.reads.symbol
    sym, side, otype = cmd.symbol, cmd.side, cmd.type
    div, lot = sy.notional_div[sym], sy.lot[sym]
    price = 0
    if otype == LIMIT:
        price = cmd.price if cmd.price > 0 else std.shift_bps(
            ctx.reads.ref_price.at(sym, ctx.t), cmd.offset_bps,
            round="down" if side == BUY else "up")
    qty, qbudget = cmd.qty, cmd.quote_qty
    if qty == 0 and qbudget == 0 and cmd.notional_usdt > 0:
        spend = ctx.reads.ref_price.from_usdt(sy.quote[sym], cmd.notional_usdt * PPM, ctx.t)
        if side == BUY and otype == MARKET:
            qbudget = spend
        else:
            px = price if price > 0 else ctx.reads.ref_price.at(sym, ctx.t)
            qty = std.checked_muldiv(spend, div, px) // lot * lot
    elif qty == 0 and qbudget == 0 and cmd.share > 0:
        if side == SELL:
            qty = std.share_of(s.balance.available[sy.base[sym]], cmd.share) // lot * lot
        elif otype == MARKET:
            qbudget = std.share_of(s.balance.available[sy.quote[sym]], cmd.share)
        else:
            spend = std.share_of(s.balance.available[sy.quote[sym]], cmd.share)
            qty = std.checked_muldiv(spend, div, price) // lot * lot
    lock_asset, lock = _lock_for(ctx, sym, side, otype, price, qty, qbudget)
    if lock <= 0 or lock > s.balance.available[lock_asset]:
        return reject(REJ_FUNDS)
    if not out.reserve(records={"order_submitted": 1}, creates={"order": 1}, requests=1,
                       timers=1 if cmd.cancel_after > 0 else 0):
        return RETRY
    fee_m, fee_t = _fees(s, ctx.cfg_of("trader_activity"))
    order = _submit(ctx, s, out, sym, side, otype, cmd.tif, cmd.post_only, price, qty, qbudget,
                    lock_asset, lock, fee_m, fee_t, cmd.channel,
                    ctx.refs.device.last(ctx.self_id), ctx.refs.ip.last(ctx.self_id))
    if cmd.cancel_after > 0:
        out.timer(ctx.t + cmd.cancel_after, C_PATIENCE, prio=PRIO_TIMER, tag=order,
                  to="order_settlement")
    return COMMIT


@kernel(state="trader", max=Res(requests=1))
def cancel_order(ctx, s, cmd, out):
    """Exposed. Params: order (0 = this account's most recent open order)."""
    o = s.order.get(cmd.order) if cmd.order != 0 else s.order.last_open()
    if o is None or o.status != ST_OPEN or o.cancel_pending:
        return reject(REJ_STALE)
    if not out.reserve(requests=1):
        return RETRY
    out.request_cancel(ctx.t, shard=o.symbol_id, order_id=o.id, trader_id=ctx.self_id)
    o.cancel_pending = True
    return COMMIT


@kernel(state="trader", reads=("asset", "ref_price"),
        max=Res(records={"deposit_detected": 1}, creates={"deposit": 1}))
def deposit(ctx, s, cmd, out):
    """Exposed. Params: asset, amount | amount_usdt, address (0 = one of the account's own)."""
    amount = cmd.amount if cmd.amount > 0 else ctx.reads.ref_price.from_usdt(
        cmd.asset, cmd.amount_usdt, ctx.t)
    if amount <= 0:
        return reject(REJ_FUNDS)
    if not out.reserve(records={"deposit_detected": 1}, creates={"deposit": 1}):
        return RETRY
    address = cmd.address if cmd.address != 0 else ctx.refs.address.pick(
        ctx.self_id, ctx.rng.uniform(site=1))
    _detect(ctx, s, out, cmd.asset, amount, address)
    return COMMIT


@kernel(state="trader", reads=("asset", "ref_price"),
        max=Res(records={"withdrawal_requested": 1}, creates={"withdrawal": 1}))
def withdraw(ctx, s, cmd, out):
    """Exposed. Params: asset, amount | share (of available), address (0 = own)."""
    avail = s.balance.available[cmd.asset]
    amount = cmd.amount if cmd.amount > 0 else std.share_of(avail, cmd.share)
    limit = ctx.reads.ref_price.from_usdt(
        cmd.asset, ctx.cfg_of("funding").withdraw_limit_usdt[s.kyc_level] * PPM, ctx.t)
    if amount > avail or amount <= ctx.reads.asset.withdraw_fee[cmd.asset]:
        return reject(REJ_FUNDS)
    if amount > limit:
        return reject(REJ_LIMIT)
    if not out.reserve(records={"withdrawal_requested": 1}, creates={"withdrawal": 1}):
        return RETRY
    address = cmd.address if cmd.address != 0 else ctx.refs.address.pick(
        ctx.self_id, ctx.rng.uniform(site=1))
    _request_withdrawal(ctx, s, out, cmd.asset, amount, address,
                        ctx.refs.device.last(ctx.self_id), ctx.refs.ip.last(ctx.self_id))
    return COMMIT


# Thin actions exposed to overlays. Each is a std recipe bound to this pack's events.
register = std.action.emit_signup("trader_registered")
login = std.action.emit("login", channel="web")


# ================================================================== book shard: matching
@kernel(state="book", commands=MATCH_COMMANDS, substep=FILLS,
        max=Res(records={"order_accepted": 1, "order_rejected": 1, "trade": FILLS,
                         "order_filled": FILLS + 1, "order_cancelled": FILLS + 1,
                         "cancel_rejected": 1},
                responses=1, messages=MAX_NOTIFY, timers=1))
def match(ctx, s, cmd, out):
    """Price/time matching for one symbol. A taker touches at most FILLS makers per invocation,
    then continues at the same time and top priority, so no other command interleaves and the
    result never depends on buffer sizes."""
    cfg = ctx.cfg
    if cmd.kind == Q_PLACE:
        return _place(ctx, s, cmd, out, cfg)
    if cmd.kind == Q_CANCEL:
        return _cancel(ctx, s, cmd, out)
    if cmd.kind == C_CONTINUE:
        if not s.tk.active:
            return reject(REJ_STALE)
        if not _reserve_substep(out):
            return RETRY
        _run_fills(ctx, s, out, cfg)
        return COMMIT
    return reject(REJ_STALE)


def _reserve_substep(out):
    return out.reserve(records={"order_accepted": 1, "trade": FILLS, "order_filled": FILLS + 1,
                                "order_cancelled": FILLS + 1},
                       responses=1, messages=MAX_NOTIFY, timers=1)


def _crosses(side, limit, maker_price):
    return maker_price <= limit if side == BUY else maker_price >= limit


def _validate(ctx, s, cmd, cfg):
    """Read-only. Returns -1 if acceptable, else the order_rejected reason."""
    sy, sym = ctx.reads.symbol, ctx.self_id
    lot, div = sy.lot[sym], sy.notional_div[sym]
    ref = ctx.reads.ref_price.at(sym, ctx.t)
    if cmd.type == LIMIT:
        if abs(cmd.price - ref) > ref * cfg.price_band:
            return std.cat("price_band")
        if cmd.qty <= 0 or cmd.qty % lot != 0:
            return std.cat("lot_size")
        if std.checked_muldiv(cmd.price, cmd.qty, div) < sy.min_notional[sym]:
            return std.cat("min_notional")
        if cmd.post_only:
            best = s.levels.best(1 - cmd.side)
            if best >= 0 and _crosses(cmd.side, cmd.price, s.levels.price[best]):
                return std.cat("post_only_would_cross")
        if cmd.tif == GTC and s.levels.count >= s.levels.cap:
            return std.cat("book_full")
        return -1
    if cmd.tif == FOK:
        return std.cat("fok_quote_budget")             # FOK needs a base qty and a limit
    if cmd.side == BUY:
        return std.cat("min_notional") if cmd.quote_qty < sy.min_notional[sym] else -1
    if cmd.qty <= 0 or cmd.qty % lot != 0:
        return std.cat("lot_size")
    if std.checked_muldiv(ref, cmd.qty, div) < sy.min_notional[sym]:
        return std.cat("min_notional")
    return -1


def _fok_preflight(ctx, s, cmd, cfg):
    """Read-only walk of the opposite side: can cmd.qty fill in full at or better than the
    limit, honoring self-trade prevention? Runs before the first fill (design 05)."""
    need = cmd.qty
    slot = s.levels.best(1 - cmd.side)
    while slot >= 0 and need > 0 and _crosses(cmd.side, cmd.price, s.levels.price[slot]):
        if cfg.stp_mode != STP_OFF and s.levels.stp_id[slot] == cmd.stp_id:
            if cfg.stp_mode != STP_CANCEL_MAKER:
                return False                           # the taker itself would be cancelled
        else:
            need -= s.levels.left[slot]
        slot = s.levels.next(slot)
    return need <= 0


def _place(ctx, s, cmd, out, cfg):
    sym = ctx.self_id
    reason = _validate(ctx, s, cmd, cfg)
    if reason >= 0:
        if not out.reserve(records={"order_rejected": 1}, responses=1):
            return RETRY
        out.emit_order_rejected(ctx.t, symbol_id=sym, order_id=cmd.order_id,
                                trader_id=cmd.trader_id, reason=reason)
        out.respond(cmd, "rejected", reason=reason)       # trader releases the whole lock
        return COMMIT
    killed = cmd.tif == FOK and not _fok_preflight(ctx, s, cmd, cfg)
    if not _reserve_substep(out):
        return RETRY
    s.seq += 1
    out.emit_order_accepted(ctx.t, symbol_id=sym, order_id=cmd.order_id, trader_id=cmd.trader_id,
                            side=cmd.side, type=cmd.type, tif=cmd.tif, post_only=cmd.post_only,
                            price=cmd.price, qty=cmd.qty, quote_qty=cmd.quote_qty,
                            book_seq=s.seq)
    out.respond(cmd, "accepted", book_seq=s.seq)          # FIFO: arrives before any fill
    if killed:
        out.emit_order_cancelled(ctx.t, symbol_id=sym, order_id=cmd.order_id,
                                 trader_id=cmd.trader_id, reason=std.cat("fok_killed"),
                                 filled_qty=0)
        out.send_done(ctx.t, to=cmd.trader_id, order_id=cmd.order_id, status=ST_CANCELLED,
                        release=cmd.lock)
        return COMMIT
    _load_taker(ctx, s, cmd, cfg)
    if cfg.fidelity == EXTERNAL:
        _finish_taker(ctx, s, out, _fill_external(ctx, s, out, cfg))
        return COMMIT
    _run_fills(ctx, s, out, cfg)
    return COMMIT


def _load_taker(ctx, s, cmd, cfg):
    tk = s.tk
    ref = ctx.reads.ref_price.at(ctx.self_id, ctx.t)
    tk.active, tk.order_id, tk.trader_id, tk.stp_id = True, cmd.order_id, cmd.trader_id, cmd.stp_id
    tk.side, tk.type, tk.tif = cmd.side, cmd.type, cmd.tif
    if cmd.type == MARKET:                             # collar stands in for the limit
        bps = cfg.market_collar * 10_000
        tk.price = (std.shift_bps(ref, bps, round="up") if cmd.side == BUY
                    else std.shift_bps(ref, -bps, round="down"))
    else:
        tk.price = cmd.price
    tk.budget = cmd.type == MARKET and cmd.side == BUY  # spend quote_qty, not a base qty
    tk.qty = cmd.qty
    tk.left = cmd.qty if not tk.budget else std.I64_MAX
    tk.lock, tk.filled = cmd.lock, 0
    tk.fee_maker_ppm, tk.fee_taker_ppm, tk.seq = cmd.fee_maker_ppm, cmd.fee_taker_ppm, s.seq


def _run_fills(ctx, s, out, cfg):
    """At most FILLS maker touches (fills or STP cancels), then continue or finish."""
    tk, lv = s.tk, s.levels
    n, stop = 0, STOP_NONE
    while n < FILLS:
        slot = lv.best(1 - tk.side)
        if slot < 0 or not _crosses(tk.side, tk.price, lv.price[slot]):
            stop = STOP_NO_LIQUIDITY
            break
        if cfg.stp_mode != STP_OFF and lv.stp_id[slot] == tk.stp_id:
            if cfg.stp_mode == STP_CANCEL_TAKER:
                stop = STOP_STP
                break
            _close_maker(ctx, s, out, slot, std.cat("stp"))      # cancel_maker / cancel_both
            n += 1
            if cfg.stp_mode == STP_CANCEL_BOTH:
                stop = STOP_STP
                break
            continue
        qty = _fill_qty(ctx, s, slot)
        if qty == 0:
            stop = STOP_DONE                           # quote budget can't buy one more lot
            break
        _fill(ctx, s, out, slot, qty)
        n += 1
        if tk.left == 0:
            stop = STOP_DONE
            break
    if stop == STOP_NONE:
        out.continue_at(ctx.t, cursor=n)               # same time, top priority
        return
    _finish_taker(ctx, s, out, stop)


def _fill_qty(ctx, s, slot):
    tk, lv, sy, sym = s.tk, s.levels, ctx.reads.symbol, ctx.self_id
    if tk.budget:
        lot = sy.lot[sym]
        afford = std.checked_muldiv(tk.lock, sy.notional_div[sym], lv.price[slot]) // lot * lot
        return min(afford, lv.left[slot])
    return min(tk.left, lv.left[slot])


def _fill(ctx, s, out, slot, qty):
    """One trade at the maker's price. Fees are charged in the asset each side receives."""
    tk, lv, sy, sym = s.tk, s.levels, ctx.reads.symbol, ctx.self_id
    price = lv.price[slot]
    quote = std.checked_muldiv(price, qty, sy.notional_div[sym])
    taker_buys = tk.side == BUY
    buyer_ppm = tk.fee_taker_ppm if taker_buys else lv.fee_maker_ppm[slot]
    seller_ppm = lv.fee_maker_ppm[slot] if taker_buys else tk.fee_taker_ppm
    buyer_fee = std.checked_muldiv(qty, buyer_ppm, PPM, round="ceil")
    seller_fee = std.checked_muldiv(quote, seller_ppm, PPM, round="ceil")
    tk_used = quote if taker_buys else qty             # the buy side's lock is quote
    mk_used = qty if taker_buys else quote
    tk.lock = std.checked_sub(tk.lock, tk_used)
    tk.left = std.checked_sub(tk.left, qty)
    tk.filled = std.checked_add(tk.filled, qty)
    lv.lock[slot] = std.checked_sub(lv.lock[slot], mk_used)
    lv.left[slot] = std.checked_sub(lv.left[slot], qty)
    s.last_price = price
    s.seq += 1
    trade = out.new_id("trade")
    out.emit_trade(ctx.t, symbol_id=sym, trade_id=trade, price=price, qty=qty, quote_amount=quote,
                   notional_usdt=ctx.reads.ref_price.to_usdt(sy.quote[sym], quote, ctx.t),
                   taker_side=tk.side, taker_order_id=tk.order_id, taker_trader_id=tk.trader_id,
                   maker_order_id=lv.order_id[slot], maker_trader_id=lv.trader_id[slot],
                   buyer_fee=buyer_fee, seller_fee=seller_fee, liquidity=std.cat("book"),
                   book_seq=s.seq)
    out.send_fill(ctx.t, to=tk.trader_id, order_id=tk.order_id, trade_id=trade,
                    side=tk.side, qty=qty, quote=quote,
                    fee=buyer_fee if taker_buys else seller_fee, lock_used=tk_used)
    out.send_fill(ctx.t, to=lv.trader_id[slot], order_id=lv.order_id[slot], trade_id=trade,
                    side=1 - tk.side, qty=qty, quote=quote,
                    fee=seller_fee if taker_buys else buyer_fee, lock_used=mk_used)
    if lv.left[slot] == 0:
        out.emit_order_filled(ctx.t, symbol_id=sym, order_id=lv.order_id[slot],
                              trader_id=lv.trader_id[slot], role=std.cat("maker"),
                              filled_qty=lv.qty[slot])
        out.send_done(ctx.t, to=lv.trader_id[slot], order_id=lv.order_id[slot],
                        status=ST_FILLED, release=lv.lock[slot])   # rounding dust on buys
        lv.remove(slot)


def _close_maker(ctx, s, out, slot, reason):
    lv = s.levels
    out.emit_order_cancelled(ctx.t, symbol_id=ctx.self_id, order_id=lv.order_id[slot],
                             trader_id=lv.trader_id[slot], reason=reason,
                             filled_qty=lv.qty[slot] - lv.left[slot])
    out.send_done(ctx.t, to=lv.trader_id[slot], order_id=lv.order_id[slot],
                    status=ST_CANCELLED, release=lv.lock[slot])
    lv.remove(slot)


def _finish_taker(ctx, s, out, stop):
    """Filled, rest (GTC limit with a remainder), or cancel the remainder."""
    tk, sym = s.tk, ctx.self_id
    if stop == STOP_DONE:
        out.emit_order_filled(ctx.t, symbol_id=sym, order_id=tk.order_id,
                              trader_id=tk.trader_id, role=std.cat("taker"), filled_qty=tk.filled)
        out.send_done(ctx.t, to=tk.trader_id, order_id=tk.order_id, status=ST_FILLED,
                        release=tk.lock)
    elif stop == STOP_NO_LIQUIDITY and tk.type == LIMIT and tk.tif == GTC:
        s.levels.insert(tk.side, tk.price, order_id=tk.order_id, trader_id=tk.trader_id,
                        stp_id=tk.stp_id, qty=tk.qty, left=tk.left, lock=tk.lock,
                        fee_maker_ppm=tk.fee_maker_ppm, seq=tk.seq)   # stays open; no event
    else:
        reason = (std.cat("stp") if stop == STOP_STP
                  else std.cat("market_no_liquidity") if tk.type == MARKET
                  else std.cat("ioc_remainder"))
        out.emit_order_cancelled(ctx.t, symbol_id=sym, order_id=tk.order_id,
                                 trader_id=tk.trader_id, reason=reason, filled_qty=tk.filled)
        out.send_done(ctx.t, to=tk.trader_id, order_id=tk.order_id, status=ST_CANCELLED,
                        release=tk.lock)
    tk.active = False


def _cancel(ctx, s, cmd, out):
    sym, lv = ctx.self_id, s.levels
    slot = lv.find(cmd.order_id)
    if not out.reserve(records={"order_cancelled": 1, "cancel_rejected": 1}, responses=1,
                       messages=1):
        return RETRY
    if slot < 0 or lv.trader_id[slot] != cmd.trader_id:
        reason = std.cat("unknown_order") if slot < 0 else std.cat("not_owner")
        out.emit_cancel_rejected(ctx.t, symbol_id=sym, order_id=cmd.order_id,
                                 trader_id=cmd.trader_id, reason=reason)
        out.respond(cmd, "cancel_rejected")               # filled or closed while in flight
        return COMMIT
    _close_maker(ctx, s, out, slot, std.cat("user"))   # done (release) precedes the response
    out.respond(cmd, "cancelled")
    return COMMIT


# ------------------------------------------------------------------ external_liquidity mode
def _external_px(ctx, cfg, side, notional_usdt):
    sy, sym = ctx.reads.symbol, ctx.self_id
    tier = sy.tier[sym]
    ref = ctx.reads.ref_price.at(sym, ctx.t)
    depth = cfg.external_depth_usdt[tier] * PPM
    bps = cfg.external_half_spread_bps[tier] * (1.0 + notional_usdt / depth)
    return std.shift_bps(ref, bps, round="up") if side == BUY else std.shift_bps(ref, -bps,
                                                                                 round="down")


def _fill_external(ctx, s, out, cfg):
    """Taker fills in full against an exogenous liquidity curve (no counterparty trader); the
    other leg goes to the external_flow accumulator. Limits that don't reach it rest."""
    tk, sy, sym = s.tk, ctx.reads.symbol, ctx.self_id
    div, lot, base, quote = sy.notional_div[sym], sy.lot[sym], sy.base[sym], sy.quote[sym]
    est = (ctx.reads.ref_price.to_usdt(quote, tk.lock, ctx.t) if tk.side == BUY
           else ctx.reads.ref_price.to_usdt(base, tk.lock, ctx.t))
    px = _external_px(ctx, cfg, tk.side, est)
    if not _crosses(tk.side, tk.price, px):
        return STOP_NO_LIQUIDITY
    qty = (std.checked_muldiv(tk.lock, div, px) // lot * lot) if tk.budget else tk.left
    if qty == 0:
        return STOP_DONE
    quote_amt = std.checked_muldiv(px, qty, div)
    taker_buys = tk.side == BUY
    fee = (std.checked_muldiv(qty, tk.fee_taker_ppm, PPM, round="ceil") if taker_buys
           else std.checked_muldiv(quote_amt, tk.fee_taker_ppm, PPM, round="ceil"))
    used = quote_amt if taker_buys else qty
    tk.lock = std.checked_sub(tk.lock, used)
    tk.left = std.checked_sub(tk.left, qty)
    tk.filled = std.checked_add(tk.filled, qty)
    s.last_price = px
    s.seq += 1
    trade = out.new_id("trade")
    out.emit_trade(ctx.t, symbol_id=sym, trade_id=trade, price=px, qty=qty,
                   quote_amount=quote_amt,
                   notional_usdt=ctx.reads.ref_price.to_usdt(quote, quote_amt, ctx.t),
                   taker_side=tk.side, taker_order_id=tk.order_id, taker_trader_id=tk.trader_id,
                   maker_order_id=0, maker_trader_id=0,
                   buyer_fee=fee if taker_buys else 0, seller_fee=0 if taker_buys else fee,
                   liquidity=std.cat("external"), book_seq=s.seq)
    out.send_fill(ctx.t, to=tk.trader_id, order_id=tk.order_id, trade_id=trade,
                    side=tk.side, qty=qty, quote=quote_amt, fee=fee, lock_used=used)
    out.accumulate("external_flow", base, -qty if taker_buys else qty)
    out.accumulate("external_flow", quote, quote_amt if taker_buys else -quote_amt)
    return STOP_DONE


# ================================================================== book shard: ticker
@kernel(state="book", substep=FILLS,
        max=Res(records={"book_ticker": 1, "trade": FILLS, "order_filled": FILLS},
                messages=2 * FILLS, timers=1))
def ticker(ctx, s, cmd, out):
    """Every minute: one top-of-book sample. In external_liquidity mode, also fills resting
    orders the reference price has crossed, FILLS per sub-step with a same-time continuation."""
    cfg, lv, sym = ctx.cfg, s.levels, ctx.self_id
    if not out.reserve(records={"book_ticker": 1 if cmd.cursor == 0 else 0, "trade": FILLS,
                                "order_filled": FILLS}, messages=2 * FILLS, timers=1):
        return RETRY
    if cmd.cursor == 0:
        bid, ask = lv.best(BUY), lv.best(SELL)
        bp = lv.price[bid] if bid >= 0 else 0
        ap = lv.price[ask] if ask >= 0 else 0
        out.emit_book_ticker(ctx.t, symbol_id=sym, best_bid=bp, best_ask=ap,
                             bid_qty=lv.qty_at(BUY, bp) if bid >= 0 else 0,
                             ask_qty=lv.qty_at(SELL, ap) if ask >= 0 else 0,
                             spread_bps=std.spread_bps(bp, ap),      # null if a side is empty
                             ref_price=ctx.reads.ref_price.at(sym, ctx.t),
                             last_price=s.last_price, resting_orders=lv.count)
    if cfg.fidelity != EXTERNAL:
        return COMMIT
    n = 0
    while n < FILLS:
        if not _sweep_one(ctx, s, out, cfg):
            return COMMIT
        n += 1
    out.continue_at(ctx.t, cursor=cmd.cursor + n)
    return COMMIT


def _sweep_one(ctx, s, out, cfg):
    """Fill the best resting order the external curve now crosses, in full, at its limit."""
    lv, sy, sym = s.levels, ctx.reads.symbol, ctx.self_id
    for side in (BUY, SELL):
        slot = lv.best(side)
        if slot < 0:
            continue
        ext = _external_px(ctx, cfg, 1 - side, 0.0)
        if not _crosses(side, lv.price[slot], ext):
            continue
        qty, price = lv.left[slot], lv.price[slot]
        quote = std.checked_muldiv(price, qty, sy.notional_div[sym])
        fee = std.checked_muldiv(qty if side == BUY else quote, lv.fee_maker_ppm[slot], PPM,
                                 round="ceil")
        used = quote if side == BUY else qty
        lv.lock[slot] = std.checked_sub(lv.lock[slot], used)
        s.last_price = price
        s.seq += 1
        trade = out.new_id("trade")
        out.emit_trade(ctx.t, symbol_id=sym, trade_id=trade, price=price, qty=qty,
                       quote_amount=quote,
                       notional_usdt=ctx.reads.ref_price.to_usdt(sy.quote[sym], quote, ctx.t),
                       taker_side=1 - side, taker_order_id=0, taker_trader_id=0,
                       maker_order_id=lv.order_id[slot], maker_trader_id=lv.trader_id[slot],
                       buyer_fee=fee if side == BUY else 0, seller_fee=0 if side == BUY else fee,
                       liquidity=std.cat("external"), book_seq=s.seq)
        out.send_fill(ctx.t, to=lv.trader_id[slot], order_id=lv.order_id[slot],
                        trade_id=trade, side=side, qty=qty, quote=quote, fee=fee, lock_used=used)
        out.emit_order_filled(ctx.t, symbol_id=sym, order_id=lv.order_id[slot],
                              trader_id=lv.trader_id[slot], role=std.cat("maker"),
                              filled_qty=lv.qty[slot])
        out.send_done(ctx.t, to=lv.trader_id[slot], order_id=lv.order_id[slot],
                        status=ST_FILLED, release=lv.lock[slot])
        out.accumulate("external_flow", sy.base[sym], qty if side == BUY else -qty)
        out.accumulate("external_flow", sy.quote[sym], -quote if side == BUY else quote)
        lv.remove(slot)
        return True
    return False
