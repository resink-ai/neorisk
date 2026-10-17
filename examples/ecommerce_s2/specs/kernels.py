"""Handwritten kernels for the S2 slice (spec §18 S2).

Every kernel: validate (draws allowed, no writes) -> out.reserve(...) -> commit. Each draw has
its own site number within its process.
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

CART = 4                                  # cart lines (Local array width)
HOLD_SLOTS = 64                           # holds per inventory shard (std.reservations table)
IDEM_SLOTS = 4                            # refund idempotency keys per payment (pack: max_refunds)
C_SESSION, C_VIEW, C_CHECKOUT, R_GRANTED, R_REJECTED, C_BILL = 1, 2, 3, 4, 5, 6
SHOPPER_COMMANDS = (START, C_SESSION, C_VIEW, C_CHECKOUT, R_GRANTED, R_REJECTED, C_BILL)
C_RESERVE, C_COMMIT, C_RELEASE, C_HOLD_EXPIRE = 1, 2, 3, 4
DESK_COMMANDS = (C_RESERVE, C_COMMIT, C_RELEASE, C_HOLD_EXPIRE)
REJ_DORMANT, REJ_NO_CART, REJ_STALE = 1, 2, 3
WHY_STOCK, WHY_BUSY = 0, 1                # stock_rejected.reason codes
C_CAPTURE, C_AUTH_EXPIRE, C_WINDOW = 1, 2, 3
C_REFUND, C_REFUND_DUP, C_SETTLE, C_DISPUTE, C_RESOLVE = 4, 5, 6, 7, 8
PAYMENT_COMMANDS = (START, C_CAPTURE, C_AUTH_EXPIRE, C_WINDOW, C_REFUND, C_REFUND_DUP, C_SETTLE,
                    C_DISPUTE, C_RESOLVE)
P_AUTHORIZED, P_CAPTURED, P_EXPIRED, P_DECLINED = 1, 2, 3, 4
D_NONE, D_OPEN, D_WON, D_LOST = 0, 1, 2, 3
R_REQUESTED, R_SETTLED, R_FAILED, R_REJECTED_IDEM = 0, 1, 2, 3
(A_CUSTOMER_FUNDS, A_CUSTOMER_HELD, A_MERCHANT, A_PLATFORM_FEES, A_REFUNDS_PAYABLE,
 A_DISPUTE_RESERVE) = 0, 1, 2, 3, 4, 5                # ledger.account codes
DAY = 86_400_000_000

SHOPPER_LOCAL = Local(session="ref", device="ref", views_left="i16", cart_n="i8",
                      cart_sku="ref[4]", cart_qty="i16[4]", cart_price="i64[4]",
                      checkout="ref", subtotal="i64", pending="i8", granted="u8",
                      rejected_sku="ref", hold="ref[4]", slot="i32[4]")
DESK_LOCAL = Local(**std.reservations.fields(HOLD_SLOTS))
PAY_LOCAL = Local(status="i8", captured="i64", refunded="i64", refund_hold="i64",
                  refunds="i8", dispute="i8", disputed="i64", window_end="i64",
                  idem_key=f"ref[{IDEM_SLOTS}]", idem_result=f"i8[{IDEM_SLOTS}]",
                  idem_amount=f"i64[{IDEM_SLOTS}]", idem_n="i8")


@kernel(state="user", local=SHOPPER_LOCAL, commands=SHOPPER_COMMANDS,
        max=Res(records={"user_signed_up": 1, "session_started": 1, "product_viewed": 1,
                         "cart_item_added": 1, "checkout_started": 1, "checkout_failed": 1,
                         "checkout_abandoned": 1, "checkout_succeeded": 1,
                         "bill_payment_started": 1},
                creates={"session": 1, "checkout": 1, "payment": 1}, timers=2, requests=CART))
def shopper(ctx, s, loc, cmd, out):
    cfg = ctx.cfg
    if cmd.kind == START:
        return _signup(ctx, s, out, cfg)
    if cmd.kind == C_SESSION:
        return _session(ctx, s, loc, out, cfg)
    if cmd.kind == C_VIEW:
        return _view(ctx, loc, out, cfg)
    if cmd.kind == C_CHECKOUT:
        return _checkout(ctx, s, loc, out)
    if cmd.kind == C_BILL:
        return _bill(ctx, out, cfg)
    return _answer(ctx, s, loc, cmd, out, cfg)


def _signup(ctx, s, out, cfg):
    delay = ctx.rng.dist_us(site=1, d=cfg.signup_delay)
    bill = ctx.rng.dist_us(site=6, d=cfg.bill_gap)
    if not out.reserve(records={"user_signed_up": 1}, timers=2):
        return RETRY
    out.emit_user_signed_up(ctx.t, user_id=ctx.self_id,
                            device_id=ctx.refs.device.get(ctx.self_id, 0),
                            acquisition=s.acquisition, referred=s.referred)
    out.timer(ctx.t + delay, C_SESSION, prio=PRIO_TIMER)
    out.timer(ctx.t + bill, C_BILL, prio=PRIO_TIMER)
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
    views = min(ctx.rng.geometric(site=3, mean=cfg.views_mean), 30)
    gap = ctx.rng.pareto_us(site=4, alpha=cfg.session_gap_alpha, min_h=cfg.session_gap_min_h)
    first = ctx.rng.dist_us(site=5, d=cfg.view_gap)
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
    hot = ctx.rng.bernoulli(site=12, p=cfg.hot_pick_p)
    sku = ctx.reads.sku.sample_by_weight(ctx.rng.uniform(site=13))
    if hot:                                                # D53: the hot group's SKUs
        sku = ctx.rng.uniform_int(site=14, lo=0, hi=cfg.hot_skus - 1)
    add = ctx.rng.bernoulli(site=15, p=cfg.add_to_cart_p)
    qty = ctx.rng.geometric(site=16, mean=1.25)
    pos = ctx.rng.geometric(site=17, mean=5.0)
    nxt = ctx.rng.dist_us(site=18, d=cfg.view_gap)
    if not out.reserve(records={"product_viewed": 1, "cart_item_added": 1}, timers=1):
        return RETRY
    price = ctx.reads.sku.price[sku]
    out.emit_product_viewed(ctx.t, user_id=ctx.self_id, session_id=loc.session, sku_id=sku,
                            device_id=loc.device, position=pos, channel=_channel(ctx, loc.device),
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


def _checkout(ctx, s, loc, out):
    if loc.cart_n == 0 or loc.checkout != std.NULL:
        return reject(REJ_NO_CART)
    total = 0
    for i in range(loc.cart_n):
        total = std.checked_add(total, std.checked_mul(loc.cart_price[i], loc.cart_qty[i]))
    if not out.reserve(records={"checkout_started": 1, "checkout_failed": 1},
                       creates={"checkout": 1}, requests=CART):
        return RETRY
    loc.checkout = out.new_id("checkout")
    if std.checked_add(s.held, total) > s.credit_limit:    # the owner's side of the hold
        out.emit_checkout_failed(ctx.t, user_id=ctx.self_id, checkout_id=loc.checkout,
                                 reason="credit_limit", hold_after=s.held)
        loc.checkout = std.NULL
        loc.cart_n = 0
        return COMMIT
    s.held = std.checked_add(s.held, total)
    loc.subtotal = total
    loc.pending = loc.cart_n
    loc.granted = 0
    loc.rejected_sku = std.NULL
    out.emit_checkout_started(ctx.t, user_id=ctx.self_id, session_id=loc.session,
                              checkout_id=loc.checkout, lines=loc.cart_n, subtotal=total,
                              hold_after=s.held)
    hot = 0
    for i in range(loc.cart_n):                            # one immutable request per line
        grp = ctx.reads.sku.sku_group[loc.cart_sku[i]]
        if grp == 0:
            hot = 1
        out.request_reserve(ctx.t, shard=grp, tag=loc.checkout, sku_id=loc.cart_sku[i],
                            quantity=loc.cart_qty[i], line=i)
    out.add_hot_checkouts(hot)                             # D53: a checkout reaching group 0
    return COMMIT                                          # suspends: join of cart_n answers


def _answer(ctx, s, loc, cmd, out, cfg):
    if cmd.tag != loc.checkout or loc.pending <= 0:
        return reject(REJ_STALE)
    abandon = ctx.rng.bernoulli(site=20, p=cfg.abandon_p)
    substitute = ctx.rng.bernoulli(site=21, p=cfg.substitute_p)
    more = ctx.rng.geometric(site=22, mean=3.0)
    nxt = ctx.rng.dist_us(site=23, d=cfg.view_gap)
    method = ctx.rng.categorical(site=24, p=(0.7, 0.22, 0.08))
    if not out.reserve(records={"checkout_failed": 1, "checkout_abandoned": 1,
                                "checkout_succeeded": 1}, creates={"payment": 1}, timers=1,
                       requests=CART):
        return RETRY
    line = cmd.line
    if cmd.kind == R_GRANTED:
        loc.granted |= 1 << line
        loc.hold[line] = cmd.hold_id
        loc.slot[line] = cmd.slot
    else:
        loc.rejected_sku = loc.cart_sku[line]
    loc.pending -= 1
    if loc.pending > 0:
        return COMMIT                                      # join: wait for the other lines
    s.held = std.checked_sub(s.held, loc.subtotal)         # the owner commits or releases
    if loc.granted == (1 << loc.cart_n) - 1:
        if abandon:                                        # holds left to the shards' TTL
            out.emit_checkout_abandoned(ctx.t, user_id=ctx.self_id, checkout_id=loc.checkout,
                                        hold_after=s.held)
        else:
            for i in range(loc.cart_n):
                out.send_commit(ctx.t, to=ctx.reads.sku.sku_group[loc.cart_sku[i]],
                                tag=loc.checkout, sku_id=loc.cart_sku[i],
                                quantity=loc.cart_qty[i], hold_id=loc.hold[i], slot=loc.slot[i])
            pay = out.create_payment(user_id=ctx.self_id, checkout_id=loc.checkout,
                                     amount=loc.subtotal, method=method, source="checkout")
            out.emit_checkout_succeeded(ctx.t, user_id=ctx.self_id, checkout_id=loc.checkout,
                                        payment_id=pay, amount=loc.subtotal, hold_after=s.held)
    else:
        for i in range(loc.cart_n):
            if loc.granted & (1 << i):
                out.send_release(ctx.t, to=ctx.reads.sku.sku_group[loc.cart_sku[i]],
                                 tag=loc.checkout, sku_id=loc.cart_sku[i],
                                 quantity=loc.cart_qty[i], hold_id=loc.hold[i],
                                 slot=loc.slot[i])
        out.emit_checkout_failed(ctx.t, user_id=ctx.self_id, checkout_id=loc.checkout,
                                 reason="out_of_stock", sku_id=loc.rejected_sku,
                                 hold_after=s.held)
        if substitute:
            loc.views_left = more
            out.timer(ctx.t + nxt, C_VIEW, prio=PRIO_TIMER)
    loc.checkout = std.NULL
    loc.cart_n = 0
    return COMMIT


def _bill(ctx, out, cfg):
    amt = max(100, ctx.rng.lognormal_minor(site=40, median=cfg.bill_median,
                                           sigma=cfg.bill_sigma))
    method = ctx.rng.categorical(site=41, p=(0.8, 0.2, 0.0))
    nxt = ctx.rng.dist_us(site=42, d=cfg.bill_gap)
    if not out.reserve(records={"bill_payment_started": 1}, creates={"payment": 1}, timers=1):
        return RETRY                                       # + its creation message (automatic)
    pay = out.create_payment(user_id=ctx.self_id, checkout_id=std.NULL, amount=amt,
                             method=method, source="bill")
    out.emit_bill_payment_started(ctx.t, user_id=ctx.self_id, payment_id=pay, amount=amt)
    out.timer(ctx.t + nxt, C_BILL, prio=PRIO_TIMER)
    return COMMIT


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


@kernel(state="payment", local=PAY_LOCAL, commands=PAYMENT_COMMANDS,
        max=Res(records={"payment_authorized": 1, "payment_declined": 1,
                         "payment_captured": 1, "payment_expired": 1, "refund_requested": 1,
                         "refund_rejected": 1, "refund_settled": 1, "refund_failed": 1,
                         "refund_replayed": 1, "dispute_opened": 1, "dispute_won": 1,
                         "dispute_lost": 1, "ledger": 3},
                creates={"refund": 1}, timers=3))
def payment_life(ctx, s, loc, cmd, out):
    cfg = ctx.cfg
    if cmd.kind == START:
        return _authorize(ctx, s, loc, out, cfg)
    if cmd.kind == C_CAPTURE:
        return _capture(ctx, s, loc, out, cfg)
    if cmd.kind == C_AUTH_EXPIRE:
        return _auth_expire(ctx, s, loc, out)
    if cmd.kind == C_REFUND:
        return _refund(ctx, loc, out, cfg)
    if cmd.kind == C_REFUND_DUP:
        return _replay(ctx, loc, cmd, out)
    if cmd.kind == C_SETTLE:
        return _settle(ctx, loc, cmd, out, cfg)
    if cmd.kind == C_DISPUTE:
        return _dispute(ctx, loc, out, cfg)
    if cmd.kind == C_RESOLVE:
        return _resolve(ctx, loc, out, cfg)
    return COMMIT                         # C_WINDOW: the dispute window closed; idle -> retire


def _post(ctx, out, debit, credit, amt):
    out.emit_ledger(ctx.t, payment_id=ctx.self_id, account=debit, side="debit", amount=amt)
    out.emit_ledger(ctx.t, payment_id=ctx.self_id, account=credit, side="credit", amount=amt)


def _authorize(ctx, s, loc, out, cfg):
    declined = ctx.rng.bernoulli(site=1, p=cfg.decline_p)
    capture = ctx.rng.bernoulli(site=2, p=cfg.capture_p)
    delay = ctx.rng.dist_us(site=3, d=cfg.capture_delay)
    if not out.reserve(records={"payment_authorized": 1, "payment_declined": 1, "ledger": 2},
                       timers=2):
        return RETRY
    if declined:
        loc.status = P_DECLINED
        out.emit_payment_declined(ctx.t, payment_id=ctx.self_id, user_id=s.user_id,
                                  amount=s.amount)
        return COMMIT                                      # nothing queued: retires
    loc.status = P_AUTHORIZED
    out.emit_payment_authorized(ctx.t, payment_id=ctx.self_id, user_id=s.user_id,
                                amount=s.amount, method=s.method, source=s.source)
    _post(ctx, out, A_CUSTOMER_FUNDS, A_CUSTOMER_HELD, s.amount)
    out.timer(ctx.t + cfg.auth_expiry_s * 1_000_000, C_AUTH_EXPIRE, prio=PRIO_EXPIRY)
    if capture:
        out.timer(ctx.t + delay, C_CAPTURE, prio=PRIO_TIMER)
    return COMMIT


def _capture(ctx, s, loc, out, cfg):
    if loc.status != P_AUTHORIZED:
        return reject(REJ_STALE)                           # expiry won the race
    refund = ctx.rng.bernoulli(site=4, p=cfg.refund_p)
    rgap = ctx.rng.dist_us(site=5, d=cfg.refund_gap)
    dispute = ctx.rng.bernoulli(site=6, p=cfg.dispute_p)
    dgap = ctx.rng.dist_us(site=7, d=cfg.dispute_delay)
    if not out.reserve(records={"payment_captured": 1, "ledger": 3}, timers=3):
        return RETRY
    fee = std.checked_mul(s.amount, cfg.fee_bps) // 10_000
    loc.status = P_CAPTURED
    loc.captured = s.amount
    loc.window_end = ctx.t + cfg.dispute_window_days * DAY
    out.emit_payment_captured(ctx.t, payment_id=ctx.self_id, amount=s.amount, fee=fee)
    out.emit_ledger(ctx.t, payment_id=ctx.self_id, account=A_CUSTOMER_HELD, side="debit",
                    amount=s.amount)
    out.emit_ledger(ctx.t, payment_id=ctx.self_id, account=A_MERCHANT, side="credit",
                    amount=s.amount - fee)
    out.emit_ledger(ctx.t, payment_id=ctx.self_id, account=A_PLATFORM_FEES, side="credit",
                    amount=fee)
    out.add_platform_fees(fee)
    out.timer(loc.window_end, C_WINDOW, prio=PRIO_TIMER)
    if refund:
        out.timer(ctx.t + rgap, C_REFUND, prio=PRIO_TIMER)
    if dispute and ctx.t + dgap < loc.window_end:
        out.timer(ctx.t + dgap, C_DISPUTE, prio=PRIO_TIMER)
    return COMMIT


def _auth_expire(ctx, s, loc, out):
    if loc.status != P_AUTHORIZED:
        return reject(REJ_STALE)                           # captured first
    if not out.reserve(records={"payment_expired": 1, "ledger": 2}):
        return RETRY
    loc.status = P_EXPIRED
    out.emit_payment_expired(ctx.t, payment_id=ctx.self_id, amount=s.amount)
    _post(ctx, out, A_CUSTOMER_HELD, A_CUSTOMER_FUNDS, s.amount)
    return COMMIT


def _find(loc, key):
    for j in range(loc.idem_n):
        if loc.idem_key[j] == key:
            return j
    return -1


def _refund(ctx, loc, out, cfg):
    if loc.status != P_CAPTURED or loc.refunds >= cfg.max_refunds or loc.idem_n >= IDEM_SLOTS:
        return reject(REJ_STALE)
    want = max(1, ctx.rng.lognormal_minor(site=10, median=cfg.refund_median,
                                          sigma=cfg.refund_sigma))
    settle = ctx.rng.dist_us(site=11, d=cfg.refund_settle)
    dup = ctx.rng.bernoulli(site=12, p=cfg.duplicate_p)
    dup_gap = ctx.rng.dist_us(site=13, d=cfg.duplicate_gap)
    again = ctx.rng.bernoulli(site=14, p=cfg.refund_p)
    gap = ctx.rng.dist_us(site=15, d=cfg.refund_gap)
    if not out.reserve(records={"refund_requested": 1, "refund_rejected": 1},
                       creates={"refund": 1}, timers=3):
        return RETRY
    rid = out.new_id("refund")
    k = loc.idem_n
    loc.idem_key[k] = rid
    loc.idem_n = k + 1
    loc.refunds += 1
    left = loc.captured - loc.refunded - loc.refund_hold
    if loc.dispute == D_OPEN:                              # §09: rejected while disputed
        loc.idem_result[k] = R_REJECTED_IDEM
        out.emit_refund_rejected(ctx.t, payment_id=ctx.self_id, refund_id=rid,
                                 reason="dispute_open")
    elif left <= 0 or loc.dispute == D_LOST:
        loc.idem_result[k] = R_REJECTED_IDEM
        out.emit_refund_rejected(ctx.t, payment_id=ctx.self_id, refund_id=rid,
                                 reason="nothing_left")
    else:
        amt = std.checked_min(left, want)
        loc.refund_hold = std.checked_add(loc.refund_hold, amt)          # the hold
        loc.idem_result[k] = R_REQUESTED
        loc.idem_amount[k] = amt
        out.emit_refund_requested(ctx.t, payment_id=ctx.self_id, refund_id=rid, amount=amt)
        out.timer(ctx.t + settle, C_SETTLE, prio=PRIO_TIMER, tag=rid)
    if dup:                                                # the merchant retries the key
        out.timer(ctx.t + dup_gap, C_REFUND_DUP, prio=PRIO_TIMER, tag=rid)
    if again and loc.refunds < cfg.max_refunds:
        out.timer(ctx.t + gap, C_REFUND, prio=PRIO_TIMER)
    return COMMIT


def _settle(ctx, loc, cmd, out, cfg):
    j = _find(loc, cmd.tag)
    if j < 0 or loc.idem_result[j] != R_REQUESTED:
        return reject(REJ_STALE)
    fail = ctx.rng.bernoulli(site=20, p=cfg.refund_fail_p)
    if not out.reserve(records={"refund_settled": 1, "refund_failed": 1, "ledger": 2}):
        return RETRY
    amt = loc.idem_amount[j]
    loc.refund_hold = std.checked_sub(loc.refund_hold, amt)
    if fail:                                               # release the hold
        loc.idem_result[j] = R_FAILED
        out.emit_refund_failed(ctx.t, payment_id=ctx.self_id, refund_id=cmd.tag, amount=amt)
    else:                                                  # commit the hold
        loc.refunded = std.checked_add(loc.refunded, amt)
        loc.idem_result[j] = R_SETTLED
        out.emit_refund_settled(ctx.t, payment_id=ctx.self_id, refund_id=cmd.tag, amount=amt,
                                refunded_after=loc.refunded)
        _post(ctx, out, A_MERCHANT, A_REFUNDS_PAYABLE, amt)
    return COMMIT


def _replay(ctx, loc, cmd, out):
    j = _find(loc, cmd.tag)
    if j < 0:
        return reject(REJ_STALE)
    if not out.reserve(records={"refund_replayed": 1}):
        return RETRY
    first = 1 if loc.idem_result[j] == R_REJECTED_IDEM else 0     # requested | rejected
    out.emit_refund_replayed(ctx.t, payment_id=ctx.self_id, refund_id=cmd.tag, result=first)
    return COMMIT


def _dispute(ctx, loc, out, cfg):
    if loc.status != P_CAPTURED or loc.dispute != D_NONE or ctx.t >= loc.window_end:
        return reject(REJ_STALE)
    # the remainder no refund has claimed: held refunds still settle or fail on their own, so
    # disputing them too would let a lost dispute return more than the capture (review I-1)
    amt = loc.captured - loc.refunded - loc.refund_hold
    if amt <= 0:
        return reject(REJ_STALE)                           # nothing left to dispute
    resolve = ctx.rng.dist_us(site=30, d=cfg.dispute_resolve)
    if not out.reserve(records={"dispute_opened": 1, "ledger": 2}, timers=1):
        return RETRY
    loc.dispute = D_OPEN
    loc.disputed = amt
    out.emit_dispute_opened(ctx.t, payment_id=ctx.self_id, amount=amt)
    _post(ctx, out, A_MERCHANT, A_DISPUTE_RESERVE, amt)
    out.timer(ctx.t + resolve, C_RESOLVE, prio=PRIO_TIMER)
    return COMMIT


def _resolve(ctx, loc, out, cfg):
    if loc.dispute != D_OPEN:
        return reject(REJ_STALE)
    won = ctx.rng.bernoulli(site=31, p=cfg.dispute_win_p)
    if not out.reserve(records={"dispute_won": 1, "dispute_lost": 1, "ledger": 2}):
        return RETRY
    if won:
        loc.dispute = D_WON
        out.emit_dispute_won(ctx.t, payment_id=ctx.self_id, amount=loc.disputed)
        _post(ctx, out, A_DISPUTE_RESERVE, A_MERCHANT, loc.disputed)
    else:
        loc.dispute = D_LOST
        out.emit_dispute_lost(ctx.t, payment_id=ctx.self_id, amount=loc.disputed)
        _post(ctx, out, A_DISPUTE_RESERVE, A_CUSTOMER_FUNDS, loc.disputed)
    return COMMIT
