from neorisk_simkit import std
from neorisk_simkit.engine import COMMIT, RETRY, START, Res, kernel, reject

R_GRANTED, R_REJECTED = 1, 2
ACCT_COMMANDS = (START, R_GRANTED, R_REJECTED)
C_CLAIM = 1
CLAIMS = 3


@kernel(state="acct", commands=ACCT_COMMANDS,
        max=Res(records={"funded": 3, "credited": 1, "held": 1, "freed": 1, "entry": 2},
                creates={"claim": 1, "hold": 1}, requests=1))
def acct_main(ctx, s, cmd, out):
    fault = ctx.cfg.fault
    if not out.reserve(records={"funded": 3, "credited": 1, "held": 1, "freed": 1, "entry": 2},
                       creates={"claim": 1, "hold": 1}, requests=1):
        return RETRY
    if cmd.kind == START:
        out.emit_funded(ctx.t, acct_id=ctx.self_id, amount=1000)
        if fault == 8:                               # a negative row, net zero funding
            out.emit_funded(ctx.t, acct_id=ctx.self_id, amount=-1)
            out.emit_funded(ctx.t, acct_id=ctx.self_id, amount=1)
        s.hold = out.new_id("hold")
        out.emit_held(ctx.t, acct_id=ctx.self_id, hold_id=s.hold)
        out.request_claim(ctx.t, shard=0, tag=out.new_id("claim"), amount=100)
        return COMMIT
    if s.claims == 0 and fault != 5:
        out.emit_freed(ctx.t, acct_id=ctx.self_id, hold_id=s.hold)
    if cmd.kind == R_GRANTED:
        amt = 2000 if fault == 2 else cmd.amount
        out.emit_credited(ctx.t, acct_id=ctx.self_id, claim_id=cmd.tag, amount=amt)
        out.emit_entry(ctx.t, acct_id=ctx.self_id, account="cash", side="debit", amount=amt)
        if fault != 3:
            out.emit_entry(ctx.t, acct_id=ctx.self_id, account="bonus", side="credit",
                           amount=amt)
    s.claims += 1
    if s.claims < CLAIMS:
        out.request_claim(ctx.t, shard=0, tag=out.new_id("claim"), amount=100)
    return COMMIT


@kernel(state="pool", commands=(C_CLAIM,),
        max=Res(records={"granted": 2, "denied": 1}, requests=1))
def pool_desk(ctx, s, cmd, out):
    fault = ctx.cfg.fault
    if fault == 6:
        return reject(1)                             # a request must be answered
    if not out.reserve(records={"granted": 2, "denied": 1}, requests=1):
        return RETRY
    g = std.capped_pool.take(s.remaining, cmd.amount)
    if fault == 1:
        g = cmd.amount                               # ignores the cap
    if g > 0:
        cost = 2 * g if fault == 7 else g
        s.remaining = max(s.remaining - cost, 0) if fault == 1 else s.remaining - cost
        out.emit_granted(ctx.t, claim_id=cmd.tag, amount=g, remaining_after=s.remaining)
        if fault == 4:
            out.emit_granted(ctx.t, claim_id=cmd.tag, amount=g, remaining_after=s.remaining)
        out.respond(cmd, "granted", amount=g)
    else:
        out.emit_denied(ctx.t, claim_id=cmd.tag, amount=cmd.amount)
        out.respond(cmd, "rejected", amount=0)
    return COMMIT
