"""CryptoScamDB's crowd-reported scam sites and the ETH addresses listed on them.

The public API (api.cryptoscamdb.org) answered 502 on 2026-10-24, so this reads the
`urls.yaml` dump in the project's GitHub repository instead (last pushed 2023).
"""

import yaml

from ethcollect import tables
from ethcollect.connectors.github import raw_file

KIND = "label"
SUMMARY = "CryptoScamDB blacklist urls.yaml, ETH addresses; scam or phishing, low trust"
DEFAULT_RATE = 2.0


def add_arguments(p) -> None:
    pass


def parse(body: bytes) -> list[dict]:
    rows = []
    for entry in yaml.safe_load(body) or []:
        eth = ((entry or {}).get("addresses") or {}).get("ETH") or []
        if not eth:
            continue
        kind = "phishing" if str(entry.get("category", "")).lower() == "phishing" else "scam"
        rows += tables.label_rows(eth, kind=kind, source="cryptoscamdb", trust="low",
                                  ref=entry.get("url") or entry.get("name"))
    return rows


def run(ctx, args) -> None:
    body = raw_file(ctx, "CryptoScamDB/blacklist", "master", "data/urls.yaml")
    df = tables.frame("labels", parse(body))
    tables.write(ctx.out, "labels", ctx.source, df)
    ctx.note("labels", df.height)
