from neorisk_simkit.engine import COMMIT, RETRY, START, Res, kernel


@kernel(state="clock", commands=(START,), max=Res(records={"ticked": 1}))
def tick(ctx, s, cmd, out):
    if not out.reserve(records={"ticked": 1}):
        return RETRY
    s.ticks += 1
    out.emit_ticked(ctx.t, clock=ctx.self_id, j=cmd.tag, n=s.ticks)
    return COMMIT
