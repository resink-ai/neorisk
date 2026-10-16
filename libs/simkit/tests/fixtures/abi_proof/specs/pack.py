"""ABI proof (spec §05 exit test): one kernel emits three record types, creates rows and ids,
schedules timers, sends requests and rejects; a shard answers."""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, dist
from neorisk_simkit.spec.types import i32, opt, ref

from . import kernels as k

PACK = "abi_proof"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Config:
    provers: int = 30
    ticks: int = 12


def define(p: Pack, cfg: Config) -> None:
    prover = p.table("prover", key="prover_id", mutable=True, cols={
        "n": i32(), "last_box": opt(ref("box"))})
    p.table("box", key="box_id", mutable=True, child_of="prover", cols={"w": i32()})
    p.ids("tok")
    p.owner("prover", table=prover, max_live=cfg.provers)
    p.population(prover, n=cfg.provers, initial=1.0)
    sink = p.shard("sink", key="sink", n=2, items=None, state={})
    put = p.request("put", frm="prover", to=sink, payload={"w": i32()},
                    response_payload={"w": i32()}, responses=("ok",),
                    latency=dist.constant(ms=50))
    p.event("e_alpha", owner="prover", cols={
        "prover_id": ref("prover"), "tok_id": ref("tok"), "k": i32()})
    p.event("e_beta", owner="prover", cols={
        "prover_id": ref("prover"), "box_id": ref("box"), "w": i32()})
    p.event("e_gamma", owner="prover", cols={
        "prover_id": ref("prover"), "k": i32(), "note": opt(i32())})
    p.event("sunk", shard="sink", cols={"w": i32()})
    p.process("prove", owner="prover", kernel=k.prove, config=cfg,
              start=p.on_created("prover"), requests={"put": put},
              on_response={("put", "ok"): k.R_OK}, commands=k.COMMANDS)
    p.process("sink_desk", shard=sink, kernel=k.sink_desk, on_request={"put": k.C_PUT})
