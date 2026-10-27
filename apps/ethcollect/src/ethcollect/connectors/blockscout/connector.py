"""Address history from Blockscout's Etherscan-compatible API. No key needed."""

from ethcollect.connectors import history
from ethcollect.connectors.explorer import BLOCKSCOUT, Explorer

KIND = "chain"
SUMMARY = "address history (normal, internal, ERC-20) from eth.blockscout.com; no key"
DEFAULT_RATE = 1.0


def add_arguments(p) -> None:
    history.add_arguments(p)


def run(ctx, args) -> None:
    history.run(ctx, args, Explorer(ctx, BLOCKSCOUT))
