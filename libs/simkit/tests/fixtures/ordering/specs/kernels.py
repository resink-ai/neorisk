from neorisk_simkit import std
from neorisk_simkit.engine import (
    COMMIT,
    PRIO_MESSAGE,
    PRIO_TIMER,
    RETRY,
    START,
    Res,
    kernel,
    reject,
)

C_PREP, C_CREDIT, C_DEBIT, R_ACK = 1, 2, 3, 4
ACCT_COMMANDS = (START, C_PREP, C_CREDIT, C_DEBIT, R_ACK)
C_NOTE = 1
HOUR = 3_600_000_000
REJ_FUNDS = 1


@kernel(state="acct", commands=ACCT_COMMANDS,
        max=Res(records={"opened": 1, "credited": 1, "debited": 1}, timers=2, requests=1))
def acct_main(ctx, s, cmd, out):
    if cmd.kind == START:
        if not out.reserve(records={"opened": 1}, timers=2, requests=1):
            return RETRY
        out.emit_opened(ctx.t, acct_id=ctx.self_id)
        out.timer(ctx.t + HOUR, C_DEBIT, prio=PRIO_TIMER)          # low priority, scheduled first
        out.timer(ctx.t + 1_000_000, C_PREP, prio=PRIO_TIMER)
        out.request_note(ctx.t, shard=0, tag=0, v=ctx.self_id)     # equal keys across accounts
        return COMMIT
    if cmd.kind == C_PREP:
        if not out.reserve(timers=1):
            return RETRY
        out.timer(ctx.t - 1_000_000 + HOUR, C_CREDIT, prio=PRIO_MESSAGE)   # same instant, higher
        return COMMIT
    if cmd.kind == C_CREDIT:
        if not out.reserve(records={"credited": 1}):
            return RETRY
        s.balance = std.checked_add(s.balance, 100)
        out.emit_credited(ctx.t, acct_id=ctx.self_id, balance_after=s.balance)
        return COMMIT
    if cmd.kind == C_DEBIT:
        if s.balance < 100:
            return reject(REJ_FUNDS)
        if not out.reserve(records={"debited": 1}):
            return RETRY
        s.balance = std.checked_sub(s.balance, 100)
        out.emit_debited(ctx.t, acct_id=ctx.self_id, balance_after=s.balance)
        return COMMIT
    return COMMIT                                                   # R_ACK: nothing to record


@kernel(state="ledger", commands=(C_NOTE,), max=Res(records={"noted": 1}, requests=1))
def ledger_desk(ctx, s, cmd, out):
    if not out.reserve(records={"noted": 1}, requests=1):
        return RETRY
    out.emit_noted(ctx.t, v=cmd.v)
    out.respond(cmd, "ack")
    return COMMIT
