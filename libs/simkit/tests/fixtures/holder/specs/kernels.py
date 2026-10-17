from neorisk_simkit.engine import COMMIT, PRIO_TIMER, RETRY, START, Local, Res, kernel

C_NOTE, C_HELLO, C_ECHO = 1, 2, 3
DESK_COMMANDS = (C_NOTE, C_HELLO, C_ECHO)
HOUR = 3_600_000_000


@kernel(state="acct", commands=(START,),
        max=Res(records={"opened": 1}, creates={"ticket": 1, "pay": 1}, requests=2))
def acct_main(ctx, s, cmd, out):
    if not out.reserve(records={"opened": 1}, creates={"ticket": 1, "pay": 1}, requests=2):
        return RETRY
    t = out.new_id("ticket")
    pay = out.create_pay(acct_id=ctx.self_id, ticket=t)
    out.emit_opened(ctx.t, acct_id=ctx.self_id, ticket_id=t, pay_id=pay)
    out.send_note(ctx.t, to=0, ticket=t)
    return COMMIT


@kernel(state="pay", commands=(START,), max=Res(requests=1))
def pay_main(ctx, s, cmd, out):
    if not out.reserve(requests=1):
        return RETRY
    out.send_hello(ctx.t, to=0, ticket=s.ticket)
    return COMMIT


@kernel(state="desk", local=Local(seen="ref[4]", n="i32"), commands=DESK_COMMANDS,
        max=Res(records={"noted": 1, "echoed": 1, "heard": 1}, timers=1))
def desk_main(ctx, s, loc, cmd, out):
    if cmd.kind == C_NOTE:
        if not out.reserve(records={"noted": 1}, timers=1):
            return RETRY
        s.last = cmd.ticket                       # a provisional handle until the step seals
        if loc.n < 4:
            loc.seen[loc.n] = cmd.ticket
        loc.n += 1
        out.emit_noted(ctx.t, ticket_id=cmd.ticket)
        out.timer(ctx.t + 2 * HOUR, C_ECHO, prio=PRIO_TIMER)
        return COMMIT
    if cmd.kind == C_HELLO:
        if not out.reserve(records={"heard": 1}):
            return RETRY
        out.emit_heard(ctx.t, ticket_id=cmd.ticket, sender_id=cmd.sender)
        return COMMIT
    if not out.reserve(records={"echoed": 1}):
        return RETRY
    out.emit_echoed(ctx.t, last_id=s.last, first_id=loc.seen[0])
    return COMMIT
