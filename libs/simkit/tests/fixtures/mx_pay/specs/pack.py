"""Request with timeout and rejection branch (D67, D83); a dispute as a spawned child process
the payment joins on (D51); create_owner from a machine (D72)."""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, dist, std
from neorisk_simkit.spec.types import boolean, i64, ref

from . import kernels as k

PACK = "mx_pay"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Config:
    payments: int = 6
    limit: int = 500
    latency_ms: int = 200
    timeout: str = "1s"
    dispute_p: float = 1.0
    dispute_after_s: int = 600
    dispute_len_s: int = 1800


def define(p: Pack, cfg: Config) -> None:
    pay = p.table("payment", key="payment_id", mutable=True, cols={"amount": i64()})
    receipt = p.table("receipt", key="receipt_id", mutable=True,
                      cols={"payment_id": ref("payment"), "amount": i64()})
    p.owner("payment", table=pay, max_live=cfg.payments)
    p.owner("receipt", table=receipt, max_live=cfg.payments)
    p.population(pay, n=cfg.payments, initial=1.0, attrs={"amount": dist.uniform_int(100, 900)})
    bank = p.shard("bank", key="bank", n=1, items=None, state={"captured": "i64"})
    p.request("capture", frm="payment", to=bank, payload={"amount": i64()},
              response_payload={"amount": i64()}, responses=("granted", "rejected"),
              latency=dist.constant(ms=cfg.latency_ms))
    p.message("void", frm="payment", to=bank, payload={"amount": i64()},
              latency=dist.constant(ms=cfg.latency_ms))
    pid = {"payment_id": ref("payment")}
    p.event("captured", owner="payment", cols={**pid, "amount": i64()})
    for name in ("declined", "timed_out", "dispute_resolved", "closed"):
        p.event(name, owner="payment", cols=pid)
    p.event("decided", shard="bank", cols={"amount": i64(), "granted": boolean()})
    p.event("voided", shard="bank", cols={"amount": i64()})
    p.event("receipt_issued", owner="receipt", cols={
        "receipt_id": ref("receipt"), "payment_id": ref("payment"), "amount": i64()})
    p.process("bank_desk", shard=bank, kernel=k.bank_desk, config=cfg,
              on_request={"capture": k.C_CAPTURE}, on_message={"void": k.C_VOID},
              commands=(k.C_CAPTURE, k.C_VOID))
    p.process("receipt_main", owner="receipt", kernel=k.receipt_main,
              start=p.on_created("receipt"))
    m = p.machine("pay", owner="payment", start=p.on_created("payment"),
                  initial="authorized", config=cfg, fields={"captured": "i64"})
    m.state("authorized", request={"capturing": std.request(
        "capture", amount=std.col("amount"), store={"amount": "captured"},
        release=std.send("void", amount=std.field("captured")))},
        on_reject="declining", timeout=cfg.timeout, on_timeout="timing_out")
    m.state("capturing", branch={"settled": (1.0, dist.constant(s=3600), std.emit(
        "captured", payment_id=std.actor(), amount=std.field("captured")).then(
        std.create_owner("receipt", payment_id=std.actor(), amount=std.field("captured"))))},
        spawn={"dispute": (cfg.dispute_p, dist.constant(s=cfg.dispute_after_s), 1)})
    m.state("settled", join={"closing": "resolved"}, timer={"closing": "1d"}, late="count")
    m.state("closing", branch={"closed": (1.0, None, std.emit("closed", payment_id=std.actor()))})
    m.state("declining", branch={"declined": (1.0, None, std.emit(
        "declined", payment_id=std.actor()))})
    m.state("timing_out", branch={"timed_out": (1.0, None, std.emit(
        "timed_out", payment_id=std.actor()))})
    m.final("closed", "declined", "timed_out")
    d = p.machine("dispute", owner="payment", initial="open", max_instances=2)
    d.state("open", branch={"done": (1.0, dist.constant(s=cfg.dispute_len_s), std.emit(
        "dispute_resolved", payment_id=std.actor()).then(std.send_parent("resolved")))})
    d.final("done")
