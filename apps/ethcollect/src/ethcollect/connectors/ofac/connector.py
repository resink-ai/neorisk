"""OFAC SDN Ethereum addresses, as extracted nightly by github.com/0xB10C."""

from ethcollect import tables
from ethcollect.connectors.github import raw_file

KIND = "label"
SUMMARY = "OFAC SDN list, ETH addresses (0xB10C nightly extract); sanctioned, high trust"
DEFAULT_RATE = 2.0
REPO, REF, FILE = "0xB10C/ofac-sanctioned-digital-currency-addresses", "lists", (
    "sanctioned_addresses_ETH.txt")


def add_arguments(p) -> None:
    pass


def parse(body: bytes) -> list[dict]:
    lines = [ln.strip() for ln in body.decode().splitlines() if ln.strip()]
    return tables.label_rows(lines, kind="sanctioned", source="ofac", trust="high",
                             ref="OFAC SDN list")


def run(ctx, args) -> None:
    df = tables.frame("labels", parse(raw_file(ctx, REPO, REF, FILE)))
    tables.write(ctx.out, "labels", ctx.source, df)
    ctx.note("labels", df.height)
