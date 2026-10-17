from neorisk_simkit.engine import COMMIT, PRIO_TIMER, RETRY, START, Res, kernel

MS = 1_000
MINUTE = 60_000_000
C_PING, R_PONG, R_OK = 1, 2, 3
ASKER_COMMANDS = (START, C_PING, R_PONG, R_OK)
C_ASK, C_STEP = 1, 4
PEER_COMMANDS = (START, C_ASK, R_OK, C_STEP)
C_PINGED, C_ASKED = 1, 1


@kernel(state="asker", commands=ASKER_COMMANDS, max=Res(timers=1, requests=1))
def asker_main(ctx, s, cmd, out):
    if not out.reserve(timers=1, requests=1):
        return RETRY
    if cmd.kind == START:                                 # 00:00, lamport 1
        out.timer(ctx.t + 60 * MINUTE - 100 * MS, C_PING, prio=PRIO_TIMER)
    elif cmd.kind == C_PING:                              # 00:59:59.9, lamport 2
        out.request_ping(ctx.t, shard=0, v=0)
    elif cmd.kind == R_PONG:                              # 01:00, lamport 4 (cause 3)
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


@kernel(state="desk", commands=(C_PINGED,), max=Res(requests=1))
def desk_ping(ctx, s, cmd, out):
    if not out.reserve(requests=1):
        return RETRY
    out.respond(cmd, "pong")
    return COMMIT


@kernel(state="desk", commands=(C_ASKED,), max=Res(records={"asked": 1}, requests=1))
def desk_asker(ctx, s, cmd, out):
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
