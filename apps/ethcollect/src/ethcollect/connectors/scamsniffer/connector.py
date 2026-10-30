"""ScamSniffer's open phishing address list (published with a 7-day delay, GPL-3.0).

`blacklist/all.json` holds the full address list (`address.json` is a smaller subset);
`blacklist/combined.json` maps phishing domains to the addresses their drainers paid out to.
"""

import json

from ethcollect import tables
from ethcollect.connectors.github import raw_file

KIND = "label"
SUMMARY = "ScamSniffer scam-database blacklist all.json + combined.json; phishing, medium trust"
DEFAULT_RATE = 2.0
FILES = ["blacklist/all.json", "blacklist/combined.json"]


def add_arguments(p) -> None:
    pass


def parse(body: bytes) -> list[dict]:
    """A plain address list, all.json's {"address": [...]}, or combined.json's
    {domain: [addresses]} (the domain goes into `source_ref`)."""
    data = json.loads(body)
    if isinstance(data, dict) and "address" in data:
        data = data["address"]
    if isinstance(data, list):
        return tables.label_rows(data, kind="phishing", source="scamsniffer", trust="medium",
                                 ref="scamsniffer blacklist")
    rows = []
    for domain, addresses in data.items():
        rows += tables.label_rows(addresses, kind="phishing", source="scamsniffer",
                                  trust="medium", ref=f"scamsniffer drainer for {domain}")
    return rows


def run(ctx, args) -> None:
    rows = []
    for f in FILES:
        got = parse(raw_file(ctx, "scamsniffer/scam-database", "main", f))
        ctx.note(f, len(got))
        rows += got
    df = tables.frame("labels", rows).unique("address", keep="first", maintain_order=True)
    tables.write(ctx.out, "labels", ctx.source, df)
    ctx.note("labels", df.height)
