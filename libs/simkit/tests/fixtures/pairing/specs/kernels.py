from neorisk_simkit.engine import COMMIT, RETRY, START, Res, kernel, reject

R_OK = 1
ACCT_COMMANDS = (START, R_OK)
C_ASK, C_TICK = 1, 2


@kernel(state="acct", commands=ACCT_COMMANDS, max=Res(records={"answered": 1}, requests=2))
def acct_main(ctx, s, cmd, out):
    if cmd.kind == START:
        if not out.reserve(requests=2):
            return RETRY
        out.send_tick(ctx.t, to=0, v=ctx.self_id)
        out.request_ask(ctx.t, shard=0, v=ctx.self_id)
        return COMMIT
    if not out.reserve(records={"answered": 1}):
        return RETRY
    out.emit_answered(ctx.t, acct_id=ctx.self_id)
    return COMMIT


@kernel(state="desk", commands=(C_ASK, C_TICK), max=Res(records={"asked": 1}, requests=2))
def desk_main(ctx, s, cmd, out):
    mode = ctx.cfg.mode
    if cmd.kind == C_TICK:
        if mode != 3:
            return COMMIT
        if not out.reserve(requests=1):
            return RETRY
        out.respond(cmd, "ok")                     # answers a message: not a request
        return COMMIT
    if mode == 1:
        return reject(1)                           # a request must be answered, not rejected
    if not out.reserve(records={"asked": 1}, requests=2):
        return RETRY
    out.emit_asked(ctx.t, v=cmd.v)
    out.respond(cmd, "ok")
    if mode == 2:
        out.respond(cmd, "ok")
    return COMMIT
