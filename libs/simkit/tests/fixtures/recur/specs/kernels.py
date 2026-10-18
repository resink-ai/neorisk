from neorisk_simkit.engine import COMMIT, RETRY, START, Res, kernel


@kernel(state="seed", commands=(START,), max=Res(creates={"node": 1}))
def plant(ctx, s, cmd, out):
    if not out.reserve(creates={"node": 1}):
        return RETRY
    out.create_node(level=1)
    return COMMIT


@kernel(state="node", commands=(START,), max=Res(records={"grown": 1}, creates={"node": 1}))
def grow(ctx, s, cmd, out):
    if not out.reserve(records={"grown": 1}, creates={"node": 1}):
        return RETRY
    out.emit_grown(ctx.t, node_id=ctx.self_id, level=s.level)
    if s.level < ctx.cfg.levels:
        out.create_node(level=s.level + 1)
    return COMMIT
