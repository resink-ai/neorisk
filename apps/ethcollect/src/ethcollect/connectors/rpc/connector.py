"""A free public JSON-RPC endpoint (publicnode by default), no key.

Public nodes are not archive nodes: state and log queries reach back only about 10,000 blocks
(publicnode refuses larger log ranges with "Archive requests require a personal token").
So this connector does what needs no history:
  codes   is each address a contract? (eth_getCode at the latest block) -> `addresses`
  blocks  the transactions of the latest N blocks -> `transfers`
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from ethcollect import tables
from ethcollect.context import env

KIND = "chain"
SUMMARY = "public JSON-RPC (no key): contract flags for addresses, or the latest blocks"
DEFAULT_RATE = 2.0
ENDPOINT = "https://ethereum-rpc.publicnode.com"


def add_arguments(p) -> None:
    p.add_argument("--mode", choices=["codes", "blocks"], default="codes")
    p.add_argument("--addresses", type=Path,
                   help="codes mode: file or .parquet of addresses (default: the addresses "
                        "table plus every transfer counterparty)")
    p.add_argument("--blocks", type=int, default=5, help="blocks mode: latest N blocks")
    p.add_argument("--endpoint", default=None, help=f"default $ETH_RPC_URL or {ENDPOINT}")


class Rpc:
    def __init__(self, ctx, url: str):
        self.ctx, self.url = ctx, url

    def batch(self, calls: list[tuple[str, list]], cache: bool) -> list:
        body = json.dumps([{"jsonrpc": "2.0", "id": i, "method": m, "params": p}
                           for i, (m, p) in enumerate(calls)]).encode()

        def fetch() -> bytes:
            return self.ctx.http(self.url, data=body,
                                 headers={"content-type": "application/json"})

        raw = self.ctx.cached(self.url + body.decode(), fetch, ".json") if cache else fetch()
        out = sorted(json.loads(raw), key=lambda r: r["id"])
        return [r.get("result") for r in out]


def known_addresses(root: Path) -> list[str]:
    seen = set(tables.load(root, "addresses")["address"].to_list())
    tr = tables.load(root, "transfers")
    seen |= set(tr["from_address"].drop_nulls().to_list())
    seen |= set(tr["to_address"].drop_nulls().to_list())
    return sorted(seen)


def run(ctx, args) -> None:
    rpc = Rpc(ctx, args.endpoint or env("ETH_RPC_URL") or ENDPOINT)
    if args.mode == "codes":
        if args.addresses:
            from ethcollect.connectors.history import read_addresses

            args.address = []
            todo = read_addresses(args)
        else:
            todo = known_addresses(ctx.out)
        if args.limit:
            todo = todo[: args.limit]
        rows = []
        for i in range(0, len(todo), 50):
            chunk = todo[i:i + 50]
            codes = rpc.batch([("eth_getCode", [a, "latest"]) for a in chunk], cache=True)
            rows += [{"address": a, "is_contract": bool(c and c != "0x"), "first_seen": None,
                      "sample_reason": None, "source": "rpc"} for a, c in zip(chunk, codes)]
        df = tables.frame("addresses", rows)
        tables.write(ctx.out, "addresses", ctx.source, df)
        ctx.note("addresses", df.height)
        ctx.note("contracts", int(df["is_contract"].sum()))
        return
    head = int(rpc.batch([("eth_blockNumber", [])], cache=False)[0], 16)
    numbers = [hex(n) for n in range(head - args.blocks + 1, head + 1)]
    blocks = rpc.batch([("eth_getBlockByNumber", [n, True]) for n in numbers], cache=True)
    rows = []
    for b in blocks:
        ts = datetime.fromtimestamp(int(b["timestamp"], 16), tz=UTC)
        for t in b["transactions"]:
            method = (t.get("input") or "")[:10]
            rows.append({
                "tx_hash": t["hash"], "log_index": -1, "block_number": int(b["number"], 16),
                "ts": ts, "from_address": tables.norm(t["from"]),
                "to_address": tables.norm(t.get("to")), "kind": "external", "asset": "ETH",
                "asset_symbol": "ETH", "amount": int(t["value"], 16) / 1e18, "decimals": 18,
                "usd_approx": None, "method_id": method if len(method) == 10 else None,
                "status": None, "source": "rpc"})
    df = tables.frame("transfers", rows)
    tables.append(ctx.out, "transfers", ctx.source, df)
    ctx.note("blocks", [int(numbers[0], 16), head])
    ctx.note("transfers", df.height)
