"""Population owners whose tied requests reach a shard in different rounds (D61).

The `asker` (declared first, so the lower partition type) pings the desk at 00:59:59.9
(lamport 2); the desk answers at lamport 3, delivered at 01:00, and the asker's response
handler asks at 01:00 with lamport 4. The `peer` asks at 01:00 with lamport 4 too. With 1h
steps both asks are routed together at the start of the 01:00 step; with 6h or 1d steps the
peer's ask is routed in the first round and the asker's only after its response wakes it, so
the desk receives the two tied asks in different rounds."""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, dist
from neorisk_simkit.spec.types import i32

from . import kernels as k

PACK = "latecomer"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Config:
    n: int = 1


def define(p: Pack, cfg: Config) -> None:
    asker = p.table("asker", key="asker_id", mutable=True, cols={"k": i32()})
    peer = p.table("peer", key="peer_id", mutable=True, cols={"k": i32()})
    p.owner("asker", table=asker, max_live=cfg.n)
    p.owner("peer", table=peer, max_live=cfg.n)
    p.population(asker, n=cfg.n, initial=1.0)
    p.population(peer, n=cfg.n, initial=1.0)
    desk = p.shard("desk", key="desk", n=1, items=None, state={})
    ping = p.request("ping", frm="asker", to=desk, payload={"v": i32()},
                     responses=("pong",), latency=dist.constant(ms=100))
    ask_asker = p.request("ask_asker", frm="asker", to=desk, payload={"v": i32()},
                          responses=("ok",), latency=dist.constant(ms=100))
    ask_peer = p.request("ask_peer", frm="peer", to=desk, payload={"v": i32()},
                         responses=("ok",), latency=dist.constant(ms=100))
    p.event("asked", shard="desk", cols={"v": i32()})
    p.process("asker_main", owner="asker", kernel=k.asker_main, start=p.on_created("asker"),
              requests={"ping": ping, "ask": ask_asker},
              on_response={("ping", "pong"): k.R_PONG, ("ask_asker", "ok"): k.R_OK},
              commands=k.ASKER_COMMANDS)
    p.process("peer_main", owner="peer", kernel=k.peer_main, start=p.on_created("peer"),
              requests={"ask": ask_peer}, on_response={("ask_peer", "ok"): k.R_OK},
              commands=k.PEER_COMMANDS)
    p.process("desk_ping", shard=desk, kernel=k.desk_ping, on_request={"ping": k.C_PINGED})
    p.process("desk_asker", shard=desk, kernel=k.desk_asker,
              on_request={"ask_asker": k.C_ASKED})
    p.process("desk_peer", shard=desk, kernel=k.desk_peer, on_request={"ask_peer": k.C_ASKED})
