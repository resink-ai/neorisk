"""A layer-1 chain's transaction envelope: wallets, one chain shard, blocks every 12 s.

Wallets submit signed transactions (transfers and contract calls) to the chain by message.
The chain shard holds every account's balance and nonce; it queues what it receives and, at
each block, processes the queue in arrival order. Validity comes first: the nonce must match
and the balance must cover the maximum fee plus the value; invalid transactions are dropped.
An included transaction bumps the nonce and pays gas. A reverted call still pays gas, but its
value transfer and logs are discarded. The chain sends each wallet a receipt.

No consensus, mempool or EVM. Amounts are gwei (int64 is plenty at this scale).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import polars as pl

from neorisk_simkit.checks import laws
from neorisk_simkit.engine import DAY
from neorisk_simkit.spec import Latency, Pack, cat, i32, i64

NAME = "layer1"
BLOCK_S = 12.0


@dataclass
class Config:
    wallets: int = 300
    contracts: int = 5
    txs_per_day: float = 6.0
    call_share: float = 0.35
    revert_p: float = 0.1             # contract calls that revert
    stale_nonce_p: float = 0.02       # a wallet resends an old nonce
    gas_price: int = 20               # gwei per gas
    genesis_gwei: int = 2_000_000_000  # 2 ETH
    value_median_gwei: int = 50_000_000


@dataclass
class Wallet:
    account: int = 0
    nonce: int = 0                    # the next nonce this wallet will use


@dataclass
class Chain:
    block: int = 0
    balance: dict[int, int] = field(default_factory=dict)
    nonce: dict[int, int] = field(default_factory=dict)
    queue: list[dict] = field(default_factory=list)


def define(p: Pack) -> None:
    p.entity("accounts", key="account_id", cols={"kind": cat("wallet", "contract")})
    p.event("genesis_allocated", cols={"account_id": i64(), "amount": i64(min=1)})
    p.event("tx_received", doc="The chain queued a transaction", cols={
        "tx_id": i64(), "from_account": i64(), "to_account": i64(), "nonce": i64(min=0),
        "value": i64(min=0), "gas_limit": i64(min=21_000), "kind": cat("transfer", "call")})
    p.event("tx_included", cols={"tx_id": i64(), "block": i64(min=1), "from_account": i64(),
                                 "nonce": i64(min=0), "gas_used": i64(), "fee": i64(),
                                 "status": cat("success", "reverted")})
    p.event("tx_dropped", cols={"tx_id": i64(), "block": i64(min=1), "from_account": i64(),
                                "reason": cat("bad_nonce", "insufficient_funds")})
    p.event("transfer_log", doc="A value transfer of a successful transaction", cols={
        "tx_id": i64(), "from_account": i64(), "to_account": i64(), "value": i64(min=1)})
    p.event("block_produced", doc="A non-empty block", cols={"block": i64(min=1), "txs": i32(min=0),
                                    "gas_used": i64(min=0)})

    wallet = p.owner("wallet", state=Wallet, latency=Latency(0.05, 0.5))
    chain = p.shard("chain", state=Chain, latency=Latency(0.2, 1.5), doc="Accounts and blocks")
    life = wallet.process("sending", start="start")
    blocks = chain.process("blocks", start="genesis")

    @life.action
    def start(ctx, s, cmd):
        ctx.after(ctx.rng.exponential(DAY / ctx.cfg.txs_per_day), "send_tx")

    @life.action
    def send_tx(ctx, s, cmd):
        cfg, rng, accts = ctx.cfg, ctx.rng, ctx.shared.accounts
        call = rng.random() < cfg.call_share
        to = int(accts.contracts[rng.integers(len(accts.contracts))] if call
                 else accts.wallets[rng.integers(len(accts.wallets))])
        value = 0 if call else int(rng.lognormal(18.0, 1.0)) % (cfg.genesis_gwei // 4) + 1
        nonce = s.nonce
        if s.nonce and rng.random() < cfg.stale_nonce_p:
            nonce = s.nonce - 1                       # a resend of an old nonce
        else:
            s.nonce += 1
        gas = 21_000 if not call else int(rng.integers(40_000, 200_000))
        ctx.send(ctx.find("chain", "main"), "submit", account=s.account, to=to, nonce=nonce,
                 value=value, gas_limit=gas, call=bool(call),
                 revert=bool(call and rng.random() < cfg.revert_p))
        ctx.after(rng.exponential(DAY / cfg.txs_per_day), "send_tx")

    @life.action
    def receipt(ctx, s, cmd):
        if cmd.dropped == "bad_nonce":
            s.nonce = max(s.nonce, cmd.expected)      # resync from the chain

    @blocks.action
    def genesis(ctx, s, cmd):
        for a in sorted(s.balance):
            ctx.emit("genesis_allocated", account_id=a, amount=s.balance[a])
        ctx.after(BLOCK_S, "build_block")

    @chain.action
    def submit(ctx, s, cmd):
        tx = {"id": ctx.new_id("tx"), "from": cmd.account, "to": cmd.to, "nonce": cmd.nonce,
              "value": cmd.value, "gas": cmd.gas_limit, "call": cmd.call,
              "revert": cmd.revert, "wallet": cmd.sender}
        s.queue.append(tx)
        ctx.emit("tx_received", tx_id=tx["id"], from_account=tx["from"], to_account=tx["to"],
                 nonce=tx["nonce"], value=tx["value"], gas_limit=tx["gas"],
                 kind="call" if tx["call"] else "transfer")

    @blocks.action
    def build_block(ctx, s, cmd):
        s.block += 1
        price, gas_total = ctx.cfg.gas_price, 0
        for tx in s.queue:                            # a loop: blocks can be large
            a = tx["from"]
            nonce, bal = s.nonce.get(a, 0), s.balance.get(a, 0)
            why = ("bad_nonce" if tx["nonce"] != nonce else
                   "insufficient_funds" if bal < tx["gas"] * price + tx["value"] else None)
            if why:
                ctx.emit("tx_dropped", tx_id=tx["id"], block=s.block, from_account=a,
                         reason=why)
                ctx.send(tx["wallet"], "receipt", dropped=why, expected=nonce)
                continue
            used = tx["gas"] if not tx["call"] else tx["gas"] * 3 // 4
            fee = used * price
            s.nonce[a] = nonce + 1
            s.balance[a] = bal - fee
            ok = not tx["revert"]
            if ok and tx["value"]:
                s.balance[a] -= tx["value"]
                s.balance[tx["to"]] = s.balance.get(tx["to"], 0) + tx["value"]
            ctx.emit("tx_included", tx_id=tx["id"], block=s.block, from_account=a,
                     nonce=nonce, gas_used=used, fee=fee,
                     status="success" if ok else "reverted")
            if ok and tx["value"]:
                ctx.emit("transfer_log", tx_id=tx["id"], from_account=a, to_account=tx["to"],
                         value=tx["value"])
            ctx.send(tx["wallet"], "receipt", dropped=None, expected=nonce + 1)
            gas_total += used
        if s.queue:                                   # empty blocks leave no row
            ctx.emit("block_produced", block=s.block, txs=len(s.queue), gas_used=gas_total)
        s.queue = []
        ctx.after(BLOCK_S, "build_block")

    # --- laws ---------------------------------------------------------------------------
    p.check("nonce_sequence", laws.consecutive("tx_included", "from_account", "nonce"))
    p.check("balances_never_negative", _balances)
    p.check("reverts_have_no_logs", _reverts)
    p.check("every_tx_resolved_once", _resolved)
    p.check("blocks_increase", _blocks)

    @p.source
    def network(src):
        cfg = src.cfg
        wallets, contracts = [], []
        for _ in range(cfg.contracts):
            contracts.append(src.insert("accounts", kind="contract"))
        for _ in range(cfg.wallets):
            wallets.append(src.insert("accounts", kind="wallet"))
        src.share("accounts", wallets=np.array(wallets), contracts=np.array(contracts))
        src.create("chain", key="main", balance=dict.fromkeys(wallets, cfg.genesis_gwei))
        for a in wallets:
            src.create("wallet", at=float(src.rng.uniform(0, 3600)), account=a)


CITE = ("partition_id", "seq", "action_id")


def _balances(d):
    g = d.ev("genesis_allocated").select("seq", pl.col("account_id").alias("a"),
                                         pl.col("amount").alias("v"))
    fee = d.ev("tx_included").select("seq", pl.col("from_account").alias("a"),
                                     (-pl.col("fee")).alias("v"))
    t = d.ev("transfer_log")
    out = t.select("seq", pl.col("from_account").alias("a"), (-pl.col("value")).alias("v"))
    inn = t.select("seq", pl.col("to_account").alias("a"), pl.col("value").alias("v"))
    u = pl.concat([g, fee, out, inn]).sort("seq").with_columns(
        run=pl.col("v").cum_sum().over("a"))
    return u.height, u.filter(pl.col("run") < 0).select(
        "seq", pl.format("account {} balance {}", "a", "run").alias("detail"))


def _reverts(d):
    inc = d.ev("tx_included")
    logs = d.ev("transfer_log").join(inc.select("tx_id", "status"), on="tx_id", how="left")
    bad = logs.filter(pl.col("status") != "success")
    return logs.height, bad.select(*CITE, pl.lit("log of a reverted or unknown tx")
                                   .alias("detail"))


def _resolved(d):
    rec = d.ev("tx_received").select("tx_id", *CITE)
    done = pl.concat([d.ev("tx_included").select("tx_id"), d.ev("tx_dropped").select("tx_id")])
    n = done.group_by("tx_id").len()
    j = rec.join(n, on="tx_id", how="left")
    end_seq = d.ev("block_produced")["seq"].max() or 0
    bad = j.filter((pl.col("len") > 1) | (pl.col("len").is_null() & (pl.col("seq") < end_seq)))
    return rec.height, bad.select(*CITE, pl.lit("received tx not resolved exactly once")
                                  .alias("detail"))


def _blocks(d):
    b = d.ev("block_produced").sort("seq")
    bad = b.filter(pl.col("block") <= pl.col("block").shift(1))
    return b.height, bad.select(*CITE, pl.lit("block numbers do not increase").alias("detail"))
