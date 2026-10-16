from neorisk_simkit.engine import COMMIT, PRIO_TIMER, RETRY, START, Res, kernel

C_MARK = 1
ACCT_COMMANDS = (START, C_MARK)
US = 1_000_000
HOUR = 3_600 * US


# Offsets of the marks from `start` (the run begins 6h earlier, so the first gap is 6h - 1us):
#   0: -1us (warm-up only)   1: 0 (exported)       2: 5h - 1us   3: 5h (a step end)
#   4: 10h (a step end)      5: 23h30m             6: 24h (midnight)  7: 25h (a step end)
@kernel(state="acct", commands=ACCT_COMMANDS, max=Res(records={"mark": 1}, timers=1))
def acct_main(ctx, s, cmd, out):
    if not out.reserve(records={"mark": 1}, timers=1):
        return RETRY
    if cmd.kind == START:
        out.timer(ctx.t + 6 * HOUR - 1, C_MARK, prio=PRIO_TIMER)
        return COMMIT
    out.emit_mark(ctx.t, acct_id=ctx.self_id, n=s.count)
    s.count = s.count + 1
    if s.count == 1:
        out.timer(ctx.t + 1, C_MARK, prio=PRIO_TIMER)
    elif s.count == 2:
        out.timer(ctx.t + 5 * HOUR - 1, C_MARK, prio=PRIO_TIMER)
    elif s.count == 3:
        out.timer(ctx.t + 1, C_MARK, prio=PRIO_TIMER)
    elif s.count == 4:
        out.timer(ctx.t + 5 * HOUR, C_MARK, prio=PRIO_TIMER)
    elif s.count == 5:
        out.timer(ctx.t + 13 * HOUR + 30 * 60 * US, C_MARK, prio=PRIO_TIMER)
    elif s.count == 6:
        out.timer(ctx.t + 30 * 60 * US, C_MARK, prio=PRIO_TIMER)
    elif s.count == 7:
        out.timer(ctx.t + HOUR, C_MARK, prio=PRIO_TIMER)
    return COMMIT
