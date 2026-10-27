"""The connector registry. One entry per `--source`; each module lives in its own folder.

A connector module exposes:
    KIND         "chain" (writes transfers/addresses) or "label" (writes labels)
    SUMMARY      one line for `--help` and `status`
    add_arguments(parser)   its own options, beyond the shared ones
    run(ctx, args)          fetch through ctx (cached), parse, write tables
"""

from __future__ import annotations

import importlib
from types import ModuleType

SOURCES = {
    # chain
    "aws-public": "aws_public",
    "blockscout": "blockscout",
    "etherscan": "etherscan",
    "rpc": "rpc",
    # labels
    "ofac": "ofac",
    "stablecoin-freezes": "stablecoin_freezes",
    "forta": "forta",
    "eth-labels": "eth_labels",
    "scamsniffer": "scamsniffer",
    "mew-darklist": "mew_darklist",
    "cryptoscamdb": "cryptoscamdb",
    "huione": "huione",
}


def load(source: str) -> ModuleType:
    return importlib.import_module(f"ethcollect.connectors.{SOURCES[source]}.connector")


def label_sources() -> list[str]:
    return [s for s in SOURCES if load(s).KIND == "label"]
