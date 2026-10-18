from neorisk_simkit.engine import COMMIT, RETRY, START, Res, kernel


@kernel(state="acct", commands=(START,), max=Res(records={"seen": 1, "tags": 1}))
def acct_main(ctx, s, cmd, out):
    if not out.reserve(records={"seen": 1, "tags": 1}):
        return RETRY
    out.emit_seen(ctx.t, acct_id=ctx.self_id)
    out.emit_tags(ctx.t, target_id=ctx.self_id, role="bad", outcome="done", final_label=1,
                  label_available_at=ctx.t + 3_600_000_000)
    return COMMIT
