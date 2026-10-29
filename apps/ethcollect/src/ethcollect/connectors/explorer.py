"""A client for Etherscan-compatible explorer APIs (Etherscan V2, Blockscout).

Both speak `?module=...&action=...` and answer `{"status", "message", "result"}`. Blockscout
needs no key; Etherscan V2 needs `apikey` and `chainid`. Responses go through the raw cache,
keyed without the API key.

Etherscan calls are paced at ETHERSCAN_RATE calls per second (your plan's limit; default 2,
under the free tier's 3) unless `--rate` is given, and its per-second rate-limit answers are
retried with back-off.
"""

from __future__ import annotations

import json
import time
import zlib
from datetime import UTC, date, datetime

from ethcollect.context import Context, FetchError, env
from ethcollect.tables import STABLECOINS, norm

ETHERSCAN = "https://api.etherscan.io/v2/api"
BLOCKSCOUT = "https://eth.blockscout.com/api"
NO_RESULTS = ("no transactions found", "no records found", "no logs found", "no token transfers")
ETHERSCAN_RATE = 2.0  # calls per second when ETHERSCAN_RATE is unset
RATE_TRIES = 6  # tries per call while Etherscan answers "Max calls per sec rate limit reached"
DAILY_LIMIT = ("daily", "per day", "day limit")
LATEST_BLOCK = 99_999_999


def etherscan_rate() -> float:
    """Calls per second for Etherscan: $ETHERSCAN_RATE (e.g. 1 on a shared key, 5 on a paid
    plan), else ETHERSCAN_RATE."""
    v = env("ETHERSCAN_RATE")
    try:
        rate = float(v) if v else ETHERSCAN_RATE
    except ValueError:
        raise SystemExit(f"ETHERSCAN_RATE must be a number of calls per second, not {v!r}")
    if rate <= 0:
        raise SystemExit(f"ETHERSCAN_RATE must be above 0, not {v!r}")
    return rate


def per_second_limit(msg: str) -> bool:
    """Etherscan's per-second limit, which a short wait clears (the daily one does not)."""
    m = msg.lower()
    return "rate limit" in m and "daily" not in m


class DailyLimit(FetchError):
    """The key's calls for the day are used up; waiting seconds will not help."""


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
        if base == ETHERSCAN and not ctx.rate_given:
            ctx.rate = etherscan_rate()

    def call(self, *, fresh: bool = False, **params) -> list | dict | str:
        """`fresh`: skip the cache, for answers that change (balances)."""
        if self.base == ETHERSCAN:
            params = {"chainid": 1, **params, "apikey": self.apikey}
        for attempt in range(RATE_TRIES):
            if fresh:
                self.ctx.forget(self.base, params, ".json")
            body = json.loads(self.ctx.get(self.base, params=params, suffix=".json"))
            result = body.get("result")
            if str(body.get("status")) != "0" or isinstance(result, list):
                return result if result is not None else []
            msg = f"{body.get('message')}: {result}"
            if any(m in msg.lower() for m in NO_RESULTS):
                return []
            self.ctx.forget(self.base, params, ".json")
            if any(m in msg.lower() for m in DAILY_LIMIT):
                raise DailyLimit(msg)
            if not per_second_limit(msg) or attempt == RATE_TRIES - 1:
                raise FetchError(msg)
            self.ctx.count("retries")
            time.sleep(2**attempt)  # 1, 2, 4, 8, 16 s
        raise AssertionError("unreachable")

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

    def first_funding(self, address: str, look: int = 10) -> tuple[dict | None, list[dict]]:
        """Who first sent `address` ETH: the oldest successful incoming normal or internal
        transfer with value among the oldest `look` of each. Returns it (or None) and every
        transfer row read."""
        rows: list[dict] = []
        for action, parse in (("txlist", _external), ("txlistinternal", _internal)):
            got = self.call(module="account", action=action, address=address, startblock=0,
                            endblock=LATEST_BLOCK, page=1, offset=look, sort="asc")
            for i, item in enumerate(got if isinstance(got, list) else []):
                row = parse(item, i)
                if row:
                    rows.append(row)
        funded = [r for r in rows
                  if r["to_address"] == address and r["amount"] > 0 and r["status"] == 1]
        return min(funded, key=lambda r: r["block_number"], default=None), rows

    def nft_history(self, address: str, start: int, end: int, per_kind: int) -> list[dict]:
        """The latest `per_kind` ERC-721 and ERC-1155 transfers of one address."""
        rows: list[dict] = []
        for action, standard in (("tokennfttx", "erc721"), ("token1155tx", "erc1155")):
            got = self.call(module="account", action=action, address=address, startblock=start,
                            endblock=end, page=1, offset=per_kind, sort="desc")
            rows += [_nft(item, standard) for item in (got if isinstance(got, list) else [])]
        return rows

    def balances(self, addresses: list[str]) -> list[tuple[str, float]]:
        """Current ETH balances, up to 20 addresses per call; never cached."""
        got = self.call(fresh=True, module="account", action="balancemulti",
                        address=",".join(addresses), tag="latest")
        return [(norm(r["account"]), int(r["balance"]) / 1e18)
                for r in (got if isinstance(got, list) else [])]

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


def _nft(item: dict, standard: str) -> dict:
    value = str(item.get("tokenValue") or "")
    return {
        "tx_hash": (item.get("hash") or "").lower(),
        "block_number": int(item["blockNumber"]),
        "ts": _ts(item["timeStamp"]),
        "from_address": norm(item.get("from")),
        "to_address": norm(item.get("to")),
        "standard": standard,
        "contract": norm(item.get("contractAddress")),
        "token_name": item.get("tokenName"),
        "token_id": str(item.get("tokenID") or ""),
        "amount": float(value) if value.isdigit() else 1.0,
    }


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
