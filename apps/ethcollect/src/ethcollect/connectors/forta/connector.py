"""Forta's labelled datasets for Ethereum mainnet: phishing wallets and malicious contracts.

Three CSVs with different headers; each file is recognised by its header, not its name, so a
renamed file still parses. Exploit and heist tags become `hack`, phishing tags `phishing`.
"""

import csv
import io

from ethcollect import tables
from ethcollect.connectors.github import raw_file

KIND = "label"
SUMMARY = "Forta labelled-datasets (Etherscan and Luabase tags); hack or phishing, medium trust"
DEFAULT_RATE = 2.0
FILES = ["labels/1/phishing_scams.csv", "labels/1/malicious_smart_contracts.csv",
         "labels/1/etherscan_malicious_labels.csv"]


def add_arguments(p) -> None:
    pass


def kind_of(tag: str) -> str:
    t = (tag or "").lower()
    if "phish" in t:
        return "phishing"
    if any(w in t for w in ("exploit", "heist", "hack", "attacker", "drainer")):
        return "hack"
    return "scam"


def parse(body: bytes) -> list[dict]:
    reader = csv.DictReader(io.StringIO(body.decode()))
    cols = set(reader.fieldnames or [])
    rows = []

    def add(address, tag):
        nonlocal rows
        rows += tables.label_rows([address], kind=kind_of(tag), source="forta", trust="medium",
                                  ref=tag or None)

    for r in reader:
        if "banned_address" in cols:  # wallet_tag, data_source
            add(r["banned_address"], f"{r.get('wallet_tag')} {r.get('data_source')}")
        elif "contract_address" in cols:  # contract + its creator, tagged by Etherscan label
            tag = f"{r.get('contract_creator_etherscan_label')} {r.get('contract_tag')}"
            add(r["contract_address"], tag)
            add(r.get("contract_creator"), tag)
        elif "address" in cols:  # etherscan_tag, etherscan_labels
            add(r["address"], f"{r.get('etherscan_labels')} {r.get('etherscan_tag')}")
    return rows


def run(ctx, args) -> None:
    rows = []
    for f in FILES:
        got = parse(raw_file(ctx, "forta-network/labelled-datasets", "main", f))
        ctx.note(f, len(got))
        rows += got
    df = tables.frame("labels", rows)
    tables.write(ctx.out, "labels", ctx.source, df)
    ctx.note("labels", df.height)
