from neorisk_simkit import std
from neorisk_simkit.engine import COMMIT, RETRY, START, Res, action, kernel, reject

R_OK, R_NO, C_CLAIM, C_REFUND = 1, 2, 1, 2
USER_COMMANDS = (START, R_OK, R_NO)


@kernel(state="user", commands=USER_COMMANDS,
        max=Res(records={"signed_up": 1, "bonus_paid": 1}, requests=1))
def user_main(ctx, s, cmd, out):
    if cmd.kind == START:
        if not out.reserve(records={"signed_up": 1}, requests=1):
            return RETRY
        out.emit_signed_up(ctx.t, user_id=ctx.self_id,
                           device_id=ctx.refs.device.get(ctx.self_id, 0), invited_by=std.NULL)
        out.request_claim(ctx.t, shard=0, who=ctx.self_id, amount=ctx.cfg.bonus)
        return COMMIT
    if cmd.kind == R_OK:
        if not out.reserve(records={"bonus_paid": 1}):
            return RETRY
        out.emit_bonus_paid(ctx.t, user_id=ctx.self_id, amount=cmd.amount)
        return COMMIT
    return reject(0)


@kernel(state="pot", commands=(C_CLAIM, C_REFUND),
        max=Res(records={"granted": 1, "refused": 1, "refunded": 1}, requests=1))
def pot_desk(ctx, s, cmd, out):
    if cmd.kind == C_REFUND:
        if not out.reserve(records={"refunded": 1}):
            return RETRY
        s.remaining = std.checked_add(s.remaining, cmd.amount)
        s.granted = std.checked_sub(s.granted, cmd.amount)
        out.emit_refunded(ctx.t, who=cmd.who, amount=cmd.amount)
        return COMMIT
    if not out.reserve(records={"granted": 1, "refused": 1}, requests=1):
        return RETRY
    g = std.capped_pool.take(s.remaining, cmd.amount)
    if g > 0:
        s.remaining = std.checked_sub(s.remaining, g)
        s.granted = std.checked_add(s.granted, g)
        out.emit_granted(ctx.t, who=cmd.who, amount=g, sender=cmd.sender)
        out.respond(cmd, "granted", amount=g)
    else:
        out.emit_refused(ctx.t, who=cmd.who, amount=cmd.amount, sender=cmd.sender)
        out.respond(cmd, "rejected", amount=0)
    return COMMIT


@action(state="user", max=Res(records={"signed_up": 1}), fields={"device": "ref"})
def signup(ctx, s, m, cmd, out):
    out.emit_signed_up(ctx.t, user_id=m.id, device_id=m.device, invited_by=std.NULL)
    return COMMIT


@action(state="user", max=Res(records={"signed_up": 1}), fields={"device": "ref"})
def signup_invited(ctx, s, m, cmd, out):
    out.emit_signed_up(ctx.t, user_id=m.id, device_id=m.device, invited_by=m.parent_id)
    return COMMIT


@action(state="user", max=Res(records={"bonus_paid": 1}), fields={"paid": "i64"})
def pay_bonus(ctx, s, m, cmd, out):
    out.emit_bonus_paid(ctx.t, user_id=m.id, amount=m.paid)
    return COMMIT
