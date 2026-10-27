"""A client for Etherscan-compatible explorer APIs (Etherscan V2, Blockscout).

Both speak `?module=...&action=...` and answer `{"status", "message", "result"}`. Blockscout
needs no key; Etherscan V2 needs `apikey` and `chainid`. Responses go through the raw cache,
keyed without the API key.
"""

from __future__ import annotations

import json
import zlib
from datetime import UTC, date, datetime

from ethcollect.context import Context, FetchError, env
from ethcollect.tables import STABLECOINS, norm

ETHERSCAN = "https://api.etherscan.io/v2/api"
BLOCKSCOUT = "https://eth.blockscout.com/api"
NO_RESULTS = ("no transactions found", "no records found", "no logs found", "no token transfers")


def history_source(choice: str = "auto") -> str:
    """`auto` means etherscan when ETHERSCAN_API_KEY is set, else blockscout."""
    if choice != "auto":
        return choice
    return "etherscan" if env("ETHERSCAN_API_KEY") else "blockscout"


def pick(ctx: Context, choice: str = "auto") -> Explorer:
    if history_source(choice) == "etherscan":
        key = env("ETHERSCAN_API_KEY")
        if not key:
            raise SystemExit("ETHERSCAN_API_KEY is not set (free key: https://etherscan.io/myapikey)")
        return Explorer(ctx, ETHERSCAN, apikey=key)
    return Explorer(ctx, BLOCKSCOUT)


class Explorer:
    def __init__(self, ctx: Context, base: str, apikey: str | None = None):
        self.ctx, self.base, self.apikey = ctx, base, apikey

    def call(self, **params) -> list | dict | str:
        if self.base == ETHERSCAN:
            params = {"chainid": 1, **params, "apikey": self.apikey}
        body = json.loads(self.ctx.get(self.base, params=params, suffix=".json"))
        result = body.get("result")
        if str(body.get("status")) == "0" and not isinstance(result, list):
            msg = f"{body.get('message')}: {result}"
            if any(m in msg.lower() for m in NO_RESULTS):
                return []
            self.ctx.forget(self.base, params, ".json")
            raise FetchError(msg)
        return result if result is not None else []

    def block_at(self, day: date, closest: str = "before") -> int:
        ts = int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp())
        r = self.call(module="block", action="getblocknobytime", timestamp=ts, closest=closest)
        if isinstance(r, dict):  # blockscout answers {"blockNumber": "..."}
            r = r.get("blockNumber")
        return int(r)

    # -- account history -------------------------------------------------------------------

    def history(self, address: str, start: int, end: int, per_kind: int) -> list[dict]:
        """The latest `per_kind` normal, internal and ERC-20 transfers of one address."""
        rows: list[dict] = []
        for action, parse in (("txlist", _external), ("txlistinternal", _internal),
                              ("tokentx", _erc20)):
            got = self.call(module="account", action=action, address=address, startblock=start,
                            endblock=end, page=1, offset=per_kind, sort="desc")
            for i, item in enumerate(got if isinstance(got, list) else []):
                row = parse(item, i)
                if row:
                    rows.append(row)
        return rows

    def logs(self, address: str, topic0: str, start: int, end: int, step: int = 1_000_000):
        """All logs of one event between two blocks, walking the range in steps."""
        lo = start
        while lo <= end:
            hi = min(lo + step - 1, end)
            got = self.call(module="logs", action="getLogs", address=address, topic0=topic0,
                            fromBlock=lo, toBlock=hi)
            if isinstance(got, list) and len(got) >= 1000 and hi > lo:  # page cap hit: split
                yield from self.logs(address, topic0, lo, hi, max(1, (hi - lo + 1) // 4))
            else:
                yield from got or []
            lo = hi + 1


def _ts(x) -> datetime:
    return datetime.fromtimestamp(int(str(x), 0), tz=UTC)


def _base(item: dict, kind: str, log_index: int) -> dict:
    return {
        "tx_hash": (item.get("hash") or item.get("transactionHash") or "").lower(),
        "log_index": log_index,
        "block_number": int(item["blockNumber"]),
        "ts": _ts(item["timeStamp"]),
        "from_address": norm(item.get("from")),
        "to_address": norm(item.get("to")) or norm(item.get("contractAddress")),
        "kind": kind,
        "status": 0 if str(item.get("isError", "0")) == "1" else 1,
    }


def _external(item: dict, _i: int) -> dict:
    row = _base(item, "external", -1)
    method = item.get("methodId") or (item.get("input") or "")[:10]
    return {**row, "asset": "ETH", "asset_symbol": "ETH", "decimals": 18,
            "amount": int(item.get("value") or 0) / 1e18, "usd_approx": None,
            "method_id": method if method and method != "0x" else None}


def _internal(item: dict, i: int) -> dict:
    """Blockscout gives a numeric `index`; Etherscan a `traceId` such as "0_1_2", hashed so
    that "1_0" and "10" stay distinct (the index is part of the transfers key)."""
    index, trace = str(item.get("index") or ""), str(item.get("traceId") or "")
    if index.isdigit():
        idx = int(index)
    elif trace:
        idx = zlib.crc32(trace.encode()) & 0x7FFFFFFF
    else:
        idx = i
    row = _base(item, "internal", idx)
    return {**row, "asset": "ETH", "asset_symbol": "ETH", "decimals": 18,
            "amount": int(item.get("value") or 0) / 1e18, "usd_approx": None, "method_id": None}


def _erc20(item: dict, i: int) -> dict:
    row = _base(item, "erc20", int(item.get("logIndex") or i))
    token = norm(item.get("contractAddress"))
    row["to_address"] = norm(item.get("to"))
    dec = int(item["tokenDecimal"]) if str(item.get("tokenDecimal") or "").isdigit() else None
    raw = int(item.get("value") or 0)
    amount = raw / 10**dec if dec is not None else float(raw)
    return {**row, "asset": token, "asset_symbol": item.get("tokenSymbol"), "decimals": dec,
            "amount": amount, "usd_approx": amount if token in STABLECOINS and dec else None,
            "method_id": None}
