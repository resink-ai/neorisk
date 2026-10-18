from neorisk_simkit.engine import COMMIT, Res, action, reject


@action(state="acct", max=Res(records={"checked": 1}))
def check(ctx, s, m, cmd, out):
    if s.weight > ctx.cfg.max_weight:
        return reject(1)
    out.emit_checked(ctx.t, acct_id=m.id)
    return COMMIT


@action(state="acct")
def refuse(ctx, s, m, cmd, out):
    return reject(2)
