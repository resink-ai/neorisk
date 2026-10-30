"""Addresses frozen by stablecoin issuers, read from the tokens' own events.

Tether emits `AddedBlackList(address)` with the address in `data`; Circle emits
`Blacklisted(address indexed)` (USDC, EURC) and Paxos `AddressFrozen(address indexed)`
(USDP, BUSD, PYUSD, PAXG) carry it in topic 1. The freeze date is the event's block time,
so these labels carry a real `observed_at`. Unfreezes are not tracked yet.
"""

from datetime import UTC, date, datetime

from ethcollect import tables
from ethcollect.connectors.explorer import pick

KIND = "label"
SUMMARY = "Stablecoin issuer freezes (USDT, USDC, EURC, Paxos), all time; frozen, high trust"
DEFAULT_RATE = 1.0
# freezes never expire, so without --since the whole history is read (USDT launched 2017-11)
FIRST_FREEZE = date(2017, 11, 1)

EVENTS = [
    ("USDT", "0xdac17f958d2ee523a2206206994597c13d831ec7",
     "0x42e160154868087d6bfdc0ca23d96a1c1cfa32f1b72ba9ba27b69b98a0d819dc", "data"),
    ("USDC", "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
     "0xffa4e6181777692565cf28528fc88fd1516ea86b56da075235fa575af6a4b855", "topic1"),
    ("EURC", "0x1abaea1f7c830bd89acc67ec4af516284b1bc33c",
     "0xffa4e6181777692565cf28528fc88fd1516ea86b56da075235fa575af6a4b855", "topic1"),
    # Paxos tokens emit AddressFrozen(address indexed)
    *[(token, contract, "0x90811a8edd3b3c17eeaefffc17f639cc69145d41a359c9843994dc2538203690",
       "topic1") for token, contract in [
        ("USDP", "0x8e870d67f660d95d5be530380d0ec0bd388289e1"),
        ("BUSD", "0x4fabb145d64652a948d72533023f6e7a623c7c53"),
        ("PYUSD", "0x6c3ea9036406852006290770bedfcaba0e23a0e8"),
        ("PAXG", "0x45804880de22913dafe09f4980848ece6ecbaf78")]],
]


def add_arguments(p) -> None:
    p.add_argument("--via", choices=["auto", "blockscout", "etherscan"], default="auto",
                   help="explorer for getLogs; auto = etherscan if ETHERSCAN_API_KEY is set, "
                        "else blockscout (keyless, about 10 calls per half hour)")


def frozen_address(log: dict, where: str) -> str | None:
    word = log.get("data") if where == "data" else (log.get("topics") or [None, None])[1]
    return tables.norm("0x" + word[-40:]) if word and len(word) >= 42 else None


def parse(logs: list[dict], token: str, where: str, contract: str = "") -> list[dict]:
    rows = []
    for log in logs:
        if frozen_address(log, where) == contract:  # an issuer freezing its own contract
            continue
        when = datetime.fromtimestamp(int(str(log["timeStamp"]), 0), tz=UTC).date()
        rows += tables.label_rows([frozen_address(log, where)], kind="frozen",
                                  source="stablecoin-freezes", trust="high",
                                  ref=f"{token} freeze tx {log.get('transactionHash')}",
                                  observed_at=when)
    return rows


def run(ctx, args) -> None:
    explorer = pick(ctx, args.via)
    ctx.note("via", explorer.base)
    since = ctx.since if getattr(args, "since", None) else FIRST_FREEZE
    start, end = explorer.block_at(since, "after"), explorer.block_at(ctx.until, "before")
    ctx.note("blocks", [start, end])
    rows = []
    for token, contract, topic0, where in EVENTS:
        got = parse(list(explorer.logs(contract, topic0, start, end)), token, where, contract)
        ctx.note(f"{token}_freezes", len(got))
        rows += got
    # one address frozen twice keeps its earliest freeze
    df = tables.frame("labels", sorted(rows, key=lambda r: r["observed_at"]))
    tables.write(ctx.out, "labels", ctx.source, df)
    ctx.note("labels", df.height)
