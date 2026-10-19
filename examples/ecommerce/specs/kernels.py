"""Handwritten kernels and machine actions of the ecommerce pack.

Kernels: validate (draws allowed, no writes) -> out.reserve(...) -> commit. Actions (@action)
never reserve: the calling machine reserves their max (D65). Each draw site is used once per
process. Exposed actions (signup, signup_invited, quick_order, pay_referral) never read `s`, so
overlay cohorts can run them for member rows (D74).
"""

from neorisk_simkit import std
from neorisk_simkit.engine import (
    COMMIT,
    PRIO_TIMER,
    RETRY,
    START,
    Local,
    Res,
    action,
    kernel,
    reject,
)

CART = 5                                  # cart lines (Local array width)
HOLD_SLOTS = 64                           # holds per inventory shard
N_REGIONS = 50
C_SESSION, C_VIEW, C_CHECKOUT, R_GRANTED, R_REJECTED, C_AUTH = 1, 2, 3, 4, 5, 6
R_BONUS, R_NO_BONUS, C_MOVE, M_CREDIT = 7, 8, 9, 10
SHOPPER_COMMANDS = (START, C_SESSION, C_VIEW, C_CHECKOUT, R_GRANTED, R_REJECTED, C_AUTH,
                    R_BONUS, R_NO_BONUS, C_MOVE, M_CREDIT)
C_RESERVE, C_COMMIT, C_RELEASE, C_HOLD_EXPIRE = 1, 2, 3, 4
DESK_COMMANDS = (C_RESERVE, C_COMMIT, C_RELEASE, C_HOLD_EXPIRE)
C_CLAIM, C_REFUND = 1, 2
REJ_NO_CART, REJ_STALE, REJ_NOTHING_TO_REFUND = 1, 2, 3
WHY_STOCK, WHY_BUSY = 0, 1

SHOPPER_LOCAL = Local(session="ref", device="ref", views_left="i16", cart_n="i8",
                      cart_sku="ref[5]", cart_qty="i16[5]", cart_price="i64[5]",
                      checkout="ref", subtotal="i64", hold="i64", pending="i8", granted="u8",
                      rejected_sku="ref", holds="ref[5]", slot="i32[5]", ordered="u8")
DESK_LOCAL = Local(**std.reservations.fields(HOLD_SLOTS))


# ================================================================== shopper
@kernel(state="user", local=SHOPPER_LOCAL, commands=SHOPPER_COMMANDS,
        max=Res(records={"user_signed_up": 1, "session_started": 1, "product_viewed": 1,
                         "cart_item_added": 1, "checkout_started": 1, "checkout_failed": 1,
                         "payment_authorized": 1, "payment_failed": 1, "order_placed": 1,
                         "referral_bonus_paid": 1, "referral_bonus_rejected": 1, "address": 1},
                creates={"session": 1, "checkout": 1, "order": 1, "claim": 1}, timers=2,
                requests=CART + 1))
def shopper(ctx, s, loc, cmd, out):
    cfg = ctx.cfg
    if cmd.kind == START:
        return _signup(ctx, s, out, cfg)
    if cmd.kind == C_SESSION:
        return _session(ctx, loc, out, cfg)
    if cmd.kind == C_VIEW:
        return _view(ctx, loc, out, cfg)
    if cmd.kind == C_CHECKOUT:
        return _checkout(ctx, s, loc, out, cfg)
    if cmd.kind == C_AUTH:
        return _auth(ctx, s, loc, cmd, out, cfg)
    if cmd.kind == R_BONUS or cmd.kind == R_NO_BONUS:
        return _bonus(ctx, s, cmd, out)
    if cmd.kind == C_MOVE:
        return _move(ctx, s, out, cfg)
    if cmd.kind == M_CREDIT:
        return _credit(ctx, s, cmd, out)
    return _answer(ctx, s, loc, cmd, out, cfg)


def _signup(ctx, s, out, cfg):
    delay = ctx.rng.dist_us(site=1, d=cfg.journey.signup_delay)
    move = ctx.rng.dist_us(site=2, d=cfg.journey.move_gap)
    if not out.reserve(records={"user_signed_up": 1}, timers=2):
        return RETRY
    inviter = std.NULL
    if s.referred:
        s.acquisition = "invite"
        if s.invited_by == ctx.self_id:                    # never one's own inviter (F-38)
            n_inv = max(1, int(cfg.users * cfg.initial_share * cfg.referral.inviter_share))
            s.invited_by = (s.invited_by + 1) % n_inv
        inviter = s.invited_by
    out.emit_user_signed_up(ctx.t, user_id=ctx.self_id,
                            device_id=ctx.refs.device.get(ctx.self_id, 0),
                            acquisition=s.acquisition, referred=s.referred, invited_by=inviter)
    out.timer(ctx.t + delay, C_SESSION, prio=PRIO_TIMER)
    out.timer(ctx.t + move, C_MOVE, prio=PRIO_TIMER)
    return COMMIT


def _channel(ctx, device):
    if ctx.reads.device.kind[device] == "desktop":
        return 0                                           # web
    return 1                                               # app


def _session(ctx, loc, out, cfg):
    j = cfg.journey
    n_dev = ctx.refs.device.count(ctx.self_id)
    dev = ctx.refs.device.get(ctx.self_id, ctx.rng.uniform_int(site=3, lo=0, hi=n_dev - 1))
    views = min(ctx.rng.geometric(site=4, mean=j.views_mean), 30)
    gap = ctx.rng.pareto_us(site=5, alpha=j.session_gap_alpha, min_h=j.session_gap_min_h)
    first = ctx.rng.dist_us(site=6, d=j.view_gap)
    if not out.reserve(records={"session_started": 1}, creates={"session": 1}, timers=2):
        return RETRY
    loc.session = out.new_id("session")
    loc.device = dev
    loc.views_left = views
    out.emit_session_started(ctx.t, user_id=ctx.self_id, session_id=loc.session, device_id=dev,
                             channel=_channel(ctx, dev))
    out.timer(ctx.t + first, C_VIEW, prio=PRIO_TIMER)
    out.timer(ctx.t + gap, C_SESSION, prio=PRIO_TIMER)
    return COMMIT


def _view(ctx, loc, out, cfg):
    j = cfg.journey
    if loc.views_left <= 0:                                # session over: maybe check out
        if loc.cart_n == 0 or loc.checkout != std.NULL:
            return reject(REJ_NO_CART)
        if not ctx.rng.bernoulli(site=10, p=j.checkout_p):
            return reject(REJ_NO_CART)
        delay = ctx.rng.dist_us(site=11, d=j.checkout_delay)
        if not out.reserve(timers=1):
            return RETRY
        out.timer(ctx.t + delay, C_CHECKOUT, prio=PRIO_TIMER)
        return COMMIT
    sku = ctx.reads.sku.sample_by_weight(ctx.rng.uniform(site=12))
    add = ctx.rng.bernoulli(site=13, p=j.add_to_cart_p)
    qty = ctx.rng.geometric(site=14, mean=1.25)          # >= 1: mostly one unit
    pos = ctx.rng.geometric(site=15, mean=5.0)
    nxt = ctx.rng.dist_us(site=16, d=j.view_gap)
    if not out.reserve(records={"product_viewed": 1, "cart_item_added": 1}, timers=1):
        return RETRY
    price = ctx.reads.sku.price[sku]
    out.emit_product_viewed(ctx.t, user_id=ctx.self_id, session_id=loc.session, sku_id=sku,
                            device_id=loc.device, position=pos,
                            category=ctx.reads.sku.category[sku], price=price)
    if add and loc.checkout == std.NULL and loc.cart_n < CART:
        n = loc.cart_n
        loc.cart_sku[n] = sku
        loc.cart_qty[n] = qty
        loc.cart_price[n] = price
        loc.cart_n = n + 1
        out.emit_cart_item_added(ctx.t, user_id=ctx.self_id, session_id=loc.session,
                                 sku_id=sku, quantity=qty, unit_price=price)
    loc.views_left -= 1
    out.timer(ctx.t + nxt, C_VIEW, prio=PRIO_TIMER)
    return COMMIT


def _checkout(ctx, s, loc, out, cfg):
    """Hold credit on the owner, then reserve every line in its inventory shard (§07)."""
    if loc.cart_n == 0 or loc.checkout != std.NULL:
        return reject(REJ_NO_CART)
    use = ctx.rng.bernoulli(site=20, p=cfg.journey.credit_use_p)
    total = 0
    for i in range(loc.cart_n):
        total = std.checked_add(total, std.checked_mul(loc.cart_price[i], loc.cart_qty[i]))
    if not out.reserve(records={"checkout_started": 1}, creates={"checkout": 1}, requests=CART):
        return RETRY
    hold = 0
    if use:
        hold = std.checked_min(s.credit - s.held, total)
    s.held = std.checked_add(s.held, hold)
    loc.checkout = out.new_id("checkout")
    loc.subtotal = total
    loc.hold = hold
    loc.pending = loc.cart_n
    loc.granted = 0
    loc.rejected_sku = std.NULL
    out.emit_checkout_started(ctx.t, user_id=ctx.self_id, session_id=loc.session,
                              checkout_id=loc.checkout, lines=loc.cart_n, subtotal=total,
                              credit_applied=hold)
    for i in range(loc.cart_n):                            # one immutable request per line
        out.request_reserve(ctx.t, shard=ctx.reads.sku.sku_group[loc.cart_sku[i]],
                            tag=loc.checkout, sku_id=loc.cart_sku[i], quantity=loc.cart_qty[i],
                            line=i)
    return COMMIT                                          # suspends: join of cart_n answers


def _release_all(ctx, s, loc, out):
    for i in range(loc.cart_n):
        if loc.granted & (1 << i):
            out.send_release(ctx.t, to=ctx.reads.sku.sku_group[loc.cart_sku[i]],
                             tag=loc.checkout, sku_id=loc.cart_sku[i], quantity=loc.cart_qty[i],
                             hold_id=loc.holds[i], slot=loc.slot[i])
    s.held = std.checked_sub(s.held, loc.hold)


def _clear(loc):
    loc.checkout = std.NULL
    loc.cart_n = 0
    loc.pending = 0
    loc.granted = 0
    loc.hold = 0


def _answer(ctx, s, loc, cmd, out, cfg):
    if cmd.tag != loc.checkout or loc.pending <= 0:
        return reject(REJ_STALE)
    j = cfg.journey
    substitute = ctx.rng.bernoulli(site=21, p=j.substitute_p)
    more = ctx.rng.geometric(site=22, mean=3.0)
    nxt = ctx.rng.dist_us(site=23, d=j.view_gap)
    auth = ctx.rng.dist_us(site=24, d=j.auth_latency)
    if not out.reserve(records={"checkout_failed": 1}, timers=1, requests=CART):
        return RETRY
    line = cmd.line
    if cmd.kind == R_GRANTED:
        loc.granted |= 1 << line
        loc.holds[line] = cmd.hold_id
        loc.slot[line] = cmd.slot
    else:
        loc.rejected_sku = loc.cart_sku[line]
    loc.pending -= 1
    if loc.pending > 0:
        return COMMIT                                      # join: wait for the other lines
    if loc.granted == (1 << loc.cart_n) - 1:               # every line held: authorize
        out.timer(ctx.t + auth, C_AUTH, prio=PRIO_TIMER, tag=loc.checkout)
        return COMMIT
    _release_all(ctx, s, loc, out)
    out.emit_checkout_failed(ctx.t, user_id=ctx.self_id, checkout_id=loc.checkout,
                             reason="out_of_stock", sku_id=loc.rejected_sku)
    if substitute:
        loc.views_left = more
        out.timer(ctx.t + nxt, C_VIEW, prio=PRIO_TIMER)
    _clear(loc)
    return COMMIT


def _largest(loc):
    best, value = 0, -1
    for i in range(loc.cart_n):
        v = loc.cart_price[i] * loc.cart_qty[i]
        if v > value:
            best, value = i, v
    return best


def _auth(ctx, s, loc, cmd, out, cfg):
    if cmd.tag != loc.checkout or loc.checkout == std.NULL or loc.pending != 0:
        return reject(REJ_STALE)
    r = cfg.referral
    fail = ctx.rng.bernoulli(site=30, p=cfg.journey.auth_fail_p)
    code = ctx.rng.categorical(site=31, p=(0.45, 0.3, 0.15, 0.1))
    method = ctx.rng.categorical(site=32, p=(0.7, 0.22, 0.08))
    if not out.reserve(records={"payment_authorized": 1, "payment_failed": 1,
                                "order_placed": 1, "checkout_failed": 1},
                       creates={"order": 1, "claim": 1}, requests=CART + 1):
        return RETRY
    charge = loc.subtotal - loc.hold
    if fail:
        out.emit_payment_failed(ctx.t, user_id=ctx.self_id, checkout_id=loc.checkout,
                                amount=charge, decline_code=code)
        _release_all(ctx, s, loc, out)
        out.emit_checkout_failed(ctx.t, user_id=ctx.self_id, checkout_id=loc.checkout,
                                 reason="payment_declined", sku_id=std.NULL)
        _clear(loc)
        return COMMIT
    out.emit_payment_authorized(ctx.t, user_id=ctx.self_id, checkout_id=loc.checkout,
                                amount=charge, method=method)
    for i in range(loc.cart_n):                            # commit every reservation
        out.send_commit(ctx.t, to=ctx.reads.sku.sku_group[loc.cart_sku[i]], tag=loc.checkout,
                        sku_id=loc.cart_sku[i], quantity=loc.cart_qty[i], hold_id=loc.holds[i],
                        slot=loc.slot[i])
    s.credit = std.checked_sub(s.credit, loc.hold)          # the owner commits its hold
    s.held = std.checked_sub(s.held, loc.hold)
    big = loc.cart_sku[_largest(loc)]
    category = ctx.reads.sku.category[big]
    order = out.create_order(user_id=ctx.self_id, amount=loc.subtotal, lines=loc.cart_n,
                             category=category, credit_used=loc.hold, refunded=0,
                             status="placed")
    out.emit_order_placed(ctx.t, user_id=ctx.self_id, order_id=order, checkout_id=loc.checkout,
                          device_id=loc.device, sku_id=big, lines=loc.cart_n,
                          amount=loc.subtotal, credit_used=loc.hold, category=category)
    if loc.ordered == 0:                                   # a referral's first order
        loc.ordered = 1
        if s.referred and loc.subtotal >= r.min_order:
            out.request_claim(ctx.t, shard=0, claim_id=out.new_id("claim"),
                              amount=2 * r.bonus_each)
    _clear(loc)
    return COMMIT


def _bonus(ctx, s, cmd, out):
    if not out.reserve(records={"referral_bonus_paid": 1, "referral_bonus_rejected": 1},
                       requests=1):
        return RETRY
    if cmd.kind == R_BONUS:
        half = cmd.amount // 2
        s.credit = std.checked_add(s.credit, half)
        out.emit_referral_bonus_paid(ctx.t, user_id=ctx.self_id, invitee_id=ctx.self_id,
                                     role="invitee", amount=half)
        if s.invited_by != std.NULL:                       # owner-to-owner, a day later (D73)
            out.send_inviter_credit(ctx.t, to=s.invited_by, invitee=ctx.self_id,
                                    amount=cmd.amount - half)
    else:
        out.emit_referral_bonus_rejected(ctx.t, user_id=ctx.self_id, reason="budget_exhausted")
    return COMMIT


def _credit(ctx, s, cmd, out):
    if not out.reserve(records={"referral_bonus_paid": 1}):
        return RETRY
    s.credit = std.checked_add(s.credit, cmd.amount)
    out.emit_referral_bonus_paid(ctx.t, user_id=ctx.self_id, invitee_id=cmd.invitee,
                                 role="inviter", amount=cmd.amount)
    return COMMIT


def _move(ctx, s, out, cfg):
    region = ctx.rng.uniform_int(site=40, lo=0, hi=N_REGIONS - 1)
    nxt = ctx.rng.dist_us(site=41, d=cfg.journey.move_gap)
    if not out.reserve(records={"address": 1}, timers=1):
        return RETRY
    out.change_address(ctx.t, region=region)
    out.timer(ctx.t + nxt, C_MOVE, prio=PRIO_TIMER)
    return COMMIT


# ================================================================== inventory (S2 desk, D49)
@kernel(state="inventory", local=DESK_LOCAL, commands=DESK_COMMANDS,
        max=Res(records={"stock_reserved": 1, "stock_rejected": 1, "stock_committed": 1,
                         "stock_released": 1, "stock_expired": 1, "stock_commit_late": 1},
                creates={"hold": 1}, timers=1, requests=1))
def inventory_desk(ctx, s, loc, cmd, out):
    if cmd.kind == C_RESERVE:
        return _reserve(ctx, s, loc, cmd, out)
    if cmd.kind == C_HOLD_EXPIRE:
        return _expire(ctx, s, loc, cmd, out)
    return _settle_hold(ctx, s, loc, cmd, out)


# copied from examples/ecommerce_s2/specs/kernels.py (frozen S2 slice)
def _reserve(ctx, s, loc, cmd, out):
    i = ctx.reads.sku.local_index[cmd.sku_id]
    free = -1
    for j in range(HOLD_SLOTS):
        if loc.res_hold[j] == std.NULL:
            free = j
            break
    if not out.reserve(records={"stock_reserved": 1, "stock_rejected": 1}, creates={"hold": 1},
                       timers=1, requests=1):
        return RETRY
    if s.on_hand[i] - s.reserved[i] < cmd.quantity or free < 0:
        why = WHY_STOCK if s.on_hand[i] - s.reserved[i] < cmd.quantity else WHY_BUSY
        out.emit_stock_rejected(ctx.t, sku_group=ctx.self_id, sku_id=cmd.sku_id,
                                checkout_id=cmd.tag, quantity=cmd.quantity, reason=why)
        out.respond(cmd, "rejected", hold_id=std.NULL, slot=-1, line=cmd.line)
        return COMMIT
    hold = out.new_id("hold")
    loc.res_hold[free] = hold
    loc.res_item[free] = i
    loc.res_qty[free] = cmd.quantity
    loc.res_ckt[free] = cmd.tag
    s.reserved[i] = std.checked_add(s.reserved[i], cmd.quantity)
    out.emit_stock_reserved(ctx.t, sku_group=ctx.self_id, sku_id=cmd.sku_id, checkout_id=cmd.tag,
                            hold_id=hold, quantity=cmd.quantity)
    out.timer(ctx.t + ctx.cfg.hold_ttl_s * 1_000_000, C_HOLD_EXPIRE, prio=PRIO_TIMER, tag=hold)
    out.respond(cmd, "granted", hold_id=hold, slot=free, line=cmd.line)
    return COMMIT


def _settle_hold(ctx, s, loc, cmd, out):
    j = cmd.slot
    live = j >= 0 and j < HOLD_SLOTS and loc.res_hold[j] == cmd.hold_id
    if cmd.kind == C_RELEASE and not live:
        return reject(REJ_STALE)                           # the hold expired already
    if not out.reserve(records={"stock_committed": 1, "stock_released": 1,
                                "stock_commit_late": 1}):
        return RETRY
    if not live:                                           # D49: commit after the TTL
        out.emit_stock_commit_late(ctx.t, sku_group=ctx.self_id, sku_id=cmd.sku_id,
                                   checkout_id=cmd.tag, hold_id=cmd.hold_id,
                                   quantity=cmd.quantity)
        return COMMIT
    i = loc.res_item[j]
    q = loc.res_qty[j]
    s.reserved[i] = std.checked_sub(s.reserved[i], q)
    if cmd.kind == C_COMMIT:
        s.on_hand[i] = std.checked_sub(s.on_hand[i], q)
        out.emit_stock_committed(ctx.t, sku_group=ctx.self_id, sku_id=cmd.sku_id,
                                 checkout_id=cmd.tag, hold_id=cmd.hold_id, quantity=q,
                                 on_hand_after=s.on_hand[i])
    else:
        out.emit_stock_released(ctx.t, sku_group=ctx.self_id, sku_id=cmd.sku_id,
                                checkout_id=cmd.tag, hold_id=cmd.hold_id, quantity=q)
    loc.res_hold[j] = std.NULL
    return COMMIT


def _expire(ctx, s, loc, cmd, out):
    j = -1
    for k in range(HOLD_SLOTS):
        if loc.res_hold[k] == cmd.tag:
            j = k
            break
    if j < 0:
        return reject(REJ_STALE)                           # committed or released in time
    if not out.reserve(records={"stock_expired": 1}):
        return RETRY
    i = loc.res_item[j]
    q = loc.res_qty[j]
    s.reserved[i] = std.checked_sub(s.reserved[i], q)
    out.emit_stock_expired(ctx.t, sku_group=ctx.self_id, sku_id=s.sku[i],
                           checkout_id=loc.res_ckt[j], hold_id=cmd.tag, quantity=q)
    loc.res_hold[j] = std.NULL
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
            qty = 1 + ctx.rng.uniform_int(site=1, lo=0, hi=gap - 1)
            s.on_hand[i] = std.checked_add(s.on_hand[i], qty)
            out.emit_restocked(ctx.t, sku_group=ctx.self_id, sku_id=s.sku[i], quantity=qty,
                               on_hand_after=s.on_hand[i])
    if stop < s.n_sku:
        out.continue_at(ctx.t, cursor=stop)
    return COMMIT


# ================================================================== referral pool
@kernel(state="referral_pool", commands=(C_CLAIM, C_REFUND),
        max=Res(records={"bonus_granted": 1, "bonus_rejected": 1, "bonus_refunded": 1},
                requests=1))
def pool_desk(ctx, s, cmd, out):
    """Claims are whole or rejected; the budget resets lazily on the first claim of a new
    period window (`ctx.t // period`, epoch-aligned like law.total_le(per=), D91). A refund
    of a late grant (D67) books the money back without reopening the period's budget, so
    `chk.referral_budget` on granted amounts stays exact."""
    if cmd.kind == C_REFUND:
        if not out.reserve(records={"bonus_refunded": 1}):
            return RETRY
        s.granted = std.checked_sub(s.granted, cmd.amount)
        out.emit_bonus_refunded(ctx.t, claim_id=cmd.claim_id, amount=cmd.amount)
        return COMMIT
    if not out.reserve(records={"bonus_granted": 1, "bonus_rejected": 1}, requests=1):
        return RETRY
    w = ctx.t // ctx.cfg.period_us
    if w != s.window:
        s.window = w
        s.remaining = ctx.cfg.budget
    g = std.capped_pool.take(s.remaining, cmd.amount)
    if g > 0:
        s.remaining = std.checked_sub(s.remaining, g)
        s.granted = std.checked_add(s.granted, g)
        out.emit_bonus_granted(ctx.t, claim_id=cmd.claim_id, amount=g,
                               remaining_after=s.remaining)
        out.respond(cmd, "granted", claim_id=cmd.claim_id, amount=g)
    else:
        out.emit_bonus_rejected(ctx.t, claim_id=cmd.claim_id, amount=cmd.amount)
        out.respond(cmd, "rejected", claim_id=cmd.claim_id, amount=0)
    return COMMIT


# ================================================================== fulfillment actions
@action(state="order", max=Res(records={"order_shipped": 1}))
def ship(ctx, s, m, cmd, out):
    s.status = "shipped"
    out.emit_order_shipped(ctx.t, user_id=s.user_id, order_id=m.id,
                           carrier=ctx.rng.categorical(site=1, p=(0.4, 0.3, 0.2, 0.1)))
    return COMMIT


@action(state="order", max=Res(records={"order_delivered": 1}))
def deliver(ctx, s, m, cmd, out):
    s.status = "delivered"
    out.emit_order_delivered(ctx.t, user_id=s.user_id, order_id=m.id, category=s.category)
    return COMMIT


@action(state="order", max=Res(records={"order_lost": 1}))
def lose(ctx, s, m, cmd, out):
    s.status = "lost"
    out.emit_order_lost(ctx.t, user_id=s.user_id, order_id=m.id)
    return COMMIT


@action(state="order", max=Res(records={"return_requested": 1}))
def request_return(ctx, s, m, cmd, out):
    out.emit_return_requested(ctx.t, user_id=s.user_id, order_id=m.id,
                              reason=ctx.rng.categorical(site=1, p=(0.3, 0.15, 0.2, 0.3, 0.05)))
    return COMMIT


@action(state="order", max=Res(records={"refund_issued": 1}))
def refund_return(ctx, s, m, cmd, out):
    left = s.amount - s.refunded
    if left <= 0:
        return reject(REJ_NOTHING_TO_REFUND)
    s.refunded = std.checked_add(s.refunded, left)
    s.status = "returned"
    out.emit_refund_issued(ctx.t, user_id=s.user_id, order_id=m.id, amount=left)
    return COMMIT


# ================================================================== exposed to overlays (§08)
@action(state="user", max=Res(records={"user_signed_up": 1}), fields={"device": "ref"})
def signup(ctx, s, m, cmd, out):
    out.emit_user_signed_up(ctx.t, user_id=m.id, device_id=m.device, acquisition="social_ad",
                            referred=0, invited_by=std.NULL)
    return COMMIT


@action(state="user", max=Res(records={"user_signed_up": 1}), fields={"device": "ref"})
def signup_invited(ctx, s, m, cmd, out):
    out.emit_user_signed_up(ctx.t, user_id=m.id, device_id=m.device, acquisition="invite",
                            referred=1, invited_by=m.parent_id)
    return COMMIT


@action(state="user", max=Res(records={"order_placed": 1}, creates={"order": 1, "checkout": 1}),
        fields={"device": "ref", "amount": "i64"})
def quick_order(ctx, s, m, cmd, out):
    """A one-line order of `m.amount` without a cart or stock reservation (the order still
    runs the fulfillment machine)."""
    sku = ctx.reads.sku.sample_by_weight(ctx.rng.uniform(site=1))
    category = ctx.reads.sku.category[sku]
    order = out.create_order(user_id=m.id, amount=m.amount, lines=1, category=category,
                             credit_used=0, refunded=0, status="placed")
    out.emit_order_placed(ctx.t, user_id=m.id, order_id=order,
                          checkout_id=out.new_id("checkout"), device_id=m.device, sku_id=sku,
                          lines=1, amount=m.amount, credit_used=0, category=category)
    return COMMIT


@action(state="user", max=Res(records={"referral_bonus_paid": 2}), fields={"paid": "i64"})
def pay_referral(ctx, s, m, cmd, out):
    """Both halves of a granted referral claim: the invitee and its inviter (the parent)."""
    half = m.paid // 2
    out.emit_referral_bonus_paid(ctx.t, user_id=m.id, invitee_id=m.id, role="invitee",
                                 amount=half)
    out.emit_referral_bonus_paid(ctx.t, user_id=m.parent_id, invitee_id=m.id, role="inviter",
                                 amount=m.paid - half)
    return COMMIT
