"""MyEtherWallet's address darklist: old, hand-reported scam addresses with a date each."""

import json
from datetime import date

from ethcollect import tables
from ethcollect.connectors.github import raw_file

KIND = "label"
SUMMARY = "MyEtherWallet ethereum-lists addresses-darklist.json; scam, low trust"
DEFAULT_RATE = 2.0


def add_arguments(p) -> None:
    pass


def parse(body: bytes) -> list[dict]:
    rows = []
    for item in json.loads(body):
        try:
            seen = date.fromisoformat(str(item.get("date", ""))[:10])
        except ValueError:
            seen = None
        rows += tables.label_rows([item.get("address")], kind="scam", source="mew-darklist",
                                  trust="low", ref=item.get("comment"), observed_at=seen)
    return rows


def run(ctx, args) -> None:
    body = raw_file(ctx, "MyEtherWallet/ethereum-lists", "master",
                    "src/addresses/addresses-darklist.json")
    df = tables.frame("labels", parse(body))
    tables.write(ctx.out, "labels", ctx.source, df)
    ctx.note("labels", df.height)
