from neorisk_simkit.engine import COMMIT, RETRY, START, Res, kernel

R_OK = 1
ACCT_COMMANDS = (START, R_OK)
PAY_COMMANDS = (START,)
C_TICK, C_ASK = 1, 2


@kernel(state="acct", commands=ACCT_COMMANDS,
        max=Res(records={"spawned": 1, "answered": 1}, creates={"pay": 1}, requests=3))
def acct_main(ctx, s, cmd, out):
    if cmd.kind == START:
        if not out.reserve(records={"spawned": 1}, creates={"pay": 1}, requests=3):
            return RETRY
        if ctx.cfg.create_on_answer == 0:
            pay = out.create_pay(acct_id=ctx.self_id, amt=100 + ctx.self_id)
            out.emit_spawned(ctx.t, acct_id=ctx.self_id, pay_id=pay)
        out.send_tick(ctx.t, to=ctx.self_id % 2, v=ctx.self_id)
        out.request_ask(ctx.t + ctx.cfg.request_delay,
                        shard=ctx.self_id % 2 + 5 * ctx.cfg.bad_shard, v=ctx.self_id)
        return COMMIT
    if not out.reserve(records={"answered": 1, "spawned": 1}, creates={"pay": 1},
                       requests=2):              # the creation message and the next ask
        return RETRY
    out.emit_answered(ctx.t, acct_id=ctx.self_id)
    if ctx.cfg.create_on_answer == 1:
        pay = out.create_pay(acct_id=ctx.self_id, amt=100 + ctx.self_id)
        out.emit_spawned(ctx.t, acct_id=ctx.self_id, pay_id=pay)
    s.n += 1
    if s.n < ctx.cfg.rounds:                 # ask again: one more round trip and creation
        out.request_ask(ctx.t, shard=ctx.self_id % 2, v=ctx.self_id)
    return COMMIT


@kernel(state="pay", commands=PAY_COMMANDS, max=Res(records={"paid": 1}))
def pay_main(ctx, s, cmd, out):
    if not out.reserve(records={"paid": 1}):
        return RETRY
    out.emit_paid(ctx.t, pay_id=ctx.self_id, acct_id=s.acct_id, amt=s.amt)
    return COMMIT


@kernel(state="desk", commands=(C_TICK, C_ASK),
        max=Res(records={"ticked": 1, "asked": 1}, requests=1))
def desk_main(ctx, s, cmd, out):
    if cmd.kind == C_TICK:
        if not out.reserve(records={"ticked": 1}):
            return RETRY
        out.emit_ticked(ctx.t, v=cmd.v)
        return COMMIT
    if not out.reserve(records={"asked": 1}, requests=1):
        return RETRY
    out.emit_asked(ctx.t, v=cmd.v)
    out.respond(cmd, "ok")
    return COMMIT
