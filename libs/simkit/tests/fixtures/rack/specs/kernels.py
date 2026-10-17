from neorisk_simkit.engine import COMMIT, PRIO_TIMER, RETRY, START, Res, kernel

C_STOW, C_ECHO = 1, 2
RACK_COMMANDS = (C_STOW, C_ECHO)
HOUR = 3_600_000_000
BIN = 3                                           # rack 1's second bin: CSR position 3


@kernel(state="acct", commands=(START,),
        max=Res(records={"opened": 1}, creates={"ticket": 1}, requests=1))
def acct_main(ctx, s, cmd, out):
    if not out.reserve(records={"opened": 1}, creates={"ticket": 1}, requests=1):
        return RETRY
    t = out.new_id("ticket")
    out.emit_opened(ctx.t, acct_id=ctx.self_id, ticket_id=t)
    out.send_stow(ctx.t, to=1, ticket=t, bin_id=BIN)
    return COMMIT


@kernel(state="rack", commands=RACK_COMMANDS,
        max=Res(records={"stowed": 1, "echoed": 1}, timers=1))
def rack_main(ctx, s, cmd, out):
    if cmd.kind == C_STOW:
        if not out.reserve(records={"stowed": 1}, timers=1):
            return RETRY
        s.held[ctx.reads.bin.local_index[cmd.bin_id]] = cmd.ticket   # provisional until seal
        out.emit_stowed(ctx.t, ticket_id=cmd.ticket, bin_id=cmd.bin_id)
        out.timer(ctx.t + 2 * HOUR, C_ECHO, prio=PRIO_TIMER)
        return COMMIT
    if not out.reserve(records={"echoed": 1}):
        return RETRY
    out.emit_echoed(ctx.t, held_id=s.held[ctx.reads.bin.local_index[BIN]])
    return COMMIT
