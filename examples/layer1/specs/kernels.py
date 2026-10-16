"""Handwritten kernels for the layer1 pack.

Every kernel follows the action interface:
    1. validate   read state, maybe reject(...)       no writes yet
    2. reserve    out.reserve(...) for every resource  RETRY if the slab is full
    3. commit     mutate state, emit, schedule         cannot fail
Random draws use ctx.rng.<dist>(site=N, ...); each draw site has its own number, so edits to
one site never shift draws at another. Draws inside a loop reuse one site; the runtime counts
them (k), so a retry replays the same sequence.

Amounts are int64 quanta (1 quantum = 10^6 wei) and use checked helpers. Timeline strings in
the config ("day 18", "3h", "12s") are resolved to absolute or relative µs by the plan, so
kernels only ever see integers. Params of exposed actions may be given as Dists in
with_params(...); the runtime draws them, one reserved site per param, before the kernel runs.

Wallet side (owner): beliefs only. The wallet never reads chain state; it learns balances,
nonces and the base fee from receipts and RPC responses, which apply_receipt / apply_account
fold into its local view before any process sees them.

Chain side (shard): the authoritative state and the tx envelope (validity first, then gas,
then effects only on success). Block building fans out in fixed 64-tx sub-steps.
"""

from neorisk_simkit.engine import COMMIT, RETRY, Local, Res, kernel, reject
from neorisk_simkit import std

# ------------------------------------------------------------------ enums (indices into pack)
K_NATIVE, K_TOKEN, K_SWAP, K_MINT, K_BRIDGE, K_CLAIM = 0, 1, 2, 3, 4, 5     # TX_KINDS
W_RETAIL, W_TRADER, W_BOT, W_EXCHANGE = 0, 1, 2, 3                          # WALLET_KINDS
ST_SUCCESS, ST_REVERTED = 0, 1
O_SUCCESS, O_REVERTED, O_DROPPED = 0, 1, 2                                  # receipt outcome
# DROP_REASONS
D_NONCE_TOO_LOW, D_INSUFFICIENT_FUNDS, D_GAS_LIMIT, D_SENDER_SLOTS, D_POOL_FULL = 0, 1, 2, 3, 4
D_EXPIRED_UNDERPRICED, D_EXPIRED_GAP, D_EXPIRED = 5, 6, 7
# REVERT_REASONS
RV_SLIPPAGE, RV_SOLD_OUT, RV_NOT_OPEN, RV_TOKEN_BALANCE, RV_OUT_OF_GAS = 0, 1, 2, 3, 4
RV_NOT_ELIGIBLE, RV_ALREADY_CLAIMED, RV_CLAIM_CLOSED, RV_POOL_EXHAUSTED, RV_LOGIC = 5, 6, 7, 8, 9
# contract kind a tx kind calls (CONTRACT_KINDS index; -1: none)
C_TOKEN, C_POOL, C_COLLECTION, C_BRIDGE, C_AIRDROP = 0, 1, 2, 3, 4
KIND_CONTRACT = (-1, C_TOKEN, C_POOL, C_COLLECTION, C_BRIDGE, C_AIRDROP)

# ------------------------------------------------------------------ command ids
C_SESSION = 1           # timer: start an activity session
C_TX = 2                # timer: next transaction in the session
C_PAYOUT = 3            # timer: exchange pays out a batch of withdrawals
M_WITHDRAWAL = 4        # owner message: a user asked this exchange for a payout
R_INCLUDED = 10         # response: submit_tx included (success or reverted)
R_DROPPED = 11          # response: submit_tx dropped
R_ACCOUNT = 12          # response: query_account
R_QUOTE = 13            # response: query_quote
WALLET_COMMANDS = (C_SESSION, C_TX, R_INCLUDED, R_DROPPED, R_ACCOUNT, R_QUOTE)
EXCHANGE_COMMANDS = (M_WITHDRAWAL, C_PAYOUT, R_INCLUDED, R_DROPPED, R_ACCOUNT)
C_BUILD = 20            # chain timer: build the block for this slot (every slot)
C_EXPIRE = 21           # chain timer: drop expired pending txs (every 5 min)

# priorities at equal time (lower runs first); responses before own timers.
# continue_at always runs at the top priority, ahead of both.
PRIO_RESPONSE, PRIO_TIMER = 1, 5

REJ_STALE = 1
REJ_BURST_OVER = 2
REJ_BELIEVED_BROKE = 3      # the wallet's own view says it can't pay; nothing is sent
REJ_NO_TOKENS = 4
REJ_TOO_MANY_PENDING = 5
REJ_NOTHING_OPEN = 6
REJ_QUEUE_FULL = 7
REJ_MISSED_SLOT = 8         # no block in this slot (counted, not an error)

ALL = -1                    # param sentinel: "everything I believe I have" (value or tokens)
SUB = 64                    # fixed fan-out sub-step: txs considered per build/expire sub-step
INTRINSIC_GAS = 21_000
MAX_TOKENS = 8
PAYOUT_QUEUE = 256
PAYOUT_BATCH = 16
SECOND = 1_000_000          # µs
MINUTE = 60 * SECOND
HOUR = 60 * MINUTE

# Per-owner scratch, laid out next to the wallet row; freed when the owner retires
WALLET_LOCAL = Local(
    next_nonce="i64",           # believed next nonce
    in_flight="i16",            # submitted, no receipt yet
    held="i64",                 # worst-case cost (gas_limit x max_fee + value) of in-flight txs
    est_balance="i64",          # last chain balance seen, minus held
    est_token="i64[8]",         # last token balances seen, by token slot
    est_base_fee="i64",
    synced_at="ts",
    resync="i8",                # a drop may have left a nonce gap: reset when in_flight hits 0
    burst_left="i16",
    awaiting="ref",             # retail: tx whose receipt we wait for before the next one
    q_tag="ref", q_pool="ref", q_eth_in="i8", q_amount="i64",   # swap waiting for its quote
    target_hits="i16",          # own successful airdrop-target calls counted by the chain
    claimed="i8",
)
# Exchanges add a payout queue; the wallet fields stay a prefix, so the hooks work on both
EXCHANGE_LOCAL = WALLET_LOCAL.extend(
    pay_to="ref[256]", pay_amt="i64[256]", pay_head="i16", pay_n="i16",
)


# ================================================================== wallet: activity
@kernel(state="wallet", local=WALLET_LOCAL, commands=WALLET_COMMANDS,
        max=Res(records={"tx_submitted": 1}, timers=2, requests=1))
def wallet_activity(ctx, s, loc, cmd, out):
    """One wallet's sessions and transactions. Dispatches on the command kind."""
    a = ctx.cfg.activity
    if cmd.kind == C_SESSION:
        return _start_session(ctx, s, loc, out, a)
    if cmd.kind == C_TX:
        return _next_tx(ctx, s, loc, out, a)
    if cmd.kind == R_ACCOUNT:
        return _on_account(ctx, s, loc, out, a)
    if cmd.kind == R_QUOTE:
        return _on_quote(ctx, s, loc, cmd, out, a)
    if cmd.kind == R_INCLUDED or cmd.kind == R_DROPPED:
        return _on_receipt(ctx, s, loc, cmd, out, a)
    return reject(REJ_STALE)


def _start_session(ctx, s, loc, out, a):
    if s.status != std.ACTIVE:
        return reject(REJ_STALE)                                   # dormant: no more sessions
    stale = ctx.t - loc.synced_at > a.sync_every
    if not out.reserve(timers=2, requests=1 if stale else 0):
        return RETRY
    loc.burst_left = 1 + ctx.rng.geometric(site=1, mean=a.burst_mean[s.kind] - 1.0)
    if stale:                                                      # R_ACCOUNT starts the burst
        out.request_query_account(ctx.t, shard=0, wallet_id=ctx.self_id)
    else:
        out.timer(ctx.t + ctx.rng.exp_us(site=2, mean_s=20), C_TX, prio=PRIO_TIMER)
    gap = ctx.rng.pareto_us(site=3, alpha=a.session_gap_alpha[s.kind],
                            min_h=a.session_gap_min_h[s.kind] * a.activity_gap_scale[s.activity])
    out.timer(ctx.t + gap, C_SESSION, prio=PRIO_TIMER)
    return COMMIT


def _next_tx(ctx, s, loc, out, a):
    if loc.burst_left <= 0:
        return reject(REJ_BURST_OVER)
    if loc.awaiting != 0 or loc.q_tag != 0 or loc.in_flight >= a.max_in_flight[s.kind]:
        if not out.reserve(timers=1):                              # wallet-side pending limit
            return RETRY
        out.timer(ctx.t + ctx.rng.exp_us(site=10, mean_s=12), C_TX, prio=PRIO_TIMER)
        return COMMIT
    if loc.est_base_fee > s.fee_ceiling:                           # demand reacts to the fee
        if not out.reserve(timers=1):
            return RETRY
        out.timer(ctx.t + ctx.rng.dist_us(site=11, d=a.defer_when_fee_high), C_TX, prio=PRIO_TIMER)
        return COMMIT
    kind = _pick_kind(ctx, s, loc, a)                              # sites 12, 13
    if kind == K_SWAP:
        return _ask_quote(ctx, s, loc, out, a)
    to_wallet, contract, value, tok = _draw_target(ctx, s, loc, a, kind)   # sites 20-28
    if kind != K_NATIVE and contract == 0:
        return reject(REJ_NOTHING_OPEN)                            # e.g. no collection minting
    if kind == K_TOKEN and tok <= 0:
        return reject(REJ_NO_TOKENS)
    gas_limit = _gas_limit(ctx, kind, contract, a, site=30)        # sites 30, 31
    tip = _tip(ctx, s, a, site=32)
    max_fee, cost = _price(loc, a, tip, gas_limit, value)
    if cost > loc.est_balance:
        return reject(REJ_BELIEVED_BROKE)                          # session ends: no next timer
    if not out.reserve(records={"tx_submitted": 1}, requests=1, timers=1):
        return RETRY
    tx = _commit_submit(ctx, loc, out, kind, to_wallet, contract, value, tok, 0, gas_limit,
                        max_fee, tip, cost)
    if kind == K_CLAIM:
        loc.claimed = 1
    _after_submit(ctx, s, loc, out, a, tx)
    return COMMIT


def _pick_kind(ctx, s, loc, a):
    ad = ctx.cfg.airdrop
    in_window = ad.claim_opens <= ctx.t < ad.claim_opens + ad.claim_window
    if (in_window and loc.claimed == 0 and loc.target_hits >= ad.min_interactions
            and ctx.rng.bernoulli(site=13, p=a.claim_p)):
        return K_CLAIM                                             # the wallet knows it qualified
    return ctx.rng.categorical(site=12, p=a.kind_mix[s.kind])


def _draw_target(ctx, s, loc, a, kind):
    """Counterparty, contract, value and token amount for a non-swap tx. Read-only."""
    c = ctx.reads.contract
    to_wallet, contract, value, tok = 0, 0, 0, 0
    if kind == K_NATIVE:
        if ctx.rng.bernoulli(site=20, p=a.exchange_deposit_p):
            to_wallet = ctx.refs.exchange.get(ctx.self_id)
        else:
            to_wallet = ctx.refs.contacts.pick(ctx.self_id, ctx.rng.uniform(site=21))
        value = std.share_of(loc.est_balance, ctx.rng.dist(site=22, d=a.transfer_share))
    elif kind == K_TOKEN:
        contract = c.sample(C_TOKEN, ctx.rng.uniform(site=23))
        to_wallet = ctx.refs.contacts.pick(ctx.self_id, ctx.rng.uniform(site=27))
        tok = std.share_of(loc.est_token[c.slot[contract]], ctx.rng.dist(site=24, d=a.transfer_share))
    elif kind == K_MINT:
        contract = c.sample_open(C_COLLECTION, ctx.t, ctx.rng.uniform(site=25))   # 0 if none
        value = c.price[contract] if contract != 0 else 0
    elif kind == K_BRIDGE:
        contract = c.sample(C_BRIDGE, ctx.rng.uniform(site=26))
        value = std.share_of(loc.est_balance, ctx.rng.dist(site=28, d=a.transfer_share))
    elif kind == K_CLAIM:
        contract = c.first(C_AIRDROP)
    return to_wallet, contract, value, tok


def _ask_quote(ctx, s, loc, out, a):
    """Swaps quote first (RPC), then submit with a slippage limit when the quote returns."""
    c = ctx.reads.contract
    pool = c.sample(C_POOL, ctx.rng.uniform(site=40))
    held_tok = loc.est_token[c.token_slot[pool]]
    eth_in = held_tok <= 0 or ctx.rng.bernoulli(site=41, p=0.55)
    share = ctx.rng.dist(site=42, d=a.swap_share)
    amt = std.share_of(loc.est_balance, share) if eth_in else std.share_of(held_tok, share)
    if amt <= 0:
        return reject(REJ_BELIEVED_BROKE)
    if not out.reserve(requests=1):
        return RETRY
    loc.q_tag, loc.q_pool, loc.q_eth_in, loc.q_amount = out.new_id("quote"), pool, eth_in, amt
    out.request_query_quote(ctx.t, shard=0, pool=pool, eth_in=eth_in, amount_in=amt,
                            tag=loc.q_tag)
    return COMMIT


def _on_quote(ctx, s, loc, cmd, out, a):
    if cmd.tag != loc.q_tag:
        return reject(REJ_STALE)
    value = loc.q_amount if loc.q_eth_in else 0
    tok = 0 if loc.q_eth_in else loc.q_amount
    min_out = std.checked_muldiv(cmd.amount_out, 10_000 - a.slippage_bps[s.kind], 10_000)
    gas_limit = _gas_limit(ctx, K_SWAP, loc.q_pool, a, site=43)    # sites 43, 44
    tip = _tip(ctx, s, a, site=45)
    max_fee, cost = _price(loc, a, tip, gas_limit, value)
    ok = cmd.amount_out > 0 and cost <= loc.est_balance
    if not out.reserve(records={"tx_submitted": 1 if ok else 0}, requests=1 if ok else 0,
                       timers=1):
        return RETRY
    pool = loc.q_pool
    loc.q_tag, loc.q_pool, loc.q_eth_in, loc.q_amount = 0, 0, 0, 0
    if not ok:                                                     # bad quote or short: skip it
        loc.burst_left -= 1
        if loc.burst_left > 0:
            out.timer(ctx.t + ctx.rng.exp_us(site=46, mean_s=a.intra_burst_s[s.kind]), C_TX,
                      prio=PRIO_TIMER)
        return COMMIT
    tx = _commit_submit(ctx, loc, out, K_SWAP, 0, pool, value, tok, min_out, gas_limit,
                        max_fee, tip, cost)
    _after_submit(ctx, s, loc, out, a, tx)
    return COMMIT


def _on_account(ctx, s, loc, out, a):
    """Beliefs were already refreshed by apply_account; this only starts the burst."""
    if loc.burst_left <= 0:
        return reject(REJ_STALE)
    if not out.reserve(timers=1):
        return RETRY
    out.timer(ctx.t + ctx.rng.exp_us(site=50, mean_s=15), C_TX, prio=PRIO_TIMER)
    return COMMIT


def _on_receipt(ctx, s, loc, cmd, out, a):
    """Retail waits for each receipt before its next tx; others ignore receipts here."""
    if cmd.tx_id != loc.awaiting:
        return reject(REJ_STALE)
    if not out.reserve(timers=1):
        return RETRY
    loc.awaiting = 0
    if loc.burst_left > 0:
        out.timer(ctx.t + ctx.rng.exp_us(site=51, mean_s=a.intra_burst_s[s.kind]), C_TX,
                  prio=PRIO_TIMER)
    return COMMIT


def _after_submit(ctx, s, loc, out, a, tx):
    """Called after reserve; schedules the next tx or waits for this one's receipt."""
    loc.burst_left -= 1
    if a.wait_for_receipt[s.kind]:
        loc.awaiting = tx
    elif loc.burst_left > 0:
        out.timer(ctx.t + ctx.rng.exp_us(site=52, mean_s=a.intra_burst_s[s.kind]), C_TX,
                  prio=PRIO_TIMER)


# ================================================================== wallet: shared tx helpers
def _gas_limit(ctx, kind, contract, a, site):
    """The wallet's estimate times a safety buffer. Plain transfers use exactly 21,000."""
    if kind == K_NATIVE:
        return INTRINSIC_GAS
    c = ctx.reads.contract
    est = c.gas_mean[contract] * (1.0 + ctx.rng.normal(site=site, mean=0.0, sd=a.gas_estimate_cv))
    buf = ctx.rng.dist(site=site + 1, d=a.gas_buffer)
    return max(INTRINSIC_GAS, int(est * buf))


def _tip(ctx, s, a, site):
    return max(1, ctx.rng.lognormal_minor(site=site, median=a.tip_median[s.kind],
                                          sigma=a.tip_sigma[s.kind]))


def _price(loc, a, tip, gas_limit, value):
    """max_fee = headroom x believed base fee + tip; cost = worst case the chain will check."""
    max_fee = std.checked_add(std.checked_mul(loc.est_base_fee, a.base_fee_headroom), tip)
    cost = std.checked_add(std.checked_mul(gas_limit, max_fee), value)
    return max_fee, cost


def _commit_submit(ctx, loc, out, kind, to_wallet, contract, value, tok, min_out, gas_limit,
                   max_fee, tip, cost):
    """Use the believed nonce, hold the worst-case cost, emit and send. After reserve only."""
    tx = out.new_id("tx")
    nonce = loc.next_nonce
    loc.next_nonce = std.checked_add(nonce, 1)
    loc.in_flight += 1
    loc.held = std.checked_add(loc.held, cost)                     # owner-side hold
    loc.est_balance = std.checked_sub(loc.est_balance, cost)
    out.emit_tx_submitted(ctx.t, tx_id=tx, sender=ctx.self_id, nonce=nonce, tx_kind=kind,
                          to_wallet=to_wallet, contract_id=contract, value=value,
                          gas_limit=gas_limit, max_fee_per_gas=max_fee,
                          max_priority_fee_per_gas=tip)
    out.request_submit_tx(ctx.t, shard=0, tx_id=tx, sender=ctx.self_id, nonce=nonce, kind=kind,
                          to_wallet=to_wallet, contract=contract, value=value, token_amount=tok,
                          min_out=min_out, gas_limit=gas_limit, max_fee_per_gas=max_fee,
                          max_priority_fee_per_gas=tip, cost=cost, submitted_at=ctx.t)
    return tx


# ================================================================== wallet: response hooks
@kernel(state="wallet", local=WALLET_LOCAL, max=Res(records={"receipt_received": 1}))
def apply_receipt(ctx, s, loc, cmd, out):
    """owner_hook of submit_tx: runs in the sender on every receipt, before the waiting
    process (wallet_activity, an overlay machine, ...) sees the response."""
    if not out.reserve(records={"receipt_received": 1}):
        return RETRY
    included = cmd.kind == R_INCLUDED
    loc.in_flight -= 1
    loc.held = std.checked_sub(loc.held, cmd.cost)                 # release the hold
    loc.est_balance = std.checked_sub(cmd.balance_after, loc.held)  # truth at decision time
    loc.est_base_fee = cmd.base_fee
    loc.synced_at = ctx.t
    if included:
        outcome = O_SUCCESS if cmd.status == ST_SUCCESS else O_REVERTED
        if cmd.token_slot >= 0:
            loc.est_token[cmd.token_slot] = cmd.token_balance_after
        if cmd.counted:
            loc.target_hits = std.sat_add(loc.target_hits, 1)
    else:
        outcome = O_DROPPED
        loc.resync = 1                                             # later nonces may be stuck
    if loc.resync == 1 and loc.in_flight == 0:
        loc.next_nonce, loc.resync = cmd.account_nonce, 0
    out.emit_receipt_received(ctx.t, tx_id=cmd.tx_id, sender=ctx.self_id, outcome=outcome,
                              block_number=cmd.block_number if included else None,
                              latency_ms=(ctx.t - cmd.submitted_at) // 1_000)
    return COMMIT


@kernel(state="wallet", local=WALLET_LOCAL, max=Res())
def apply_account(ctx, s, loc, cmd, out):
    """owner_hook of query_account: refresh beliefs from an RPC snapshot. Owner-local writes
    only: no records, timers or requests, so there is nothing to reserve and it can't fail."""
    loc.est_balance = std.checked_sub(cmd.balance, loc.held)
    for i in range(MAX_TOKENS):
        loc.est_token[i] = cmd.token_balances[i]
    loc.est_base_fee = cmd.base_fee
    loc.synced_at = ctx.t
    if loc.in_flight == 0:
        loc.next_nonce, loc.resync = cmd.nonce, 0
    return COMMIT


# ================================================================== wallet: exposed actions
@kernel(state="wallet", local=WALLET_LOCAL, max=Res(records={"tx_submitted": 1}, requests=1),
        params=("tx_kind", "to_wallet", "contract", "value", "token_amount", "min_out",
                "gas_limit", "tip", "max_fee"))
def send_tx(ctx, s, loc, cmd, out):
    """One transaction with explicit parameters; the action overlays drive. Unset params
    (0) fall back to the wallet's own habits: popular contract, estimated gas, usual tip,
    max_fee = headroom x believed base fee + tip. value=ALL / token_amount=ALL sweep what the
    wallet believes it holds."""
    a, c, prm = ctx.cfg.activity, ctx.reads.contract, cmd.params
    if loc.in_flight >= a.max_in_flight[s.kind]:
        return reject(REJ_TOO_MANY_PENDING)
    contract = prm.contract
    if contract == 0 and KIND_CONTRACT[prm.tx_kind] >= 0:
        contract = c.sample(KIND_CONTRACT[prm.tx_kind], ctx.rng.uniform(site=60))
    gas_limit = prm.gas_limit if prm.gas_limit > 0 else _gas_limit(ctx, prm.tx_kind, contract,
                                                                   a, site=61)   # 61, 62
    tip = prm.tip if prm.tip > 0 else _tip(ctx, s, a, site=63)
    max_fee, gas_cost = _price(loc, a, tip, gas_limit, 0)
    if prm.max_fee > 0:                                            # caller pins the fee cap
        max_fee = max(prm.max_fee, tip)
        gas_cost = std.checked_mul(gas_limit, max_fee)
    value = prm.value
    if value == ALL:
        value = loc.est_balance - gas_cost                         # sweep all but worst-case gas
    elif prm.tx_kind == K_MINT and value == 0:
        value = c.price[contract]
    tok = prm.token_amount
    if tok == ALL:
        tok = loc.est_token[c.token_slot[contract]] if contract != 0 else 0
    if value < 0 or std.checked_add(gas_cost, value) > loc.est_balance:
        return reject(REJ_BELIEVED_BROKE)
    if (prm.tx_kind == K_TOKEN or (prm.tx_kind == K_SWAP and value == 0)) and tok <= 0:
        return reject(REJ_NO_TOKENS)
    if not out.reserve(records={"tx_submitted": 1}, requests=1):
        return RETRY
    _commit_submit(ctx, loc, out, prm.tx_kind, prm.to_wallet, contract, value, tok, prm.min_out,
                   gas_limit, max_fee, tip, std.checked_add(gas_cost, value))
    return COMMIT


@kernel(state="wallet", max=Res(requests=1))
def sync_account(ctx, s, cmd, out):
    """RPC balance/nonce refresh; apply_account folds the answer into the wallet's view."""
    if not out.reserve(requests=1):
        return RETRY
    out.request_query_account(ctx.t, shard=0, wallet_id=ctx.self_id)
    return COMMIT


@kernel(state="wallet", max=Res(records={"cex_withdrawal_requested": 1}, messages=1),
        params=("amount",))
def cex_withdraw(ctx, s, cmd, out):
    """Ask this wallet's exchange for a payout (off-chain). Owner-to-owner message, delivered
    at the next step boundary or later; the exchange pays with an ordinary transfer."""
    exchange = ctx.refs.exchange.get(ctx.self_id)
    amt = cmd.params.amount
    if amt <= 0:
        return reject(REJ_BELIEVED_BROKE)
    if not out.reserve(records={"cex_withdrawal_requested": 1}, messages=1):
        return RETRY
    out.emit_cex_withdrawal_requested(ctx.t, wallet_id=ctx.self_id, exchange_id=exchange,
                                      amount=amt)
    out.send_cex_withdrawal(ctx.t, to=exchange, wallet_id=ctx.self_id, amount=amt)
    return COMMIT


# ================================================================== exchange hot wallet
@kernel(state="wallet", local=EXCHANGE_LOCAL, commands=EXCHANGE_COMMANDS,
        max=Res(records={"tx_submitted": PAYOUT_BATCH}, requests=PAYOUT_BATCH + 1, timers=1))
def cex_hot_wallet(ctx, s, loc, cmd, out):
    """Queues withdrawal requests and pays them out in batches of up to 16 transfers."""
    a = ctx.cfg.activity
    if cmd.kind == M_WITHDRAWAL:
        if loc.pay_n >= PAYOUT_QUEUE:
            return reject(REJ_QUEUE_FULL)                          # counted; user stays unfunded
        arm = loc.pay_n == 0
        if not out.reserve(timers=1 if arm else 0):
            return RETRY
        i = (loc.pay_head + loc.pay_n) % PAYOUT_QUEUE
        loc.pay_to[i], loc.pay_amt[i] = cmd.wallet_id, cmd.amount
        loc.pay_n += 1
        if arm:                                                    # exchanges batch payouts
            out.timer(ctx.t + ctx.rng.dist_us(site=1, d=a.payout_delay), C_PAYOUT, prio=PRIO_TIMER)
        return COMMIT
    if cmd.kind == C_PAYOUT:
        return _pay_batch(ctx, s, loc, out, a)
    return reject(REJ_STALE)                                       # receipts: hooks did the work


def _pay_batch(ctx, s, loc, out, a):
    room = a.max_in_flight[W_EXCHANGE] - loc.in_flight
    tip = a.tip_median[W_EXCHANGE]                                 # fixed policy, no draw
    max_fee, gas_cost = _price(loc, a, tip, INTRINSIC_GAS, 0)
    n, budget = 0, loc.est_balance                                 # preflight, read-only
    while n < min(loc.pay_n, PAYOUT_BATCH, room):
        need = std.checked_add(gas_cost, loc.pay_amt[(loc.pay_head + n) % PAYOUT_QUEUE])
        if need > budget:
            break
        budget -= need
        n += 1
    stale = ctx.t - loc.synced_at > HOUR
    if not out.reserve(records={"tx_submitted": n}, requests=n + (1 if stale else 0), timers=1):
        return RETRY
    for _ in range(n):
        i = loc.pay_head
        amt = loc.pay_amt[i]
        _commit_submit(ctx, loc, out, K_NATIVE, loc.pay_to[i], 0, amt, 0, 0, INTRINSIC_GAS,
                       max_fee, tip, std.checked_add(gas_cost, amt))
        loc.pay_head = (i + 1) % PAYOUT_QUEUE
        loc.pay_n -= 1
    if stale:
        out.request_query_account(ctx.t, shard=0, wallet_id=ctx.self_id)
    if loc.pay_n > 0:
        out.timer(ctx.t + 30 * SECOND, C_PAYOUT, prio=PRIO_TIMER)
    return COMMIT


# ================================================================== chain: request handlers
@kernel(state="chain", max=Res(records={"tx_dropped": 1}, responses=1))
def admit_tx(ctx, s, cmd, out):
    """A submit_tx request enters the chain's heap. Admission only; validity (nonce, balance)
    is decided at inclusion, against the state of that moment."""
    acct = s.account(cmd.sender)
    reason = -1
    if cmd.gas_limit < INTRINSIC_GAS or cmd.gas_limit > ctx.cfg.gas_limit:
        reason = D_GAS_LIMIT
    elif cmd.nonce < s.nonce[acct] or s.txpool.has(acct, cmd.nonce):
        reason = D_NONCE_TOO_LOW                                   # no replacement (out of scope)
    elif s.txpool.sender_count(acct) >= ctx.cfg.sender_slots:
        reason = D_SENDER_SLOTS
    elif s.txpool.full():
        reason = D_POOL_FULL
    if reason < 0:
        # No slab resource is used: the pool is fixed-capacity shard state, checked above.
        # The response is deferred to build_block (included / dropped) or expire_pending.
        s.txpool.insert(cmd, sender=acct, arrived=ctx.t)
        return COMMIT
    if not out.reserve(records={"tx_dropped": 1}, responses=1):
        return RETRY
    _drop(ctx, s, cmd, acct, reason, out)
    return COMMIT


@kernel(state="chain", max=Res(responses=1))
def query_account(ctx, s, cmd, out):
    """eth_getBalance + getTransactionCount + token balances: an immutable snapshot."""
    acct = s.account(cmd.wallet_id)
    if not out.reserve(responses=1):
        return RETRY
    out.respond(cmd, "ok", balance=s.balance[acct], nonce=s.nonce[acct],
                              token_balances=s.token_balance[acct], base_fee=s.base_fee)
    return COMMIT


@kernel(state="chain", max=Res(responses=1))
def query_quote(ctx, s, cmd, out):
    """Router quote at the current reserves; it can be stale by inclusion time."""
    if not out.reserve(responses=1):
        return RETRY
    amt = _cp_out(ctx, s, cmd.pool, cmd.eth_in, cmd.amount_in)
    out.respond(cmd, "ok", amount_out=amt, tag=cmd.tag)
    return COMMIT


# ================================================================== chain: block building
@kernel(state="chain", substep=SUB,
        max=Res(records={"tx_included": SUB, "tx_dropped": SUB, "transfer": SUB,
                         "token_transfer": SUB, "swap": SUB, "nft_minted": SUB,
                         "bridge_deposit": SUB, "airdrop_claimed": SUB, "block_produced": 1},
                responses=SUB))
def build_block(ctx, s, cmd, out):
    """One slot's block. Considers at most 64 pending txs per sub-step in priority-fee order
    (one nonce at a time per sender), continued at the same time and top priority until the
    gas limit is reached or nothing eligible is left; then seals the block.

    Every request with time < slot time is already in the pool: the slot timer runs only once
    the safe horizon has passed it."""
    cfg = ctx.cfg
    if cmd.cursor == 0 and ctx.rng.bernoulli(site=1, p=cfg.missed_slot_p):
        return reject(REJ_MISSED_SLOT)                             # no block; base fee unchanged
    if not out.reserve(records={"tx_included": SUB, "tx_dropped": SUB, "transfer": SUB,
                                "token_transfer": SUB, "swap": SUB, "nft_minted": SUB,
                                "bridge_deposit": SUB, "airdrop_claimed": SUB,
                                "block_produced": 1}, responses=SUB):
        return RETRY
    if cmd.cursor == 0:
        _open_block(ctx, s)                                        # site 2
    considered = 0
    while considered < SUB and cfg.gas_limit - s.blk_gas >= INTRINSIC_GAS:
        h = s.txpool.pop_best(min_fee=s.base_fee)    # best effective tip among sender heads
        if h < 0:
            break
        considered += 1
        tx = s.txpool.view(h)
        if tx.gas_limit > cfg.gas_limit - s.blk_gas:
            s.txpool.park(h)                         # doesn't fit; eligible again next block
            continue
        _apply_envelope(ctx, s, h, tx, out)
    if considered == SUB and cfg.gas_limit - s.blk_gas >= INTRINSIC_GAS:
        out.continue_at(ctx.t, cursor=cmd.cursor + considered)    # same time, top priority
        return COMMIT
    _seal_block(ctx, s, out)                                       # sites 20, 21
    return COMMIT


def _open_block(ctx, s):
    s.block_number = std.checked_add(s.block_number, 1)
    s.blk_gas, s.blk_txs, s.blk_logs, s.blk_tips, s.blk_burned = 0, 0, 0, 0, 0
    s.blk_recipient = s.system_account("fee_recipient", ctx.rng.uniform(site=2))


def _apply_envelope(ctx, s, h, tx, out):
    """Validity first, then gas, then effects only on success. Called after reserve."""
    a = s.account(tx.sender)
    if tx.nonce < s.nonce[a]:
        _drop(ctx, s, tx, a, D_NONCE_TOO_LOW, out)
        s.txpool.free(h)
        return
    if tx.nonce > s.nonce[a]:
        s.txpool.park(h)                             # nonce gap: waits, expires after pool_ttl
        return
    max_cost = std.checked_add(std.checked_mul(tx.gas_limit, tx.max_fee_per_gas), tx.value)
    if s.balance[a] < max_cost:
        _drop(ctx, s, tx, a, D_INSUFFICIENT_FUNDS, out)
        s.txpool.free(h)
        return
    reason, gas, amt_out = _plan(ctx, s, tx, a)                    # read-only; sites 10-12
    tip = min(tx.max_priority_fee_per_gas, tx.max_fee_per_gas - s.base_fee)
    price = s.base_fee + tip
    fee = std.checked_mul(gas, price)
    burned = std.checked_mul(gas, s.base_fee)
    tips = fee - burned
    s.balance[a] = std.checked_sub(s.balance[a], fee)              # gas is charged either way
    s.balance[s.blk_recipient] = std.checked_add(s.balance[s.blk_recipient], tips)
    s.burned = std.checked_add(s.burned, burned)
    s.nonce[a] = std.checked_add(s.nonce[a], 1)                    # included: nonce + 1 always
    idx = s.blk_txs
    s.blk_txs += 1
    s.blk_gas = std.checked_add(s.blk_gas, gas)
    s.blk_tips = std.checked_add(s.blk_tips, tips)
    s.blk_burned = std.checked_add(s.blk_burned, burned)
    status = ST_SUCCESS if reason < 0 else ST_REVERTED
    out.emit_tx_included(ctx.t, tx_id=tx.tx_id, sender=tx.sender, nonce=tx.nonce,
                         block_number=s.block_number, tx_index=idx, tx_kind=tx.kind,
                         status=status, revert_reason=reason if reason >= 0 else None,
                         gas_used=gas, effective_gas_price=price, priority_fee_per_gas=tip,
                         fee_burned=burned, priority_fee=tips)
    tslot, tbal, counted = -1, 0, 0
    if status == ST_SUCCESS:                                       # a revert moves no value
        tslot, tbal = _effects(ctx, s, tx, a, amt_out, out)
        if (ctx.reads.contract.airdrop_target[tx.contract] and tx.contract != 0
                and ctx.t < ctx.cfg.airdrop.snapshot_at):
            s.interactions[a] = std.sat_add(s.interactions[a], 1)
            counted = 1
    out.respond(tx, "included", block_number=s.block_number,
                          status=status, gas_used=gas, effective_gas_price=price,
                          balance_after=s.balance[a], account_nonce=s.nonce[a],
                          token_slot=tslot, token_balance_after=tbal, base_fee=s.base_fee,
                          counted=counted)
    s.txpool.free(h)


def _plan(ctx, s, tx, a):
    """Decide status, revert reason and gas used without writing. Returns (reason or -1,
    gas_used, amount_out)."""
    c, ad = ctx.reads.contract, ctx.cfg.airdrop
    need = INTRINSIC_GAS
    if tx.kind != K_NATIVE:                                        # true gas of a successful run
        need = max(INTRINSIC_GAS, int(c.gas_mean[tx.contract] * ctx.rng.lognormal(
            site=10, median=1.0, sigma=c.gas_cv[tx.contract])))
    reason, amt_out = -1, 0
    if tx.kind == K_TOKEN:
        if s.token_balance[a, c.slot[tx.contract]] < tx.token_amount:
            reason = RV_TOKEN_BALANCE
    elif tx.kind == K_SWAP:
        eth_in = tx.value > 0
        if not eth_in and s.token_balance[a, c.token_slot[tx.contract]] < tx.token_amount:
            reason = RV_TOKEN_BALANCE
        else:
            amt_out = _cp_out(ctx, s, tx.contract, eth_in, tx.value if eth_in else tx.token_amount)
            if amt_out <= 0 or amt_out < tx.min_out:
                reason = RV_SLIPPAGE                               # price moved since the quote
    elif tx.kind == K_MINT:
        if ctx.t < c.opens_at[tx.contract]:
            reason = RV_NOT_OPEN
        elif s.minted[c.slot[tx.contract]] >= c.supply[tx.contract]:
            reason = RV_SOLD_OUT
        elif tx.value < c.price[tx.contract]:
            reason = RV_LOGIC
    elif tx.kind == K_CLAIM:
        if not (ad.claim_opens <= ctx.t < ad.claim_opens + ad.claim_window):
            reason = RV_CLAIM_CLOSED
        elif s.claimed[a]:
            reason = RV_ALREADY_CLAIMED
        elif s.interactions[a] < ad.min_interactions:
            reason = RV_NOT_ELIGIBLE
        elif s.token_balance[s.contract_account(tx.contract), c.token_slot[tx.contract]] < \
                _allocation(ad, s.interactions[a]):
            reason = RV_POOL_EXHAUSTED
    if reason < 0 and tx.kind != K_NATIVE and ctx.rng.bernoulli(site=11, p=c.revert_p[tx.contract]):
        reason = RV_LOGIC
    if need > tx.gas_limit:
        return RV_OUT_OF_GAS, tx.gas_limit, 0                      # all gas consumed
    if reason >= 0:
        frac = ctx.rng.uniform(site=12, lo=0.2, hi=0.9)            # reverted part-way through
        return reason, max(INTRINSIC_GAS, int(need * frac)), 0
    return -1, need, amt_out


def _effects(ctx, s, tx, a, amt_out, out):
    """Value movements and logs of a successful tx. Returns (token slot, token balance after)
    for the receipt, or (-1, 0)."""
    c = ctx.reads.contract
    k = tx.kind
    if k == K_NATIVE:
        to = s.account(tx.to_wallet)
        _move(s, a, to, tx.value)
        _log_transfer(ctx, s, tx, a, to, tx.value, False, out)
        return -1, 0
    ca = s.contract_account(tx.contract)
    if k == K_TOKEN:
        t = c.slot[tx.contract]
        to = s.account(tx.to_wallet)
        _move_tok(s, a, to, t, tx.token_amount)
        _log_token(ctx, s, tx, tx.contract, a, to, tx.token_amount, out)
        return t, s.token_balance[a, t]
    if k == K_SWAP:
        t = c.token_slot[tx.contract]                              # the pool account is the pool
        if tx.value > 0:
            _move(s, a, ca, tx.value)
            _move_tok(s, ca, a, t, amt_out)
            _log_transfer(ctx, s, tx, a, ca, tx.value, False, out)
            _log_token(ctx, s, tx, c.token[tx.contract], ca, a, amt_out, out)
            eth_amt, tok_amt, direction = tx.value, amt_out, 0
        else:
            _move_tok(s, a, ca, t, tx.token_amount)
            _move(s, ca, a, amt_out)
            _log_token(ctx, s, tx, c.token[tx.contract], a, ca, tx.token_amount, out)
            _log_transfer(ctx, s, tx, ca, a, amt_out, True, out)
            eth_amt, tok_amt, direction = amt_out, tx.token_amount, 1
        out.emit_swap(ctx.t, tx_id=tx.tx_id, sender=tx.sender, block_number=s.block_number,
                      log_index=_next_log(s), pool=tx.contract, direction=direction,
                      eth_amount=eth_amt, token_amount=tok_amt)
        return t, s.token_balance[a, t]
    if k == K_MINT:
        col = c.slot[tx.contract]
        _move(s, a, ca, tx.value)
        _log_transfer(ctx, s, tx, a, ca, tx.value, False, out)
        out.emit_nft_minted(ctx.t, tx_id=tx.tx_id, sender=tx.sender, block_number=s.block_number,
                            log_index=_next_log(s), collection=tx.contract,
                            token_index=s.minted[col], price=tx.value)
        s.minted[col] += 1
        return -1, 0
    if k == K_BRIDGE:
        _move(s, a, ca, tx.value)                                  # locked in the bridge
        _log_transfer(ctx, s, tx, a, ca, tx.value, False, out)
        out.emit_bridge_deposit(ctx.t, tx_id=tx.tx_id, sender=tx.sender,
                                block_number=s.block_number, log_index=_next_log(s),
                                bridge=tx.contract, destination=c.destination[tx.contract],
                                amount=tx.value)
        return -1, 0
    # K_CLAIM
    ad = ctx.cfg.airdrop
    t = c.token_slot[tx.contract]
    alloc = _allocation(ad, s.interactions[a])
    _move_tok(s, ca, a, t, alloc)
    s.claimed[a] = 1
    _log_token(ctx, s, tx, c.token[tx.contract], ca, a, alloc, out)
    out.emit_airdrop_claimed(ctx.t, tx_id=tx.tx_id, sender=tx.sender, block_number=s.block_number,
                             log_index=_next_log(s), airdrop=tx.contract, amount=alloc,
                             tier=_tier(ad, s.interactions[a]))
    return t, s.token_balance[a, t]


def _seal_block(ctx, s, out):
    """Issuance, the block record, and the EIP-1559 base fee for the next block."""
    cfg = ctx.cfg
    w = ctx.rng.dist(site=20, d=cfg.issuance_per_block)            # consensus-layer withdrawals
    v = s.system_account("validator", ctx.rng.uniform(site=21))
    s.balance[v] = std.checked_add(s.balance[v], w)
    s.issued = std.checked_add(s.issued, w)
    out.emit_block_produced(ctx.t, block_number=s.block_number, slot=ctx.slot_index(ctx.t),
                            base_fee_per_gas=s.base_fee, gas_used=s.blk_gas,
                            gas_limit=cfg.gas_limit, tx_count=s.blk_txs, burned=s.blk_burned,
                            priority_fees=s.blk_tips, withdrawals=w,
                            fee_recipient=s.blk_recipient)
    s.base_fee = next_base_fee(s.base_fee, s.blk_gas, cfg.gas_limit, cfg.min_base_fee)


# ================================================================== chain: expiry
@kernel(state="chain", substep=SUB, max=Res(records={"tx_dropped": SUB}, responses=SUB))
def expire_pending(ctx, s, cmd, out):
    """Drops pending txs older than pool_ttl, oldest first, 64 per sub-step."""
    if not out.reserve(records={"tx_dropped": SUB}, responses=SUB):
        return RETRY
    cutoff = ctx.t - ctx.cfg.pool_ttl
    n = 0
    while n < SUB:
        h = s.txpool.pop_oldest(before=cutoff)
        if h < 0:
            break
        tx = s.txpool.view(h)
        a = s.account(tx.sender)
        if tx.nonce < s.nonce[a]:
            reason = D_NONCE_TOO_LOW
        elif tx.nonce > s.nonce[a]:
            reason = D_EXPIRED_GAP
        elif tx.max_fee_per_gas < s.base_fee:
            reason = D_EXPIRED_UNDERPRICED
        else:
            reason = D_EXPIRED
        _drop(ctx, s, tx, a, reason, out)
        s.txpool.free(h)
        n += 1
    if n == SUB:
        out.continue_at(ctx.t, cursor=cmd.cursor + n)              # same time, top priority
    return COMMIT


# ================================================================== chain: helpers
def _drop(ctx, s, tx, a, reason, out):
    """tx_dropped record plus the dropped receipt. Called only after reserve succeeded."""
    out.emit_tx_dropped(ctx.t, tx_id=tx.tx_id, sender=tx.sender, nonce=tx.nonce, reason=reason,
                        account_nonce=s.nonce[a])
    out.respond(tx, "dropped", block_number=0, status=0,
                          gas_used=0, effective_gas_price=0, balance_after=s.balance[a],
                          account_nonce=s.nonce[a], token_slot=-1, token_balance_after=0,
                          base_fee=s.base_fee, counted=0)


def _move(s, frm, to, amt):
    s.balance[frm] = std.checked_sub(s.balance[frm], amt)
    s.balance[to] = std.checked_add(s.balance[to], amt)


def _move_tok(s, frm, to, t, amt):
    s.token_balance[frm, t] = std.checked_sub(s.token_balance[frm, t], amt)
    s.token_balance[to, t] = std.checked_add(s.token_balance[to, t], amt)


def _next_log(s):
    i = s.blk_logs
    s.blk_logs += 1
    return i


def _log_transfer(ctx, s, tx, frm, to, value, internal, out):
    out.emit_transfer(ctx.t, tx_id=tx.tx_id, sender=tx.sender, block_number=s.block_number,
                      log_index=_next_log(s), from_account=frm, to_account=to, value=value,
                      internal=internal)


def _log_token(ctx, s, tx, token, frm, to, amt, out):
    out.emit_token_transfer(ctx.t, tx_id=tx.tx_id, sender=tx.sender, block_number=s.block_number,
                            log_index=_next_log(s), token=token, from_account=frm,
                            to_account=to, amount=amt)


def _cp_out(ctx, s, pool, eth_in, amount_in):
    """Constant-product output with a 0.3% fee; 128-bit intermediate, checked result."""
    ca = s.contract_account(pool)
    t = ctx.reads.contract.token_slot[pool]
    r_eth, r_tok = s.balance[ca], s.token_balance[ca, t]
    r_in, r_out = (r_eth, r_tok) if eth_in else (r_tok, r_eth)
    if amount_in <= 0 or r_in <= 0 or r_out <= 0:
        return 0
    in_fee = std.checked_mul(amount_in, 997)
    return std.checked_muldiv(in_fee, r_out, std.checked_add(std.checked_mul(r_in, 1_000), in_fee))


def _tier(ad, interactions):
    tier = 0
    for i in range(len(ad.tiers)):
        if interactions >= ad.tiers[i][0]:
            tier = i + 1
    return tier


def _allocation(ad, interactions):
    tier = _tier(ad, interactions)
    return ad.tiers[tier - 1][1] if tier > 0 else 0


def next_base_fee(base, used, limit, floor):
    """EIP-1559, Specification: elasticity multiplier 2, max change denominator 8, evaluated
    in quanta. Pure; compiled into build_block and mirrored by law.domains.eip1559_base_fee."""
    target = limit // 2
    if used == target:
        nxt = base
    elif used > target:
        delta = std.checked_muldiv(base, used - target, target) // 8
        nxt = std.checked_add(base, max(delta, 1))
    else:
        delta = std.checked_muldiv(base, target - used, target) // 8
        nxt = base - delta
    return max(nxt, floor)


# Thin actions exposed to overlays: send_tx bound to one tx kind, plus a process starter.
send_native = send_tx.with_params(tx_kind=K_NATIVE)
send_token = send_tx.with_params(tx_kind=K_TOKEN)
swap = send_tx.with_params(tx_kind=K_SWAP)                         # min_out=0 unless given
mint_nft = send_tx.with_params(tx_kind=K_MINT)
bridge_deposit = send_tx.with_params(tx_kind=K_BRIDGE)
claim_airdrop = send_tx.with_params(tx_kind=K_CLAIM)
start_activity = std.action.start("wallet_activity", command=C_SESSION)
