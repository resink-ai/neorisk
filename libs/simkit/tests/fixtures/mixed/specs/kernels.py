from neorisk_simkit.engine import COMMIT, PRIO_TIMER, RETRY, START, Res, kernel

MS = 1_000
MINUTE = 60_000_000
C_MAKE = 1
ACCT_COMMANDS = (START, C_MAKE)
C_PING, R_PONG, R_OK, C_STEP, C_ASK, C_IDLE = 1, 2, 3, 4, 5, 6
PAY_COMMANDS = (START, C_PING, R_PONG, R_OK, C_STEP, C_ASK, C_IDLE)
C_PINGED, C_ASKED = 1, 1


@kernel(state="acct", commands=ACCT_COMMANDS, max=Res(creates={"pay": 1}, timers=1))
def acct_main(ctx, s, cmd, out):
    if not out.reserve(creates={"pay": 1}, timers=1):
        return RETRY
    if cmd.kind == START:
        out.timer(ctx.t + 90 * MINUTE, C_MAKE, prio=PRIO_TIMER)
    else:
        out.create_pay(made=1)
    return COMMIT


@kernel(state="pay", commands=PAY_COMMANDS, max=Res(timers=2, requests=1))
def pay_main(ctx, s, cmd, out):
    if not out.reserve(timers=2, requests=1):
        return RETRY
    if s.made == 1:                                       # the created pay stays idle
        return COMMIT
    late = ctx.self_id == 0
    if cmd.kind == START:                                 # 00:00, lamport 1, cseq 1
        if late:
            out.timer(ctx.t + 60 * MINUTE - 100 * MS, C_PING, prio=PRIO_TIMER)
        else:
            out.timer(ctx.t + 20 * MINUTE, C_STEP, prio=PRIO_TIMER)
    elif cmd.kind == C_PING:                              # 00:59:59.9, lamport 2
        out.timer(ctx.t + 60 * MINUTE, C_IDLE, prio=PRIO_TIMER)    # cseq 2
        out.request_ping(ctx.t, shard=0, v=0)                      # src_seq 3
    elif cmd.kind == R_PONG:                              # 01:00, lamport 4, src_seq 4
        out.request_ask(ctx.t, shard=0, v=0)
    elif cmd.kind == C_STEP:                              # 00:20 lamport 2, 00:40 lamport 3
        s.made -= 1
        if s.made > -2:
            out.timer(ctx.t + 20 * MINUTE, C_STEP, prio=PRIO_TIMER)
        else:
            out.timer(ctx.t + 20 * MINUTE, C_ASK, prio=PRIO_TIMER)
    elif cmd.kind == C_ASK:                               # 01:00, lamport 4, src_seq 4
        out.request_ask(ctx.t, shard=0, v=1)
    return COMMIT


@kernel(state="desk", commands=(C_PINGED,), max=Res(requests=1))
def desk_ping(ctx, s, cmd, out):
    if not out.reserve(requests=1):
        return RETRY
    out.respond(cmd, "pong")
    return COMMIT


@kernel(state="desk", commands=(C_ASKED,), max=Res(records={"asked": 1}, requests=1))
def desk_ask(ctx, s, cmd, out):
    if not out.reserve(records={"asked": 1}, requests=1):
        return RETRY
    out.emit_asked(ctx.t, v=cmd.v)
    out.respond(cmd, "ok")
    return COMMIT
