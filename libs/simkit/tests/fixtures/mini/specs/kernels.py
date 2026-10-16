"""Mini kernels: an owner that pings, creates rows and requests stock; a shard that answers."""

from neorisk_simkit import std
from neorisk_simkit.engine import COMMIT, PRIO_TIMER, RETRY, START, Local, Res, kernel, reject

C_PING = 1
R_OK = 2
R_NONE = 3
USER_COMMANDS = (START, C_PING, R_OK, R_NONE)
C_TAKE = 1
REJ_DONE = 1


@kernel(state="user", local=Local(pings="i32", visit="ref"), commands=USER_COMMANDS,
        max=Res(records={"user_joined": 1, "ping": 1, "took": 1},
                creates={"note": 1, "visit": 1}, timers=1, requests=1))
def user_main(ctx, s, loc, cmd, out):
    cfg = ctx.cfg
    if cmd.kind == START:
        if not out.reserve(records={"user_joined": 1}, timers=1):
            return RETRY
        out.emit_user_joined(ctx.t, user_id=ctx.self_id, tier=s.tier)
        out.timer(ctx.t + ctx.rng.dist_us(site=1, d=cfg.ping_gap), C_PING, prio=PRIO_TIMER)
        return COMMIT
    if cmd.kind == C_PING:
        if loc.pings >= cfg.max_pings:
            return reject(REJ_DONE)                    # no timer: the user goes idle and retires
        take = ctx.rng.bernoulli(site=2, p=cfg.take_p)
        note = ctx.rng.bernoulli(site=3, p=cfg.note_p)
        if not out.reserve(records={"ping": 1}, creates={"note": 1, "visit": 1}, timers=1,
                           requests=1):
            return RETRY
        loc.visit = out.new_id("visit")
        nid = s.last_note                              # a handle from an earlier step, or NULL
        if note:
            nid = out.create_note(size=ctx.rng.uniform_int(site=4, lo=1, hi=9))
            s.last_note = nid                          # provisional until the step seals
        loc.pings += 1
        out.emit_ping(ctx.t, user_id=ctx.self_id, visit_id=loc.visit, n=loc.pings, note_id=nid)
        if take:
            item = ctx.rng.uniform_int(site=5, lo=0, hi=ctx.reads.item.n - 1)
            out.request_take(ctx.t, shard=ctx.reads.item.bin[item], item_id=item, tag=loc.visit)
        else:
            out.timer(ctx.t + ctx.rng.dist_us(site=6, d=cfg.ping_gap), C_PING, prio=PRIO_TIMER)
        return COMMIT
    if not out.reserve(records={"took": 1}, timers=1):
        return RETRY
    if cmd.kind == R_OK:
        out.emit_took(ctx.t, user_id=ctx.self_id, item_id=cmd.item_id, ok="yes")
    else:
        out.emit_took(ctx.t, user_id=ctx.self_id, item_id=cmd.item_id, ok="no")
    out.timer(ctx.t + ctx.rng.dist_us(site=7, d=cfg.ping_gap), C_PING, prio=PRIO_TIMER)
    return COMMIT


@kernel(state="bin", commands=(C_TAKE,),
        max=Res(records={"item_taken": 1, "take_failed": 1}, requests=1))
def bin_desk(ctx, s, cmd, out):
    i = ctx.reads.item.local_index[cmd.item_id]
    if not out.reserve(records={"item_taken": 1, "take_failed": 1}, requests=1):
        return RETRY
    if s.on_hand[i] > 0:
        s.on_hand[i] = std.checked_sub(s.on_hand[i], 1)
        out.emit_item_taken(ctx.t, bin=ctx.self_id, item_id=cmd.item_id, left=s.on_hand[i])
        out.respond(cmd, "ok", item_id=cmd.item_id)
    else:
        out.emit_take_failed(ctx.t, bin=ctx.self_id, item_id=cmd.item_id)
        out.respond(cmd, "none", item_id=cmd.item_id)
    return COMMIT
