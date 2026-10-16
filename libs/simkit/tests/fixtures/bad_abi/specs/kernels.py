from neorisk_simkit.engine import COMMIT, RETRY, Res, kernel, reject


@kernel(state="acct", commands=(0,), max=Res(records={"e": 1}, timers=1))
def bad(ctx, s, cmd, out):
    mode = ctx.cfg.mode
    if mode == 0:
        s.n = 1
        return reject(1)
    if mode == 1:
        out.emit_e(ctx.t, acct_id=ctx.self_id)
        return COMMIT
    if mode == 2:
        if not out.reserve(timers=1):
            return RETRY
        out.timer(ctx.t - 1, 0)
        return COMMIT
    if not out.reserve(records={"e": 1}):
        return RETRY
    s.n = 2
    return RETRY
