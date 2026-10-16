"""Handwritten kernels for the payments pack.

Every kernel follows the action interface:
    1. validate   read state, maybe reject(...)       no writes yet
    2. reserve    out.reserve(...) for every resource  RETRY if the slab is full
    3. commit     mutate state, emit, post, schedule   cannot fail
Random draws use ctx.rng.<dist>(site=N, ...); each draw site has its own number, so edits to
one site never shift draws at another. Amounts are int64 cents and use checked helpers.
A process's start trigger delivers the first command id of its *_COMMANDS tuple.
"""

from neorisk_simkit.engine import COMMIT, RETRY, Local, Res, kernel, reject
from neorisk_simkit import std

# ------------------------------------------------------------------ command ids
# cardholder
C_START_PURCHASES = 1   # start: schedule the first purchase
C_PURCHASE = 2          # timer: make a purchase, schedule the next one
PURCHASE_COMMANDS = (C_START_PURCHASES, C_PURCHASE)

# payment: authorization
C_AUTH_START = 20       # start: payment created by a purchase (creation message)
C_3DS_DONE = 21         # timer: the cardholder finishes (or abandons) the 3DS challenge
C_ISSUER = 22           # timer: the issuer's answer arrives
C_AUTH_RETRY = 23       # timer: merchant resends the request with the same idempotency key
R_APPROVE = 30          # response: authorize -> approve
R_DECLINE = 31          # response: authorize -> decline
R_CHALLENGE = 32        # response: authorize -> challenge (3DS step-up)
AUTH_COMMANDS = (C_AUTH_START, C_3DS_DONE, C_ISSUER, C_AUTH_RETRY, R_APPROVE, R_DECLINE,
                 R_CHALLENGE)

# payment: refunds
C_REFUND_START = 40     # start: capture_succeeded; decide whether this payment gets refunds
C_REFUND = 41           # timer: the merchant issues a refund
C_REFUND_RETRY = 42     # timer: merchant resends the refund with the same idempotency key
R_REFUND_OK = 50        # response: refund_check -> approved
R_REFUND_DECLINED = 51  # response: refund_check -> declined (merchant daily limit)
REFUND_COMMANDS = (C_REFUND_START, C_REFUND, C_REFUND_RETRY, R_REFUND_OK, R_REFUND_DECLINED)

# priorities at equal time (lower runs first); responses before own timers. The lifecycle
# machine declares its own precedence: expiry before capture.
PRIO_RESPONSE, PRIO_TIMER = 1, 5

REJ_STALE = 1
REJ_BAD_AMOUNT = 2
REJ_EXPIRED = 3
REJ_NO_REFUND = 4
REJ_NOTHING_REFUNDABLE = 5
REJ_REFUND_IN_FLIGHT = 6
REJ_ALREADY_DISPUTED = 7
REJ_NOTHING_DISPUTABLE = 8

# auth_result / original_result codes, in pack.RESULTS order
RES_IN_PROGRESS, RES_APPROVED, RES_DECLINED, RES_SUCCEEDED, RES_REJECTED = 0, 1, 2, 3, 4

# ledger accounts (std.ledger); every post_ledger call writes one debit row and one credit row
ACCOUNTS = ("scheme_receivable", "merchant_payable", "fee_revenue", "disputes_pending",
            "settlement_cash")
A_SCHEME, A_MERCHANT, A_FEES, A_DISPUTES, A_CASH = 0, 1, 2, 3, 4

SECOND = 1_000_000      # µs
DAY = 86_400_000_000

# Per-owner scratch, laid out next to the payment row; freed when the owner retires
AUTH_LOCAL = Local(risk_score="i16", authenticated="b1", challenged_at="i64")
REFUND_LOCAL = Local(
    refund="ref",               # latest refund (provisional handle within a step)
    refund_key="ref",           # its idempotency key
    amount="i64",               # amount held for it
    pending="b1",               # waiting on refund_check
    result="i8",                # RES_* of the latest refund, for idempotent replays
    left="i8",                  # refunds this payment may still get
)


# ================================================================== cardholder
@kernel(state="cardholder", commands=PURCHASE_COMMANDS, max=Res(creates={"payment": 1}, timers=1))
def cardholder_purchases(ctx, s, cmd, out):
    """One cardholder's purchases at our merchants. Each purchase creates a payment owner."""
    cfg = ctx.cfg
    if s.status != std.ACTIVE:
        return reject(REJ_STALE)                                   # dormant: no more purchases
    if cmd.kind == C_START_PURCHASES:
        if not out.reserve(timers=1):
            return RETRY
        first = ctx.rng.dist_us(site=1, d=cfg.first_purchase)
        out.timer(std.diurnal_shift(ctx.t + first, u=ctx.rng.uniform(site=2),
                                    profile=cfg.hour_profile), C_PURCHASE, prio=PRIO_TIMER)
        return COMMIT
    if cmd.kind != C_PURCHASE:
        return reject(REJ_STALE)
    if not out.reserve(creates={"payment": 1}, timers=1):
        return RETRY
    merchant = ctx.reads.merchant.sample_local(s.country, ctx.rng.uniform(site=10),
                                               home_p=cfg.home_country_p)
    mcc = ctx.reads.merchant.mcc[merchant]
    card = ctx.refs.card.pick(ctx.self_id, ctx.rng.uniform(site=11))
    online = ctx.rng.bernoulli(site=12, p=ctx.reads.mcc.ecom_share[mcc])
    device = ctx.refs.device.pick(ctx.self_id, ctx.rng.uniform(site=13)) if online else 0
    channel = std.cat("ecom") if online else (
        std.cat("moto") if ctx.rng.bernoulli(site=14, p=0.03) else std.cat("pos"))
    amt = ctx.rng.lognormal_minor(site=15, median=ctx.reads.mcc.median_amount[mcc],
                                  sigma=ctx.reads.mcc.sigma[mcc], min=cfg.min_amount,
                                  max=cfg.max_amount)
    _create_payment(ctx, out, card, merchant, mcc, device, amt, channel, holder_present=True)
    s.purchases = std.checked_add(s.purchases, 1)
    s.last_purchase_at = ctx.t
    gap = ctx.rng.exp_us(site=16, mean_days=30.0 / s.rate_30d)
    out.timer(std.diurnal_shift(ctx.t + gap, u=ctx.rng.uniform(site=17), profile=cfg.hour_profile),
              C_PURCHASE, prio=PRIO_TIMER)
    return COMMIT


@kernel(state="cardholder", max=Res(creates={"payment": 1}))
def place_purchase(ctx, s, cmd, out):
    """Exposed to overlays: one payment with the caller's card, merchant, device and amount."""
    if cmd.amount <= 0:
        return reject(REJ_BAD_AMOUNT)
    if not out.reserve(creates={"payment": 1}):
        return RETRY
    _create_payment(ctx, out, cmd.card_id, cmd.merchant_id, ctx.reads.merchant.mcc[cmd.merchant_id],
                    cmd.device_id, cmd.amount, cmd.channel, holder_present=cmd.holder_present)
    return COMMIT


def _create_payment(ctx, out, card, merchant, mcc, device, amt, channel, holder_present):
    """Creation message: the payment owner starts at ctx.t in the next round of this step."""
    out.create_payment(card_id=card, merchant_id=merchant, device_id=device, mcc=mcc,
                       channel=channel, amount=amt, authorized=0, captured=0, fee=0, refunded=0,
                       refund_hold=0, disputed=0, charged_back=0, status=std.cat("requested"),
                       auth_result=RES_IN_PROGRESS, three_ds=False, dispute_open=False,
                       disputes=0, idem_key=out.new_id("idempotency_key"),
                       holder_present=holder_present)


# ================================================================== payment: authorization
@kernel(state="payment", local=AUTH_LOCAL, commands=AUTH_COMMANDS,
        max=Res(records={"authorization_requested": 1, "three_ds_challenged": 1,
                         "three_ds_completed": 1, "authorization_approved": 1,
                         "authorization_declined": 1, "idempotent_replay": 1},
                timers=2, requests=1))
def authorize_payment(ctx, s, loc, cmd, out):
    """Risk screen (shard request), optional 3DS step-up, issuer answer, idempotent replays."""
    cfg = ctx.cfg
    if cmd.kind == C_AUTH_START:
        return _auth_start(ctx, s, loc, out, cfg)
    if cmd.kind == R_APPROVE or cmd.kind == R_DECLINE or cmd.kind == R_CHALLENGE:
        return _on_risk(ctx, s, loc, cmd, out, cfg)
    if cmd.kind == C_3DS_DONE:
        return _on_3ds(ctx, s, loc, out, cfg)
    if cmd.kind == C_ISSUER:
        return _on_issuer(ctx, s, loc, out, cfg)
    if cmd.kind == C_AUTH_RETRY:
        return _auth_replay(ctx, s, out)
    return reject(REJ_STALE)


def _auth_start(ctx, s, loc, out, cfg):
    if s.status != std.cat("requested"):
        return reject(REJ_STALE)
    if not out.reserve(records={"authorization_requested": 1}, requests=1, timers=1):
        return RETRY
    m, c = s.merchant_id, s.card_id
    card_country = ctx.reads.card.issuer_country[c]
    merchant_country = ctx.reads.merchant.country[m]
    out.emit_authorization_requested(
        ctx.t, payment_id=ctx.self_id, card_id=c, merchant_id=m, device_id=s.device_id,
        amount=s.amount, mcc=s.mcc, channel=s.channel, bin=ctx.reads.card.bin[c],
        card_brand=ctx.reads.card.brand[c], funding=ctx.reads.card.funding[c],
        card_country=card_country, merchant_country=merchant_country,
        idempotency_key=s.idem_key)
    out.request_authorize(ctx.t, shard=ctx.reads.merchant.merchant_group[m],    # immutable copy
                          payment_id=ctx.self_id, card_id=c, merchant_id=m, device_id=s.device_id,
                          amount=s.amount, mcc=s.mcc, channel=s.channel,
                          funding=ctx.reads.card.funding[c],
                          cross_border=card_country != merchant_country)
    if ctx.rng.bernoulli(site=1, p=cfg.client_retry_p):            # merchant client times out
        out.timer(ctx.t + ctx.rng.dist_us(site=2, d=cfg.client_retry_delay), C_AUTH_RETRY,
                  prio=PRIO_TIMER)
    return COMMIT


def _on_risk(ctx, s, loc, cmd, out, cfg):
    if s.status != std.cat("requested"):
        return reject(REJ_STALE)
    if not out.reserve(records={"three_ds_challenged": 1, "authorization_declined": 1}, timers=1):
        return RETRY
    loc.risk_score = cmd.score
    if cmd.kind == R_DECLINE:
        code = std.cat("velocity") if cmd.rule_velocity else std.cat("risk_decline")
        _decline(ctx, s, loc, out, code, std.cat("risk"))
        return COMMIT
    if cmd.kind == R_CHALLENGE and s.channel == std.cat("ecom"):
        s.status = std.cat("challenged")
        loc.challenged_at = ctx.t
        out.emit_three_ds_challenged(ctx.t, payment_id=ctx.self_id, card_id=s.card_id,
                                     merchant_id=s.merchant_id, risk_score=cmd.score,
                                     protocol=ctx.rng.categorical(site=10, p=(0.3, 0.7)))
        out.timer(ctx.t + ctx.rng.dist_us(site=11, d=cfg.challenge_time), C_3DS_DONE,
                  prio=PRIO_TIMER)
        return COMMIT
    # approve (or a challenge on a channel without 3DS): forward to the issuer
    out.timer(ctx.t + ctx.rng.dist_us(site=12, d=cfg.issuer_latency), C_ISSUER, prio=PRIO_TIMER)
    return COMMIT


def _on_3ds(ctx, s, loc, out, cfg):
    if s.status != std.cat("challenged"):
        return reject(REJ_STALE)
    if not out.reserve(records={"three_ds_completed": 1, "authorization_declined": 1}, timers=1):
        return RETRY
    if s.holder_present:
        outcome = ctx.rng.categorical(site=20, p=cfg.three_ds_outcome)
    else:                                                          # no OTP, no banking app
        passed = ctx.rng.bernoulli(site=21, p=cfg.three_ds_pass_absent)
        outcome = 0 if passed else 1 + ctx.rng.bernoulli(site=22, p=0.5)
    out.emit_three_ds_completed(ctx.t, payment_id=ctx.self_id, result=outcome,
                                duration_ms=(ctx.t - loc.challenged_at) // 1_000)
    if outcome == 0:
        loc.authenticated = True
        s.three_ds = True
        s.status = std.cat("requested")                            # back in the auth path
        out.timer(ctx.t + ctx.rng.dist_us(site=23, d=cfg.issuer_latency), C_ISSUER,
                  prio=PRIO_TIMER)
        return COMMIT
    code = std.cat("authentication_failed") if outcome == 1 else std.cat("authentication_abandoned")
    _decline(ctx, s, loc, out, code, std.cat("authentication"))
    return COMMIT


def _on_issuer(ctx, s, loc, out, cfg):
    if s.status != std.cat("requested"):
        return reject(REJ_STALE)
    if not out.reserve(records={"authorization_approved": 1, "authorization_declined": 1}):
        return RETRY
    c = s.card_id
    status = ctx.reads.card.status[c]
    if status == std.cat("expired"):
        _decline(ctx, s, loc, out, std.cat("expired_card"), std.cat("issuer"))
        return COMMIT
    if status == std.cat("closed"):
        _decline(ctx, s, loc, out, std.cat("invalid_card"), std.cat("issuer"))
        return COMMIT
    p_decline = cfg.issuer_decline_p
    if ctx.reads.card.funding[c] == std.cat("prepaid"):
        p_decline = p_decline * cfg.prepaid_decline_mult
    if loc.authenticated:
        p_decline = p_decline * cfg.authenticated_decline_mult
    if ctx.rng.bernoulli(site=30, p=p_decline):
        reason = ctx.rng.categorical(site=31, p=cfg.issuer_decline_mix)   # 4 contiguous codes
        _decline(ctx, s, loc, out, std.cat("insufficient_funds") + reason, std.cat("issuer"))
        return COMMIT
    s.authorized = s.amount
    s.auth_expires_at = ctx.t + cfg.auth_validity_days * DAY       # capture must be strictly before
    s.status = std.cat("authorized")
    s.auth_result = RES_APPROVED
    out.emit_authorization_approved(ctx.t, payment_id=ctx.self_id, card_id=c,
                                    merchant_id=s.merchant_id, amount=s.authorized,
                                    auth_code=ctx.rng.uniform_int(site=32, lo=100_000, hi=999_999),
                                    three_ds=loc.authenticated, risk_score=loc.risk_score,
                                    expires_at=s.auth_expires_at)
    return COMMIT


def _decline(ctx, s, loc, out, code, source):
    """Terminal decline. Called only after reserve succeeded."""
    s.status = std.cat("declined")
    s.auth_result = RES_DECLINED
    out.emit_authorization_declined(ctx.t, payment_id=ctx.self_id, card_id=s.card_id,
                                    merchant_id=s.merchant_id, amount=s.amount,
                                    decline_code=code, source=source, risk_score=loc.risk_score)


def _auth_replay(ctx, s, out):
    """Same idempotency key again: answer with the first result, never authorize twice."""
    if not out.reserve(records={"idempotent_replay": 1}):
        return RETRY
    out.emit_idempotent_replay(ctx.t, payment_id=ctx.self_id, operation=std.cat("authorization"),
                               idempotency_key=s.idem_key, original_result=s.auth_result,
                               refund_id=0)
    return COMMIT


# ================================================================== payment: refunds
@kernel(state="payment", local=REFUND_LOCAL, commands=REFUND_COMMANDS,
        max=Res(records={"refund_requested": 1, "refund_succeeded": 1, "refund_rejected": 1,
                         "idempotent_replay": 1, "posting": 2, "settlement": 1},
                creates={"refund": 1}, timers=2, requests=1))
def refund_flow(ctx, s, loc, cmd, out):
    """Refunds as a hold: hold on the payment, merchant_risk decides headroom, commit or release."""
    cfg = ctx.cfg
    if cmd.kind == C_REFUND_START:
        return _refund_start(ctx, s, loc, out, cfg)
    if cmd.kind == C_REFUND:
        return _refund(ctx, s, loc, out, cfg)
    if cmd.kind == R_REFUND_OK or cmd.kind == R_REFUND_DECLINED:
        return _on_refund_response(ctx, s, loc, cmd, out, cfg)
    if cmd.kind == C_REFUND_RETRY:
        return _refund_replay(ctx, s, loc, cmd, out)
    return reject(REJ_STALE)


def _refundable(s):
    """Captured minus everything already refunded, held, disputed or charged back."""
    used = std.checked_add(std.checked_add(s.refunded, s.refund_hold),
                           std.checked_add(s.disputed, s.charged_back))
    return std.checked_sub(s.captured, used)


def _refund_start(ctx, s, loc, out, cfg):
    if not ctx.rng.bernoulli(site=1, p=ctx.reads.mcc.refund_p[s.mcc]):
        return reject(REJ_NO_REFUND)                   # no refund ever: the process ends here
    if not out.reserve(timers=1):
        return RETRY
    loc.left = 1
    while loc.left < cfg.max_refunds and ctx.rng.bernoulli(site=2, p=cfg.extra_refund_p):
        loc.left += 1                                  # k counts draws at site 2
    out.timer(ctx.t + ctx.rng.dist_us(site=3, d=cfg.refund_delay), C_REFUND, prio=PRIO_TIMER)
    return COMMIT


def _refund(ctx, s, loc, out, cfg):
    if loc.pending:
        return reject(REJ_REFUND_IN_FLIGHT)
    left = _refundable(s)
    if left <= 0:
        return reject(REJ_NOTHING_REFUNDABLE)          # the merchant UI blocks it; no event
    if not out.reserve(records={"refund_requested": 1, "refund_rejected": 1},
                       creates={"refund": 1}, requests=1, timers=1):
        return RETRY
    full = loc.left == 1 and ctx.rng.bernoulli(site=10, p=cfg.full_refund_p)
    if full:
        amt = left
    else:
        amt = std.checked_min(left, ctx.rng.lognormal_minor(
            site=11, median=std.checked_max(100, s.captured // 3), sigma=0.7, min=100))
    key = out.new_id("idempotency_key")
    r = out.create_refund(amount=amt, idem_key=key, status=std.cat("requested"))
    loc.refund, loc.refund_key, loc.amount, loc.result = r, key, amt, RES_IN_PROGRESS
    loc.left -= 1
    out.emit_refund_requested(ctx.t, payment_id=ctx.self_id, refund_id=r,
                              merchant_id=s.merchant_id, amount=amt, partial=amt < left,
                              idempotency_key=key)
    if s.dispute_open:                                 # never while a dispute is open
        loc.result = RES_REJECTED
        out.emit_refund_rejected(ctx.t, payment_id=ctx.self_id, refund_id=r,
                                 merchant_id=s.merchant_id, amount=amt,
                                 reason=std.cat("dispute_open"))
        return COMMIT
    s.refund_hold = std.checked_add(s.refund_hold, amt)            # 1. owner holds its side
    loc.pending = True
    out.request_refund_check(ctx.t, shard=ctx.reads.merchant.merchant_group[s.merchant_id],
                             payment_id=ctx.self_id, refund_id=r, merchant_id=s.merchant_id,
                             amount=amt, tag=r)                    # 2. shard decides its side
    if ctx.rng.bernoulli(site=12, p=cfg.client_retry_p):
        out.timer(ctx.t + ctx.rng.dist_us(site=13, d=cfg.client_retry_delay), C_REFUND_RETRY,
                  prio=PRIO_TIMER, tag=r)
    return COMMIT


def _on_refund_response(ctx, s, loc, cmd, out, cfg):
    if not loc.pending or cmd.tag != loc.refund:
        return reject(REJ_STALE)
    if not out.reserve(records={"refund_succeeded": 1, "refund_rejected": 1, "posting": 2,
                                "settlement": 1}, timers=1):
        return RETRY
    amt = loc.amount
    s.refund_hold = std.checked_sub(s.refund_hold, amt)            # 3. commit or release
    loc.pending = False
    if cmd.kind == R_REFUND_OK and not s.dispute_open:
        s.refunded = std.checked_add(s.refunded, amt)
        out.post_ledger(ctx.t, payment_id=ctx.self_id, debit=A_MERCHANT, credit=A_SCHEME,
                        amount=amt)
        out.accumulate_settlement(ctx.t, merchant_id=s.merchant_id, refunds=amt)
        loc.result = RES_SUCCEEDED
        out.emit_refund_succeeded(ctx.t, payment_id=ctx.self_id, refund_id=loc.refund,
                                  merchant_id=s.merchant_id, amount=amt, refunded_total=s.refunded)
    else:                                              # declined, or a dispute opened meanwhile
        loc.result = RES_REJECTED
        reason = std.cat("dispute_open") if s.dispute_open else std.cat("merchant_limit")
        out.emit_refund_rejected(ctx.t, payment_id=ctx.self_id, refund_id=loc.refund,
                                 merchant_id=s.merchant_id, amount=amt, reason=reason)
    if loc.left > 0 and not s.dispute_open and _refundable(s) > 0:
        wait = DAY if cmd.kind == R_REFUND_DECLINED else ctx.rng.dist_us(site=20, d=cfg.refund_delay)
        out.timer(ctx.t + wait, C_REFUND, prio=PRIO_TIMER)         # next partial refund
    return COMMIT


def _refund_replay(ctx, s, loc, cmd, out):
    if cmd.tag != loc.refund:
        return reject(REJ_STALE)                       # a newer refund replaced it
    if not out.reserve(records={"idempotent_replay": 1}):
        return RETRY
    out.emit_idempotent_replay(ctx.t, payment_id=ctx.self_id, operation=std.cat("refund"),
                               idempotency_key=loc.refund_key, original_result=loc.result,
                               refund_id=loc.refund)
    return COMMIT


# ================================================================== payment: lifecycle actions
@kernel(state="payment", max=Res(records={"capture_succeeded": 1, "posting": 4}))
def capture(ctx, s, cmd, out):
    """Capture all or part of the authorization; strictly before expiry."""
    cfg = ctx.cfg
    if s.status != std.cat("authorized"):
        return reject(REJ_STALE)
    if ctx.t >= s.auth_expires_at:
        return reject(REJ_EXPIRED)                     # precedence makes expiry win at equality
    if not out.reserve(records={"capture_succeeded": 1, "posting": 4}):
        return RETRY
    partial = ctx.rng.bernoulli(site=1, p=cfg.partial_capture_p)
    amt = s.authorized
    if partial:
        amt = std.checked_max(1, std.mul_bps(s.authorized, ctx.rng.uniform_int(site=2, lo=5_000,
                                                                                hi=9_900)))
    fee = std.checked_add(std.mul_bps(amt, ctx.reads.merchant.mdr_bps[s.merchant_id]),
                          cfg.fixed_fee)
    fee = std.checked_min(fee, amt)
    s.captured, s.fee, s.status = amt, fee, std.cat("captured")
    s.captured_at = ctx.t
    out.post_ledger(ctx.t, payment_id=ctx.self_id, debit=A_SCHEME, credit=A_MERCHANT, amount=amt)
    out.post_ledger(ctx.t, payment_id=ctx.self_id, debit=A_MERCHANT, credit=A_FEES, amount=fee)
    out.emit_capture_succeeded(ctx.t, payment_id=ctx.self_id, card_id=s.card_id,
                               merchant_id=s.merchant_id, amount=amt, authorized=s.authorized,
                               partial=partial, fee=fee)
    return COMMIT


@kernel(state="payment", max=Res(records={"authorization_voided": 1}))
def void_authorization(ctx, s, cmd, out):
    if s.status != std.cat("authorized"):
        return reject(REJ_STALE)
    if not out.reserve(records={"authorization_voided": 1}):
        return RETRY
    s.status = std.cat("voided")
    out.emit_authorization_voided(ctx.t, payment_id=ctx.self_id, merchant_id=s.merchant_id,
                                  amount=s.authorized,
                                  reason=ctx.rng.categorical(site=1, p=(0.55, 0.2, 0.25)))
    return COMMIT


@kernel(state="payment", max=Res(records={"authorization_expired": 1}))
def expire_authorization(ctx, s, cmd, out):
    if s.status != std.cat("authorized"):
        return reject(REJ_STALE)
    if not out.reserve(records={"authorization_expired": 1}):
        return RETRY
    s.status = std.cat("expired")
    out.emit_authorization_expired(ctx.t, payment_id=ctx.self_id, merchant_id=s.merchant_id,
                                   amount=s.authorized)
    return COMMIT


@kernel(state="payment", max=Res(records={"capture_rejected": 1}))
def reject_late_capture(ctx, s, cmd, out):
    """The merchant's capture arrives after expiry; we refuse it (no money moves)."""
    if s.status != std.cat("expired"):
        return reject(REJ_STALE)
    if not out.reserve(records={"capture_rejected": 1}):
        return RETRY
    out.emit_capture_rejected(ctx.t, payment_id=ctx.self_id, merchant_id=s.merchant_id,
                              amount=s.authorized, reason=std.cat("authorization_expired"))
    return COMMIT


@kernel(state="payment", max=Res(records={"payment_settled": 1, "posting": 4, "settlement": 1}))
def settle_payment(ctx, s, cmd, out):
    """Daily batch: the network pays us the gross, we pay the merchant the net."""
    if s.status != std.cat("captured"):
        return reject(REJ_STALE)
    if not out.reserve(records={"payment_settled": 1, "posting": 4, "settlement": 1}):
        return RETRY
    net = std.checked_sub(s.captured, s.fee)
    s.status = std.cat("settled")
    out.post_ledger(ctx.t, payment_id=ctx.self_id, debit=A_CASH, credit=A_SCHEME, amount=s.captured)
    out.post_ledger(ctx.t, payment_id=ctx.self_id, debit=A_MERCHANT, credit=A_CASH, amount=net)
    out.accumulate_settlement(ctx.t, merchant_id=s.merchant_id, gross=s.captured, fees=s.fee)
    out.emit_payment_settled(ctx.t, payment_id=ctx.self_id, merchant_id=s.merchant_id,
                             batch_date=std.batch_date(ctx.t), gross=s.captured, fee=s.fee, net=net)
    return COMMIT


# ================================================================== payment: dispute (child)
@kernel(state="payment", max=Res(records={"dispute_opened": 1, "posting": 2}, creates={"dispute": 1}))
def open_dispute(ctx, s, cmd, out):
    """Cardholder disputes through the issuer. Exposed; overlays pass a reason, the base draws one.

    ctx.cfg is the Lifecycle config whether the base machine or an overlay calls it.
    """
    cfg = ctx.cfg
    if s.status != std.cat("captured") and s.status != std.cat("settled"):
        return reject(REJ_STALE)
    if s.dispute_open or s.disputes > 0:
        return reject(REJ_ALREADY_DISPUTED)
    amt = std.checked_sub(s.captured, std.checked_add(std.checked_add(s.refunded, s.refund_hold),
                                                      s.charged_back))
    if amt <= 0:
        return reject(REJ_NOTHING_DISPUTABLE)          # fully refunded
    if not out.reserve(records={"dispute_opened": 1, "posting": 2}, creates={"dispute": 1}):
        return RETRY
    reason = cmd.reason if cmd.has_reason else ctx.rng.categorical(site=1, p=cfg.dispute_reason_mix)
    d = out.create_dispute(reason=reason, amount=amt, opened_at=ctx.t, status=std.cat("opened"))
    s.dispute_open, s.disputed = True, amt
    s.disputes = std.checked_add(s.disputes, 1)
    out.post_ledger(ctx.t, payment_id=ctx.self_id, debit=A_MERCHANT, credit=A_DISPUTES, amount=amt)
    out.emit_dispute_opened(ctx.t, payment_id=ctx.self_id, dispute_id=d, card_id=s.card_id,
                            merchant_id=s.merchant_id, reason=reason, amount=amt,
                            days_since_capture=(ctx.t - s.captured_at) // DAY,
                            respond_by=ctx.t + cfg.evidence_window_days * DAY)
    return COMMIT


@kernel(state="payment", instance="dispute", max=Res(records={"dispute_evidence_submitted": 1}))
def submit_evidence(ctx, s, d, cmd, out):
    if d.status != std.cat("opened"):
        return reject(REJ_STALE)
    if not out.reserve(records={"dispute_evidence_submitted": 1}):
        return RETRY
    d.status = std.cat("evidence")
    p = (0.5, 0.15, 0.1, 0.1, 0.15) if d.reason == std.cat("not_received") else (0.2, 0.3, 0.2, 0.1, 0.2)
    out.emit_dispute_evidence_submitted(ctx.t, payment_id=ctx.self_id, dispute_id=d.id,
                                        evidence=ctx.rng.categorical(site=1, p=p))
    return COMMIT


@kernel(state="payment", instance="dispute", max=Res(records={"dispute_won": 1, "posting": 2}))
def win_dispute(ctx, s, d, cmd, out):
    """Issuer rules for the merchant: the provisional debit is reversed; refunds allowed again."""
    if d.status != std.cat("evidence"):
        return reject(REJ_STALE)
    if not out.reserve(records={"dispute_won": 1, "posting": 2}):
        return RETRY
    d.status = std.cat("won")
    s.dispute_open, s.disputed = False, 0
    out.post_ledger(ctx.t, payment_id=ctx.self_id, debit=A_DISPUTES, credit=A_MERCHANT,
                    amount=d.amount)
    out.emit_dispute_won(ctx.t, payment_id=ctx.self_id, dispute_id=d.id, amount=d.amount)
    return COMMIT


@kernel(state="payment", instance="dispute", max=Res(records={"dispute_lost": 1}))
def accept_dispute(ctx, s, d, cmd, out):
    """Merchant doesn't contest; the dispute stays open until the chargeback posts."""
    if d.status != std.cat("opened"):
        return reject(REJ_STALE)
    if not out.reserve(records={"dispute_lost": 1}):
        return RETRY
    d.status = std.cat("lost")
    out.emit_dispute_lost(ctx.t, payment_id=ctx.self_id, dispute_id=d.id, amount=d.amount,
                          resolution=std.cat("accepted"))
    return COMMIT


@kernel(state="payment", instance="dispute", max=Res(records={"dispute_lost": 1}))
def lose_dispute(ctx, s, d, cmd, out):
    if d.status != std.cat("evidence"):
        return reject(REJ_STALE)
    if not out.reserve(records={"dispute_lost": 1}):
        return RETRY
    d.status = std.cat("lost")
    out.emit_dispute_lost(ctx.t, payment_id=ctx.self_id, dispute_id=d.id, amount=d.amount,
                          resolution=std.cat("issuer_ruled"))
    return COMMIT


@kernel(state="payment", instance="dispute",
        max=Res(records={"chargeback_posted": 1, "posting": 4, "settlement": 1}))
def post_chargeback(ctx, s, d, cmd, out):
    """Final: the disputed amount goes back through the network, plus a fee to the merchant."""
    cfg = ctx.cfg
    if d.status != std.cat("lost"):
        return reject(REJ_STALE)
    if not out.reserve(records={"chargeback_posted": 1, "posting": 4, "settlement": 1}):
        return RETRY
    fee = cfg.chargeback_fee
    d.status = std.cat("charged_back")
    s.charged_back = std.checked_add(s.charged_back, d.amount)
    s.dispute_open, s.disputed = False, 0
    out.post_ledger(ctx.t, payment_id=ctx.self_id, debit=A_DISPUTES, credit=A_SCHEME,
                    amount=d.amount)
    out.post_ledger(ctx.t, payment_id=ctx.self_id, debit=A_MERCHANT, credit=A_FEES, amount=fee)
    out.accumulate_settlement(ctx.t, merchant_id=s.merchant_id, chargebacks=d.amount, fees=fee)
    out.emit_chargeback_posted(ctx.t, payment_id=ctx.self_id, dispute_id=d.id,
                               merchant_id=s.merchant_id, amount=d.amount, fee=fee)
    return COMMIT


# ================================================================== merchant_risk shard
@kernel(state="merchant_risk", max=Res(records={"risk_evaluated": 1}, responses=1))
def risk_decide(ctx, s, cmd, out):
    """Screen one authorization request using only this shard's counters and the payload.

    Runs at the request's time in canonical order; the response reaches the payment at
    t + latency (>= 80 ms). Counters are 60 one-minute buckets, updated at commit.
    """
    cfg = ctx.cfg
    if not out.reserve(records={"risk_evaluated": 1}, responses=1):
        return RETRY                                   # nothing to reject: every request answered
    t, m = ctx.t, cmd.merchant_id
    small = cmd.amount < cfg.small_amount
    card_n = s.card_auths.add(cmd.card_id, t, 1)       # count in the trailing window, incl. this
    dev_n = s.device_auths.add(cmd.device_id, t, 1) if cmd.device_id != 0 else 0
    s.merchant_auths.add(m, t, 1)
    m_small = s.merchant_small.add(m, t, 1 if small else 0)
    mcc_median = ctx.reads.mcc.median_amount[cmd.mcc]

    score = ctx.reads.mcc.risk_base[cmd.mcc]
    score += cfg.w_card * std.checked_max(0, card_n - 1)
    score += cfg.w_device * std.checked_max(0, dev_n - cfg.device_free)
    score += cfg.w_small_burst if (small and m_small > cfg.small_burst) else 0
    score += cfg.w_cross_border if cmd.cross_border else 0
    score += cfg.w_prepaid if cmd.funding == std.cat("prepaid") else 0
    score += cfg.w_amount * std.ilog2(cmd.amount // std.checked_max(1, mcc_median) + 1)
    score += ctx.rng.normal_int(site=1, sd=cfg.score_noise)
    score = std.clamp(score, 0, 999)

    rule = std.cat("none")
    if card_n > cfg.max_card_auths_1h:
        decision, rule = R_DECLINE, std.cat("velocity_card")
    elif score >= cfg.decline_at:
        decision, rule = R_DECLINE, std.cat("score")
    elif score >= cfg.challenge_at and cmd.channel == std.cat("ecom"):
        decision = R_CHALLENGE
        if small and m_small > cfg.small_burst:
            rule = std.cat("small_burst")
        elif dev_n > cfg.device_free:
            rule = std.cat("velocity_device")
        else:
            rule = std.cat("score")
    else:
        decision = R_APPROVE
    if decision == R_DECLINE:
        s.merchant_declines.add(m, t, 1)
    out.emit_risk_evaluated(t, merchant_group=ctx.self_id, payment_id=cmd.payment_id,
                            card_id=cmd.card_id, merchant_id=m, device_id=cmd.device_id,
                            amount=cmd.amount, score=score,
                            decision=std.cat_of_response(decision), rule=rule,
                            card_auths_1h=card_n, device_auths_1h=dev_n, merchant_small_1h=m_small)
    out.respond(cmd, decision, score=score, rule_velocity=rule == std.cat("velocity_card"))
    return COMMIT


@kernel(state="merchant_risk", max=Res(records={"refund_screened": 1}, responses=1))
def refund_check(ctx, s, cmd, out):
    """Merchant daily refund headroom. The shard's side of the refund hold.

    An approval counts against today's limit even if the payment later releases its hold
    (a dispute opened meanwhile): the limit is conservative, and no message flows back.
    """
    if not out.reserve(records={"refund_screened": 1}, responses=1):
        return RETRY
    i = s.merchant_slot(cmd.merchant_id)
    today = std.day_index(ctx.t)
    if s.refund_day[i] != today:                       # lazy daily reset of this merchant only
        s.refund_day[i], s.refund_sum[i] = today, 0
    limit = ctx.reads.merchant.refund_limit_daily[cmd.merchant_id]
    after = std.checked_add(s.refund_sum[i], cmd.amount)
    ok = after <= limit
    if ok:
        s.refund_sum[i] = after
    out.emit_refund_screened(ctx.t, merchant_group=ctx.self_id, payment_id=cmd.payment_id,
                             refund_id=cmd.refund_id, merchant_id=cmd.merchant_id,
                             amount=cmd.amount, refunded_today=s.refund_sum[i], daily_limit=limit,
                             decision=std.cat("approved") if ok else std.cat("declined"))
    out.respond(cmd, R_REFUND_OK if ok else R_REFUND_DECLINED)
    return COMMIT
