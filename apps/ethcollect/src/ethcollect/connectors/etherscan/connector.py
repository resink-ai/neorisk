"""Address history from the Etherscan API V2. Needs ETHERSCAN_API_KEY (free tier is enough)."""

from ethcollect.connectors import history
from ethcollect.connectors.explorer import ETHERSCAN, Explorer
from ethcollect.context import env

KIND = "chain"
SUMMARY = "address history (normal, internal, ERC-20) from Etherscan V2; needs ETHERSCAN_API_KEY"
DEFAULT_RATE = 2.0  # replaced by $ETHERSCAN_RATE unless --rate is given (see explorer.py)


def add_arguments(p) -> None:
    history.add_arguments(p)


def run(ctx, args) -> None:
    key = env("ETHERSCAN_API_KEY")
    if not key:
        raise SystemExit(
            "ETHERSCAN_API_KEY is not set. Get a free key at https://etherscan.io/myapikey, "
            "or use --source blockscout, which needs none."
        )
    history.run(ctx, args, Explorer(ctx, ETHERSCAN, apikey=key))
