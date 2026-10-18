from neorisk_simkit.engine import COMMIT, RETRY, START, Res, kernel

R_OK, C_ASK = 1, 1
USER_COMMANDS = (START, R_OK)
CREW_COMMANDS = (START, R_OK)


@kernel(state="user", commands=USER_COMMANDS, max=Res(records={"joined": 1}, requests=1))
def user_main(ctx, s, cmd, out):
    if cmd.kind == R_OK:
        return COMMIT
    if not out.reserve(records={"joined": 1}, requests=1):
        return RETRY
    out.emit_joined(ctx.t, user_id=ctx.self_id, tier=s.tier)
    out.request_ask(ctx.t, shard=0, who=ctx.self_id)
    return COMMIT


@kernel(state="crew", commands=CREW_COMMANDS,
        max=Res(records={"joined": 3}, creates={"user": 3}, requests=1))
def crew_main(ctx, s, cmd, out):
    if cmd.kind == R_OK:
        return COMMIT
    if not out.reserve(records={"joined": 3}, creates={"user": 3}, requests=1):
        return RETRY
    first = 0
    for j in range(s.size):
        mid = out.add_member_user(tier="b")
        if j == 0:
            first = mid
        out.emit_joined(ctx.t, user_id=mid, tier="b")
    out.request_ask(ctx.t, shard=0, who=first)
    return COMMIT


@kernel(state="desk", commands=(C_ASK,), max=Res(records={"asked": 1}, requests=1))
def desk_main(ctx, s, cmd, out):
    if not out.reserve(records={"asked": 1}, requests=1):
        return RETRY
    s.asks += 1
    out.emit_asked(ctx.t, who=cmd.who)
    out.respond(cmd, "ok")
    return COMMIT
