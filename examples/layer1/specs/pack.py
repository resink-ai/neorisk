"""Account-based layer-1 chain pack.

Partitions
    owner  wallet   one externally owned account: its beliefs (nonce, balance, base fee),
                    in-flight transactions and processes; never the chain's account state
    shard  chain    the one canonical chain: account state, contract state, the pending pool,
                    block building (a hot shard by nature; see README)

Boundaries (immutable request/response, latency >= delta)
    wallet -> chain   submit_tx       a signed transaction; propagation delta 200 ms; the
                                      receipt is answered when a block includes or drops it,
                                      plus reply delta 100 ms
    wallet -> chain   query_account   eth_getBalance / getTransactionCount   delta 80 ms
    wallet -> chain   query_quote     router quote for a swap               delta 80 ms
    wallet -> wallet  cex_withdrawal  user asks an exchange for a payout, next step or later

Amounts
    Native amounts and gas prices are int64 multiples of one declared quantum, 10^6 wei
    (0.001 gwei), with checked arithmetic. One ETH is 10^12 quanta; an int64 holds 9.2M ETH
    per account, which validate enforces at genesis. Supply-wide sums (conservation) are
    accumulated by the checker in 128 bits. Token amounts use a quantum of 10^-6 token.
    The EIP-1559 update is evaluated in quanta, so it differs from mainnet wei arithmetic by
    less than one quantum per block; the base fee has a floor of one quantum.
"""

from dataclasses import dataclass, field

from neorisk_simkit.spec import Pack, dist, law, std
from neorisk_simkit.spec.types import amount, boolean, cat, f64, i16, i32, i64, opt, ref, text, ts

from . import kernels as k

PACK = "layer1"
SCHEMA_VERSION = 1

QUANTUM = "1e6 wei"                         # one native amount unit
GWEI = 1_000                                # quanta
ETH = 1_000_000_000_000                     # quanta
TOKEN = 1_000_000                           # token quanta per whole token

WALLET_KINDS = ("retail", "trader", "bot", "exchange")
ACTIVITY = ("casual", "regular", "heavy")
TX_KINDS = ("native_transfer", "token_transfer", "swap", "nft_mint", "bridge_deposit",
            "airdrop_claim")
CONTRACT_KINDS = ("token", "pool", "nft_collection", "bridge", "airdrop")
SYSTEM_ACCOUNTS = ("fee_recipient", "validator")
DROP_REASONS = ("nonce_too_low", "insufficient_funds", "gas_limit_invalid", "sender_slots_full",
                "pool_full", "expired_underpriced", "expired_nonce_gap", "expired")
REVERT_REASONS = ("slippage", "sold_out", "not_open", "insufficient_token_balance",
                  "out_of_gas", "not_eligible", "already_claimed", "claim_closed",
                  "pool_exhausted", "contract_logic")
DESTINATIONS = ("rollup_a", "rollup_b", "rollup_c", "rollup_d")

# Gas per successful call (mean, coefficient of variation) and residual revert probability
# for "other contract logic"; state-driven reverts (slippage, sold out, ...) come on top.
GAS_PROFILES = {
    "native_transfer": (21_000, 0.0, 0.0),
    "token_transfer":  (52_000, 0.15, 0.002),
    "swap":            (145_000, 0.25, 0.006),
    "nft_mint":        (95_000, 0.30, 0.004),
    "bridge_deposit":  (75_000, 0.10, 0.003),
    "airdrop_claim":   (85_000, 0.10, 0.0),
}


def native():
    return amount(asset="ETH", quantum=QUANTUM)


def token_amount():
    return amount(asset="token", quantum="1e-6 token")


# --------------------------------------------------------------------------- config
@dataclass(frozen=True)
class Activity:
    """Wallet behavior per kind; tuples are indexed by WALLET_KINDS. Consumed by
    kernels.wallet_activity and kernels.send_tx."""
    session_gap_alpha: tuple = (1.15, 1.3, 2.5, 0.0)      # Pareto tail of gaps between sessions
    session_gap_min_h: tuple = (20.0, 4.0, 0.02, 0.0)
    activity_gap_scale: tuple = (3.0, 1.0, 0.3)            # by ACTIVITY: casual waits longer
    burst_mean: tuple = (1.6, 3.0, 40.0, 0.0)              # geometric txs per session
    intra_burst_s: tuple = (90.0, 45.0, 6.0, 0.0)          # think time between txs
    wait_for_receipt: tuple = (True, False, False, False)  # retail confirms before the next tx
    max_in_flight: tuple = (2, 4, 16, 64)                  # wallet-side pending limit
    kind_mix: tuple = (                                    # native, token, swap, mint, bridge
        (0.48, 0.30, 0.12, 0.06, 0.04),
        (0.22, 0.30, 0.38, 0.05, 0.05),
        (0.02, 0.10, 0.88, 0.00, 0.00),
        (1.00, 0.00, 0.00, 0.00, 0.00),
    )
    tip_median: tuple = (80, 400, 3_000, 1_000)            # quanta per gas (0.08 gwei, ...)
    tip_sigma: tuple = (0.9, 0.9, 1.1, 0.4)
    slippage_bps: tuple = (100, 50, 15, 0)
    base_fee_headroom: int = 2                             # max_fee = 2 x base fee + tip
    gas_buffer: dist.Dist = dist.uniform(1.15, 1.6)        # gas_limit = estimate x buffer
    gas_estimate_cv: float = 0.08                          # estimate error -> rare out-of-gas
    defer_when_fee_high: dist.Dist = dist.exp(mean_min=20)
    sync_every: str = "1d"                                 # RPC balance refresh when older
    transfer_share: dist.Dist = dist.beta(a=1.2, b=6.0)    # share of believed balance sent
    swap_share: dist.Dist = dist.beta(a=1.5, b=8.0)
    exchange_deposit_p: float = 0.25                       # native transfer goes to an exchange
    claim_p: float = 0.3                                   # per tx, while qualified and open
    payout_delay: dist.Dist = dist.lognormal(median_min=8, sigma=1.0)   # exchange batching


@dataclass(frozen=True)
class Airdrop:
    """One airdrop program on the router's pools. Exposed as params for overlays."""
    target: str = "pool"                                   # contract kind whose calls count
    snapshot_at: str = "day 18"
    claim_opens: str = "day 21"
    claim_window: str = "30d"
    min_interactions: int = 3
    tiers: tuple = ((3, 400 * TOKEN), (10, 1_200 * TOKEN), (25, 3_000 * TOKEN))
    pool_tokens: int = 90_000_000 * TOKEN                  # held by the distributor; when it
                                                           # can't cover a claim -> revert


@dataclass(frozen=True)
class Config:
    wallets: int = 4_000_000                # non-exchange wallets at the end of the span
    initial_share: float = 0.6              # share that exists at genesis
    exchanges: int = 12
    tokens: int = 8                         # one ETH/token pool each
    collections: int = 40
    bridges: int = 4
    slot: str = "12s"
    missed_slot_p: float = 0.008
    gas_limit: int = 30_000_000             # scaled down with the population in sample runs
    base_fee_init: int = 3 * GWEI
    min_base_fee: int = 1                   # one quantum
    issuance_per_block: dist.Dist = dist.normal_minor(mean=375 * ETH // 1_000,
                                                      sd=40 * ETH // 1_000, min=0)
    pool_ttl: str = "3h"                    # pending txs older than this are dropped
    sender_slots: int = 64                  # chain-side pending txs per sender
    pool_capacity: int = 400_000
    onramp_p: float = 0.7
    onramp_amount: dist.Dist = dist.lognormal_minor(median=300 * ETH // 1_000, sigma=1.1,
                                                    min=ETH // 1_000, max=50 * ETH)
    activity: Activity = field(default_factory=Activity)
    airdrop: Airdrop = field(default_factory=Airdrop)
    execution_owner: str = "wallet_id"      # overlays may group cohort members under another owner


# --------------------------------------------------------------------------- pack
def define(p: Pack, cfg: Config) -> None:
    ad = cfg.airdrop

    # ---------------------------------------------------------------- read inputs
    contract = p.table("contract", key="contract_id", mutable=False,
                       doc="Deployed contracts, fixed for the run", cols={
        "address": text(),
        "kind": cat(*CONTRACT_KINDS),
        "slot": i16(),                       # index within its kind (token i, pool i, ...)
        "token": opt(ref("contract")),       # pool: its token; airdrop: the token it pays
        "token_slot": opt(i16()),            # slot of that token (a token: its own slot)
        "gas_mean": i32(), "gas_cv": f64(), "revert_p": f64(),
        "supply": opt(i32()),                # nft_collection: fixed supply
        "price": opt(native()),              # nft_collection: mint price
        "opens_at": opt(ts()),               # nft_collection: mint opening
        "destination": opt(cat(*DESTINATIONS)),
        "popularity": f64(),                 # choice weight within its kind
        "airdrop_target": boolean(),         # calls count toward the airdrop
    }, source=std.contracts(
        counts={"token": cfg.tokens, "pool": cfg.tokens, "nft_collection": cfg.collections,
                "bridge": cfg.bridges, "airdrop": 1},
        gas={"token": GAS_PROFILES["token_transfer"], "pool": GAS_PROFILES["swap"],
             "nft_collection": GAS_PROFILES["nft_mint"], "bridge": GAS_PROFILES["bridge_deposit"],
             "airdrop": GAS_PROFILES["airdrop_claim"]},
        popularity=dist.zipf(s=1.1),
        nft_supply=dist.lognormal_int(median=3_000, sigma=0.8, min=100, max=20_000),
        nft_price=dist.lognormal_minor(median=20 * ETH // 1_000, sigma=1.0, min=0),
        nft_opens=dist.uniform_time("day 0", "day 30"),
        destinations=DESTINATIONS,
        airdrop_target=ad.target,            # every pool's calls count toward the airdrop
        airdrop_token=dist.uniform_int(0, cfg.tokens - 1),
    ))

    account = p.table("account", key="account_id", mutable=False,
                      doc="Address book: every wallet, contract and system account", cols={
        "address": text(),
        "kind": cat("wallet", "contract", *SYSTEM_ACCOUNTS),
        "wallet_id": opt(ref("wallet")),
        "contract_id": opt(ref("contract")),
    }, source=std.account_book(owners="wallet", contracts=contract,
                               system={"fee_recipient": 24, "validator": 64}))

    # ---------------------------------------------------------------- owner state
    wallet = p.table("wallet", key="wallet_id", mutable=True, doc="An externally owned account",
                     cols={
        "address": text(),
        "kind": cat(*WALLET_KINDS),
        "activity": cat(*ACTIVITY),
        "origin": cat("genesis", "new"),
        "created_at": ts(),
        "fee_ceiling": native(),             # waits while the believed base fee is above this
        "status": cat("active", "dormant"),
    })

    p.owner("wallet", table="wallet", execution_owner=cfg.execution_owner,
            max_live=cfg.wallets + cfg.exchanges)

    p.population(
        wallet, n=cfg.wallets,
        initial=cfg.initial_share,
        arrivals=dist.poisson_daily(weekly=(1.05, 1.0, 1.0, 1.0, 1.05, 0.95, 0.9), trend=0.001),
        attrs={
            "kind": dist.categorical({"retail": .88, "trader": .115, "bot": .005}),
            "activity": dist.categorical({"casual": .7, "regular": .25, "heavy": .05}),
            "fee_ceiling": dist.lognormal_minor(median=25 * GWEI, sigma=0.9, min=2 * GWEI),
            "address": std.address(),
            "origin": std.origin(),          # "genesis" for the initial share, else "new"
        },
        refs={"contacts": std.contacts(per_wallet=dist.negbinom(mean=6, disp=0.6, max=200),
                                       attach="preferential", reciprocity=0.35),
              "exchange": std.pick_ref("wallet", where="kind == 'exchange'", sticky=True)},
    )
    p.population(wallet, n=cfg.exchanges, initial=1.0, arrivals=None, name="exchanges",
                 attrs={"kind": "exchange", "activity": "heavy", "fee_ceiling": 500 * GWEI,
                        "address": std.address(), "origin": "genesis"})

    # ---------------------------------------------------------------- shard
    # Pool reserves are the pool contract's own balances, and the airdrop pool is the
    # distributor's token balance, so conservation covers them with no extra terms.
    chain = p.shard("chain", key="chain_id", n=1, doc="The canonical chain and its state",
                    config=cfg, state={
        "balance": "i64[account]",           # native, quanta
        "nonce": "i64[account]",
        "token_balance": "i64[account, token]",
        "interactions": "i16[account]",      # successful airdrop-target calls before snapshot
        "claimed": "bit[account]",
        "minted": "i32[collection]",
        "base_fee": "i64",                   # base fee of the block being built
        "block_number": "i64",
        "burned": "i64", "issued": "i64",    # cumulative; checked against conservation
        # block in progress (sub-steps of build_block)
        "blk_gas": "i64", "blk_txs": "i16", "blk_logs": "i32", "blk_tips": "i64",
        "blk_burned": "i64", "blk_recipient": "ref",
        # pending txs: per-sender nonce queues, sender heads indexed by effective tip at the
        # current base fee; park() hides an entry until the block number advances
        "txpool": std.tx_pool(capacity=cfg.pool_capacity, per_sender=cfg.sender_slots,
                              order="effective_tip", ties="arrival"),
    }, accounts=account,
       init=std.genesis(
        balance={"retail": dist.lognormal_minor(median=50 * ETH // 1_000, sigma=2.2, max=200 * ETH),
                 "trader": dist.lognormal_minor(median=2 * ETH, sigma=1.8, max=50_000 * ETH),
                 "bot": dist.lognormal_minor(median=20 * ETH, sigma=1.0, max=2_000 * ETH),
                 "exchange": dist.lognormal_minor(median=150_000 * ETH, sigma=0.6,
                                                  max=1_500_000 * ETH)},
        funded_share={"retail": 0.8, "trader": 0.97, "bot": 1.0, "exchange": 1.0},
        tokens=std.token_holdings(holders_share=0.35, by_popularity=True,
                                  amount=dist.pareto_minor(alpha=1.1, min=10 * TOKEN)),
        pools=std.cp_pools(eth=dist.lognormal_minor(median=20_000 * ETH, sigma=0.8),
                           price=dist.lognormal(median=0.0004, sigma=1.5)),   # ETH per token
        airdrop=std.fund_contract("airdrop", amount=ad.pool_tokens),   # in contract.token
        base_fee=cfg.base_fee_init,
        max_account=2**62,                   # validate refuses a genesis above this
    ))

    # ---------------------------------------------------------------- boundaries
    # submit_tx is deferred: the chain answers when a block includes the tx, or when it is
    # dropped (at admission, at inclusion, or on expiry). A wallet with txs in flight runs
    # ahead only to the earliest time a receipt could reach it (the next slot plus the reply
    # minimum), which the chain publishes after admitting the tx; the safe-horizon argument
    # is unchanged because every hop still takes at least its declared minimum.
    submit = p.request(
        "submit_tx", frm="wallet", to="chain", handler=k.admit_tx,
        payload={"tx_id": ref("tx"), "sender": ref("wallet"), "nonce": i64(),
                 "kind": cat(*TX_KINDS), "to_wallet": opt(ref("wallet")),
                 "contract": opt(ref("contract")), "value": native(),
                 "token_amount": token_amount(), "min_out": i64(), "gas_limit": i32(),
                 "max_fee_per_gas": native(), "max_priority_fee_per_gas": native(),
                 "cost": native(), "submitted_at": ts()},
        responses={"included": k.R_INCLUDED, "dropped": k.R_DROPPED},
        response={"block_number": i64(), "status": cat("success", "reverted"),
                  "gas_used": i32(), "effective_gas_price": native(),
                  "balance_after": native(), "account_nonce": i64(), "token_slot": i16(),
                  "token_balance_after": token_amount(), "base_fee": native(),
                  "counted": boolean()},     # tx_id, cost, submitted_at are echoed
        latency=dist.shifted_lognormal(min_ms=200, median_ms=450),        # propagation
        deferred=True, decided_by=("admit_tx", "build_block", "expire_pending"),
        reply_latency=dist.shifted_lognormal(min_ms=100, median_ms=900),  # receipt polling
        owner_hook=k.apply_receipt,          # belief update in the sender, before any process
    )
    # Owner-to-owner: a user asks an exchange hot wallet for a payout (next step or later)
    p.message("cex_withdrawal", frm="wallet", to="wallet", delivery="next_step",
              payload={"wallet_id": ref("wallet"), "amount": native()})
    account_q = p.request(
        "query_account", frm="wallet", to="chain", handler=k.query_account,
        payload={"wallet_id": ref("wallet")},
        responses={"ok": k.R_ACCOUNT},
        response={"balance": native(), "nonce": i64(), "token_balances": "i64[8]",
                  "base_fee": native()},
        latency=dist.shifted_lognormal(min_ms=80, median_ms=150),
        owner_hook=k.apply_account)
    quote_q = p.request(
        "query_quote", frm="wallet", to="chain", handler=k.query_quote,
        payload={"pool": ref("contract"), "eth_in": boolean(), "amount_in": i64(),
                 "tag": ref("quote")},
        responses={"ok": k.R_QUOTE},
        response={"amount_out": i64(), "tag": ref("quote")},
        latency=dist.shifted_lognormal(min_ms=80, median_ms=150))

    # ---------------------------------------------------------------- shard processes
    # Requests enter the chain's heap as commands (handler kernels above). Block building and
    # expiry are the chain's own timers; both fan out in fixed 64-tx sub-steps.
    p.process("build_block", shard=chain, kernel=k.build_block, every=cfg.slot,
              commands=(k.C_BUILD,))
    p.process("expire_pending", shard=chain, kernel=k.expire_pending, every="5m",
              commands=(k.C_EXPIRE,))

    # ---------------------------------------------------------------- events
    tx_cols = {"tx_id": ref("tx"), "sender": ref("wallet")}
    log_cols = {**tx_cols, "block_number": i64(), "log_index": i16()}

    p.event("wallet_created", owner="wallet", doc="A new wallet appears (genesis wallets are in "
            "entities/ and the opening snapshot)", cols={
        "wallet_id": ref("wallet"), "address": text(), "kind": cat(*WALLET_KINDS),
    })
    p.event("cex_withdrawal_requested", owner="wallet", doc="Off-chain: a user asks an "
            "exchange to pay out to this wallet", cols={
        "wallet_id": ref("wallet"), "exchange_id": ref("wallet"), "amount": native(),
    })
    p.event("tx_submitted", owner="wallet", doc="A signed transaction leaves the wallet", cols={
        **tx_cols, "nonce": i64(), "tx_kind": cat(*TX_KINDS),
        "to_wallet": opt(ref("wallet")), "contract_id": opt(ref("contract")),
        "value": native(), "gas_limit": i32(min=21_000),
        "max_fee_per_gas": native(), "max_priority_fee_per_gas": native(),
    })
    p.event("tx_included", shard="chain", doc="A transaction in a block; success or reverted",
            cols={
        **tx_cols, "nonce": i64(), "block_number": i64(), "tx_index": i16(),
        "tx_kind": cat(*TX_KINDS), "status": cat("success", "reverted"),
        "revert_reason": opt(cat(*REVERT_REASONS)), "gas_used": i32(min=21_000),
        "effective_gas_price": native(), "priority_fee_per_gas": native(),
        "fee_burned": native(), "priority_fee": native(),     # totals: gas_used x price parts
    })
    p.event("tx_dropped", shard="chain", doc="Never included: invalid, rejected at admission, or "
            "expired from the pending pool", cols={
        **tx_cols, "nonce": i64(), "reason": cat(*DROP_REASONS), "account_nonce": i64(),
    })
    p.event("transfer", shard="chain", doc="Native value movement of a successful tx (top-level "
            "or internal, e.g. a pool paying out ETH)", cols={
        **log_cols, "from_account": ref("account"), "to_account": ref("account"),
        "value": native(), "internal": boolean(),
    })
    p.event("token_transfer", shard="chain", doc="ERC-20 Transfer log", cols={
        **log_cols, "token": ref("contract"), "from_account": ref("account"),
        "to_account": ref("account"), "amount": token_amount(),
    })
    p.event("swap", shard="chain", doc="Pool Swap log", cols={
        **log_cols, "pool": ref("contract"), "direction": cat("eth_to_token", "token_to_eth"),
        "eth_amount": native(), "token_amount": token_amount(),
    })
    p.event("nft_minted", shard="chain", doc="NFT Transfer-from-zero log", cols={
        **log_cols, "collection": ref("contract"), "token_index": i32(min=0), "price": native(),
    })
    p.event("bridge_deposit", shard="chain", doc="Bridge DepositInitiated log", cols={
        **log_cols, "bridge": ref("contract"), "destination": cat(*DESTINATIONS),
        "amount": native(),
    })
    p.event("airdrop_claimed", shard="chain", doc="Distributor Claimed log", cols={
        **log_cols, "airdrop": ref("contract"), "amount": token_amount(), "tier": i16(min=1),
    })
    p.event("block_produced", shard="chain", doc="A sealed block (missed slots produce none)",
            cols={
        "block_number": i64(), "slot": i64(), "base_fee_per_gas": native(),
        "gas_used": i32(min=0), "gas_limit": i32(), "tx_count": i16(min=0),
        "burned": native(), "priority_fees": native(), "withdrawals": native(),
        "fee_recipient": ref("account"),
    })
    p.event("receipt_received", owner="wallet", doc="The wallet learns a tx's outcome", cols={
        **tx_cols, "outcome": cat("success", "reverted", "dropped"),
        "block_number": opt(i64()), "latency_ms": i32(min=0),
    })

    # ---------------------------------------------------------------- wallet processes
    # Wallet kernels read cfg.activity and cfg.airdrop, so they get the whole config
    p.process("wallet_activity", owner="wallet", kernel=k.wallet_activity, config=cfg,
              start=p.on_created("wallet", where="origin == 'genesis' and kind != 'exchange'"),
              requests={"submit_tx": submit, "query_account": account_q, "query_quote": quote_q},
              reads={"contract": contract},
              commands=k.WALLET_COMMANDS)

    p.process("cex_hot_wallet", owner="wallet", kernel=k.cex_hot_wallet, config=cfg,
              start=p.on_created("wallet", where="kind == 'exchange'"),
              requests={"submit_tx": submit, "query_account": account_q},
              messages={"cex_withdrawal": k.M_WITHDRAWAL},
              commands=k.EXCHANGE_COMMANDS)

    # Onboarding of wallets created during the run: common behavior, so a state machine
    ob = p.machine("onboarding", owner="wallet",
                   start=p.on_created("wallet", where="origin == 'new' and kind != 'exchange'"),
                   initial="new")
    ob.state("new", branch={
        "funding": (cfg.onramp_p, dist.lognormal(median_s=1_200),
                    std.emit("wallet_created").then(k.cex_withdraw.with_params(
                        amount=cfg.onramp_amount))),
        "otherwise": (1 - cfg.onramp_p, dist.lognormal(median_s=600), std.emit("wallet_created")),
    })
    ob.state("funding", branch={"active": (1.0, dist.exp(mean_min=30), k.start_activity)})
    ob.state("otherwise", branch={"active": (1.0, dist.exp(mean_days=3), k.start_activity)})
    ob.final("active")

    # ---------------------------------------------------------------- enrichment
    # Cross-owner features, computed after each step seals on canonical order; go to golden/
    p.feature("sender_distinct_recipients_24h",
              std.rolling_distinct("to_account", by="from_account", window="24h"),
              on=["transfer"], into="golden")
    p.feature("account_first_funder", std.first_value("from_account", by="to_account"),
              on=["transfer"], into="golden")
    p.feature("sender_txs_1h", std.rolling_count("tx_submitted", by="sender", window="1h"),
              on=["tx_submitted"], into="golden")

    # ---------------------------------------------------------------- laws
    p.check("chk.nonce_sequence",
            law.sequence("tx_included.nonce", by="sender", step=1,
                         start="snapshot:chain.nonce"), required=True)
    p.check("chk.balance_never_negative", law.never_negative("chain.balance"), required=True)
    p.check("chk.token_never_negative", law.never_negative("chain.token_balance"), required=True)
    p.check("chk.value_conservation",
            law.conserved("chain.balance", initial="snapshot",
                          inflow="block_produced.withdrawals", outflow="block_produced.burned",
                          at="block_produced"), required=True)
    p.check("chk.token_conservation",
            law.conserved("chain.token_balance", by="token", initial="snapshot",
                          at="block_produced"), required=True)
    p.check("chk.gas_within_limit",
            law.sum_le("tx_included.gas_used", "block_produced.gas_limit", by="block_number"),
            required=True)
    p.check("chk.block_gas_consistent",
            law.sum_eq("tx_included.gas_used", "block_produced.gas_used", by="block_number"),
            required=True)
    p.check("chk.base_fee_eip1559",                  # EIP-1559, "Specification" section
            law.recurrence("block_produced.base_fee_per_gas", order="block_number",
                           next=law.domains.eip1559_base_fee(elasticity=2, denominator=8,
                                                              floor=cfg.min_base_fee),
                           inputs=("gas_used", "gas_limit")), required=True)
    p.check("chk.fee_bounds",                        # base fee <= effective price <= max fee
            law.bounded("tx_included.effective_gas_price",
                        lo="block_produced.base_fee_per_gas", lo_by="block_number",
                        hi="tx_submitted.max_fee_per_gas", hi_by="tx_id"), required=True)
    p.check("chk.reverted_no_effects",
            law.no_children("tx_included", where="status == 'reverted'", key="tx_id",
                            children=("transfer", "token_transfer", "swap", "nft_minted",
                                      "bridge_deposit", "airdrop_claimed")), required=True)
    p.check("chk.tx_resolved",
            law.resolved("tx_submitted", by=("tx_included", "tx_dropped"), key="tx_id",
                         within="horizon", censored="pending"), required=True)
    p.check("chk.tx_once",
            law.at_most_once(("tx_included", "tx_dropped"), key="tx_id"), required=True)
    p.check("chk.tx_lifecycle", law.lifecycle("tx_id", edges={
        "tx_submitted": ("tx_included", "tx_dropped"),
        "tx_included": ("receipt_received",),
        "tx_dropped": ("receipt_received",),
    }), required=True)
    p.check("chk.nft_supply",
            law.count_le("nft_minted", cap="contract.supply", by="collection"), required=True)
    p.check("chk.airdrop_once",
            law.at_most_once("airdrop_claimed", key="sender"), required=True)

    # ---------------------------------------------------------------- extension points
    # Named actions overlays may call (validate checks them against the resolved plan)
    p.expose(
        send_native=k.send_native, send_token=k.send_token, swap=k.swap, mint_nft=k.mint_nft,
        bridge_deposit=k.bridge_deposit, claim_airdrop=k.claim_airdrop,
        sync_account=k.sync_account, cex_withdraw=k.cex_withdraw,
        start_activity=k.start_activity,
    )
    p.expose_param("airdrop.snapshot_at", ad.snapshot_at)
    p.expose_param("airdrop.claim_opens", ad.claim_opens)
    p.expose_param("airdrop.min_interactions", ad.min_interactions)
    p.expose_param("airdrop.target", ad.target)
