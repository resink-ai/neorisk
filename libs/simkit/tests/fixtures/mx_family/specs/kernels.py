from neorisk_simkit.engine import COMMIT, Res, action


@action(state="nest", max=Res(records={"fed": 1}), fields={"meals": "i32"})
def feed(ctx, s, m, cmd, out):
    m.meals += 1
    out.emit_fed(ctx.t, nest_id=m.id, meal=m.meals)
    return COMMIT
