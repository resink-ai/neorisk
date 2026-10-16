"""Handwritten kernels for the ecommerce pack.

Every kernel follows the action interface:
    1. validate   read state, maybe reject(...)       no writes yet
    2. reserve    out.reserve(...) for every resource  RETRY if the slab is full
    3. commit     mutate state, emit, schedule         cannot fail
Random draws use ctx.rng.<dist>(site=N, ...); each draw site has its own number, so edits to
one site never shift draws at another.
"""

from neorisk_simkit.engine import COMMIT, RETRY, Local, Res, kernel, reject
from neorisk_simkit import std

# ------------------------------------------------------------------ command ids
C_SESSION = 1           # timer: start the next session
C_VIEW = 2              # timer: next product view inside a session
C_CHECKOUT = 3          # timer: start checkout with the current cart
C_AUTH = 4              # timer: payment authorization result arrives
R_RESERVED = 10         # response: stock.reserve granted
R_REJECTED = 11         # response: stock.reserve rejected (out of stock)
R_TIMEOUT = 12          # timer: reservations not all answered in time
JOURNEY_COMMANDS = (C_SESSION, C_VIEW, C_CHECKOUT, C_AUTH, R_RESERVED, R_REJECTED, R_TIMEOUT)

# priorities at equal time (lower runs first); responses before own timers
PRIO_RESPONSE, PRIO_TIMER = 1, 5

REJ_NO_CART = 1
REJ_STALE = 2
REJ_NOTHING_TO_REFUND = 3

MAX_LINES = 5
HOUR = 3_600_000_000     # µs
MINUTE = 60_000_000

# Per-owner scratch, laid out next to the user row; freed when the owner retires
JOURNEY_LOCAL = Local(
    session="ref",              # current session id (provisional handle within a step)
    views_left="i16",
    cart_sku="i32[5]", cart_qty="i16[5]", cart_price="i64[5]", cart_n="i8",
    checkout="ref", pending="i8", granted_mask="u8", failed_sku="i32",
    hold="i64",                 # credit held for this checkout
)


# ================================================================== shopper journey
@kernel(state="user", local=JOURNEY_LOCAL, commands=JOURNEY_COMMANDS,
        max=Res(records={"session_started": 1, "product_viewed": 1, "cart_item_added": 1,
                         "checkout_started": 1, "checkout_failed": 1, "payment_authorized": 1,
                         "payment_failed": 1, "order_placed": 1},
                creates={"order": 1}, timers=2, requests=MAX_LINES))
def shopper_journey(ctx, s, loc, cmd, out):
    """One shopper's sessions, browsing, cart and checkout. Dispatches on the command kind."""
    cfg = ctx.cfg
    if cmd.kind == C_SESSION:
        return _start_session(ctx, s, loc, out, cfg)
    if cmd.kind == C_VIEW:
        return _view(ctx, s, loc, out, cfg)
    if cmd.kind == C_CHECKOUT:
        return _checkout(ctx, s, loc, out, cfg)
    if cmd.kind == R_RESERVED or cmd.kind == R_REJECTED:
        return _on_reserve_response(ctx, s, loc, cmd, out, cfg)
    if cmd.kind == R_TIMEOUT:
        return _on_timeout(ctx, s, loc, cmd, out)
    if cmd.kind == C_AUTH:
        return _on_auth(ctx, s, loc, cmd, out, cfg)
    return reject(REJ_STALE)


def _start_session(ctx, s, loc, out, cfg):
    if s.status != std.ACTIVE:
        return reject(REJ_STALE)                                   # dormant: no more sessions
    if not out.reserve(records={"session_started": 1}, timers=2):
        return RETRY
    device = ctx.refs.device.pick(ctx.self_id, ctx.rng.uniform(site=1))
    loc.session = out.new_id("session")
    loc.views_left = ctx.rng.geometric(site=2, mean=cfg.views_mean)
    channel = ctx.rng.categorical(site=3, p=ctx.reads.device.channel_mix[device])
    out.emit_session_started(ctx.t, user_id=ctx.self_id, session_id=loc.session,
                             device_id=device, channel=channel)
    out.timer(ctx.t + ctx.rng.exp_us(site=4, mean_s=40), C_VIEW, prio=PRIO_TIMER)
    gap = ctx.rng.pareto_us(site=5, alpha=cfg.session_gap_alpha, min_h=cfg.session_gap_min_h)
    out.timer(ctx.t + gap, C_SESSION, prio=PRIO_TIMER)
    return COMMIT


def _view(ctx, s, loc, out, cfg):
    if loc.views_left <= 0:
        # session over: maybe check out what's in the cart
        if loc.cart_n > 0 and ctx.rng.bernoulli(site=10, p=cfg.checkout_p):
            if not out.reserve(timers=1):
                return RETRY
            out.timer(ctx.t + ctx.rng.exp_us(site=11, mean_s=25), C_CHECKOUT, prio=PRIO_TIMER)
            return COMMIT
        return reject(REJ_NO_CART)
    if not out.reserve(records={"product_viewed": 1, "cart_item_added": 1}, timers=1):
        return RETRY
    sku = ctx.reads.sku.sample_by_weight(ctx.rng.uniform(site=12))
    out.emit_product_viewed(ctx.t, user_id=ctx.self_id, session_id=loc.session, sku_id=sku,
                            position=ctx.rng.geometric(site=13, mean=4),
                            source=ctx.rng.categorical(site=14, p=(.25, .35, .2, .2)))
    if loc.cart_n < MAX_LINES and ctx.rng.bernoulli(site=15, p=cfg.add_to_cart_p):
        qty = 1 + ctx.rng.geometric(site=16, mean=0.25)
        i = loc.cart_n
        loc.cart_sku[i], loc.cart_qty[i] = sku, qty
        loc.cart_price[i] = ctx.reads.sku.price[sku]
        loc.cart_n = i + 1
        out.emit_cart_item_added(ctx.t, user_id=ctx.self_id, session_id=loc.session,
                                 sku_id=sku, quantity=qty, unit_price=loc.cart_price[i])
    loc.views_left -= 1
    out.timer(ctx.t + ctx.rng.exp_us(site=17, mean_s=40), C_VIEW, prio=PRIO_TIMER)
    return COMMIT


def _checkout(ctx, s, loc, out, cfg):
    """Hold credit on the owner, then reserve every line in its inventory shard."""
    n = loc.cart_n
    if n == 0 or loc.pending > 0:
        return reject(REJ_NO_CART)
    if not out.reserve(records={"checkout_started": 1}, requests=n, timers=1):
        return RETRY
    subtotal = 0
    for i in range(n):
        subtotal = std.checked_add(subtotal, loc.cart_price[i] * loc.cart_qty[i])
    use = s.credit - s.credit_hold
    hold = std.checked_min(use, subtotal) if ctx.rng.bernoulli(site=20, p=cfg.credit_use_p) else 0
    s.credit_hold = std.checked_add(s.credit_hold, hold)              # owner-side hold
    loc.hold, loc.checkout, loc.pending, loc.granted_mask = hold, out.new_id("checkout"), n, 0
    out.emit_checkout_started(ctx.t, user_id=ctx.self_id, session_id=loc.session,
                              checkout_id=loc.checkout, lines=n, subtotal=subtotal,
                              credit_applied=hold)
    for i in range(n):                                                # immutable payloads
        out.request_reserve(ctx.t, shard=ctx.reads.sku.sku_group[loc.cart_sku[i]],
                            sku_id=loc.cart_sku[i], quantity=loc.cart_qty[i],
                            tag=loc.checkout, line=i)
    out.timer(ctx.t + 30_000_000, R_TIMEOUT, prio=PRIO_TIMER, tag=loc.checkout)   # join timeout
    return COMMIT


def _on_reserve_response(ctx, s, loc, cmd, out, cfg):
    if cmd.tag != loc.checkout or loc.pending == 0:
        return reject(REJ_STALE)                       # late response for an old checkout
    granted = cmd.kind == R_RESERVED
    last = loc.pending == 1
    all_ok = granted and (loc.granted_mask | (1 << cmd.line)) == (1 << loc.cart_n) - 1
    failed_before = loc.failed_sku != 0
    need_release = last and not all_ok
    if not out.reserve(records={"checkout_failed": 1}, requests=MAX_LINES if need_release else 0,
                       timers=2):
        return RETRY
    loc.pending -= 1
    if granted:
        loc.granted_mask |= 1 << cmd.line
    elif not failed_before:
        loc.failed_sku = loc.cart_sku[cmd.line]
    if not last:
        return COMMIT
    if all_ok:                                         # every line reserved: authorize payment
        out.timer(ctx.t + ctx.rng.dist_us(site=30, d=cfg.auth_latency), C_AUTH, prio=PRIO_TIMER,
                  tag=loc.checkout)
        return COMMIT
    _release_all(ctx, s, loc, out)                     # some line out of stock: give back
    out.emit_checkout_failed(ctx.t, user_id=ctx.self_id, checkout_id=loc.checkout,
                             reason=std.cat("out_of_stock"), sku_id=loc.failed_sku)
    if ctx.rng.bernoulli(site=31, p=cfg.substitute_p):
        loc.views_left = 1 + ctx.rng.geometric(site=32, mean=2)      # look for a substitute
        out.timer(ctx.t + ctx.rng.exp_us(site=33, mean_s=60), C_VIEW, prio=PRIO_TIMER)
    _clear_checkout(loc, keep_cart=True)
    return COMMIT


def _on_timeout(ctx, s, loc, cmd, out):
    if cmd.tag != loc.checkout or loc.pending == 0:
        return reject(REJ_STALE)                       # all responses arrived first
    if not out.reserve(records={"checkout_failed": 1}, requests=MAX_LINES):
        return RETRY
    _release_all(ctx, s, loc, out)
    out.emit_checkout_failed(ctx.t, user_id=ctx.self_id, checkout_id=loc.checkout,
                             reason=std.cat("timeout"), sku_id=0)
    _clear_checkout(loc, keep_cart=False)
    return COMMIT


def _on_auth(ctx, s, loc, cmd, out, cfg):
    if cmd.tag != loc.checkout:
        return reject(REJ_STALE)
    if not out.reserve(records={"payment_authorized": 1, "payment_failed": 1,
                                "order_placed": 1, "checkout_failed": 1},
                       creates={"order": 1}, requests=MAX_LINES):
        return RETRY
    amount = 0
    for i in range(loc.cart_n):
        amount = std.checked_add(amount, loc.cart_price[i] * loc.cart_qty[i])
    charge = amount - loc.hold
    if ctx.rng.bernoulli(site=40, p=cfg.auth_fail_p):
        out.emit_payment_failed(ctx.t, user_id=ctx.self_id, checkout_id=loc.checkout,
                                amount=charge, decline_code=ctx.rng.categorical(
                                    site=41, p=(.45, .3, .15, .1)))
        _release_all(ctx, s, loc, out)
        out.emit_checkout_failed(ctx.t, user_id=ctx.self_id, checkout_id=loc.checkout,
                                 reason=std.cat("payment_declined"), sku_id=0)
        _clear_checkout(loc, keep_cart=False)
        return COMMIT
    out.emit_payment_authorized(ctx.t, user_id=ctx.self_id, checkout_id=loc.checkout,
                                amount=charge, method=ctx.rng.categorical(site=42, p=(.7, .22, .08)))
    for i in range(loc.cart_n):                        # commit every reservation
        out.request_commit(ctx.t, shard=ctx.reads.sku.sku_group[loc.cart_sku[i]],
                           tag=loc.checkout, line=i)
    s.credit = std.checked_sub(s.credit, loc.hold)     # owner-side hold committed
    s.credit_hold = std.checked_sub(s.credit_hold, loc.hold)
    order = out.create_order(lines=loc.cart_n, amount=amount, credit_used=loc.hold,
                             refunded=0, status=std.cat("placed"))
    if s.first_paid_order == 0:
        s.first_paid_order = order
    out.emit_order_placed(ctx.t, user_id=ctx.self_id, order_id=order, checkout_id=loc.checkout,
                          device_id=ctx.refs.device.last(ctx.self_id), lines=loc.cart_n,
                          amount=amount, credit_used=loc.hold,
                          category=ctx.reads.sku.category[_largest_line(loc)])
    _clear_checkout(loc, keep_cart=False)
    return COMMIT


def _release_all(ctx, s, loc, out):
    """Release granted reservations and the credit hold. Called only after reserve succeeded."""
    for i in range(loc.cart_n):
        if loc.granted_mask & (1 << i):
            out.request_release(ctx.t, shard=ctx.reads.sku.sku_group[loc.cart_sku[i]],
                                tag=loc.checkout, line=i)
    s.credit_hold = std.checked_sub(s.credit_hold, loc.hold)


def _clear_checkout(loc, keep_cart):
    loc.checkout, loc.pending, loc.granted_mask, loc.failed_sku, loc.hold = 0, 0, 0, 0, 0
    if not keep_cart:
        loc.cart_n = 0


def _largest_line(loc):
    best, value = 0, -1
    for i in range(loc.cart_n):
        v = loc.cart_price[i] * loc.cart_qty[i]
        if v > value:
            best, value = i, v
    return loc.cart_sku[best]


# ================================================================== inventory shard
@kernel(state="inventory", max=Res(records={"restocked": 64}, timers=1), substep=64)
def restock(ctx, s, cmd, out):
    """Weekly restock of one inventory group; 64 SKUs per sub-step, continued at top priority."""
    start = cmd.cursor
    stop = min(start + 64, s.n_sku)
    if not out.reserve(records={"restocked": stop - start}, timers=1):
        return RETRY
    for i in range(start, stop):
        target = ctx.reads.stock_target[s.sku[i]]
        gap = target - s.on_hand[i]
        if gap > 0:
            qty = ctx.rng.binomial(site=1, n=gap, p=0.9)           # supplier short-ships
            s.on_hand[i] = std.checked_add(s.on_hand[i], qty)
            out.emit_restocked(ctx.t, sku_group=ctx.self_id, sku_id=s.sku[i], quantity=qty)
    if stop < s.n_sku:
        out.continue_at(ctx.t, cursor=stop)                        # same time, top priority
    return COMMIT


# ================================================================== small actions
@kernel(state="user", instance="order", max=Res(records={"refund_issued": 1}))
def refund_return(ctx, s, o, cmd, out):
    left = o.amount - o.refunded
    if left <= 0:
        return reject(REJ_NOTHING_TO_REFUND)
    if not out.reserve(records={"refund_issued": 1}):
        return RETRY
    amt = std.checked_min(left, std.prorate(o.amount, cmd.lines, o.lines))
    o.refunded = std.checked_add(o.refunded, amt)
    o.status = std.cat("returned")
    out.emit_refund_issued(ctx.t, user_id=ctx.self_id, order_id=o.id, amount=amt)
    return COMMIT


@kernel(state="user", max=Res(records={"referral_bonus_paid": 1}))
def pay_invitee_bonus(ctx, s, cmd, out):
    if not out.reserve(records={"referral_bonus_paid": 1}):
        return RETRY
    amt = cmd.granted_amount // 2
    s.credit = std.checked_add(s.credit, amt)
    out.emit_referral_bonus_paid(ctx.t, user_id=ctx.self_id, invitee_id=ctx.self_id,
                                 role=std.cat("invitee"), amount=amt)
    return COMMIT


@kernel(state="user", max=Res(records={"referral_bonus_paid": 1}))
def credit_inviter(ctx, s, cmd, out):
    """Inviter side; arrives as an owner-to-owner message, at the next step boundary or later."""
    if not out.reserve(records={"referral_bonus_paid": 1}):
        return RETRY
    s.credit = std.checked_add(s.credit, cmd.amount)
    out.emit_referral_bonus_paid(ctx.t, user_id=ctx.self_id, invitee_id=cmd.sender,
                                 role=std.cat("inviter"), amount=cmd.amount)
    return COMMIT


# Thin actions exposed to overlays. Each is a std recipe bound to this pack's events.
signup = std.action.emit_signup("user_signed_up")
signup_via_invite = std.action.emit_signup("user_signed_up", acquisition="invite")
send_invite = std.action.emit("invite_sent", medium="link")
start_session = std.action.timer(C_SESSION)
quick_order = std.action.single_line_checkout(                    # reserve → auth → order
    reserve="reserve", commit="commit", release="release", amount_param="amount")
