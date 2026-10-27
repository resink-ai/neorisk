"""eth-labels: a public copy of Etherscan's account labels (github.com/dawsbot/eth-labels).

Most of its ~113k mainnet rows are neither risky nor services (genesis, charity, token
contracts) and are skipped. What is kept: sanctions and exploit tags as risk labels, and
exchanges, bridges, mixers and DEXes as service labels the model sees as counterparty types.
"""

import csv
import io

from ethcollect import tables
from ethcollect.connectors.github import raw_file

KIND = "label"
SUMMARY = "eth-labels accounts.csv (Etherscan labels); sanctions, exploits and services"
DEFAULT_RATE = 2.0

EXCHANGES = {
    "binance", "coinbase", "kraken", "okx", "bitget", "bybit", "kucoin", "gate-io", "htx",
    "huobi", "bitfinex", "gemini", "crypto-com", "upbit", "mexc", "poloniex", "bittrex",
    "deribit", "bilaxy", "bitstamp", "bithumb", "robinhood", "bitmart", "coinone", "hotbit",
}
BRIDGES = {"bridge", "allbridge", "debridge", "hop-protocol", "across-protocol", "stargate"}
MIXERS = {"tornado-cash", "mixer", "ethereum-mixer"}
DEXES = {"dex", "uniswap", "sushiswap", "balancer", "curve-finance", "pancakeswap", "1inch",
         "0x-protocol", "bancor"}


def add_arguments(p) -> None:
    pass


def classify(label: str, name_tag: str) -> tuple[str, str] | None:
    """(label_kind, trust) for an eth-labels row, or None to skip it."""
    lab, tag = label.lower(), (name_tag or "").lower()
    if lab.startswith("ofac-sanction"):
        return "sanctioned", "high"
    if "phish" in lab or "fake_phishing" in tag:
        return "phishing", "medium"
    if lab.endswith("exploit") or lab in {"heist", "exploit", "phish-hack"} or "exploiter" in tag:
        return "hack", "medium"
    if lab in MIXERS:
        return "mixer", "medium"
    if lab in EXCHANGES or lab.endswith("-exchange"):
        return "exchange", "medium"
    if lab in BRIDGES or (lab.endswith("-bridge") and lab != "bridged-token"):
        return "bridge", "medium"
    if lab in DEXES:
        return "dex", "medium"
    return None


def parse(body: bytes) -> list[dict]:
    rows = []
    for r in csv.DictReader(io.StringIO(body.decode())):
        if str(r.get("chainId")) != "1":
            continue
        got = classify(r.get("label", ""), r.get("nameTag", ""))
        if got:
            kind, trust = got
            rows += tables.label_rows([r["address"]], kind=kind, source="eth-labels",
                                      trust=trust, ref=f"{r['label']}: {r.get('nameTag')}")
    return rows


def run(ctx, args) -> None:
    body = raw_file(ctx, "dawsbot/eth-labels", "v1", "data/csv/accounts.csv")
    df = tables.frame("labels", parse(body))
    tables.write(ctx.out, "labels", ctx.source, df)
    ctx.note("labels", df.height)
    ctx.note("by_kind", dict(df.group_by("label_kind").len().iter_rows()))
