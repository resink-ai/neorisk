from neorisk_simkit import std
from neorisk_simkit.engine import COMMIT, PRIO_TIMER, RETRY, START, Res, action, kernel, reject

R_OK, R_NO, C_CLAIM, C_GO, C_REFUND = 1, 2, 1, 3, 2
USER_COMMANDS = (START, R_OK, R_NO, C_GO)
S = 1_000_000


@kernel(state="user", commands=USER_COMMANDS,
        max=Res(records={"order_placed": 1, "bonus_paid": 1}, timers=1, requests=1))
def user_main(ctx, s, cmd, out):
    if cmd.kind == START:
        if not out.reserve(timers=1):
            return RETRY
        out.timer(ctx.t + ctx.cfg.claim_at_s * S, C_GO, prio=PRIO_TIMER)
        return COMMIT
    if cmd.kind == C_GO:
        if not out.reserve(records={"order_placed": 1}, requests=1):
            return RETRY
        out.emit_order_placed(ctx.t, user_id=ctx.self_id, amount=3_100)
        out.request_claim(ctx.t, shard=0, who=ctx.self_id, amount=ctx.cfg.bonus)
        return COMMIT
    if cmd.kind == R_OK:
        if not out.reserve(records={"bonus_paid": 1}):
            return RETRY
        out.emit_bonus_paid(ctx.t, user_id=ctx.self_id, amount=cmd.amount)
        return COMMIT
    return reject(0)


@kernel(state="pool", commands=(C_CLAIM, C_REFUND),
        max=Res(records={"bonus_granted": 1, "bonus_rejected": 1, "bonus_refunded": 1},
                requests=1))
def pool_desk(ctx, s, cmd, out):
    if cmd.kind == C_REFUND:                    # never happens in the trace (timeout 1m)
        if not out.reserve(records={"bonus_refunded": 1}):
            return RETRY
        s.remaining = std.checked_add(s.remaining, cmd.amount)
        s.granted = std.checked_sub(s.granted, cmd.amount)
        out.emit_bonus_refunded(ctx.t, who=cmd.who, amount=cmd.amount)
        return COMMIT
    if not out.reserve(records={"bonus_granted": 1, "bonus_rejected": 1}, requests=1):
        return RETRY
    g = std.capped_pool.take(s.remaining, cmd.amount)
    if g > 0:
        s.remaining = std.checked_sub(s.remaining, g)
        s.granted = std.checked_add(s.granted, g)
        out.emit_bonus_granted(ctx.t, who=cmd.who, amount=g)
        out.respond(cmd, "granted", amount=g)
    else:
        out.emit_bonus_rejected(ctx.t, who=cmd.who, amount=cmd.amount)
        out.respond(cmd, "rejected", amount=0)
    return COMMIT


@action(state="user", max=Res(records={"order_placed": 1}))
def first_order(ctx, s, m, cmd, out):
    out.emit_order_placed(ctx.t, user_id=m.id, amount=3_100)
    return COMMIT


@action(state="user", max=Res(records={"bonus_paid": 1}), fields={"paid": "i64"})
def pay_bonus(ctx, s, m, cmd, out):
    out.emit_bonus_paid(ctx.t, user_id=m.id, amount=m.paid)
    return COMMIT
