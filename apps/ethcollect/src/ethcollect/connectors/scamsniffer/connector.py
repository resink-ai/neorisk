"""ScamSniffer's open phishing address list (published with a 7-day delay, GPL-3.0)."""

import json

from ethcollect import tables
from ethcollect.connectors.github import raw_file

KIND = "label"
SUMMARY = "ScamSniffer scam-database blacklist/address.json; phishing, medium trust"
DEFAULT_RATE = 2.0


def add_arguments(p) -> None:
    pass


def parse(body: bytes) -> list[dict]:
    return tables.label_rows(json.loads(body), kind="phishing", source="scamsniffer",
                             trust="medium", ref="scamsniffer blacklist")


def run(ctx, args) -> None:
    body = raw_file(ctx, "scamsniffer/scam-database", "main", "blacklist/address.json")
    df = tables.frame("labels", parse(body))
    tables.write(ctx.out, "labels", ctx.source, df)
    ctx.note("labels", df.height)
