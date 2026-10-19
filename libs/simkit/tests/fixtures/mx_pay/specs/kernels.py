from neorisk_simkit.engine import COMMIT, RETRY, START, Res, kernel

C_CAPTURE, C_VOID = 1, 2


@kernel(state="bank", commands=(C_CAPTURE, C_VOID),
        max=Res(records={"decided": 1, "voided": 1}, requests=1))
def bank_desk(ctx, s, cmd, out):
    if cmd.kind == C_VOID:                               # a late grant given back (F-35)
        if not out.reserve(records={"voided": 1}):
            return RETRY
        s.captured -= cmd.amount
        out.emit_voided(ctx.t, amount=cmd.amount)
        return COMMIT
    if not out.reserve(records={"decided": 1}, requests=1):
        return RETRY
    ok = cmd.amount <= ctx.cfg.limit
    out.emit_decided(ctx.t, amount=cmd.amount, granted=1 if ok else 0)
    if ok:
        s.captured += cmd.amount
        out.respond(cmd, "granted", amount=cmd.amount)
    else:
        out.respond(cmd, "rejected", amount=0)
    return COMMIT


@kernel(state="receipt", commands=(START,), max=Res(records={"receipt_issued": 1}))
def receipt_main(ctx, s, cmd, out):
    if not out.reserve(records={"receipt_issued": 1}):
        return RETRY
    out.emit_receipt_issued(ctx.t, receipt_id=ctx.self_id, payment_id=s.payment_id,
                            amount=s.amount)
    return COMMIT
