from neorisk_simkit.engine import COMMIT, RETRY, START, Res, kernel, reject


@kernel(state="acct", commands=(START,), max=Res(records={"opened": 1, "entry": 2}))
def acct_main(ctx, s, cmd, out):
    amt = 100 + ctx.self_id - 1000 * ctx.cfg.bad
    if not out.reserve(records={"opened": 1, "entry": 2}):
        return RETRY
    if ctx.cfg.add_then_reject == 1:
        out.add_fees(1)
        return reject(1)                            # a write before reject: checked mode fails
    s.bal = amt
    out.add_fees(ctx.self_id + 1)
    out.emit_opened(ctx.t, acct_id=ctx.self_id, amount=amt)
    out.emit_entry(ctx.t, acct_id=ctx.self_id, account="cash", side="debit", amount=amt)
    out.emit_entry(ctx.t, acct_id=ctx.self_id, account="revenue", side="credit", amount=amt)
    return COMMIT
