from neorisk_simkit.engine import COMMIT, PRIO_TIMER, RETRY, START, Res, kernel

MINUTE = 60_000_000
C_MAKE = 1
ACCT_COMMANDS = (START, C_MAKE)
C_ASK, R_OK = 1, 2
ASKER_COMMANDS = (START, C_ASK, R_OK)
C_STEP = 3
PEER_COMMANDS = (START, C_ASK, R_OK, C_STEP)
C_ASKED = 1


@kernel(state="acct", commands=ACCT_COMMANDS, max=Res(creates={"pay": 1}, timers=1))
def acct_main(ctx, s, cmd, out):
    if not out.reserve(creates={"pay": 1}, timers=1):     # the creation message: automatic
        return RETRY
    if cmd.kind == START:
        out.timer(ctx.t + 50 * MINUTE, C_MAKE, prio=PRIO_TIMER)
    else:
        out.create_pay(acct_id=ctx.self_id)
    return COMMIT


@kernel(state="pay", commands=ASKER_COMMANDS, max=Res(timers=1, requests=1))
def pay_main(ctx, s, cmd, out):
    if not out.reserve(timers=1, requests=1):
        return RETRY
    if cmd.kind == START:                                 # 00:50, lamport 3 (cause 2)
        out.timer(ctx.t + 10 * MINUTE, C_ASK, prio=PRIO_TIMER)
    elif cmd.kind == C_ASK:                               # 01:00, lamport 4
        out.request_ask(ctx.t, shard=0, v=0)
    return COMMIT


@kernel(state="peer", commands=PEER_COMMANDS, max=Res(timers=1, requests=1))
def peer_main(ctx, s, cmd, out):
    if not out.reserve(timers=1, requests=1):
        return RETRY
    if cmd.kind == START:                                 # 00:00, lamport 1
        out.timer(ctx.t + 20 * MINUTE, C_STEP, prio=PRIO_TIMER)
    elif cmd.kind == C_STEP:                              # 00:20 lamport 2, 00:40 lamport 3
        s.k += 1
        if s.k < 2:
            out.timer(ctx.t + 20 * MINUTE, C_STEP, prio=PRIO_TIMER)
        else:
            out.timer(ctx.t + 20 * MINUTE, C_ASK, prio=PRIO_TIMER)
    elif cmd.kind == C_ASK:                               # 01:00, lamport 4
        out.request_ask(ctx.t, shard=0, v=1)
    return COMMIT


@kernel(state="desk", commands=(C_ASKED,), max=Res(records={"asked": 1}, requests=1))
def desk_pay(ctx, s, cmd, out):
    if not out.reserve(records={"asked": 1}, requests=1):
        return RETRY
    out.emit_asked(ctx.t, v=cmd.v)
    out.respond(cmd, "ok")
    return COMMIT


@kernel(state="desk", commands=(C_ASKED,), max=Res(records={"asked": 1}, requests=1))
def desk_peer(ctx, s, cmd, out):
    if not out.reserve(records={"asked": 1}, requests=1):
        return RETRY
    out.emit_asked(ctx.t, v=cmd.v)
    out.respond(cmd, "ok")
    return COMMIT
