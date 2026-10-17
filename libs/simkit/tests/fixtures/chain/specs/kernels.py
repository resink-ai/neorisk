from neorisk_simkit.engine import COMMIT, RETRY, START, Res, kernel

# no `requests=`: creating an owner reserves its creation message automatically (Task 4)


@kernel(state="a", commands=(START,), max=Res(records={"a_made": 1}, creates={"b": 1}))
def a_main(ctx, s, cmd, out):
    if not out.reserve(records={"a_made": 1}, creates={"b": 1}):
        return RETRY
    b = out.create_b(a_id=ctx.self_id, w=10 + ctx.self_id)
    out.emit_a_made(ctx.t, a_id=ctx.self_id, b_id=b)
    return COMMIT


@kernel(state="b", commands=(START,), max=Res(records={"b_made": 1}, creates={"c": 1}))
def b_main(ctx, s, cmd, out):
    if not out.reserve(records={"b_made": 1}, creates={"c": 1}):
        return RETRY
    c = out.create_c(b_id=ctx.self_id, w=s.w + 100)
    out.emit_b_made(ctx.t, b_id=ctx.self_id, c_id=c, w=s.w)
    return COMMIT


@kernel(state="c", commands=(START,), max=Res(records={"c_drew": 1}))
def c_main(ctx, s, cmd, out):
    d = ctx.rng.uniform_int(site=1, lo=0, hi=1_000_000)
    if not out.reserve(records={"c_drew": 1}):
        return RETRY
    out.emit_c_drew(ctx.t, c_id=ctx.self_id, b_id=s.b_id, w=s.w, draw=d)
    return COMMIT
