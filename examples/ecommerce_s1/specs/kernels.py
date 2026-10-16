"""Handwritten kernels for the S1 e-commerce slice.

Every kernel: validate (draws allowed, no writes) -> out.reserve(...) -> commit.
Each random draw has its own site number.
"""

from neorisk_simkit import std
from neorisk_simkit.engine import (
    COMMIT,
    PRIO_EXPIRY,
    PRIO_TIMER,
    RETRY,
    START,
    Local,
    Res,
    kernel,
    reject,
)

C_SESSION, C_VIEW, C_CHECKOUT, C_AUTH, R_GRANTED, R_REJECTED = 1, 2, 3, 4, 5, 6
C_KYC_REDEEM, C_KYC_EXPIRE, C_KYC_FACE = 7, 8, 9
SHOPPER_COMMANDS = (START, C_SESSION, C_VIEW, C_CHECKOUT, C_AUTH, R_GRANTED, R_REJECTED,
                    C_KYC_REDEEM, C_KYC_EXPIRE, C_KYC_FACE)
C_RESERVE, C_COMMIT, C_RELEASE = 1, 2, 3

REJ_DORMANT, REJ_NO_CART, REJ_STALE, REJ_BUSY, REJ_KYC_STATE = 1, 2, 3, 4, 5

SHOPPER_LOCAL = Local(session="ref", device="ref", views_left="i16", cart_sku="ref",
                      cart_qty="i16", cart_price="i64", cart_n="i8", checkout="ref",
                      kyc_flow="ref", kyc_session="ref", kyc_desktop="ref", kyc_phone="ref",
                      kyc_expires="i64", kyc_status="i8")


@kernel(state="user", local=SHOPPER_LOCAL, commands=SHOPPER_COMMANDS,
        max=Res(records={"user_signed_up": 1, "session_started": 1, "product_viewed": 1,
                         "cart_item_added": 1, "checkout_started": 1, "checkout_failed": 1,
                         "payment_authorized": 1, "payment_failed": 1, "order_placed": 1,
                         "kyc_started": 1, "kyc_handoff_redeemed": 1, "kyc_handoff_rejected": 1,
                         "kyc_handoff_expired": 1, "kyc_completed": 1, "user_kyc": 1},
                creates={"order": 1, "session": 1, "checkout": 1, "flow": 1}, timers=5,
                requests=1))
def shopper(ctx, s, loc, cmd, out):
    cfg = ctx.cfg
    if cmd.kind == START:
        return _signup(ctx, s, out, cfg)
    if cmd.kind == C_SESSION:
        return _session(ctx, s, loc, out, cfg)
    if cmd.kind == C_VIEW:
        return _view(ctx, loc, out, cfg)
    if cmd.kind == C_CHECKOUT:
        return _checkout(ctx, loc, out)
    if cmd.kind == R_GRANTED:
        return _granted(ctx, loc, cmd, out, cfg)
    if cmd.kind == R_REJECTED:
        return _rejected(ctx, loc, cmd, out, cfg)
    if cmd.kind == C_KYC_REDEEM:
        return _kyc_redeem(ctx, loc, cmd, out, cfg)
    if cmd.kind == C_KYC_EXPIRE:
        return _kyc_expire(ctx, loc, cmd, out)
    if cmd.kind == C_KYC_FACE:
        return _kyc_face(ctx, s, loc, cmd, out)
    return _auth(ctx, loc, cmd, out, cfg)


def _signup(ctx, s, out, cfg):
    delay = ctx.rng.dist_us(site=1, d=cfg.signup_delay)
    if not out.reserve(records={"user_signed_up": 1}, timers=1):
        return RETRY
    out.emit_user_signed_up(ctx.t, user_id=ctx.self_id,
                            device_id=ctx.refs.device.get(ctx.self_id, 0),
                            acquisition=s.acquisition, age_band=s.age_band)
    out.timer(ctx.t + delay, C_SESSION, prio=PRIO_TIMER)
    return COMMIT


def _channel(ctx, device):
    if ctx.reads.device.kind[device] == "desktop":
        return 0                                           # web
    return 1                                               # app


def _session(ctx, s, loc, out, cfg):
    if s.status != "active":
        return reject(REJ_DORMANT)
    n_dev = ctx.refs.device.count(ctx.self_id)
    dev = ctx.refs.device.get(ctx.self_id, ctx.rng.uniform_int(site=2, lo=0, hi=n_dev - 1))
    views = min(ctx.rng.geometric(site=3, mean=cfg.views_mean), 30)   # 1-30 views
    gap = ctx.rng.pareto_us(site=4, alpha=cfg.session_gap_alpha, min_h=cfg.session_gap_min_h)
    first = ctx.rng.dist_us(site=5, d=cfg.view_gap)
    phone = _first_phone(ctx)
    kyc = (s.kyc_level == 0 and loc.kyc_status == std.handoff.NONE
           and ctx.reads.device.kind[dev] == "desktop" and phone != std.NULL
           and ctx.rng.bernoulli(site=50, p=cfg.kyc_start_p))
    expires = ctx.t + cfg.kyc_expiry_s * 1_000_000
    redeem_at = expires
    again_at = std.NULL                                    # NULL: no duplicate scan
    if kyc:                                                # draws only for a flow that starts
        if not ctx.rng.bernoulli(site=51, p=cfg.kyc_late_scan_p):
            redeem_at = ctx.t + ctx.rng.dist_us(site=52, d=cfg.kyc_redeem_delay)
        if ctx.rng.bernoulli(site=53, p=cfg.kyc_duplicate_p):
            again_at = redeem_at + ctx.rng.dist_us(site=54, d=cfg.kyc_duplicate_gap)
    if not out.reserve(records={"session_started": 1, "kyc_started": 1},
                       creates={"session": 1, "flow": 1}, timers=5):
        return RETRY
    loc.session = out.new_id("session")
    loc.device = dev
    loc.views_left = views
    out.emit_session_started(ctx.t, user_id=ctx.self_id, session_id=loc.session, device_id=dev,
                             channel=_channel(ctx, dev))
    out.timer(ctx.t + first, C_VIEW, prio=PRIO_TIMER)
    out.timer(ctx.t + gap, C_SESSION, prio=PRIO_TIMER)
    if kyc:
        _kyc_start(ctx, loc, out, dev, phone, expires, redeem_at, again_at)
    return COMMIT


def _first_phone(ctx):
    """The user's first device of kind phone, or NULL."""
    for i in range(ctx.refs.device.count(ctx.self_id)):
        d = ctx.refs.device.get(ctx.self_id, i)
        if ctx.reads.device.kind[d] == "phone":
            return d
    return std.NULL


def _kyc_start(ctx, loc, out, desktop, phone, expires, redeem_at, again_at):
    """Open a handoff flow on the desktop session (D28); runs after _session's reserve.

    A scan at `redeem_at == expires` runs after the expiry (PRIO_EXPIRY < PRIO_TIMER) and is
    rejected as expired (§06)."""
    loc.kyc_flow = out.new_id("flow")
    loc.kyc_session = loc.session
    loc.kyc_desktop = desktop
    loc.kyc_phone = phone
    loc.kyc_expires = expires
    loc.kyc_status = std.handoff.OPEN
    out.emit_kyc_started(ctx.t, user_id=ctx.self_id, flow_id=loc.kyc_flow,
                         session_id=loc.session, device_id=desktop, expires_at=expires)
    out.timer(expires, C_KYC_EXPIRE, prio=PRIO_EXPIRY, tag=loc.kyc_flow)
    out.timer(redeem_at, C_KYC_REDEEM, prio=PRIO_TIMER, tag=loc.kyc_flow)
    if again_at != std.NULL:
        out.timer(again_at, C_KYC_REDEEM, prio=PRIO_TIMER, tag=loc.kyc_flow)


def _kyc_expire(ctx, loc, cmd, out):
    if cmd.tag != loc.kyc_flow:
        return reject(REJ_STALE)
    status = std.handoff.expire(loc.kyc_status)
    if status == loc.kyc_status:                           # already redeemed: nothing expires
        return reject(REJ_KYC_STATE)
    if not out.reserve(records={"kyc_handoff_expired": 1}):
        return RETRY
    loc.kyc_status = status
    out.emit_kyc_handoff_expired(ctx.t, user_id=ctx.self_id, flow_id=loc.kyc_flow)
    return COMMIT


def _kyc_redeem(ctx, loc, cmd, out, cfg):
    outcome = std.handoff.redeem(loc.kyc_status, loc.kyc_expires, ctx.t, loc.kyc_flow, cmd.tag)
    if outcome == std.handoff.REJ_UNKNOWN:
        return reject(REJ_STALE)
    delay = ctx.rng.dist_us(site=55, d=cfg.kyc_face_delay)
    if not out.reserve(records={"kyc_handoff_redeemed": 1, "kyc_handoff_rejected": 1},
                       timers=1):
        return RETRY
    if outcome == std.handoff.OK:
        loc.kyc_status = std.handoff.REDEEMED
        out.emit_kyc_handoff_redeemed(ctx.t, user_id=ctx.self_id, flow_id=loc.kyc_flow,
                                      device_id=loc.kyc_phone)
        out.timer(ctx.t + delay, C_KYC_FACE, prio=PRIO_TIMER, tag=loc.kyc_flow)
    elif outcome == std.handoff.REJ_EXPIRED:
        out.emit_kyc_handoff_rejected(ctx.t, user_id=ctx.self_id, flow_id=loc.kyc_flow,
                                      device_id=loc.kyc_phone, reason="expired")
    else:
        out.emit_kyc_handoff_rejected(ctx.t, user_id=ctx.self_id, flow_id=loc.kyc_flow,
                                      device_id=loc.kyc_phone, reason="already_redeemed")
    return COMMIT


def _kyc_face(ctx, s, loc, cmd, out):
    if cmd.tag != loc.kyc_flow:
        return reject(REJ_STALE)
    if loc.kyc_status != std.handoff.REDEEMED:
        return reject(REJ_KYC_STATE)
    if not out.reserve(records={"kyc_completed": 1, "user_kyc": 1}):
        return RETRY
    loc.kyc_status = std.handoff.DONE
    out.emit_kyc_completed(ctx.t, user_id=ctx.self_id, flow_id=loc.kyc_flow,
                           session_id=loc.kyc_session, device_id=loc.kyc_desktop,
                           scan_device_id=loc.kyc_phone)
    out.change_user_kyc(ctx.t, kyc_level=1, kyc_device=loc.kyc_phone)
    return COMMIT


def _view(ctx, loc, out, cfg):
    if loc.views_left <= 0:                                # session over: maybe check out
        if loc.cart_n == 0 or loc.checkout != std.NULL:
            return reject(REJ_NO_CART)
        if not ctx.rng.bernoulli(site=10, p=cfg.checkout_p):
            return reject(REJ_NO_CART)
        delay = ctx.rng.dist_us(site=11, d=cfg.checkout_delay)
        if not out.reserve(timers=1):
            return RETRY
        out.timer(ctx.t + delay, C_CHECKOUT, prio=PRIO_TIMER)
        return COMMIT
    sku = ctx.reads.sku.sample_by_weight(ctx.rng.uniform(site=12))
    add = ctx.rng.bernoulli(site=13, p=cfg.add_to_cart_p)
    qty = ctx.rng.geometric(site=14, mean=1.25)          # >= 1, mean 1.25
    pos = ctx.rng.geometric(site=15, mean=5.0)
    src = ctx.rng.categorical(site=16, p=(0.25, 0.35, 0.2, 0.2))
    referrer = ctx.rng.categorical(site=17, p=(0.7, 0.1, 0.12, 0.08))
    page_ms = 200 + ctx.rng.geometric(site=18, mean=800.0)
    nxt = ctx.rng.dist_us(site=19, d=cfg.view_gap)
    if not out.reserve(records={"product_viewed": 1, "cart_item_added": 1}, timers=1):
        return RETRY
    out.emit_product_viewed(ctx.t, user_id=ctx.self_id, session_id=loc.session, sku_id=sku,
                            device_id=loc.device, position=pos, source=src,
                            channel=_channel(ctx, loc.device),
                            category=ctx.reads.sku.category[sku], price=ctx.reads.sku.price[sku],
                            page_ms=page_ms, referrer=referrer, is_recommended=src == 3)
    if add and loc.checkout == std.NULL:                   # one-line cart (D27)
        loc.cart_sku = sku
        loc.cart_qty = qty
        loc.cart_price = ctx.reads.sku.price[sku]
        loc.cart_n = 1
        out.emit_cart_item_added(ctx.t, user_id=ctx.self_id, session_id=loc.session, sku_id=sku,
                                 quantity=qty, unit_price=loc.cart_price)
    loc.views_left -= 1
    out.timer(ctx.t + nxt, C_VIEW, prio=PRIO_TIMER)
    return COMMIT


def _checkout(ctx, loc, out):
    if loc.cart_n == 0 or loc.checkout != std.NULL:
        return reject(REJ_BUSY)
    if not out.reserve(records={"checkout_started": 1}, creates={"checkout": 1}, requests=1):
        return RETRY
    loc.checkout = out.new_id("checkout")
    out.emit_checkout_started(ctx.t, user_id=ctx.self_id, session_id=loc.session,
                              checkout_id=loc.checkout, sku_id=loc.cart_sku,
                              quantity=loc.cart_qty,
                              subtotal=std.checked_mul(loc.cart_price, loc.cart_qty))
    out.request_reserve(ctx.t, shard=ctx.reads.sku.sku_group[loc.cart_sku], tag=loc.checkout,
                        sku_id=loc.cart_sku, quantity=loc.cart_qty)
    return COMMIT                                          # the owner suspends until answered


def _granted(ctx, loc, cmd, out, cfg):
    if cmd.tag != loc.checkout:
        return reject(REJ_STALE)
    delay = ctx.rng.dist_us(site=30, d=cfg.auth_latency)
    if not out.reserve(timers=1):
        return RETRY
    out.timer(ctx.t + delay, C_AUTH, prio=PRIO_TIMER, tag=loc.checkout)
    return COMMIT


def _rejected(ctx, loc, cmd, out, cfg):
    if cmd.tag != loc.checkout:
        return reject(REJ_STALE)
    substitute = ctx.rng.bernoulli(site=31, p=cfg.substitute_p)
    more = ctx.rng.geometric(site=32, mean=3.0)
    nxt = ctx.rng.dist_us(site=33, d=cfg.view_gap)
    if not out.reserve(records={"checkout_failed": 1}, timers=1):
        return RETRY
    out.emit_checkout_failed(ctx.t, user_id=ctx.self_id, checkout_id=loc.checkout,
                             reason="out_of_stock", sku_id=loc.cart_sku)
    loc.checkout = std.NULL
    loc.cart_n = 0
    if substitute:
        loc.views_left = more
        out.timer(ctx.t + nxt, C_VIEW, prio=PRIO_TIMER)
    return COMMIT


def _auth(ctx, loc, cmd, out, cfg):
    if cmd.tag != loc.checkout:
        return reject(REJ_STALE)
    fail = ctx.rng.bernoulli(site=40, p=cfg.auth_fail_p)
    code = ctx.rng.categorical(site=41, p=(0.45, 0.3, 0.15, 0.1))
    method = ctx.rng.categorical(site=42, p=(0.7, 0.22, 0.08))
    if not out.reserve(records={"payment_authorized": 1, "payment_failed": 1,
                                "order_placed": 1, "checkout_failed": 1},
                       creates={"order": 1}, requests=1):
        return RETRY
    amount = std.checked_mul(loc.cart_price, loc.cart_qty)
    group = ctx.reads.sku.sku_group[loc.cart_sku]
    if fail:
        out.emit_payment_failed(ctx.t, user_id=ctx.self_id, checkout_id=loc.checkout,
                                amount=amount, decline_code=code)
        out.send_release(ctx.t, to=group, tag=loc.checkout, sku_id=loc.cart_sku,
                         quantity=loc.cart_qty)
        out.emit_checkout_failed(ctx.t, user_id=ctx.self_id, checkout_id=loc.checkout,
                                 reason="payment_declined", sku_id=loc.cart_sku)
    else:
        out.emit_payment_authorized(ctx.t, user_id=ctx.self_id, checkout_id=loc.checkout,
                                    amount=amount, method=method)
        out.send_commit(ctx.t, to=group, tag=loc.checkout, sku_id=loc.cart_sku,
                        quantity=loc.cart_qty)
        order = out.create_order(sku_id=loc.cart_sku, quantity=loc.cart_qty, amount=amount)
        out.emit_order_placed(ctx.t, user_id=ctx.self_id, order_id=order,
                              checkout_id=loc.checkout, device_id=loc.device,
                              sku_id=loc.cart_sku, quantity=loc.cart_qty, amount=amount,
                              category=ctx.reads.sku.category[loc.cart_sku])
    loc.checkout = std.NULL
    loc.cart_n = 0
    return COMMIT


@kernel(state="inventory", commands=(C_RESERVE, C_COMMIT, C_RELEASE),
        max=Res(records={"stock_reserved": 1, "stock_rejected": 1, "stock_committed": 1,
                         "stock_released": 1}, requests=1))
def inventory_desk(ctx, s, cmd, out):
    i = ctx.reads.sku.local_index[cmd.sku_id]
    if not out.reserve(records={"stock_reserved": 1, "stock_rejected": 1,
                                "stock_committed": 1, "stock_released": 1}, requests=1):
        return RETRY
    if cmd.kind == C_RESERVE:                              # decided at the request's time (D6)
        if s.on_hand[i] - s.reserved[i] >= cmd.quantity:
            s.reserved[i] = std.checked_add(s.reserved[i], cmd.quantity)
            out.emit_stock_reserved(ctx.t, sku_group=ctx.self_id, sku_id=cmd.sku_id,
                                    checkout_id=cmd.tag, quantity=cmd.quantity)
            out.respond(cmd, "granted")
        else:
            out.emit_stock_rejected(ctx.t, sku_group=ctx.self_id, sku_id=cmd.sku_id,
                                    checkout_id=cmd.tag, quantity=cmd.quantity)
            out.respond(cmd, "rejected")
        return COMMIT
    s.reserved[i] = std.checked_sub(s.reserved[i], cmd.quantity)
    if cmd.kind == C_COMMIT:
        s.on_hand[i] = std.checked_sub(s.on_hand[i], cmd.quantity)
        out.emit_stock_committed(ctx.t, sku_group=ctx.self_id, sku_id=cmd.sku_id,
                                 checkout_id=cmd.tag, quantity=cmd.quantity,
                                 on_hand_after=s.on_hand[i])
    else:
        out.emit_stock_released(ctx.t, sku_group=ctx.self_id, sku_id=cmd.sku_id,
                                checkout_id=cmd.tag, quantity=cmd.quantity)
    return COMMIT


@kernel(state="inventory", commands=(START,), max=Res(records={"restocked": 64}, timers=1),
        substep=64)
def restock(ctx, s, cmd, out):
    """Weekly restock of one inventory group, 64 SKUs per sub-step, continued at top priority."""
    start = cmd.cursor
    stop = min(start + 64, s.n_sku)
    if not out.reserve(records={"restocked": 64}, timers=1):
        return RETRY
    for i in range(start, stop):
        gap = ctx.reads.sku.stock_target[s.sku[i]] - s.on_hand[i]
        if gap > 0:
            qty = 1 + ctx.rng.uniform_int(site=1, lo=0, hi=gap - 1)     # suppliers short-ship
            s.on_hand[i] = std.checked_add(s.on_hand[i], qty)
            out.emit_restocked(ctx.t, sku_group=ctx.self_id, sku_id=s.sku[i], quantity=qty,
                               on_hand_after=s.on_hand[i])
    if stop < s.n_sku:
        out.continue_at(ctx.t, cursor=stop)
    return COMMIT
