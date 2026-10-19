from neorisk_simkit.engine import COMMIT, PRIO_TIMER, RETRY, START, Res, kernel

C_AGAIN = 1
ORDER_COMMANDS = (START, C_AGAIN)
H = 3_600_000_000


@kernel(state="order", commands=ORDER_COMMANDS, max=Res(records={"refund_issued": 1}, timers=1))
def order_main(ctx, s, cmd, out):
    if not out.reserve(records={"refund_issued": 1}, timers=1):
        return RETRY
    half = s.amount // 2
    if cmd.kind == START:
        out.emit_refund_issued(ctx.t, order_id=ctx.self_id, amount=half)
        out.timer(ctx.t + 2 * H, C_AGAIN, prio=PRIO_TIMER)
    else:
        out.emit_refund_issued(ctx.t, order_id=ctx.self_id,
                               amount=s.amount - half + ctx.cfg.extra)
    return COMMIT
