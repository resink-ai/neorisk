from neorisk_simkit import std
from neorisk_simkit.engine import COMMIT, PRIO_TIMER, RETRY, START, Local, Res, kernel, reject

C_SUBSTITUTE, R_GRANTED, R_REJECTED = 1, 2, 3
JOURNEY_COMMANDS = (START, C_SUBSTITUTE, R_GRANTED, R_REJECTED)
C_RESERVE, C_RELEASE, C_COMMIT = 1, 2, 3
SKU_A, SKU_B, SKU_C = 0, 1, 2
REJ_LIMIT, REJ_STALE = 1, 2

LOCAL = Local(checkout="ref", pending="i8", granted="u8", failed_sku="ref", lines="i8",
              sku="ref[2]")


@kernel(state="user", local=LOCAL, commands=JOURNEY_COMMANDS,
        max=Res(records={"checkout_started": 1, "checkout_failed": 1, "checkout_succeeded": 1},
                creates={"checkout": 1, "payment": 1}, timers=1, requests=3))
def journey(ctx, s, loc, cmd, out):
    cfg = ctx.cfg
    if cmd.kind == START:                                 # 10:00:00.0: check out A and B
        return _start_checkout(ctx, s, loc, out, cfg, SKU_A, SKU_B, 2)
    if cmd.kind == C_SUBSTITUTE:                          # 10:02:10.0: substitute C
        return _start_checkout(ctx, s, loc, out, cfg, SKU_C, SKU_C, 1)
    return _on_response(ctx, s, loc, cmd, out, cfg)


def _start_checkout(ctx, s, loc, out, cfg, a, b, lines):
    limit = cfg.spend_limit
    if limit - s.hold - s.spent < cfg.hold:               # validate the owner side first
        return reject(REJ_LIMIT)
    if not out.reserve(records={"checkout_started": 1}, creates={"checkout": 1},
                       requests=lines):
        return RETRY
    s.spend_limit = limit
    s.hold = std.checked_add(s.hold, cfg.hold)            # the owner holds its side
    loc.checkout = out.new_id("checkout")
    loc.pending, loc.granted, loc.failed_sku, loc.lines = lines, 0, std.NULL, lines
    loc.sku[0] = a
    loc.sku[1] = b
    out.emit_checkout_started(ctx.t, user_id=ctx.self_id, checkout_id=loc.checkout,
                              lines=lines, hold_after=s.hold)
    for j in range(lines):                                # immutable payloads, one per shard
        out.request_reserve(ctx.t, shard=ctx.reads.sku.sku_group[loc.sku[j]],
                            tag=loc.checkout, sku_id=loc.sku[j])
    return COMMIT                                         # suspends: join of `lines`


def _line_of(loc, sku_id):
    if loc.sku[0] == sku_id:
        return 0
    return 1


def _on_response(ctx, s, loc, cmd, out, cfg):
    if cmd.tag != loc.checkout or loc.pending == 0:
        return reject(REJ_STALE)
    if not out.reserve(records={"checkout_failed": 1, "checkout_succeeded": 1},
                       creates={"payment": 1}, timers=1, requests=2):
        return RETRY
    if cmd.kind == R_GRANTED:
        loc.granted |= 1 << _line_of(loc, cmd.sku_id)
    else:
        loc.failed_sku = cmd.sku_id
    loc.pending -= 1
    if loc.pending > 0:
        return COMMIT
    if loc.granted == (1 << loc.lines) - 1:               # every line granted: commit all
        s.hold = std.checked_sub(s.hold, cfg.hold)
        s.spent = std.checked_add(s.spent, cfg.hold)
        for j in range(loc.lines):
            out.send_commit(ctx.t, to=ctx.reads.sku.sku_group[loc.sku[j]], tag=loc.checkout,
                            sku_id=loc.sku[j])
        pay = out.create_payment(user_id=ctx.self_id, amount=cfg.hold)
        out.emit_checkout_succeeded(ctx.t, user_id=ctx.self_id, checkout_id=loc.checkout,
                                    payment_id=pay, spent_after=s.spent)
    else:                                                 # release all, release the hold
        s.hold = std.checked_sub(s.hold, cfg.hold)
        for j in range(loc.lines):
            if loc.granted & (1 << j):
                out.send_release(ctx.t, to=ctx.reads.sku.sku_group[loc.sku[j]],
                                 tag=loc.checkout, sku_id=loc.sku[j])
        out.emit_checkout_failed(ctx.t, user_id=ctx.self_id, checkout_id=loc.checkout,
                                 reason="out_of_stock", sku_id=loc.failed_sku,
                                 hold_after=s.hold)
        out.timer(ctx.t + cfg.substitute_after_us, C_SUBSTITUTE, prio=PRIO_TIMER)
    loc.checkout = std.NULL
    return COMMIT


@kernel(state="payment", commands=(START,), max=Res(records={"payment_created": 1}))
def payment_start(ctx, s, cmd, out):
    if not out.reserve(records={"payment_created": 1}):
        return RETRY
    out.emit_payment_created(ctx.t, payment_id=ctx.self_id, user_id=s.user_id, amount=s.amount)
    return COMMIT


@kernel(state="inventory", commands=(C_RESERVE, C_RELEASE, C_COMMIT),
        max=Res(records={"stock_reserved": 1, "stock_rejected": 1, "stock_released": 1,
                         "stock_committed": 1}, requests=1))
def desk(ctx, s, cmd, out):
    i = ctx.reads.sku.local_index[cmd.sku_id]
    if not out.reserve(records={"stock_reserved": 1, "stock_rejected": 1,
                                "stock_released": 1, "stock_committed": 1}, requests=1):
        return RETRY
    if cmd.kind == C_RESERVE:
        if s.on_hand[i] - s.reserved[i] >= 1:
            s.reserved[i] += 1
            out.emit_stock_reserved(ctx.t, sku_id=cmd.sku_id, checkout_id=cmd.tag)
            out.respond(cmd, "granted", sku_id=cmd.sku_id)
        else:
            out.emit_stock_rejected(ctx.t, sku_id=cmd.sku_id, checkout_id=cmd.tag)
            out.respond(cmd, "rejected", sku_id=cmd.sku_id)
        return COMMIT
    s.reserved[i] -= 1
    if cmd.kind == C_COMMIT:
        s.on_hand[i] -= 1
        out.emit_stock_committed(ctx.t, sku_id=cmd.sku_id, checkout_id=cmd.tag)
    else:
        out.emit_stock_released(ctx.t, sku_id=cmd.sku_id, checkout_id=cmd.tag)
    return COMMIT
