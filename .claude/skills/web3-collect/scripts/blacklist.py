"""Collect and check blacklisted (hack / frozen) wallet addresses across chains.

Standard library only, so it runs anywhere with `python3 -I blacklist.py <command> ...`.
Every collecting command writes the same CSV shape:

    source, chain, address, observed_at, ref

Commands
    elliptic   download an Elliptic incident blocklist CSV (one address per line)
    freezes    issuer freeze events: USDT/USDC on Ethereum, USDT on Tron, in a date window
    tayvano    addresses in one incident note of tayvano/lazarus-bluenoroff-research
    check      is this address frozen right now? (USDT/USDC on Ethereum, USDT on Tron)
    overlap    how many addresses of one CSV appear in another

Keys are optional: ETHERSCAN_API_KEY (Ethereum logs via Etherscan instead of keyless
Blockscout) and TRON_PRO_API_KEY (TronGrid without the anonymous rate limit).
"""

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime

UA = "Mozilla/5.0 (X11; Linux x86_64) web3-collect"
ELLIPTIC_BINANCE_2026 = "https://data-cdn.elliptic.co/blocklists/binance-hack-blocklist.csv"
ETH_RPC = "https://ethereum-rpc.publicnode.com"  # latest state only; old logs need a token
BLOCKSCOUT = "https://eth.blockscout.com/api"
ETHERSCAN = "https://api.etherscan.io/v2/api"
TRONGRID = "https://api.trongrid.io"
TRON_USDT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"

# (token, contract, topic0 of the freeze event, where the frozen address sits)
ETH_FREEZE_EVENTS = [
    ("USDT", "0xdac17f958d2ee523a2206206994597c13d831ec7",  # AddedBlackList(address)
     "0x42e160154868087d6bfdc0ca23d96a1c1cfa32f1b72ba9ba27b69b98a0d819dc", "data"),
    ("USDC", "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",  # Blacklisted(address indexed)
     "0xffa4e6181777692565cf28528fc88fd1516ea86b56da075235fa575af6a4b855", "topic1"),
]
# (token, contract, selector of the view that returns the freeze flag)
ETH_FREEZE_VIEWS = [
    ("USDT", "0xdac17f958d2ee523a2206206994597c13d831ec7", "e47d6060"),  # isBlackListed
    ("USDC", "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48", "fe575a87"),  # isBlacklisted
]
COLUMNS = ["source", "chain", "address", "observed_at", "ref"]

B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
PATTERNS = [  # order matters: the first match wins
    ("evm", r"0x[0-9a-fA-F]{40}"),
    ("tron", r"T[1-9A-HJ-NP-Za-km-z]{33}"),
    ("xrp", r"r[1-9A-HJ-NP-Za-km-z]{24,34}"),
    ("bitcoin", r"bc1[02-9ac-hj-np-z]{11,71}|[13][1-9A-HJ-NP-Za-km-z]{25,33}"),
    ("cosmos", r"[a-z]{2,10}1[02-9ac-hj-np-z]{38,58}"),  # dydx1..., osmo1...
    ("near", r"[0-9a-f]{64}|[a-z0-9_-]+\.near"),
    ("solana", r"[1-9A-HJ-NP-Za-km-z]{32,44}"),
]


def guess_chain(address: str) -> str:
    """Chain family from the address format alone. EVM covers every EVM chain (Ethereum,
    Base, Arbitrum, BSC...), so the format cannot say which one."""
    for chain, pattern in PATTERNS:
        if re.fullmatch(pattern, address):
            return chain
    return "unknown"


def norm(address: str) -> str:
    """EVM addresses are case-insensitive, base58 ones are not."""
    return address.lower() if address.startswith("0x") else address


def tron_from_hex(h: str) -> str:
    """0x-prefixed 20-byte (or 41-prefixed 21-byte) hex to a base58check T... address."""
    h = h[2:] if h.startswith("0x") else h
    raw = bytes.fromhex(h if len(h) == 42 else "41" + h[-40:])
    raw += hashlib.sha256(hashlib.sha256(raw).digest()).digest()[:4]
    n, out = int.from_bytes(raw, "big"), ""
    while n:
        n, r = divmod(n, 58)
        out = B58[r] + out
    return out


def tron_to_hex(address: str) -> str:
    n = 0
    for c in address:
        n = n * 58 + B58.index(c)
    raw = n.to_bytes(25, "big")
    if hashlib.sha256(hashlib.sha256(raw[:21]).digest()).digest()[:4] != raw[21:]:
        raise ValueError(f"bad Tron checksum: {address}")
    return raw[1:21].hex()


def http(url: str, body: dict | None = None, headers: dict | None = None, tries: int = 5):
    """GET (or POST JSON) with backoff on 429/5xx. Returns (bytes, response headers)."""
    hdrs = {"user-agent": UA, **(headers or {})}
    data = None
    if body is not None:
        data, hdrs["content-type"] = json.dumps(body).encode(), "application/json"
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data, hdrs), timeout=60) as r:
                return r.read(), r.headers
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or attempt == tries - 1:
                raise SystemExit(f"HTTP {e.code} from {url.split('?')[0]}: {e.read()[:200]!r}")
            time.sleep(2 ** attempt)
    raise AssertionError("unreachable")


def get_json(url: str, **kw):
    return json.loads(http(url, **kw)[0])


def write_rows(rows: list[dict], out: str | None) -> None:
    f = open(out, "w", newline="") if out else sys.stdout
    w = csv.DictWriter(f, COLUMNS)
    w.writeheader()
    w.writerows(rows)
    if out:
        f.close()
        print(f"{len(rows)} rows -> {out}", file=sys.stderr)


def day_ts(day: str) -> int:
    return int(datetime.fromisoformat(day).replace(tzinfo=UTC).timestamp())


def iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, UTC).isoformat(timespec="seconds")


# --- elliptic ---------------------------------------------------------------------------

def cmd_elliptic(args) -> None:
    body, headers = http(args.url)
    stamp = headers.get("last-modified", "")
    rows = [{"source": "elliptic", "chain": guess_chain(a), "address": norm(a),
             "observed_at": "", "ref": f"{args.url} (last-modified {stamp})"}
            for a in dict.fromkeys(line.strip() for line in body.decode().splitlines())
            if a]
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["chain"]] = counts.get(r["chain"], 0) + 1
    print(f"elliptic: {len(rows)} addresses, last-modified {stamp}, {counts}", file=sys.stderr)
    write_rows(rows, args.out)


# --- freezes ----------------------------------------------------------------------------

def eth_explorer(via: str):
    key = os.environ.get("ETHERSCAN_API_KEY", "")
    if via == "etherscan" or (via == "auto" and key):
        if not key:
            raise SystemExit("--via etherscan needs ETHERSCAN_API_KEY")
        return ETHERSCAN, {"chainid": "1", "apikey": key}, 4.5
    # keyless Blockscout allows roughly 10 calls per half hour on bursts; pace gently
    return BLOCKSCOUT, {}, 0.5


def explorer_call(base: str, extra: dict, params: dict) -> dict:
    url = base + "?" + urllib.parse.urlencode({**params, **extra})
    d = get_json(url)
    if str(d.get("status")) != "1" and d.get("message") != "No records found":
        raise SystemExit(f"{base}: {d.get('message')} {str(d.get('result'))[:200]}")
    return d


def eth_block_at(base: str, extra: dict, ts: int, closest: str) -> int:
    d = explorer_call(base, extra, {"module": "block", "action": "getblocknobytime",
                                    "timestamp": ts, "closest": closest})
    r = d["result"]
    return int(r["blockNumber"] if isinstance(r, dict) else r)


def eth_logs(base, extra, rate, contract, topic0, start, end):
    """All logs in [start, end]; a full page (1000) means the range is split and re-read."""
    time.sleep(1 / rate)
    d = explorer_call(base, extra, {"module": "logs", "action": "getLogs", "address": contract,
                                    "topic0": topic0, "fromBlock": start, "toBlock": end})
    logs = d.get("result") or []
    if len(logs) >= 1000 and end > start:
        mid = (start + end) // 2
        return (eth_logs(base, extra, rate, contract, topic0, start, mid)
                + eth_logs(base, extra, rate, contract, topic0, mid + 1, end))
    return logs


def freezes_eth(args) -> list[dict]:
    base, extra, rate = eth_explorer(args.via)
    start = eth_block_at(base, extra, day_ts(args.since), "after")
    end = eth_block_at(base, extra, day_ts(args.until), "before")
    print(f"ethereum blocks {start}..{end} via {base}", file=sys.stderr)
    rows = []
    for token, contract, topic0, where in ETH_FREEZE_EVENTS:
        logs = eth_logs(base, extra, rate, contract, topic0, start, end)
        for lg in logs:
            word = lg["data"] if where == "data" else lg["topics"][1]
            rows.append({"source": f"{token.lower()}-freeze", "chain": "ethereum",
                         "address": "0x" + word[-40:].lower(),
                         "observed_at": iso(int(lg["timeStamp"], 0)),
                         "ref": lg["transactionHash"]})
        print(f"  {token}: {len(logs)} freezes", file=sys.stderr)
    return rows


def freezes_tron(args) -> list[dict]:
    headers = {"TRON-PRO-API-KEY": os.environ["TRON_PRO_API_KEY"]} \
        if os.environ.get("TRON_PRO_API_KEY") else {}
    params = {"event_name": "AddedBlackList", "limit": 200,
              "min_block_timestamp": day_ts(args.since) * 1000,
              "max_block_timestamp": day_ts(args.until) * 1000,
              "order_by": "block_timestamp,asc"}
    url = f"{TRONGRID}/v1/contracts/{TRON_USDT}/events?" + urllib.parse.urlencode(params)
    rows = []
    while url:
        d = get_json(url, headers=headers)
        if not d.get("success", True):
            raise SystemExit(f"trongrid: {d.get('error')}")
        for e in d.get("data", []):
            rows.append({"source": "usdt-freeze", "chain": "tron",
                         "address": tron_from_hex(e["result"]["_user"]),
                         "observed_at": iso(e["block_timestamp"] // 1000),
                         "ref": e["transaction_id"]})
        url = (d.get("meta") or {}).get("links", {}).get("next")
        time.sleep(0.5 if headers else 1.5)
    print(f"tron USDT: {len(rows)} freezes", file=sys.stderr)
    return rows


def cmd_freezes(args) -> None:
    rows = []
    if args.chain in ("eth", "all"):
        rows += freezes_eth(args)
    if args.chain in ("tron", "all"):
        rows += freezes_tron(args)
    write_rows(rows, args.out)


# --- tayvano ----------------------------------------------------------------------------

def cmd_tayvano(args) -> None:
    url = f"https://raw.githubusercontent.com/tayvano/lazarus-bluenoroff-research/main/{args.file}"
    text = http(url)[0].decode()
    rows, seen, heading = [], set(), ""
    any_address = re.compile(r"0x[0-9a-fA-F]{40}|\b[1-9A-HJ-NP-Za-km-z]{25,44}\b"
                             r"|\bbc1[02-9ac-hj-np-z]{11,71}\b")
    for line in text.splitlines():
        if line.startswith("#"):
            heading = line.lstrip("# ").strip()
            continue
        for m in any_address.finditer(line):
            a, chain = m.group(0), guess_chain(m.group(0))
            if chain == "unknown" or (a, chain) in seen:
                continue
            seen.add((a, chain))
            # keep the section and line so victim / service addresses can be filtered by eye
            rows.append({"source": "tayvano", "chain": chain, "address": norm(a),
                         "observed_at": "", "ref": f"{args.file} | {heading} | {line.strip()[:160]}"})
    print(f"tayvano {args.file}: {len(rows)} addresses", file=sys.stderr)
    write_rows(rows, args.out)


# --- check ------------------------------------------------------------------------------

def eth_frozen(address: str) -> dict:
    out = {}
    for token, contract, selector in ETH_FREEZE_VIEWS:
        data = "0x" + selector + address[2:].lower().rjust(64, "0")
        d = get_json(ETH_RPC, body={"jsonrpc": "2.0", "id": 1, "method": "eth_call",
                                    "params": [{"to": contract, "data": data}, "latest"]})
        out[token] = int(d["result"], 16) == 1
    return out


def tron_frozen(address: str) -> dict:
    headers = {"TRON-PRO-API-KEY": os.environ["TRON_PRO_API_KEY"]} \
        if os.environ.get("TRON_PRO_API_KEY") else {}
    d = get_json(f"{TRONGRID}/wallet/triggerconstantcontract", headers=headers,
                 body={"owner_address": address, "contract_address": TRON_USDT,
                       "function_selector": "getBlackListStatus(address)",
                       "parameter": tron_to_hex(address).rjust(64, "0"), "visible": True})
    time.sleep(0 if headers else 1.5)
    return {"USDT": int(d["constant_result"][0], 16) == 1}


def cmd_check(args) -> None:
    for a in args.addresses:
        chain = guess_chain(a)
        if chain == "evm":
            print(a, "ethereum", eth_frozen(a))
        elif chain == "tron":
            print(a, "tron", tron_frozen(a))
        else:
            print(a, chain, "no issuer freeze view for this chain")


# --- overlap ----------------------------------------------------------------------------

def read_addresses(path: str) -> set[str]:
    with open(path, newline="") as f:
        first = f.readline()
        f.seek(0)
        if "address" in first.split(","):
            return {norm(r["address"]) for r in csv.DictReader(f) if r["address"]}
        return {norm(line.strip()) for line in f if line.strip()}


def cmd_overlap(args) -> None:
    a, b = read_addresses(args.a), read_addresses(args.b)
    both = a & b
    print(f"{args.a}: {len(a)}  {args.b}: {len(b)}  in both: {len(both)} "
          f"({len(both) / max(len(a), 1):.0%} of the first)")
    for x in sorted(a - b)[: args.show]:
        print("  only in first:", x)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("elliptic", help="download an Elliptic incident blocklist")
    s.add_argument("--url", default=ELLIPTIC_BINANCE_2026)
    s.add_argument("--out")
    s.set_defaults(fn=cmd_elliptic)

    s = sub.add_parser("freezes", help="stablecoin issuer freezes in a date window")
    s.add_argument("--chain", choices=["eth", "tron", "all"], default="all")
    s.add_argument("--since", required=True, help="YYYY-MM-DD (UTC, inclusive)")
    s.add_argument("--until", required=True, help="YYYY-MM-DD (UTC, exclusive)")
    s.add_argument("--via", choices=["auto", "blockscout", "etherscan"], default="auto")
    s.add_argument("--out")
    s.set_defaults(fn=cmd_freezes)

    s = sub.add_parser("tayvano", help="addresses in a tayvano incident note")
    s.add_argument("--file", default="hacks-and-thefts/binance.md")
    s.add_argument("--out")
    s.set_defaults(fn=cmd_tayvano)

    s = sub.add_parser("check", help="current freeze status of addresses")
    s.add_argument("addresses", nargs="+")
    s.set_defaults(fn=cmd_check)

    s = sub.add_parser("overlap", help="addresses shared by two CSVs (or plain lists)")
    s.add_argument("a")
    s.add_argument("b")
    s.add_argument("--show", type=int, default=0, help="print N addresses only in the first")
    s.set_defaults(fn=cmd_overlap)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
