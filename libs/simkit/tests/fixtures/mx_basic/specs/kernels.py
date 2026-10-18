from neorisk_simkit.engine import COMMIT, Res, action, reject


@action(state="parcel", max=Res(records={"delivered": 1}))
def deliver(ctx, s, m, cmd, out):
    out.emit_delivered(ctx.t, parcel_id=m.id, weight=s.weight)
    return COMMIT


@action(state="parcel", max=Res(records={"audited": 1}))
def audit(ctx, s, m, cmd, out):
    if s.weight > ctx.cfg.max_weight:
        return reject(1)
    out.emit_audited(ctx.t, parcel_id=m.id)
    return COMMIT
