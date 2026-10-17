from neorisk_simkit.engine import COMMIT, PRIO_TIMER, RETRY, START, Res, kernel

C_AGAIN, C_LAST = 1, 2
ACCT_COMMANDS = (START, C_AGAIN, C_LAST)
C_TICK = 1
PAY_COMMANDS = (START, C_TICK)
MINUTE = 60_000_000
TICK_EVERY = 480 * MINUTE                       # 8 h, aligned to UTC midnight


@kernel(state="acct", commands=ACCT_COMMANDS,
        max=Res(records={"spawned": 2}, creates={"pay": 2}, timers=1))
def acct_main(ctx, s, cmd, out):
    if cmd.kind == C_AGAIN:
        if not out.reserve(records={"spawned": 2}, creates={"pay": 2}, timers=1):
            return RETRY
        a = out.create_pay(acct_id=ctx.self_id, amt=200)
        out.emit_spawned(ctx.t, acct_id=ctx.self_id, pay_id=a)
        b = out.create_pay(acct_id=ctx.self_id, amt=300)
        out.emit_spawned(ctx.t, acct_id=ctx.self_id, pay_id=b)
        out.timer(ctx.t + 180 * MINUTE, C_LAST, prio=PRIO_TIMER)
        return COMMIT
    if not out.reserve(records={"spawned": 1}, creates={"pay": 1}, timers=1):
        return RETRY
    pay = out.create_pay(acct_id=ctx.self_id, amt=100)
    out.emit_spawned(ctx.t, acct_id=ctx.self_id, pay_id=pay)
    if cmd.kind == START:                    # higher accounts create their pair earlier
        out.timer(ctx.t + (ctx.cfg.accts - ctx.self_id) * 40 * MINUTE, C_AGAIN,
                  prio=PRIO_TIMER)
    return COMMIT


@kernel(state="pay", commands=PAY_COMMANDS, max=Res(records={"paid": 1, "ticked": 1},
                                                    creates={"refund": 1}, timers=1))
def pay_main(ctx, s, cmd, out):
    d = ctx.rng.uniform_int(site=1, lo=0, hi=1_000_000)
    if cmd.kind == START:
        if not out.reserve(records={"paid": 1}, creates={"refund": 1}, timers=1):
            return RETRY
        out.emit_paid(ctx.t, pay_id=ctx.self_id, acct_id=s.acct_id, draw=d)
        if s.amt > 100:
            out.create_refund(pay_id=ctx.self_id)
        out.timer(ctx.t - ctx.t % TICK_EVERY + TICK_EVERY, C_TICK, prio=PRIO_TIMER)
        return COMMIT
    if not out.reserve(records={"ticked": 1}):
        return RETRY
    out.emit_ticked(ctx.t, pay_id=ctx.self_id, acct_id=s.acct_id, draw=d)
    return COMMIT


@kernel(state="refund", commands=PAY_COMMANDS, max=Res(records={"refunded": 1}, timers=1))
def refund_main(ctx, s, cmd, out):
    d = ctx.rng.uniform_int(site=1, lo=0, hi=1_000_000)
    if not out.reserve(records={"refunded": 1}, timers=1):
        return RETRY
    out.emit_refunded(ctx.t, refund_id=ctx.self_id, pay_id=s.pay_id, phase=cmd.kind, draw=d)
    if cmd.kind == START:
        out.timer(ctx.t - ctx.t % TICK_EVERY + TICK_EVERY, C_TICK, prio=PRIO_TIMER)
    return COMMIT
