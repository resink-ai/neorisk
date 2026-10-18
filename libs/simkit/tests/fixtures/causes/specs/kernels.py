from neorisk_simkit.engine import COMMIT, PRIO_TIMER, RETRY, START, Res, kernel

R_OK, C_TICK, C_EMIT, C_ASK = 1, 2, 3, 1
ACCT_COMMANDS = (START, R_OK, C_TICK, C_EMIT)
H = 3_600_000_000


@kernel(state="acct", commands=ACCT_COMMANDS,
        max=Res(records={"opened": 1, "ticked": 1, "answered": 1, "marks": 1}, timers=1,
                requests=1))
def acct_main(ctx, s, cmd, out):
    if cmd.kind == START:
        if not out.reserve(records={"opened": 1}, timers=1, requests=1):
            return RETRY
        out.emit_opened(ctx.t, acct_id=ctx.self_id)
        out.timer(ctx.t + 2 * H, C_TICK, prio=PRIO_TIMER)
        out.request_ask(ctx.t, shard=0, who=ctx.self_id)
        return COMMIT
    if cmd.kind == C_TICK:                 # emits only a label row: causes pass through it
        if not out.reserve(records={"marks": 1}, timers=1):
            return RETRY
        out.emit_marks(ctx.t, acct_id=ctx.self_id)
        out.timer(ctx.t + H, C_EMIT, prio=PRIO_TIMER)
        return COMMIT
    if not out.reserve(records={"ticked": 1, "answered": 1}):
        return RETRY
    if cmd.kind == C_EMIT:
        out.emit_ticked(ctx.t, acct_id=ctx.self_id)
    else:
        out.emit_answered(ctx.t, acct_id=ctx.self_id)
    return COMMIT


@kernel(state="desk", commands=(C_ASK,), max=Res(records={"asked": 1}, requests=1))
def desk_main(ctx, s, cmd, out):
    if not out.reserve(records={"asked": 1}, requests=1):
        return RETRY
    out.emit_asked(ctx.t, who=cmd.who)
    out.respond(cmd, "ok")
    return COMMIT
