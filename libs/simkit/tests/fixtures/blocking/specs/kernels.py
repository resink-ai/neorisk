from neorisk_simkit.engine import COMMIT, PRIO_TIMER, RETRY, START, Res, kernel

C_LATER, R_ACK = 1, 2
ACCT_COMMANDS = (START, C_LATER, R_ACK)
C_NOTE = 1
MS = 1_000


@kernel(state="acct", commands=ACCT_COMMANDS,
        max=Res(records={"later": 1, "acked": 1}, timers=1, requests=1))
def acct_main(ctx, s, cmd, out):
    if cmd.kind == START:
        if not out.reserve(timers=1, requests=1):
            return RETRY
        if ctx.self_id == 0:                       # asks now, and again 10 ms later
            out.request_note(ctx.t, shard=0, tag=0, v=ctx.self_id)
            out.timer(ctx.t + 10 * MS, C_LATER, prio=PRIO_TIMER)
        else:                                      # asks once, 50 ms later
            out.timer(ctx.t + 50 * MS, C_LATER, prio=PRIO_TIMER)
        return COMMIT
    if cmd.kind == C_LATER:
        if not out.reserve(records={"later": 1}, requests=1):
            return RETRY
        out.emit_later(ctx.t, acct_id=ctx.self_id)
        out.request_note(ctx.t, shard=0, tag=0, v=ctx.self_id)
        return COMMIT
    if not out.reserve(records={"acked": 1}):
        return RETRY
    out.emit_acked(ctx.t, acct_id=ctx.self_id)
    return COMMIT


@kernel(state="ledger", commands=(C_NOTE,), max=Res(records={"noted": 1}, requests=1))
def ledger_desk(ctx, s, cmd, out):
    if not out.reserve(records={"noted": 1}, requests=1):
        return RETRY
    out.emit_noted(ctx.t, v=cmd.v)
    out.respond(cmd, "ack")
    return COMMIT
