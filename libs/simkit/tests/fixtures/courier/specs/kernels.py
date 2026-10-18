from neorisk_simkit.engine import COMMIT, PRIO_TIMER, RETRY, START, Res, kernel, reject

C_CREDIT, C_KEEP = 1, 2
ACCT_COMMANDS = (START, C_CREDIT, C_KEEP)
S = 1_000_000
DAY = 86_400 * S


@kernel(state="acct", commands=ACCT_COMMANDS,
        max=Res(records={"credited": 1}, timers=1, requests=5))
def acct_main(ctx, s, cmd, out):
    if cmd.kind == START:
        if ctx.self_id == 3:
            return COMMIT                              # nothing queued: retires idle at +0
        if not out.reserve(timers=1, requests=5):
            return RETRY
        if ctx.self_id == 0:
            for j in range(4):
                out.send_credit(ctx.t + ctx.cfg.send_after_s * S, to=ctx.cfg.targets[j],
                                amount=10 + j)
            if ctx.cfg.send4_s >= 0:
                out.send_credit(ctx.t + ctx.cfg.send4_s * S, to=4, amount=40)
        keep = DAY if ctx.self_id == 2 else 3 * DAY    # acct 2 retires idle at +1 d
        out.timer(ctx.t + keep, C_KEEP, prio=PRIO_TIMER)
        return COMMIT
    if cmd.kind == C_KEEP:
        return reject(0)
    if not out.reserve(records={"credited": 1}):
        return RETRY
    s.bal += cmd.amount
    out.emit_credited(ctx.t, acct_id=ctx.self_id, sender=cmd.sender, amount=cmd.amount)
    return COMMIT
