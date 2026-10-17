from neorisk_simkit.engine import COMMIT, RETRY, START, Res, kernel


@kernel(state="acct", commands=(START,), max=Res(records={"opened": 1, "entry": 2}))
def acct_main(ctx, s, cmd, out):
    amt = 100 + ctx.self_id
    if not out.reserve(records={"opened": 1, "entry": 2}):
        return RETRY
    s.bal = amt
    out.emit_opened(ctx.t, acct_id=ctx.self_id, amount=amt)
    out.emit_entry(ctx.t, acct_id=ctx.self_id, account="cash", side="debit", amount=amt)
    out.emit_entry(ctx.t, acct_id=ctx.self_id, account="revenue", side="credit", amount=amt)
    return COMMIT
