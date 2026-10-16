from neorisk_simkit.engine import COMMIT, RETRY, START, Res, kernel, reject

C_TICK, C_ECHO, R_OK = 1, 2, 3
COMMANDS = (START, C_TICK, C_ECHO, R_OK)
C_PUT = 1
MINUTE = 60_000_000


@kernel(state="prover", commands=COMMANDS,
        max=Res(records={"e_alpha": 1, "e_beta": 1, "e_gamma": 2},
                creates={"box": 1, "tok": 1}, timers=2, requests=1))
def prove(ctx, s, cmd, out):
    if cmd.kind == START:
        if not out.reserve(timers=1):
            return RETRY
        out.timer(ctx.t + MINUTE, C_TICK)
        return COMMIT
    if cmd.kind == C_TICK:
        if s.n >= ctx.cfg.ticks:
            return reject(1)
        w = ctx.rng.uniform_int(site=1, lo=1, hi=100)
        target = ctx.rng.uniform_int(site=3, lo=0, hi=1)
        gap = ctx.rng.uniform_int(site=4, lo=1, hi=5)
        if not out.reserve(records={"e_alpha": 1, "e_beta": 1, "e_gamma": 2},
                           creates={"box": 1, "tok": 1}, timers=2, requests=1):
            return RETRY
        s.n += 1
        tok = out.new_id("tok")
        box = out.create_box(w=w)
        s.last_box = box
        out.emit_e_alpha(ctx.t, prover_id=ctx.self_id, tok_id=tok, k=s.n)
        out.emit_e_beta(ctx.t, prover_id=ctx.self_id, box_id=box, w=w)
        for j in range(2):                                   # one site, k counts the draws
            out.emit_e_gamma(ctx.t, prover_id=ctx.self_id,
                             k=j + ctx.rng.uniform_int(site=2, lo=0, hi=9))
        out.request_put(ctx.t, shard=target, tag=tok, w=w)
        out.timer(ctx.t + gap * MINUTE, C_TICK)
        out.timer(ctx.t, C_ECHO)
        return COMMIT
    if cmd.kind == C_ECHO:
        if s.n % 3 == 2:
            return reject(2)
        if not out.reserve(records={"e_gamma": 1}):
            return RETRY
        out.emit_e_gamma(ctx.t, prover_id=ctx.self_id, k=100 + s.n)
        return COMMIT
    if not out.reserve(records={"e_gamma": 1}):
        return RETRY
    out.emit_e_gamma(ctx.t, prover_id=ctx.self_id, k=200, note=cmd.w)
    return COMMIT


@kernel(state="sink", commands=(C_PUT,), max=Res(records={"sunk": 1}, requests=1))
def sink_desk(ctx, s, cmd, out):
    if not out.reserve(records={"sunk": 1}, requests=1):
        return RETRY
    out.emit_sunk(ctx.t, w=cmd.w)
    out.respond(cmd, "ok", w=cmd.w)
    return COMMIT
